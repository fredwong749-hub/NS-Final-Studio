"""I7：系统后缀 = 当前默认出图预设（config/render_quality.json default_preset，项目方 2026-10-31 定“徕卡 S★”）。"""
from __future__ import annotations

import json
import re

from . import ROOT, cfg

NO_TEXT = "无字幕、无文字、无水印"
SKIN = ("皮肤", "肌肤", "脸", "面部", "skin", "face")


def preset() -> dict:
    try:
        rq = json.loads((ROOT / "config" / "render_quality.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pid = cfg().get("suffix_preset") or rq.get("default_preset")
    return next((p for p in rq.get("image_presets") or [] if p.get("id") == pid), {})


def preset_suffix() -> str:
    return ((preset().get("params") or {}).get("style_suffix") or "").strip()


def image_suffix() -> str:
    """编译器 image_style 参数用：预设后缀 + 无字幕句（Q6）"""
    s = preset_suffix()
    return f"{s}，{NO_TEXT}" if s else NO_TEXT


def banned_hits(prompt: str) -> list[str]:
    """提示词里的禁用后缀词。“油光 / 油亮 / oily / glossy skin”只在落到皮肤上时算（漆皮的光泽不算）"""
    hits = []
    low = (prompt or "").lower()
    for w in cfg().get("suffix_banned") or []:
        wl = w.lower()
        if wl not in low:
            continue
        if w in ("油光", "油亮", "oily"):
            ok = False
            for m in re.finditer(re.escape(wl), low):
                win = low[max(0, m.start() - 8): m.end() + 8]
                ok = ok or any(s in win for s in SKIN)
            if not ok:
                continue
        hits.append(w)
    return hits
