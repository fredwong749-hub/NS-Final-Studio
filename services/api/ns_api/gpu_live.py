"""GPU 实时详情（GPUVIEW 2026-11-01；项目方原话：“实时展示gpu显卡做什么任务细节”）。

GET /api/gpu/live   每张卡（gpu33·卡0/1/3 + 坏卡 gpu33·卡2 + gpu36·卡0/1/2）：
    谁在做什么（comfy_tag 标签或推断，人话）、进度（采样第 x/y 步 / 已跑 / 预计还要）、队列长度 + 后面 2–3 个、
    利用率 / 显存 / 温度 / 功耗与功耗墙（gpu36 温控守护压到 200 W 时标出）、最近一张出图（缩略图，可放大）、
    非 ComfyUI 的 GPU 进程（训练 / 其他用户）、心跳任务（TTS 等，docs/GPU_STATUS.md）。
GET /api/gpu/thumb?lane=gpu36:1&filename=…&subfolder=…&type=output[&w=…]   ComfyUI 出图的缩略图（服务端缩放、缓存）
    UIRSI r38：先在本镜 takes.json 里找登记过的同名一版（笔记本文件，不经隧道）；没有才经隧道取（8 s 超时，失败 1 分钟内不重试，404 带中文原因）

数据（全部只读）：
  · ComfyUI（每条道，本机隧道）：/queue 每 4 s，/history?max_items=20 每 12 s；标签读 extra_data.ns_tag（ns_agent.comfy_tag）。
  · nvidia-smi：每台机器一条常驻 ssh（BatchMode），远端 bash 循环每 5 s 打一段只读快照（nvidia-smi 查询、进程表、
    ComfyUI 日志末尾的采样进度、gpu36 温控守护状态文件、远端心跳）；远端循环最多 30 分钟，本地断了就重连。
    绝不执行 nvidia-smi -pl 或任何改状态的命令。
  · 心跳：本机 data/gpu_heartbeats/*.json + gpu36 /root/work/fredw/gpu_heartbeats/*.json。
采集线程在第一次请求时启动，2 分钟没人看就停（ssh 也关）。接口只读缓存，不在请求里连远端。
"""
from __future__ import annotations

import io
import json
import os
import re
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ns_agent import comfy_tag as CT

router = APIRouter(tags=["gpu-live"])
REPO = Path(__file__).resolve().parents[3]
QUEUE_EVERY_S = 4.0
HISTORY_EVERY_S = 30.0
SSH_PERIOD_S = 5
SSH_MAX_S = 1800
IDLE_STOP_S = 120
FAULTY = {("gpu33", 2): "坏卡 · 不用"}
HOSTS = ("gpu33", "gpu36")
GPU_COUNT = {"gpu33": 4, "gpu36": 3}
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.Lock()
_st: dict = {"seen": 0.0, "thread": None, "lanes": {}, "hosts": {}, "ssh": {}, "thumbs": {}}

# ---------------------------------------------------------------- 远端只读快照脚本（bash -s，stdin 传入）
REMOTE = r"""
end=$((SECONDS+__MAX__))
while [ $SECONDS -lt $end ]; do
  echo "##BEGIN $(date +%s)"
  echo "##SMI"
  timeout 8 nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,power.default_limit --format=csv,noheader,nounits 2>&1
  A=$(timeout 8 nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null)
  echo "##APPS"; echo "$A"
  echo "##PS"
  for p in $(echo "$A" | cut -d, -f2 | tr -d ' '); do
    [ -r /proc/$p/cmdline ] || continue
    printf '%s|%s|%s|%s\n' "$p" "$(ps -o user= -p $p 2>/dev/null | tr -d ' ')" "$(ps -o etimes= -p $p 2>/dev/null | tr -d ' ')" "$(tr '\0' ' ' </proc/$p/cmdline 2>/dev/null | cut -c1-240)"
  done
  echo "##LOG"
  for p in $(echo "$A" | cut -d, -f2 | tr -d ' '); do
    c=$(tr '\0' ' ' </proc/$p/cmdline 2>/dev/null)
    case "$c" in *main.py*--port*) ;; *) continue ;; esac
    port=$(echo "$c" | grep -o -- '--port [0-9]*' | head -1 | cut -d' ' -f2)
    f=$(readlink /proc/$p/fd/2 2>/dev/null)
    if [ -f "$f" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$f") ))
      ln=$(tail -c 4000 "$f" | tr '\r' '\n' | grep -aE '[0-9]+/[0-9]+ \[' | tail -1 | cut -c1-160)
      echo "$port|$age|$ln"
    else
      echo "$port|-1|"
    fi
  done
  echo "##GUARD"; cat /var/lib/gpu36-dimm-guard/state 2>/dev/null
  echo "##HB"
  for f in __HBDIR__/*.json; do [ -f "$f" ] && { tr -d '\n' < "$f"; echo; }; done
  echo "##END"
  sleep __PERIOD__
done
"""


