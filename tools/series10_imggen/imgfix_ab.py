"""IMGGEN 修配方对照（2026-10-31 夜，总调度：项目方判 80 张首帧“一致性差、塑料、油、糊、场景不合格”）。

4 镜 × 多个变体，只在 gpu33 三道出（gpu36 归 BAKEOFF），守 VIDEO10 的“每道全部任务 < 2”，每道同时最多 1 个本工具任务。
变体（同一 seed，只改一个因素逐级叠加，便于归因）：
  v0 基线        第一轮作业原图（plan_c：Base 25 步 cfg1、lin_wan_qi 0.8 + lnwan_qi 触发词、旧剧本统一后缀）
  v1 去LoRA      生产出图路径 W.qwen_edit（脸参考 ref_resolution 0 / 不裁）；去掉 lin_wan_qi 与 lnwan_qi
  v2 新后缀      v1 + 去掉旧统一后缀（f/1.2 奶油柔焦、浓郁饱和、艳丽）与镜头句，漆皮“油光”只落在衣物 + 徕卡 S★ 后缀
  v3 S★全套      v2 提示词走 image_params 预设 leica_sstar（Turbo 8 步 + krea2_film_texture 0.5 + 1.5× 出图 + lanczos 缩回 + USM）
  v4 cfg2.5      v2 走 Base 25 步 cfg 2.5（负面词生效）
  v5 cfg4        同上 cfg 4
  v6 写实LoRA    v3 + glamour_realism_qwen21 0.4（gpu33 只有这个 / canon；civitai raw_photo 只在 gpu36）
  v7 单脸参考    双人镜：只挂主角脸参考，另一人只用文字；单人林晚镜：v3 + @identity lin_wan_qi 0.6（量 LoRA 在 S★ 里的作用）
打分：身份（gpu33 原地 ArcFace，tools/series10_imggen/score_remote.py）+ “塑料感”代理指标（本机 cv2）：
  脸部高频能量（脸框内 灰度 − 高斯模糊σ2 的绝对值均值，越低越“磨皮 / 塑料”）、全图 Laplacian 方差（清晰度）、平均饱和度。
输出：data/pipeline/runs/<legacy run>/images/imgfix/<镜>/<变体>.png，对照页 data/review_pages/series10_imgfix/index.html
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen"):
    sys.path.insert(0, str(ROOT / p))
from ns_render import image_params as IP  # noqa: E402
from ns_render import workflows as W  # noqa: E402
import imggen as IG  # noqa: E402
import refkit as RK  # noqa: E402

RUN = ROOT / ("data/pipeline/runs/" + _LEGACY)
OUT = RUN / "images/imgfix"
PAGE = ROOT / "data/review_pages/series10_imgfix/index.html"
LANES = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191"}
OLD_SUFFIX = ("专业电影镜头画面感，画面干净，徕卡镜头级锐利度与通透质感，85mm人像镜头f/1.2大光圈，主体锐利对焦，前景与背景奶油般柔焦虚化、"
              "柔和圆形光斑，浓郁饱和的暖色调电影调色，色彩丰富艳丽、通透明亮，柔和的大面积光源与暖调轮廓光、高光柔和不过曝，"
              "皮肤通透有真实质感，无字幕、无文字、无水印")
LENS_SENT = re.compile(r"Leica Summilux[^，]*，焦平面上眼睛与睫毛清晰锐利，皮肤毛孔与发丝细节真实，?")
OIL = ("漆皮为像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利", "像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利")
OIL_FIX = "漆皮衣物为高亮镜面漆皮，镜面反光只在衣物表面，皮肤保持自然哑光、不反光"
NEG = ("anime, cartoon, illustration, CGI, 3d render, doll face, plastic skin, waxy skin, oily skin, airbrushed, "
       "beauty filter, blurry, soft focus, over-saturated, deformed hands, extra fingers, text, watermark")
LEICA = IP.find_preset("leica_sstar")["params"]["style_suffix"]


def clean_prompt(p: str) -> str:
    p = p.replace("lnwan_qi，", "").replace("，lnwan_qi", "")
    p = p.replace("，" + OLD_SUFFIX, "").replace(OLD_SUFFIX, "")
    p = LENS_SENT.sub("", p)
    for o in OIL:
        p = p.replace(o, OIL_FIX)
    return re.sub("，{2,}", "，", p).strip("，")


def pick_shots(jobs):
    by = {j["shot"]: j for j in jobs}
    lin_near = next(j for j in jobs if j["on_screen"] == ["林晚"] and j["size"] in ("近景", "中近景"))
    male = next(j for j in jobs if j["on_screen"] in (["顾沉"], ["陈宇"]) and j["size"] in ("近景", "中近景", "中景", "特写"))
    wide = by.get("ep05-S7") or next(j for j in jobs if j["size"] == "全景")
    return [by["ep05-S5"], lin_near, male, wide]


def variants(job, old_job):
    two = len(job["on_screen"]) > 1
    refs = list(job["refs"])
    base_prompt = job["prompt"]
    v2p = clean_prompt(base_prompt) + "，" + LEICA
    v3p = clean_prompt(base_prompt)                     # S★ 预设自己接后缀
    V = [("v0", "基线（第一轮原图）", {"old": True}),
         ("v1", "去 LoRA/触发词", {"prompt": base_prompt.replace("lnwan_qi，", ""), "base_cfg": 1.0}),
         ("v2", "新后缀+去油光", {"prompt": v2p, "base_cfg": 1.0}),
         ("v3", "S★全套", {"prompt": v3p, "sstar": []}),
         ("v4", "cfg2.5", {"prompt": v2p, "base_cfg": 2.5}),
         ]
    # v8 / v9（GEN_CONTRACT I3 / I5 / I9）：脸参考 > 造型图（景别决定半身 / 全身）> 场景底图；双人镜第二人只给造型图、不给脸
    on = job["on_screen"]
    lead = on[0] if "林晚" not in on else "林晚"
    face = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}
    fr = next((r for r in refs if f"/{face[lead]}" in r or f"{face[lead]}_face" in r), refs[0] if refs else None)
    r8, lines = [], []
    if fr:
        r8.append(fr)
        lines.append(f"图{len(r8)}是{lead}的脸部参考（只取脸和发型，必须一致）。")
    for n in on:
        cid = face.get(n)
        lk = RK.look_for_shot(cid, job["prompt"], int(job["ep"])) if cid else None
        lr = RK.look_ref(cid, lk, job["size"]) if cid else None
        if lr:
            r8.append(str(lr.relative_to(ROOT)).replace("\\", "/"))
            lines.append(f"图{len(r8)}是{n}本镜造型{lk}的服装参考（只取服装、鞋与饰品的款式和颜色，必须一致；不取脸）。")
    body = re.sub(r"图\d是[^。]*?（[^）]*）。", "", v3p)
    r10, l10 = r8[:1], lines[:1]
    for n in on:
        cid = face.get(n)
        lk = RK.look_for_shot(cid, job["prompt"], int(job["ep"])) if cid else None
        lr = RK.look_ref_nohead(cid, lk, job["size"]) if cid else None
        if lr:
            r10.append(str(lr.relative_to(ROOT)).replace(chr(92), "/"))
            l10.append(f"图{len(r10)}是{n}本镜造型{lk}的服装参考（只有服装、鞋与饰品，必须一致）。")
    # 项目方：脸只由身份参考给，写实只加在质感上 → 三档写实强度（krea2 胶片质感 + glamour_realism 低权重）
    V.append(("v10", "S★+脸+去头造型图（写实·中）", {"prompt": "".join(l10) + body, "sstar": [], "refs": r10}))
    V.append(("v10L", "同上（写实·轻）", {"prompt": "".join(l10) + body, "sstar": [], "krea": 0.3, "refs": r10}))
    V.append(("v10H", "同上（写实·重）", {"prompt": "".join(l10) + body, "sstar": [], "krea": 0.8, "refs": r10}))   # glamour_realism 已禁用
    # REFLOCK 接口（GEN_CONTRACT）：vR = 资产槽位规划（脸 > 造型设定图 > 单品 > 场景，超槽拼板）；vN = 只挂脸（assets=False）
    for vid, label, assets in (("vR", "REFLOCK 资产槽位（S★）", True), ("vN", "REFLOCK 只挂脸（S★）", False)):
        try:
            pr, rf = reflock(job, assets)
            V.append((vid, label, {"prompt": pr, "sstar": [], "refs": rf, "no_suffix": True}))
        except Exception as e:  # noqa: BLE001
            print("reflock variant skipped", job["shot"], vid, repr(e)[:160], flush=True)
    sc = scene_of(job)
    if sc:
        r9 = r10 + [sc]
        V.append(("v9", "v10+场景底图", {"prompt": "".join(l10) + f"图{len(r9)}是本镜场景参考（只取场景空间、陈设与光线，不取人物）。" + body,
                                        "sstar": [], "refs": r9}))
    if two:
        main = refs[[i for i, r in enumerate(refs) if "lin_wan" in r][0]] if any("lin_wan" in r for r in refs) else refs[0]
        p = re.sub(r"图\d是[^。]*?（[^）]*）。", "", v3p)
        V.append(("v7", "单脸参考（另一人只用文字）", {"prompt": "图1是林晚的脸部参考（只取脸和发型）。" + p, "sstar": [],
                                               "refs": [main]}))
    elif job["on_screen"] == ["林晚"]:
        V.append(("v7", "S★+林晚LoRA0.6", {"prompt": "lnwan_qi，" + v3p, "sstar": [("lin_wan_qi_v1.safetensors", 0.6)]}))
    out = []
    for vid, label, o in V:
        o = dict(o)
        o.setdefault("refs", refs)
        out.append((vid, label, o))
    return out


def reflock(job, assets):
    import image_jobs as IJ
    n = int(job["ep"])
    __import__("os").environ.setdefault("NS_ALLOW_P4_SOURCE", "1")   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：标定 / 对照实验复现当时 P4 稿出的图，属调研用途
    si, ep = IJ.load_episode(RUN / f"ep{n:02d}" / f"P4_ep{n:02d}.md")
    shot = next(x for x in ep.shots if f"ep{n:02d}-S{x.index}" == job["shot"])
    g = IJ.merged_globals(si.globals, IJ.production_globals())
    faces = [r for r in job["refs"] if "face_ref" in r]
    p, c, sr, plan = IJ.frame_prompt_full(ep, shot, g, faces, _LEGACY, assets=assets)
    return p, (list(plan.files) if plan else faces)


def scene_of(job):
    m = re.search(r"sk_[a-z_]+", job["prompt"])
    if not m:
        return None
    p = RUN / "images/scenes/scenes.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8")).get(m.group(0)) or {}
    c = d.get("chosen")
    return c["file"] if c else None


def build(job, old_job, o, seed, lane_url, prefix):
    ln = IG.Lane("x", lane_url)
    if o.get("old"):
        g = copy.deepcopy(old_job["graph"])
        IG.set_seed(g, seed)
        IG.set_prefix(g, prefix)
        return g, None, old_job["prompt"]
    names = [ln.upload(r) for r in o["refs"]]
    if "sstar" in o:
        ov = {"loras": [{"name": "krea2_film_texture_qwen21.safetensors", "strength": o.get("krea", 0.5)}] +
              [{"name": f, "strength": s} for f, s in o["sstar"]]}
        if o.get("no_suffix"):
            ov["style_suffix"] = ""                      # 提示词已含编译器给的 S★ 后缀（REFLOCK），不再重复接
        eff = IP.resolve("leica_sstar", ov)
        wf = W.qwen_edit(o["prompt"], "", names, 768, 1344, seed, prefix, m=W.QwenModel(), loras=[],
                         ref_resolution=0, crop=False)
        wf = IP.apply(wf, eff, set())
        return wf, eff, wf["20"]["inputs"]["prompt"]
    m = W.QwenModel(unet="qwen_image_2.1_int8_convrot.safetensors", turbo=False, steps=25, cfg=o["base_cfg"],
                    vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors")
    wf = W.qwen_edit(o["prompt"], NEG, names, 768, 1344, seed, prefix, m=m, loras=[], ref_resolution=0, crop=False)
    return wf, None, o["prompt"]


def queue_total(url):
    d = json.loads(IG.api(url, "/queue", timeout=20))
    return len(d["queue_running"]) + len(d["queue_pending"])


def metrics(path: Path, faces, raw_size=None):
    im = cv2.imread(str(path))
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lap = float(cv2.Laplacian(g, cv2.CV_32F).var())
    sat = float(cv2.cvtColor(im, cv2.COLOR_BGR2HSV)[..., 1].mean() / 255)
    hf = oil = None
    if faces:
        sc = im.shape[1] / raw_size[0] if raw_size else 1.0          # 1.5× 出图：脸框按缩回比例换算
        x1, y1, x2, y2 = [int(v * sc) for v in faces[0]["bbox"]]
        w, h = x2 - x1, y2 - y1
        crop = g[max(0, y1 + h // 5): y2 - h // 5, max(0, x1 + w // 5): x2 - w // 5]
        if crop.size > 400:
            hf = float(np.abs(crop - cv2.GaussianBlur(crop, (0, 0), 2)).mean())
            hsv = cv2.cvtColor(im[max(0, y1 + h // 5): y2 - h // 5, max(0, x1 + w // 5): x2 - w // 5], cv2.COLOR_BGR2HSV)
            oil = float(((hsv[..., 2] > 235) & (hsv[..., 1] < 60)).mean())     # Q4 油光代理：脸部近白低饱和镜面高光占比
    return {"lap_var": round(lap, 1), "sat": round(sat, 3), "face_hf": round(hf, 2) if hf is not None else None,
            "oil": round(oil, 4) if hf is not None else None}


def main():
    jobs = json.loads((RUN / "assets/first_frame_jobs.json").read_text(encoding="utf-8"))["jobs"]
    old = {j["shot"]: j for j in json.loads((RUN / "assets/first_frame_jobs.before_round2.json").read_text(encoding="utf-8"))["jobs"]}
    shots = pick_shots(jobs)
    tasks = []
    for j in shots:
        for vid, label, o in variants(j, old[j["shot"]]):
            tasks.append({"shot": j["shot"], "vid": vid, "label": label, "o": o, "job": j, "seed": int(j["seed"])})
    order = {"v10": 0, "v3": 1, "v2": 2, "v10L": 3, "v10H": 4, "vR": 5, "vN": 6, "v9": 7, "v1": 8, "v0": 9, "v7": 10, "v4": 11}
    tasks.sort(key=lambda t: order.get(t["vid"], 9))        # 最能回答问题的变体先出（gpu33 和视频共用，很慢）
    res_path = OUT / "results.json"
    res = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    tasks = [t for t in tasks if f"{t['shot']}/{t['vid']}" not in res or not res[f"{t['shot']}/{t['vid']}"].get("file")]
    print("shots", [j["shot"] for j in shots], "tasks", len(tasks), flush=True)
    lk = threading.Lock()

    def worker(lane, url):
        while True:
            with lk:
                if not tasks:
                    return
                t = tasks.pop(0)
            # VIDEO10 按“每道总负载 ≤2（含别人的）”自己让位；本工具每道同时只 1 个、front 插队
            key = f"{t['shot']}/{t['vid']}"
            try:
                g, eff, prompt = build(t["job"], old[t["shot"]], t["o"], t["seed"], url, f"imgfix/{t['shot']}_{t['vid']}")
                c = IG.Lane(lane, url)
                pid = c.submit(g, front=True)          # 短图任务插到视频任务前（每道仍只 1 个本工具任务、总负载 ≤2）
                t0 = time.time()
                dest = OUT / t["shot"] / f"{t['vid']}.png"
                while True:
                    time.sleep(5)
                    r = c.fetch(pid, dest)
                    if r:
                        break
                rec = {"shot": t["shot"], "vid": t["vid"], "label": t["label"], "lane": lane, "seed": t["seed"],
                       "prompt": prompt, "refs": t["o"]["refs"], "secs": round(time.time() - t0, 1), "status": r,
                       "host_path": getattr(c, "last_host_path", None)}
                if r == "ok":
                    rec["raw"] = str(dest.relative_to(ROOT)).replace("\\", "/")
                    final = dest
                    if eff:
                        post = IP.post_file(dest, eff)
                        if post:
                            final = Path(post["path"])
                            rec["post"] = post["steps"]
                    rec["file"] = str(final.relative_to(ROOT)).replace("\\", "/")
                with lk:
                    res[key] = rec
                    res_path.parent.mkdir(parents=True, exist_ok=True)
                    res_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                print(time.strftime("%H:%M:%S"), lane, key, r, rec["secs"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, key, repr(e)[:200], flush=True)
                with lk:
                    res[key] = {"shot": t["shot"], "vid": t["vid"], "label": t["label"], "err": repr(e)[:300]}

    th = [threading.Thread(target=worker, args=(n, u)) for n, u in LANES.items()]
    for x in th:
        x.start()
    for x in th:
        x.join()
    score(res)
    res_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    page(res)


def score(res):
    out = IG.qc_batch({"frame:" + k: (None, "gpu33", v["host_path"]) for k, v in res.items() if v.get("host_path")})
    out["items"] = {k[len("frame:"):]: v for k, v in out["items"].items()}
    refs = out.get("ref_emb", {})
    alan = (IG.jload(IG.IMG / "state.json", {}) or {}).get("alan_emb")
    if alan:
        refs["ch_a_lan"] = alan
    for k, v in res.items():
        q = out["items"].get(k) or {}
        fs = q.get("faces", [])
        v["faces"] = len(fs)
        v["ids"] = {}
        for f in fs[:3]:
            sims = {n: round(IG.cos(f["emb"], e), 3) for n, e in refs.items()}
            best = max(sims, key=sims.get)
            v["ids"].setdefault(best, sims[best])
        v["face_h"] = fs[0]["h_ratio"] if fs else None
        if v.get("file"):
            v["metrics"] = metrics(ROOT / v["file"], fs, q.get("size"))
        v["text"] = [t["text"] for t in q.get("text", [])]
        v["hands"] = (q.get("hand_check") or {}).get("flags")


SIZE_OF = {}


def contract(v: dict) -> dict:
    """GEN_CONTRACT 逐项自检（✓ 通过 / ✗ 不通过 / – 不适用 / ? 未测）。阈值：Q1 林晚 ≥0.70、他人主角 ≥0.60；
    Q4 脸部高频 ≥ 本镜 v0 基线、油光 ≤0.02；Q3 按 K-REN-122 档位（局部特写不判）。"""
    vid, refs, prompt = v["vid"], v.get("refs") or [], v.get("prompt") or ""
    on = v.get("on_screen") or []
    face_refs = [r for r in refs if "face_ref" in r or ("assets/characters/" in r and "/refs/" in r and "_look" not in r)
                 or "identity_refs" in r]
    out = {}
    out["I2"] = "✓" if face_refs else "✗"
    out["I3"] = "✓" if any("_look" in r for r in refs) else "✗"
    out["I5"] = "✓" if any("/scenes/" in r for r in refs) else "✗"
    from ns_agent.gen_contract import style as GST          # 与 REFLOCK preflight 同一判定（漆皮光泽不算皮肤油光）
    out["I7"] = "✗" if GST.banned_hits(prompt) else "✓"
    out["I8"] = "✗" if ("lnwan_qi" in prompt or vid in ("v0",)) else "✓"
    out["I9"] = ("✗" if len(face_refs) > 1 else "✓") if len(on) > 1 else "–"
    ids = v.get("ids") or {}
    lw = ids.get("lin_wan")
    if "林晚" in on and v.get("subject") not in ("part", "object"):
        out["Q1"] = "?" if lw is None else ("✓" if lw >= 0.70 else "✗")
    else:
        others = [x for n, x in ids.items() if n != "lin_wan"]
        out["Q1"] = "–" if not others else ("✓" if max(others) >= 0.60 else "✗")
    m = v.get("metrics") or {}
    base = v.get("_base_hf")
    if m.get("face_hf") is None:
        out["Q4"] = "?"
    else:
        out["Q4"] = "✓" if (base is None or m["face_hf"] >= base) and (m.get("oil") or 0) <= 0.02 else "✗"
    out["Q5"] = "✗" if v.get("hands") else "✓"
    out["Q6"] = "✗" if v.get("text") else "✓"
    out["Q2"] = "?"      # 服装区域相似度（DINO/CLIP 裁区）尚未实现，人工看
    out["Q7"] = "?" if out["I5"] == "✓" else "–"
    return out


def page(res):
    import html
    E = html.escape
    shots = []
    for v in res.values():
        if v["shot"] not in shots:
            shots.append(v["shot"])
    css = """:root{--bg:#f6f5f2;--fg:#1d1d1b;--mut:#6b6a65;--card:#fff;--line:#e2e0da;--ok:#1f7a3d;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--mut:#a09e97;--card:#21201e;--line:#34332f;--ok:#5fc27e;--bad:#f2867d}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;margin:0;padding:16px}
h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:24px 0 8px;border-bottom:1px solid var(--line)}
.row{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px}.card{background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:6px;min-width:230px;max-width:230px}.card img{width:100%;border-radius:4px}.mut{color:var(--mut)}
.k{font-size:12px}.ok{color:var(--ok)}.bad{color:var(--bad)}table{border-collapse:collapse;font-size:12px}td,th{border:1px solid var(--line);padding:2px 6px}"""
    o = [f"<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>首帧配方对照</title><style>{css}</style></head><body><h1>首帧配方对照（Qwen-Image 2.1，gpu33）</h1>"
         f"<div class=mut>更新 {time.strftime('%F %T')}。同一镜同一 seed，每列只多改一个因素。身份 = ArcFace 余弦（同人 ≥0.50；林晚目标 ≥0.70）。"
         "脸部高频 = 脸框内细节能量（越低越磨皮 / 塑料）；清晰度 = 全图 Laplacian 方差；饱和度 0–1。坏手：mediapipe 只标可疑。</div>"]
    jobs = {j["shot"]: j for j in json.loads((RUN / "assets/first_frame_jobs.json").read_text(encoding="utf-8"))["jobs"]}
    for v in res.values():
        j = jobs.get(v["shot"], {})
        v["on_screen"], v["subject"] = j.get("on_screen"), j.get("framing_subject")
        b = res.get(v["shot"] + "/v0", {}).get("metrics") or {}
        v["_base_hf"] = b.get("face_hf")
        v["contract"] = contract(v)
    keys = ["I2", "I3", "I5", "I7", "I8", "I9", "Q1", "Q2", "Q4", "Q5", "Q6", "Q7"]
    o.append("<h2>契约逐项（GEN_CONTRACT §1/§2；✓ 过 ✗ 不过 – 不适用 ? 未测）</h2><table><tr><th>镜/变体</th>" +
             "".join(f"<th>{k}</th>" for k in keys) + "<th>林晚</th><th>他人主角</th><th>脸部高频</th><th>油光</th></tr>")
    for k in sorted(res):
        v = res[k]
        if not v.get("file"):
            continue
        c, ids, m = v["contract"], v.get("ids") or {}, v.get("metrics") or {}
        oth = max([x for n, x in ids.items() if n != "lin_wan"] or [0])
        o.append(f"<tr><td>{E(k)} {E(v['label'])}</td>" + "".join(f"<td>{c[x]}</td>" for x in keys) +
                 f"<td>{ids.get('lin_wan', '')}</td><td>{oth or ''}</td><td>{m.get('face_hf')}</td><td>{m.get('oil')}</td></tr>")
    o.append("</table>")
    for s in shots:
        o.append(f"<h2>{E(s)}</h2><div class=row>")
        for k in sorted(k for k in res if k.startswith(s + "/")):
            v = res[k]
            if not v.get("file"):
                o.append(f"<div class=card><b>{E(v['vid'])} {E(v['label'])}</b><br><span class=bad>{E(v.get('err') or v.get('status') or '未出')}</span></div>")
                continue
            m = v.get("metrics") or {}
            ids = " ".join(f"<span class={'ok' if x >= 0.5 else 'bad'}>{IG.ID2NAME.get(n, n)} {x:.2f}</span>" for n, x in (v.get("ids") or {}).items())
            rp = Path(v["file"])
            src = Path(__import__("os").path.relpath(ROOT / rp, PAGE.parent)).as_posix()
            o.append(f"<div class=card><a href='{src}'><img loading=lazy src='{src}'></a><div class=k><b>{E(v['vid'])} {E(v['label'])}</b><br>"
                     f"身份：{ids or '无脸'}<br>脸部高频 {m.get('face_hf')}｜油光 {m.get('oil')}｜清晰度 {m.get('lap_var')}｜饱和度 {m.get('sat')}<br>"
                     f"脸高 {v.get('face_h')}｜{v.get('secs')} s｜{E(v['lane'])}"
                     f"{'<br>手：' + E('；'.join(v['hands'])) if v.get('hands') else ''}{'<br>有字' if v.get('text') else ''}</div></div>")
        o.append("</div>")
    o.append("</body></html>")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text("\n".join(o), encoding="utf-8")
    print(PAGE)


if __name__ == "__main__":
    RUNS.gate_legacy_tool(None, __file__)        # I-16：page 和出图两条路都要显式 --run
    if len(sys.argv) > 1 and sys.argv[1] == "page":
        r = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
        score(r)
        (OUT / "results.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        page(r)
    else:
        main()
