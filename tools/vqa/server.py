#!/usr/bin/env python3
"""VQA 本地看图服务（gpu36，owner = VQA；config/vqa.json model 段）。

只在本机（127.0.0.1:<port>）监听；图片只在 gpu36 本机进模型，绝不转发到任何外部 API（K-REV-V01）。
接口（JSON，UTF-8）：
  GET  /health                     → {loaded, gpu, queue, served, last_error, ...}
  POST /generate {system, text, images:[{b64|path, max_pixels?, label?}], max_new_tokens?, key?}
       → {text, seconds, gpu, cached}   （key = 调用方的缓存键；同 key 直接回缓存）
  POST /unload                     → 立即卸载（把卡还给出图）

让道（生产优先，任务书“yield mode”）：
  - 只用 config 里的卡（gpu36 GPU0 / GPU1，GPU2 是长镜头视频道，不用）；
  - 加载前要求：该卡 ComfyUI 队列（running + pending）为空、空闲 ≥ idle_s、显存空闲 ≥ need_free_mib；
    都不满足就排队等（调用方超时 = 调用方自己定），绝不 /free 别人的 ComfyUI；
  - 每做完一条都复查该卡 ComfyUI 队列：有活 → 立刻卸载让出；空闲 idle_unload_s 秒也卸载；
  - 不执行任何 nvidia-smi 改状态命令（只读 --query-gpu）。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
HERE = Path(__file__).resolve().parent
BASE = Path(os.environ.get("VQA_BASE", "/root/work/fredw/vqa"))
CFG = json.loads((HERE / "vqa.json").read_text(encoding="utf-8")) if (HERE / "vqa.json").exists() else {}
M = CFG.get("model") or {}
PORT = int(os.environ.get("VQA_PORT", M.get("port", 8870)))
GPUS = [int(g) for g in os.environ.get("VQA_GPUS", ",".join(str(g) for g in M.get("gpus", [0, 1]))).split(",") if g != ""]
COMFY = ({int(a): int(b) for a, b in (x.split(":") for x in os.environ["VQA_COMFY"].split(","))} if os.environ.get("VQA_COMFY")
         else {int(k): int(v) for k, v in (M.get("comfy_ports") or {"0": 8188, "1": 8189}).items()})
DEVICE = os.environ.get("VQA_DEVICE", "gpu")      # cpu = 只用 CPU（gpu33 出图卡常年满，视频道不能挤）：fp32，常驻，不碰 GPU
THREADS = int(os.environ.get("VQA_THREADS", 24))
NEED_MIB = int(os.environ.get("VQA_NEED_MIB", M.get("need_free_mib", 7800)))
IDLE_S = float(os.environ.get("VQA_IDLE_S", 20))
IDLE_UNLOAD_S = float(os.environ.get("VQA_IDLE_UNLOAD_S", M.get("idle_unload_s", 90)))
# LOCALGPU（11-01，总调度 fredw-2b 批，CONSENT VQAGATE → LOCALGPU）：笔记本 12 GB 单卡和本机 ComfyUI（18388，我们自己的）轮流用。
# VQA_FREE_COMFY=1 才生效（gpu36 不设 = 旧行为，绝不 /free 别人的 ComfyUI）：ComfyUI 队列空 ≥ IDLE_S 后，显存不够就先对本机
# ComfyUI POST /free 再加载；出图方提交前 POST /yield → 立即（推理中则推理完）卸载并重置空闲计时；每次切换记 switch.jsonl
FREE_COMFY = os.environ.get("VQA_FREE_COMFY") == "1"
SWITCH_LOG = Path(os.environ.get("VQA_SWITCH_LOG", str(BASE / "logs" / "switch.jsonl")))
_mlock = threading.RLock()                       # 加载 / 推理 / 卸载互斥（/yield 在 HTTP 线程里卸载）


def switch_log(ev: str, **kw):
    try:
        SWITCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SWITCH_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": ev, **kw}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def comfy_free(gpu: int) -> float | None:
    """本机 ComfyUI 卸模型、清显存（POST /free），等显存回到 NEED_MIB 以上（≤30 s）→ 耗时秒；没配端口 → None"""
    port = COMFY.get(gpu)
    if not port:
        return None
    t0 = time.time()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001
        log("comfy /free failed", e)
    while time.time() - t0 < 30 and free_mib().get(gpu, 0) < NEED_MIB:
        time.sleep(1)
    secs = round(time.time() - t0, 1)
    switch_log("comfy_free", gpu=gpu, secs=secs, free_mib=free_mib().get(gpu))
    return secs
SRC = BASE / "models" / "Qwen3-VL-8B-Instruct"
QDIR = BASE / "models" / "Qwen3-VL-8B-Instruct-nf4"
CACHE = BASE / "cache"
HB = Path(os.environ.get("VQA_HB", "/root/work/fredw/gpu_heartbeats/VQA-server.json"))
FORCE_GPU = os.environ.get("VQA_FORCE_GPU")
ATTN = os.environ.get("VQA_ATTN", "")                    # VQAGATE 11-01：注意力实现（sdpa / eager / 空 = transformers 默认）
# VQAGATE 11-01（本机 4080 12 GB）：服务端兜底上限——主图 / 参考图像素、输出 token 不超过这里（0 = 不限，按请求）
CAP_SUBJECT = int(os.environ.get("VQA_CAP_SUBJECT_PX", "0") or 0)
CAP_REF = int(os.environ.get("VQA_CAP_REF_PX", "0") or 0)
CAP_TOKENS = int(os.environ.get("VQA_CAP_TOKENS", "0") or 0)      # 只给标定 / 测试：指定卡，仍然遵守队列空闲

STATE = {"loaded": False, "gpu": None, "queue": 0, "served": 0, "last_error": None, "started": time.time(),
         "last_job": None, "load_s": None, "peak_mib": None, "waiting_since": None, "why_waiting": None}
JOBS: "queue.Queue[tuple[dict, queue.Queue]]" = queue.Queue()
# VQAGATE 11-01（总调度批）：让道模式下给看图留最短窗口——出图连续排队时看图会一直饿着（19:34–19:50 实测一条没跑成）。
# 出图方每次 /yield 计一张；满足任一 → 开窗口：出图每满 WIN_N 张、最老看图请求等满 WIN_WAIT_S、积压 ≥ WIN_BACKLOG。
# 窗口内 /yield 不立刻让，等窗口结束或积压清空（≤ WIN_MAX_S，小于出图方 yield_timeout_s 300 s）再卸载放行。WIN_N=0 关掉。
WIN_N = int(os.environ.get("VQA_WIN_N", "6"))
WIN_WAIT_S = float(os.environ.get("VQA_WIN_WAIT_S", "480"))
WIN_BACKLOG = int(os.environ.get("VQA_WIN_BACKLOG", "10"))
WIN_PER_JOB_S = float(os.environ.get("VQA_WIN_PER_JOB_S", "50"))
WIN_MAX_S = float(os.environ.get("VQA_WIN_MAX_S", "270"))
_win = {"until": 0.0, "yields": 0}
_pending: dict[int, float] = {}                 # 排队中的看图请求：id(box) → 入队时间
_model = _proc = None


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def heartbeat(label: str, state: str = "running"):
    try:
        HB.parent.mkdir(parents=True, exist_ok=True)
        HB.write_text(json.dumps({"agent": "VQA", "label": label, "kind": "other", "server": "gpu36",
                                  "gpu": STATE["gpu"], "state": state, "ttl": 180, "pid": os.getpid(),
                                  "updated": time.time()}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- 让道
def free_mib() -> dict[int, int]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return {int(a): int(b) for a, b in (ln.split(",") for ln in out.strip().splitlines())}
    except Exception:  # noqa: BLE001
        return {}


def comfy_busy(gpu: int) -> bool:
    port = COMFY.get(gpu)
    if not port:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=3) as r:
            d = json.loads(r.read())
        return bool(d.get("queue_running") or d.get("queue_pending"))
    except Exception:  # noqa: BLE001
        return True          # 读不到 = 当作忙（宁可不占）


_idle_since: dict[int, float] = {}


def window_active() -> bool:
    return time.time() < _win["until"]


def maybe_open_window() -> bool:
    """/yield 时调用：有积压且满足任一条件 → 开窗口（记 switch.jsonl ev=vqa_window）"""
    if WIN_N <= 0 or not _pending:
        return False
    now = time.time()
    backlog, oldest = len(_pending), now - min(_pending.values())
    why = [w for w, hit in ((f"出图满 {WIN_N} 张", _win["yields"] >= WIN_N), (f"最老请求等了 {oldest:.0f}s", oldest >= WIN_WAIT_S),
                            (f"积压 {backlog} 条", backlog >= WIN_BACKLOG)) if hit]
    if not why:
        return False
    dur = min(backlog * WIN_PER_JOB_S, WIN_MAX_S)
    _win.update(until=now + dur, yields=0, opened=now, served0=STATE["served"])
    for g in list(COMFY):
        _idle_since[g] = now - IDLE_S - 1          # 窗口内不再等“空闲 IDLE_S 秒”
    switch_log("vqa_window", phase="open", backlog=backlog, secs=round(dur), why="、".join(why))
    log("看图窗口开：", "、".join(why), f"积压 {backlog}，最长 {dur:.0f}s")
    return True


def pick_gpu() -> tuple[int | None, str]:
    fm = free_mib()
    now = time.time()
    cands = [int(FORCE_GPU)] if FORCE_GPU else GPUS
    why = []
    for g in cands:
        if comfy_busy(g):
            _idle_since.pop(g, None)
            why.append(f"GPU{g} ComfyUI 有任务")
            continue
        _idle_since.setdefault(g, now)
        if now - _idle_since[g] < IDLE_S and not window_active():
            why.append(f"GPU{g} 空闲才 {now - _idle_since[g]:.0f}s")
            continue
        if fm.get(g, 0) < NEED_MIB and FREE_COMFY:      # LOCALGPU：本机 ComfyUI 空闲时还占着模型 → 让它先释放
            comfy_free(g)
            fm = free_mib()
            if comfy_busy(g):                            # 释放期间来了出图活 → 让道
                _idle_since.pop(g, None)
                why.append(f"GPU{g} ComfyUI 有任务")
                continue
        if fm.get(g, 0) < NEED_MIB:
            why.append(f"GPU{g} 显存余 {fm.get(g)} MiB < {NEED_MIB}")
            continue
        return g, ""
    return None, "；".join(why)


# ---------------------------------------------------------------- 模型
def load(gpu: int):
    global _model, _proc
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
    t0 = time.time()
    if gpu is None:                                  # CPU 模式
        torch.set_num_threads(THREADS)
        _model = AutoModelForImageTextToText.from_pretrained(SRC, device_map={"": "cpu"}, dtype=torch.float32)
        _model.eval()
        _proc = AutoProcessor.from_pretrained(SRC)
        STATE.update(loaded=True, gpu="cpu", load_s=round(time.time() - t0, 1))
        log(f"loaded on CPU ({THREADS} threads) in {STATE['load_s']}s")
        return
    dev = {"": f"cuda:{gpu}"}
    akw = {"attn_implementation": ATTN} if ATTN else {}     # VQAGATE 11-01 显存：VQA_ATTN=sdpa 等
    if (QDIR / "config.json").exists():
        _model = AutoModelForImageTextToText.from_pretrained(QDIR, device_map=dev, dtype=torch.bfloat16, **akw)
    else:
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                               bnb_4bit_use_double_quant=True, llm_int8_skip_modules=["visual", "lm_head"])
        _model = AutoModelForImageTextToText.from_pretrained(SRC, device_map=dev, dtype=torch.bfloat16,
                                                             quantization_config=q)
        try:
            _model.save_pretrained(QDIR)
            log("nf4 checkpoint saved", QDIR)
        except Exception as e:  # noqa: BLE001
            log("save nf4 failed", e)
    _model.eval()
    _proc = AutoProcessor.from_pretrained(SRC)
    torch.cuda.reset_peak_memory_stats(gpu)
    STATE.update(loaded=True, gpu=gpu, load_s=round(time.time() - t0, 1))
    log(f"loaded on GPU{gpu} in {STATE['load_s']}s")
    switch_log("vqa_load", gpu=gpu, secs=STATE["load_s"])


def unload(reason: str):
    global _model, _proc
    with _mlock:
        if _model is None:
            return
        import gc
        import torch
        t0 = time.time()
        g = STATE["gpu"]
        _model = _proc = None
        gc.collect()
        torch.cuda.empty_cache()
        log(f"unloaded GPU{g}: {reason}")
        STATE.update(loaded=False, gpu=None)
        switch_log("vqa_unload", gpu=g, reason=reason, secs=round(time.time() - t0, 1))
    heartbeat(f"本地看图模型已卸载（{reason}）", "done")


def _img(spec: dict):
    from PIL import Image
    if spec.get("b64"):
        im = Image.open(io.BytesIO(base64.b64decode(spec["b64"])))
    else:
        im = Image.open(spec["path"])
    im = im.convert("RGB")
    mp = int(spec.get("max_pixels") or M.get("ref_max_pixels", 360000))
    cap = CAP_SUBJECT if spec.get("label") == "【待检图】" else CAP_REF
    if cap:
        mp = min(mp, cap)
    w, h = im.size
    if w * h > mp:
        s = (mp / (w * h)) ** 0.5
        im = im.resize((max(28, int(w * s)), max(28, int(h * s))))
    return im


def infer(req: dict) -> str:
    import torch
    content = []
    for i, spec in enumerate(req.get("images") or []):
        if spec.get("label"):
            content.append({"type": "text", "text": spec["label"]})
        content.append({"type": "image", "image": _img(spec)})
    content.append({"type": "text", "text": req["text"]})
    msgs = []
    if req.get("system"):
        msgs.append({"role": "system", "content": [{"type": "text", "text": req["system"]}]})
    msgs.append({"role": "user", "content": content})
    inputs = _proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True,
                                       return_tensors="pt").to(_model.device)
    mnt = int(req.get("max_new_tokens") or M.get("max_new_tokens", 900))
    if CAP_TOKENS:
        mnt = min(mnt, CAP_TOKENS)
    if STATE["gpu"] != "cpu":
        torch.cuda.reset_peak_memory_stats(STATE["gpu"])     # VQAGATE：按条记峰值（原来是加载以来的最大值）
    import contextlib
    ctx = contextlib.nullcontext()
    if os.environ.get("VQA_SDPA_EFFICIENT") == "1" and STATE["gpu"] != "cpu":
        # VQAGATE 11-01（未实测）：不让 sdpa 退回 math 内核（会整块物化注意力矩阵，长 prompt 预填充时显存峰值的主要来源）
        from torch.nn.attention import SDPBackend, sdpa_kernel
        ctx = sdpa_kernel([SDPBackend.EFFICIENT_ATTENTION, SDPBackend.FLASH_ATTENTION])
    with torch.inference_mode(), ctx:
        out = _model.generate(**inputs, max_new_tokens=mnt, do_sample=False)
    txt = _proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    if STATE["gpu"] != "cpu":
        STATE["last_peak_mib"] = int(torch.cuda.max_memory_allocated(STATE["gpu"]) / 2**20)
        STATE["last_reserved_mib"] = int(torch.cuda.max_memory_reserved(STATE["gpu"]) / 2**20)
        STATE["peak_mib"] = max(STATE["peak_mib"] or 0, STATE["last_peak_mib"])
    STATE["last_tokens_in"] = int(inputs["input_ids"].shape[1])
    STATE["last_tokens_out"] = int(out.shape[1] - inputs["input_ids"].shape[1])
    del inputs, out
    if STATE["gpu"] != "cpu":
        torch.cuda.empty_cache()
    return txt


def worker():
    last = time.time()
    while True:
        try:
            req, box = JOBS.get(timeout=5)
        except queue.Empty:
            if DEVICE != "cpu" and _model is not None and (time.time() - last > IDLE_UNLOAD_S or comfy_busy(STATE["gpu"])):
                unload("空闲" if time.time() - last > IDLE_UNLOAD_S else "出图来活，让道")
            continue
        STATE["queue"] = JOBS.qsize()
        try:
            if DEVICE != "cpu" and _model is not None and comfy_busy(STATE["gpu"]):
                unload("出图来活，让道")
            if DEVICE == "cpu" and _model is None:
                load(None)
            while True:
                while _model is None:
                    g, why = pick_gpu()
                    if g is not None:
                        STATE.update(waiting_since=None, why_waiting=None)
                        heartbeat("本地看图模型加载中")
                        with _mlock:
                            load(g)
                        break
                    STATE.update(waiting_since=STATE["waiting_since"] or time.time(), why_waiting=why)
                    if req.get("deadline") and time.time() > req["deadline"]:
                        raise TimeoutError("等不到空闲卡：" + why)
                    time.sleep(5)
                heartbeat(f"本地看图复核 · {req.get('label') or req.get('key', '')[:12]}")
                with _mlock:                     # LOCALGPU：/yield 可能在加载后、推理前把模型卸了 → 回去重新等卡
                    if _model is None:
                        continue
                    t0 = time.time()
                    txt = infer(req)
                break
            res = {"text": txt, "seconds": round(time.time() - t0, 1), "gpu": STATE["gpu"], "cached": False,
                   "tokens_in": STATE.get("last_tokens_in"), "tokens_out": STATE.get("last_tokens_out"),
                   "peak_mib": STATE.get("last_peak_mib"), "reserved_mib": STATE.get("last_reserved_mib"),
                   "model": M.get("name", "Qwen3-VL-8B-Instruct")}
            if req.get("key"):
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / f"{req['key']}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            STATE["served"] += 1
            STATE["last_job"] = time.time()
            box.put(res)
        except Exception as e:  # noqa: BLE001
            STATE["last_error"] = f"{type(e).__name__}: {e}"
            log("job failed", traceback.format_exc())
            if "out of memory" in str(e).lower() and DEVICE != "cpu":
                unload("显存不够（OOM），让道")
            box.put({"error": STATE["last_error"]})
        last = time.time()
        if DEVICE != "cpu" and _model is not None and comfy_busy(STATE["gpu"]):
            unload("出图来活，让道")


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {**STATE, "queue": JOBS.qsize(), "gpus": GPUS, "need_free_mib": NEED_MIB, "free": free_mib()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        if self.path.startswith("/unload"):
            unload("调用方要求")
            return self._send(200, {"ok": True})
        if self.path.startswith("/yield"):      # LOCALGPU：出图方提交前调用；推理中则等这条推理完再卸（≤ 推理时长）
            t0 = time.time()
            _win["yields"] += 1
            if window_active() or maybe_open_window():   # VQAGATE 最短看图窗口：等窗口结束或积压清空再让
                while window_active() and _pending:
                    time.sleep(1)
                if _win.get("opened"):
                    switch_log("vqa_window", phase="close", served=STATE["served"] - _win.get("served0", 0),
                               draw_waited_s=round(time.time() - t0, 1), left=len(_pending))
                    _win.update(until=0.0, opened=None)
            for g in list(COMFY):
                _idle_since[g] = time.time()     # 重新计空闲：出图活交上去之前不会又加载
            was = _model is not None
            unload(f"出图方让道请求（{req.get('by') or '?'}）")
            secs = round(time.time() - t0, 1)
            if was:
                switch_log("yield", by=req.get("by"), secs=secs)
            return self._send(200, {"ok": True, "was_loaded": was, "secs": secs})
        if not self.path.startswith("/generate"):
            return self._send(404, {"error": "not found"})
        key = req.get("key")
        if key and (CACHE / f"{key}.json").exists() and not req.get("refresh"):
            res = json.loads((CACHE / f"{key}.json").read_text(encoding="utf-8"))
            res["cached"] = True
            return self._send(200, res)
        if req.get("wait_s"):
            req["deadline"] = time.time() + float(req["wait_s"])
        box: queue.Queue = queue.Queue()
        _pending[id(box)] = time.time()
        JOBS.put((req, box))
        try:
            res = box.get()
        finally:
            _pending.pop(id(box), None)
        self._send(200 if "error" not in res else 503, res)


def main():
    threading.Thread(target=worker, daemon=True).start()
    log(f"VQA server on 127.0.0.1:{PORT}, gpus {GPUS}, need {NEED_MIB} MiB")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
