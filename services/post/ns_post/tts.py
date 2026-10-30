"""Local CPU TTS (Kokoro multi-lang v1.1) and ASR round trip (SenseVoice), adapted from ns-studio
adapters/tts/local_tts (NSFW Drama system).

Speech runs in a separate, isolated interpreter that has only sherpa-onnx installed (NS_TTS_PYTHON);
this repo never imports sherpa-onnx. `speech_worker.py` is spoken to over JSON stdin/stdout. CPU only
(provider="cpu"), audio never leaves the machine. Voices are Kokoro's generic synthetic speakers — no
cloning of anyone.

Clips are cached by sha256(model, sid, speed, text) under data/cache/tts/, so re-assembling an episode
does not re-synthesize unchanged lines.
"""

import hashlib
import json
import math
import os
import subprocess
import unicodedata
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

ROOT = Path(os.environ.get("NS_PROJECT_ROOT") or Path(__file__).resolve().parents[3])  # T42：子进程可指向 projects/<slug>
WORKER = Path(__file__).with_name("speech_worker.py")
VOICES_JSON = ROOT / "config" / "voices.json"
CACHE_DIR = ROOT / "data" / "cache" / "tts"


class TtsError(RuntimeError):
    pass


class TtsUnavailable(TtsError):
    """No speech interpreter or model on this machine."""


@dataclass(frozen=True)
class Voice:
    speaker: str  # character id (config/voices.json)
    sid: int  # Kokoro speaker id
    name: str = ""  # Kokoro voice name (zf_001 ...)
    speed: float = 1.0
    model: str = "kokoro-multi-lang-v1_1"

    @property
    def id(self) -> str:
        return f"kokoro:{self.name or self.sid}"


def load_voice_config(path: Path = VOICES_JSON) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def voice_for(cfg: dict, speaker: str, *, voiceover: bool = False, speed_factor: float = 1.0) -> list[Voice]:
    """The fixed voice(s) of a speaker: one Voice, or several for a group (chorus)."""
    chars = cfg["characters"]
    model = cfg.get("tts_model", {}).get("id", "kokoro-multi-lang-v1_1")
    members = cfg.get("groups", {}).get(speaker)
    if members:
        return [v for m in members for v in voice_for(cfg, m, speed_factor=speed_factor)]
    c = chars.get(speaker)
    if c is None:
        raise TtsError(f"no voice for speaker {speaker!r}: add it to config/voices.json")
    speed = float(c.get("vo_speed", c.get("speed", 1.0)) if voiceover else c.get("speed", 1.0))
    return [Voice(speaker, int(c["sid"]), c.get("voice", ""), round(speed * speed_factor, 3), model)]


# ---------------- WAV helpers (stdlib) ----------------

