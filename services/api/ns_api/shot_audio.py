"""对白 / 旁白逐句试听 + 配乐（UIRSI 2026-11-01，REDESIGN B4，UI_CONTRACT §1.4，BE-3）。

  GET /api/shots/{ep01-S3}/audio          这一镜要说的每一句（对白在前、独白/旁白在后），说话人按成片同一套规则认
                                          （ns_post.speakers.resolve_episode + config/voices.json line_overrides）。
                                          每句给 play 地址；已合成过的标 cached。
  GET /api/shots/{ep01-S3}/audio/{i}.wav  播这一句：本机 Kokoro 音色没合成过就现合成（CPU、不花钱、按内容缓存，
                                          和成片用同一个缓存 data/cache/tts）；旁白是远端复刻音色，本机只放已合成过的。
  GET /api/sound/lines?ep=1                整集每镜的台词（同上，一次给全）
  GET /api/music                          有配乐的集（data/music/epNN.wav + .json）
  GET /api/music/{ep}                     这一集配乐：wav 地址、总长、每镜起点、提示点（cues）
只读剧本、不改剧本；合成试听只写 TTS 缓存。
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["shot-audio"])
_lock = threading.Lock()


def _post():
    p = str(REPO / "services" / "post")
    if p not in sys.path:
        sys.path.insert(0, p)
    from ns_post import speakers, tts  # noqa: PLC0415
    return speakers, tts


def _script() -> dict:
    try:
        return json.loads((REPO / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _parse(shot_id: str) -> tuple[int, int]:
    m = re.fullmatch(r"ep(\d{2,3})-S(\d{1,3})", shot_id)
    if not m:
        raise HTTPException(404, f"镜头号不对：{shot_id}")
    return int(m.group(1)), int(m.group(2))


def _cache_dir() -> Path:
    _, tts = _post()
    return Path(tts.CACHE_DIR)


def _episode(epn: int) -> dict:
    ep = next((e for e in _script().get("episodes", []) if int(e.get("number") or 0) == epn), None)
    if not ep:
        raise HTTPException(404, f"当前剧本里没有第 {epn} 集")
    return ep


def _resolved(ep: dict):
    """{shot index: [(SpokenLine, [Voice...], cfg)]} for the whole episode (speaker rules need the whole episode)."""
    speakers, tts = _post()
    from ns_api import run_paths as RP  # noqa: PLC0415  OVERSIGHT-F P1-13a：音色按剧取（V2 只用 voices_v2.json 启用的音色）
    cfg = tts.load_voice_config(run=RP.current_run())
    out: dict[int, list] = {}
    try:
        resolved = speakers.resolve_episode(ep, cfg.get("line_overrides"), narrator=tts.default_voiceover_speaker(cfg),
                                            cast=speakers.Cast.from_cfg(cfg))
    except speakers.UnresolvedSpeaker as e:
        raise HTTPException(422, str(e)) from e
    for ln in resolved:
        try:
            vs = tts.voice_for(cfg, ln.speaker, voiceover=ln.kind == "voiceover")
        except tts.TtsError:
            vs = []
        out.setdefault(int(ln.shot), []).append((ln, vs, cfg))
    return out


def _lines(shot_id: str):
    """[(SpokenLine, [Voice...], cfg)] for this shot."""
    epn, idx = _parse(shot_id)
    ep = _episode(epn)
    if not any(int(s.get("index") or 0) == idx for s in ep.get("shots") or []):
        raise HTTPException(404, f"当前剧本里没有 {shot_id}")
    return _resolved(ep).get(idx, [])


def _clip(text: str, v, cache: Path) -> Path:
    _, tts = _post()
    return cache / f"{tts.clip_key(text, v, 'kokoro')}.wav"


def _dur(p: Path) -> float | None:
    try:
        _, tts = _post()
        return round(tts.wav_duration(p), 2)
    except Exception:  # noqa: BLE001
        return None


def _rows(shot_id: str, lines: list) -> list[dict]:
    cache = _cache_dir()
    rows = []
    for i, (ln, vs, cfg) in enumerate(lines):
        ch = (cfg.get("characters") or {}).get(ln.speaker) or {}
        name = ch.get("name") or ln.speaker
        local = bool(vs) and all(v.engine == "kokoro" for v in vs)
        clip = _clip(ln.text, vs[0], cache) if len(vs) == 1 else None
        cached = bool(clip and clip.is_file())
        playable = len(vs) == 1 and (local or cached)
        reason = None
        if not vs:
            reason = f"{name} 还没有配音色"
        elif len(vs) > 1:
            reason = "多人齐声，成片里才合成"
        elif not playable:
            reason = "旁白用远端音色，合成成片后才能听"
        rows.append({"i": i, "kind": ln.kind, "speaker": ln.speaker, "speaker_name": name,
                     "label": "旁白" if ln.kind == "voiceover" and ln.speaker == "narrator" else
                              ("独白" if ln.kind == "voiceover" else "对白"),
                     "text": ln.text, "note": ln.note,
                     "play": f"/api/shots/{shot_id}/audio/{i}.wav" if playable else None,
                     "cached": cached, "dur": _dur(clip) if cached else None, "reason": reason})
    return rows


@router.get("/api/shots/{shot_id}/audio")
def shot_audio(shot_id: str):
    return {"shot": shot_id, "lines": _rows(shot_id, _lines(shot_id))}


@router.get("/api/sound/lines")
def episode_lines(ep: int):
    """一集每镜要说的话（声音页「对白」按集看）：一次算完整集，不用每镜各请求一次"""
    e = _episode(ep)
    by = _resolved(e)
    shots = []
    for s in e.get("shots") or []:
        idx = int(s.get("index") or 0)
        sid = f"ep{ep:02d}-S{idx}"
        shots.append({"shot": sid, "index": idx, "lines": _rows(sid, by.get(idx, []))})
    return {"episode": ep, "title": e.get("title"), "shots": shots}


@router.get("/api/shots/{shot_id}/audio/{i}.wav")
def shot_audio_clip(shot_id: str, i: int):
    lines = _lines(shot_id)
    if not 0 <= i < len(lines):
        raise HTTPException(404, "没有这一句")
    ln, vs, cfg = lines[i]          # cfg = _resolved 按剧取的那份音色表（同一个函数里不再混用第二份）
    if len(vs) != 1:
        raise HTTPException(409, "这一句现在不能单独试听")
    cache = _cache_dir()
    clip = _clip(ln.text, vs[0], cache)
    if not clip.is_file():
        if vs[0].engine != "kokoro":
            raise HTTPException(409, "旁白用远端音色，合成成片后才能听")
        _, tts = _post()
        try:
            with _lock:
                backend = tts.KokoroBackend(cfg, num_threads=4)
                [clip] = tts.synthesize_cached(backend, [(ln.text, vs[0])], cache)
        except tts.TtsUnavailable as e:
            raise HTTPException(503, f"这台电脑上的配音模型没装好，暂时不能试听（{e}）")
        except tts.TtsError as e:
            raise HTTPException(502, f"合成试听没成功：{e}")
    return FileResponse(clip, media_type="audio/wav")


# ----------------------------------------------------------------------------- 配乐
def _music_dir() -> Path:
    from ns_api.bgm_api import music_dir  # noqa: PLC0415  BGM10：series10 配乐在 data/music/series10（旧剧目录已隔离）
    return music_dir()


def _music(ep: int) -> dict | None:
    d = _music_dir()
    j, w = d / f"ep{ep:02d}.json", d / f"ep{ep:02d}.wav"
    if not w.is_file():
        return None
    try:
        meta = json.loads(j.read_text(encoding="utf-8")) if j.is_file() else {}
    except (OSError, ValueError):
        meta = {}
    starts = [float(x) for x in meta.get("shot_starts") or []]
    durs = [float(x) for x in meta.get("shot_durations") or []]
    # DATAALIGN（K-UI-D01）：配乐时间轴按剧本镜头顺序排（第 k 段 = 本集第 k 个镜头），镜号取剧本里的真实镜号，
    # 不再按位置现编 S{k+1}（插镜 / 删镜后会错位）；段数和剧本镜数不一致 = 时间轴是按另一版剧本作的，标 stale_timeline
    ep_d = next((e for e in _script().get("episodes", []) if int(e.get("number") or 0) == ep), None) or {}
    real = [int(x.get("index") or 0) for x in ep_d.get("shots") or []]
    idx_of = lambda k: real[k] if k < len(real) and real[k] else k + 1   # noqa: E731
    shots = [{"shot": f"ep{ep:02d}-S{idx_of(k)}", "index": idx_of(k), "start_s": round(s, 2),
              "dur_s": round(durs[k], 2) if k < len(durs) else None} for k, s in enumerate(starts)]
    pos = lambda v: idx_of(int(v) - 1) if isinstance(v, int) and v >= 1 else v   # noqa: E731  提示点 shot = 第几段（从 1 起）
    cues = [{"shot": pos(c.get("shot")), "start_s": c.get("start_s"), "action": c.get("action"),
             "intensity": c.get("intensity"), "text": c.get("text")} for c in meta.get("cues") or []]
    stale_tl = bool(starts) and bool(real) and len(starts) != len(real)
    try:
        from ns_api.cuts import _last_replace_import  # noqa: PLC0415
        smt = _last_replace_import()
    except Exception:  # noqa: BLE001
        smt = None
    from ns_api.bgm_api import file_url  # noqa: PLC0415  BGM10：带目录与 ?v=修改时间（换用候选后不读旧缓存）
    return {"episode": ep, "url": file_url(w), "duration_s": meta.get("duration_s"),
            "shots": shots, "cues": cues, "old_script": bool(smt and w.stat().st_mtime < smt), "stale_timeline": stale_tl}


@router.get("/api/music")
def music_list():
    d = _music_dir()
    eps = sorted(int(m.group(1)) for f in (d.glob("ep*.wav") if d.is_dir() else [])
                 if (m := re.fullmatch(r"ep(\d{2,3})\.wav", f.name)))
    return {"episodes": [x for x in (_music(e) for e in eps) if x]}


@router.get("/api/music/{ep}")
def music_one(ep: int):
    m = _music(ep)
    if not m:
        raise HTTPException(404, f"第 {ep} 集还没有配乐")
    return m


# BGM10（2026-11-01）：配乐候选 + 一键换用（ns_api/bgm_api.py），挂在本路由下，不改 app.py
from ns_api.bgm_api import router as _bgm_router  # noqa: E402

router.include_router(_bgm_router)
