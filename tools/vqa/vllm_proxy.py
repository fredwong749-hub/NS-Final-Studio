#!/usr/bin/env python3
"""VQAGATE 11-02（总调度 L-100）：gpu36 GPU2 专用看图——vLLM 连续批处理前面的兼容层。

对外接口和 tools/vqa/server.py 完全一样（POST /generate、GET /health、POST /yield、POST /unload），所以 client、
gpu36 内网入口（10.0.0.36:8870）、笔记本隧道（8871）都不用改；每条请求一个线程转给本机 vLLM（OpenAI 接口，127.0.0.1:VLLM_PORT），
vLLM 自己做连续批处理（max_num_seqs ≥ 4）。图片按请求里的 max_pixels 先缩（口径 B：主图 0.6 MP、参考 0.15 MP，和 server.py 同一套缩法），
再以 data URL 发给本机 vLLM——图片不出这台机器（K-REV-V01）。缓存键 / 缓存目录和 server.py 相同。

    VQA_BASE=/root/work/fredw/vqa VLLM_PORT=8000 python vllm_proxy.py      # 默认听 127.0.0.1:8870
"""
from __future__ import annotations

import os as _os   # K-OPS-V13
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")

import base64  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

PORT = int(_os.environ.get("VQA_PORT", "8870"))
VLLM = f"http://127.0.0.1:{_os.environ.get('VLLM_PORT', '8000')}"
MODEL = _os.environ.get("VLLM_MODEL", "qwen3vl")
BASE = Path(_os.environ.get("VQA_BASE", "/root/work/fredw/vqa"))
CACHE = BASE / "cache"
CAP_SUBJECT = int(_os.environ.get("VQA_CAP_SUBJECT_PX", "600000"))
CAP_REF = int(_os.environ.get("VQA_CAP_REF_PX", "150000"))
CAP_TOKENS = int(_os.environ.get("VQA_CAP_TOKENS", "1000"))
STATE = {"loaded": True, "gpu": "vllm", "queue": 0, "inflight": 0, "served": 0, "last_error": None, "started": time.time(),
         "backend": "vllm", "dedicated": True}
_lock = threading.Lock()


def _img_b64(spec: dict) -> str:
    from PIL import Image
    im = Image.open(io.BytesIO(base64.b64decode(spec["b64"]))) if spec.get("b64") else Image.open(spec["path"])
    im = im.convert("RGB")
    cap = CAP_SUBJECT if spec.get("label") == "【待检图】" else CAP_REF
    mp = min(int(spec.get("max_pixels") or cap), cap)
    w, h = im.size
    if w * h > mp:
        s = (mp / (w * h)) ** 0.5
        im = im.resize((max(28, int(w * s)), max(28, int(h * s))))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def infer(req: dict) -> dict:
    content = []
    for spec in req.get("images") or []:
        if spec.get("label"):
            content.append({"type": "text", "text": spec["label"]})
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _img_b64(spec)}})
    content.append({"type": "text", "text": req["text"]})
    msgs = ([{"role": "system", "content": req["system"]}] if req.get("system") else []) + [{"role": "user", "content": content}]
    body = {"model": MODEL, "messages": msgs, "temperature": 0, "max_tokens": min(int(req.get("max_new_tokens") or CAP_TOKENS), CAP_TOKENS)}
    t0 = time.time()
    r = urllib.request.Request(VLLM + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=float(req.get("wait_s") or 1800)) as resp:
        d = json.loads(resp.read())
    u = d.get("usage") or {}
    return {"text": d["choices"][0]["message"]["content"], "seconds": round(time.time() - t0, 1), "gpu": "vllm", "cached": False,
            "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens"), "model": "Qwen3-VL-8B-Instruct (vLLM bf16)"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/health"):
            try:
                urllib.request.urlopen(VLLM + "/health", timeout=3)
                up = True
            except Exception:  # noqa: BLE001
                up = False
            return self._send(200, {**STATE, "loaded": up})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        if self.path.startswith(("/yield", "/unload")):        # 专用卡：不让、不卸
            return self._send(200, {"ok": True, "dedicated": True, "secs": 0})
        if not self.path.startswith("/generate"):
            return self._send(404, {"error": "not found"})
        key = req.get("key")
        if key and (CACHE / f"{key}.json").exists() and not req.get("refresh"):
            res = json.loads((CACHE / f"{key}.json").read_text(encoding="utf-8"))
            return self._send(200, {**res, "cached": True})
        with _lock:
            STATE["inflight"] += 1
            STATE["queue"] = STATE["inflight"]
        try:
            res = infer(req)
            if key:
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / f"{key}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            STATE["served"] += 1
            self._send(200, res)
        except Exception as e:  # noqa: BLE001
            STATE["last_error"] = f"{type(e).__name__}: {e}"[:300]
            self._send(503, {"error": STATE["last_error"]})
        finally:
            with _lock:
                STATE["inflight"] -= 1
                STATE["queue"] = STATE["inflight"]


def main():
    print(time.strftime("%H:%M:%S"), f"vLLM 兼容层 127.0.0.1:{PORT} → {VLLM}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
