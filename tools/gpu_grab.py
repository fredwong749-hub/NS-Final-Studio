"""
GPU 抢卡任务器（项目方："显卡空闲你就抢"）——只跑资产/候选文生图，礼貌地抢空闲卡。

    uv run python tools/gpu_grab.py --once            # 跑一轮：有空卡就领任务，跑完退出
    uv run python tools/gpu_grab.py --watch           # 常驻：每 60 s 看一次
    uv run python tools/gpu_grab.py --status          # 只看各卡能不能抢，不领任务
    uv run python tools/gpu_grab.py --once --no-gpu3  # 只用笔记本

队列：data/jobs/queue/*.json（格式同 data/jobs/gpu3_char_variety_20261030.json：顶层元数据 + "jobs": [...]，
或单个任务对象）。领到的文件移到 data/jobs/running/，结束后移到 data/jobs/done/ 或 data/jobs/failed/，
文件里追加 "_gpu_grab" 记录每个子任务的结果。协议细节见 docs/gpu_grab.md。

卡：
- laptop：本机 ComfyUI :8188（RTX 4080 12 GB）。条件：队列空 + 没有 render_batch / gen_* / 训练进程。永不出视频。
- gpu3:0/1/3（GPU2 坏，永不用）：每个任务前 `ns_sched.py may-use fredw-d9-assets <gpu>`（退出码 0 才可用，
  出错 = 不可用）+ 本地看到 nvidia-smi 空闲满 2 分钟；用 O_EXCL 写 gpu.lock.gpuN = "fredw-d9 <job>"，
  任务结束立即删（每个任务单独加锁/释放），单任务 ≤ 15 分钟（超时中断、放回队列）。从不写 lend 文件、从不杀进程。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "jobs"
QUEUE, RUNNING, DONE, FAILED = JOBS / "queue", JOBS / "running", JOBS / "done", JOBS / "failed"
LOG = ROOT / "data" / "logs" / "gpu_grab.log"
OWNERSHIP = ROOT / "config" / "shot_ownership.json"

ME = "fredw-d9"
CONSUMER = "fredw-d9-assets"                     # gpu3 ns_sched.json 里登记的消费者名
SSH_HOST = "gpu33"
STATE_DIR = "/root/.local/state/NS-Studio"
SCHED = ("/root/claude-kimi-ns-studio-v1/env/comfy/bin/python "
         "/root/claude-kimi-ns-studio-v1/ns-studio/scripts/ns_sched.py")
GPU3_PORTS = {0: 8188, 1: 8189, 3: 8191}        # systemd ns-comfy@<gpu>-<port>
NEVER = {2}                                      # gpu3 GPU2 坏卡，写死
LAPTOP = "laptop"
LAPTOP_URL = "http://127.0.0.1:8188"
TARGETS = (LAPTOP, "gpu3:0", "gpu3:1", "gpu3:3")

IDLE_WINDOW_S = 120
IDLE_MEM_MB = 1024
IDLE_UTIL = 5
GPU3_JOB_LIMIT_S = 15 * 60                       # 协议：单任务 ≤ 15 分钟（锁 TTL 1200 s）
LAPTOP_JOB_LIMIT_S = 60 * 60
LOCK_TTL_S = 1200
MAX_TIMEOUTS = 2
MAX_SIDE = 1536
POLL_S = 60

# 笔记本上有这些进程在跑就不抢（只看 python/uv/cmd/powershell 的命令行）
LAPTOP_BUSY_RE = re.compile(
    r"render_batch|[\\/ ]gen_[a-z0-9_]+\.py|run_adult_batch|ai[-_]toolkit|kohya|musubi|train_network|"
    r"[\\/ ]train[a-z_]*\.py|(^|[\\/ ])training[\\/]", re.I)
LAPTOP_PROC_NAMES = ("python.exe", "pythonw.exe", "uv.exe", "cmd.exe", "powershell.exe", "pwsh.exe")

SHOT_KEYS = {"shot", "shot_id", "episode", "ep", "first_frame", "last_frame", "frames", "video", "motion"}
SHOT_KINDS = {"frame", "first_frame", "last_frame", "frames", "video", "i2v", "fl2v", "fl2va", "h3", "shot"}
ADULT_RATINGS = {"adult", "nsfw", "explicit", "r18", "x"}
REQUIRED = ("prompt", "seed", "size", "model", "file", "out_dir")
MODES = ("t2i", "edit")
UPSCALE_METHODS = ("lanczos", "bicubic", "bilinear", "nearest-exact", "area")


def ref_path(r: str) -> Path:
    """参考图路径：仓库相对路径（g2_candidates 写的格式）或绝对路径。"""
    p = Path(r)
    return p if p.is_absolute() else ROOT / p

_log_lock = threading.Lock()


def log(msg: str):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with _log_lock:
        print(line, flush=True)
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# ======================================================================== 任务文件与校验
def load_jobs(doc: dict) -> tuple[dict, list[dict]]:
    """返回 (文件级元数据, 子任务列表)。单任务文件 = 没有 "jobs" 键的对象。"""
    if isinstance(doc.get("jobs"), list):
        meta = {k: v for k, v in doc.items() if k not in ("jobs", "_gpu_grab")}
        return meta, [dict(j) for j in doc["jobs"]]
    return {}, [{k: v for k, v in doc.items() if k != "_gpu_grab"}]


def _ownership(path: Path = OWNERSHIP) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("projects", {})
    except (OSError, ValueError):
        return {}


def _is_adult(d: dict) -> bool:
    if any(d.get(k) is True for k in ("adult", "nsfw", "explicit", "adult_shot", "is_adult")):
        return True
    return str(d.get("rating", "")).strip().lower() in ADULT_RATINGS


def refuse_reason(meta: dict, job: dict, ownership: dict | None = None) -> str | None:
    """不该由本任务器跑的任务 → 拒绝原因；可以跑 → None。"""
    ownership = _ownership() if ownership is None else ownership
    # 2026-10-30 项目方取消成人过滤器：不再按 adult/nsfw 标记拒绝任务
    kind = str(job.get("kind") or job.get("type") or meta.get("kind") or "t2i").lower()
    shot_like = (kind in SHOT_KINDS or SHOT_KEYS & set(job) or SHOT_KEYS & set(meta)
                 or re.search(r"(^|/)(renders(_gpu3)?|frames|run)(/|$)", str(job.get("out_dir", "")).replace("\\", "/")))
    if shot_like:
        proj = str(job.get("project") or meta.get("project") or "")
        text = json.dumps({**meta, **job}, ensure_ascii=False).lower()
        for slug, o in ownership.items():
            if o.get("owner") == "gpu3" and (proj == slug or slug in text):
                return f"shot frame/video job for '{slug}' — config/shot_ownership.json: owner=gpu3（gpu3 渲染器负责）"
        return "shot frame/video job — 本任务器只跑资产/候选（assets/candidates only）"
    if "video" in kind:
        return f"unsupported kind '{kind}' (images only; never video)"
    mode = str(job.get("mode", "t2i")).lower()
    if mode not in MODES:
        return f"unsupported mode '{mode}' (t2i / edit only; never video)"
    missing = [k for k in REQUIRED if job.get(k) in (None, "", [])]
    if missing:
        return f"missing fields: {missing}"
    if mode == "edit":
        refs = job.get("refs") or []
        if not refs or not isinstance(refs, list):
            return "edit job needs refs: [path, ...]"
        for r in refs:
            if not ref_path(r).is_file():
                return f"reference missing: {r}"
        want = (job.get("reference") or {}).get("sha256") if isinstance(job.get("reference"), dict) else None
        if want and len(refs) == 1 and _sha(ref_path(refs[0])) != want:
            return f"reference sha256 mismatch: {refs[0]}"
    ref = job.get("refine")
    if ref is not None and not isinstance(ref, dict):
        return "refine must be an object"
    if isinstance(ref, dict) and ref.get("upscale_to") is not None:
        try:
            uw, uh = (int(x) for x in ref["upscale_to"])
            assert 256 <= uw <= 3072 and 256 <= uh <= 3072
        except Exception:  # noqa: BLE001
            return f"bad refine.upscale_to {ref.get('upscale_to')}"
        if str(ref.get("upscale_method", "lanczos")) not in UPSCALE_METHODS:
            return f"bad refine.upscale_method {ref.get('upscale_method')}"
    try:
        w, h = (int(x) for x in job["size"])
        assert 256 <= w <= 2048 and 256 <= h <= 2048
    except Exception:  # noqa: BLE001
        return f"bad size {job.get('size')}"
    out = (ROOT / job["out_dir"]).resolve()
    if ROOT.resolve() not in out.parents and out != ROOT.resolve():
        return f"out_dir outside project: {job['out_dir']}"
    if Path(job["file"]).name != job["file"] or not job["file"].lower().endswith(".png"):
        return f"file must be a bare .png name: {job['file']}"
    t = job.get("targets", meta.get("targets"))
    if t is not None:
        bad = [x for x in t if x not in TARGETS]
        if bad:
            return f"bad targets {bad} (allowed {TARGETS}; gpu3:2 never)"
    return None


def job_targets(meta: dict, job: dict) -> tuple[str, ...]:
    t = job.get("targets", meta.get("targets"))
    return tuple(x for x in (t or TARGETS) if x in TARGETS)


# ======================================================================== 空闲判断（纯函数，测试用假数据）
class IdleTracker:
    """每张卡记录"连续空闲从何时开始"；连续空闲满 window_s 才算空闲。"""

    def __init__(self, window_s: float = IDLE_WINDOW_S, mem_mb: int = IDLE_MEM_MB, util: int = IDLE_UTIL):
        self.window_s, self.mem_mb, self.util = window_s, mem_mb, util
        self.since: dict[int, float | None] = {}

    def record(self, now: float, smi: dict[int, tuple[int, int]]):
        for g, (mem, util) in smi.items():
            if mem < self.mem_mb and util < self.util:
                if self.since.get(g) is None:
                    self.since[g] = now
            else:
                self.since[g] = None
        for g in list(self.since):
            if g not in smi:
                self.since[g] = None

    def idle(self, g: int, now: float) -> bool:
        s = self.since.get(g)
        return s is not None and now - s >= self.window_s


def gpu3_local_block(g: int, files: dict[str, str | None]) -> str | None:
    """本地能看出的阻挡（may-use 之外的保险）：锁、lend、assign 文件。"""
    if g in NEVER:
        return "GPU2 faulty: never used"
    for n in (f"gpu.lock.gpu{g}", f"train.lock.gpu{g}", f"train.lock.{g}"):
        if n in files:
            return f"{n}: {(files[n] or '').strip()[:60]}"
    if f"lend.gpu{g}" in files:
        return f"lend.gpu{g}: {(files[f'lend.gpu{g}'] or '').strip()[:60]}"
    if f"assign.gpu{g}.json" in files:
        return f"assign.gpu{g}.json present"
    return None


def gpu3_free(g: int, snap: dict, tracker: IdleTracker, now: float) -> str | None:
    """None = 本地条件允许（还要再问 may-use）。"""
    b = gpu3_local_block(g, snap.get("files", {}))
    if b:
        return b
    if g not in snap.get("smi", {}):
        return "no nvidia-smi data"
    if not tracker.idle(g, now):
        mem, util = snap["smi"][g]
        return f"not idle ≥{tracker.window_s:.0f}s (now {mem} MiB, {util}%)"
    return None


def laptop_free(queue: dict | None, procs: list[str], lock_holder: dict | None = None) -> str | None:
    """lock_holder：本机 ComfyUI 单一锁（ns_orch.comfy_lock，data/comfy.lock）的占用者；被画布 / 编排器占着就不抢（X-1）"""
    if lock_holder:
        return f"laptop ComfyUI held via comfy.lock by {lock_holder.get('who', 'unknown')}" + \
            (f" ({lock_holder['what']})" if lock_holder.get("what") else "")
    if queue is None:
        return "laptop ComfyUI unreachable"
    if queue.get("queue_running") or queue.get("queue_pending"):
        return f"laptop ComfyUI busy (running {len(queue.get('queue_running', []))}, " \
               f"pending {len(queue.get('queue_pending', []))})"
    if procs:
        return f"laptop busy: {procs[0][:100]}"
    return None


def lock_text(job_id: str) -> str:
    return f"{ME} {re.sub(r'[^A-Za-z0-9_.:/-]+', '_', job_id)[:100]}"


# ======================================================================== 真实环境：gpu3（ssh）与笔记本
_SNAPSHOT_PY = r"""
import json, os, subprocess, time
ST = %r
out = {"now": time.time(), "files": {}, "smi": {}}
for n in os.listdir(ST):
    if n.startswith(("gpu.lock.", "lend.", "train.lock.", "assign.gpu")):
        try:
            p = os.path.join(ST, n)
            out["files"][n] = open(p, errors="replace").read()[:300]
            out.setdefault("ages", {})[n] = time.time() - os.stat(p).st_mtime
        except OSError:
            out["files"][n] = None
r = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                   capture_output=True, text=True, timeout=30)
for line in r.stdout.splitlines():
    i, m, u = [x.strip() for x in line.split(",")]
    out["smi"][i] = [int(m), int(u)]
print(json.dumps(out))
""" % STATE_DIR


class Gpu3:
    """gpu3 的全部远程操作都在这里（测试里换成假的）。"""

    def __init__(self, host: str = SSH_HOST):
        self.host = host

    def _ssh(self, cmd: str, timeout: float = 60, inp: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", self.host, cmd],
                              input=inp, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")

    def snapshot(self) -> dict | None:
        try:
            r = self._ssh("python3 -", inp=_SNAPSHOT_PY)
            d = json.loads(r.stdout)
            d["smi"] = {int(k): tuple(v) for k, v in d["smi"].items()}
            return d
        except Exception as e:  # noqa: BLE001
            log(f"gpu3 snapshot failed: {type(e).__name__}: {str(e)[:200]}")
            return None

    def may_use(self, g: int) -> tuple[bool, str]:
        """协议：退出码 0 = 可以用；其他（含 ssh 失败、超时）= 不可以。"""
        try:
            r = self._ssh(f"{SCHED} may-use {CONSUMER} {int(g)}", timeout=90)
        except Exception as e:  # noqa: BLE001
            return False, f"may-use error: {type(e).__name__}"
        return r.returncode == 0, (r.stdout + r.stderr).strip()[:200] or f"exit {r.returncode}"

    def acquire(self, g: int, text: str) -> bool:
        """O_EXCL（bash noclobber）创建 gpu.lock.gpuN；lend/train.lock/assign 存在时不建。从不写 lend。"""
        q, d = shlex.quote(text), shlex.quote(STATE_DIR)
        # 全部绝对路径；状态目录不存在就退出——绝不在当前目录/家目录写锁
        cmd = (f"[ -d {d} ] || {{ echo NOSTATE; exit 3; }}; "
               f"for f in train.lock.gpu{g} train.lock.{g} lend.gpu{g} assign.gpu{g}.json; do "
               f"[ -e {d}/$f ] && {{ echo BUSY $f; exit 2; }}; done; "
               f"( set -C; printf '%s\\n' {q} > {d}/gpu.lock.gpu{g} ) 2>/dev/null && echo OK || {{ echo BUSY lock; exit 2; }}")
        try:
            r = self._ssh(f"bash -c {shlex.quote(cmd)}")
        except Exception:  # noqa: BLE001
            return False
        return r.returncode == 0 and "OK" in r.stdout

    def holds(self, g: int, text: str) -> bool:
        try:
            r = self._ssh(f"cat {STATE_DIR}/gpu.lock.gpu{g}")
        except Exception:  # noqa: BLE001
            return False
        return r.returncode == 0 and r.stdout.strip() == text

    def release(self, g: int, text: str) -> bool:
        """只删内容与自己写的完全一致的锁。"""
        q = shlex.quote(text)
        cmd = (f"f={shlex.quote(STATE_DIR + f'/gpu.lock.gpu{g}')}; [\"$(cat $f 2>/dev/null)\" = {q} ] && rm -f $f && echo RELEASED; "
               f"[ -e $f ] || echo GONE")
        for _ in range(3):
            try:
                r = self._ssh(f"bash -c {shlex.quote(cmd)}")
                if "RELEASED" in r.stdout or "GONE" in r.stdout:
                    return True
                return False      # 文件在但不是我们的：不碰
            except Exception:  # noqa: BLE001
                time.sleep(5)
        return False

    def remove_own_stale(self, snap: dict, ttl: float = LOCK_TTL_S):
        """上次崩溃留下的自己的锁（文本以 'fredw-d9 ' 开头、超过 TTL）——只删自己的。"""
        for n, txt in (snap or {}).get("files", {}).items():
            m = re.fullmatch(r"gpu\.lock\.gpu(\d)", n)
            if m and txt and txt.startswith(ME + " ") and snap.get("ages", {}).get(n, 0) > ttl:
                log(f"gpu3: removing own stale lock {n} ({txt.strip()})")
                self.release(int(m.group(1)), txt.strip())

    def tunnel(self, g: int) -> "Tunnel":
        return Tunnel(self.host, GPU3_PORTS[g])


class Tunnel:
    """ssh -N -L <本地空闲端口>:127.0.0.1:<gpu3 端口>"""

    def __init__(self, host: str, remote_port: int):
        self.host, self.remote_port = host, remote_port
        self.proc: subprocess.Popen | None = None
        self.port = 0

    def __enter__(self) -> str:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-N", "-L",
                                      f"{self.port}:127.0.0.1:{self.remote_port}", self.host],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return f"http://127.0.0.1:{self.port}"
            except OSError:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.5)
        self.__exit__()
        raise RuntimeError(f"ssh tunnel to gpu3:{self.remote_port} failed")

    def __exit__(self, *a):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def _comfy_lock():
    """本机 ComfyUI 单一锁模块（T44）；导入不了（环境缺包）时返回 None，退回只看队列"""
    try:
        from ns_orch import comfy_lock
        return comfy_lock
    except Exception:  # noqa: BLE001
        return None


class Laptop:
    def lock_holder(self) -> dict | None:
        cl = _comfy_lock()
        return cl.holder() if cl else None

    def queue(self) -> dict | None:
        import urllib.request
        try:
            with urllib.request.urlopen(LAPTOP_URL + "/queue", timeout=10) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001
            return None

    def busy_procs(self) -> list[str]:
        ps = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                               timeout=60, encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ["process list unavailable"]
        return filter_busy(r.stdout.splitlines(), os.getpid())


def filter_busy(lines: list[str], own_pid: int) -> list[str]:
    out = []
    for line in lines:
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        pid, name, cmd = parts
        if not pid.strip().isdigit() or int(pid) == own_pid or name.lower() not in LAPTOP_PROC_NAMES:
            continue
        if "gpu_grab" in cmd:
            continue
        if LAPTOP_BUSY_RE.search(cmd):
            out.append(f"{name}#{pid}: {cmd.strip()}")
    return out


# ======================================================================== 出图（ComfyUI）
class QCFail(RuntimeError):
    pass


class JobTimeout(RuntimeError):
    pass


_qc_lock = threading.Lock()
_manifest_lock = threading.Lock()


def build_graphs(job: dict, prefix: str, ref_names: list[str] | None = None):
    """返回 (第一遍工作流, refine 函数或 None)。提示词/负面词严格按任务原文，不增删。
    mode=edit：ref_names 为已上传到 ComfyUI 的参考图名（依次为 图1、图2…），同 tools/gen_assets.run_job
    （本地预缩放到长边 1024，ref_resolution=0、crop=False）。"""
    from ns_render import workflows as W
    model = job["model"]
    turbo = "turbo" in model.lower()
    m = W.QwenModel(unet=model, clip=job.get("clip", W.QwenModel.clip), vae=job.get("vae", W.QwenModel.vae),
                    turbo=turbo, steps=int(job.get("steps", 25)), cfg=float(job.get("cfg", 2.5)),
                    sampler=job.get("sampler", "euler"))
    loras = [(str(n), float(s)) for n, s in job.get("lora", []) or []]
    w, h = (int(x) for x in job["size"])
    neg = job.get("negative", "")
    refs = list(ref_names or [])
    edit = str(job.get("mode", "t2i")).lower() == "edit"
    if edit and not refs:
        raise ValueError("edit job without uploaded references")

    def graph(width, height, seed, pfx, mm):
        if edit:
            return W.qwen_edit(job["prompt"], neg, refs if len(refs) > 1 else refs[0], width, height, seed, pfx,
                               m=mm, loras=loras, ref_resolution=0, crop=False)
        return W.qwen_t2i(job["prompt"], neg, width, height, seed, pfx, m=mm, loras=loras)

    wf = graph(w, h, int(job["seed"]), prefix, m)
    ref = job.get("refine")
    if not ref:
        return wf, None

    def refine(first_pass_name: str) -> dict:
        # 同 tools/gen_assets.refine_graph：放大 → VAEEncode → Base 少步数低重绘（edit 时带同样的参考图）
        base = model if not turbo else "qwen_image_2.1_int8_convrot.safetensors"
        m2 = W.QwenModel(unet=base, clip=m.clip, vae=m.vae, turbo=False, steps=int(ref.get("steps", 12)),
                         cfg=m.cfg, sampler=m.sampler)
        if ref.get("upscale_to"):          # 场景底板：指定第二遍尺寸（gen_scenes 928×1632 → 1152×2016）
            W2, H2 = (int(x) for x in ref["upscale_to"])
        else:
            sc = float(ref.get("scale", 1.5))
            W2, H2 = int(w * sc) // 16 * 16, int(h * sc) // 16 * 16
        wf2 = graph(W2, H2, int(job["seed"]) + 1, prefix + "_r", m2)
        wf2["201"] = {"class_type": "LoadImage", "inputs": {"image": first_pass_name}}
        wf2["202"] = {"class_type": "ImageScale", "inputs": {"image": ["201", 0],
                                                             "upscale_method": str(ref.get("upscale_method", "lanczos")),
                                                             "width": W2, "height": H2, "crop": "disabled"}}
        wf2["203"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["202", 0], "vae": ["12", 0]}}
        wf2["40"]["inputs"]["latent_image"] = ["203", 0]
        wf2["37"]["inputs"].update({"steps": int(ref.get("steps", 12)), "denoise": float(ref.get("denoise", 0.3))})
        wf2.pop("34", None)
        return wf2
    return wf, refine


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def prep_ref(p: Path, side: int = 1024) -> Path:
    """参考图预缩放到长边 side（同 gen_assets.prep_ref），缓存在 data/jobs/.refcache/。"""
    from PIL import Image
    out = JOBS / ".refcache" / f"{_sha(p)[:16]}_{side}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(p).convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        im.save(out)
    return out


def clamp_side(job: dict) -> int | None:
    """输出长边上限：指定 max_side 就用它；refine.upscale_to（场景底板，finalize 自己裁）不缩；否则 1536（同 gen_assets）。"""
    if job.get("max_side"):
        return int(job["max_side"])
    if isinstance(job.get("refine"), dict) and job["refine"].get("upscale_to"):
        return None
    return MAX_SIDE


def _read_manifest(mp: Path):
    """list（资产/候选目录）或 dict（assets/scenes/<id>/manifest.json）。读不懂就报错——绝不覆盖。"""
    if not mp.exists():
        return []
    man = json.loads(mp.read_text(encoding="utf-8"))
    if not isinstance(man, (list, dict)):
        raise ValueError(f"{mp}: unexpected manifest type {type(man).__name__}")
    return man


def manifest_has(job: dict) -> bool:
    out = ROOT / job["out_dir"]
    try:
        man = _read_manifest(out / "manifest.json")
    except (OSError, ValueError):
        return False
    entries = man if isinstance(man, list) else list((man.get("renders") or {}).values())
    return (out / job["file"]).exists() and any(
        e.get("file") == job["file"] and e.get("seed") == job["seed"] and e.get("prompt") == job["prompt"]
        for e in entries if isinstance(e, dict))


def write_manifest(out_dir: Path, entry: dict):
    """list 清单：按文件名替换/追加。dict 清单（场景底板，gen_scenes 的 queued/variants 结构）：只写
    man["renders"][file]，其他键（queued、variants、确认字段）一律不动，finalize 照常工作。"""
    with _manifest_lock:
        mp = out_dir / "manifest.json"
        man = _read_manifest(mp)
        if isinstance(man, list):
            man = [e for e in man if not (isinstance(e, dict) and e.get("file") == entry["file"])] + [entry]
        else:
            man.setdefault("renders", {})[entry["file"]] = entry
        tmp = mp.with_name(mp.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, mp)


def comfy_execute(job: dict, base_url: str, limit_s: float, target: str, job_id: str) -> dict:
    """在 base_url 的 ComfyUI 上出一张图 → QC v3（硬失败）→ 写 out_dir + manifest。返回 manifest 条目。
    job["post"]（场景底板的裁切/调色说明）只原样记进清单，本任务器不执行（笔记本 tools/gen_scenes.py finalize 做）。"""
    from PIL import Image
    from ns_render.comfy_client import ComfyClient
    from ns_render.qc import nudity_qc, vlm_judge

    deadline = time.monotonic() + limit_s
    client = ComfyClient(base_url)
    out_dir = ROOT / job["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    _read_manifest(out_dir / "manifest.json")           # 清单读不懂就别出图
    dest = out_dir / job["file"]
    tmp = out_dir / f".{Path(job['file']).stem}.gpu_grab.png"
    prefix = f"ns_final/gpu_grab/{Path(job['file']).stem}"
    refs = [ref_path(r) for r in job.get("refs") or []] if str(job.get("mode", "t2i")).lower() == "edit" else []
    names = [client.upload_image(prep_ref(r), subfolder="ns_final/gpu_grab") for r in refs]
    wf, refine = build_graphs(job, prefix, names)

    def run(graph):
        left = deadline - time.monotonic()
        if left <= 5:
            client.interrupt()
            raise JobTimeout(f"over {limit_s:.0f}s")
        try:
            return client.run(graph, timeout_s=left)
        except Exception as e:  # noqa: BLE001
            if "超时" in str(e):
                raise JobTimeout(f"over {limit_s:.0f}s") from e
            raise

    t0 = time.monotonic()
    entry, _ = run(wf)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    client.download(item, tmp)
    if refine:
        name = client.upload_image(tmp, subfolder="ns_final/gpu_grab")
        entry, _ = run(refine(name))
        item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
        client.download(item, tmp)
    secs = time.monotonic() - t0
    side = clamp_side(job)
    im = Image.open(tmp)
    if side and max(im.size) > side:
        im.thumbnail((side, side), Image.LANCZOS)
        im.save(tmp)
    size = list(im.size)
    im.close()
    with _qc_lock:     # NudeNet/CLIP 在本机跑；看图模型用同一台 ComfyUI。只记录，不淘汰（过滤器已取消）
        q = nudity_qc(tmp, vlm=vlm_judge(client))
    os.replace(tmp, dest)
    keep = {k: v for k, v in job.items() if k not in ("targets",)}
    m = {**keep, "file": dest.name, "sha256": _sha(dest), "output_size": size, "qc": q, "gen_seconds": round(secs, 1),
         "references_sha256": [_sha(r) for r in refs], "gpu": target, "runner": "tools/gpu_grab.py",
         "job_id": job_id, "requested_by": job.get("requested_by", ME),
         "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_manifest(out_dir, m)
    return m


# ======================================================================== 调度
@dataclass
class Claimed:
    path: Path                      # data/jobs/running/<name>
    doc: dict
    meta: dict
    jobs: list[dict]
    state: dict = field(default_factory=dict)   # doc["_gpu_grab"]

    @property
    def name(self) -> str:
        return self.path.stem

    def pending(self) -> list[int]:
        res = self.state.setdefault("results", {})
        return [i for i in range(len(self.jobs)) if res.get(str(i), {}).get("status") not in ("ok", "failed")]

    def save(self):
        self.doc["_gpu_grab"] = self.state
        self.path.write_text(json.dumps(self.doc, ensure_ascii=False, indent=1), encoding="utf-8")


class Runner:
    def __init__(self, gpu3: Gpu3 | None = None, laptop: Laptop | None = None, execute=comfy_execute,
                 use_gpu3: bool = True, use_laptop: bool = True, tracker: IdleTracker | None = None,
                 ownership: dict | None = None, clock=time.time):
        self.gpu3 = gpu3 if gpu3 is not None else (Gpu3() if use_gpu3 else None)
        self.laptop = laptop if laptop is not None else (Laptop() if use_laptop else None)
        self.use_gpu3, self.use_laptop = use_gpu3 and self.gpu3 is not None, use_laptop and self.laptop is not None
        self.execute = execute
        self.tracker = tracker or IdleTracker()
        self.ownership = ownership
        self.clock = clock
        self.busy: set[str] = set()             # 本进程正在用的卡
        self.threads: dict[str, threading.Thread] = {}
        self.snap: dict | None = None
        self._lock = threading.Lock()
        for d in (QUEUE, RUNNING, DONE, FAILED):
            d.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 队列
    def recover(self):
        """上次被打断留在 running/ 的文件放回队列（进度在 _gpu_grab 里，已完成的子任务不重跑）。"""
        for p in sorted(RUNNING.glob("*.json")):
            os.replace(p, QUEUE / p.name)
            log(f"recover: {p.name} running/ -> queue/")

    def queue_files(self) -> list[Path]:
        return sorted(QUEUE.glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name))

    def _finish(self, c: Claimed, dest_dir: Path, why: str):
        c.state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        c.save()
        os.replace(c.path, dest_dir / c.path.name)
        log(f"{c.path.name} -> {dest_dir.name}/ ({why})")

    def screen(self, p: Path) -> Claimed | None:
        """读 + 校验；被拒的直接进 failed/。返回未认领的 Claimed（path 仍在 queue/）。"""
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            meta, jobs = load_jobs(doc)
        except (OSError, ValueError, AttributeError) as e:
            self._reject(p, None, f"unreadable: {e}")
            return None
        if not jobs:
            self._reject(p, doc, "no jobs")
            return None
        for i, j in enumerate(jobs):
            r = refuse_reason(meta, j, self.ownership)
            if r:
                self._reject(p, doc, f"job[{i}] {j.get('file', '?')}: {r}")
                return None
        return Claimed(p, doc, meta, jobs, dict(doc.get("_gpu_grab") or {}))

    def _reject(self, p: Path, doc: dict | None, reason: str):
        log(f"REFUSE {p.name}: {reason}")
        dest = FAILED / p.name
        if doc is None:
            os.replace(p, dest)
            return
        doc["_gpu_grab"] = {**(doc.get("_gpu_grab") or {}), "refused": reason,
                            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        dest.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        p.unlink()

    def pick_file(self, target: str) -> Claimed | None:
        for p in self.queue_files():
            c = self.screen(p)
            if not c:
                continue
            if not any(target in job_targets(c.meta, c.jobs[i]) for i in c.pending()):
                continue
            dest = RUNNING / p.name
            try:
                os.replace(p, dest)
            except OSError:
                continue
            c.path = dest
            return c
        return None

    # ---------------------------------------------------------------- 卡
    def sample_gpu3(self) -> dict | None:
        if not self.use_gpu3:
            return None
        snap = self.gpu3.snapshot()
        if snap:
            self.tracker.record(self.clock(), snap["smi"])
            self.snap = snap
        return snap

    def free_targets(self) -> dict[str, str | None]:
        """各卡 -> None（可抢）或原因。gpu3 只做本地判断，真正领用前每个任务再问 may-use。"""
        out: dict[str, str | None] = {}
        if self.use_laptop:
            out[LAPTOP] = "in use by gpu_grab" if LAPTOP in self.busy else \
                laptop_free(self.laptop.queue(), self.laptop.busy_procs(), self.laptop.lock_holder())
        if self.use_gpu3:
            now = self.clock()
            for g in GPU3_PORTS:
                t = f"gpu3:{g}"
                if t in self.busy:
                    out[t] = "in use by gpu_grab"
                elif not self.snap:
                    out[t] = "no gpu3 snapshot"
                else:
                    out[t] = gpu3_free(g, self.snap, self.tracker, now)
        return out

    # ---------------------------------------------------------------- 一个文件在一张卡上
    def work(self, target: str, c: Claimed):
        try:
            self._work(target, c)
        except Exception as e:  # noqa: BLE001
            log(f"ERROR worker {target} {c.name}: {type(e).__name__}: {str(e)[:300]}")
            if c.path.exists():
                c.save()
                os.replace(c.path, QUEUE / c.path.name)
        finally:
            with self._lock:
                self.busy.discard(target)

    def _work(self, target: str, c: Claimed):
        res = c.state.setdefault("results", {})
        gpu = int(target.split(":")[1]) if target.startswith("gpu3:") else None
        yielded = None
        for i in c.pending():
            job = c.jobs[i]
            if target not in job_targets(c.meta, job):
                continue
            job_id = f"{c.name}:{job['file']}"
            if manifest_has(job):
                res[str(i)] = {"status": "ok", "note": "already in manifest", "gpu": target}
                c.save()
                continue
            if gpu is None:
                yielded = self._run_laptop(c, i, job, job_id, target)
            else:
                yielded = self._run_gpu3(c, i, job, job_id, gpu)
            c.save()
            if yielded:
                break
        if c.pending():
            c.save()
            os.replace(c.path, QUEUE / c.path.name)
            log(f"{c.path.name}: {len(c.pending())} job(s) left -> queue/ ({yielded or 'other targets'})")
            return
        bad = [k for k, v in res.items() if v.get("status") == "failed"]
        self._finish(c, FAILED if bad else DONE, f"{len(res) - len(bad)} ok, {len(bad)} failed")

    def _run_laptop(self, c: Claimed, i: int, job: dict, job_id: str, target: str) -> str | None:
        """本机 ComfyUI 与画布队列 / 编排器共用一把 comfy.lock（X-1）：拿不到就让出，任务回队列下一轮再试（不计失败）"""
        cl = _comfy_lock()
        if cl is None:
            return self._run_one(c, i, job, job_id, target, LAPTOP_URL, LAPTOP_JOB_LIMIT_S)
        try:
            fh = cl.acquire("gpu_grab", job_id, timeout=0)
        except cl.Busy as e:
            log(f"laptop: comfy.lock busy before {job_id}: {e}")
            return f"laptop comfy.lock busy ({(e.info or {}).get('who', 'unknown')})"
        try:
            return self._run_one(c, i, job, job_id, target, LAPTOP_URL, LAPTOP_JOB_LIMIT_S)
        finally:
            cl.release(fh)

    def _run_gpu3(self, c: Claimed, i: int, job: dict, job_id: str, g: int) -> str | None:
        ok, why = self.gpu3.may_use(g)
        if not ok:
            log(f"gpu3:{g} may-use refused before {job_id}: {why}")
            return f"gpu3:{g} not allowed: {why}"
        text = lock_text(job_id)
        if not self.gpu3.acquire(g, text):
            log(f"gpu3:{g} lock not acquired for {job_id}")
            return f"gpu3:{g} lock taken"
        log(f"gpu3:{g} LOCK '{text}'")
        try:
            with self.gpu3.tunnel(g) as url:
                if not _remote_queue_empty(url):
                    return f"gpu3:{g} ComfyUI queue not empty"
                r = self._run_one(c, i, job, job_id, f"gpu3:{g}", url, GPU3_JOB_LIMIT_S)
                _free(url)          # 卸载模型，卡回到 <1 GB，别人好判断空闲
                return r
        finally:
            released = self.gpu3.release(g, text)
            log(f"gpu3:{g} UNLOCK '{text}'" + ("" if released else " (FAILED — lock TTL 1200 s will expire it)"))

    def _run_one(self, c: Claimed, i: int, job: dict, job_id: str, target: str, url: str, limit: float) -> str | None:
        res = c.state.setdefault("results", {})
        log(f"RUN {job_id} on {target}")
        try:
            m = self.execute(job, url, limit, target, job_id)
            res[str(i)] = {"status": "ok", "gpu": target, "sha256": m.get("sha256"), "gen_seconds": m.get("gen_seconds"),
                           "qc": m.get("qc"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            log(f"OK {job_id} on {target} {m.get('gen_seconds')}s -> {job['out_dir'].rstrip('/')}/{job['file']}")
            return None
        except QCFail as e:
            res[str(i)] = {"status": "failed", "gpu": target, "error": str(e)[:600]}
            log(f"QC FAIL {job_id}: {str(e)[:300]}")
            return None
        except JobTimeout as e:
            r = res.setdefault(str(i), {})
            r["timeouts"] = r.get("timeouts", 0) + 1
            r["last_error"] = f"timeout on {target}: {e}"
            if r["timeouts"] >= MAX_TIMEOUTS:
                r["status"] = "failed"
            log(f"TIMEOUT {job_id} on {target} ({r['timeouts']}/{MAX_TIMEOUTS}) -> requeue")
            return f"timeout on {target}"
        except Exception as e:  # noqa: BLE001
            from ns_render.comfy_client import ComfyUnavailable
            if isinstance(e, (ComfyUnavailable, OSError)):
                log(f"UNAVAILABLE {target} for {job_id}: {e}")
                return f"{target} unavailable"
            r = res.setdefault(str(i), {})
            r["errors"] = r.get("errors", 0) + 1
            r["last_error"] = f"{type(e).__name__}: {str(e)[:400]}"
            if r["errors"] >= 2:
                r["status"] = "failed"
            log(f"ERROR {job_id} on {target}: {r['last_error']}")
            return None

    # ---------------------------------------------------------------- 一轮
    def start_free(self, free: dict[str, str | None], wait: bool) -> int:
        order = [t for t in ("gpu3:1", "gpu3:3", "gpu3:0", LAPTOP) if free.get(t) is None and t in free]
        started = 0
        for t in order:
            c = self.pick_file(t)
            if not c:
                continue
            with self._lock:
                self.busy.add(t)
            th = threading.Thread(target=self.work, args=(t, c), name=f"grab-{t}", daemon=False)
            self.threads[t] = th
            th.start()
            started += 1
        if wait:
            for th in list(self.threads.values()):
                th.join()
        return started

    def once(self, sample_s: float = IDLE_WINDOW_S, step_s: float = 15) -> int:
        self.recover()
        if not self.queue_files():
            log("once: queue empty")
            return 0
        if self.use_gpu3:
            snap = self.sample_gpu3()
            if snap:
                self.gpu3.remove_own_stale(snap)
            # 只在笔记本不空闲时为 gpu3 采满 2 分钟
            if not (self.use_laptop and self.free_targets().get(LAPTOP) is None):
                t_end = time.monotonic() + sample_s
                while time.monotonic() < t_end:
                    time.sleep(step_s)
                    self.sample_gpu3()
        free = self.free_targets()
        log("once: " + "; ".join(f"{k}={'FREE' if v is None else v}" for k, v in free.items()))
        n = self.start_free(free, wait=True)
        log(f"once: started {n} worker(s); queue now {len(self.queue_files())} file(s)")
        return n

    def watch(self, poll_s: float = POLL_S):
        self.recover()
        log(f"watch: polling every {poll_s:.0f}s (gpu3={'on' if self.use_gpu3 else 'off'}, "
            f"laptop={'on' if self.use_laptop else 'off'})")
        first = True
        while True:
            try:
                if self.queue_files():
                    snap = self.sample_gpu3()
                    if first and snap:
                        self.gpu3.remove_own_stale(snap)
                        first = False
                    free = self.free_targets()
                    if any(v is None for v in free.values()):
                        self.start_free(free, wait=False)
            except Exception as e:  # noqa: BLE001
                log(f"watch loop error: {type(e).__name__}: {str(e)[:300]}")
            time.sleep(poll_s)


def _remote_queue_empty(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url + "/queue", timeout=15) as r:
            q = json.loads(r.read())
        return not q.get("queue_running") and not q.get("queue_pending")
    except Exception:  # noqa: BLE001
        return False


def _free(url: str):
    try:
        from ns_render.comfy_client import ComfyClient
        ComfyClient(url).free(unload_models=True)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    mode.add_argument("--status", action="store_true", help="只报告各卡状态（会采样 2 分钟 gpu3 空闲）")
    ap.add_argument("--no-gpu3", action="store_true")
    ap.add_argument("--no-laptop", action="store_true")
    ap.add_argument("--poll", type=float, default=POLL_S)
    a = ap.parse_args(argv)
    r = Runner(use_gpu3=not a.no_gpu3, use_laptop=not a.no_laptop)
    if a.status:
        for _ in range(int(IDLE_WINDOW_S // 15) + 1):
            r.sample_gpu3()
            time.sleep(15) if r.use_gpu3 else None
        for t, v in r.free_targets().items():
            extra = ""
            if v is None and t.startswith("gpu3:"):
                ok, why = r.gpu3.may_use(int(t[-1]))
                extra = f"  may-use: {'yes' if ok else 'no'} ({why})"
            print(f"{t:8s} {'FREE' if v is None else v}{extra}")
        return 0
    if a.once:
        r.once()
    else:
        r.watch(a.poll)
    return 0


if __name__ == "__main__":
    sys.exit(main())
