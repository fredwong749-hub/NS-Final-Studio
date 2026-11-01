"""NS-Final Studio 实时监控看板（只读）。

启动:  python tools/monitor/server.py   → http://127.0.0.1:8810
数据来源（全部只读，不改任何东西）:
  - ~/.claude/sessions/*.json            本机正在运行的 Claude Code 会话
  - ~/.claude/projects/*/<sid>.jsonl      会话 token（按 message.id 去重）
  - ~/.claude/projects/*/<sid>/subagents  子 agent 描述、状态、token、最近动作
  - data/**/ledger.json(l)                写作模型（abliteration 等）API 花费
  - ssh gpu33 / gpu36 + 本机 nvidia-smi   GPU 与远端进程
  - data/ assets/ 本地图片视频目录 + 远端 ComfyUI 输出目录
"""
from __future__ import annotations

import ctypes
import glob
import json
import mimetypes
import os
import shlex
import sys
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]  # D:\NS-Final Studio
HERE = Path(__file__).resolve().parent
CLAUDE = Path.home() / ".claude"
PORT = int(os.environ.get("NS_MONITOR_PORT", "8810"))
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VID_EXT = {".mp4", ".webm", ".mov"}
ACTIVE_SEC = 30 * 60  # 子 agent 未结束且 30 分钟内有写入 = 运行中

REMOTES = {
    "gpu33": {
        "outputs": ["/root/claude-kimi-ns-studio-v1/ComfyUI/output", "/root/claude-kimi-ns-studio-v1/renders",
                    "/root/claude-kimi-ns-studio-v1/production"],
        "proc_grep": "claude-kimi|qwen-agent|nsfs",
    },
    "gpu36": {
        "outputs": ["/root/work/fredw/comfy/output/gpu0", "/root/work/fredw/comfy/output/gpu1",
                    "/root/work/fredw/comfy/output/gpu2", "/root/work/fredw/longshot", "/root/work/fredw/consist"],
        "proc_grep": "/root/work/fredw",
    },
}

STATE: dict = {"gpu": {}, "remote_procs": {}, "remote_outputs": {}, "local_media": [], "updated": {}}
LOCK = threading.Lock()


# ---------------------------------------------------------------- helpers
def pid_alive(pid: int) -> bool:
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


def run(cmd: list[str], timeout: int = 40) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=0x08000000)
        return r.stdout
    except Exception as e:  # noqa: BLE001
        return f"__ERR__ {e}"


