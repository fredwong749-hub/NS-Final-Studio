"""IMGFIX r5（总调度 fredw-2b 派，11-02）：林晚造型 A 设定图 v2_s202 正面栏缺一只外套袖子（画面右侧 = 她的左臂是米白衬衫袖）。
修源头：只局部重绘这只袖子——正面栏裁出来（原尺寸放大 1.5 倍）→ Qwen-Image 2.1 编辑（init = 正面栏，turbo 截断 sigma）→
只把袖子框（羽化）贴回原图，框外像素 = 原图（脸、发、身材、裙、鞋、构图、调色一律不动）→ 整张设定图写进 candidates/。
adopted 与 refcrops 原文件不动（项目方点选后再按 REFLOCK 流程替换）。scope=ab：不进生产、不写 takes。

    .venv/Scripts/python.exe tools/imgfix/sleeve_fix.py run [--url http://127.0.0.1:18188]
    .venv/Scripts/python.exe tools/imgfix/sleeve_fix.py page
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "services/agent", "packages/schema", "packages/qc", "tools/localgpu"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

SHEET = ROOT / "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png"
OUT = ROOT / "data/assetmaster/sheets_v2/candidates/lookA_sleeve_fix"
PAGE = ROOT / "data/review_pages/lookA_sleeve_fix"
# 正面栏（asset_refs sheet_layout front = [0.335, 0.556]）内的袖子框，按正面栏像素（439×1120）：肩头到袖口
ARM_BOX = (250, 182, 350, 548)
FEATHER = 9
SCALE = 1.5
SEEDS = (20261102, 20261202, 20261302)
DENOISES = (0.85, 0.92)     # 0.7 不加遮罩时模型照抄原袖（r5 第 1 次 s20261102：袖子没变）→ 改用潜空间遮罩 + 高 denoise
PROMPT = ("图1是同一个人的全身正面设定图。只修改画面右侧那只手臂（人物的左臂）的袖子：把现在的米白衬衫袖子改成深灰西装外套的袖子，"
          "和画面左侧那只手臂的外套袖子完全对称、同色同面料（深灰细格羊毛西装面料），袖口处露出一截米白衬衫袖口，长度到手腕；"
          "手、指甲、手臂姿势不变。其余全部与图1完全一致：脸、头发、身材、外套前片与翻领、米白衬衫前襟、项链、深灰铅笔裙、透明高跟鞋、"
          "纯白背景、光线和调色都不改。真实摄影质感，无文字。")


def prefill(panel):
    """袖子框里的米白像素 → 左臂外套袖（关于人物中线镜像）的同位置像素；镜像源不是深灰时用外套主色。袖口（框下端 cuff_y 以下）保持米白"""
    import numpy as np
    from PIL import Image
    a = np.asarray(panel).astype(np.float32)
    H, W, _ = a.shape
    cx = (BODY_X[0] + BODY_X[1]) / 2
    x0, yt, x1, yb = ARM_BOX
    jacket = np.median(a[300:420, 60:100].reshape(-1, 3), axis=0)      # 左臂外套袖中段主色
    out, m = a.copy(), np.zeros((H, W), np.uint8)
    for y in range(yt, CUFF_Y):
        for x in range(x0, x1):
            r, g, b = a[y, x]
            # 米白衬衫袖（含与外套交界处偏亮的过渡像素）；r5 第 2 次：镜像像素把左袖的缝线 / 翻领轮廓也搬了过来、交界留米白细条
            # → 改为外套主色平铺（加轻微亮度起伏），质感交给模型
            if r > 125 and g > 110 and b > 80 and (r - b) > 6 and not (r > 235 and g > 235 and b > 230):   # v4：交界细条一并铺（不碰白背景）
                shade = 1.0 + 0.06 * np.sin(y / 23.0) - 0.05 * ((x - x0) / max(1, x1 - x0))
                out[y, x], m[y, x] = np.clip(jacket * shade, 0, 255), 255
    return Image.fromarray(out.astype(np.uint8)), Image.fromarray(m)


BODY_X = (40, 335)      # 正面栏人物外框（asset_refs._person_box，正面栏像素）
CUFF_Y = 478            # 米白袖口上沿（与另一只手臂对称）


def panel_box(im):
    from ns_agent import asset_refs as AR
    a, b = AR._cfg()["sheet_layout"]["front"]
    W, H = im.size
    return int(a * W), 0, int(b * W), H


def run(url: str):
    from PIL import Image, ImageDraw, ImageFilter
    from ns_render import workflows as W
    from ns_render.comfy_client import ComfyClient
    OUT.mkdir(parents=True, exist_ok=True)
    full = Image.open(SHEET).convert("RGB")
    x0, y0, x1, y1 = panel_box(full)
    panel = full.crop((x0, y0, x1, y1))
    pw, ph = panel.size
    filled, fmask = prefill(panel)            # 先按左臂外套袖镜像 / 外套主色把米白袖子铺成深灰，再让模型低 denoise 融合质感
    gw, gh = (int(pw * SCALE) // 16) * 16, (int(ph * SCALE) // 16) * 16
    big = filled.resize((gw, gh), Image.LANCZOS)
    src = OUT / "front_panel_x15.png"
    big.save(src)
    client = ComfyClient(url)
    name = client.upload_image(src, subfolder="ns_ab/sleeve_fix")
    log = OUT / "candidates.jsonl"
    sx, sy = gw / pw, gh / ph
    mk = fmask.filter(ImageFilter.MaxFilter(13)).resize((gw, gh), Image.NEAREST)
    mpath = OUT / "arm_mask_x15.png"
    Image.merge("RGB", (mk, mk, mk)).save(mpath)
    mname = client.upload_image(mpath, subfolder="ns_ab/sleeve_fix")
    for DENOISE in DENOISES:
      for seed in SEEDS:
        wf = W.qwen_edit(PROMPT, "", [name], gw, gh, seed, f"ns_ab/sleeve_fix/d{int(DENOISE*100)}_s{seed}", m=W.QwenModel(),
                         ref_resolution=0, crop=False, init_image=name, denoise=DENOISE)
        # 潜空间遮罩：只在袖子框里加噪重画（ComfyUI 核心 SetLatentNoiseMask），框外潜变量保持原图
        wf["113"] = {"class_type": "LoadImageMask", "inputs": {"image": mname, "channel": "red"}}
        wf["114"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["112", 0], "mask": ["113", 0]}}
        wf["40"]["inputs"]["latent_image"] = ["114", 0]
        t0 = time.time()
        entry, secs = client.run(wf, timeout_s=1200)
        item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
        raw = OUT / f"edit_raw_v4_d{int(DENOISE*100)}_s{seed}.png"
        client.download(item, raw)
        ed = Image.open(raw).convert("RGB").resize((pw, ph), Image.LANCZOS)
        mask = fmask.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.GaussianBlur(FEATHER))
        fixed_panel = Image.composite(ed, panel, mask)
        sheet = full.copy()
        sheet.paste(fixed_panel, (x0, y0))
        out = OUT / f"lin_wan_lookA_v2_s202_sleevefix_v4_d{int(DENOISE*100)}_s{seed}.png"
        sheet.save(out)
        rec = {"scope": "ab", "seed": seed, "denoise": DENOISE, "method": "prefill_solid_v4+latent_mask", "file": str(out.relative_to(ROOT)).replace("\\", "/"),
               "raw": str(raw.relative_to(ROOT)).replace("\\", "/"), "comfy_s": round(secs, 1), "wall_s": round(time.time() - t0, 1),
               "arm_box_panel_px": ARM_BOX, "feather": FEATHER, "url": url, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps(rec, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv
    if a[1] == "run":
        run(a[a.index("--url") + 1] if "--url" in a else "http://127.0.0.1:18188")
