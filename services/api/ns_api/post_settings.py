"""
UX4（2026-10-31）：成片后期设置的只读接口——画布上显示“这一集成片的对白用哪种声音”。

GET /api/post/dialogue-source?ep=N → {source, default, per_episode, label, hint}
数据只读自 config/render_quality.json 的 post.dialogue_source（AUD 引入，项目方 10-31 定默认 h3）。不写任何文件。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["post-settings"])

CFG = Path(__file__).resolve().parents[3] / "config" / "render_quality.json"

LABEL = {
    "h3": ("视频原声", "对白用视频（H3）里的原声，和嘴型同步；原声听不清的句子和独白用配音补"),
    "tts": ("配音", "对白处压低视频原声，改用配音（TTS）"),
}


@router.get("/api/post/dialogue-source")
def dialogue_source(ep: int | None = None) -> dict:
    try:
        d = json.loads(CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    ds = ((d.get("post") or {}).get("dialogue_source") or {}) if isinstance(d, dict) else {}
    default = ds.get("default") or "tts"
    per = ds.get("per_episode") or {}
    src = per.get(str(ep), default) if ep is not None else default
    label, hint = LABEL.get(src, (src, ""))
    return {"source": src, "default": default, "per_episode": per, "label": label, "hint": hint,
            "owner_decision": ds.get("owner_decision")}
