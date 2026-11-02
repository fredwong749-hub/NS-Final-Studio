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


class StyleMissing(RuntimeError):
    """资产包模式（V2）的剧没有登记自己的风格后缀——不退回 V1 的 S★（L-126）"""


def run_style_cfg() -> dict:
    p = ROOT / "config" / "compile" / "run_style.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _run() -> str | None:
    from ns_agent import run_paths as RP
    return RP.current_run(ROOT)


def _manifest_mode(run: str | None) -> bool:
    from ns_agent import asset_refs as AR
    return bool(run and AR.project_cfg(run) and AR.manifest_rel(run))


def preset_suffix(run: str | None = None) -> str:
    """按剧取风格后缀（config/compile/run_style.json）；资产包模式的剧没登记 → StyleMissing；旧剧 → render_quality 默认预设"""
    r = run or _run()
    ent = ((run_style_cfg().get("runs") or {}).get(r or "") or {})
    if ent.get("suffix"):
        return ent["suffix"].strip()
    if _manifest_mode(r):
        raise StyleMissing(f"{r} 是资产包模式（V2），config/compile/run_style.json 里没有它的风格后缀；不退回 V1 的 S★（L-126）")
    return ((preset().get("params") or {}).get("style_suffix") or "").strip()


def v1_style_hits(prompt: str, run: str | None = None) -> list[str]:
    """V2（资产包模式）提示词里的 V1 风格短语（run_style.json v1_style_phrases）；旧剧不判"""
    r = run or _run()
    if not _manifest_mode(r):
        return []
    return [w for w in run_style_cfg().get("v1_style_phrases") or [] if w and w in (prompt or "")]


def image_suffix(run: str | None = None) -> str:
    """编译器 image_style 参数用：本剧风格后缀 + 无字幕句（Q6）"""
    s = preset_suffix(run)
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
