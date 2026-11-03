"""Provenance gates (PI-24 / PI-25): bible_version stamps vs current, prompt recompiled after render, stems built
from another video, keyframes used by H3 not in the mirror, video.mp4 ≠ active take, sync heartbeat age."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import media as M
from .thresholds import judge, judge_bool


def current_bible_version(root: Path) -> tuple[str | None, str]:
    p = root / "data" / "state_timeline.json"
    try:                                        # V2CUT-O 11-03：状态表按当前剧取（V2 = data/import/runs/<run>/）
        from ns_agent.run_paths import timeline_json  # type: ignore
        p = timeline_json(root)
    except Exception:  # noqa: BLE001  — 没有 ns_agent（gpu3 侧）：用旧位置
        pass
    try:
        v = json.loads(p.read_text(encoding="utf-8")).get("bible_version")
        if v:
            return v, f"{p.name} bible_version"
    except (OSError, ValueError):
        pass
    try:  # laptop helper (same function gpu3 stamps with)
        from ns_agent.compiler import bible_version  # type: ignore
        return bible_version(root), "ns_agent.compiler.bible_version()"
    except Exception:  # noqa: BLE001
        return None, "unknown"


def stamp_state(take: dict, current: str | None) -> str:
    v = take.get("bible_version")
    if not v:
        return "unstamped"
    if current is None:
        return "unknown_current"
    return "current" if v == current else "stale"


def local_path(p: str | None, data: Path, shot_dir: Path, cache: Path | None = None) -> tuple[Path | None, str]:
    """Map a takes.json path (data-relative, or gpu3 absolute) onto the laptop. Returns (path, how)."""
    if not p:
        return None, "none recorded"
    pp = Path(p)
    posix = pp.as_posix()
    cands = []
    if not pp.is_absolute() and not posix.startswith("/"):
        cands += [(data / pp, "data-relative"), (shot_dir / pp, "shot-relative")]
    if "/data/renders_gpu3/" in posix:
        cands.append((data / "renders_gpu3" / posix.split("/data/renders_gpu3/", 1)[1], "gpu3 mirror path"))
    if cache is not None:
        cands.append((cache / gpu3_cache_name(posix), "fetched from gpu3 (read-only copy)"))
    for c, how in cands:
        if c.is_file():
            return c, how
    return None, "not in the local mirror"


def gpu3_cache_name(posix: str) -> str:
    import hashlib
    return hashlib.sha1(posix.encode()).hexdigest()[:16] + "_" + Path(posix).name


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()  # naive stamps are UTC (gpu3)
    except ValueError:
        return None


def shot_provenance(shot_dir: Path, takes: dict, current_bv: str | None, compiled: dict | None,
                    stems: dict | None, video_take: dict | None, video_path: Path | None,
                    kf: dict) -> dict:
    res: list[dict] = []
    active = takes.get("active") or {}
    rows = takes.get("takes") or []
    stale = []
    for t in rows:
        stg = t.get("stage")
        is_active = active.get(stg) == t.get("n")
        st = stamp_state(t, current_bv)
        if is_active:
            stale.append({"stage": stg, "n": t.get("n"), "file": t.get("file"), "state": st,
                          "bible_version": t.get("bible_version")})
    bad = [s for s in stale if s["state"] != "current"]
    res.append(judge_bool("Q-P1", not bad, [f"{s['stage']}#{s['n']}:{s['state']}" for s in stale],
                          detail=f"current bible_version {current_bv}; active takes "
                                 f"{len(stale)}, not current {len(bad)}"))
    all_states = {}
    for t in rows:
        all_states[stamp_state(t, current_bv)] = all_states.get(stamp_state(t, current_bv), 0) + 1
    if video_take is not None:
        comp_at = _ts((compiled or {}).get("h3_prompt_compiled_at"))
        made_at = _ts(video_take.get("created_at"))
        if comp_at is None or made_at is None:
            res.append(judge("Q-P2", None, unchecked="compiled_at or take created_at missing"))
        else:
            newer = comp_at > made_at
            used_sha = M_sha_text(video_take.get("prompt"))
            res.append(judge_bool("Q-P2", not newer, newer,
                                  detail=f"h3_prompt compiled {compiled.get('h3_prompt_compiled_at')} vs video take "
                                         f"#{video_take.get('n')} {video_take.get('created_at')}; take prompt sha "
                                         f"{used_sha[:12] if used_sha else None} vs compiled h3_prompt sha "
                                         f"{(compiled.get('h3_prompt_sha256') or '')[:12]}"))
    else:
        res.append(judge("Q-P2", None, unchecked="no active video take"))
    vsha = M.sha256(video_path) if video_path and video_path.is_file() else None
    if stems is None:
        res.append(judge("Q-P3", None, unchecked="no audio/stems.json"))
    elif vsha is None:
        res.append(judge("Q-P3", None, unchecked="video file not in the mirror"))
    else:
        ok = stems.get("video_sha256") == vsha
        res.append(judge_bool("Q-P3", ok, ok, detail=f"stems {str(stems.get('video_sha256'))[:12]} vs video {vsha[:12]}"))
    for which in ("first", "last"):
        info = kf.get(which) or {}
        if info.get("recorded") is None:
            continue
        exact = info.get("how") in ("data-relative", "shot-relative", "gpu3 mirror path",
                                    "fetched from gpu3 (read-only copy)")
        res.append(judge_bool("Q-P4", exact, exact, edge=which,
                              detail=f"{which} keyframe recorded {info.get('recorded')} → {info.get('how')}"))
    if video_take is None:
        res.append(judge("Q-P5", None, unchecked="no active video take"))
    else:
        tfile, _ = local_path(video_take.get("file"), shot_dir.parents[2], shot_dir)
        mp4 = shot_dir / "video.mp4"
        if tfile is None and not mp4.is_file():
            res.append(judge_bool("Q-P5", False, False, detail=f"active video take #{video_take.get('n')} "
                                                               f"({video_take.get('file')}) and video.mp4 both missing"))
        else:
            a = M.sha256(tfile) if tfile else None
            b = M.sha256(mp4) if mp4.is_file() else None
            ok = a is not None and b is not None and a == b
            res.append(judge_bool("Q-P5", ok, ok, detail=f"take {str(a)[:12]} vs video.mp4 {str(b)[:12]}"))
    return {"gates": res, "active_stamps": stale, "all_take_stamps": all_states}


def M_sha_text(s: str | None) -> str | None:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest() if s else None


def heartbeat(path: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not path.is_file():
        return judge("Q-S1", None, unchecked=f"{path} missing")
    try:
        ts = float(path.read_text(encoding="utf-8").strip().split()[0])
        how = "epoch in file"
    except (ValueError, IndexError, OSError):
        ts, how = path.stat().st_mtime, "file mtime"
    age = round((now - ts) / 60.0, 1)
    return judge("Q-S1", age, detail=f"{path.name}: {how} {datetime.fromtimestamp(ts, timezone.utc).isoformat()}",
                 last_sync_utc=datetime.fromtimestamp(ts, timezone.utc).isoformat())
