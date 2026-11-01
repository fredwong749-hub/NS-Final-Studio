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


def main():
    req = json.load(sys.stdin)
    from PIL import Image
    import metrics as M
    rd = req["refs_dir"]
    need = {r["ref"] for it in req["items"] for r in it.get("rows") or []} | {it["scene"] for it in req["items"] if it.get("scene")}
    missing = sorted(x for x in need if not os.path.exists(os.path.join(rd, x + ".png")))
    if missing:
        print(json.dumps({"items": {}, "missing_refs": missing}))
        return
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
    print(json.dumps({"items": out, "missing_refs": [], "cpu_fallback": fallback, "gpu_retried": retried,
                      "device": dev, "gpu": gpu}))


if __name__ == "__main__":
    main()
