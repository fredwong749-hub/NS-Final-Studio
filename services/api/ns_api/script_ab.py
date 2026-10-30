"""
剧本 A/B 对比（项目方 2026-10-30：“两个都要，看看那个写出画面更漂亮，更有短剧感觉”）。

同一集同一镜并排：A、B 两份剧本稿（例如 Qwen 逐镜返修版 vs 剧本创作对话全本）的剧本原文、H3 提示词、
首尾帧提示词，以及两版各自的首帧 / 尾帧 / 视频（gpu3 按版本出图后放到 data/ab_renders/<版本>/epXX/SN/）。
系统只原样展示、只记录项目方的选择，不打分、不评价内容。

接口（前缀 /api/script-ab）：
  GET  /sources                         可对比的剧本稿（= 剧本导入候选）
  GET  /episode?a=&b=&ep=               两版本集逐镜字段 + 渲染文件（有则给 URL）
  POST /choice {ep, shot?, pick:A|B, a, b, by:"owner", note?}   记录项目方选择（只追加）
  GET  /choices?ep=                     选择记录
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_api import script_inbox as SI

router = APIRouter(prefix="/api/script-ab", tags=["script-ab"])
CHOICES = SI.DATA / "import" / "ab_choices.jsonl"
RENDERS = "ab_renders"
_cache: dict[str, object] = {}
_lock = threading.Lock()


def _parse(p: Path):
    """整份剧本用正式导入器解析（按 sha256 缓存在内存）"""
    sha = SI._sha(p)
    with _lock:
        if sha in _cache:
            return sha, _cache[sha]
    from ns_agent.importer.script_md import import_script
    result = import_script(p, None)
    with _lock:
        _cache[sha] = result
        while len(_cache) > 6:
            _cache.pop(next(iter(_cache)))
    return sha, result


def _version_key(p: Path, sha: str) -> str:
    return f"{p.stem[:40]}_{sha[:10]}"


def _render_urls(key: str, ep: int, idx: int) -> dict:
    d = SI.DATA / RENDERS / key / f"ep{ep:02d}" / f"S{idx}"
    out = {}
    for name, files in (("first", ("first.png", "frame.png")), ("last", ("last.png",)), ("video", ("video.mp4",))):
        f = next((d / x for x in files if (d / x).is_file()), None)
        out[name] = f"/files/{f.relative_to(SI.DATA).as_posix()}?v={int(f.stat().st_mtime)}" if f else None
    return out


def h3_timing(seconds: int | float, source: str = "script") -> dict:
    """时长 → H3 帧数档位（17k+5，124–362 帧，24 fps；SOP §6 表）；不在 5–15 秒给出提示"""
    from ns_schema.h3_lint import MAX_FRAMES, MIN_FRAMES, frames_for_seconds
    f = frames_for_seconds(seconds)
    ok = 5 <= seconds <= 15
    return {"seconds": seconds, "source": source, "frames": f, "h3_seconds": round(f / 24, 2),
            "ok": ok and MIN_FRAMES <= f <= MAX_FRAMES,
            "hint": "" if ok else f"{seconds} 秒不在 H3 支持的 5–15 秒（会按 {f} 帧≈{f / 24:.2f} 秒出）"}


def _shot_view(s, key: str) -> dict:
    motion = s.motion_prompt or ""
    return {
        "id": f"ep{s.episode:02d}-S{s.index}", "index": s.index, "duration": s.duration,
        "timing": h3_timing(s.duration, s.duration_source),
        "img": s.img_prompt, "motion": motion,
        "last_state": motion.rsplit("——", 1)[1].strip() if "——" in motion else "",
        "sound": s.sound, "sound_h3": s.sound_h3, "music_cue": s.music_cue, "intimate": s.sound_intimate,
        "dialogue": [{"speaker": d.speaker_note, "text": d.text, "stage": d.stage} for d in s.dialogue],
        "voiceover": s.voiceover.text if s.voiceover else None,
        "h3_prompt": getattr(s, "h3_prompt", "") or "",
        "renders": _render_urls(key, s.episode, s.index),
    }


def _side(path: str, ep: int) -> dict:
    p = SI._allowed(path)
    sha, result = _parse(p)
    key = _version_key(p, sha)
    e = next((x for x in result.episodes if x.number == ep), None)
    return {"path": SI._rel(p), "name": p.name, "sha256": sha, "version": key,
            "episodes": [x.number for x in result.episodes],
            "episode": None if e is None else {
                "number": e.number, "title": e.title, "synopsis": getattr(e, "synopsis", ""),
                "music": getattr(e, "music", ""), "music_bgm": getattr(e, "music_bgm", ""),
                "shots": [_shot_view(s, key) for s in e.shots]}}


@router.get("/sources")
def sources():
    return [{"path": SI._rel(p), "name": p.name} for p in SI.candidates()]


@router.get("/episode")
def episode(a: str, b: str, ep: int = 1):
    return {"ep": ep, "a": _side(a, ep), "b": _side(b, ep)}


class Choice(BaseModel):
    ep: int
    shot: str | None = None
    pick: str
    a: str
    b: str
    by: str
    note: str | None = None


@router.post("/choice")
def choice(body: Choice):
    if body.by != "owner":
        raise HTTPException(403, "选择只由项目方在画布上点")
    if body.pick not in ("A", "B"):
        raise HTTPException(422, "pick 只能是 A 或 B")
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **body.model_dump(),
           "a_sha256": SI._sha(SI._allowed(body.a)), "b_sha256": SI._sha(SI._allowed(body.b))}
    CHOICES.parent.mkdir(parents=True, exist_ok=True)
    with CHOICES.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


@router.get("/choices")
def choices(ep: int | None = None):
    if not CHOICES.exists():
        return []
    rows = []
    for x in CHOICES.read_text(encoding="utf-8").splitlines():
        try:                                   # 封板修复：坏行（写到一半）跳过，不让整个列表 500
            r = json.loads(x)
        except ValueError:
            continue
        if isinstance(r, dict):
            rows.append(r)
    return [r for r in rows if ep is None or r.get("ep") == ep]
