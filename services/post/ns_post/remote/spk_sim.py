"""Speaker similarity (cosine of CAM++ embeddings, CosyVoice's campplus.onnx) — runs on gpu36 venv_tts.

    python spk_sim.py <campplus.onnx> <ref.wav> <wav> [<wav> ...]   → JSON {wav: cosine}
Same feature recipe as CosyVoice frontend._extract_spk_embedding (16 kHz, 80-bin kaldi fbank, mean-normalised).
"""
import json
import sys

import numpy as np
import onnxruntime as ort
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi


def emb(sess, path):
    wav, sr = torchaudio.load(path)
    wav = wav.mean(0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    e = sess.run(None, {sess.get_inputs()[0].name: feat.unsqueeze(0).numpy()})[0].flatten()
    return e / (np.linalg.norm(e) + 1e-9)


def main():
    sess = ort.InferenceSession(sys.argv[1], providers=["CPUExecutionProvider"])
    ref = emb(sess, sys.argv[2])
    print(json.dumps({p: round(float(ref @ emb(sess, p)), 4) for p in sys.argv[3:]}))


if __name__ == "__main__":
    torch.set_num_threads(4)
    main()