def iso_to_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------- transcript token parsing (incremental)
class Transcript:
    """增量读取一个 jsonl：按 message.id 去重累计 token，记录最近动作。"""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.usage: dict[str, dict] = {}
        self.hourly: dict[str, dict] = {}  # "YYYY-mm-dd HH" -> {in,out}
        self.msg_hour: dict[str, str] = {}
        self.model = ""
        self.last_ts = 0.0
        self.first_ts = 0.0
        self.last_action = ""
        self.first_prompt = ""

    def update(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:
            self.__init__(self.path)
        if size == self.offset:
            return
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read(size - self.offset)
        end = chunk.rfind(b"\n")
        if end < 0:
            return
        self.offset += end + 1
        for raw in chunk[: end + 1].splitlines():
            try:
                d = json.loads(raw)
            except Exception:
                continue
            t = d.get("type")
            ts = iso_to_ts(d.get("timestamp"))
            if ts:
                self.last_ts = max(self.last_ts, ts)
                self.first_ts = self.first_ts or ts
            if t == "user" and not self.first_prompt:
                c = (d.get("message") or {}).get("content")
                if isinstance(c, str):
                    self.first_prompt = c[:160]
            if t != "assistant":
                continue
            m = d.get("message") or {}
            u = m.get("usage")
            mid = m.get("id") or d.get("uuid")
            if m.get("model") and not m["model"].startswith("<"):
                self.model = m["model"]
            if u and mid:
                self.usage[mid] = {
                    "in": u.get("input_tokens") or 0,
                    "cw": u.get("cache_creation_input_tokens") or 0,
                    "cr": u.get("cache_read_input_tokens") or 0,
                    "out": u.get("output_tokens") or 0,
                }
                if ts:
                    self.msg_hour[mid] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H")
            for blk in m.get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    inp = blk.get("input") or {}
                    hint = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                    self.last_action = f"{blk.get('name')}: {str(hint)[:120]}"

    def totals(self) -> dict:
        tot = {"in": 0, "cw": 0, "cr": 0, "out": 0, "calls": len(self.usage)}
        for u in self.usage.values():
            for k in ("in", "cw", "cr", "out"):
                tot[k] += u[k]
        tot["total"] = tot["in"] + tot["cw"] + tot["cr"] + tot["out"]
        return tot

    def hourly_totals(self) -> dict[str, dict]:
        h: dict[str, dict] = {}
        for mid, u in self.usage.items():
            k = self.msg_hour.get(mid)
            if not k:
                continue
            e = h.setdefault(k, {"fresh": 0, "cache": 0, "out": 0})
            e["fresh"] += u["in"] + u["cw"]
            e["cache"] += u["cr"]
            e["out"] += u["out"]
        return h


TRANSCRIPTS: dict[str, Transcript] = {}


def transcript(path: Path) -> Transcript:
    key = str(path)
    if key not in TRANSCRIPTS:
        TRANSCRIPTS[key] = Transcript(path)
    tr = TRANSCRIPTS[key]
    tr.update()
    return tr


def find_session_file(sid: str) -> Path | None:
    hits = glob.glob(str(CLAUDE / "projects" / "*" / f"{sid}.jsonl"))
    return Path(hits[0]) if hits else None


def read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_agents() -> dict:
    now = time.time()
    sessions = []
    hourly: dict[str, dict] = {}
    for sf in glob.glob(str(CLAUDE / "sessions" / "*.json")):
        s = read_json(Path(sf))
        if not s.get("sessionId"):
            continue
        alive = pid_alive(s.get("pid", 0))
        if not alive:
            continue
        tf = find_session_file(s["sessionId"])
        tr = transcript(tf) if tf else None
        subs = []
        if tf:
            sub_dir = tf.with_suffix("") / "subagents"
            for jf in glob.glob(str(sub_dir / "agent-*.jsonl")):
                jp = Path(jf)
                mtime = jp.stat().st_mtime
                if now - mtime > 36 * 3600:
                    continue  # 只看 36 小时内
                meta = read_json(jp.with_suffix(".meta.json"))
                st = transcript(jp)
                finished = bool(meta.get("finished"))
                if finished:
                    state = "已完成"
                elif now - mtime < ACTIVE_SEC:
                    state = "运行中"
                else:
                    state = "停滞/中断"
                subs.append({
                    "id": jp.stem.replace("agent-", ""),
                    "desc": meta.get("description") or st.first_prompt[:60],
                    "type": meta.get("agentType", ""),
                    "parent": meta.get("parentAgentId"),
                    "depth": meta.get("spawnDepth", 1),
                    "state": state,
                    "model": st.model,
                    "tokens": st.totals(),
                    "started": st.first_ts,
                    "last": mtime,
                    "action": st.last_action,
                })
                for k, v in st.hourly_totals().items():
                    e = hourly.setdefault(k, {"fresh": 0, "cache": 0, "out": 0})
                    for kk in v:
                        e[kk] += v[kk]
        if tr:
            for k, v in tr.hourly_totals().items():
                e = hourly.setdefault(k, {"fresh": 0, "cache": 0, "out": 0})
                for kk in v:
                    e[kk] += v[kk]
        order = {"运行中": 0, "停滞/中断": 1, "已完成": 2}
        subs.sort(key=lambda x: (order[x["state"]], -x["last"]))
        sessions.append({
            "name": s.get("name"), "sid": s["sessionId"], "pid": s.get("pid"), "status": s.get("status"),
            "cwd": s.get("cwd"), "version": s.get("version"), "started": (s.get("startedAt") or 0) / 1000,
            "updated": (s.get("statusUpdatedAt") or 0) / 1000,
            "model": tr.model if tr else "", "tokens": tr.totals() if tr else {},
            "action": tr.last_action if tr else "", "subagents": subs,
        })
    sessions.sort(key=lambda x: -x["updated"])
    dsh = collect_dsh()
    for r in dsh["sessions"]:
        for k, v in r["hourly"].items():
            e = hourly.setdefault(k, {"fresh": 0, "cache": 0, "out": 0})
            for kk in v:
                e[kk] += v[kk]
        r.pop("hourly", None)
    tot = {"in": 0, "cw": 0, "cr": 0, "out": 0, "calls": 0, "total": 0}
    for r in dsh["sessions"]:
        for k in tot:
            tot[k] += r["tokens"].get(k, 0)
    busy = any(r["state"] == "运行中" for r in dsh["sessions"])
    if dsh["sessions"] or dsh["web_up"]:
        sessions.append({
            "name": "DeepSeek Harness (dsh)", "sid": "dsh", "pid": None,
            "status": "busy" if busy else "idle", "cwd": "", "version": "",
            "started": 0, "updated": max([r["last"] for r in dsh["sessions"]] or [0]),
            "model": "abliterated-model-large-flash", "tokens": tot,
            "action": ("网页端 :3080 在线" if dsh["web_up"] else "网页端 :3080 未启动"),
            "subagents": dsh["sessions"], "kind": "dsh",
        })
    keys = sorted(hourly)[-24:]
    return {"sessions": sessions, "hourly": [{"h": k, **hourly[k]} for k in keys]}


DSH_DIR = Path.home() / ".dsh" / "sessions"
DSH_CACHE: dict[str, dict] = {}


def _dsh_parse(path: Path) -> dict | None:
    try:
        import zstandard  # 项目 .venv 已装
    except ImportError:
        return None
    try:
        with open(path, "rb") as fh:
            raw = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True).read()
    except Exception:
        return None  # 正在写入的残帧，下次再读
    info = {"id": path.parent.name.replace("session-", ""), "title": "", "cwd": "", "depth": 0, "model": "",
            "tokens": {"in": 0, "cw": 0, "cr": 0, "out": 0, "calls": 0, "total": 0}, "hourly": {},
            "started": 0.0, "last": 0.0, "action": "", "open_turn": False, "ended": False}
    for ln in raw.decode("utf-8", errors="replace").splitlines():
        try:
            d = json.loads(ln)
        except Exception:
            continue
        t, data = d.get("type"), d.get("data") or {}
        tm = (d.get("time") or 0) / 1000
        if tm:
            info["last"] = max(info["last"], tm)
        if t == "session":
            info["started"] = (d.get("createdAt") or 0) / 1000
            info["cwd"] = d.get("cwd", "")
            info["depth"] = d.get("delegationDepth", 0)
        elif t == "session/title":
            info["title"] = data.get("title", "")
        elif t == "turn/start":
            info["open_turn"], info["ended"] = True, False
        elif t == "turn/end":
            info["open_turn"] = False
        elif t == "session/end-seed":
            info["ended"] = True
        elif t == "tool/call":
            try:
                a = json.loads(data.get("arguments") or "{}")
            except Exception:
                a = {}
            hint = a.get("description") or a.get("command") or a.get("path") or ""
            info["action"] = f"{data.get('name')}: {str(hint)[:120]}"
        elif t == "assistant/message":
            u = data.get("usage") or {}
            src = (data.get("message") or {}).get("source") or {}
            info["model"] = src.get("model") or info["model"]
            i, o = u.get("inputTokens") or 0, u.get("outputTokens") or 0
            tk = info["tokens"]
            tk["in"] += i
            tk["out"] += o
            tk["calls"] += 1
            tk["total"] += i + o
            if tm:
                h = info["hourly"].setdefault(datetime.fromtimestamp(tm).strftime("%Y-%m-%d %H"),
                                              {"fresh": 0, "cache": 0, "out": 0})
                h["fresh"] += i
                h["out"] += o
    return info


