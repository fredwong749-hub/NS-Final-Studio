#!/usr/bin/env python3
"""gpu33 上的 postflight 像素度量（Q2 造型 / Q4 质感 / Q7 场景）：与笔记本 ns_agent.gen_contract.metrics 同一份代码（metrics.py 一起
放在本目录），CLIP ViT-L/14 放 GPU（权重 = ModelScope AI-ModelScope/clip-vit-large-patch14 的 model.safetensors，
sha256 a2bf730a0c7d… = HF openai/clip-vit-large-patch14@32bd642，与笔记本同一份）。

stdin：{"refs_dir": 参考图缓存目录（文件名 = <sha16>.png）,
        "items": [{"id", "path": 本机图, "post": {"size": [w,h], "usm": {...}} | null（按交付图的后处理复现）,
                   "rows": [{label, role, zone, source, file, ref: <sha16>}], "face_bbox": [..] | null（已换算到交付图）,
                   "scene": <sha16> | null}]}
stdout 一行 JSON：{"items": {id: {Q2, Q4, Q7}}, "missing_refs": [...], "device": ...}
用法（REFLOCK remote_score.full_score 自动调）：/root/claude-kimi-ns-studio-v1/env/comfy/bin/python clip_srv.py -
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("NS_CLIP_PATH", os.path.join(HERE, "clip-vit-large-patch14"))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# K-OPS-V13 线程上限（重型 import 都在函数里，这里先设好）
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_k, os.environ.get("NS_SCORE_THREADS", "4"))


def _is_oom(e) -> bool:
    t = (type(e).__name__ + " " + str(e)).lower()
    return "out of memory" in t or "outofmemory" in t or "cublas_status_alloc_failed" in t


def _measure_all(req, M, Image):
    rd = req["refs_dir"]
    cache = {}

    def ref(sha):
        if sha not in cache:
            cache[sha] = Image.open(os.path.join(rd, sha + ".png")).convert("RGB")
        return cache[sha]
    out, oom = {}, []
    for it in req["items"]:
        try:
            img = Image.open(it["path"]).convert("RGB")
            p = it.get("post") or {}
            if p:
                img = M.post_like(img, p.get("size"), p.get("usm"))
            rows = it.get("rows") or []
            refs = {r["ref"]: ref(r["ref"]) for r in rows}
            out[it["id"]] = M.measure(img, rows, refs, it.get("face_bbox"), ref(it["scene"]) if it.get("scene") else None,
                                       outer=it.get("outer"))
        except Exception as e:  # noqa: BLE001
            if _is_oom(e):
                oom.append(it["id"])
            else:
                out[it["id"]] = {"error": repr(e)[:300]}
    return out, oom


def _free_cuda(M):
    try:
        M._clip.cache_clear()
        import gc
        gc.collect()
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def _cpu_subprocess(req, ids):
    """OOM 兜底（11-01 ASSETMASTER 04:16–04:20 GPU_SCORE_FALLBACK：ComfyUI 同卡出图，CLIP 加载时 OOM，进程内切 CPU 也没救回来）：
    另起一个看不见 GPU 的子进程算这几张——干净的进程，不带任何 CUDA 状态，也不再占 ComfyUI 的显存"""
    import subprocess
    sub = dict(req, items=[it for it in req["items"] if it["id"] in ids])
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", NS_CLIP_DEVICE="cpu", NS_CLIP_SRV_CHILD="1")
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "-"], input=json.dumps(sub), env=env,
                       capture_output=True, text=True, timeout=1800)
    ln = [x for x in r.stdout.splitlines() if x.startswith("{")]
    if not ln:
        return {i: {"error": "cpu 兜底失败：" + r.stderr[-300:]} for i in ids}
    return json.loads(ln[-1]).get("items", {})


def handle(req: dict) -> dict:
    """一次请求 → 结果 dict（stdin 单次模式与常驻模式共用）"""
    from PIL import Image
    import metrics as M
    rd = req["refs_dir"]
    need = {r["ref"] for it in req["items"] for r in it.get("rows") or []} | {it["scene"] for it in req["items"] if it.get("scene")}
    missing = sorted(x for x in need if not os.path.exists(os.path.join(rd, x + ".png")))
    if missing:
        return {"items": {}, "missing_refs": missing}
    out, oom = _measure_all(req, M, Image)
    fallback, retried = [], []
    if oom and os.environ.get("NS_CLIP_SRV_CHILD") != "1":
        # 先让一让：放掉本进程的显存，等 ComfyUI 这一步过去再在 GPU 上试一次；还 OOM → 干净的 CPU 子进程
        _free_cuda(M)
        time.sleep(float(os.environ.get("NS_CLIP_OOM_WAIT_S", "20")))
        retried = list(oom)
        o2, oom = _measure_all(dict(req, items=[it for it in req["items"] if it["id"] in oom]), M, Image)
        out.update(o2)
        if oom:
            _free_cuda(M)
            out.update(_cpu_subprocess(req, oom))
            fallback = list(oom)
    dev, gpu = None, None
    try:
        import torch
        if out:
            dev = "cpu(兜底)" if fallback and len(fallback) == len(req["items"]) else M._clip()[2]
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:  # noqa: BLE001
        pass
    return {"items": out, "missing_refs": [], "cpu_fallback": fallback, "gpu_retried": retried, "device": dev, "gpu": gpu}


def _file_sha(p: str) -> str:
    import hashlib
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError:
        return ""


def serve(port: int) -> None:
    """FACTORY D6（K-OPS-F04）：常驻模式——CLIP 只加载一次（钉在 CUDA_VISIBLE_DEVICES 指定的卡，gpu36 = GPU2，与 vLLM 同卡，L-100），
    只听 127.0.0.1。POST /measure（与 stdin 模式同一份请求 JSON）→ 同一份结果 JSON；GET /health。
    口径一致：每次请求比对本目录 metrics.py / clip_srv.py 的 sha 与启动时是否一致（remote_score 每次随请求下发最新一份），
    不一致 → 409 + 退出（调用方当次退回单次子进程，外层保活脚本按新代码重启）"""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import metrics as M
    boot = {n: _file_sha(os.path.join(HERE, n)) for n in ("metrics.py", "clip_srv.py")}
    M._clip()                                  # 预热：启动即加载
    lock = threading.Lock()
    st = {"served": 0, "started": time.time(), "last_s": None}

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

        def do_GET(self):
            self._send(200, {**st, "device": M._clip()[2], "boot_sha": {k: v[:12] for k, v in boot.items()}})

        def do_POST(self):
            now = {n: _file_sha(os.path.join(HERE, n)) for n in boot}
            if now != boot:
                self._send(409, {"error": "代码已更新，常驻进程退出重启"})
                threading.Thread(target=lambda: (time.sleep(0.5), os._exit(3)), daemon=True).start()
                return
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            t0 = time.time()
            with lock:                          # 一张卡一个模型：请求排队串行（单张 < 10 s）
                try:
                    res = handle(req)
                except Exception as e:  # noqa: BLE001
                    self._send(500, {"error": repr(e)[:300]})
                    return
            st["served"] += 1
            st["last_s"] = round(time.time() - t0, 2)
            res["resident"] = True
            self._send(200, res)

    HTTPServer(("127.0.0.1", port), H).serve_forever()


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
        return
    req = json.load(sys.stdin)
    print(json.dumps(handle(req)))


if __name__ == "__main__":
    main()
