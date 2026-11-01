"""VOICE10 · 第 2 步（gpu36 venv_tts 里跑，PYTHONPATH=venv_tts/cosy_overlay）：Fun-CosyVoice3 0.5B zero-shot
以候选 ref.wav 复刻，念这个人物自己的两句台词 → sample.wav（两句之间留 0.35 s）。与旁白 QAg 的管线同一方法
（services/post/ns_post/remote/narrator_batch.py 的 Cosy 类；时长不合理换种子重试，同一套 plausible 判据）。

    python remote_clone.py request.json

request = {"model_dir": ..., "seed": int,
           "items": [{"ref_wav": ..., "ref_text": ..., "lines": [t1, t2], "out": "<abs>/sample.wav"}]}
"""
import json
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch

COSY_SRC = "/root/work/fredw/src_tts/CosyVoice"
SEEDS_EXTRA = (1, 2, 3, 4, 5)
OUT_SR = 24000
GAP = 0.35


def plausible(text, seconds):
    n = sum(ch.isalnum() for ch in text)
    return n / 7.5 <= seconds <= max(2.0, n / 2.5)


def main():
    req = json.loads(open(sys.argv[1], encoding="utf-8").read())
    sys.path.insert(0, COSY_SRC)
    sys.path.insert(0, COSY_SRC + "/third_party/Matcha-TTS")
    from cosyvoice.cli.cosyvoice import AutoModel
    t0 = time.time()
    m = AutoModel(model_dir=req["model_dir"])
    print(json.dumps({"load_s": round(time.time() - t0, 1)}), flush=True)
    for it in req["items"]:
        if os.path.exists(it["out"]):
            continue
        prompt = "You are a helpful assistant.<|endofprompt|>" + it["ref_text"]
        parts, used = [], []
        t1 = time.time()
        for text in it["lines"]:
            for seed in (int(req.get("seed", 20261101)),) + SEEDS_EXTRA:
                torch.manual_seed(seed)
                segs = [j["tts_speech"] for j in m.inference_zero_shot(text, prompt, it["ref_wav"], stream=False)]
                wav = torch.cat(segs, 1).squeeze(0).cpu().numpy().astype(np.float32)
                if m.sample_rate != OUT_SR:
                    import torchaudio.functional as F
                    wav = F.resample(torch.from_numpy(wav), m.sample_rate, OUT_SR).numpy()
                if plausible(text, len(wav) / OUT_SR):
                    break
            parts.append(wav)
            used.append(seed)
        gap = np.zeros(int(GAP * OUT_SR), dtype=np.float32)
        out = np.concatenate([parts[0], gap, parts[1]])
        sf.write(it["out"], np.clip(out, -1, 1), OUT_SR, subtype="PCM_16")
        print(json.dumps({"out": it["out"], "seconds": round(len(out) / OUT_SR, 2), "seeds": used,
                          "parts_s": [round(len(p) / OUT_SR, 2) for p in parts], "sec": round(time.time() - t1, 1)},
                         ensure_ascii=False), flush=True)
    print(json.dumps({"ok": True}), flush=True)


if __name__ == "__main__":
    main()
