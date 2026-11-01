"""VOICE10 · 第 1 步（gpu36 venv_tts 里跑，本仓库不 import）：Qwen3-TTS 1.7B VoiceDesign 按文字描述设计音色 → ref.wav。
与旁白 QAg 同一方法（data/assets/voices/narrator_qag/voice.json ref_generated_by）。文字设计的合成声，不克隆任何真人。

    python remote_design.py request.json   → 每条打印一行 JSON，最后一行 {"ok": true, ...}

request = {"model_dir": ..., "device": "cpu"|"cuda:0",
           "items": [{"instruct": ..., "text": ..., "seed": int, "out": "<abs>.wav"}]}
输出 24 kHz mono PCM16（与旁白 ref.wav 同格式）。已存在的 out 跳过（可断点续跑）。
"""
import json
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch

OUT_SR = 24000


def main():
    req = json.loads(open(sys.argv[1], encoding="utf-8").read())
    from qwen_tts import Qwen3TTSModel
    dev = req.get("device", "cpu")
    t0 = time.time()
    m = Qwen3TTSModel.from_pretrained(req["model_dir"], device_map=dev,
                                      dtype=torch.bfloat16 if dev.startswith("cuda") else torch.float32)
    print(json.dumps({"load_s": round(time.time() - t0, 1)}), flush=True)
    for it in req["items"]:
        if os.path.exists(it["out"]):
            continue
        os.makedirs(os.path.dirname(it["out"]), exist_ok=True)
        torch.manual_seed(int(it["seed"]))
        t1 = time.time()
        wavs, sr = m.generate_voice_design(text=it["text"], language="Chinese", instruct=it["instruct"])
        wav = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        if sr != OUT_SR:
            import torchaudio.functional as F
            wav = F.resample(torch.from_numpy(wav), sr, OUT_SR).numpy()
        sf.write(it["out"], np.clip(wav, -1, 1), OUT_SR, subtype="PCM_16")
        print(json.dumps({"out": it["out"], "seconds": round(len(wav) / OUT_SR, 2), "sec": round(time.time() - t1, 1)},
                         ensure_ascii=False), flush=True)
    print(json.dumps({"ok": True}), flush=True)


if __name__ == "__main__":
    main()
