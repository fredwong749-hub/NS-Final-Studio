"""HOLLYWOOD（项目方 11-01 模板，K-WRT-H01–H03）：模板接入点、不变量、解析格式。不调网关、不花钱。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def H():
    spec = importlib.util.spec_from_file_location("hollywood", ROOT / "tools" / "script_rsi" / "hollywood.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def ep01(H):
    text, _ = H.RC.assemble(H.RL, [1], H.RC.episode_sources())
    pre, chunks = H.RL.split_doc(text)
    return pre, chunks[0]


def test_k_wrt_h01_template_verbatim_and_source():
    w = (ROOT / "config/prompts/hollywood_writer.md").read_text(encoding="utf-8")
    j = (ROOT / "config/prompts/hollywood_judge.md").read_text(encoding="utf-8")
    for s in ("项目方 2026-11-01", "第一步：盘点 config，不要猜", "第二步：用好莱坞方法重写，不要直接润色原句",
              "第三步：RSI 迭代（生成 → 打分 → 只改不及格项 → 再打分）", "红线：不改给定的剧情事实和人物设定"):
        assert s in w, s
    for s in ("项目方 2026-11-01", "量表 10 项，每项 1–5 分", "保留得分最高的版本，不默认用最后一版"):
        assert s in j, s
    assert (ROOT / "config/prompts/hollywood_pika_reference.md").exists()
    assert "docs/video_rca/RCA_r1.md" in (ROOT / "config/prompts/hollywood_pika_reference.md").read_text(encoding="utf-8")


def test_k_wrt_h02_judge_keys_match_dims(H):
    j = (ROOT / "config/prompts/hollywood_judge.md").read_text(encoding="utf-8")
    assert len(H.DIMS) == 10
    for k, _ in H.DIMS:
        assert f'"{k}"' in j, k
    # 项目方 22:1x“达到95分,继续迭代”：≥48/50 且无 <4 项；最多 8 轮
    assert (H.PASS_SCORE, H.MAX_ROUNDS, H.TARGET_SUM, H.FIX_BELOW) == (4, 8, 47.5, 5)
    mk = lambda xs: {"scores": {k: {"score": x, "shots": [], "why": ""} for (k, _), x in zip(H.DIMS, xs)}}  # noqa: E731
    assert H.reached(mk([5] * 8 + [4] * 2)) and not H.reached(mk([5] * 7 + [4] * 3)) and not H.reached(mk([5] * 9 + [3]))


def test_beats_to_duration_only_timecode(H):
    blk = "**分拍**：0–2秒｜甲｜视线=桌面；2–5秒｜乙｜视线=窗外\n**时长**：6秒"
    nb, rec = H.beats_to_duration(blk, 6)
    assert rec and "2–6秒｜乙｜视线=窗外" in nb and nb.replace("2–6秒", "2–5秒") == blk
    assert H.beats_to_duration(nb, 6)[1] == ""


def test_k_wrt_h03_duration_window_60_120_and_plan(H, ep01, tmp_path):
    # 项目方 11-01 21:4x 选“改成 60–120 秒”（D-SCR-08）；6 秒一镜，镜数按 D-SCR-06
    assert H.DUR_WINDOW == (60, 120) and H.SHOT_S == 6 and H.MIN_SHOTS == 10
    pre, orig = ep01
    obj = H.episode_obj(pre, orig, 1, tmp_path)
    dp = H.duration_plan(obj)
    assert 60 <= dp["total"] <= 120 and dp["n"] >= max(10, len(obj.shots))
    from ns_agent.importer.script_md import shot_cap
    assert dp["n"] <= max(8, H._turns_mono(obj), -(-dp["total"] // 6))
    assert shot_cap  # 公式同源


def _before_exception(H, chunk, ep):
    """CODE-RSI 11-01（K-OPS-C02）：23:21 HOLLYWOOD 10 集已导入，现行剧本 ep01 集头已经是例外替换后的“深灰铅笔裙”。
    按 HEAD_EXCEPTIONS 把替换反做回去，得到导入前原稿，测试不再依赖真实剧本处在哪个状态"""
    head = H.RL.block_text(chunk, "head")
    lines = head.split("\n")
    for mark, old, rep in H.HEAD_EXCEPTIONS.get(ep, []):
        for i, ln in enumerate(lines):
            if ln.startswith(mark) and rep in ln and old not in ln:
                lines[i] = ln.replace(rep, old)
    back = "\n".join(lines)
    return H.RL.splice(chunk, "head", back) if back != head else chunk


def test_head_exception_pencil_skirt_only(H, ep01):
    pre, cur = ep01
    orig = _before_exception(H, cur, 1)
    new, done = H.apply_head_exceptions(orig, 1)
    assert done and "深灰铅笔裙" in H.RL.block_text(new, "head")
    a, b = H.RL.block_text(orig, "head").splitlines(), H.RL.block_text(new, "head").splitlines()
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(diff) == 1 and diff[0][0].startswith("**造型｜林晚**")
    assert H.RL.split_doc(pre + new)[1][0].count("**镜") == orig.count("**镜")   # 镜头不动
    assert H.apply_head_exceptions(orig, 2)[1] == []


def test_parse_scores_and_full(H):
    raw = "```json\n" + json.dumps({"scores": {k: {"score": 4, "shots": [], "why": ""} for k, _ in H.DIMS}, "note": "x"}) + "\n```"
    sc, err = H.parse_scores(raw)
    assert not err and H._sum(sc) == 40
    bad = raw.replace('"score": 4', '"score": 7', 1)
    assert H.parse_scores(bad)[0] is None


def test_gate_identity_and_dialogue_change(H, ep01, tmp_path, monkeypatch):
    import p4_adapter
    monkeypatch.setattr(p4_adapter, "TMP", tmp_path)
    pre, orig = ep01
    base = H.lint(orig, 1)
    g = H.gate(pre, orig, orig, 1, base, tmp_path)
    ok = {c["id"]: c["ok"] for c in g["checks"]}
    assert ok["I1"] and ok["I2"] and ok["I3"] and ok["I4"] and ok["I6"]
    # 改一个字的台词 → I1 不过
    seq = H.FR.dialogue_seq(H.episode_obj(pre, orig, 1, tmp_path))
    line = next(x for x in seq if not x.startswith("🎙")).split("|", 1)[1]
    g2 = H.gate(pre, orig, orig.replace(line, line[:-1] + "X", 1), 1, base, tmp_path)
    assert not {c["id"]: c["ok"] for c in g2["checks"]}["I1"]


def test_consistency_lock_is_card_verbatim(H, ep01):
    pre, orig = ep01
    lock = H.consistency_lock(pre, orig, ["林晚"])
    head = H.RL.block_text(orig, "head")
    look = next(ln for ln in head.splitlines() if ln.startswith("**造型｜林晚**")).split("：", 1)[1]
    assert look in lock
    assert next(ln.strip() for ln in pre.splitlines() if ln.strip().startswith("【林晚】")) in lock


def test_partial_reply_keeps_shot_count(H, ep01):
    pre, orig = ep01
    blk = H.RL.block_text(orig, 0)
    plan, bmap, err = H.parse_partial('```json\n{"shots": []}\n```\n\n' + blk, 9)
    assert not err and list(bmap) == [1]
    _, _, err2 = H.parse_partial('```json\n{}\n```\n\n' + blk.replace("**镜1｜img**", "**镜12｜img**", 1), 9)
    assert err2


def test_free_dialogue_i1_report_only(H, ep01, tmp_path, monkeypatch):
    """项目方 11-02 选“允许改台词，出审片页”：--free-dialogue 下台词改动只记录（I1 report_only），不作废、不进写作方的校验说明"""
    import p4_adapter
    monkeypatch.setattr(p4_adapter, "TMP", tmp_path)
    pre, orig = ep01
    base = H.lint(orig, 1)
    line = H.FR.dialogue_seq(H.episode_obj(pre, orig, 1, tmp_path))[0].split("|", 1)[1]
    cand = orig.replace(line, line.rstrip("。！？") + "，听见没有。", 1)
    try:
        H.FREE_DIALOGUE[0] = False
        g = H.gate(pre, orig, cand, 1, base, tmp_path)
        assert not next(c for c in g["checks"] if c["id"] == "I1")["ok"] and not g["ok"]
        H.FREE_DIALOGUE[0] = True
        g = H.gate(pre, orig, cand, 1, base, tmp_path)
        i1 = next(c for c in g["checks"] if c["id"] == "I1")
        assert i1["report_only"] and not i1["ok"] and "听见没有" in i1["detail"]
        assert "I1" not in H.gate_note(g)
        assert "已放开台词冻结" in H.constraints_text(H.episode_obj(pre, orig, 1, tmp_path), base)
    finally:
        H.FREE_DIALOGUE[0] = False
