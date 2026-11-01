"""
VOX：一镜的 H3 原声里只把指定角色那句台词换成参考音色（Seed-VC），画面原样复制 → 嘴型 / 时间不变。

  .venv/Scripts/python.exe tools/voice_convert_shot.py ep02-S2 --reference <参考 wav> [--speaker gu_chen]
        [--video <mp4，默认 ep02.timeline.json 里这一镜用的那版>] [--out data/ab/voice_fix/vc_demo] [--label demo]

输出 <out>/<镜>_<label>.wav / .mp4 / .json（时间段、ASR 回听前后、基频前后）。
参考音色要项目方给；没给之前 --label 必须带 demo 字样，不代表选择。见 ns_post/voice_convert.py。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ab_voice_fix as V  # noqa: E402  (ASR / 基频测量共用)
from ns_post import voice_convert as VC  # noqa: E402
from ns_post.h3_dialogue import split_lines  # noqa: E402
from ns_post.tts import char_error_rate  # noqa: E402


def shot_video(shot: int) -> Path:
    tl = json.loads(V.TIMELINE.read_text(encoding="utf-8"))
    s = next(x for x in tl["shots"] if x["index"] == shot)
    return ROOT / s["file"]


def hear(w48: Path, work: Path, text: str) -> dict:
    w16 = work / (w48.stem + ".16k.wav")
    V.ffmpeg("-i", str(w48), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(w16))
    d = V.asr_detail(w16)
    r = split_lines(d, [text])[0]
    v = V.voice_metrics(w16, r["t0"], r["t1"], len(V.normalize(text)))
    return {"heard": d.get("text"), "cer": round(char_error_rate(text, str(d.get("text") or "")), 3),
            "t0": r["t0"], "t1": r["t1"], "voice": v}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--speaker", default="gu_chen")
    ap.add_argument("--video")
    ap.add_argument("--out", default=str(ROOT / "data" / "ab" / "voice_fix" / "vc_demo"))
    ap.add_argument("--label", default="demo")
    ap.add_argument("--steps", type=int, default=30)
    a = ap.parse_args()
    n = int(a.shot.split("S")[-1])
    line = V.speech_lines().get(n)
    if not line or line["speaker"] != a.speaker:
        raise SystemExit(f"{a.shot} 没有 {a.speaker} 的对白（时间线 speech）")
    video = Path(a.video) if a.video else shot_video(n)
    out = Path(a.out)
    work = out / "_work" / f"S{n}_{a.label}"
    work.mkdir(parents=True, exist_ok=True)
    stem = f"S{n}_{a.label}"
    orig = VC.extract_audio(video, out / f"S{n}_original.wav")
    before = hear(orig, work, line["text"])
    if before["t0"] is None:
        raise SystemExit(f"{a.shot}：SenseVoice 没听到这句，找不到时间段")
    res = VC.convert_span(orig, before["t0"], before["t1"], Path(a.reference), out / f"{stem}.wav",
                          steps=a.steps, work=work)
    VC.mux(video, out / f"{stem}.wav", out / f"{stem}.mp4")
    V.ffmpeg("-i", str(out / f"{stem}.wav"), "-c:a", "libmp3lame", "-b:a", "160k", str(out / f"{stem}.mp3"))
    after = hear(out / f"{stem}.wav", work, line["text"])
    rec = {"shot": a.shot, "speaker": a.speaker, "line": line["text"], "video": V.rel(video),
           "label": a.label, "is_demo": "demo" in a.label, "reference": a.reference,
           "convert": res, "before": before, "after": after,
           "files": {k: V.rel(out / f"{stem}.{k}") for k in ("wav", "mp3", "mp4")}}
    VC.dump(rec, out / f"{stem}.json")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
