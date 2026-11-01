"""Pika Flex 冒烟（WORKFLOW 11-01，项目方“改用 Pika Flex”后的一镜验证）：用 series10 生产编译链
（build_jobs.compile_variant + recipe_choice.json 的 face_default）编出一镜，按 vidgen.Lane 同一提交路径派到一条空闲道，
取回成片，用 score_clip.py 打分。非生产版本：不写 takes.json、不碰 night / vidgen 状态，产物只在 data/autopilot/pika_smoke/。
用法：.venv/Scripts/python.exe tools/autopilot/pika_smoke.py ep01-S3 gpu33:0 18188
"""
import json, sys, time, urllib.parse, urllib.request, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ("tools/series10_video", "services/recipes", "packages/schema", "services/agent", "services/render_router")]
import build_jobs as B   # noqa: E402
import vidgen as VG      # noqa: E402

OUT = ROOT / "data/autopilot/pika_smoke"


def main(sid, lane_name, port):
    OUT.mkdir(parents=True, exist_ok=True)
    reg = B.R.load(); specs = B.load_specs(); frames = B.passed_frames()
    ch = B.recipe_choice(); rid = ch["face_default"] if specs[sid].faces else ch["noface_default"]
    var = B.compile_variant(specs[sid], reg, rid, 1, "pk1", frames)
    rec = {"shot": sid, "recipe_requested": rid, "lane": lane_name, "variant_status": var.get("status"),
           "recipe": var.get("recipe"), "inputs": var.get("inputs"), "started": time.strftime("%F %T")}
    assert var.get("status") == "ready", var.get("status")
    lane = VG.Lane(lane_name, int(port))
    pid = lane.submit(var, f"ns_final/pika_smoke/{sid}", tag={"agent": "WORKFLOW", "kind": "video", "label": f"Pika 冒烟 {sid}"})
    rec["prompt_id"] = pid
    (OUT / f"{sid}.job.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("submitted", pid, flush=True)
    t0 = time.time()
    while True:
        r = lane.result(pid)
        if r:
            break
        time.sleep(15)
    rec["result"] = r; rec["wall_s"] = round(time.time() - t0, 1)
    if r.get("path"):
        fn = r["path"].rsplit("/", 1)[-1]
        sub = "/".join(r["path"].split("/output/", 1)[1].split("/")[1:-1]) if "/output/" in r["path"] else ""
        # /view 的 subfolder 相对 output 根（道的 output 子目录由 ComfyUI --output-directory 决定，这里取 history 原值）
        h = json.loads(VG.api(int(port), f"/history/{pid}"))
        item = next(im for n in h[pid]["outputs"].values() for k in ("images", "videos", "gifs") for im in (n.get(k) or [])
                    if str(im.get("filename", "")).endswith(".mp4"))
        q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
        dst = OUT / f"{sid}__pika.mp4"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/view?{q}", timeout=300) as resp:
            dst.write_bytes(resp.read())
        rec["file"] = dst.relative_to(ROOT).as_posix()
    (OUT / f"{sid}.job.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False)[:800])


if __name__ == "__main__":
    main(*sys.argv[1:4])
