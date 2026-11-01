"""HOLLYWOOD r5（D-SCR-09 / L-096 / L-097，K-WRT-H04–H05）：剧情事实不变量（代码部分）、清单评审解析、回复整集 / 部分判定。不调网关。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def R():
    spec = importlib.util.spec_from_file_location("hollywood_r5", ROOT / "tools" / "script_rsi" / "hollywood_r5.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def ep04(R):
    text, _ = R.RC.assemble(R.RL, [4], R.RC.episode_sources())
    pre, chunks = R.RL.split_doc(text)
    return pre, chunks[0]


def test_rubric_is_checklist_5x10(R):
    d = json.loads(R.RUBRIC_JSON.read_text(encoding="utf-8"))
    assert sorted(d) == sorted(k for k, _ in R.H.DIMS)
    assert all(len(v) == 5 for v in d.values())
    j = R.H.JUDGE_MD.read_text(encoding="utf-8")
    assert "## 三、可核对清单" in j and "## 五、刁钻评审" in j and "原有标准" not in j.split("## 三、")[0][-1:]


def test_parse_checklist_counts_met_and_never_loosens(R):
    ch = {k: {"met": [1, 2, 3, 4, 5], "unmet": []} for k, _ in R.H.DIMS}
    ch["hook5s"] = {"met": [1, 2, 3, 4], "unmet": [{"id": 4, "shots": [1], "why": "x"}]}   # 4 既 met 又 unmet → 不满足
    ch["turns"] = {"met": [1, 2], "unmet": []}                                              # 3–5 没给 → 不满足
    sc, err = R.parse_checklist("```json\n" + json.dumps({"checks": ch}) + "\n```")
    assert not err
    assert sc["scores"]["hook5s"]["score"] == 3 and sc["scores"]["turns"]["score"] == 2
    assert R.H._sum(sc) == 45


def test_gate5_speaker_order_code_check(R, ep04, tmp_path, monkeypatch):
    import p4_adapter
    monkeypatch.setattr(p4_adapter, "TMP", tmp_path)
    pre, orig = ep04
    R.H.ZERO_CODES[:] = ["QW-W11"]
    base = R.H.lint(orig, 4)
    g = R.gate5(pre, orig, orig, 4, base, tmp_path)
    ok = {c["id"]: c["ok"] for c in g["checks"]}
    assert ok["F1"] and "I1" not in ok                      # r5：I1 台词逐字 → F1 说话人顺序 + F2 事实核对
    obj = R.H.episode_obj(pre, orig, 4, tmp_path)
    seq = R.speaker_seq(obj)
    assert seq and all(isinstance(x, str) for x in seq)


def test_apply_reply_full_vs_partial(R, ep04):
    pre, orig = ep04
    blk = R.RL.block_text(orig, 0)
    c, p, chg, err = R.apply_reply('```json\n{"shots": []}\n```\n\n' + blk, orig, orig, 9, {})
    assert not err and chg == [1]                            # 只给镜1 → 部分镜
    allb = "\n\n".join(R.RL.block_text(orig, k) for k in range(9))
    c, p, chg, err = R.apply_reply('```json\n{"logline": "x", "shots": []}\n```\n\n' + allb, orig, orig, 9, {})
    assert not err and chg == "全集"


def test_d_scr_09_recorded():
    od = (ROOT / "config/owner_decisions.yaml").read_text(encoding="utf-8")
    mp = (ROOT / "docs/master/MASTER_PICTURE.md").read_text(encoding="utf-8")
    assert "id: D-SCR-09" in od and "| L-096 |" in mp and "| L-097 |" in mp
    assert "50 over 50" in mp