def _remote_script(host: str) -> str:
    hb = CT.REMOTE_HEARTBEAT_DIR.get(host, "/nonexistent_ns_heartbeats")
    return REMOTE.replace("__MAX__", str(SSH_MAX_S)).replace("__PERIOD__", str(SSH_PERIOD_S)).replace("__HBDIR__", hb)


def _f(x):
    x = (x or "").strip()
    if x in ("", "[N/A]", "N/A", "[Not Supported]"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def parse_block(text: str) -> dict:
    """一段远端快照 → {now, gpus{idx: {...}}, procs{idx: [...]}, comfy_log{port: {...}}, guard, heartbeats}"""
    sec: dict[str, list[str]] = {}
    cur = None
    now = None
    for ln in text.splitlines():
        if ln.startswith("##BEGIN"):
            try:
                now = float(ln.split()[1])
            except (IndexError, ValueError):
                pass
            continue
        if ln.startswith("##"):
            cur = ln[2:].strip()
            sec[cur] = []
            continue
        if cur:
            sec[cur].append(ln)
    from ns_agent.gpu_smi import parse_query  # 与 tools/monitor/server.py 共用解析
    gpus = {}
    uuid2idx = {}
    for row in parse_query(sec.get("SMI", []), ("index", "uuid", "name", "util", "mem_used", "mem_total", "temp",
                                                 "power", "power_limit", "power_default")):
        try:
            i = int(row["index"])
        except (TypeError, ValueError):
            continue
        uuid2idx[row["uuid"]] = i
        gpus[i] = {"name": (row["name"] or "").replace("NVIDIA GeForce ", ""), "uuid": row["uuid"], "util": _f(row["util"]),
                   "vram_used_mb": _f(row["mem_used"]), "vram_total_mb": _f(row["mem_total"]), "temp_c": _f(row["temp"]),
                   "power_w": _f(row["power"]), "power_limit_w": _f(row["power_limit"]),
                   "power_default_w": _f(row["power_default"])}
    pid_gpu, pid_mem = {}, {}
    for ln in sec.get("APPS", []):
        p = [x.strip() for x in ln.split(",")]
        if len(p) == 3 and p[1].isdigit():
            pid_gpu[p[1]] = uuid2idx.get(p[0])
            pid_mem[p[1]] = _f(p[2])
    procs: dict[int, list] = {}
    for ln in sec.get("PS", []):
        p = ln.split("|", 3)
        if len(p) < 4:
            continue
        pid, user, et, cmd = p
        g = pid_gpu.get(pid)
        if g is None:
            continue
        port = re.search(r"--port\s+(\d+)", cmd)
        procs.setdefault(g, []).append({"pid": int(pid), "user": user, "elapsed_s": int(et) if et.isdigit() else None,
                                        "cmd": cmd.strip(), "vram_mb": pid_mem.get(pid),
                                        "comfy_port": int(port.group(1)) if port and "main.py" in cmd else None})
    logs = {}
    for ln in sec.get("LOG", []):
        p = ln.split("|", 2)
        if len(p) == 3 and p[0].isdigit():
            logs[int(p[0])] = {"age_s": int(p[1]) if p[1].lstrip("-").isdigit() else None, **_tqdm(p[2])}
    guard = None
    gl = sec.get("GUARD") or []
    if gl:
        lv = next((ln.split()[1] for ln in gl if ln.startswith("level ")), None)
        sets = {}
        for ln in gl:
            q = ln.split()
            if q[:1] == ["gpu"] and len(q) >= 4:
                sets[q[1]] = {"default_w": _f(q[2]), "set_w": _f(q[3])}
        guard = {"level": int(lv) if lv and lv.isdigit() else None, "gpus": sets}
    hbs = []
    for ln in sec.get("HB", []):
        try:
            hbs.append(json.loads(ln))
        except ValueError:
            pass
    return {"now": now, "gpus": gpus, "procs": procs, "comfy_log": logs, "guard": guard, "heartbeats": hbs}


_TQDM = re.compile(r"(\d+)/(\d+)\s*\[([0-9:]+)<([0-9:?]+)")


def _hms(s: str) -> float | None:
    try:
        parts = [int(x) for x in s.split(":")]
    except ValueError:
        return None
    v = 0
    for x in parts:
        v = v * 60 + x
    return float(v)


def _tqdm(line: str) -> dict:
    m = _TQDM.search(line or "")
    if not m:
        return {}
    return {"step": int(m.group(1)), "steps": int(m.group(2)), "step_elapsed_s": _hms(m.group(3)),
            "step_left_s": _hms(m.group(4)) if "?" not in m.group(4) else None}


# ---------------------------------------------------------------- ssh 常驻读取
class SshStream:
    def __init__(self, host: str):
        self.host = host
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.stop = False
        self.last: dict | None = None
        self.at = 0.0
        self.err = ""

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop = False
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"gpu-live-ssh-{self.host}")
        self.thread.start()

    def close(self):
        self.stop = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()       # 只关本机 ssh 客户端；远端循环随会话断开结束（最多 30 分钟自停）
            except OSError:
                pass

    def _run(self):
        while not self.stop:
            try:
                self.proc = subprocess.Popen(
                    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=20",
                     self.host, "bash", "-s"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=NO_WIN)
                # 二进制写入：Windows 文本模式会把 LF 换成 CRLF，远端 bash 读不懂
                self.proc.stdin.write(_remote_script(self.host).replace(chr(13) + chr(10), chr(10)).encode("utf-8"))
                self.proc.stdin.close()
                buf: list[str] = []
                for raw in self.proc.stdout:
                    ln = raw.decode("utf-8", "replace").rstrip(chr(13) + chr(10))
                    if self.stop:
                        break
                    ln = ln.rstrip("\n")
                    if ln.startswith("##BEGIN"):
                        buf = [ln]
                    elif ln == "##END":
                        try:
                            snap = parse_block("\n".join(buf))
                            snap["local_at"] = time.time()
                            self.last, self.at, self.err = snap, time.time(), ""
                        except Exception as e:  # noqa: BLE001
                            self.err = f"解析失败：{e!r}"[:200]
                        buf = []
                    else:
                        buf.append(ln)
                rc = self.proc.wait(timeout=10)
                if not self.stop:
                    self.err = f"ssh 断开（rc={rc}）{(self.proc.stderr.read() or b'').decode('utf-8', 'replace')[-200:]}"
            except Exception as e:  # noqa: BLE001
                self.err = f"ssh 失败：{e!r}"[:200]
            if not self.stop:
                time.sleep(10)


