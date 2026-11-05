#!/usr/bin/env python3
"""AUDIT-PERF 提案 A（11-05）：出图机器上的常驻打分服务（ArcFace+OCR / mediapipe 手），只听 127.0.0.1，仿 clip_srv.py 的常驻模式。
起因：full_score 每张图冷起 score_remote（ArcFace + OCR 加载）和 hands_remote（mediapipe 加载）子进程，实测 ~40–60 s/张；常驻后模型只加载一次，
参考脸特征按（路径+mtime+大小）缓存。两个服务（两个 venv）：
  --kind idm  端口 8873（venv_idm：insightface + rapidocr）  POST /score  = score_remote.score
  --kind hand 端口 8874（venv_hand：mediapipe）               POST /hands  = hands_remote.detect
GET /health → {kind, served, started, boot_sha}。请求 JSON 与对应脚本 stdin 的 manifest 完全相同，结果同口径（同一份函数）。
代码换了（score_remote.py / hands_remote.py / 本文件 sha 与启动时不同）→ 409 + 退出，外层保活脚本（ops/factory/score_resident.sh）按新代码重启，
调用方当次退回旧子进程。用法：python score_srv.py --kind idm --serve 8873
"""
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.normpath(os.path.join(HERE, "..", "series10_imggen"))
sys.path.insert(0, IMG)


def _sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:12]
    except OSError:   # arch-ok: 代码 sha 读不到 = 空串，下次请求比对不一致即 409 重启，不会静默用旧代码
        return ""


def serve(kind: str, port: int) -> None:
    files = {"idm": "score_remote.py", "hand": "hands_remote.py"}[kind]
    paths = {files: os.path.join(IMG, files), "score_srv.py": os.path.abspath(__file__)}
    boot = {n: _sha(p) for n, p in paths.items()}
    if kind == "idm":
        import score_remote as S
        app = S.load_app()
        ocr_box, ref_cache = [None], {}
        try:                                    # 预热 OCR（原来每次冷启动里最慢的一段）
            from rapidocr_onnxruntime import RapidOCR
            ocr_box[0] = RapidOCR()
        except Exception:  # noqa: BLE001   arch-ok: OCR 预热失败 → 首次请求时再试
            pass
        run = lambda man: S.score(man, app, ocr_box, ref_cache)  # noqa: E731
        route = "/score"
    else:
        import hands_remote as Hh
        models = Hh.load_models()
        run = lambda man: Hh.detect(man, models)  # noqa: E731
        route = "/hands"
    lock = threading.Lock()
    st = {"kind": kind, "served": 0, "started": time.time(), "last_s": None}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send(200, {**st, "boot_sha": boot})

        def do_POST(self):
            if self.path != route:
                self._send(404, {"error": "unknown route"})
                return
            now = {n: _sha(p) for n, p in paths.items()}
            if now != boot:
                self._send(409, {"error": "代码与常驻版本不同，常驻退出重启，当次走单次子进程"})
                threading.Thread(target=lambda: (time.sleep(0.5), os._exit(3)), daemon=True).start()
                return
            man = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            t0 = time.time()
            with lock:
                try:
                    res = run(man)
                except Exception as e:  # noqa: BLE001
                    self._send(500, {"error": repr(e)[:300]})
                    return
            st["served"] += 1
            st["last_s"] = round(time.time() - t0, 2)
            self._send(200, res)

    HTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "--kind" and a[2] == "--serve":
        serve(a[1], int(a[3]))
    else:
        sys.exit("用法：score_srv.py --kind idm|hand --serve PORT")
