"""Standalone speech worker, run by the isolated speech interpreter (NS_TTS_PYTHON).

Copied from ns-studio adapters/tts/local_tts/worker.py (NSFW Drama system), unchanged protocol.

    <NS_TTS_PYTHON> -I worker.py  < request.json  > response.json

Depends only on the standard library and `sherpa_onnx` (installed in that
interpreter, never in ns-studio). It must not import NS-Final Studio code. Runs on
CPU; audio never leaves this machine.

Request:  {"op": "tts", "model_dir": ..., "num_threads": 2,
           "items": [{"text": ..., "sid": 0, "speed": 1.0, "out": "<path>.wav"}]}
          {"op": "asr", "model_dir": ..., "num_threads": 2, "language": "auto",
           "items": [{"wav": "<path>.wav"}]}
          {"op": "ping"}
Response: {"ok": true, "items": [...]}  or  {"ok": false, "error": "..."}
TTS items return {"out", "sample_rate", "samples"}; ASR items return {"text"}.
"""

import json
import os
import sys
import wave
from array import array

PROTOCOL = 1


def _existing(model_dir, names):
    return [os.path.join(model_dir, n) for n in names if os.path.exists(os.path.join(model_dir, n))]


def _require(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return path


def kokoro_tts(sherpa, model_dir, num_threads):
    lexicons = _existing(model_dir, ("lexicon-us-en.txt", "lexicon-zh.txt"))
    fsts = _existing(model_dir, ("phone-zh.fst", "date-zh.fst", "number-zh.fst"))
    kokoro = dict(model=_require(os.path.join(model_dir, "model.onnx")),
                  voices=_require(os.path.join(model_dir, "voices.bin")),
                  tokens=_require(os.path.join(model_dir, "tokens.txt")),
                  data_dir=_require(os.path.join(model_dir, "espeak-ng-data")),
                  lexicon=",".join(lexicons))
    if os.path.isdir(os.path.join(model_dir, "dict")):
        kokoro["dict_dir"] = os.path.join(model_dir, "dict")
    try:
        kokoro_cfg = sherpa.OfflineTtsKokoroModelConfig(**kokoro)
    except TypeError:  # newer sherpa-onnx dropped dict_dir
        kokoro.pop("dict_dir", None)
        kokoro_cfg = sherpa.OfflineTtsKokoroModelConfig(**kokoro)
    config = sherpa.OfflineTtsConfig(
        model=sherpa.OfflineTtsModelConfig(kokoro=kokoro_cfg, num_threads=num_threads, provider="cpu"),
        rule_fsts=",".join(fsts), max_num_sentences=1)
    if hasattr(config, "validate") and not config.validate():
        raise ValueError(f"invalid Kokoro config for {model_dir}")
    return sherpa.OfflineTts(config)


def write_wav(path, samples, sample_rate):
    pcm = array("h", (max(-32768, min(32767, int(round(float(s) * 32767)))) for s in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())
    return len(pcm)


def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV is supported")
        channels, rate = w.getnchannels(), w.getframerate()
        pcm = array("h")
        pcm.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder != "little":
        pcm.byteswap()
    return [pcm[i] / 32768.0 for i in range(0, len(pcm), channels)], rate


def sense_voice(sherpa, model_dir, num_threads, language):
    model = _existing(model_dir, ("model.int8.onnx", "model.onnx"))
    if not model:
        raise FileNotFoundError(os.path.join(model_dir, "model.int8.onnx"))
    return sherpa.OfflineRecognizer.from_sense_voice(
        model=model[0], tokens=_require(os.path.join(model_dir, "tokens.txt")), num_threads=num_threads,
        use_itn=True, language=language or "auto")


def handle(request, sherpa):
    op = request.get("op")
    if op == "ping":
        return {"ok": True, "protocol": PROTOCOL, "sherpa_onnx": getattr(sherpa, "__version__", "unknown")}
    model_dir = request["model_dir"]
    threads = int(request.get("num_threads", 2))
    items = []
    if op == "tts":
        tts = kokoro_tts(sherpa, model_dir, threads)
        for item in request["items"]:
            audio = tts.generate(item["text"], sid=int(item.get("sid", 0)), speed=float(item.get("speed", 1.0)))
            n = write_wav(item["out"], audio.samples, audio.sample_rate)
            if n == 0:
                raise ValueError(f"no audio generated for item {len(items)}")
            items.append({"out": item["out"], "sample_rate": int(audio.sample_rate), "samples": n})
        return {"ok": True, "protocol": PROTOCOL, "items": items}
    if op == "asr":
        recognizer = sense_voice(sherpa, model_dir, threads, request.get("language", "auto"))
        for item in request["items"]:
            samples, rate = read_wav(item["wav"])
            stream = recognizer.create_stream()
            stream.accept_waveform(rate, samples)
            recognizer.decode_stream(stream)
            res = stream.result
            item = {"text": res.text}
            # AUD（2026-10-31）：附带 SenseVoice 的逐字时间戳与事件标签（BGM/Speech/…）；旧调用方只读 text
            for key in ("tokens", "timestamps", "durations"):
                v = getattr(res, key, None)
                if v:
                    item[key] = [x if isinstance(x, str) else float(x) for x in v]
            for key in ("event", "lang", "emotion"):
                v = getattr(res, key, None)
                if v:
                    item[key] = str(v)
            items.append(item)
        return {"ok": True, "protocol": PROTOCOL, "items": items}
    raise ValueError(f"unknown op {op!r}")


def main():
    try:
        request = json.loads(sys.stdin.read())
        import sherpa_onnx
        response = handle(request, sherpa_onnx)
    except Exception as e:  # report every failure as JSON; the caller decides retryability
        response = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(response))  # ASCII-escaped: safe on any console code page
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
