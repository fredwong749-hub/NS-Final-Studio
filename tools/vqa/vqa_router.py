#!/usr/bin/env python3
"""VQAGATE 11-02（总调度 L-100 + P0）：gpu36 专用看图卡（GPU2）上多个看图实例前面的分发器。

对外接口和 tools/vqa/server.py 一样（GET /health、POST /generate、/yield、/unload），占 127.0.0.1:8870，
所以 client、gpu36 内网入口 10.0.0.36:8870、笔记本隧道都不用改。每条 /generate 发给当前排队最少的后端实例
（各实例 = 同一份 server.py，VQA_DEDICATED=1，口径 B，同一模型同一量化 → 判定和原服务一致）；一个后端出错就换下一个。
图片只在本机转发（K-REV-V01）。

    VQA_BACKENDS=8876,8878,8879 python vqa_router.py
"""
from __future__ import annotations

import os as _os   # K-OPS-V13
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")

import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

PORT = int(_os.environ.get("VQA_PORT", "8870"))
BACKENDS = [int(p) for p in _os.environ.get("VQA_BACKENDS", "8876").split(",") if p.strip()]
_inflight = {p: 0 for p in BACKENDS}
_lock = threading.Lock()
STATS = {"served": 0, "errors": 0, "started": time.time()}


def _health(p: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=3) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


_hcache: dict = {"at": 0.0, "ok": set(BACKENDS)}


def healthy() -> set:
    """VQAGATE 11-02 S3：只派给活着且没在等卡的实例（死实例照派 → 单子排到超时才失败，gpu33 p50 1417 s 的放大器）。
    10 s 刷新一次；全都不健康时退回全部（让实例自己等卡 / 报错）"""
    now = time.time()
    if now - _hcache["at"] > 10:
        ok = set()
        for p in BACKENDS:
            h = _health(p)
            if h and not h.get("why_waiting"):         # 没加载但也没在等卡 = 懒加载，来单就加载，照派
                ok.add(p)
        _hcache.update(at=now, ok=ok or set(BACKENDS))
    return _hcache["ok"]


def pick(exclude=()) -> int | None:
    up = healthy()
    with _lock:
        cands = [p for p in BACKENDS if p not in exclude and p in up] or [p for p in BACKENDS if p not in exclude]
        if not cands:
            return None
        p = min(cands, key=lambda q: _inflight[q])
        _inflight[p] += 1
        return p


def release(p: int):
    with _lock:
        _inflight[p] = max(0, _inflight[p] - 1)


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
        if not self.path.startswith("/health"):
            return self._send(404, {"error": "not found"})
        hs = {p: _health(p) for p in BACKENDS}
        up = [p for p, h in hs.items() if h]
        self._send(200, {"loaded": any((h or {}).get("loaded") for h in hs.values()), "gpu": "router", "dedicated": True,
                         "queue": sum(_inflight.values()), "instances": len(up), "backends": {str(p): (h or {}).get("served") for p, h in hs.items()},
                         "inflight": {str(p): n for p, n in _inflight.items()}, **STATS, "last_error": None})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) or b"{}"
        if self.path.startswith(("/yield", "/unload")):        # 专用卡：不让、不卸
            return self._send(200, {"ok": True, "dedicated": True, "secs": 0})
        if not self.path.startswith("/generate"):
            return self._send(404, {"error": "not found"})
        tried, last = [], None
        while True:
            p = pick(tried)
            if p is None:
                STATS["errors"] += 1
                return self._send(503, {"error": f"所有看图实例都失败：{last}"})
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{p}/generate", body, {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3600) as r:
                    res = json.loads(r.read())
                STATS["served"] += 1
                return self._send(200, {**res, "instance": p})
            except urllib.error.HTTPError as e:
                try:
                    res = json.loads(e.read() or b"{}")
                except ValueError:
                    res = {"error": f"HTTP {e.code}"}
                last = res.get("error")
                if "OutOfMemory" not in str(last) and "out of memory" not in str(last).lower() and "等不到" not in str(last):
                    return self._send(503, {**res, "instance": p})
            except Exception as e:  # noqa: BLE001
                last = repr(e)[:200]
            finally:
                release(p)
            tried.append(p)


def main():
    print(time.strftime("%H:%M:%S"), f"看图分发器 127.0.0.1:{PORT} → 实例 {BACKENDS}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
