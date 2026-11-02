"""DETECT-S 标注回归集：data/vqa/regression_anomaly/labeled.json（总调度 11-02 人工标注的真问题 / 误报，带测量值和 cast）。
true_issue 必须判出该缺陷，false_positive 必须不判。改阈值后离线重判，不连远端。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.vqa import anomaly as A  # noqa: E402

FX = json.loads((ROOT / "data" / "vqa" / "regression_anomaly" / "labeled.json").read_text(encoding="utf-8"))
CASES = [(k, code, v["label"]) for k, e in FX.items() for code, v in e["labels"].items()]


@pytest.mark.parametrize("key,code,label", CASES, ids=[f"{k}:{c}:{lab}" for k, c, lab in CASES])
def test_labeled(key, code, label):
    r = A.judge(FX[key]["feat"], FX[key]["cast"])
    got = {d["code"] for d in r["defects"] if d["conf"] != "low"}
    assert (code in got) == (label == "true_issue"), f"{key} {code} 标 {label}，检测器给 {sorted(got)}"
