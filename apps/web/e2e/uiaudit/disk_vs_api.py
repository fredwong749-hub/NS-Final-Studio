"""UIAUDIT：盘上 takes.json（active / 版本数）vs 接口 first_frame / last / video（只读）。
用法：python disk_vs_api.py r19_api_distinct.json out.json
"""
import json, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[4]
api = json.load(open(sys.argv[1], encoding="utf-8"))
rows = []
for e in api["episodes"]:
    for r in e["rows"]:
        sid = r["id"]
        ep, s = sid.split("-")
        p = ROOT / "data" / "renders" / ep / s / "takes.json"
        cnt = {"image": 0, "last": 0, "video": 0}
        active = {}
        if p.exists():
            t = json.loads(p.read_text(encoding="utf-8"))
            for tk in t.get("takes", []):
                cnt[tk.get("stage")] = cnt.get(tk.get("stage"), 0) + 1
            active = t.get("active") or {}
        rows.append({"id": sid, "takes_json": p.exists(), "n_image": cnt["image"], "n_last": cnt["last"], "n_video": cnt["video"],
                     "active": active, "api_ff": bool(r["ff"]), "api_lf": bool(r["lf"]), "api_video": bool(r["video"])})
json.dump(rows, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
gap = [x for x in rows if (x["n_image"] and not x["api_ff"]) or (x["n_video"] and not x["api_video"]) or (x["n_last"] and not x["api_lf"])]
print(f"shots={len(rows)}  有版本但接口无当前={len(gap)}")
for x in gap:
    print(f"  {x['id']}: image{x['n_image']}/api_ff={x['api_ff']} last{x['n_last']}/api_lf={x['api_lf']} video{x['n_video']}/api_v={x['api_video']} active={x['active']}")