def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def write_tone(path: Path, seconds: float, freq: float, sample_rate: int = 24000) -> None:
    n = max(1, round(seconds * sample_rate))
    pcm = array("h", (int(6000 * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


# ---------------- backends ----------------

class TtsBackend(Protocol):
    name: str

    def synthesize(self, items: list[tuple[str, Voice, Path]]) -> None:
        """Write one 16-bit mono WAV per (text, voice, out path)."""
        ...


class AsrBackend(Protocol):
    def transcribe(self, wavs: list[Path], language: str = "zh") -> list[str]: ...


Runner = Callable[[list[str], str, float], subprocess.CompletedProcess]


def run_json(cmd: list[str], stdin: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def _setting(cfg: dict, section: str, key_env: str, key_default: str) -> str | None:
    sec = cfg.get(section, {})
    env = sec.get(key_env)
    v = os.environ.get(env) if env else None
    if v and Path(v).exists():
        return v
    d = sec.get(key_default)
    return d if d and Path(d).exists() else None


class _Worker:
    def __init__(self, cfg: dict, model_section: str, *, python: str | None = None, model_dir: str | None = None,
                 num_threads: int = 4, timeout_s: float = 3600.0, runner: Runner = run_json):
        self.python = python or _setting(cfg, "speech_python", "env", "default")
        self.model_dir = model_dir or _setting(cfg, model_section, "env_dir", "default_dir")
        if not self.python:
            raise TtsUnavailable("no speech interpreter: set NS_TTS_PYTHON (python with sherpa-onnx==1.13.8)")
        if not self.model_dir:
            raise TtsUnavailable(f"no model directory for {model_section}: see config/voices.json")
        self.num_threads, self.timeout_s, self.runner = num_threads, timeout_s, runner

    def call(self, request: dict) -> dict:
        request = {"model_dir": self.model_dir, "num_threads": self.num_threads, **request}
        try:
            proc = self.runner([self.python, "-I", str(WORKER)], json.dumps(request), self.timeout_s)
        except subprocess.TimeoutExpired as e:
            raise TtsError(f"speech worker timed out after {self.timeout_s:.0f} s") from e
        except OSError as e:
            raise TtsUnavailable(f"cannot start {self.python}: {e}") from e
        try:
            resp = json.loads(proc.stdout or "")
        except ValueError:
            raise TtsError(f"speech worker exited {proc.returncode}: {(proc.stderr or '')[-500:]}") from None
        if not resp.get("ok"):
            raise TtsError(f"speech worker failed: {resp.get('error')}")
        return resp


class KokoroBackend(_Worker):
    name = "kokoro"

    def __init__(self, cfg: dict, **kw):
        super().__init__(cfg, "tts_model", **kw)

    def synthesize(self, items: list[tuple[str, Voice, Path]]) -> None:
        if not items:
            return
        req = [{"text": t, "sid": v.sid, "speed": v.speed, "out": str(p)} for t, v, p in items]
        resp = self.call({"op": "tts", "items": req})
        if len(resp.get("items", [])) != len(req):
            raise TtsError("speech worker returned the wrong number of clips")


class SenseVoiceAsr(_Worker):
    def __init__(self, cfg: dict, **kw):
        super().__init__(cfg, "asr_model", **kw)

    def transcribe(self, wavs: list[Path], language: str = "zh") -> list[str]:
        if not wavs:
            return []
        resp = self.call({"op": "asr", "language": language, "items": [{"wav": str(p)} for p in wavs]})
        return [str(i.get("text", "")) for i in resp.get("items", [])]


class FakeTts:
    """Tests: a tone per line, length from the character count (12 chars/s ÷ speed), pitch from the sid."""

    name = "fake"

    def __init__(self, chars_per_second: float = 12.0):
        self.cps = chars_per_second
        self.calls: list[tuple[str, int]] = []

    def synthesize(self, items: list[tuple[str, Voice, Path]]) -> None:
        for text, voice, out in items:
            self.calls.append((text, voice.sid))
            n = sum(ch.isalnum() for ch in text)
            write_tone(out, max(0.3, n / self.cps) / max(voice.speed, 0.1), 150.0 + 3.0 * voice.sid)


class FakeAsr:
    def __init__(self, transcripts: dict[str, str] | None = None):
        self.transcripts = transcripts or {}

    def transcribe(self, wavs: list[Path], language: str = "zh") -> list[str]:
        return [self.transcripts.get(Path(w).name, "") for w in wavs]


# ---------------- cached synthesis ----------------

def clip_key(text: str, voice: Voice, backend: str) -> str:
    h = hashlib.sha256(json.dumps([backend, voice.model, voice.sid, voice.speed, text],
                                  ensure_ascii=False).encode("utf-8")).hexdigest()
    return h[:24]


def synthesize_cached(backend: TtsBackend, requests: list[tuple[str, Voice]], cache_dir: Path = CACHE_DIR
                      ) -> list[Path]:
    """One WAV per (text, voice); only lines not in the cache are synthesized (one worker call)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths, todo = [], []
    for text, voice in requests:
        p = cache_dir / f"{clip_key(text, voice, backend.name)}.wav"
        paths.append(p)
        if not p.exists() and all(p != q for _, _, q in todo):
            todo.append((text, voice, p.with_suffix(".tmp.wav")))
    if todo:
        backend.synthesize(todo)
        for _, _, tmp in todo:
            if not tmp.exists():
                raise TtsError(f"TTS did not write {tmp.name}")
            os.replace(tmp, tmp.with_name(tmp.name.replace(".tmp.wav", ".wav")))
    return paths


# ---------------- ASR round trip ----------------

def normalize(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold()
                   if unicodedata.category(ch)[0] in "LN")


def char_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return min(1.0, prev[-1] / len(ref))


def asr_limit(text: str) -> float:
    """Short lines are dominated by homophones (有/又): allow more."""
    return 0.5 if len(normalize(text)) <= 6 else 0.2
