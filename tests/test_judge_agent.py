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
    (rd / "P1_storyline.json").write_text('{"title": "t"}', encoding="utf-8")
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
