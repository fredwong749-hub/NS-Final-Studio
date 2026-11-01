"""ASSETMASTER：用 FLUX.2 [klein] 4B（Apache-2.0，蒸馏 4 步，多参考 ReferenceLatent）重出资产，与 Qwen 版并排对比、按契约自动选暂定。
项目方原话（总调度 2026-11-01 转）："人物的资产，场景的资产全部做完了好吗？要用新的模型，用那个 flux 的模型。"

种类：
  scene  6 场景 × 3 seed 空镜底图（同一光线基线：场景表原文，系统只加空镜包装句；与 IMGGEN scene_plates 同一提示词）
  item   38 件单品 × 3（正面 ×2 + 侧 45°）产品图（提示词同 gen_items.py）
  sheet  12 套造型 × 2 seed 四栏设定图：图1 身份脸、图2 四栏姿势模板、图3 本造型单品参考板（拼板，I9）
图结构照抄 BAKEOFF tools/bakeoff/run.py klein 分支（CLIPLoader flux2 + ReferenceLatent + Flux2Scheduler + CFGGuider cfg1）。
结果：data/assetmaster/flux/{scenes,items,sheets}.json；图在 data/assetmaster/flux/<kind>/…；postflight 复用 gen_items.pick /
gen_look_sheets.pick（身份 Q1）/ scene_plates.pick（0 脸 0 字 + 清晰度）。

用法：.venv/Scripts/python.exe tools/assetmaster/flux_gen.py {scene,item,sheet,all} [--lanes gpu33:0,gpu33:1,gpu33:3]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen", "tools/assetmaster"):
    sys.path.insert(0, str(ROOT / p))
OUT = ROOT / "data/assetmaster/flux"
M = dict(unet="flux-2-klein-4b.safetensors", clip="qwen_3_4b.safetensors", vae="flux2-vae.safetensors", steps=4, cfg=1.0)
POSE = "data/ab/owner_workflows/aisley_char_sheet/character_sheet_pose.png"
SHEET_TXT = ("图1只提供人物身份：脸、肤色、身材比例和发型，不取图1的服装。图2是四栏版式与姿势模板：严格按图2的四栏布局、姿势、裁切和人物比例，"
             "只取姿势与构图，不取人台外观。图3是本造型全部单品的参考板：服装、鞋、饰品的款式、颜色、材质必须与图3完全一致，不取图3的背景。"
             "人物穿着：{outfit}。最左栏是放大的正面头肩特写（头正、双眼看镜头、完整发型、裁到上胸）；第二栏全身正面站立，双脚完整入画；"
             "第三栏全身标准侧面朝画面右侧；第四栏全身背面站立。四栏是同一个人，身份与服装细节一致。纯白摄影棚背景，柔和均匀光，真实摄影质感，"
             "无文字、无其他人。")


def graph(prompt: str, names: list[str], w: int, h: int, seed: int, prefix: str) -> dict:
    g, n = {}, [0]

    def add(ct, **inp):
        n[0] += 1
        k = str(n[0])
        g[k] = {"class_type": ct, "inputs": {a: ([b[0], b[1]] if isinstance(b, tuple) else b) for a, b in inp.items()}}
        return (k, 0)

    model = add("UNETLoader", unet_name=M["unet"], weight_dtype="default")
    vae = add("VAELoader", vae_name=M["vae"])
    clip = add("CLIPLoader", clip_name=M["clip"], type="flux2", device="default")
    pos = add("CLIPTextEncode", clip=clip, text=prompt)
    neg = add("CLIPTextEncode", clip=clip, text="")
    for nm in names:
        img = add("LoadImage", image=nm)
        lt = add("VAEEncode", pixels=img, vae=vae)
        pos = add("ReferenceLatent", conditioning=pos, latent=lt)
        neg = add("ReferenceLatent", conditioning=neg, latent=lt)
    guider = add("CFGGuider", model=model, positive=pos, negative=neg, cfg=M["cfg"])
    out = add("SamplerCustomAdvanced", noise=add("RandomNoise", noise_seed=seed), guider=guider,
              sampler=add("KSamplerSelect", sampler_name="euler"), sigmas=add("Flux2Scheduler", steps=M["steps"], width=w, height=h),
              latent_image=add("EmptyFlux2LatentImage", width=w, height=h, batch_size=1))
    dec = add("VAEDecode", samples=out, vae=vae)
    add("SaveImage", images=dec, filename_prefix=prefix)
    return g


def board(files: list[str], dest: Path) -> str:
    """单品参考板：浅灰底横排拼接（I9 槽位不足 → 参考板）"""
    from PIL import Image
    ims = [Image.open(ROOT / f).convert("RGB") for f in files]
    H = 640
    ims = [im.resize((int(im.width * H / im.height), H)) for im in ims]
    W = sum(im.width for im in ims) + 16 * (len(ims) + 1)
    c = Image.new("RGB", (W, H + 32), (232, 232, 230))
    x = 16
    for im in ims:
        c.paste(im, (x, 16))
        x += im.width + 16
    dest.parent.mkdir(parents=True, exist_ok=True)
    c.save(dest)
    return str(dest.relative_to(ROOT)).replace("\\", "/")


def tasks_scene():
    import scene_plates as SP
    t = SP.scene_table()
    return [dict(kind="scene", key=sid, seed=s, prompt=SP.prompt_for(t[sid]), refs=[], w=768, h=1344,
                 dest=OUT / "scene" / sid / f"plate_s{s}.png") for sid in SP.SCENES for s in (801, 802, 803)]


def tasks_item():
    import gen_items as GI
    out = []
    for it in GI.items_to_make(None) + _registered_extra():
        for view, seed, vz in GI.VIEWS:
            out.append(dict(kind="item", key=it["slug"], it=it, view=view, seed=seed, prompt=GI.prompt_for(it, vz), refs=[],
                            w=768, h=1344, dest=OUT / "item" / it["char"] / it["slug"] / f"{view}_s{seed}.png"))
    return out


def _registered_extra():
    """todo 里已登记掉（缺图→有图）的单品仍要出 FLUX 版对比：从 Qwen 结果表补回"""
    import gen_items as GI
    have = {(i["char"], i["name"]) for i in GI.items_to_make(None)}
    q = json.loads((ROOT / "data/assetmaster/items.json").read_text(encoding="utf-8"))
    return [{k: v[k] for k in ("char", "name", "slot", "looks", "shots", "slug")} for v in q.values() if (v["char"], v["name"]) not in have]


def tasks_sheet():
    import imggen as IG
    import gen_look_sheets as GS
    looks = json.loads((ROOT / "data/pipeline/runs/series10_v1/P1_looks.json").read_text(encoding="utf-8"))
    zh = {(c["char_id"], l["id"]): l["zh"] for c in looks for l in c["looks"]}
    face = dict(IG.FACE)
    face["ch_a_lan"] = str(IG.ALAN_FACE.relative_to(ROOT)).replace("\\", "/")
    out = []
    for j in IG.sheet_jobs():
        key = j["shot"]
        ch, lk = IG.char_of(key), key[-1]
        refs = GS.refs_for(ch, lk)
        b = board([f for _, f in refs], OUT / "sheet" / "boards" / f"{key}.png") if refs else None
        names = [face[ch], POSE] + ([b] if b else [])
        for s in (101, 202):
            out.append(dict(kind="sheet", key=key, char=ch, seed=s, prompt=SHEET_TXT.format(outfit=zh.get((ch, lk), "")), refs=names,
                            w=1984, h=1120, dest=OUT / "sheet" / f"{key}_s{s}.png", items=[n for n, _ in refs]))
    return out


def run(tasks, lanes):
    import imggen as IG
    res = {k: (json.loads((OUT / f"{k}s.json").read_text(encoding="utf-8")) if (OUT / f"{k}s.json").exists() else {})
           for k in ("scene", "item", "sheet")}
    tasks = [t for t in tasks if not (res[t["kind"]].get(t["key"], {}).get("cands", {}).get(t["dest"].stem) or {}).get("file")]
    print("flux tasks", len(tasks), flush=True)
    lk = threading.Lock()

    def save():
        OUT.mkdir(parents=True, exist_ok=True)
        for k, v in res.items():
            (OUT / f"{k}s.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")

    def worker(lane, url):
        c = IG.Lane(lane, url)
        while True:
            with lk:
                if not tasks:
                    return
                t = tasks.pop(0)
            try:
                names = [c.upload(r) for r in t["refs"]]
                g = graph(t["prompt"], names, t["w"], t["h"], t["seed"], f"assetmaster_flux/{t['kind']}_{t['key']}_{t['dest'].stem}")
                try:   # GPU 任务归属标签（K-OPS-G01）；出错就不带标签
                    _tag = IG._ct().make("ASSETMASTER", "sheet", obj=f"{t['kind']} {t['key']}", label=f"FLUX {t['dest'].stem}",
                                         job=f"{t['kind']}_{t['key']}_{t['dest'].stem}")
                except Exception:  # noqa: BLE001
                    _tag = None
                pid = c.submit(g, front=True, tag=_tag)
                t0 = time.time()
                while True:
                    time.sleep(3)
                    r = c.fetch(pid, t["dest"])
                    if r:
                        break
                rec = {"lane": lane, "status": r, "secs": round(time.time() - t0, 1), "host_path": getattr(c, "last_host_path", None), "seed": t["seed"],
                       "prompt": t["prompt"], "refs": t["refs"], "model": "flux2-klein-4b", "view": t.get("view", "front")}
                if r == "ok":
                    rec["file"] = str(t["dest"].relative_to(ROOT)).replace("\\", "/")
                with lk:
                    d = res[t["kind"]].setdefault(t["key"], {})
                    if t["kind"] == "item":
                        d.update({k: t["it"][k] for k in ("char", "name", "slot", "looks", "shots", "slug")})
                    if t["kind"] == "sheet":
                        d.update(char=t["char"], items=t["items"])
                    d.setdefault("cands", {})[t["dest"].stem] = rec
                    save()
                print(time.strftime("%H:%M:%S"), lane, t["kind"], t["key"], t["dest"].stem, r, rec["secs"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, t["kind"], t["key"], repr(e)[:300], flush=True)

    th = [threading.Thread(target=worker, args=(n, IG.LANES[n])) for n in lanes]
    [x.start() for x in th]
    [x.join() for x in th]
    postflight(res)
    save()


def postflight(res):
    import gen_items as GI
    import imggen as IG
    # 单品：与 Qwen 版同一套质检
    GI.pick(res["item"])
    # 场景：0 脸 0 字 + 清晰度
    import cv2
    files = {f"frame:{k}/{s}": (None, v["lane"].split(":")[0], v["host_path"]) for k, d in res["scene"].items()
             for s, v in d.get("cands", {}).items() if v.get("host_path")}
    try:
        out = IG.qc_batch(files) if files else {"items": {}}
    except Exception as e:  # noqa: BLE001
        print("qc_err", repr(e)[:200])
        out = {"items": {}}
    for k, d in res["scene"].items():
        best = None
        for s, v in d.get("cands", {}).items():
            if not v.get("file"):
                continue
            q = out["items"].get(f"frame:{k}/{s}") or {}
            v["faces"] = len(q.get("faces", []))
            v["text"] = [t["text"] for t in q.get("text", [])]
            v["lap_var"] = round(float(cv2.Laplacian(cv2.cvtColor(cv2.imread(str(ROOT / v["file"])), cv2.COLOR_BGR2GRAY), cv2.CV_32F).var()), 1)
            v["ok"] = bool(q) and v["faces"] == 0 and not v["text"]
            kk = (v["ok"], v["lap_var"])
            if best is None or kk > best[0]:
                best = (kk, s)
        if best:
            d["chosen"] = {"cand": best[1], "file": d["cands"][best[1]]["file"], "ok": d["cands"][best[1]]["ok"], "tentative": True}
    # 设定图：身份 Q1（gen_look_sheets.pick 的结构：{key: {seed: rec}}）
    import gen_look_sheets as GS
    shaped = {k: {str(v["seed"]): dict(v, char=d["char"]) for v in d.get("cands", {}).values()} for k, d in res["sheet"].items()}
    GS.pick(shaped)
    for k, d in res["sheet"].items():
        for v in d.get("cands", {}).values():
            sv = shaped[k].get(str(v["seed"])) or {}
            v["sim"], v["ok"] = sv.get("sim"), sv.get("ok")
        if shaped[k].get("chosen"):
            d["chosen"] = shaped[k]["chosen"]


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["scene", "item", "sheet", "all", "postflight"])
    ap.add_argument("--lanes", default="gpu33:0,gpu33:1,gpu33:3")
    a = ap.parse_args(argv)
    if a.kind == "postflight":
        res = {k: json.loads((OUT / f"{k}s.json").read_text(encoding="utf-8")) for k in ("scene", "item", "sheet") if (OUT / f"{k}s.json").exists()}
        for k in ("scene", "item", "sheet"):
            res.setdefault(k, {})
        postflight(res)
        for k, v in res.items():
            (OUT / f"{k}s.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    t = []
    if a.kind in ("scene", "all"):
        t += tasks_scene()
    if a.kind in ("sheet", "all"):
        t += tasks_sheet()
    if a.kind in ("item", "all"):
        t += tasks_item()
    run(t, a.lanes.split(","))
    return 0


if __name__ == "__main__":
    sys.exit(main())
