"""Episode assembly: 6 shot videos + TTS dialogue/voiceover + H3 sound design → data/episodes/epXX.mp4.

Picture: each shot is trimmed (or held on its last frame) to Shot.duration, scaled to cover 1080×1920 and
center-cropped, 24 fps, H.264 (libx264, CPU). No subtitles (owner rule). Shots without a gpu3 video get a
placeholder still clip made from the active first frame (marked in the timeline).

Sound (one audible copy of every line, the lesson from ns-studio media/audio.py): H3 was prompted with the
same dialogue, so its soundtrack carries its own take of the lines in an arbitrary voice. Under every TTS
dialogue line the H3 track is gated (-gate_db, linear ramps); under voiceover it is ducked (-vo_duck_db);
elsewhere it plays at h3_gain_db as the sound design bed. The sum is loudness-normalised with a two-pass
linear loudnorm to target_lufs (default -14 LUFS, true peak -1.5 dBTP).

Timing: dialogue is laid out inside its own shot (lead-in, gaps); if it does not fit, gaps shrink, then the
lines are sped up (atempo, ≤ max_tempo) and, as a last resort, cut at the shot end — each with a warning.
Voiceover starts in its own shot (after the shot's dialogue, if any) and may run on into the next shots,
avoiding later dialogue where it can. Audio that runs past the last shot holds the last frame (tail hold).
"""

import json
import math
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path

import numpy as np

from .ffmpeg import FFmpeg, parse_loudnorm
from .music import (find_music, fit_length, ignored_edits, level_curve, load_stems, normalise_rms,
                    read_edit_music, resolve_cues)
from .speakers import SpokenLine, resolve_episode
from .tts import (CACHE_DIR, AsrBackend, TtsBackend, Voice, asr_limit, char_error_rate, load_voice_config,
                  synthesize_cached, voice_for, wav_duration)

ROOT = Path(os.environ.get("NS_PROJECT_ROOT") or Path(__file__).resolve().parents[3])  # T42：子进程可指向 projects/<slug>
DATA = ROOT / "data"


@dataclass(frozen=True)
class Settings:
    width: int = 1080
    height: int = 1920
    fps: int = 24
    crf: int = 18
    preset: str = "medium"
    threads: int = 8  # x264 threads (CPU is shared with other jobs)
    sample_rate: int = 48000
    target_lufs: float = -14.0
    true_peak_db: float = -1.5
    lra: float = 11.0
    h3_gain_db: float = -3.0  # sound design bed under everything
    gate_db: float = 40.0  # H3 attenuation under TTS dialogue (its own take of the line)
    vo_duck_db: float = 10.0  # H3 attenuation under voiceover
    gate_pad_s: float = 0.12
    gate_fade_s: float = 0.08
    dialogue_lead_s: float = 0.3
    dialogue_gap_s: float = 0.35
    min_lead_s: float = 0.1
    min_gap_s: float = 0.12
    max_tempo: float = 1.2
    vo_lead_s: float = 0.5
    vo_after_dialogue_s: float = 0.4
    vo_margin_s: float = 0.2
    tail_s: float = 0.6  # audio must end this long before the picture does
    chorus_gain_db: float = -4.0
    edge_fade_s: float = 0.05
    # gpu3 stems (docs/intimate_audio.md: foley -6..-10 dB under voice, scene -8..-12 dB under voice-over)
    scene_duck_dialogue_db: float = 6.0
    scene_duck_vo_db: float = 10.0
    foley_duck_db: float = 8.0
    # BGM
    bgm: bool = True
    bgm_duck_dialogue_db: float = 12.0
    bgm_duck_vo_db: float = 9.0
    bgm_duck_h3_db: float = 6.0  # epXX.json duck_spans without their own duck_db
    # deliveries: 1080x1920 always; 2160x3840 when "on", or "auto" and any 4K clip exists
    deliver_4k: str = "auto"
    width_4k: int = 2160
    height_4k: int = 3840
    crf_4k: int = 20
    # optional per-shot colour correction to our keyframes (ns_post.colormatch; <clip>_cc.mp4). Off by default.
    color_match: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- picture sources ----------------

