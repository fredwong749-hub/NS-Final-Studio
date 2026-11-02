"""IMGMASTER A/B 真出图：ep01 同场 10 镜，旧入口（现行 build_first）和新入口（compile_frame_v2）各 1 张，同 seed。
走 ns_render.unified_frame.render_ab（scope=ab）：不写 takes.json、不写契约账本，图在 data/ab/imgmaster/<shot>/，记录追加 data/ab/imgmaster/takes.jsonl。
借道：tools/debug/lanes.py 登记的 gpu33:1（到期前自己停）。用法：
  .venv/Scripts/python.exe tools/imgmaster/ab_run.py --lane gpu33:1 [--shots 1,2,..] [--expires 2026-11-02T14:34:59]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "services/api", "tools/prompt_v2", "tools/pipeline", "tools/autopilot", "tools/imgmaster"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

EXP = "imgmaster"
OUT = ROOT / "data/ab/imgmaster"


def done() -> set:
    f = OUT / "takes.jsonl"
    if not f.exists():
        return set()
    return {(r["shot"], r["tier"]) for r in (json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="gpu33:1")
    ap.add_argument("--shots", default="1,2,3,4,5,6,7,8,9,10")
    ap.add_argument("--expires", required=True, help="借道 expires_at，临近 3 分钟就停")
    ap.add_argument("--ep", type=int, default=1)
    a = ap.parse_args(argv)
    import trial_compile as T
    import image_jobs as IJ
    import runs as RN
    from ns_agent import asset_refs as AR
    from ns_agent import comfy_tag as CT
    from ns_agent import frame_job as FJ
    from ns_agent.bible import load_bible
    from ns_api import jobs as J
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    from ns_schema.script import ScriptImport
    run = RN.primary_run(ROOT)
    sc = ScriptImport.model_validate(json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8")))
    si = IJ.load_import(None)
    g = si.globals
    ep = next(e for e in si.episodes if e.number == a.ep)
    cont = T.trial_lock_file(a.ep, run, ROOT / "data/review_pages/imgmaster", {s.scene_id for s in ep.shots if s.scene_id})
    srs = {s.index: AR.resolve_shot(run, ep, IJ.retrigger(s, g)) for s in ep.shots}
    looks = AR.scene_look_refs(list(srs.values()))
    exp_at = datetime.fromisoformat(a.expires)
    client = J._make_client(a.lane)
    seen = done()
    for idx in [int(x) for x in a.shots.split(",")]:
        shot = next(s for s in ep.shots if s.index == idx)
        sid = f"ep{a.ep:02d}-S{idx}"
        seed = P.seed_for(sid + "/v9", 1)
        new = FJ.compile_frame_v2(ep, shot, g, run, cont, bible=load_bible(), available=IJ.AVAILABLE_IMAGE_LORAS, scene_looks=looks)
        tr = FJ.write_compile_trace(new["trace"], OUT / "traces")
        patch = {"prompt": new["prompt"], "refs": new["plan"].files, "asset_refs": AR.record(new["sr"], new["plan"])}
        for tier, jp in (("old", None), ("new", patch)):
            if (sid, tier) in seen:
                continue
            if (exp_at - datetime.now()).total_seconds() < 180:
                print("借道临近到期，停", flush=True)
                return 2
            tag = CT.make("IMGMASTER", "bakeoff", episode=a.ep, shot=f"S{idx}", label=f"A/B {tier}")
            t0 = time.time()
            try:
                rec = UF.render_ab(client, sc, sid, experiment=EXP, tier=tier, seed=seed, tag=tag, job_patch=jp)
            except Exception as e:  # noqa: BLE001
                print(sid, tier, "失败：", type(e).__name__, str(e)[:300], flush=True)
                continue
            print(sid, tier, rec["file"], f"{time.time() - t0:.0f}s", "trace", tr["sha"][:8] if tier == "new" else "", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
