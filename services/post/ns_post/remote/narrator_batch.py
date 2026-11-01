"""Narrator TTS batch worker — runs on gpu36 inside /root/work/fredw/venv_tts (NOT imported by this repo).

VOICE 2026-10-31：项目方选定旁白音色 QAg（Qwen3-TTS VoiceDesign 文字设计的合成声，不克隆任何真人）。
所有旁白句都以固定参考音频 ref.wav 复刻，保证每集同一个声音。

    python narrator_batch.py request.json      (→ prints one JSON line: {"ok": true, "items": [...]})

request = {"engine": "cosyvoice3_zs" | "qwen3_clone", "model_dir": ..., "ref_wav": ..., "ref_text": ...,
           "seed": 20261031, "device": "cuda:0" | "cpu",
           "items": [{"text": ..., "out": "<abs path>.wav", "speed": 1.0}]}
Output: 24 kHz mono 16-bit PCM WAV per item. Long items are retried with other seeds when the duration is
implausible for the character count (LLM sampling occasionally runs away or stops early).
cosyvoice3_zs needs transformers 4.51.3 on PYTHONPATH (venv_tts/cosy_overlay; run_narrator.sh sets it).
"""
import json
import sys
import time

import numpy as np
import soundfile as sf
import torch

COSY_SRC = "/root/work/fredw/src_tts/CosyVoice"
SEEDS_EXTRA = (1, 2, 3, 4, 5)
OUT_SR = 24000


def plausible(text: str, seconds: float, speed: float) -> bool:
    n = sum(ch.isalnum() for ch in text)
    return n / (7.5 * speed) <= seconds <= max(2.0, n / (2.5 * speed))


def to_out(wav: np.ndarray, sr: int) -> np.ndarray:
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if sr != OUT_SR:
        import torchaudio.functional as F
        wav = F.resample(torch.from_numpy(wav), sr, OUT_SR).numpy()
    return np.clip(wav, -1.0, 1.0)


class Cosy:
    def __init__(self, req):
        sys.path.insert(0, COSY_SRC)
        sys.path.insert(0, COSY_SRC + "/third_party/Matcha-TTS")
        from cosyvoice.cli.cosyvoice import AutoModel
        self.m = AutoModel(model_dir=req["model_dir"])
        self.prompt_text = "You are a helpful assistant.<|endofprompt|>" + req["ref_text"]
        self.ref = req["ref_wav"]

    def say(self, text, speed):
        segs = [j["tts_speech"] for j in self.m.inference_zero_shot(text, self.prompt_text, self.ref, stream=False,
                                                                      speed=speed)]
        return torch.cat(segs, 1).squeeze(0).cpu().numpy(), self.m.sample_rate


class Qwen:
    def __init__(self, req):
        from qwen_tts import Qwen3TTSModel
        dev = req.get("device", "cpu")
        self.m = Qwen3TTSModel.from_pretrained(req["model_dir"], device_map=dev,
                                               dtype=torch.bfloat16 if dev.startswith("cuda") else torch.float32)
        self.prompt = self.m.create_voice_clone_prompt(ref_audio=req["ref_wav"], ref_text=req["ref_text"])

    def say(self, text, speed):
        wavs, sr = self.m.generate_voice_clone(text=text, language="Chinese", voice_clone_prompt=self.prompt)
        wav = wavs[0]
        if abs(speed - 1.0) > 1e-3:  # Qwen clone has no speed knob: time-stretch keeps pitch
            import librosa
            wav = librosa.effects.time_stretch(np.asarray(wav, dtype=np.float32), rate=speed)
        return wav, sr


def main():
    req = json.loads(open(sys.argv[1], encoding="utf-8").read())
    t0 = time.time()
    eng = {"cosyvoice3_zs": Cosy, "qwen3_clone": Qwen}[req["engine"]](req)
    load_s = round(time.time() - t0, 1)
    out = []
    for it in req["items"]:
        speed = float(it.get("speed", 1.0))
        t1 = time.time()
        for seed in (int(req.get("seed", 20261031)),) + SEEDS_EXTRA:
            torch.manual_seed(seed)
            wav, sr = eng.say(it["text"], speed)
            wav = to_out(wav, sr)
            dur = len(wav) / OUT_SR
            if plausible(it["text"], dur, speed):
                break
        sf.write(it["out"], wav, OUT_SR, subtype="PCM_16")
        out.append({"out": it["out"], "seconds": round(dur, 3), "seed": seed, "sec": round(time.time() - t1, 1)})
    print(json.dumps({"ok": True, "engine": req["engine"], "load_s": load_s, "items": out}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — reported to the caller as JSON
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        sys.exit(1)