def _active_file(shot_dir: Path, stage: str) -> Path | None:
    tj = shot_dir / "takes.json"
    if not tj.exists():
        return None
    try:
        t = json.loads(tj.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    n = (t.get("active") or {}).get(stage)
    for take in t.get("takes") or []:
        if take.get("stage") == stage and take.get("n") == n and take.get("file"):
            p = Path(take["file"])
            for cand in (p, DATA / p, shot_dir / "takes" / p.name):
                if cand.is_file():
                    return cand
    return None


def find_source(ep: int, idx: int, *, data: Path = DATA, allow_laptop_video: bool = False) -> dict:
    """Where shot epXX/SN's picture comes from: {kind, path, note}. kind: video | still | black."""
    g = data / "renders_gpu3" / f"ep{ep:02d}" / f"S{idx}"
    l = data / "renders" / f"ep{ep:02d}" / f"S{idx}"
    v = _active_file(g, "video") if g.is_dir() else None
    if v is None and (g / "video.mp4").is_file():
        v = g / "video.mp4"
    if v is not None:
        v4 = v.with_name(v.stem + "_4k" + v.suffix)
        return {"kind": "video", "origin": "gpu3", "path": v, "path_4k": v4 if v4.is_file() else None}
    if allow_laptop_video:
        lv = _active_file(l, "video") or ((l / "video.mp4") if (l / "video.mp4").is_file() else None)
        if lv is not None:
            return {"kind": "video", "origin": "laptop", "path": lv}
    for d, origin in ((g, "gpu3"), (l, "laptop")):
        img = _active_file(d, "image") if d.is_dir() else None
        if img is None and (d / "frame.png").is_file():
            img = d / "frame.png"
        if img is not None:
            return {"kind": "still", "origin": origin, "path": img}
    return {"kind": "black", "origin": None, "path": None}


# ---------------- timeline planning (pure) ----------------

@dataclass
class Placement:
    line: SpokenLine
    voices: list[str]
    clip_s: float  # natural TTS length (s)
    start_s: float = 0.0
    tempo: float = 1.0
    cut_s: float | None = None  # audible length after a forced cut at the shot end
    files: list[str] = field(default_factory=list)

    @property
    def length_s(self) -> float:
        n = self.clip_s / self.tempo
        return min(n, self.cut_s) if self.cut_s is not None else n

    @property
    def end_s(self) -> float:
        return self.start_s + self.length_s


def _overlaps(a0: float, a1: float, spans: list[tuple[float, float]], margin: float) -> tuple[float, float] | None:
    for b0, b1 in spans:
        if a0 < b1 + margin and b0 < a1 + margin:
            return b0, b1
    return None


def plan_timeline(durations: list[float], placements: list[Placement], s: Settings = Settings()
                  ) -> tuple[list[float], float, list[str]]:
    """Set start/tempo/cut on every placement. Returns (shot starts, tail hold seconds, warnings)."""
    warnings: list[str] = []
    starts = [sum(durations[:i]) for i in range(len(durations))]
    total = sum(durations)
    by_shot: dict[int, list[Placement]] = {}
    for p in placements:
        if p.line.kind == "dialogue":
            by_shot.setdefault(p.line.shot, []).append(p)
    for shot, lines in by_shot.items():
        i = shot - 1
        dur, t0 = durations[i], starts[i]
        speech = sum(p.clip_s for p in lines)
        n = len(lines)
        lead, gap, tempo = s.dialogue_lead_s, s.dialogue_gap_s, 1.0
        if lead + speech + gap * (n - 1) + s.min_lead_s > dur:
            lead, gap = s.min_lead_s, s.min_gap_s
            room = dur - 2 * s.min_lead_s - gap * (n - 1)
            if speech > room:
                tempo = min(s.max_tempo, speech / max(room, 1e-6))
                warnings.append(f"S{shot}: dialogue {speech:.2f}s does not fit the {dur:g}s shot; "
                                f"sped up ×{tempo:.2f}")
        t = t0 + lead
        for p in lines:
            p.start_s, p.tempo = round(t, 3), round(tempo, 4)
            t = p.end_s + gap
        last = lines[-1]
        if last.end_s > t0 + dur - 0.02:
            over = last.end_s - (t0 + dur)
            warnings.append(f"S{shot}: dialogue still {over:.2f}s longer than the shot after ×{tempo:.2f}; "
                            f"lines are cut at the shot end")
            for p in lines:
                if p.end_s > t0 + dur - 0.02:
                    p.cut_s = max(0.0, t0 + dur - 0.02 - p.start_s)
    shot_of = {k + 1: (starts[k], durations[k]) for k in range(len(durations))}
    vos: list[Placement] = []

    def busy() -> list[tuple[float, float]]:
        return [(q.start_s, q.end_s) for q in placements if q.line.kind == "dialogue"] +                [(q.start_s, q.end_s) for q in vos]

    def shift_later_dialogue(a0: float, a1: float) -> bool:
        """Move the dialogue block of a later shot that overlaps [a0, a1] later inside its shot, if it fits."""
        for shot, lines in by_shot.items():
            first, last = lines[0], lines[-1]
            if not (a0 < last.end_s + s.vo_margin_s and first.start_s < a1 + s.vo_margin_s):
                continue
            k0, kd = shot_of[shot]
            need = a1 + s.vo_margin_s - first.start_s
            if first.start_s < a0 or last.end_s + need > k0 + kd - s.min_lead_s:
                return False
            for q in lines:
                q.start_s = round(q.start_s + need, 3)
            warnings.append(f"S{shot}: dialogue moved {need:.2f}s later to make room for the voiceover")
            return True
        return False

    for p in sorted((p for p in placements if p.line.kind == "voiceover"), key=lambda p: p.line.shot):
        i = p.line.shot - 1
        t0, dur = starts[i], durations[i]
        own = by_shot.get(p.line.shot, [])
        earliest = (max(q.end_s for q in own) + s.vo_after_dialogue_s) if own else t0 + s.vo_lead_s
        base = earliest
        if "尾入" in (p.line.note or "") and not own:  # enters late in its shot, ideally ending with it
            base = max(base, t0 + dur - s.tail_s - p.clip_s)
        start = base
        hit = _overlaps(start, start + p.clip_s, busy(), s.vo_margin_s)
        if hit is not None and hit[0] > start:  # runs into something later: start earlier in its own shot
            start = max(earliest, hit[0] - s.vo_margin_s - p.clip_s)
            hit = _overlaps(start, start + p.clip_s, busy(), s.vo_margin_s)
        if hit is not None and hit[0] > start:  # still: move the next shot's dialogue later if it has room
            if shift_later_dialogue(start, start + p.clip_s):
                hit = _overlaps(start, start + p.clip_s, busy(), s.vo_margin_s)
        for _ in range(50):
            if hit is None:
                break
            start = hit[1] + s.vo_margin_s
            hit = _overlaps(start, start + p.clip_s, busy(), s.vo_margin_s)
        if start > t0 + dur - 0.5:  # cannot begin inside its own shot without talking over dialogue
            start = base
            warnings.append(f"S{p.line.shot}: voiceover overlaps later dialogue (no free slot in its shot)")
        p.start_s = round(start, 3)
        vos.append(p)
        if p.end_s > t0 + dur:
            nxt = [k + 1 for k in range(len(durations)) if starts[k] < p.end_s and k > i]
            if nxt:
                warnings.append(f"S{p.line.shot}: voiceover runs {p.end_s - (t0 + dur):.2f}s into S{nxt[-1]}"
                                + ("" if len(nxt) == 1 else f" (spans S{nxt[0]}–S{nxt[-1]})"))
    end = max([p.end_s for p in placements], default=0.0)
    tail = max(0.0, end + s.tail_s - total)
    tail = math.ceil(tail * s.fps - 1e-6) / s.fps  # whole frames, so picture and sound end together
    if tail > 0:
        warnings.append(f"audio runs past the last shot: last frame held {tail:.2f}s")
    return starts, round(tail, 3), warnings


# ---------------- rendering ----------------

def _vf(s: Settings, frames: int, w: int, h: int) -> str:
    return (f"fps={s.fps},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h},setsar=1,tpad=stop_mode=clone:stop_duration=600,"
            f"trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p")


def render_segment(ff: FFmpeg, src: dict, seconds: float, out: Path, s: Settings, *, uhd: bool = False) -> None:
    frames = round(seconds * s.fps)
    w, h = (s.width_4k, s.height_4k) if uhd else (s.width, s.height)
    crf = s.crf_4k if uhd else s.crf
    if src["kind"] == "video":
        inp = ["-i", (src.get("path_4k_cc") or src.get("path_4k") or src["path"]) if uhd
               else (src.get("path_cc") or src["path"])]
    elif src["kind"] == "still":
        inp = ["-loop", "1", "-framerate", str(s.fps), "-t", f"{seconds + 1:.3f}", "-i", src["path"]]
    else:
        inp = ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={s.fps}:d={seconds + 1:.3f}"]
    ff.run([*inp, "-map", "0:v:0", "-vf", _vf(s, frames, w, h), "-an", "-c:v", "libx264", "-preset", s.preset,
            "-crf", str(crf), "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(s.fps),
            "-threads", str(s.threads), "-video_track_timescale", "12288", str(out)])


def read_audio(ff: FFmpeg, path: str | Path, sr: int, *, channels: int = 2, seconds: float | None = None,
               tempo: float = 1.0, work: Path) -> np.ndarray:
    """Decode to float32 [n, channels] at sr (optionally sped up with atempo, cut/padded to seconds)."""
    raw = work / f"dec_{abs(hash((str(path), tempo, seconds))) % 10**12}.f32"
    af = [f"aresample={sr}"]
    if abs(tempo - 1.0) > 1e-3:
        af.append(f"atempo={tempo:.4f}")
    if seconds is not None:
        af += ["apad", f"atrim=end_sample={round(seconds * sr)}"]
    ff.run(["-i", path, "-vn", "-af", ",".join(af), "-ac", str(channels), "-ar", str(sr), "-f", "f32le", raw])
    x = np.fromfile(raw, dtype=np.float32)
    raw.unlink(missing_ok=True)
    return x.reshape(-1, channels)


def gain_envelope(n: int, sr: int, spans: list[tuple[float, float, float]], fade: float) -> np.ndarray:
    """Per-sample linear gain: 1 outside spans, 10^(-db/20) inside, linear ramps of `fade` outside each span.
    Overlaps take the deepest attenuation."""
    t = np.arange(n, dtype=np.float64) / sr
    g = np.ones(n, dtype=np.float64)
    for a, b, db in spans:
        floor = 10 ** (-db / 20)
        w = np.clip((t - (a - fade)) / fade, 0, 1) * np.clip(((b + fade) - t) / fade, 0, 1)
        g = np.minimum(g, 1 - (1 - floor) * w)
    return g.astype(np.float32)


def _fade_edges(x: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    k = min(len(x) // 2, round(seconds * sr))
    if k > 0:
        ramp = np.linspace(0, 1, k, dtype=np.float32)[:, None]
        x[:k] *= ramp
        x[-k:] *= ramp[::-1]
    return x


def loudnorm(ff: FFmpeg, raw: Path, out: Path, s: Settings) -> dict:
    """Two-pass linear loudnorm of a raw f32le stereo mix → 48 kHz 16-bit WAV. When the gain to the target
    would push peaks past the true-peak ceiling, a limiter is put in front first (so the second pass can stay
    linear instead of loudnorm's dynamic fallback). Returns the measurements."""
    inp = ["-f", "f32le", "-ar", str(s.sample_rate), "-ac", "2", "-i", raw]
    base = f"loudnorm=I={s.target_lufs:g}:TP={s.true_peak_db:g}:LRA={s.lra:g}"

    def measure(pre: str) -> dict:
        return parse_loudnorm(ff.run(["-nostats", *inp, "-af", pre + base + ":print_format=json",
                                      "-f", "null", "-"]).stderr)

    m1 = measure("")
    if not math.isfinite(float(m1["input_i"])) or float(m1["input_i"]) < -70:
        ff.run([*inp, "-c:a", "pcm_s16le", out])  # silence: nothing to normalise
        return {"pass1": m1, "limiter": None, "applied": None}
    pre = ""
    gain = s.target_lufs - float(m1["input_i"])
    if float(m1["input_tp"]) + gain > s.true_peak_db:
        limit = 10 ** ((s.true_peak_db - 1.0) / 20)
        pre = f"volume={gain:.2f}dB,alimiter=limit={limit:.4f}:attack=5:release=80:level=false,"
        m1 = measure(pre)
    f = (f"{base}:measured_I={m1['input_i']}:measured_TP={m1['input_tp']}:measured_LRA={m1['input_lra']}"
         f":measured_thresh={m1['input_thresh']}:offset={m1['target_offset']}:linear=true:print_format=json")
    proc = ff.run(["-nostats", *inp, "-af", pre + f + f",aresample={s.sample_rate}", "-c:a", "pcm_s16le", out])
    return {"pass1": m1, "limiter": pre.rstrip(",") or None, "applied": parse_loudnorm(proc.stderr)}


def measure_loudness(ff: FFmpeg, path: Path) -> dict:
    m = parse_loudnorm(ff.run(["-nostats", "-i", path, "-vn", "-af", "loudnorm=print_format=json",
                               "-f", "null", "-"]).stderr)
    return {"integrated_lufs": float(m["input_i"]), "true_peak_dbtp": float(m["input_tp"]),
            "lra": float(m["input_lra"])}


def _color_match_source(ff: FFmpeg, src: dict, idx: int, warnings: list[str], log) -> None:
    """Settings.color_match: picture from <clip>_cc.mp4 (made/reused by ns_post.colormatch). src["path"] stays the
    original (qa.json sha256 gate, H3 audio)."""
    from .colormatch import ensure_cc, short_summary
    info = {}
    for key, out_key in (("path", "path_cc"), ("path_4k", "path_4k_cc")):
        if not src.get(key):
            continue
        try:
            cc, rep = ensure_cc(Path(src[key]), ff=ff, log=log)
        except Exception as e:  # noqa: BLE001 — colour correction is optional; fall back to the original
            warnings.append(f"S{idx}: colour match failed on {Path(src[key]).name}: {e}")
            continue
        if cc is None:
            warnings.append(f"S{idx}: colour match skipped ({rep.get('error')})")
        else:
            src[out_key] = str(cc)
        info[key] = {"file": _rel(cc), "before": short_summary(rep, "before"), "after": short_summary(rep, "after"),
                     "plan": rep.get("plan")}
    src["color_match"] = info or None


# ---------------- episode ----------------

def _concat(ff: FFmpeg, segs: list[Path], out: Path, work: Path) -> Path:
    lst = work / f"{out.stem}.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    ff.run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    return out


def load_episode(script: Path, ep: int) -> dict:
    d = json.loads(Path(script).read_text(encoding="utf-8"))
    for e in d["episodes"]:
        if int(e["number"]) == ep:
            return e
    raise KeyError(f"episode {ep} not in {script}")


def _rel(p: Path | str | None) -> str | None:
    if p is None:
        return None
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)



def _sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def qa_gate(qa_path: Path, srcs: list[dict], src_list: list[dict]) -> tuple[bool, list[str]]:
    """成片闸门（与 gpu3 约定）：renders_gpu3/epXX/qa.json 的 verdict 必须是 "pass"，
    且每个镜头实际用的视频与 qa.json.shots[SN].video_sha256 一致、该镜 verdict 为 pass。"""
    if not qa_path.is_file():
        return False, ["没有 qa.json（gpu3 未验收）"]
    try:
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return False, [f"qa.json 读不了：{e}"]
    reasons = []
    if qa.get("verdict") != "pass":
        reasons.append(f"整集 verdict={qa.get('verdict')!r}")
    shots = qa.get("shots") or {}
    for row, src in zip(srcs, src_list):
        key = f"S{row['index']}"
        q = shots.get(key)
        if not q:
            reasons.append(f"{key} 不在 qa.json")
            continue
        if q.get("verdict") != "pass":
            reasons.append(f"{key} verdict={q.get('verdict')!r}")
        if src.get("kind") != "video" or not src.get("path"):
            reasons.append(f"{key} 不是视频")
        elif q.get("video_sha256") != _sha256(src["path"]):
            reasons.append(f"{key} 视频与验收版本不一致（sha256）")
    return not reasons, reasons

def assemble_episode(episode: dict, out_dir: Path, *, tts: TtsBackend, asr: AsrBackend | None = None,
                     ff: FFmpeg | None = None, settings: Settings = Settings(), voices_cfg: dict | None = None,
                     data: Path = DATA, cache_dir: Path = CACHE_DIR, sources: dict[int, dict] | None = None,
                     allow_laptop_video: bool = False, keep_work: bool = False, log=print) -> dict:
    """Build out_dir/epXX.mp4 and out_dir/epXX.timeline.json; returns the timeline dict."""
    s = settings
    ff = ff or FFmpeg.discover()
    cfg = voices_cfg or load_voice_config()
    ep = int(episode["number"])
    name = f"ep{ep:02d}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    shots = sorted(episode["shots"], key=lambda x: int(x["index"]))
    durations = [float(x.get("duration") or 10) for x in shots]

    # 1. lines + TTS
    lines = resolve_episode(episode, cfg.get("line_overrides"))
    placements, requests, req_index = [], [], []
    for ln in lines:
        vs: list[Voice] = voice_for(cfg, ln.speaker, voiceover=ln.kind == "voiceover")
        p = Placement(ln, [f"{v.id} (sid {v.sid}, speed {v.speed:g})" for v in vs], 0.0)
        placements.append(p)
        for v in vs:
            req_index.append((len(placements) - 1, v))
            requests.append((ln.text, v))
    t = time.perf_counter()
    paths = synthesize_cached(tts, requests, cache_dir) if requests else []
    timings["tts_s"] = round(time.perf_counter() - t, 2)
    for (pi, _v), path in zip(req_index, paths):
        placements[pi].files.append(str(path))
    for p in placements:
        p.clip_s = round(max(wav_duration(f) for f in p.files), 3)

    # 2. ASR round trip (one audible voice per line; chorus checked on its first voice)
    asr_rows: dict[int, dict] = {}
    if asr is not None and placements:
        t = time.perf_counter()
        heard = asr.transcribe([Path(p.files[0]) for p in placements], "zh")
        for i, (p, h) in enumerate(zip(placements, heard)):
            cer = char_error_rate(p.line.text, h)
            asr_rows[i] = {"heard": h, "cer": round(cer, 3), "ok": cer <= asr_limit(p.line.text)}
        timings["asr_s"] = round(time.perf_counter() - t, 2)

    # 3. plan
    starts, tail, warnings = plan_timeline(durations, placements, s)
    for i, row in asr_rows.items():
        if not row["ok"]:
            warnings.append(f"{placements[i].line.key}: ASR heard '{row['heard']}' (CER {row['cer']:.2f})")

    # 4. picture
    total = sum(durations) + tail
    srcs, src_list = [], []
    work_root = Path(cache_dir).parent / "post"
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{name}_", dir=str(work_root)))
    deliveries: dict[str, dict] = {}
    bgm_info: dict = {"used": False}
    try:
        t = time.perf_counter()
        seg_files = []
        for i, shot in enumerate(shots):
            idx = int(shot["index"])
            src = (sources or {}).get(idx) or find_source(ep, idx, data=data, allow_laptop_video=allow_laptop_video)
            src = {k: (str(v) if isinstance(v, Path) else v) for k, v in dict(src).items()}
            seconds = durations[i] + (tail if i == len(shots) - 1 else 0.0)
            info = ff.info(src["path"]) if src["kind"] == "video" else None
            if src["kind"] != "video":
                warnings.append(f"S{idx}: no gpu3 video — placeholder {src['kind']} clip"
                                + (f" from {_rel(src['path'])}" if src.get("path") else ""))
            elif info["duration"] + 0.02 < durations[i]:
                warnings.append(f"S{idx}: video is {info['duration']:.2f}s, shot is {durations[i]:g}s; "
                                f"last frame held {durations[i] - info['duration']:.2f}s")
            if s.color_match and src["kind"] == "video":
                _color_match_source(ff, src, idx, warnings, log)
            seg = work / f"seg{idx}.mp4"
            render_segment(ff, src, seconds, seg, s)
            seg_files.append(seg)
            src_list.append(src)
            srcs.append({"shot": f"{name}-S{idx}", "index": idx, "start_s": round(starts[i], 3),
                         "duration_s": durations[i], "duration_source": shot.get("duration_source"),
                         "picture_s": round(seconds, 6), "kind": src["kind"], "origin": src.get("origin"),
                         "placeholder": src["kind"] != "video", "file": _rel(src.get("path")),
                         "file_4k": _rel(src.get("path_4k")),
                         "source_duration_s": round(info["duration"], 3) if info else None,
                         "source_size": [info["width"], info["height"]] if info else None,
                         "trimmed_s": round(max(0.0, info["duration"] - durations[i]), 3) if info else None,
                         "h3_audio": bool(info and info["has_audio"]), "adult": shot.get("adult"),
                         **({"color_match": src.get("color_match")} if s.color_match else {})})
        picture = _concat(ff, seg_files, work / "picture.mp4", work)
        timings["picture_s"] = round(time.perf_counter() - t, 2)

        # 5. sound
        t = time.perf_counter()
        sr = s.sample_rate
        n_total = round(sum(round(x["picture_s"] * s.fps) for x in srcs) / s.fps * sr)
        dlg = [(p.start_s - s.gate_pad_s, p.end_s + s.gate_pad_s) for p in placements if p.line.kind == "dialogue"]
        vo = [(p.start_s - s.gate_pad_s, p.end_s + s.gate_pad_s) for p in placements if p.line.kind == "voiceover"]

        def env(dlg_db: float, vo_db: float) -> np.ndarray:
            spans = [(a, b, dlg_db) for a, b in dlg if dlg_db > 0] + [(a, b, vo_db) for a, b in vo if vo_db > 0]
            return gain_envelope(n_total, sr, spans, s.gate_fade_s)[:, None]

        duck = {  # role -> (dB under TTS dialogue, dB under voice-over)
            "h3": (s.gate_db, s.vo_duck_db), "vocals": (s.gate_db, s.vo_duck_db),
            "scene": (s.scene_duck_dialogue_db, s.scene_duck_vo_db), "foley": (s.foley_duck_db, s.foley_duck_db),
        }
        layers: dict[tuple, np.ndarray] = {}  # (role, dB under TTS dialogue, dB under voice-over) -> track
        for i, row in enumerate(srcs):
            k0 = round(starts[i] * sr)
            k1 = min(n_total, k0 + round(durations[i] * sr))
            stems, err = load_stems(data / "renders_gpu3" / name / f"S{row['index']}")
            if err:
                warnings.append(f"S{row['index']}: {err}")
            if stems:
                used = []
                for st in stems:
                    a = read_audio(ff, st["path"], sr, seconds=durations[i], work=work)
                    a = _fade_edges(a, sr, s.edge_fade_s) * np.float32(10 ** (st["gain_db"] / 20))
                    off = round(st["offset_s"] * sr)
                    a0 = k0 + max(0, off)
                    a = a[max(0, -off):][: max(0, k1 - a0)]
                    role = st["role"] if st["role"] in duck else "foley"
                    d_dlg, d_vo = duck[role]
                    if role != "vocals" and st.get("duck_under_voice_db") is not None:  # vocals stay gated
                        d_dlg = abs(float(st["duck_under_voice_db"]))
                    if st.get("duck_under_vo_db") is not None:
                        d_vo = abs(float(st["duck_under_vo_db"]))
                    key = (role, d_dlg, d_vo)
                    layers.setdefault(key, np.zeros((n_total, 2), dtype=np.float32))[a0:a0 + len(a)] += a
                    used.append({"name": st["name"], "file": _rel(st["path"]), "gain_db": st["gain_db"],
                                 "offset_s": st["offset_s"], "role": role, "duck_under_dialogue_db": d_dlg,
                                 "duck_under_vo_db": d_vo})
                row["audio"], row["stems"] = "stems", used
            elif row["h3_audio"]:
                a = read_audio(ff, src_list[i]["path"], sr, seconds=durations[i], work=work)
                a = _fade_edges(a, sr, s.edge_fade_s) * np.float32(10 ** (s.h3_gain_db / 20))
                layers.setdefault(("h3", *duck["h3"]), np.zeros((n_total, 2), dtype=np.float32))[k0:k0 + len(a)] += \
                    a[: max(0, n_total - k0)]
                row["audio"] = "h3_track"
            else:
                row["audio"] = "none"
        mix = np.zeros((n_total, 2), dtype=np.float32)
        for (_role, d_dlg, d_vo), x in layers.items():
            mix += x * env(d_dlg, d_vo)
        for p in placements:
            g = 10 ** (s.chorus_gain_db / 20) if len(p.files) > 1 else 1.0
            for f in p.files:
                a = read_audio(ff, f, sr, channels=1, tempo=p.tempo, work=work)[:, 0]
                if p.cut_s is not None:
                    a = a[: round(p.cut_s * sr)]
                    k = min(len(a), round(0.08 * sr))
                    if k:
                        a[-k:] *= np.linspace(1, 0, k, dtype=np.float32)
                k0 = round(p.start_s * sr)
                a = a[: max(0, n_total - k0)]
                mix[k0:k0 + len(a)] += (a * g)[:, None]

        # BGM (gpu3 T40 file + cue timeline; skipped with a warning when absent)
        if not s.bgm:
            bgm_info = {"used": False, "reason": "disabled"}
        else:
            music_file, music_meta = find_music(ep, data / "music")
            if music_file is None:
                warnings.append(f"no BGM: data/music/{name}.(wav|flac|mp3) not found — music layer skipped")
                bgm_info = {"used": False, "reason": "no file"}
            else:
                edits = {int(x["index"]): read_edit_music(data / "renders", ep, int(x["index"])) for x in shots}
                edits = {k: v for k, v in edits.items() if v}
                cues = resolve_cues(shots, starts, music_meta, edits)
                for k, v in ignored_edits(music_meta, edits).items():
                    warnings.append(f"S{k}: owner music edit '{v}' not applied — {name}.json carries a cue "
                                    f"timeline; regenerate the BGM on gpu3 (T40) to include it")
                m = normalise_rms(read_audio(ff, music_file, sr, work=work))
                g = level_curve(cues, n_total, sr, total)[:, None]
                if len(m) < n_total and float(g[len(m):].max()) < 1e-3:  # cues are silent past its end: pad
                    m, looped = np.concatenate([m, np.zeros((n_total - len(m), 2), np.float32)]), False
                else:
                    m, looped = fit_length(m, n_total, sr)
                if looped:
                    warnings.append(f"BGM {music_file.name} is shorter than the episode: looped")
                shot_duck = np.zeros(n_total, dtype=np.float32)
                for c in cues:
                    if c.duck_db and c.shot:
                        a0 = round(starts[c.shot - 1] * sr)
                        shot_duck[a0:a0 + round(durations[c.shot - 1] * sr)] = c.duck_db
                ducked = env(s.bgm_duck_dialogue_db, s.bgm_duck_vo_db)
                # gpu3 duck_spans: H3 dialogue / vocal activity (absolute seconds) — duck there too
                h3_spans = []
                for d in music_meta.get("duck_spans") or []:
                    try:
                        h3_spans.append((float(d["start_s"]) - s.gate_pad_s, float(d["end_s"]) + s.gate_pad_s,
                                         abs(float(d.get("duck_db", s.bgm_duck_h3_db)))))
                    except (KeyError, TypeError, ValueError):
                        continue
                if h3_spans:
                    ducked = np.minimum(ducked, gain_envelope(n_total, sr, h3_spans, s.gate_fade_s)[:, None])
                speaking = ducked[:, 0] < 0.999
                extra = np.where(speaking, 10 ** (-shot_duck / 20), 1.0).astype(np.float32)[:, None]
                mix += m * g * ducked * extra
                bgm_info = {"used": True, "file": _rel(music_file),
                            "meta": {k: music_meta.get(k) for k in ("bpm", "model", "seed", "sha256", "prompt")
                                     if k in music_meta},
                            "episode_edit_music": read_edit_music(data / "renders", ep),
                            "script_music": episode.get("music_bgm") or episode.get("music") or None,
                            "cues": [c.to_dict() for c in cues], "looped": looped,
                            "cue_source": "music_json" if music_meta.get("cues") else
                            ("script/edit" if any(c.source in ("script", "edit") for c in cues) else "default"),
                            "duck_spans": len(h3_spans)}
        raw = work / "mix.f32"
        mix.astype(np.float32).tofile(raw)
        wav = work / "mix.wav"
        loud_passes = loudnorm(ff, raw, wav, s)
        timings["sound_s"] = round(time.perf_counter() - t, 2)

        # 6. mux (+ 4K delivery with the same sound)
        t = time.perf_counter()
        want_4k = s.deliver_4k == "on" or (s.deliver_4k == "auto" and any(x.get("path_4k") for x in src_list))
        # 有占位镜头（无 gpu3 视频）或 gpu3 QA 未通过时绝不叫 final：项目方会把预览当成片（gpu3 4K 只从 _final 取音频）
        qa_ok, qa_reasons = qa_gate(data / "renders_gpu3" / name / "qa.json", srcs, src_list)
        preview = any(x.get("placeholder") for x in srcs) or not qa_ok
        warnings.extend(f"QA 闸门：{r}" for r in qa_reasons)
        stem = f"{name}_PREVIEW_未完成" if preview else f"{name}_final"
        final = out_dir / f"{stem}.mp4"
        if preview:
            warnings.append("PREVIEW：有占位镜头，输出为预览（不是成片），不生成 epXX_final / epXX 别名")
        outputs = [("1080p", picture, final)]
        if want_4k:
            segs4 = []
            for i, src in enumerate(src_list):
                seg = work / f"seg{srcs[i]['index']}_4k.mp4"
                render_segment(ff, src, srcs[i]["picture_s"], seg, s, uhd=True)
                segs4.append(seg)
                srcs[i]["picture_4k"] = "4k_clip" if src.get("path_4k") else (
                    "upscaled_lanczos" if src["kind"] != "black" else "black")
            outputs.append(("4k", _concat(ff, segs4, work / "picture_4k.mp4", work), out_dir / f"{stem}_4k.mp4"))
            missing = [x["index"] for x in srcs if x.get("picture_4k") != "4k_clip"]
            if missing:
                warnings.append(f"4K delivery: no 4K clip for S{', S'.join(map(str, missing))} — "
                                f"upscaled (lanczos) from the lower-resolution source")
        expected = sum(round(x["picture_s"] * s.fps) for x in srcs)
        for label, pic, out in outputs:
            ff.run(["-i", pic, "-i", wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-ar", str(sr), "-ac", "2", "-movflags", "+faststart", "-shortest", out])
            n_frames = ff.count_frames(out)
            if n_frames != expected:
                warnings.append(f"{label}: frame count {n_frames} != expected {expected}")
            inf = ff.info(out)
            deliveries[label] = {"file": _rel(out), "size": [inf["width"], inf["height"]], "frames": n_frames,
                                 "duration_s": round(inf["duration"], 3), "video_codec": inf["video_codec"],
                                 "audio_codec": inf["audio_codec"]}
        if not preview:
            alias = out_dir / f"{name}.mp4"
            alias.unlink(missing_ok=True)
            try:
                os.link(final, alias)
            except OSError:
                shutil.copyfile(final, alias)
            deliveries["1080p"]["alias"] = _rel(alias)
        loud = measure_loudness(ff, outputs[0][2])
        info = ff.info(outputs[0][2])
        frames = deliveries["1080p"]["frames"]
        timings["mux_s"] = round(time.perf_counter() - t, 2)
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
    timings["total_s"] = round(time.perf_counter() - t_start, 2)

    speech = []
    for i, p in enumerate(placements):
        ln = p.line
        speech.append({"key": f"{name}-{ln.key}", "kind": ln.kind, "shot": ln.shot, "speaker": ln.speaker,
                       "speaker_name": cfg["characters"].get(ln.speaker, {}).get("name", ln.speaker),
                       "voices": p.voices, "text": ln.text, "note": ln.note, "resolved_by": ln.how,
                       "start_s": p.start_s, "end_s": round(p.end_s, 3), "tts_s": p.clip_s,
                       "tempo": p.tempo, "cut_s": p.cut_s, "files": [_rel(f) for f in p.files],
                       "asr": asr_rows.get(i)})
    timeline = {
        "episode": ep, "title": episode.get("title"), "output": _rel(final), "preview": preview,
        "duration_s": round(info["duration"], 3), "frames": frames, "fps": s.fps,
        "size": [s.width, s.height], "video_codec": info["video_codec"], "audio_codec": info["audio_codec"],
        "subtitles": False, "tail_hold_s": tail,
        "deliveries": deliveries,
        "loudness": {"target_lufs": s.target_lufs, "measured": loud, "loudnorm": loud_passes},
        "bgm": bgm_info,
        "tts": {"backend": getattr(tts, "name", type(tts).__name__), "model": cfg.get("tts_model", {}).get("id"),
                "asr": "sensevoice" if asr is not None and type(asr).__name__ == "SenseVoiceAsr"
                else (type(asr).__name__ if asr else None)},
        "shots": srcs, "speech": speech, "warnings": warnings, "timings": timings, "settings": s.to_dict(),
    }
    (out_dir / f"{name}.timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1),
                                                   encoding="utf-8")
    for w in warnings:
        log(f"WARN {w}")
    return timeline
