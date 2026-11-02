#!/usr/bin/env python3
"""本地图片异常检测常驻服务（VQAGATE 11-02，总调度定方案 1：检测器在 gpu36 上常驻、走内网端口，measure() 返回格式不变）。

为什么要常驻：tools/vqa/anomaly.py 的 measure() 原来经 rssh 连 gpu36 跑远端脚本（REMOTE_SRC），gpu33 上的 producer 没有到 gpu36 的密钥，
契约 Q1d 只能关着；每次还要重新起 Python、加载 YOLO / insightface / DWPose / OneFormer（20 多秒）。

做法：REMOTE_SRC 原样复用（单一来源，从 anomaly.py 读，不复制）——拆成两段：
  前半段（到 "refs = {}" 之前）= 加载模型，服务启动时执行一次；
  后半段（从 "refs = {}" 起）= 按请求算身份脸参照 + 逐张测量，每个请求执行一次，截获 stdout 里的 @@RES@@ 行原样返回。
找不到拆分点 → 启动即报错（不静默跑错）。一次只跑一个请求（同一张卡，串行）。图片只在 gpu36 本机进模型（K-REV-V01）。

接口（JSON，UTF-8；只监听 127.0.0.1，内网由 tools/netfix/lan_proxy.py 转发，只放行 gpu33）：
  GET  /health   → {loaded, served, errors, last_error, code_sha, mirror_seg, started}
  POST /measure  {"refs": {角色: 身份脸 b64}, "items": [{"id", "b64"}]} → 与 REMOTE_SRC 的 @@RES@@ 同格式 {"@refs": …, id: 测量值 …}

部署（交 FACTORY，随版本上线，不热替换）：
  CUDA_VISIBLE_DEVICES=2 CUDA_DEVICE_ORDER=PCI_BUS_ID ANOMALY_PORT=8893 ANOMALY_COMFY_ROOT=<车道表 comfy_root> \
    /root/work/fredw/venv/bin/python -u tools/vqa/anomaly_server.py
  lan_proxy.py --bind 10.0.0.36 --port 8893 --allow 10.0.0.33 --target 127.0.0.1:8893
显存：DWPose + yolov8m-seg + face / hand + OneFormer 约 2.5–3 GB，登记在 config/vqa.json model.vram_budget。
"""
from __future__ import annotations

import os as _os   # K-OPS-V13：服务器脚本限线程
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")

import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PORT = int(_os.environ.get("ANOMALY_PORT", "8893"))
SPLIT = "\nrefs = {}\n"
CODE_SHA = hashlib.sha256(Path(__file__).read_bytes().replace(bytes([13]), b"")).hexdigest()[:16]
STATE = {"loaded": False, "served": 0, "errors": 0, "last_error": None, "code_sha": CODE_SHA, "mirror_seg": None, "started": time.time()}
_lock = threading.Lock()
_ns: dict = {}
_per_request = ""


def split_remote_src(src: str) -> tuple[str, str]:
    """REMOTE_SRC → (加载模型段, 每请求段)。纯函数，便于单测；找不到拆分点 / 每请求段不打印 @@RES@@ 就报错"""
    i = src.find(SPLIT)
    if i < 0:
        raise RuntimeError("REMOTE_SRC 里找不到拆分点 'refs = {}'（anomaly.py 改了结构，常驻服务要跟着改）")
    setup, per = src[:i + 1], src[i + 1:]
    if '"@@RES@@"' not in per:
        raise RuntimeError("REMOTE_SRC 每请求段里没有 @@RES@@ 输出")
    if "json.load(sys.stdin)" not in setup:
        raise RuntimeError("REMOTE_SRC 加载段里没有 req = json.load(sys.stdin)")
    return setup, per


def comfy_root() -> str:
    r = _os.environ.get("ANOMALY_COMFY_ROOT")
    if r:
        return r.rstrip("/")
    sys.path.insert(0, str(ROOT))
    from tools.factory import hosts as H
    return H.load()["hosts"][_os.environ.get("ANOMALY_HOST", "gpu36")]["comfy_root"].rstrip("/")


def load() -> None:
    global _per_request
    sys.path.insert(0, str(ROOT))
    from tools.vqa import anomaly as AN
    setup, _per_request = split_remote_src(AN.REMOTE_SRC)
    croot = comfy_root()
    boot = {"comfy": croot, "work": croot.rsplit("/", 1)[0], "refs": {}, "items": []}
    _ns.clear()
    old = sys.stdin                      # 加载段第一句是 req = json.load(sys.stdin)：喂一份只带路径的 req
    sys.stdin = io.StringIO(json.dumps(boot))
    try:
        exec(compile(setup, "REMOTE_SRC[setup]", "exec"), _ns)    # noqa: S102 — 单一来源的远端脚本，仓库内代码
    finally:
        sys.stdin = old
    STATE.update(loaded=True, mirror_seg=bool(_ns.get("seg")))


def measure(req: dict) -> dict:
    with _lock:
        ns = dict(_ns)
        ns["req"] = {"comfy": _ns["req"]["comfy"], "work": _ns["req"]["work"], "refs": req.get("refs") or {}, "items": req.get("items") or []}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(compile(_per_request, "REMOTE_SRC[request]", "exec"), ns)   # noqa: S102
        line = next((ln for ln in buf.getvalue().splitlines() if ln.startswith("@@RES@@")), None)
        if not line:
            raise RuntimeError("远端脚本没有输出 @@RES@@")
        return json.loads(line[7:])


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, STATE)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/measure"):
            return self._send(404, {"error": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            res = measure(req)
            STATE["served"] += 1
            return self._send(200, res)
        except Exception as e:  # noqa: BLE001 — 单个请求失败只回错误，服务不退出
            STATE["errors"] += 1
            STATE["last_error"] = f"{type(e).__name__}: {e}"[:300]
            print(time.strftime("%H:%M:%S"), "measure failed", traceback.format_exc(), flush=True)
            return self._send(500, {"error": STATE["last_error"]})


def main() -> None:
    load()
    print(time.strftime("%H:%M:%S"), f"异常检测常驻服务 127.0.0.1:{PORT}（镜面分割 {'开' if STATE['mirror_seg'] else '关'}，code {CODE_SHA}）", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
