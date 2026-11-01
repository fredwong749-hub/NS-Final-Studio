"""Q1 复核带清晰度阈值重算（总调度 11-02：每周一次，按标定集）。
标定集 = data/vqa/gate_calib/q1_band_review.json（总调度判过的 20 张：label 合格 / 不合格）
       + data/vqa/gate_calib/band_sharp_labels.json（之后人工或亲审补的标签：{crop: "合格"|"不合格"}，被清晰度拦下的
         自动进 band_sharp_auto.jsonl，待补标签）。
算法：合格最低值与不合格最高值的中点；两类重叠时取让“不合格 0 漏过”的最小值，并报误杀数。只写提议，不自动改代码阈值：
结果写 data/vqa/gate_calib/band_recalib.json，contract.BAND_SHARP_MIN 由 VQAGATE / 总调度按提议改（改动走 GATE_CALIBRATION）。
    .venv/Scripts/python.exe tools/vqa/band_recalib.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/agent"))
G = ROOT / "data/vqa/gate_calib"


def samples() -> list[tuple[float, str]]:
    from ns_agent.vqa import contract as VQ
    out = []
    base = G / "q1_band_review.json"
    if base.exists():
        for r in json.loads(base.read_text(encoding="utf-8")):
            crop = ROOT / "data/review_pages/q1_band" / r["crop"]
            if crop.exists():
                out.append((VQ.face_sharpness(crop), r["label"]))
    extra = G / "band_sharp_labels.json"
    if extra.exists():
        for crop, lab in json.loads(extra.read_text(encoding="utf-8")).items():
            if Path(crop).exists():
                out.append((VQ.face_sharpness(crop), lab))
    return out


def main() -> int:
    from ns_agent.vqa import contract as VQ
    s = samples()
    good = sorted(v for v, l in s if l == "合格")
    bad = sorted(v for v, l in s if l == "不合格")
    if not good or not bad:
        print("标定集正反例不全，不重算")
        return 1
    if bad[-1] < good[0]:
        th, fp = round((bad[-1] + good[0]) / 2, 1), 0
    else:
        th = round(bad[-1] + 0.1, 1)
        fp = sum(1 for v in good if v < th)
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_good": len(good), "n_bad": len(bad), "good_min": round(good[0], 1),
           "bad_max": round(bad[-1], 1), "proposed": th, "current": VQ.BAND_SHARP_MIN, "false_kill": fp,
           "pending_unlabeled": sum(1 for _ in open(VQ.BAND_CALIB, encoding="utf-8")) if VQ.BAND_CALIB.exists() else 0}
    import os
    tmp = G / "band_recalib.json.tmp"                  # 原子写（SYSARCH 11-02：闸门不会读到半个 JSON）
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, G / "band_recalib.json")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
