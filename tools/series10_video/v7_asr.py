"""K-OPS-V13 / VQAGATE 11-02：V7 台词时段用回听时间戳（总调度：分拍时间码只作兜底；ep01_v2 S4 实际 1.54 s、分拍写 00:04）。
服务器 speech venv（sherpa-onnx + SenseVoice int8，/root/work/fredw/speech）跑：片子音轨 16 kHz → SenseVoice 逐字时间戳 →
台词时段 = [第一个有字 token − pad, 最后一个有字 token + 字长 + pad]（多句按 > gap 秒的停顿切开）。

    /root/work/fredw/speech/venv/bin/python v7_asr.py <video.mp4>   → stdout 最后一行 JSON {"windows": [[t0, t1], ...], "text": ...}
"""
from __future__ import annotations

import os as _os   # K-OPS-V13：限线程
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")
NS_THREADS = int(_os.environ.get("NS_SCORE_THREADS", "4"))

import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import wave  # noqa: E402
from pathlib import Path  # noqa: E402

MODEL_DIRS = ["/root/work/fredw/speech/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
              "/root/claude-kimi-ns-studio-v1/models/speech/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"]
PAD, GAP, TOK_S = 0.3, 0.8, 0.25


def windows_from_tokens(tokens, stamps, durs=None, pad=PAD, gap=GAP) -> list:
    pts = []
    for k, tok in enumerate(tokens):
        if k < len(stamps) and re.search(r"\w", str(tok)):
            d = float(durs[k]) if durs and k < len(durs) and durs[k] else TOK_S
            pts.append((float(stamps[k]), float(stamps[k]) + d))
    out = []
    for a, b in pts:
        if out and a - out[-1][1] <= gap:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [[round(max(0.0, a - pad), 2), round(b + pad, 2)] for a, b in out]


def main(argv):
    import sherpa_onnx
    md = next((m for m in MODEL_DIRS if Path(m, "tokens.txt").exists()), None)
    if not md:
        print(json.dumps({"error": "没有 SenseVoice 模型"}, ensure_ascii=False))
        return
    model = next(str(Path(md, f)) for f in ("model.int8.onnx", "model.onnx") if Path(md, f).exists())
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(model=model, tokens=str(Path(md, "tokens.txt")), num_threads=NS_THREADS,
                                                         use_itn=True, language="auto")
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", argv[0], "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(w)],
                       check=True)
        with wave.open(str(w)) as wf:
            import array
            pcm = array.array("h")
            pcm.frombytes(wf.readframes(wf.getnframes()))
            rate = wf.getframerate()
    st = rec.create_stream()
    st.accept_waveform(rate, [x / 32768.0 for x in pcm])
    rec.decode_stream(st)
    r = st.result
    toks, ts = list(getattr(r, "tokens", []) or []), list(getattr(r, "timestamps", []) or [])
    durs = list(getattr(r, "durations", []) or [])
    print(json.dumps({"text": r.text, "windows": windows_from_tokens(toks, ts, durs), "n_tokens": len(toks)}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
