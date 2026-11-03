"""V2 音色可分辨度检查（STYLE-V2，总调度 L-132 后：m3_c 的 f0 约 96 Hz，可能和 m1_b 撞音区）。只作提醒，不推翻项目方选择。

同一组台词（两个候选的 sample.wav 读的是同样两句）→ f0 中位数 / 四分位（librosa pyin）+ 说话人嵌入余弦相似度
（CAM++ campplus.onnx，CosyVoice3 自带的说话人编码器，gpu36 CPU）。同一音色基线 = 同一候选的 ref.wav 对 sample.wav（文字不同、声音相同）。

  python tools/v2style/voice_distinct.py [角色_候选 ...]     # 默认 m1_b m3_c，另附全部已选两两对照
输出：data/assets/voices_v2/distinct_check.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/v2style"))
import common as C  # noqa: E402

VCFG = ROOT / "config/voices_v2.json"
OUT = ROOT / "data/assets/voices_v2/distinct_check.json"

REMOTE = r'''
import json, sys, numpy as np, librosa, onnxruntime as ort, torch, torchaudio.compliance.kaldi as K
man = json.load(sys.stdin)
sess = ort.InferenceSession(man["model"], providers=["CPUExecutionProvider"])
out = {}
for name, path in man["files"].items():
    y, sr = librosa.load(path, sr=16000)
    f0, vf, _ = librosa.pyin(y, fmin=60, fmax=400, sr=16000)
    f0 = f0[~np.isnan(f0)]
    fb = K.fbank(torch.tensor(y)[None] * 32768, num_mel_bins=80, dither=0, sample_frequency=16000)
    fb = fb - fb.mean(0, keepdim=True)
    e = sess.run(None, {sess.get_inputs()[0].name: fb[None].numpy()})[0].flatten()
    out[name] = {"f0_med": float(np.median(f0)), "f0_p25": float(np.percentile(f0, 25)), "f0_p75": float(np.percentile(f0, 75)),
                 "emb": (e / np.linalg.norm(e)).tolist()}
print(json.dumps(out))
'''


def main(argv: list[str]) -> None:
    v = json.loads(VCFG.read_text(encoding="utf-8"))
    sel = {f"{r}_{c['cand']}": c for r, rr in v["roles"].items() for c in rr["candidates"] if c.get("selected")}
    focus = argv or ["m1_b", "m3_c"]
    d = C.cfg()["depth"]                      # 复用 gpu36 的工作目录 / venv_tts 解释器
    host, py, wd = d["host"], d["python"], d["work_dir"] + "/voice"
    model = C.cfg().get("speaker_model") or ""
    if not model:
        raise SystemExit("config/v2style.json 缺 speaker_model（campplus.onnx 在服务器上的路径）")
    files = {}
    C.remote(host, f"mkdir -p {wd}", timeout=120)
    for k, c in sel.items():
        for kind in ("sample", "ref"):
            local = ROOT / c["dir"] / f"{kind}.wav"
            rp = f"{wd}/{k}_{kind}.wav"
            C.remote(host, f"cat > {rp}", stdin=local.read_bytes(), timeout=600)
            files[f"{k}/{kind}"] = rp
    C.remote(host, f"cat > {wd}/distinct_remote.py", stdin=REMOTE.encode(), timeout=120)
    r = C.remote(host, f"OMP_NUM_THREADS=8 {py} {wd}/distinct_remote.py 2>/dev/null",
                 stdin=json.dumps({"model": model, "files": files}).encode(), timeout=1800)
    lines = [x for x in r.stdout.decode("utf-8", "replace").splitlines() if x.startswith("{")]
    if not lines:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-500:])
    feats = json.loads(lines[-1])

    import numpy as np
    cos = lambda a, b: float(np.dot(feats[a]["emb"], feats[b]["emb"]))  # noqa: E731
    same = {k: round(cos(f"{k}/ref", f"{k}/sample"), 3) for k in sel}
    keys = sorted(sel)
    pairs = {f"{a}~{b}": round(cos(f"{a}/sample", f"{b}/sample"), 3) for i, a in enumerate(keys) for b in keys[i + 1:]}
    f0 = {k: {x: round(feats[f"{k}/sample"][x], 1) for x in ("f0_med", "f0_p25", "f0_p75")} for k in sel}
    a, b = focus[0], focus[1]
    rep = {"method": "f0 = librosa pyin（60–400 Hz）；嵌入 = CAM++ campplus.onnx（CosyVoice3 自带），同一组台词的 sample.wav；"
                     "同一音色基线 = 各候选 ref.wav 对 sample.wav",
           "focus": f"{a}~{b}", "focus_cos": pairs.get(f"{a}~{b}") or pairs.get(f"{b}~{a}"),
           "focus_f0": {a: f0[a], b: f0[b]}, "same_voice_baseline": same, "pairs_cos": pairs, "f0": f0}
    C.save_json_atomic(OUT, rep)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
