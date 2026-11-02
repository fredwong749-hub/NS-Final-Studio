"""V2 调色预设（STYLE-V2，L-127；项目方 19:1x 主题“上海时尚模特的幻想和现实的挣扎”）。

两套视觉语言，各 3 个候选，候选 = 出图风格后缀（config/render_quality.json image_presets 里 v2_* 预设的 style_suffix）
+ 后期 LUT（config/post/luts/v2_*.cube，本文件生成，自产无第三方许可）。V1 的 S★ / day_v1 / night_v1 不动、不引用。

颜色主要靠 LUT 和具体的光位 / 布景色给，后缀不写“浓郁饱和 / 色彩丰富艳丽 / 柔焦 / 奶油”（config/gen_contract.json
suffix_banned：V1 imgfix 实测这些词带来塑料 / 油光感），也不写 4K / 8K 等锐度助推词（RL01：预设已开 USM）。

  python tools/v2style/looks.py luts          # 生成 6 条 .cube
  python tools/v2style/looks.py apply <in.png> <look_id> <out.png>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LUT_DIR = ROOT / "config" / "post" / "luts"

# s：S 曲线强度；lift：黑位抬升；sat：整体饱和；vib：低饱和区额外加饱和；skin_keep：肤色区饱和增量保留比例（0=不加、1=全加）
# shadow / high：暗部 / 亮部 RGB 偏移；gamma：中间调（<1 提亮）
LOOKS: dict[str, dict] = {
    "fantasy_a": {"lang": "fantasy", "label": "幻想 A · 霓虹宝石", "s": 0.24, "lift": 0.0, "gamma": 1.02, "sat": 1.26, "vib": 0.18,
                  "skin_keep": 0.45, "shadow": (0.006, -0.012, 0.034), "high": (0.020, -0.004, 0.012)},
    "fantasy_b": {"lang": "fantasy", "label": "幻想 B · 胭脂红金", "s": 0.22, "lift": 0.004, "gamma": 1.0, "sat": 1.22, "vib": 0.14,
                  "skin_keep": 0.4, "shadow": (0.022, 0.002, -0.012), "high": (0.030, 0.012, -0.022)},
    "fantasy_c": {"lang": "fantasy", "label": "幻想 C · 黄金时刻", "s": 0.16, "lift": 0.010, "gamma": 0.97, "sat": 1.20, "vib": 0.16,
                  "skin_keep": 0.45, "shadow": (0.010, -0.002, 0.016), "high": (0.026, 0.012, -0.018)},
    # 第 2 轮（总调度 20:4x：幻想 B 偏白天、现实 C 和 A 太像 → 各重出一次）
    "fantasy_b2": {"lang": "fantasy", "label": "幻想 B · 胭脂红金（第 2 版）", "s": 0.26, "lift": 0.0, "gamma": 1.04, "sat": 1.24, "vib": 0.14,
                   "skin_keep": 0.4, "shadow": (0.030, -0.004, -0.004), "high": (0.034, 0.010, -0.026)},
    "reality_a": {"lang": "reality", "label": "现实 A · 阴天冷青", "s": 0.10, "lift": 0.022, "gamma": 1.0, "sat": 0.80, "vib": 0.0,
                  "skin_keep": 1.0, "shadow": (-0.016, 0.006, 0.022), "high": (-0.006, 0.004, 0.010)},
    "reality_b": {"lang": "reality", "label": "现实 B · 夜街混合光", "s": 0.20, "lift": 0.0, "gamma": 1.03, "sat": 0.92, "vib": 0.0,
                  "skin_keep": 1.0, "shadow": (-0.020, 0.016, 0.010), "high": (0.018, 0.010, -0.010)},
    "reality_c": {"lang": "reality", "label": "现实 C · 直闪纪实", "s": 0.15, "lift": 0.008, "gamma": 1.0, "sat": 0.86, "vib": 0.0,
                  "skin_keep": 1.0, "shadow": (0.0, 0.002, 0.014), "high": (-0.002, 0.003, 0.008)},
    "reality_c2": {"lang": "reality", "label": "现实 C · 直闪纪实（第 2 版）", "s": 0.30, "lift": 0.0, "gamma": 1.06, "sat": 0.92, "vib": 0.0,
                   "skin_keep": 1.0, "shadow": (-0.004, -0.002, 0.010), "high": (0.012, 0.010, 0.012)},
}

# 出图风格后缀（接在提示词末尾，同 image_params.append_style_suffix）
SUFFIX: dict[str, str] = {
    "fantasy_a": "时尚杂志大片，品红与电光蓝双色轮廓光，深邃纯净的黑位，漆皮上有锐利的反光，饱满的宝石色调，85mm人像镜头，电影级布光",
    "fantasy_b": "时尚杂志大片，胭脂红与琥珀金为主色，硬朗侧光勾出轮廓，浓重的暖色阴影，肤色红润通透，35mm电影胶片质感，细腻颗粒",
    "fantasy_c": "时尚杂志大片，日落黄金时刻的低角度暖阳，橙粉色天空，逆光勾边与镜头光晕，色彩明艳温暖，肤色金润，70mm电影胶片质感",
    "fantasy_b2": "时尚杂志大片，夜晚室内，胭脂红色调的霓虹灯与琥珀金色暖光交织，背景沉入深红与暗金，硬朗侧光勾出轮廓，浓重的红色阴影，肤色红润通透，35mm电影胶片质感，细腻颗粒",
    "reality_a": "纪实杂志摄影，阴天的柔和自然光，整体偏冷的青灰色调，色彩克制但肤色真实，轻微手持感，35mm胶片质感与细颗粒",
    "reality_b": "纪实杂志摄影，夜晚的混合光源，暖黄钨丝灯与冷白荧光灯交织，高反差，阴影深沉，偏青绿的暗部，35mm胶片质感与细颗粒",
    "reality_c": "纪实杂志摄影，机顶直闪硬光，背景略暗，真实的皮肤质感，冷调白平衡，色彩干净略低饱和，轻微颗粒",
    "reality_c2": "纪实杂志快照，夜里用相机机顶闪光灯正面直闪，人物被闪光打得很亮，身后墙面上有一道清晰锐利的黑色硬阴影，背景迅速坠入黑暗，高反差，白平衡偏冷，真实皮肤质感，轻微颗粒",
}


def lut_path(look: str) -> Path:
    return LUT_DIR / f"v2_{look}.cube"


def _transform(rgb: np.ndarray, lk: dict) -> np.ndarray:
    y = np.clip(rgb, 0, 1)
    if lk.get("gamma", 1.0) != 1.0:
        y = y ** lk["gamma"]
    sm = y * y * (3 - 2 * y)
    y = (1 - lk["s"]) * y + lk["s"] * sm
    y = lk["lift"] + (1 - lk["lift"]) * y
    lum = (0.2126 * y[..., 0] + 0.7152 * y[..., 1] + 0.0722 * y[..., 2])[..., None]
    mx, mn = y.max(-1, keepdims=True), y.min(-1, keepdims=True)
    chroma = mx - mn
    # 肤色区（R > G > B、色度中等）：饱和增量只保留 skin_keep（防止肤色发橙发塑料）
    r, g, b = y[..., 0:1], y[..., 1:2], y[..., 2:3]
    skin = ((r > g) & (g > b) & (chroma > 0.04) & (chroma < 0.45)).astype(np.float32)
    hue_w = np.clip(1 - np.abs((g - b) / np.maximum(r - b, 1e-6) - 0.45) / 0.45, 0, 1)
    skin = skin * hue_w
    sat = lk["sat"] + lk["vib"] * (1 - np.clip(chroma / 0.5, 0, 1))
    delta = sat - 1.0
    delta = np.where(delta > 0, delta * (1 - skin * (1 - lk["skin_keep"])), delta)
    y = lum + (y - lum) * (1 + delta)
    y = y + (1 - lum) ** 2 * np.array(lk["shadow"]) + lum ** 2 * np.array(lk["high"])
    return np.clip(y, 0, 1)


def make_lut(look: str, n: int = 33) -> Path:
    lk = LOOKS[look]
    g = np.linspace(0, 1, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube：R 变化最快
    y = _transform(np.stack([r, gg, b], -1), lk)
    LUT_DIR.mkdir(parents=True, exist_ok=True)
    p = lut_path(look)
    params = {k: v for k, v in lk.items() if k not in ("label",)}
    lines = [f"# NS-Final Studio V2 look '{look}' (STYLE-V2, L-127; generated by tools/v2style/looks.py; self-authored, no third-party license)",
             f"# params {json.dumps(params, ensure_ascii=False)}", f'TITLE "nsfs_v2_{look}"', f"LUT_3D_SIZE {n}",
             "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in y.reshape(-1, 3)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def apply(src: Path, look: str, dst: Path) -> Path:
    """用 ffmpeg lut3d 套 .cube（与视频后期同一条路），输出 PNG"""
    lp = lut_path(look)
    if not lp.exists():
        make_lut(look)
    rel = Path(lp).relative_to(ROOT).as_posix()      # ffmpeg 滤镜参数里避开盘符冒号：在仓库根目录用相对路径
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(Path(src).resolve()), "-vf",
                    f"lut3d=file={rel}:interp=tetrahedral", "-frames:v", "1", str(Path(dst).resolve())],
                   check=True, cwd=ROOT, timeout=300)
    return dst


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "luts":
        for k in LOOKS:
            print(make_lut(k))
    elif a and a[0] == "apply":
        print(apply(Path(a[1]), a[2], Path(a[3])))
    else:
        print(__doc__)
