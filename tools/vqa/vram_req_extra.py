"""VQAGATE 11-01：gpu36 口径对照的补充请求——单品串人（item_on_wrong_person）正 / 反例。
正例：data/ab/localgpu_verify/repro_S4_vN/ep01-S4_vN_s20261311_local_raw_post.png（顾沉右手长着林晚的满钻尖甲，AUDIT 19:3x；VQAGATE 目视确认）；
反例：reflock_val ep01-S4 asset / noasset s20261311、asset s20261312（目视顾沉手部正常）；noasset s20261312 手部看不清，记 None。
提示词与参考 = ep01-S4 当前首帧（同一镜）。→ data/vqa/vram_bench/requests_extra.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/vqa", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))
from ns_agent.vqa import rubric  # noqa: E402
import gate_scan as GS  # noqa: E402

from ns_render import pipeline as P  # noqa: E402
t = next(x for x in P.load_takes("ep01-S4")["takes"] if x.get("stage") == "image" and x.get("n") == 5)   # 标定时的 ep01-S4 当前版 v5
refs = GS.refs_of("ep01-S4", t)
rv = "data/pipeline/runs/series10_v1/images/reflock_val/"
items = [("data/ab/localgpu_verify/repro_S4_vN/ep01-S4_vN_s20261311_local_raw_post.png", True),
         (rv + "ep01-S4_noasset_s20261311.png", False), (rv + "ep01-S4_asset_s20261311.png", False),
         (rv + "ep01-S4_asset_s20261312.png", False), (rv + "ep01-S4_noasset_s20261312.png", None)]
reqs = []
for f, lab in items:
    r = rubric.build_image_request(str(ROOT / f), t.get("prompt") or "", refs)
    reqs.append({"id": Path(f).name, "label_item_wrong_person": lab, "label": None, "req": r})
(ROOT / "data/vqa/vram_bench/requests_extra.json").write_text(json.dumps(reqs, ensure_ascii=False, indent=0), encoding="utf-8")
print(len(reqs))
