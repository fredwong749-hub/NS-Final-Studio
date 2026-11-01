"""REFLOCK 2026-10-31：生成契约 Q2（造型）/ Q4（质感）/ Q7（场景）阈值标定（证据进 knowledge K-GEN-202..205）。

正例 / 反例只用“已知答案”的图：造型设定图正面栏（设定图本身就是登记造型）、衣橱 worn 图；
现有 series10 首帧（只挂脸、服装靠文字，项目方说“鞋都不一样”）只作分布参考，不当正例。
输出 data/review_pages/asset_reflock/calibration.json
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))
from PIL import Image  # noqa: E402

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent.gen_contract import postflight as Q  # noqa: E402

P = "series10_v1"
OUT = ROOT / "data/review_pages/asset_reflock/calibration.json"


def im(p):
    return Image.open(ROOT / p).convert("RGB")


def front(cid, lk):
    return AR.sheet_crop(P, AR.sheet_of(P, cid, lk), "front")


def main():
    t0 = time.time()
    res = {"shoes": [], "skirt": [], "sheet": [], "texture": [], "scene": []}
    S01 = Q._ref_crop(im("assets/characters/lin_wan/items/shoes/S01_side45_s0.png"))
    O09 = Q._ref_crop(im("assets/characters/lin_wan/items/outfit/O09_product_s0.png"))
    shoe_cases = [("lin_wan A 设定图正面（透明细高跟）", front("lin_wan", "A"), True),
                  ("lin_wan B 设定图正面（侧开透明细高跟）", front("lin_wan", "B"), True),
                  ("S01 worn 上脚图", "assets/characters/lin_wan/items/shoes/S01_worn_s0.png", True),
                  ("lin_wan C 设定图（白球鞋）", front("lin_wan", "C"), False),
                  ("gu_chen A（黑皮鞋）", front("gu_chen", "A"), False), ("gu_chen C（拖鞋）", front("gu_chen", "C"), False),
                  ("chen_yu A（白帆布鞋）", front("chen_yu", "A"), False), ("chen_yu B（棕皮鞋）", front("chen_yu", "B"), False),
                  ("ch_a_lan A（黑短靴）", front("ch_a_lan", "A"), False), ("ch_a_lan B（马丁靴）", front("ch_a_lan", "B"), False)]
    for lab, p, pos in shoe_cases:
        r = Q.region_match(im(p), S01, "feet")
        res["shoes"].append({"case": lab, "file": p, "positive": pos, **{k: v for k, v in r.items() if k != "box"}})
        print("shoe", lab, r["clip"], r["hist"], flush=True)
    skirt_cases = [("lin_wan B 设定图（漆皮短裙）", front("lin_wan", "B"), True),
                   ("O09 worn", "assets/characters/lin_wan/items/outfit/O09_worn_s0.png", True),
                   ("lin_wan A（深灰西装裙）", front("lin_wan", "A"), False), ("lin_wan C（雾蓝针织长裙）", front("lin_wan", "C"), False),
                   ("ch_a_lan C（黑阔腿裤）", front("ch_a_lan", "C"), False), ("gu_chen B（黑西裤）", front("gu_chen", "B"), False)]
    for lab, p, pos in skirt_cases:
        r = Q.region_match(im(p), O09, "lower")
        res["skirt"].append({"case": lab, "file": p, "positive": pos, **{k: v for k, v in r.items() if k != "box"}})
        print("skirt", lab, r["clip"], r["hist"], flush=True)
    # 设定图 vs 现有首帧（造型层面区分度；首帧服装靠文字，只看分布）
    d = json.loads((ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json").read_text(encoding="utf-8"))
    import collections
    per = collections.defaultdict(list)
    dry = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) if len(sys.argv) > 1 else d
    for j in dry["jobs"]:
        rec = j.get("asset_refs") or {}
        ch = next((c for c in rec.get("characters") or [] if c["character"] == "lin_wan" and c.get("primary")), None)
        if ch and ch.get("look") and rec.get("size") in ("中景", "中全景", "全景", "全身") and (ROOT / j["out"]).exists():
            per[ch["look"]].append(j["out"])
    sheets = {lk: im(front("lin_wan", lk)) for lk in "ABC"}
    for lk, outs in per.items():
        for o in outs[:4]:
            g = im(o)
            row = {"frame": o, "look": lk}
            for s, sim in sheets.items():
                row[s] = Q.region_match(g, sim)["clip"]
            res["sheet"].append(row)
            print("sheet", row, flush=True)
    # 质感分布（现有首帧，中心区域）
    for j in dry["jobs"]:
        if (ROOT / j["out"]).exists():
            res["texture"].append({"frame": j["out"], **Q.texture(im(j["out"]))})
    # 场景：sk_office 参考 vs ep01（办公室）与其它场景首帧
    sref = AR.scene_ref("sk_office_night")
    if sref:
        e_ref = Q.embed([im(sref)])[0]
        for j in dry["jobs"][:40]:
            if (ROOT / j["out"]).exists():
                e = Q.embed([im(j["out"])])[0]
                res["scene"].append({"frame": j["out"], "office": j["shot"].startswith("ep01"), "clip": round(float(e @ e_ref), 4)})
    res["seconds"] = round(time.time() - t0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", res["seconds"], flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
