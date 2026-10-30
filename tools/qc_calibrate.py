"""
裸露质检（qc.py）校准：在带标签的图片集上比较 CLIP 提示词组与阈值。

    uv run python tools/qc_calibrate.py            # 收集标签（必要时用本地看图模型给不确定的渲染图打标签）→ 打分 → 报告
标签来源：
  clothed  资产会话核对过的着装资产（assets/characters/**：outfit/looks/plates/expressions/makeup/candidates）
           + 已人工看过确认着装的渲染图（golden/quality_v2 下的列表 CLOTHED_SEEN）
  nude     人工看过的真阳性（NUDE_SEEN）+ NudeNet 露出部位命中的渲染图
  vlm      其余被旧质检拦下的渲染图：本地 Qwen3-VL 判断（不需要人看）
结果写 golden/qc_calibration/results.json，阈值写进报告。
"""
import json
import sys
from pathlib import Path

from ns_render import qc as Q
from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "golden" / "qc_calibration"
CLOTHED_SEEN = [  # 本会话人工看过、确认着装的图
    "data/renders/ep01/S2/frame.png", "data/renders/ep01/S3/frame.png",
    "golden/quality_v2/smoke2/renders/ep01/S5/takes/image_002.png",
    "golden/quality_v2/smoke2/renders/ep01/S5/takes/image_003.png",
    "golden/quality_v2/sweep/ep01-S5_full_768_head.png", "golden/quality_v2/sweep/ep01-S5_face_512_head.png",
    "golden/quality_v2/sweep/ep01-S3_two_i1_768.png", "golden/quality_v2/sweep/ep02-S1_two_i1_768.png",
    "golden/quality_v2/sweep/ep01-S6_two_i1_768.png", "golden/quality_v2/idfix/swap768.png",
    "assets/style/color_reference_01.png",
]
NUDE_SEEN = ["golden/quality_v2/sweep/ep01-S5_none_0_head.png",    # 人工看过：背面赤裸
             "data/renders/ep01/S5/takes/image_003.png",               # 背面赤裸（v1 漏检）
             "data/renders/ep04/S6/takes/image_002.png"]               # 上身赤裸只用手机遮挡（v1 漏检）
ASSET_DIRS = ["items/outfit", "looks", "plates", "expressions", "items/makeup", "candidates"]
VLM_Q = ("Look at this image carefully. Is any person in it nude or topless — bare female breasts, a bare male or "
         "female chest with no clothing on the upper body, a completely bare back with no top, or exposed genitals "
         "or buttocks? Bare arms, legs, feet, shoulders, cleavage in a top, or a strapless dress do NOT count. "
         "Answer only yes or no.")


def vlm_label(client, path: Path) -> bool | None:
    name = client.upload_image(path, subfolder="ns_final/qc")
    try:
        entry, _ = client.run(W.text_generate(VLM_Q, "ns_final/vlm", image=name, max_length=4), timeout_s=300)
    except Exception as e:  # noqa: BLE001 — 拿不到标签就不用这张
        print("VLM 失败，跳过", path.name, str(e)[:80], flush=True)
        return None
    t = "".join(entry.get("outputs", {}).get("90", {}).get("text", []) or []).strip().lower()
    return True if t.startswith("yes") else False if t.startswith("no") else None


def collect(client) -> list[dict]:
    items = []
    for d in ASSET_DIRS:
        for p in sorted((ROOT / "assets" / "characters").glob(f"*/{d}/*.png")):
            if "rejected" in p.name:
                continue
            items.append({"file": p, "label": False, "src": f"asset:{d}"})
    items += [{"file": ROOT / f, "label": False, "src": "seen"} for f in CLOTHED_SEEN if (ROOT / f).exists()]
    items += [{"file": ROOT / f, "label": True, "src": "seen"} for f in NUDE_SEEN if (ROOT / f).exists()]
    flagged = []
    for tj in (ROOT / "data" / "renders").glob("ep*/S*/takes.json"):
        for t in json.loads(tj.read_text(encoding="utf-8"))["takes"]:
            q = t.get("qc") or {}
            if q.get("nudity") and (ROOT / "data" / t["file"]).exists():
                flagged.append((ROOT / "data" / t["file"], q))
    for p, q in flagged:
        if q.get("hits"):
            items.append({"file": p, "label": True, "src": "nudenet"})
        else:
            lab = vlm_label(client, p)
            if lab is not None:
                items.append({"file": p, "label": lab, "src": "vlm"})
    return items


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = ComfyClient()
    items = collect(client)
    rows = []
    for it in items:
        old = Q.clip_bare_score_legacy(it["file"])
        new = Q.clip_bare_score(it["file"])
        rows.append({"file": str(it["file"].relative_to(ROOT)), "label": it["label"], "src": it["src"],
                     "old": old, "new": new})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    pos = [r for r in rows if r["label"]]
    neg = [r for r in rows if not r["label"]]
    print(f"标签：nude {len(pos)}，clothed {len(neg)}")
    for key, thr in (("old", 0.80), ("new", Q.CLIP_THRESHOLD)):
        fp = sum(r[key] >= thr for r in neg)
        tp = sum(r[key] >= thr for r in pos)
        print(f"{key} @ {thr}: 误报 {fp}/{len(neg)}  命中 {tp}/{len(pos)}")
    for thr in (0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9):
        print(f"  new @ {thr}: 误报 {sum(r['new'] >= thr for r in neg)}/{len(neg)}  "
              f"命中 {sum(r['new'] >= thr for r in pos)}/{len(pos)}")
    worst = sorted(neg, key=lambda r: -r["new"])[:8]
    print("着装图里新分数最高：", [(r["file"][-50:], r["new"]) for r in worst])
    miss = sorted(pos, key=lambda r: r["new"])[:8]
    print("裸露图里新分数最低：", [(r["file"][-50:], r["src"], r["new"]) for r in miss])


if __name__ == "__main__":
    sys.exit(main())
