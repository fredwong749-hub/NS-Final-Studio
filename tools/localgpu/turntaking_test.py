"""LOCALGPU 轮流用卡验收（总调度 11-01：“连出 3 张图并完成看图判定、不崩”）。
① 本机道连出 N 张（新 first_frame_jobs 作业、非亲密，scope=ab → data/ab/localgpu_turntaking/），每张出完立刻异步交看图
   （ns_agent.vqa.contract.inspect_for，与 producer.vqa_gate 同一调用，wait_s=1200）；
② 看图开始推理后再插 --interrupt 张出图（ComfyClient 交图前自动 POST /yield），验证推理中途来活不崩；
记录每张出图耗时、每次看图耗时、看图服务 switch.jsonl 的切换耗时、ComfyUI 是否存活。
用法：python tools/localgpu/turntaking_test.py --n 3 --interrupt 2
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "services/agent", "packages/schema", "services/api"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
URL = "http://127.0.0.1:18388"
OUT = ROOT / "data/ab/localgpu_turntaking"
JOBS = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"


def health():
    try:
        return json.loads(urllib.request.urlopen("http://127.0.0.1:8870/health", timeout=5).read())
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def comfy_alive():
    try:
        urllib.request.urlopen(URL + "/system_stats", timeout=5).read()
        return True
    except Exception:  # noqa: BLE001
        return False


def render(job: dict, seed: int, tag: str) -> dict:
    from ns_render import image_params as IP
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    client = ComfyClient(URL)
    up = lambda p: client.upload_image(p, subfolder="ns_ab/localgpu_turntaking")  # noqa: E731
    wf, eff, sent = UF.build_graph(job, seed, up, f"ns_ab/localgpu_turntaking/{job['shot']}_{tag}")
    t0 = time.time()
    entry, secs = client.run(wf, timeout_s=1800)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"{job['shot']}_{tag}_s{seed}_raw.png"
    client.download(item, raw)
    post = IP.post_file(raw, eff)
    from ns_api import jobs as J
    return {"shot": job["shot"], "tag": tag, "file": post["path"], "prompt": sent, "comfy_s": round(secs, 1),
            "gpu_s": J.gpu_seconds(entry), "wall_s": round(time.time() - t0, 1), "refs": job["refs"]}


def vqa(rec: dict, results: list):
    from ns_agent.vqa import contract as VQ
    t0 = time.time()
    refs = [str(ROOT / r) for r in rec["refs"]]
    try:
        v = VQ.inspect_for(rec["shot"], "first", rec["file"], rec["prompt"], refs, wait_s=1200)
        results.append({"shot": rec["shot"], "tag": rec["tag"], "vqa_s": round(time.time() - t0, 1), "error": v.get("error"),
                        "verdict": v.get("verdict") or v.get("ok"), "defects": v.get("defects"), "gaze_mp": v.get("gaze_mp")})
    except Exception as e:  # noqa: BLE001
        results.append({"shot": rec["shot"], "tag": rec["tag"], "vqa_s": round(time.time() - t0, 1), "error": repr(e)[:300]})


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 3
    k = int(argv[argv.index("--interrupt") + 1]) if "--interrupt" in argv else 2
    jobs = [j for j in json.loads(JOBS.read_text(encoding="utf-8"))["jobs"]
            if not j.get("intimate_ep") and j.get("status") == "ready" and j.get("ep") == 1]
    plan = jobs[: n + k]
    sw0 = Path(r"D:\ns_vqa\logs\switch.jsonl")
    sw_before = sw0.read_text(encoding="utf-8").count("\n") if sw0.exists() else 0
    renders, vres, threads = [], [], []
    t_all = time.time()
    for j in plan[:n]:
        r = render(j, int(j["seed"]), "tt")
        renders.append(r)
        print("render", json.dumps({x: r[x] for x in ("shot", "comfy_s", "gpu_s")}, ensure_ascii=False), "| vqa:", health().get("loaded"), flush=True)
        t = threading.Thread(target=vqa, args=(r, vres), daemon=True)
        t.start()
        threads.append(t)
    # 等看图真的开始推理（loaded=True），再插出图活
    t0 = time.time()
    while time.time() - t0 < 600 and not health().get("loaded"):
        time.sleep(2)
    print("vqa loaded after", round(time.time() - t0, 1), "s idle wait", flush=True)
    time.sleep(3)
    for j in plan[n:]:
        r = render(j, int(j["seed"]), "tt_interrupt")
        renders.append(r)
        print("interrupt render", json.dumps({x: r[x] for x in ("shot", "comfy_s", "gpu_s")}, ensure_ascii=False), "| comfy alive", comfy_alive(), flush=True)
        t = threading.Thread(target=vqa, args=(r, vres), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=1800)
    sw = sw0.read_text(encoding="utf-8").splitlines()[sw_before:] if sw0.exists() else []
    res = {"renders": [{x: r[x] for x in ("shot", "tag", "comfy_s", "gpu_s", "wall_s", "file")} for r in renders], "vqa": vres,
           "switches": [json.loads(x) for x in sw], "comfy_alive": comfy_alive(), "vqa_health": health(),
           "total_s": round(time.time() - t_all, 1)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"result_{time.strftime('%H%M%S')}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, default=str)[:6000])


if __name__ == "__main__":
    main(sys.argv[1:])
