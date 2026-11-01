"""RSI 线 3 打分器（tools/script_rsi/line3_score.py，L-112）：权重、分项口径、写 scores.jsonl 的字段。不调网关。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def L3():
    spec = importlib.util.spec_from_file_location("line3_score", ROOT / "tools" / "script_rsi" / "line3_score.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_weights_match_rsi_program(L3):
    assert L3.WEIGHTS == {"script": 35, "shot_block": 20, "shootable": 20, "structure": 15, "automation": 10}
    assert sum(L3.WEIGHTS.values()) == 100
    t = (ROOT / "docs/master/RSI_PROGRAM.md").read_text(encoding="utf-8")
    assert "线 3" in t and "| 剧本分（新尺子） | 35 |" in t


def test_automation_counts_only_unattended_importable(L3, tmp_path):
    (tmp_path / "autoflow_ep01.json").write_text(json.dumps({"episode": 1, "verdict": "importable", "agent_history": []}), encoding="utf-8")
    (tmp_path / "autoflow_ep02.json").write_text(json.dumps({"episode": 2, "verdict": "importable",
                                                             "agent_history": [{"note": "manual fix"}]}), encoding="utf-8")
    (tmp_path / "autoflow_ep03.json").write_text(json.dumps({"episode": 3, "verdict": "not_importable"}), encoding="utf-8")
    pts, eps = L3.automation(tmp_path)
    assert eps == [1] and pts == 1.0


def test_lens_names_from_director_vocab(L3):
    names = L3.lens_names()
    if (ROOT / "config/director/lenses.yaml").exists():
        assert names and any("50" in n for n in names)


def test_k_wrt_h13_shootable_single_source():
    """导入闸门、打分器、补丁环都调同一个 shootable.py（单一来源）"""
    gate = (ROOT / "tools/script_rsi/rubric_audit.py").read_text(encoding="utf-8")
    score = (ROOT / "tools/script_rsi/line3_score.py").read_text(encoding="utf-8")
    flow = (ROOT / "tools/script_rsi/autoflow.py").read_text(encoding="utf-8")
    for t in (gate, score, flow):
        assert "tools/script_rsi/shootable.py" in t
    import importlib.util as iu
    spec = iu.spec_from_file_location("shootable", ROOT / "tools/script_rsi/shootable.py")
    SH = iu.module_from_spec(spec)
    spec.loader.exec_module(SH)
    w = SH.why({"lost": ["阿岚"], "misowned": [], "clash": "特写脸占六成 + 两张脸都清晰入画"})
    assert "K-REN-901" in w and "K-REN-902" in w
