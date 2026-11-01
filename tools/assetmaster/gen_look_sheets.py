"""ASSETMASTER：造型版设定图 v2——在 SERIES 四栏设定图作业（身份脸 + 姿势模板）上，追加本造型的单品产品图作参考
（<image3>… 逐一标注"必须一致"），让设定图里的服装 / 鞋 / 饰品与单品图一致。

单品图来源优先级：data/assetmaster/look_sheet_refs.json 人工指定（项目方决定，如林晚 B 束腰 = LW-O10）
                > 新出产品图暂定（data/assetmaster/items.json chosen）> 衣橱已有图（inventory lib 有图）。
输出 data/assetmaster/sheets_v2/<char>_look<L>_s<seed>.png + sheets_v2.json；postflight：本人 ArcFace（qc_batch "sheet:" 前缀）。
不改 registered_refs.json——总调度审后由 adopt 子命令替换（旧图留档）。

用法：.venv/Scripts/python.exe tools/assetmaster/gen_look_sheets.py gen [--only lin_wan_lookB] [--lanes gpu33:0,gpu33:1,gpu33:3]
      .venv/Scripts/python.exe tools/assetmaster/gen_look_sheets.py adopt   # 把 chosen 写进 registered_refs.json（暂定），清 refkit 缓存
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen"):
    sys.path.insert(0, str(ROOT / p))
RUN = ROOT / "data/pipeline/runs/series10_v1"
OUT = ROOT / "data/assetmaster/sheets_v2"
RES = Path(__import__("os").environ.get("AM_SHEETS_RES") or ROOT / "data/assetmaster/sheets_v2.json")
MANUAL = ROOT / "data/assetmaster/look_sheet_refs.json"
SLOTS = ("outfit", "shoes", "jewelry", "accessory", "nails")
SEEDS = (101, 202)
SEEDS_OVERRIDE = {"lin_wan_lookB": (303, 404, 505)}   # v2 第一版（101/202）束腰画成抹胸，不符合项目方 LW-O10 → 重出
SPECIAL = {"lin_wan_lookB": {"name": "黑色漆皮束腰", "file": "assets/characters/lin_wan/items/outfit/O10_product_s0.png",
                             "name_en": "black patent leather corset (owner-specified LW-O10)",
                             "desc": "a high-neck glossy black patent leather harness-corset with wide shoulder straps fastened by "
                                     "silver buckles, a large open cut-out window across the upper chest, a boned underbust waist "
                                     "with black criss-cross front lacing and silver eyelets, and buckled side straps."}}
ZH = {"outfit": "服装", "shoes": "鞋", "jewelry": "饰品", "accessory": "配件", "nails": "美甲"}


def refs_for(char: str, look: str) -> list[tuple[str, str]]:
    inv = json.loads((ROOT / "data/assetmaster/inventory.json").read_text(encoding="utf-8"))
    gen = json.loads((ROOT / "data/assetmaster/items.json").read_text(encoding="utf-8"))
    man = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    by = {(v["char"], v["name"]): v for v in gen.values()}
    extras = json.loads((ROOT / "data/assetmaster/look_extras.json").read_text(encoding="utf-8"))
    skip = {x["name"] for x in (extras.get(char) or {}).get(look, [])}     # 暂定外搭 / 装饰不进设定图
    out = []
    for e in inv["items"]:
        if e["name"] in skip:
            continue
        if e["char"] != char or e["look"] != look or not e["registered"] or e["slot"] not in SLOTS or e.get("tentative"):
            continue
        k = f"{char}:{look}:{e['name']}"
        f = None
        if k in man:
            f = man[k]
        elif (g := by.get((char, e["name"]))) and (g.get("chosen") or {}).get("ok"):
            f = g["chosen"]["file"]
        elif e["lib"]["status"] == "有图" and e["lib"]["matches"]:
            f = e["lib"]["matches"][0]["files"][0]
        if f:
            out.append((e["name"], f))
    return out[:6]


def graph_for(key: str, seed: int):
    import imggen as IG
    ch = IG.char_of(key)
    variant = "alanref" if ch == "ch_a_lan" and not key.endswith("A") else None
    g, prompt = IG.sheet_graph(key, seed, variant)
    enc = next(n for n in g.values() if n.get("class_type") == "TextEncodeQwenImage21")
    used = [k for k in enc["inputs"] if k.startswith("images.image_")]
    nxt = len(used) + 1
    lines = []
    refs = refs_for(ch, key[-1])
    sp = SPECIAL.get(key)
    if sp:                                    # 项目方指定的关键单品单独占一槽 + 明确文字（如林晚 B 束腰 = LW-O10）
        refs = [(n, f) for n, f in refs if n != sp["name"]]
        nid = str(950 + nxt)
        g[nid] = {"class_type": "LoadImage", "inputs": {"image": "@upload:" + sp["file"]}}
        enc["inputs"][f"images.image_{nxt}"] = [nid, 0]
        lines.append(f"<image{nxt}> is the exact {sp['name_en']}: {sp['desc']} It must be identical to <image{nxt}>; "
                     f"do NOT replace it with a strapless or sweetheart bustier.")
        nxt += 1
    if refs:                                   # 3090 显存：8 张参考 @2048 会 OOM → 单品拼成一张参考板（契约 I9）
        import flux_gen as FG
        bd = FG.board([f for _, f in refs], OUT / "boards" / f"{key}.png")
        nid = str(900 + nxt)
        g[nid] = {"class_type": "LoadImage", "inputs": {"image": "@upload:" + bd}}
        enc["inputs"][f"images.image_{nxt}"] = [nid, 0]
        lines.append(f"<image{nxt}> is the product reference board for this outfit ({', '.join(n for n, _ in refs)}): the clothing, "
                     f"shoes and accessories must match <image{nxt}> exactly in design, cut, color, material and details "
                     f"(must be identical); ignore its background and mannequins.")
    enc["inputs"]["prompt"] = enc["inputs"]["prompt"] + " " + " ".join(lines)
    IG.set_prefix(g, f"assetmaster_sheets/{key}_s{seed}")
    return g, enc["inputs"]["prompt"], ch


def gen(a):
    import imggen as IG
    keys = list(dict.fromkeys(j["shot"] for j in IG.sheet_jobs()))
    if a.only:
        keys = [k for k in keys if k in a.only.split(",")]
    res = json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else {}
    tasks = [(k, s) for k in keys for s in SEEDS_OVERRIDE.get(k, SEEDS) if not (res.get(k, {}).get(str(s)) or {}).get("file")]
    print("sheets", len(tasks), flush=True)
    lanes = {n: IG.LANES[n] for n in a.lanes.split(",")}
    lk = threading.Lock()

    def worker(lane, url):
        c = IG.Lane(lane, url)
        while True:
            with lk:
                if not tasks:
                    return
                key, seed = tasks.pop(0)
            try:
                g, prompt, ch = graph_for(key, seed)
                for n in g.values():
                    if n.get("class_type") == "LoadImage" and str(n["inputs"]["image"]).startswith("@upload:"):
                        n["inputs"]["image"] = c.upload(n["inputs"]["image"][8:])
                try:   # GPU 任务归属标签（K-OPS-G01）；出错就不带标签
                    _tag = IG._ct().make("ASSETMASTER", "sheet", obj=f"{ch} · {key}" if ch else key, label=f"s{seed}",
                                         job=f"{key}_s{seed}")
                except Exception:  # noqa: BLE001
                    _tag = None
                pid = c.submit(g, front=True, tag=_tag)
                dest = OUT / f"{key}_s{seed}.png"
                t0 = time.time()
                while True:
                    time.sleep(6)
                    r = c.fetch(pid, dest)
                    if r:
                        break
                rec = {"key": key, "seed": seed, "char": ch, "lane": lane, "status": r, "secs": round(time.time() - t0, 1),
                       "host_path": getattr(c, "last_host_path", None), "prompt": prompt, "refs": refs_for(ch, key[-1])}
                if r == "ok":
                    rec["file"] = str(dest.relative_to(ROOT)).replace("\\", "/")
                with lk:
                    res.setdefault(key, {})[str(seed)] = rec
                    RES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                print(time.strftime("%H:%M:%S"), lane, key, seed, r, rec["secs"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, key, seed, repr(e)[:300], flush=True)

    th = [threading.Thread(target=worker, args=(n, u)) for n, u in lanes.items()]
    [t.start() for t in th]
    [t.join() for t in th]
    pick(res)
    RES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def pick(res):
    """postflight：设定图左栏本人脸 ArcFace（qc_batch 对 FACE 三位主角；阿岚只看与他人 <0.40）"""
    import imggen as IG
    files = {f"sheet:{k}/{s}": (None, v["lane"].split(":")[0], v["host_path"]) for k, d in res.items()
             for s, v in d.items() if isinstance(v, dict) and v.get("host_path")}
    try:
        out = IG.qc_batch(files)
    except Exception as e:  # noqa: BLE001
        print("qc_err", repr(e)[:200])
        return
    for k, d in res.items():
        best = None
        for s, v in d.items():
            if not isinstance(v, dict) or not v.get("file"):
                continue
            q = out["items"].get(f"sheet:{k}/{s}") or {}
            sims = {}
            for f in q.get("faces", []):
                for c, x in (f.get("sims") or f.get("sim") or {}).items():
                    sims[c] = max(sims.get(c, -1), x)
            v["sim"] = sims
            ch = v.get("char") or k.rsplit("_look", 1)[0]
            own = sims.get(ch)
            others = max([x for c, x in sims.items() if c != ch] or [0])
            thr = 0.70 if ch == "lin_wan" else 0.60
            v["ok"] = (own is None and ch == "ch_a_lan" and others < 0.40) or (own is not None and own >= thr)
            key = (v["ok"], own or 0)
            if best is None or key > best[0]:
                best = (key, s)
        if best:
            d["chosen"] = {"seed": best[1], "file": d[best[1]]["file"], "ok": d[best[1]]["ok"], "tentative": True}


PANELS = ("half", "front", "side", "back")


def _atomic_json(p: Path, d) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def prewarm(sheet_rel: str, project: str = "series10_v1") -> list[str]:
    """新设定图的裁切先全部生成好（指针切换前，没有任何作业引用这些新文件名 → 等价于原子换入）"""
    from ns_agent import asset_refs as AR
    out = []
    for pn in PANELS:
        for name in (pn, pn + "_nohead"):
            for zone in (None, *AR.ZONE_SPAN):
                if name.endswith("_nohead") and zone:
                    continue
                try:
                    out.append(AR.sheet_crop(project, sheet_rel, name, zone))
                except Exception:  # noqa: BLE001
                    pass
    return out


def adopt(a):
    """总调度审过后：chosen 设定图换入（K-AST-261）。
    1) 复制成带版本的新文件名（sheets_v2/adopted/<key>_v2_s<seed>.png）→ 裁切缓存文件名不和旧图撞；
    2) 先为新文件名生成全部裁切（prewarm），再原子改写 registered_refs.json 与 sheets_chosen.json（tmp + replace）；
    3) 不删除任何旧文件：排队中的作业还引用旧裁切（01:29 job b30ec4a4e11e 因旧做法删缓存 Errno 2）。"""
    import shutil
    res = json.loads(RES.read_text(encoding="utf-8"))
    rp = RUN / "assets/registered_refs.json"
    sp = RUN / "assets/sheets_chosen.json"
    reg = json.loads(rp.read_text(encoding="utf-8"))
    sc = json.loads(sp.read_text(encoding="utf-8"))
    ts = time.strftime("%Y%m%d_%H%M%S")
    _atomic_json(rp.with_name(f"registered_refs.before_sheets_v2_{ts}.json"), reg)
    _atomic_json(sp.with_name(f"sheets_chosen.before_sheets_v2_{ts}.json"), sc)
    only = set((getattr(a, "only", None) or "").split(",")) - {""}
    adopted = []
    for key, d in res.items():
        if key.startswith("_") or (only and key not in only):
            continue
        c = d.get("chosen")
        if not c or not c.get("ok"):
            continue
        ch, look = key.rsplit("_look", 1)[0], key[-1]
        src = ROOT / c["file"]
        dst = OUT / "adopted" / f"{key}_v2_s{c.get('seed') or 0}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(src, dst)
        new = str(dst.relative_to(ROOT)).replace("\\", "/")
        if getattr(a, "prewarm", True):
            prewarm(new)
        hit = [r for r in reg if r["asset"] == ch and r.get("look") == look and r.get("role") == "item"]
        for r in hit:
            r.setdefault("sheets_v1_src", r["src"])
            r["src"] = new
            r["note"] = "ASSETMASTER 造型版设定图 v2（单品图锁定，暂定）"
        if not hit:
            reg.append({"asset": ch, "role": "item", "look": look, "src": new, "note": "ASSETMASTER 造型版设定图 v2（暂定）"})
        e = sc.setdefault(f"sheet:{key}", {"char": ch, "look": key})
        e.setdefault("file_v1", e.get("file"))
        e.update(file=new, seed=int(c.get("seed") or 0), source_file=c["file"], model=c.get("model") or "qwen-image-2.1",
                 note="ASSETMASTER 造型版设定图 v2（单品图锁定，暂定）")
        adopted.append(key)
    _atomic_json(rp, reg)
    _atomic_json(sp, sc)
    print("adopted", adopted)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "adopt", "pick", "refs"])
    ap.add_argument("--only")
    ap.add_argument("--lanes", default="gpu33:0,gpu33:1,gpu33:3")
    ap.add_argument("--no-prewarm", dest="prewarm", action="store_false")
    a = ap.parse_args(argv)
    if a.cmd == "gen":
        gen(a)
    elif a.cmd == "adopt":
        adopt(a)
    elif a.cmd == "pick":
        res = json.loads(RES.read_text(encoding="utf-8"))
        pick(res)
        RES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        import imggen as IG
        for j in IG.sheet_jobs():
            print(j["shot"], refs_for(IG.char_of(j["shot"]), j["shot"][-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
