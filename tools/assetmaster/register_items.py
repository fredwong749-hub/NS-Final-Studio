"""把 gen_items.py 选出的暂定产品图登记进衣橱（POST /api/looks/wardrobe/items + /images），标暂定。
只登记 postflight 通过（chosen.ok）的；按 sha256 去重（重复执行不重复上传）。登记结果写 data/assetmaster/registered_items.json。

用法：.venv/Scripts/python.exe tools/assetmaster/register_items.py [--names 短款西装外套,腰侧九枚细金属环] [--all] [--api http://127.0.0.1:5173]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx as requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/assetmaster/registered_items.json"
SLOT = {"outfit": "outfit", "shoes": "shoes", "legwear": "outfit", "jewelry": "accessory", "accessory": "accessory",
        "piercing": "accessory", "nails": "nails", "body_mark": "other"}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:5173")
    a = ap.parse_args(argv)
    names = {x for x in a.names.split(",") if x}
    gen = json.loads((ROOT / "data/assetmaster/items.json").read_text(encoding="utf-8"))
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    w = requests.get(f"{a.api}/api/looks/wardrobe", timeout=30).json()
    have = {i["id"]: i for i in w["items"]}
    for slug, d in gen.items():
        if not (a.all or d["name"] in names):
            continue
        c = d.get("chosen_final") or d.get("chosen") or {}      # choose.py 选定的最终版（FLUX / Qwen）优先
        if not c.get("ok"):
            print("skip（未通过）", d["char"], d["name"])
            continue
        iid = f"am-{d['char']}-{slug}"
        if iid not in have:
            body = {"id": iid, "slot": SLOT.get(d["slot"], "other"), "name": d["name"], "description": "",
                    "character": d["char"], "keywords": [d["name"]], "prompt_policy": "when_in_shot", "removable": True,
                    "source": "assetmaster", "needs_review": True,
                    "notes": [f"暂定｜ASSETMASTER 产品参考图（{c.get('model') or 'qwen-image-2.1'}）", f"造型 {','.join(d['looks'])}",
                              f"出现镜头 {' '.join(d['shots'][:20])}"]}
            r = requests.post(f"{a.api}/api/looks/wardrobe/items", json=body, timeout=60)
            if r.status_code not in (200, 201):
                print("create fail", iid, r.status_code, r.text[:300])
                continue
        files = [c["file"]]
        if c.get("model") in (None, "qwen-image-2.1"):
            files += [v["file"] for k, v in sorted(d["cands"].items()) if v.get("ok") and v["file"] != c["file"] and v["view"] == "side"]
        rec = done.setdefault(iid, {"char": d["char"], "name": d["name"], "slug": slug, "images": []})
        for f in files:
            sha = hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
            if any(x["sha256"] == sha for x in rec["images"]):
                continue
            with open(ROOT / f, "rb") as fh:
                r = requests.post(f"{a.api}/api/looks/wardrobe/items/{iid}/images",
                                  files={"file": (Path(f).name, fh, "image/png")}, data={"variant": "clean"}, timeout=120)
            if r.status_code != 200:
                print("upload fail", iid, r.status_code, r.text[:300])
                continue
            rec["images"].append({"src": f, "sha256": sha, "file": r.json()["image"]["file"]})
        rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        print("ok", iid, d["name"], len(rec["images"]))
    OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
