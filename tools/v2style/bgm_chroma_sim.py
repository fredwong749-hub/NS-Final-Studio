"""STYLE-V2 配乐：幻想编配 vs 现实编配的动机相似度（在 bgm.json score_host 上跑，用 /root/work/fredw/bgm/venv 的 librosa）。

    venv/bin/python stylev2_chroma_sim.py files.json      files.json = {候选 id: raw.wav 路径}

逐帧 chroma_cqt（hop 2048 @ 22.05 kHz，≈ 93 ms）单位化后对齐时间求余弦均值。cover 任务保留结构与时长，所以按时间直接对齐即可。
pair[X_reality*] = 与同主题 X_fantasy 的相似度；cross_theme_mean = 不同主题之间（幻想 X vs 现实 Y，X≠Y）的均值，作对照。
"""
import json
import sys

import librosa
import numpy as np

files = json.load(open(sys.argv[1], encoding="utf-8"))
C = {}
for cid, path in files.items():
    y, sr = librosa.load(path, sr=22050, mono=True)
    ch = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=2048)
    C[cid] = ch / (np.linalg.norm(ch, axis=0, keepdims=True) + 1e-9)


def sim(a, b):
    n = min(C[a].shape[1], C[b].shape[1])
    return float(np.mean(np.sum(C[a][:, :n] * C[b][:, :n], axis=0)))


pair, cross = {}, []
for cid in C:
    if "_reality" not in cid:
        continue
    k = cid.split("_")[0]
    if f"{k}_fantasy" in C:
        pair[cid] = round(sim(f"{k}_fantasy", cid), 3)
    cross += [sim(f, cid) for f in C if f.endswith("_fantasy") and not f.startswith(k + "_")]
print(json.dumps({"pair": pair, "cross_theme_mean": round(float(np.mean(cross)), 3) if cross else None}))