def port_listening(port: int) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def collect_dsh() -> dict:
    now = time.time()
    rows = []
    for f in glob.glob(str(DSH_DIR / "*" / "session-*" / "session.v4.jsonl.zstd")):
        p = Path(f)
        st = p.stat()
        if now - st.st_mtime > 36 * 3600:
            continue
        key = (st.st_mtime, st.st_size)
        c = DSH_CACHE.get(f)
        if not c or c["key"] != key:
            info = _dsh_parse(p)
            if info:
                DSH_CACHE[f] = c = {"key": key, "info": info}
        if not c:
            continue
        info = dict(c["info"])
        info["last"] = max(info["last"], st.st_mtime)
        if info["open_turn"] and now - info["last"] < ACTIVE_SEC:
            info["state"] = "运行中"
        elif info["open_turn"] and not info["ended"]:
            info["state"] = "停滞/中断"
        else:
            info["state"] = "已完成"
        info["desc"] = info["title"] or info["id"][:8]
        info["type"] = "dsh" + (f" · 委派深度 {info['depth']}" if info["depth"] else "")
        rows.append(info)
    order = {"运行中": 0, "停滞/中断": 1, "已完成": 2}
    rows.sort(key=lambda x: (order[x["state"]], -x["last"]))
    return {"web_up": port_listening(3080), "sessions": rows}


