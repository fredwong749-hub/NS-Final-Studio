"""判断类条目独立评审（tools/script_rsi/judge_agent.py）：50 分制逐份总分、3 次 σ ≤ 1 稳定性判定。不调网关。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def JA():
    spec = importlib.util.spec_from_file_location("judge_agent", ROOT / "tools" / "script_rsi" / "judge_agent.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_stability_needs_three_and_sigma_le_1(JA):
    assert JA.stability([40, 41, 40])["stable"]
    assert not JA.stability([40, 41])["stable"]                 # 不到 3 份
    assert not JA.stability([36, 40, 44])["stable"]             # σ ≈ 3.27


def test_rep_total_combines_code_and_judge(JA):
    dims = ["a", "b"]
    code = {"a": {1: (True, ""), 2: (False, "")}, "b": {}}
    llm = [("a", 3), ("b", 1), ("b", 2)]
    judged = {"a": {3: {"met": True}}, "b": {1: {"met": False}, 2: {"met": True}}}
    # a：1 过、2 代码不过、3 评审过、4/5 无判定按满足 → 4；b：1 评审不过、2 过、3–5 满足 → 4
    assert JA.rep_total(code, judged, llm, dims) == 8


def test_rules_v3_registered():
    t = (ROOT / "knowledge/rules/writer_hollywood.yaml").read_text(encoding="utf-8")
    assert all(f"id: K-WRT-H{n}" in t for n in range(17, 23))
    j = (ROOT / "config/prompts/hollywood_judge.md").read_text(encoding="utf-8")
    assert "## 七、v3 判断条目" in j and "judge_id" in j


def test_blind_pack_hides_version(JA, tmp_path):
    """盲评（总调度 11-02）：包里不出现版本标签和快照路径；每个评审 6 份、编号唯一；对照表另存在 _key/"""
    import json
    src = ROOT / "data" / "rsi" / "v2v3"
    if not ((src / "v2" / "P4_ep01.final.md").exists() and (src / "v3" / "P4_ep01.final.md").exists()):
        import pytest
        pytest.skip("没有 v2 / v3 快照")
    out = tmp_path / "blind"
    made = JA.blind_pack({"v2": src / "v2", "v3": src / "v3"}, [1, 2, 3], 3, out, seed=7)
    assert {k: len(v) for k, v in made.items()} == {"judge_1": 6, "judge_2": 6, "judge_3": 6}
    key = json.loads((JA._key_dir(out) / "KEY.json").read_text(encoding="utf-8"))
    assert len(key["packets"]) == 18
    for j in made:
        for pp in made[j]:
            pk = json.loads(JA._abs(pp).read_text(encoding="utf-8"))
            txt = json.dumps({k: v for k, v in pk.items() if k not in ("system", "user", "output")}, ensure_ascii=False)   # output 在 pytest 临时目录下，目录名含测试名
            assert "v2v3" not in pk["output"]["path"] and "_key" not in pk["output"]["path"]
            assert "v2v3" not in txt and '"v2"' not in txt and '"v3"' not in txt and "version" not in txt
    orders = [[key["packets"][JA._abs(p).stem.split("_", 1)[1]]["version"] + str(key["packets"][JA._abs(p).stem.split("_", 1)[1]]["episode"]) for p in made[j]] for j in made]
    assert len({tuple(o) for o in orders}) > 1          # 三个评审的顺序不全一样


def test_p1_pack_and_collect(JA, tmp_path):
    """P1 三评委（总调度 11-02 19:3x）：每家一份；8 条 1–5 分；无证据记 1 分；judge_id 去重；σ ≤ 1 才稳定"""
    import json
    rd = tmp_path / "run"
    rd.mkdir()
    (rd / "P1_storyline.json").write_text('{"title": "原文"}', encoding="utf-8")
    made = JA.p1_pack(rd, 3)
    assert len(made) == 3
    for j, base in zip((1, 2, 3), (4, 4, 5)):
        pk = json.loads(JA._abs(made[j - 1]).read_text(encoding="utf-8"))
        op = JA._abs(pk["output"]["path"])
        op.parent.mkdir(parents=True, exist_ok=True)
        items = [{"id": i, "score": base, "evidence": "原文"} for i in JA.P1_ITEMS]
        items[0]["evidence"] = "" if j == 3 else "原文"              # 无证据 → 1 分
        op.write_text("```json\n" + json.dumps({"judge_id": f"J{j}", "items": items}) + "\n```", encoding="utf-8")
        op.with_name(op.name + ".done").write_text("", encoding="utf-8")
    r = JA.p1_collect(rd)
    assert r["n"] == 3 and r["totals"] == [32, 32, 36] and not r["single_judge"] and "act3" in r["item_split"]



def _p1_run(JA, tmp_path, story: dict):
    import json
    rd = tmp_path / "run"
    rd.mkdir()
    (rd / "P1_storyline.json").write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
    made = JA.p1_pack(rd, 3)
    ops = [JA._abs(json.loads(JA._abs(m).read_text(encoding="utf-8"))["output"]["path"]) for m in made]
    return rd, ops


def _submit(op, judge_id, evs, score=5):
    import json
    op.parent.mkdir(parents=True, exist_ok=True)
    items = [{"id": i, "score": score, "evidence": e} for i, e in evs.items()]
    op.write_text(json.dumps({"judge_id": judge_id, "items": items}, ensure_ascii=False), encoding="utf-8")
    op.with_name(op.name + ".done").write_text("", encoding="utf-8")


def test_p1_evidence_normalized_substring_and_cap(JA, tmp_path):
    """总调度 11-02（r4-sonnet 事件）：证据必须是 P1 原文子串（空白、全半角、引号归一化后），≤60 字；不合格那条封顶 2 分，记 evidence_fail"""
    story = {"title": "透明高跟", "acts": [{"beat": "她在外滩系紧腰带，ABC 灯下像杂志封面。"}, {"beat": "天亮后“她”挡风回家"}]}
    rd, ops = _p1_run(JA, tmp_path, story)
    good = "她在外滩 系紧腰带，ＡＢＣ灯下"            # 多了空格、全角字母、全角逗号 → 归一化后仍是原文
    for j, op in enumerate(ops, 1):
        evs = {i: good for i in JA.P1_ITEMS}
        evs["arc"] = '天亮后"她"挡风回家'                # 引号换了种写法，仍算原文
        if j == 1:
            evs["act3"] = "她在外滩痛哭"                # 编的 → 封顶 2
            evs["men"] = "她在外滩系紧腰带" * 8         # 超过 60 字 → 封顶 2
        _submit(op, f"J{j}", evs)
    r = JA.p1_collect(rd)
    assert r["n"] == 3 and r["totals"] == [34, 40, 40]          # 6×5 + 2 + 2
    assert {(x["judge_slot"], x["id"]) for x in r["evidence_fail"]} == {("judge_1", "act3"), ("judge_1", "men")}
    assert any("超过 60" in x["why"] for x in r["evidence_fail"]) and r["invalid_judges"] == []
    import json
    assert json.loads((rd / "judge_p1" / "RESULT.json").read_text(encoding="utf-8"))["evidence_fail"]


def test_p1_evidence_over_3_invalid_then_recollect(JA, tmp_path):
    """一份评审证据不合格超过 3 条：整份无效、不计入均分、要求重交；重交后 .done 签名变了，能重新汇总"""
    import os
    import time
    AG = _agent()
    story = {"title": "透明高跟", "beat": "她在外滩系紧腰带"}
    rd, ops = _p1_run(JA, tmp_path, story)
    for j, op in enumerate(ops, 1):
        evs = {i: "她在外滩系紧腰带" for i in JA.P1_ITEMS}
        if j == 2:
            for i in JA.P1_ITEMS[:4]:
                evs[i] = "编出来的话"
        _submit(op, f"J{j}", evs)
    r = JA.p1_collect(rd)
    assert r["n"] == 2 and r["invalid_judges"] == ["judge_2"] and r["mean"] == 40
    assert any("judge_2 证据不合格 4 条" in p and "请重交" in p for p in r["problems"])
    sig1 = AG.judge_done_sig(rd / "judge_p1")
    time.sleep(0.02)
    _submit(ops[1], "J2", {i: "她在外滩系紧腰带" for i in JA.P1_ITEMS}, score=4)   # 重交（这里字节数同样可能不变）
    os.utime(ops[1], ns=(time.time_ns(), time.time_ns() + 10_000_000))
    assert AG.judge_done_sig(rd / "judge_p1") != sig1
    r = JA.p1_collect(rd)
    assert r["n"] == 3 and r["invalid_judges"] == [] and r["totals"] == [40, 32, 40]


def _agent():
    import importlib.util
    import sys
    sys.path.insert(0, str(ROOT / "tools" / "script_rsi"))
    spec = importlib.util.spec_from_file_location("autoflow_agent_t", ROOT / "tools" / "script_rsi" / "autoflow_agent.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
