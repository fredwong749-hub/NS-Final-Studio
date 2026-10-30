"""Audio gates on H3 native audio (PI-11 / PI-12 / PI-13 / PI-14). All warn-level (thresholds not locked).

Q-A1   H3-generated music when the take's prompt says non_diegetic_music N/A (or omits the field): CLAP music score
       from audio_post's stems.json (only when its video_sha256 equals the clip) ≤ 0.30. Q-A1b: DSP proxy
       (sustained spectral peaks in the non-vocal bed), reported only.
Q-A2   integrated loudness of the H3 track (ffmpeg ebur128) in −30…−16 LUFS; true peak ≤ −1 dBTP.
Q-A3   male-voice heuristic: voiced time with F0 < 165 Hz > 0.5 s while no male speaker is in the H3 dialogue.
Q-A4   speaker-count proxy: voiced pitch bands (<165 / ≥165 Hz, each > 0.5 s) vs genders of H3 dialogue speakers.
Q-A5   speech in the first 1.0 s of a shot without H3 dialogue < 0.3 s.
F0: YIN (cumulative-mean-normalised difference, threshold 0.15) on 40 ms frames, 10 ms hop, 60–500 Hz, energy gate.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import media as M
from .thresholds import judge

SR = 16000
MALE_F0 = 165.0
MUSIC_TAGS = ("music",)


def f0_track(x: np.ndarray, sr: int = SR, frame: float = 0.04, hop: float = 0.01, fmin: float = 60.0,
             fmax: float = 500.0, thresh: float = 0.15, gate_db: float = -45.0) -> tuple[np.ndarray, np.ndarray]:
    """(times, f0) with f0 = 0 for unvoiced frames."""
    W, Hp = int(frame * sr), int(hop * sr)
    if x is None or len(x) < W:
        return np.zeros(0), np.zeros(0)
    n = 1 + (len(x) - W) // Hp
    idx = np.arange(W)[None, :] + Hp * np.arange(n)[:, None]
    fr = x[idx].astype(np.float64)
    fr -= fr.mean(1, keepdims=True)
    rms_db = 10 * np.log10(np.mean(fr ** 2, 1) + 1e-12)
    peak_db = 20 * np.log10(np.max(np.abs(x)) + 1e-9)
    nfft = 1 << (2 * W - 1).bit_length()
    spec = np.fft.rfft(fr, nfft)
    r = np.fft.irfft(spec * np.conj(spec), nfft)[:, :W]
    e_tail = np.cumsum(fr[:, ::-1] ** 2, 1)[:, ::-1]  # Σ x[j], j ∈ [τ, W)
    e_head = np.cumsum(fr ** 2, 1)  # Σ x[j], j ∈ [0, k]
    tmin, tmax = int(sr / fmax), min(W - 1, int(sr / fmin))
    tau = np.arange(tmax + 1)
    d = e_head[:, W - 1 - tau] + e_tail[:, :tmax + 1] - 2 * r[:, :tmax + 1]
    d[:, 0] = 0
    cs = np.cumsum(d[:, 1:], 1)
    cmn = np.ones_like(d)
    cmn[:, 1:] = d[:, 1:] * tau[1:] / np.maximum(cs, 1e-12)
    f0 = np.zeros(n)
    for i in range(n):
        if rms_db[i] < max(gate_db, peak_db - 40):
            continue
        c = cmn[i, tmin:tmax + 1]
        below = np.nonzero(c < thresh)[0]
        if not below.size:
            continue
        j = below[0]
        while j + 1 < len(c) and c[j + 1] < c[j]:
            j += 1
        f0[i] = sr / (tmin + j)
    t = (np.arange(n) * Hp + W / 2) / sr
    return t, f0


def _runs_seconds(mask: np.ndarray, hop: float = 0.01, min_run: float = 0.1) -> float:
    total, run = 0, 0
    for m in list(mask) + [False]:
        if m:
            run += 1
        else:
            if run * hop >= min_run:
                total += run
            run = 0
    return round(total * hop, 2)


def tonal_ratio(x: np.ndarray, sr: int = SR, nfft: int = 2048, hop: int = 512, persist: int = 8,
                prom_db: float = 15.0) -> float | None:
    """Share of frames whose strongest spectral peak (100–4000 Hz) persists ±1 bin for `persist` frames and stands
    `prom_db` above the frame median — a proxy for sustained tonal (music-like) content."""
    if x is None or len(x) < nfft * 4:
        return None
    n = 1 + (len(x) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    mag = 20 * np.log10(np.abs(np.fft.rfft(x[idx] * np.hanning(nfft), axis=1)) + 1e-9)
    lo, hi = int(100 * nfft / sr), int(4000 * nfft / sr)
    band = mag[:, lo:hi]
    pk = band.argmax(1)
    prom = band.max(1) - np.median(band, 1)
    loud = band.max(1) > (band.max() - 50)
    stable = np.zeros(n, bool)
    for i in range(n - persist):
        if prom[i] >= prom_db and loud[i] and np.all(np.abs(pk[i:i + persist] - pk[i]) <= 1):
            stable[i:i + persist] = True
    return round(float(stable.mean()), 3)


def prompt_music(prompt: str | None) -> str:
    """'N/A' | 'unspecified' | the field text."""
    if not prompt:
        return "unspecified"
    m = re.search(r"non_diegetic_music:\s*(.+?)(?:\n\s*\n|$)", prompt, re.S)
    if not m:
        return "unspecified"
    v = m.group(1).strip()
    return "N/A" if v.upper().startswith("N/A") else v


def clap_music(stems: dict | None, clip_sha: str | None) -> tuple[float | None, str]:
    if not stems:
        return None, "no stems.json"
    if clip_sha and stems.get("video_sha256") and stems["video_sha256"] != clip_sha:
        return None, "stems.json was made from another video (sha mismatch) — CLAP evidence stale"
    tags = stems.get("h3_rest_tags") or {}
    vals = [v for k, v in tags.items() if any(t in k for t in MUSIC_TAGS)]
    if not vals:
        return None, "stems.json has no h3_rest_tags"
    return round(float(sum(vals)), 3), "sum of CLAP music-labels on the full H3 non-vocal bed (audio_post h3_rest_tags)"


def audio_gate(clip: Path, *, prompt: str | None, h3_dialogue_genders: set[str], has_dialogue: bool,
               stems: dict | None = None, clip_sha: str | None = None, vocals: Path | None = None,
               bed: Path | None = None) -> dict:
    res: list[dict] = []
    out = {"clip": str(clip), "gates": res}
    x = M.decode_audio(clip, SR)
    if x is None:
        for g in ("Q-A1", "Q-A2", "Q-A3", "Q-A4", "Q-A5"):
            res.append(judge(g, None, unchecked="clip has no audio stream"))
        return out
    # ---- music ----
    expect = prompt_music(prompt)
    out["non_diegetic_music_expected"] = expect
    bed_x = M.decode_audio(bed, SR) if bed and Path(bed).is_file() else None
    out["bed_source"] = str(bed) if bed_x is not None else "clip (no separated bed)"
    tr = tonal_ratio(bed_x if bed_x is not None else x)
    if expect in ("N/A", "unspecified"):
        score, why = clap_music(stems, clip_sha)
        res.append(judge("Q-A1", score, detail=f"prompt non_diegetic_music = {expect}; {why}",
                         unchecked=None if score is not None else why))
        res.append(judge("Q-A1b", tr, detail="share of frames with a sustained tonal peak"))
    else:
        res.append(judge("Q-A1", None, unchecked=f"music requested in the prompt: {expect[:80]}"))
        res.append(judge("Q-A1b", tr))
    # ---- loudness ----
    try:
        lo = M.ebur128(clip)
    except Exception as e:  # noqa: BLE001
        lo = {"lufs": M.rms_lufs_approx(x), "true_peak_dbtp": None, "method": f"RMS approx ({e})"}
    if lo["lufs"] is None:
        lo = {"lufs": M.rms_lufs_approx(x), "true_peak_dbtp": None, "method": "RMS approx (meter parse failed)"}
    res.append(judge("Q-A2", lo["lufs"], detail=lo["method"]))
    res.append(judge("Q-A2b", lo["true_peak_dbtp"], unchecked=None if lo["true_peak_dbtp"] is not None
                     else "true peak unavailable"))
    # ---- voice / pitch ----
    vx = M.decode_audio(vocals, SR) if vocals and Path(vocals).is_file() else None
    src = vx if vx is not None else x
    out["voice_source"] = str(vocals) if vx is not None else "clip mix (no vocal stem)"
    t, f0 = f0_track(src)
    voiced = f0 > 0
    low, high = voiced & (f0 < MALE_F0), voiced & (f0 >= MALE_F0)
    low_s, high_s = _runs_seconds(low), _runs_seconds(high)
    out["pitch"] = {"voiced_s": _runs_seconds(voiced), "low_band_s": low_s, "high_band_s": high_s,
                    "median_f0_hz": round(float(np.median(f0[voiced])), 1) if voiced.any() else None}
    male_ok = "male" in h3_dialogue_genders
    if male_ok:
        res.append(judge("Q-A3", None, unchecked="a male speaker is in the H3 dialogue"))
    else:
        res.append(judge("Q-A3", low_s, detail=f"voiced <{MALE_F0:.0f} Hz; H3 dialogue genders "
                                               f"{sorted(h3_dialogue_genders) or 'none'}"))
    bands = (low_s > 0.5) + (high_s > 0.5)
    expected = len(h3_dialogue_genders)
    res.append(judge("Q-A4", int(max(0, bands - expected)), detail=f"{bands} pitch band(s) >0.5 s vs {expected} "
                                                                  f"expected gender(s)"))
    if has_dialogue:
        res.append(judge("Q-A5", None, unchecked="shot has H3 dialogue (start time unknown)"))
    else:
        first = voiced & (t < 1.0)
        res.append(judge("Q-A5", _runs_seconds(first, min_run=0.05), detail="voiced seconds in 0–1.0 s"))
    return out