# ---------------------------------------------------------------- ComfyUI 道
def _get(url: str, timeout: float = 6.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def _lane_list() -> list[dict]:
    from ns_render import endpoints as EP
    out = []
    for g in EP.gpu_ids():
        try:
            url = EP.url_for_gpu(g)
        except ValueError:
            continue
        srv = EP.server_of(g)
        idx = g if isinstance(g, int) else int(str(g).split(":", 1)[1])
        out.append({"lane": EP.lane_name(g), "gpu": g, "server": srv, "idx": idx, "url": url,
                    "port": int(urllib.parse.urlparse(url).port or 0)})
    return out


def _item(it: list) -> dict:
    num, pid, prompt = it[0], it[1], it[2] if len(it) > 2 else {}
    extra = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
    tag = CT.tag_of(prompt, extra)
    return {"prompt_id": pid, "number": num, "client_id": extra.get("client_id"),
            "created": (extra.get("create_time") or 0) / 1000 or None, "tag": tag, "what": CT.describe(tag)}


def _hist(pid: str, h: dict) -> dict:
    p = h.get("prompt") or []
    extra = p[3] if len(p) > 3 and isinstance(p[3], dict) else {}
    tag = CT.tag_of(p[2] if len(p) > 2 else {}, extra)
    st = h.get("status") or {}
    ts = {m[0]: (m[1] or {}).get("timestamp") for m in st.get("messages") or [] if isinstance(m, list) and len(m) == 2}
    start, end = ts.get("execution_start"), ts.get("execution_success") or ts.get("execution_error") or ts.get("execution_interrupted")
    imgs, vids = [], []
    for node in (h.get("outputs") or {}).values():
        for k in ("images", "gifs", "videos", "video"):
            for f in node.get(k) or []:
                if not isinstance(f, dict) or not f.get("filename"):
                    continue
                rec = {"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}
                (imgs if re.search(r"\.(png|jpe?g|webp)$", f["filename"], re.I) else vids).append(rec)
    err = None
    if st.get("status_str") == "error":
        em = next((m[1] for m in st.get("messages") or [] if isinstance(m, list) and m and m[0] == "execution_error"), {})
        err = f"{em.get('exception_type', '')}: {em.get('exception_message', '')}".strip(": ")[:400] or "出错"
    return {"prompt_id": pid, "number": p[0] if p else None, "tag": tag, "what": CT.describe(tag),
            "client_id": extra.get("client_id"), "created": (extra.get("create_time") or 0) / 1000 or None,
            "start": start / 1000 if start else None, "end": end / 1000 if end else None,
            "ok": st.get("status_str") == "success", "error": err, "images": imgs, "videos": vids}


def _poll_lane(ln: dict, with_history: bool) -> dict:
    out = {"reachable": False, "at": time.time()}
    try:
        q = _get(ln["url"] + "/queue")
        out["running"] = [_item(it) for it in q.get("queue_running") or []]
        pend = sorted(q.get("queue_pending") or [], key=lambda it: it[0])
        out["pending"] = [_item(it) for it in pend]
        out["reachable"] = True
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:160]
        return out
    if with_history:
        try:
            h = _get(ln["url"] + "/history?max_items=20", timeout=10) or {}
            out["history"] = sorted((_hist(k, v) for k, v in h.items()), key=lambda x: x.get("end") or 0)
        except Exception:  # noqa: BLE001
            pass
    return out


OFFLINE_AFTER_S = 120   # UIAUDIT verify_gpuview_r1 P2：隧道 / ComfyUI 短暂断开不写“离线”，连续连不上超过 2 分钟才算


def merge_poll(prev: dict, r: dict, now: float) -> dict:
    """本轮读数并入上一轮：history 没读就沿用；连不上时记 down_since，2 分钟内沿用上次的队列（标 stale），
    超过 2 分钟才清掉、算离线"""
    r = dict(r)
    if "history" not in r and prev.get("history") is not None:
        r["history"] = prev["history"]
    if r.get("reachable"):
        r["down_since"] = None
        return r
    down = prev.get("down_since") or now
    r["down_since"] = down
    if now - down < OFFLINE_AFTER_S:
        for k in ("running", "pending"):
            if prev.get(k) is not None:
                r[k] = prev[k]
        r["stale"] = True
    return r


def link_state(ln: dict | None, now: float, util: float | None) -> dict | None:
    """连不上的道：{down_s, offline, text}；连得上 → None"""
    if not ln or ln.get("reachable", True):
        return None
    down = now - float(ln.get("down_since") or now)
    if down >= OFFLINE_AFTER_S:
        return {"down_s": round(down), "offline": True, "text": f"ComfyUI 离线（已连不上 {round(down / 60)} 分钟）"}
    busy = (util or 0) >= 5
    return {"down_s": round(down), "offline": False,
            "text": f"暂时连不上（{round(down)} 秒）" + (f" · 卡在忙（利用率 {round(util)}%）" if busy else "")}


def _loop():
    last_hist = 0.0
    lanes = _lane_list()
    while time.time() - _st["seen"] < IDLE_STOP_S:
        t0 = time.time()
        hist = t0 - last_hist >= HISTORY_EVERY_S
        try:
            lanes = _lane_list()
        except Exception:  # noqa: BLE001
            pass
        with ThreadPoolExecutor(max_workers=max(1, len(lanes))) as ex:
            res = list(ex.map(lambda ln: _poll_lane(ln, hist), lanes))
        with _lock:
            for ln, r in zip(lanes, res):
                prev = _st["lanes"].get(ln["lane"], {})
                _st["lanes"][ln["lane"]] = {**ln, **merge_poll(prev, r, time.time())}
        if hist:
            last_hist = t0
        time.sleep(max(0.5, QUEUE_EVERY_S - (time.time() - t0)))
    with _lock:
        _st["thread"] = None
        for s in _st["ssh"].values():
            s.close()


def ensure() -> None:
    """标记有人在看；采集线程 / ssh 没在跑就启动"""
    with _lock:
        _st["seen"] = time.time()
        if _st["thread"] is None:
            t = threading.Thread(target=_loop, daemon=True, name="gpu-live")
            _st["thread"] = t
            t.start()
        for h in HOSTS:
            s = _st["ssh"].get(h)
            if s is None:
                s = _st["ssh"][h] = SshStream(h)
            s.start()


# ---------------------------------------------------------------- 心跳
def _heartbeats(remote: dict[str, list]) -> list[dict]:
    now = time.time()
    out = []
    try:
        files = list(CT.HEARTBEAT_DIR.glob("*.json"))
    except OSError:
        files = []
    recs = []
    for f in files:
        try:
            recs.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    for host, lst in remote.items():
        for r in lst:
            r.setdefault("server", host)
            recs.append(r)
    for r in recs:
        if not isinstance(r, dict):
            continue
        age = now - float(r.get("updated") or 0)
        if age > float(r.get("ttl") or 120) or r.get("state") == "done":
            continue
        r["age_s"] = round(age, 1)
        out.append(r)
    return out


# ---------------------------------------------------------------- 组装
def _median(xs):
    xs = [x for x in xs if x and x > 0]
    return statistics.median(xs) if xs else None


def _sig(t: dict) -> tuple:
    return (t.get("agent"), t.get("kind"), t.get("family"))


# 本项目自己的常驻 GPU 进程（不经 ComfyUI）：命令行片段 → 人话 + 归属。面板写它们“在跑”，不写“训练/其他用户”。
# 新增常驻服务请在这里加一行，或让它写心跳（docs/GPU_STATUS.md §3）。选卡逻辑（pick_lane / PRODUCER）只看 train.lock 和 ComfyUI 队列，不看进程。
KNOWN_PROCS = [
    ("clip_srv.py", "契约打分 · REFLOCK（CLIP）", "REFLOCK"),
    ("bgm_worker.py", "配乐 · BGM10（ACE-Step）", "BGM10"),
    ("score_remote.py", "出图质检 · IMGGEN（ArcFace）", "IMGGEN"),
    ("llama-server", "写作模型（llama-server）", "Qwen"),
]


def known_proc(cmd: str | None) -> dict | None:
    c = cmd or ""
    for pat, label, agent in KNOWN_PROCS:
        if pat in c:
            return {"label": label, "agent": agent}
    return None


def _fmt_proc(p: dict) -> str:
    from ns_api.gpu_monitor import _short  # 复用现有命令简称
    return _short(p.get("cmd") or "") or (p.get("cmd") or "")[:60]


def _thumb_url(lane: str, f: dict, w: int | None = None) -> str:
    q = {"lane": lane, "filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}
    if w:
        q["w"] = str(w)
    return "/api/gpu/thumb?" + urllib.parse.urlencode(q)


def lane_items(ln: dict, skew: float = 0.0) -> dict:
    """一条道的 正在跑 / 排队 / 最近完成（带耗时估计）。skew = 远端时钟 - 本机时钟"""
    now = time.time() + skew
    hist = ln.get("history") or []
    done = [h for h in hist if h.get("start") and h.get("end") and h.get("ok")]
    by_sig: dict[tuple, list] = {}
    for h in done:
        by_sig.setdefault(_sig(h["tag"]), []).append(h["end"] - h["start"])
    lane_med = _median([h["end"] - h["start"] for h in done])

    def est(t):
        return _median(by_sig.get(_sig(t), [])) or None

    last_end = max([h["end"] for h in hist if h.get("end")] or [0])
    run = []
    for it in ln.get("running") or []:
        start = max(it.get("created") or 0, last_end) or None
        el = now - start if start else None
        e = est(it["tag"])
        run.append({**it, "started": start - skew if start else None, "elapsed_s": round(el, 1) if el else None,
                    "typical_s": round(e, 1) if e else None,
                    "eta_s": round(max(0.0, e - el), 1) if e and el is not None else None, "eta_basis": "history" if e else None})
    pend = []
    acc = sum((r.get("eta_s") or 0) for r in run)
    for it in ln.get("pending") or []:
        e = est(it["tag"]) or lane_med
        pend.append({**it, "typical_s": round(e, 1) if e else None, "starts_in_s": round(acc, 1) if e else None})
        acc += e or 0
    return {"running": run, "pending": pend, "recent": hist[-8:][::-1], "queue_eta_s": round(acc, 1) if acc else None}


def snapshot() -> dict:
    ensure()
    with _lock:
        lanes = {k: dict(v) for k, v in _st["lanes"].items()}
        sshs = {h: s for h, s in _st["ssh"].items()}
    hosts = {}
    remote_hb = {}
    for h in HOSTS:
        s = sshs.get(h)
        snap = s.last if s else None
        age = time.time() - s.at if s and s.at else None
        hosts[h] = {"ok": bool(snap) and age is not None and age < 45, "age_s": round(age, 1) if age is not None else None,
                    "err": (s.err if s else "") or None}
        if snap:
            remote_hb[h] = snap.get("heartbeats") or []
            g = snap.get("guard")
            if g and g.get("level") is not None:
                hosts[h]["guard"] = {"level": g["level"], "name": ["正常", "限 200 W", "紧急 100 W"][min(2, max(0, g["level"]))]}
    hbs = _heartbeats(remote_hb)
    cards = []
    lane_by_hw = {(v["server"], v["idx"]): v for v in lanes.values()}
    for h in HOSTS:
        s = sshs.get(h)
        snap = (s.last if s else None) or {}
        skew = (snap.get("now") - snap.get("local_at")) if snap.get("now") and snap.get("local_at") else 0.0
        idxs = sorted(set(snap.get("gpus", {}).keys()) | {v["idx"] for v in lanes.values() if v["server"] == h}
                      | {i for (srv, i) in FAULTY if srv == h})
        if not idxs:
            idxs = list(range(GPU_COUNT.get(h, 0)))
        for i in idxs:
            ln = lane_by_hw.get((h, i))
            hw = (snap.get("gpus") or {}).get(i) or {}
            procs = (snap.get("procs") or {}).get(i) or []
            comfy_port = next((p["comfy_port"] for p in procs if p.get("comfy_port")), None)
            log = (snap.get("comfy_log") or {}).get(comfy_port) if comfy_port else None
            items = lane_items(ln, skew) if ln else {"running": [], "pending": [], "recent": [], "queue_eta_s": None}
            if items["running"] and log and log.get("steps") and (log.get("age_s") is not None and 0 <= log["age_s"] < 40):
                r0 = items["running"][0]
                r0["progress"] = {"step": log["step"], "steps": log["steps"], "step_left_s": log.get("step_left_s"),
                                  "source": "ComfyUI 日志"}
            others = []
            for p in procs:
                if p.get("comfy_port"):
                    continue
                k = known_proc(p.get("cmd"))
                others.append({"pid": p["pid"], "user": p.get("user"), "what": k["label"] if k else _fmt_proc(p),
                               "agent": k["agent"] if k else None, "ours": bool(k), "vram_mb": p.get("vram_mb"),
                               "elapsed_s": p.get("elapsed_s")})
            # 心跳没写卡号（如 REFLOCK 契约打分：卡由服务器端按空闲显存现选）→ 放到同机上跑着该 agent 常驻进程的那张卡
            ours = {o["agent"] for o in others if o.get("ours")}
            mine_hb = [b for b in hbs if b.get("server") == h and (str(b.get("gpu")) == str(i)
                                                                    or (b.get("gpu") is None and b.get("agent") in ours))]
            thumb = None
            for hh in reversed((ln or {}).get("history") or []):
                if hh.get("images"):
                    f = hh["images"][0]
                    thumb = {"src": _thumb_url(ln["lane"], f, 200), "full": _thumb_url(ln["lane"], f),
                             "what": hh["what"], "end": (hh.get("end") or 0) - skew if hh.get("end") else None,
                             "file": f["filename"]}
                    break
            faulty = FAULTY.get((h, i))
            pl, pdef = hw.get("power_limit_w"), hw.get("power_default_w")
            guard = hosts[h].get("guard")
            throttled = bool(pl and pdef and pl < pdef - 1)
            link = link_state(ln, time.time(), hw.get("util"))
            # 谁在做什么（一句话）
            if faulty:
                who, state = faulty, "faulty"
            elif link and link["offline"]:
                who, state = link["text"], "offline"
            elif items["running"]:
                r0 = items["running"][0]
                who, state = r0["what"], "busy"
                if link:
                    who = f"{who}（{link['text']}，显示的是断开前的队列）"
            elif link:
                who, state = link["text"], "busy" if (hw.get("util") or 0) >= 5 else "flaky"
            elif mine_hb:
                who, state = mine_hb[0].get("label") or mine_hb[0].get("agent"), "busy"
            elif others and (hw.get("util") or 0) >= 5:
                o = next((x for x in others if not x.get("ours")), None) or others[0]
                if o.get("ours"):      # 本项目的常驻 GPU 服务（KNOWN_PROCS）：算“在跑”，不是别人 / 训练
                    who, state = o["what"], "busy"
                else:
                    who, state = f"训练/其他用户：{o.get('user') or '?'} · {o['what']}", "external"
            else:
                who, state = "空闲", "idle"
            cards.append({
                "id": f"{h}:{i}", "server": h, "idx": i, "lane": ln["lane"] if ln else None, "faulty": bool(faulty),
                "state": state, "who": who, "link": link,
                "agent": (items["running"][0]["tag"].get("agent") if items["running"] else
                          mine_hb[0].get("agent") if mine_hb else
                          next((o["agent"] for o in others if o.get("ours")), None) if state == "busy" else None),
                "running": items["running"], "pending": items["pending"], "queue_len": len(items["pending"]),
                "queue_eta_s": items["queue_eta_s"], "recent": [{k: r.get(k) for k in ("what", "ok", "error", "end", "start")}
                                                                for r in items["recent"][:5]],
                "heartbeats": mine_hb, "other_procs": others, "thumb": thumb,
                "hw": {k: hw.get(k) for k in ("name", "util", "vram_used_mb", "vram_total_mb", "temp_c", "power_w",
                                               "power_limit_w", "power_default_w")} if hw else None,
                "throttle": ({"limit_w": pl, "default_w": pdef, "by_guard": bool(guard and guard["level"] >= 1),
                              "text": f"温控守护限功耗 {round(pl)} W（默认 {round(pdef)} W，内存温度高）" if guard and guard["level"] >= 1
                              else f"功耗墙 {round(pl)} W（默认 {round(pdef)} W）"} if throttled else None),
                "comfy": {"url": ln.get("url"), "port": comfy_port, "reachable": ln.get("reachable"),
                          "error": ln.get("error")} if ln else None,
                "hw_age_s": hosts[h]["age_s"],
            })
    unplaced = [b for b in hbs if not any(b in c["heartbeats"] for c in cards)]
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cards": cards, "hosts": hosts, "heartbeats": unplaced,
            "warming": not lanes}


@router.get("/api/gpu/live")
def gpu_live():
    return snapshot()


# ---------------------------------------------------------------- 缩略图代理
_SHOT_RE = re.compile(r"^(ep\d{2})-S(\d{1,3})_")


def _local_copy(filename: str) -> Path | None:
    """UIRSI r38（项目方截图“最近出图”裂图）：ComfyUI 输出名“ep05-S3_image_v9_00002_.png”在服务器上，
    笔记本经隧道去取——隧道 / 跳板一断就 30 s 超时再 502，图就裂了。这张图登记进版本链时，takes.json 里记了
    服务器原路径（gen_contract.postflight.subject / origin），所以先在本镜 takes.json 里找同名的一版，用笔记本上的文件。"""
    m = _SHOT_RE.match(filename)
    if not m:
        return None
    try:
        from ns_render import pipeline as P  # noqa: PLC0415
        tj = P.RENDERS / m.group(1) / f"S{int(m.group(2))}" / "takes.json"
        data = json.loads(tj.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for tk in reversed(data.get("takes") or []):
        if tk.get("file") and filename in json.dumps(tk, ensure_ascii=False):
            f = P.DATA / tk["file"]
            if f.is_file():
                return f
    return None


@router.get("/api/gpu/thumb")
def gpu_thumb(lane: str, filename: str, subfolder: str = "", type: str = "output", w: int | None = None):  # noqa: A002
    from ns_render import endpoints as EP
    try:
        url = EP.url_for_gpu(lane)
    except ValueError:
        raise HTTPException(404, "没有这条道")
    if "/" in filename or "\\" in filename or ".." in filename or ".." in subfolder or type not in ("output", "temp", "input"):
        raise HTTPException(400, "文件名不对")
    key = (lane, filename, subfolder, type, w)
    with _lock:
        hit = _st["thumbs"].get(key)
        miss = _st.setdefault("thumb_miss", {}).get(key)
    if hit:
        return Response(hit[1], media_type=hit[0], headers={"Cache-Control": "max-age=3600"})
    raw, ctype = None, "image/png"
    loc = _local_copy(filename)
    if loc is not None:                      # 笔记本上有同一张（已登记进版本链）→ 不经隧道
        raw = loc.read_bytes()
        ctype = "image/jpeg" if loc.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    else:
        if miss and time.time() - miss < 60:    # 刚读不到过：1 分钟内不再去等隧道（前端显示占位字）
            raise HTTPException(404, "这张图在服务器上，笔记本上还没有，连接也暂时不通")
        q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": type})
        try:
            with urllib.request.urlopen(f"{url}/view?{q}", timeout=8) as r:
                raw = r.read()
                ctype = r.headers.get("content-type") or "image/png"
        except Exception:  # noqa: BLE001
            with _lock:
                _st["thumb_miss"][key] = time.time()
            raise HTTPException(404, "这张图在服务器上，笔记本上还没有，连接也暂时不通")
    if w:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail((int(w), int(w) * 2))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=82)
            raw, ctype = b.getvalue(), "image/jpeg"
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        if len(_st["thumbs"]) > 60:
            _st["thumbs"].clear()
        _st["thumbs"][key] = (ctype, raw)
        _st["thumb_miss"].pop(key, None)
    return Response(raw, media_type=ctype, headers={"Cache-Control": "max-age=3600"})


def lanes_cache() -> dict:
    """给 render_tasks 用：各道缓存（不触发 ssh）"""
    ensure()
    with _lock:
        return {k: dict(v) for k, v in _st["lanes"].items()}


def env_debug() -> dict:  # pragma: no cover - 排障
    return {"pid": os.getpid(), "ssh": {h: {"at": s.at, "err": s.err} for h, s in _st["ssh"].items()}}