def collect_ledgers() -> dict:
    rows = []
    for pat in ("data/**/ledger.jsonl", "data/**/ledger.json", "data/**/*ledger*.jsonl"):
        for f in glob.glob(str(ROOT / pat), recursive=True):
            if "_archive" in f:
                continue
            p = Path(f)
            try:
                txt = p.read_text(encoding="utf-8")
            except Exception:
                continue
            items = []
            if p.suffix == ".jsonl":
                for ln in txt.splitlines():
                    try:
                        items.append(json.loads(ln))
                    except Exception:
                        pass
            else:
                try:
                    j = json.loads(txt)
                    items = j if isinstance(j, list) else j.get("calls") or j.get("ledger") or []
                except Exception:
                    pass
            for it in items:
                if not isinstance(it, dict):
                    continue
                u = it.get("usage") or {}
                rows.append({
                    "file": str(p.relative_to(ROOT)),
                    "at": it.get("at") or it.get("t") or "",
                    "provider": it.get("provider", ""),
                    "model": it.get("model", ""),
                    "pt": it.get("prompt_tokens") or u.get("prompt_tokens") or 0,
                    "ct": it.get("completion_tokens") or u.get("completion_tokens") or 0,
                    "usd": float(it.get("usd") or 0),
                    "tag": it.get("tag") or it.get("run") or p.parent.name,
                })
    seen, uniq = set(), []
    for r in rows:
        k = (r["at"], r["model"], r["pt"], r["ct"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    uniq.sort(key=lambda r: r["at"])
    today = datetime.now().strftime("%Y-%m-%d")
    by_tag: dict[str, dict] = {}
    for r in uniq:
        e = by_tag.setdefault(r["tag"], {"tag": r["tag"], "calls": 0, "usd": 0.0, "pt": 0, "ct": 0, "last": ""})
        e["calls"] += 1
        e["usd"] += r["usd"]
        e["pt"] += r["pt"]
        e["ct"] += r["ct"]
        e["last"] = max(e["last"], r["at"])
    return {
        "total_usd": sum(r["usd"] for r in uniq),
        "today_usd": sum(r["usd"] for r in uniq if str(r["at"]).startswith(today)),
        "calls": len(uniq),
        "by_tag": sorted(by_tag.values(), key=lambda e: e["last"], reverse=True),
        "recent": uniq[-12:][::-1],
    }


# ---------------------------------------------------------------- slow collectors (background threads)
# GPUVIEW 11-01：查询串与解析与 ns_api.gpu_live 共用 services/agent/ns_agent/gpu_smi.py（不各写一遍）
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(ROOT / "services" / "agent"))
from ns_agent.gpu_smi import MONITOR_QUERY as GPU_Q, parse_monitor as parse_gpu  # noqa: E402,F401


GPU_PERIOD_S = 30     # 总调度 11-02 03:1x：GPU 采集放宽到 30 s，每台每拍一次合并调用


def remote(host: str, script: str, timeout: int = 40) -> str:
    """远程只走 tools/netfix/rssh.py 的常驻主连接（K-OPS-N07 / N09）：主连接不在立刻失败，不新建 ssh 握手；服务器侧 timeout + nice"""
    sys.path.insert(0, str(ROOT / "tools" / "netfix"))
    import rssh
    try:
        r = rssh.run(host, f"timeout {timeout - 5} nice -n 19 bash -c {shlex.quote(script)}", timeout=timeout)
        return r.stdout.decode("utf-8", "replace") or r.stderr.decode("utf-8", "replace")[-300:]
    except subprocess.TimeoutExpired:  # arch-ok: 看板只展示，超时写进 err 显示
        return "超时（rssh 主连接）"


def gpu_loop() -> None:
    while True:
        local = parse_gpu(run(["nvidia-smi"] + GPU_Q.split()[1:], 15))
        with LOCK:
            STATE["gpu"]["本机"] = {"gpus": local, "ok": bool(local), "procs": []}
        for host, cfg in REMOTES.items():
            script = (
                f"{GPU_Q}; echo '##APPS'; nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits;"
                " echo '##UUID'; nvidia-smi --query-gpu=index,uuid --format=csv,noheader;"
                f" echo '##PS'; ps -eo pid=,etimes=,args= | grep -E '{cfg['proc_grep']}' | grep -v grep | cut -c1-220"
            )
            out = remote(host, script, 40)
            parts = {"gpu": out, "apps": "", "uuid": "", "ps": ""}
            if "##APPS" in out:
                parts["gpu"], rest = out.split("##APPS", 1)
                parts["apps"], rest = rest.split("##UUID", 1)
                parts["uuid"], parts["ps"] = rest.split("##PS", 1)
            uuid2idx = {}
            for ln in parts["uuid"].splitlines():
                if "," in ln:
                    i, u = [x.strip() for x in ln.split(",", 1)]
                    uuid2idx[u] = i
            pid2gpu = {}
            for ln in parts["apps"].splitlines():
                p = [x.strip() for x in ln.split(",")]
                if len(p) == 3:
                    pid2gpu[p[1]] = uuid2idx.get(p[0], "?")
            procs = []
            for ln in parts["ps"].splitlines():
                p = ln.strip().split(None, 2)
                if len(p) < 3:
                    continue
                args = p[2]
                port = ""
                if "--port" in args:
                    try:
                        port = args.split("--port", 1)[1].split()[0]
                    except Exception:
                        pass
                kind = "ComfyUI" if "main.py" in args else "进程"
                procs.append({"pid": p[0], "secs": int(p[1]), "args": args, "gpu": pid2gpu.get(p[0], ""),
                              "port": port, "kind": kind})
            gpus = parse_gpu(parts["gpu"])
            with LOCK:
                STATE["gpu"][host] = {"gpus": gpus, "ok": bool(gpus), "procs": procs,
                                      "err": "" if gpus else out[-300:]}
        with LOCK:
            STATE["updated"]["gpu"] = time.time()
        time.sleep(GPU_PERIOD_S)


REMOTE_MEDIA_S = 300
REMOTE_MEDIA_T: dict = {}


def media_loop() -> None:
    while True:
        # 本地：按 data/<a>/<b> 两级目录聚合
        groups: dict[str, dict] = {}
        for base in ("data", "assets", "previews"):
            bp = ROOT / base
            if not bp.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(bp):
                if "_archive" in dirpath or "cache" in Path(dirpath).parts:
                    dirnames[:] = []
                    continue
                rel = Path(dirpath).relative_to(ROOT).parts
                key = "/".join(rel[:3])
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in IMG_EXT and ext not in VID_EXT:
                        continue
                    fp = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(fp)
                    except OSError:
                        continue
                    g = groups.setdefault(key, {"dir": key, "img": 0, "vid": 0, "bytes": 0, "last": 0, "latest": "",
                                                "latest_img": "", "latest_img_t": 0, "today": 0})
                    g["img" if ext in IMG_EXT else "vid"] += 1
                    g["bytes"] += st.st_size
                    if st.st_mtime > time.time() - 86400:
                        g["today"] += 1
                    if st.st_mtime > g["last"]:
                        g["last"], g["latest"] = st.st_mtime, str(Path(fp).relative_to(ROOT)).replace("\\", "/")
                    if ext in IMG_EXT and st.st_mtime > g["latest_img_t"]:
                        g["latest_img_t"] = st.st_mtime
                        g["latest_img"] = str(Path(fp).relative_to(ROOT)).replace("\\", "/")
        local = sorted(groups.values(), key=lambda g: -g["last"])
        with LOCK:
            STATE["local_media"] = local
        # 远端 ComfyUI / 渲染输出
        for host, cfg in REMOTES.items():
            sh = "; ".join(
                f"d={d}; [ -d $d ] && echo \"$d|$(find $d -type f \\( -iname '*.png' -o -iname '*.jpg' -o -iname '*.webp' \\) | wc -l)"
                f"|$(find $d -type f \\( -iname '*.mp4' -o -iname '*.webm' \\) | wc -l)"
                f"|$(find $d -type f -mmin -1440 | wc -l)|$(du -sb $d | cut -f1)"
                f"|$(find $d -type f -printf '%T@ %P\\n' 2>/dev/null | sort -n | tail -1)\""
                for d in cfg["outputs"]
            )
            if time.time() - REMOTE_MEDIA_T.get(host, 0) < REMOTE_MEDIA_S:   # 远端 find / du 较重：5 分钟一次（总调度 03:1x：看板不给服务器加负载）
                continue
            REMOTE_MEDIA_T[host] = time.time()
            out = remote(host, sh, 90)
            rows = []
            for ln in out.splitlines():
                p = ln.split("|")
                if len(p) == 6:
                    lt, _, lf = p[5].partition(" ")
                    rows.append({"dir": p[0], "img": int(p[1] or 0), "vid": int(p[2] or 0), "today": int(p[3] or 0),
                                 "bytes": int(p[4] or 0), "last": float(lt or 0), "latest": lf})
            with LOCK:
                STATE["remote_outputs"][host] = rows
        with LOCK:
            STATE["updated"]["media"] = time.time()
        time.sleep(60)


def local_procs() -> list[dict]:
    """本机正在跑的项目相关 python/node 进程（如 API 8800、迭代脚本）。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe' or Name='node.exe'\" | "
          "Where-Object { $_.CommandLine -match 'NS-Final|ns-studio|deepseek-harness|dsh' } | "
          "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress")
    out = run(["powershell", "-NoProfile", "-Command", ps], 25)
    try:
        j = json.loads(out) if out.strip() else []
    except Exception:
        return []
    if isinstance(j, dict):
        j = [j]
    res = []
    for p in j:
        cl = p.get("CommandLine") or ""
        if "tools\\monitor\\server.py" in cl or "tools/monitor/server.py" in cl:
            continue
        cd = p.get("CreationDate")
        res.append({"pid": p.get("ProcessId"), "args": cl[:220], "created": cd})
    return res


LOCAL_PROCS: dict = {"rows": [], "t": 0}


def collect_alerts() -> dict:
    """WORKFLOW 11-01（W7b，K-OPS-W06）：基础设施看门狗的报警（tools/autopilot/infra_watchdog.py → data/qa/alerts.jsonl）。
    open = 当前还开着的（状态文件），recent = 最近 30 行"""
    st = read_json(ROOT / "data/qa/infra_watchdog_state.json")
    recent = []
    try:
        lines = (ROOT / "data/qa/alerts.jsonl").read_text(encoding="utf-8").splitlines()[-30:]
        recent = [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        pass
    return {"open": list((st.get("open") or {}).values()), "recent": recent[::-1], "at": st.get("at"),
            "down": st.get("down") or []}


def collect_sentinel() -> dict:
    """SENTINEL 工单（tools/sentinel，K-OPS-S03）：data/sentinel/open.json = 未关闭工单 + 负责方 + 持续时长；读不到如实报“未运行”"""
    p = ROOT / "data/sentinel/open.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # arch-ok: 看板只展示，读不到显示“SENTINEL 未运行 / 读不到”
        return {"ok": False, "why": f"{type(e).__name__}", "issues": []}
    d["ok"] = True
    d["age_s"] = round(time.time() - p.stat().st_mtime)
    return d


def snapshot() -> dict:
    agents = collect_agents()
    if time.time() - LOCAL_PROCS["t"] > 20:
        LOCAL_PROCS["rows"], LOCAL_PROCS["t"] = local_procs(), time.time()
    with LOCK:
        st = json.loads(json.dumps(STATE))
    return {"now": time.time(), "agents": agents, "ledger": collect_ledgers(), "local_procs": LOCAL_PROCS["rows"],
            "alerts": collect_alerts(), "sentinel": collect_sentinel(), **st}


SNAP_CACHE = {"t": 0.0, "data": None}
SNAP_LOCK = threading.Lock()


def cached_snapshot() -> dict:
    with SNAP_LOCK:
        if time.time() - SNAP_CACHE["t"] > 4 or SNAP_CACHE["data"] is None:
            SNAP_CACHE["data"] = snapshot()
            SNAP_CACHE["t"] = time.time()
        return SNAP_CACHE["data"]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 安静
        pass

    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/status":
            try:
                body = json.dumps(cached_snapshot(), ensure_ascii=False).encode("utf-8")
                return self.send(200, body, "application/json; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                return self.send(500, str(e).encode(), "text/plain")
        if u.path == "/file":
            rel = (parse_qs(u.query).get("p") or [""])[0]
            fp = (ROOT / rel).resolve()
            if ROOT not in fp.parents or not fp.is_file() or fp.suffix.lower() not in IMG_EXT | VID_EXT:
                return self.send(404, b"no", "text/plain")
            return self.send(200, fp.read_bytes(), mimetypes.guess_type(fp.name)[0] or "application/octet-stream")
        if u.path == "/open":
            rel = (parse_qs(u.query).get("p") or [""])[0]
            fp = (ROOT / rel).resolve()
            if fp == ROOT or ROOT in fp.parents:
                target = fp if fp.is_dir() else fp.parent
                subprocess.Popen(["explorer", str(target)])
                return self.send(200, b"ok", "text/plain")
            return self.send(404, b"no", "text/plain")
        return self.send(404, b"not found", "text/plain")


if __name__ == "__main__":
    threading.Thread(target=gpu_loop, daemon=True).start()
    threading.Thread(target=media_loop, daemon=True).start()
    print(f"NS 监控看板: http://127.0.0.1:{PORT}")
    # Windows 上 SO_REUSEADDR 允许两个进程同绑 8810（11-02 03:1x 实测：00:27 起的旧看板 GPU 采集卡死 2.9 小时，新看板起来后请求仍落到旧进程）
    # → 关掉 reuse，端口被占时直接报错退出，不起第二份（NS-Monitor.vbs 与自启守护同时拉起也安全）
    ThreadingHTTPServer.allow_reuse_address = False
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
