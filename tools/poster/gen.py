"""海报主图：用系统出图路径（ns_agent.frame_job.build_first → 契约 preflight → unified_frame._run），
把一张“海报镜”当成虚拟镜头（ep01-S98，只在内存里，不写剧本、不写 takes.json、不进账本），多人构图 + 身份脸 + 造型设定图。
图存 data/posters/<run>/art/，记录追加 art.jsonl。
用法：
  .venv/Scripts/python.exe tools/poster/gen.py --dry                      只编译 + 过契约 preflight，不出图
  .venv/Scripts/python.exe tools/poster/gen.py --lane gpu33:1 --expires 2026-11-02T20:10:00 --only s1_A_portrait,...
借道必须先 tools/debug/lanes.py sweep + lend，用前确认无生产作业。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "services/api", "tools/pipeline", "tools/autopilot", "tools/prompt_v2"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

SIZE = {"portrait": (832, 1248), "landscape": (1344, 768)}
STYLE = "时尚大片海报质感，杂志封面式布光，颜色饱满，真实皮肤质感，可见细小毛孔，所有人物为成年人，衣着得体"
# 三种构图（海报用，现行造型 A 的得体服装；不露骨）。三人及以上系统契约不过（I2/I9：次要人物脸只能进参考板），所以主图最多两人，其余人物由排版的人物条展示
COMPS = {
    "A": {  # 林晚前景居中最大，顾沉后景
        "cast": [("林晚", "在画", "中", "前"), ("顾沉", "在画", "右", "后")],
        "cast_landscape": [("林晚", "在画", "右", "前"), ("顾沉", "在画", "中", "后")],
        "portrait": "海报主视觉，中景，平视，主次分明的双人构图：林晚站在画面正中最前，身体微侧，侧脸到四分之三侧脸，神情克制而有张力；顾沉站在她右后方，目光落在她身上。林晚占画面一半以上，顾沉明显更小更虚。深夜写字楼落地窗背景，城市霓虹形成大光圈光斑",
        "landscape": "海报主视觉，宽幅中景，平视，主次分明的双人构图：林晚站在画面右三分之一最前，四分之三侧脸；顾沉在她左后方，目光落在她身上。画面左侧留出大片暗部空间。深夜写字楼落地窗背景，城市霓虹大光圈光斑",
    },
    "B": {  # 林晚与顾沉对视
        "cast": [("林晚", "在画", "左", "前"), ("顾沉", "在画", "右", "前")],
        "portrait": "海报主视觉，中近景，平视，双人对视构图：林晚在画面左侧，顾沉在画面右侧，两人相距一臂，面向对方，视线相交，彼此不接触，气氛克制而紧张。深色办公室，窗外城市夜景大光圈光斑",
        "landscape": "海报主视觉，宽幅中景，平视，双人对视构图：林晚在画面右侧，顾沉在她左侧，两人相距一臂，面向对方，视线相交，彼此不接触。画面左侧留出大片暗部空间。深色办公室，窗外城市夜景大光圈光斑",
    },
    "C": {  # 林晚单人特写
        "cast": [("林晚", "在画", "中", "前")],
        "portrait": "海报主视觉，近景（胸部以上），平视，林晚单人居中，脸朝镜头，眼神直视，神情平静而有力量，风吹动及腰蓝发。画面上方三分之一留白暗部。夜间城市背景，大光圈虚化光斑",
        "landscape": "海报主视觉，宽幅近景（胸部以上），平视，林晚单人在画面右三分之一，脸朝镜头，眼神直视，神情平静而有力量。画面左侧留出大片暗部空间。夜间城市背景，大光圈虚化光斑",
    },
}
# 第二季：同一批人物，色调偏冷，林晚更主导
S2_MOOD = {"A": "冷青蓝色调，林晚居中占主导", "B": "冷青蓝色调", "C": "冷青蓝色调，霓虹倒影"}


from common import poster_runs, run_of_season, season_of  # noqa: E402


def build_job(run: str, comp: str, kind: str):
    import image_jobs as IJ
    import runs as RN
    from ns_agent import frame_job as FJ
    spec = COMPS[comp]
    si = IJ.load_import(None)
    ep = next(e for e in si.episodes if e.number == 1)
    base = next(s for s in ep.shots if s.index == 5)
    cls = type(base.cast[0])
    cl = spec.get("cast_" + kind) or spec["cast"]
    cast = [cls(name=n, presence=p, x=x, depth=d, part=None, raw=f"{n}（{p}｜{x}｜{d}）") for n, p, x, d in cl]
    img = spec[kind] + "，" + STYLE + ("，" + S2_MOOD[comp] if season_of(run) > 1 else "，暖金色调")
    shot = base.model_copy(update={"index": 98, "cast": cast, "img_prompt": img, "img_triggers": [], "scene_id": base.scene_id})
    project = RN.primary_run(ROOT)
    job = FJ.build_first(project, ep, shot, si.globals)
    return job


def preflight(job):
    from ns_agent.gen_contract import preflight as PF
    req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by")}
    req.update(kind="image", project=job.get("framing_project"), shot_id=job["shot"])
    return PF.check(req)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--lane", default="gpu33:1")
    ap.add_argument("--expires")
    ap.add_argument("--only", default="")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--seed", type=int, default=7001)
    a = ap.parse_args(argv)
    todo = [f"s{season_of(r)}_{c}_{k}" for r in poster_runs() for c in "ABC" for k in ("portrait", "landscape")]
    if a.only:
        todo = [t for t in todo if t in a.only.split(",")]
    client = None
    if not a.dry:
        from ns_api import jobs as J
        client = J._make_client(a.lane)
    exp_at = datetime.fromisoformat(a.expires) if a.expires else None
    for key in todo:
        rk, comp, kind = key.split("_")
        run = run_of_season(int(rk[1:]))
        job = build_job(run, comp, kind)
        pf = preflight(job)
        bad = [i for i in pf.to_dict()["items"] if i["status"] == "fail"]
        print(key, "refs", len(job["refs"]), "preflight", "ok" if pf.ok else "FAIL", [f'{i["id"]}:{i["detail"]}' for i in bad], flush=True)
        if a.dry:
            if a.v:
                print(job["prompt"], job["refs"])
            continue
        if not pf.ok:
            continue
        if exp_at and (exp_at - datetime.now()).total_seconds() < 180:
            print("借道临近到期，停")
            return 2
        from ns_agent import comfy_tag as CT
        from ns_render import unified_frame as UF
        client.ns_tag = CT.make("POSTER", "poster", episode=None, shot=key, label=f"海报 {key}")
        out = ROOT / "data" / "posters" / run / "art"
        out.mkdir(parents=True, exist_ok=True)
        w, h = SIZE[kind]
        t0 = time.time()
        take, eff, post = UF._run(client, "ep01-S98", "image", job, a.seed, rel_dir=out.relative_to(ROOT / "data").as_posix(),
                                  overrides={"width": w, "height": h}, prefix=f"ns_poster/{run}/{key}")
        rec = {"key": key, "run": run, "comp": comp, "kind": kind, "seed": a.seed, "file": take.file, "seconds": take.seconds,
               "prompt": take.prompt, "refs": job["refs"], "created_at": take.created_at}
        with open(ROOT / "data" / "posters" / run / "art.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(key, take.file, f"{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
