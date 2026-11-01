"""VOICE 2026-10-31：旁白音色 QAg 落地验证——用管线同一路径（resolve_episode → voice_for → synthesize_cached →
RoutedTts → RemoteCloneBackend @ gpu36）合成某集的旁白，回听（SenseVoice）记 CER，响度归一 −16 LUFS，
写 data/review_pages/narrator_pick/verify/。

  .venv/Scripts/python.exe tools/narrator_verify.py --ep 1 [--shots 7]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.speakers import resolve_episode  # noqa: E402
from ns_post.tts import (KokoroBackend, SenseVoiceAsr, char_error_rate, load_voice_config,  # noqa: E402
                         synthesize_cached, voice_for, wav_duration)

OUT = ROOT / "data" / "review_pages" / "narrator_pick" / "verify"


def loudnorm(src: Path, dst: Path, target: float = -16.0) -> dict:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af",
                        f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    j = json.loads(p.stderr[p.stderr.rindex("{"):p.stderr.rindex("}") + 1])
    af = (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
          f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-af", af, "-ar", "24000",
                    "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True)
    q = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(dst), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    t = q[q.rindex("Summary:"):]
    return {"lufs": float(t.split("I:")[1].split("LUFS")[0]), "true_peak_dbtp": float(t.split("Peak:")[1].split("dBFS")[0])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--shots", type=int, nargs="*")
    a = ap.parse_args()
    cfg = load_voice_config()
    script = json.loads((ROOT / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    ep = next(e for e in script["episodes"] if int(e.get("number", 0)) == a.ep)
    lines = [ln for ln in resolve_episode(ep, cfg.get("line_overrides"))
             if ln.kind == "voiceover" and (not a.shots or ln.shot in a.shots)]
    reqs = [(ln.text, v) for ln in lines for v in voice_for(cfg, ln.speaker, voiceover=True)]
    paths = synthesize_cached(KokoroBackend(cfg), reqs)
    asr = SenseVoiceAsr(cfg)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for ln, (text, v), p in zip(lines, reqs, paths):
        stem = f"ep{a.ep:02d}_S{ln.shot}_vo_{v.speaker}"
        dst = OUT / f"{stem}.wav"
        ln_meas = loudnorm(p, dst)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(dst), "-c:a", "libmp3lame",
                        "-b:a", "192k", str(dst.with_suffix(".mp3"))], check=True)
        wav16 = OUT / f"_{stem}_16k.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(dst), "-ar", "16000", "-ac", "1",
                        str(wav16)], check=True)
        heard = asr.transcribe([wav16])[0]
        wav16.unlink()
        rows.append({"key": f"ep{a.ep:02d}-S{ln.shot}#vo", "speaker": ln.speaker, "voice": v.id, "model": v.model,
                     "text": text, "raw": ln.raw, "heard": heard, "cer": round(char_error_rate(text, heard), 3),
                     "seconds": round(wav_duration(dst), 2), "cache": p.relative_to(ROOT).as_posix(),
                     "mp3": dst.with_suffix(".mp3").name, **ln_meas})
        print(json.dumps(rows[-1], ensure_ascii=False))
    (OUT / f"ep{a.ep:02d}_verify.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
