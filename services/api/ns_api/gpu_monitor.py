"""
GPU 实时面板后端（项目方 2026-10-30：“gpu进程实时tracking”）。

GET /api/gpu3/gpus → {at, gpus:[…4 张卡…], qwen:{reachable, running, queued, tasks}, sources}
  每张卡：利用率、显存、温度、功耗、进程（pid、命令简称、显存）、train.lock / gpu.lock / lend 归属、ComfyUI 队列，
  last_busy_at（服务端记的最近一次忙）与 locked_idle（锁着但空闲 ≥ 10 分钟）。GPU2 标坏卡。
数据：gpu3 桥 /api/gpu3/gpus（主）+ 一次 ssh（温度、功耗、进程命令行，失败就缺这几项）+ Qwen 信箱。服务端缓存 5 秒，单飞。
只读：不改锁、不碰进程。
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request

from fastapi import APIRouter

from ns_api import readiness as RD

router = APIRouter(tags=["gpu-monitor"])
CACHE_S = 5.0
IDLE_WARN_S = 600
BUSY_UTIL = 5          # 利用率 ≥ 5% 算忙
FAULTY = {2}
_state: dict = {"at": 0.0, "data": None}
_last_busy: dict[int, float] = {}
_lock = threading.Lock()

SSH_SCRIPT = r"""
import json, subprocess
q = subprocess.run(["nvidia-smi", "--query-gpu=index,temperature.gpu,power.draw,power.limit",
                    "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
gpus = {}
for ln in q.strip().splitlines():
    i, t, p, pl = [x.strip() for x in ln.split(",")]
    gpus[i] = {"temp_c": float(t) if t not in ("", "[N/A]") else None,
               "power_w": float(p) if p not in ("", "[N/A]") else None,
               "power_limit_w": float(pl) if pl not in ("", "[N/A]") else None}
apps = subprocess.run(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory", "--format=csv,noheader,nounits"],
                      capture_output=True, text=True).stdout
uu = subprocess.run(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"], capture_output=True, text=True).stdout
idx = {u.strip(): i.strip() for i, u in (l.split(",") for l in uu.strip().splitlines())}
procs = {}
for ln in apps.strip().splitlines():
    u, pid, mem = [x.strip() for x in ln.split(",")]
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmd = ""
    procs.setdefault(idx.get(u, "?"), []).append({"pid": int(pid), "vram_mb": int(mem), "cmd": cmd[:300]})
import glob, os, re
paused = {}   # 暂停的锁：.train.lock.gpuN.<谁>-paused-for-<为什么>
for f in glob.glob("/root/.local/state/NS-Studio/.train.lock.gpu*"):
    m = re.match(r"\.train\.lock\.gpu(\d+)\.(.+)$", os.path.basename(f))
    if m and "paused" in m.group(2):
        try:
            txt = open(f).read()[:300]
        except OSError:
            txt = ""
        paused[m.group(1)] = {"tag": m.group(2), "text": txt}
print(json.dumps({"gpus": gpus, "procs": procs, "paused": paused}))
"""


def _short(cmd: str) -> str:
    """命令简称：常见进程给可读名（ComfyUI :端口 / Qwen LLM / 训练），其余取脚本名或可执行文件名"""
    parts = cmd.split()
    if not parts:
        return ""
    port = next((parts[i + 1] for i, p in enumerate(parts[:-1]) if p == "--port"), None)
    if "llama-server" in cmd:
        return f"Qwen LLM (llama-server{f' :{port}' if port else ''})"
    if any(p.endswith("main.py") for p in parts) and port:
        return f"ComfyUI :{port}"
    if "ai-toolkit" in cmd or any(p.endswith("run.py") for p in parts):
        return "LoRA 训练 (ai-toolkit)"
    if "musubi" in cmd:
        return "LoRA 训练 (musubi)"
    for i, p in enumerate(parts[1:], 1):
        if p.endswith(".py"):
            return p.rsplit("/", 1)[-1]
        if p == "-m" and i + 1 < len(parts):
            return parts[i + 1]
    return parts[0].rsplit("/", 1)[-1]


def _bridge() -> list[dict] | None:
    try:
        with urllib.request.urlopen(f"{RD.BRIDGE_URL}/api/gpu3/gpus", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _ssh() -> dict | None:
    try:
        p = _rssh().run_retry("gpu33", "python3 -", input=SSH_SCRIPT, timeout=12, tries=1, text=True)   # SYSARCH 4-1：走常驻主连接
        return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError, ImportError, AttributeError):   # rssh 加载失败也按“读不到”
        return None


def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location("_rssh_41", _P(__file__).resolve().parents[3] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _qwen() -> dict:
    from ns_api.qwen_mailbox import MAILBOX_URL as base
    try:
        with urllib.request.urlopen(f"{base}/tasks", timeout=4) as r:
            rows = json.loads(r.read().decode("utf-8"))
        if not isinstance(rows, list):   # 封板修复：/tasks 返回对象时元素是字符串 → AttributeError → 整个 /api/gpu3/gpus 500
            raise ValueError("mailbox /tasks 不是列表")
        live = [t for t in rows if isinstance(t, dict) and t.get("status") in ("running", "queued")]
        return {"reachable": True, "running": sum(t["status"] == "running" for t in live),
                "queued": sum(t["status"] == "queued" for t in live),
                "tasks": [{"id": t.get("id"), "from": t.get("from"), "status": t.get("status"),
                           "created_at": t.get("created_at")} for t in live][:20]}
    except (OSError, ValueError, KeyError, TypeError):
        return {"reachable": False, "running": None, "queued": None, "tasks": []}


def _owner(text: str | None) -> str | None:
    """锁 / lend 文件 → 归属简称（JSON 的 by/job，或文本第一段）"""
    if not text:
        return None
    try:
        d = json.loads(text)
    except ValueError:
        return text.strip()[:120]
    if not isinstance(d, dict):          # 封板修复：锁文件内容是数字 / 字符串 JSON 时曾 AttributeError → 整个面板 500
        return text.strip()[:120]
    return " · ".join(str(x) for x in (d.get("by"), d.get("job")) if x)


def collect(now: float | None = None, ssh: bool = True) -> dict:
    """ssh=False：不等 ssh（温度 / 功耗 / 进程命令行缺），给冷启动的第一个请求用"""
    now = now or time.time()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:    # 三个来源并行（桥 / ssh / 信箱），总耗时 ≈ 最慢的一个
        fb, fq = ex.submit(_bridge), ex.submit(_qwen)
        fe = ex.submit(_ssh) if ssh else None
        bridge, extra, qwen = fb.result(), fe.result() if fe else None, fq.result()
    rows = {g["id"]: g for g in (bridge if isinstance(bridge, list) else []) if isinstance(g, dict) and "id" in g}
    eg, ep = (extra or {}).get("gpus", {}), (extra or {}).get("procs", {})
    paused = (extra or {}).get("paused", {})
    out = []
    for i in range(4):
        b = rows.get(i, {})
        util = b.get("util")
        procs = [{"pid": p["pid"], "vram_mb": p["vram_mb"], "cmd": _short(p["cmd"]), "cmdline": p["cmd"]}
                 for p in ep.get(str(i), [])] or [{"pid": p.get("pid"), "vram_mb": p.get("vram_mb"),
                                                   "cmd": p.get("name"), "cmdline": None} for p in b.get("processes", [])]
        busy = util is not None and util >= BUSY_UTIL
        if busy or i not in _last_busy:
            _last_busy[i] = now if busy else _last_busy.get(i, now)
        tl = b.get("train_lock") or {}
        lock_owner = _owner(tl.get("text")) or _owner(b.get("lock_file"))
        lend = _owner(b.get("lend_file") if isinstance(b.get("lend_file"), str) else None)
        idle_s = 0 if busy else now - _last_busy[i]
        pz = paused.get(str(i))
        paused_note = None
        if pz:   # 例：qwen-agent-paused-for-ep01 → “为 ep01 预留（已暂停 Qwen，等项目方启动）”
            who, _, why = pz["tag"].partition("-paused-for-")
            who = who.replace("qwen-agent", "Qwen")
            paused_note = f"为 {why} 预留（已暂停 {who}，等项目方启动）" if why else f"暂停：{pz['tag']}"
        out.append({
            "paused": paused_note,
            "id": i, "name": b.get("name"), "faulty": i in FAULTY or bool(b.get("faulty")),
            "util": util, "vram_used_mb": b.get("vram_used_mb"), "vram_total_mb": b.get("vram_total_mb"),
            "temp_c": (eg.get(str(i)) or {}).get("temp_c"), "power_w": (eg.get(str(i)) or {}).get("power_w"),
            "power_limit_w": (eg.get(str(i)) or {}).get("power_limit_w"),
            "processes": procs, "train_lock": lock_owner, "gpu_lock": _owner(b.get("busy_by")) if not tl else None,
            "lend": lend, "comfy": b.get("comfy"), "busy": busy,
            "last_busy_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(_last_busy[i])),
            "idle_s": round(idle_s), "locked_idle": bool(lock_owner) and not busy and idle_s >= IDLE_WARN_S,
        })
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "gpus": out, "qwen": qwen,
            "sources": {"bridge": bridge is not None, "ssh": extra is not None, "qwen_mailbox": qwen["reachable"]},
            "idle_warn_s": IDLE_WARN_S}


def _loop():
    """后台每 CACHE_S 秒刷新一次快照（ssh 经中继约 8 s，不能让接口请求等它）；没人看 2 分钟就停"""
    while time.time() - _state.get("seen", 0) < 120:
        try:
            data = collect()
            with _lock:
                _state["data"], _state["at"] = data, time.time()
        except Exception as e:      # noqa: BLE001  采集失败不影响接口，下一轮再试
            with _lock:
                _state["error"] = repr(e)
        time.sleep(CACHE_S)
    with _lock:
        _state["thread"] = None


@router.get("/api/gpu3/gpus")
def gpus():
    """立即返回最近一次快照（后台线程刷新；首个请求时启动线程并同步采一次）"""
    with _lock:
        _state["seen"] = time.time()
        if _state.get("thread") is None:
            t = threading.Thread(target=_loop, daemon=True, name="gpu-monitor")
            _state["thread"] = t
            t.start()
        data, at = _state["data"], _state["at"]
    if data is None:    # 刚启动：同步采一次（封板修复 A-2：不等 ssh ≈8 s，ssh 那几项由后台线程下一轮补上）
        data = collect(ssh=False)
        with _lock:
            _state["data"], _state["at"] = data, time.time()
        at = _state["at"]
    return {**data, "age_s": round(time.time() - at, 1)}
