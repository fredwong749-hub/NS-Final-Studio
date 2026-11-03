"""K211-F 11-03，REVIEW-A sv-17 复核项：
P0 I6 / I2 / F1 基线 = 当前已采用的稿（cur），hard 口径单一来源 hollywood_r5.hard_checks；
P1② 写作规则正文按 L-141 不再教镜内 At 时间码；
P1③ autoflow run 同一错误连续 3 次 → report_issue + halted_error 停重试；v1_guard 常用词只在另有 V1 专名时才算命中；
P1⑤ PATCH_MAX 两处分支都走 patch_exhausted（见 tests/test_patch_exhaust.py::test_post_step_calls_exhausted_not_bare_set）。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_p0_i6_baseline_is_current_draft():
    src = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    post = src.split("def post_step(")[1].split("\ndef ")[0]
    assert "base_lint = H.lint(base, ep)" not in post                       # 不再拿原始 P4_epNN.md 当基线
    assert "base_lint = H.lint(cur, ep)" in post and "R5.gate5(pre, cur, c, ep, base_lint, wd)" in post
    assert "hard = R5.hard_checks(g)" in post and 'x["id"] != "I7"]' not in post


def test_p0_hard_checks_single_definition():
    R5 = _load("hollywood_r5_t", "tools/script_rsi/hollywood_r5.py")
    g = {"checks": [{"id": "I2", "ok": False}, {"id": "I6", "ok": False}, {"id": "I7", "ok": False}, {"id": "W11", "ok": False},
                    {"id": "I8", "ok": False, "report_only": True}, {"id": "F1", "ok": True}]}
    assert [x["id"] for x in R5.hard_checks(g)] == ["I2", "I6", "W11"]                        # 补丁环：I6 / W11 是硬的，I7 / I8 只报告
    assert [x["id"] for x in R5.hard_checks(g, auto_fixable=("I6", "W11"))] == ["I2"]        # r5 轮回：I6 / W11 先交 format_repair
    src = (ROOT / "tools/script_rsi/hollywood_r5.py").read_text(encoding="utf-8")
    assert 'x["id"] not in ("I6", "I7", "W11")' not in src and 'hard_checks(g, auto_fixable=("I6", "W11"))' in src


def test_p1_2_rules_text_follows_l141():
    rules = (ROOT / "config/script_chat_rules.md").read_text(encoding="utf-8")
    app = (ROOT / "config/script_chat_rules_appendix.md").read_text(encoding="utf-8")
    assert "从第二拍起每拍以 `At 00:SS.mmm,` 开头" not in rules and "镜内不写 `At 00:SS.mmm,` 时间码" in rules
    assert "In the first two seconds," in rules and "Then, around the <序数> second," in rules and "as the shot ends" in rules
    assert "第一个 `At 00:0x` 之前" not in app and "镜内不用 `At 00:0x` 时间码" in app
    assert "At 00:SS.mmm," in rules                                                            # 切镜仍用 At（tests/test_prompt_timeline_v2 也靠这一句）


def test_p1_3_same_error_three_times_halts_and_reports(tmp_path, monkeypatch):
    AF = _load("autoflow_err_t", "tools/script_rsi/autoflow.py")
    RI = _load("report_issue_err_t", "tools/master/report_issue.py")
    issues, live = tmp_path / "issues.jsonl", tmp_path / "live.md"
    live.write_text("# live\n", encoding="utf-8")
    monkeypatch.setattr(RI, "ISSUES", issues)
    monkeypatch.setattr(RI, "LIVE", live)
    monkeypatch.setattr(AF, "_load", lambda n, r: RI if n == "report_issue" else _load(n, r))
    rd = tmp_path / "series10_t"
    rd.mkdir()
    st = AF.Status(rd, 2, 0.0)
    st.set(verdict="awaiting_writer", awaiting={"output": "x/P4_ep02_a1.md"})
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "P4_ep02_a1.md.done").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(AF, "ROOT", tmp_path)
    assert AF.pending_done(rd) == [2]
    err = RuntimeError("剧 series10_t 的P4_ep02 作业包里有旧剧内容：顾沉")
    for i in (1, 2):
        r = AF.record_run_error(rd, 2, err)
        assert r["count"] == i and r["issue"] is None and not issues.exists()
    r = AF.record_run_error(rd, 2, err)
    assert r["count"] == 3 and r["issue"].startswith("ISS-")
    recs = [json.loads(x) for x in issues.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["blocking"] and "顾沉" in recs[0]["what"] and recs[0]["episode"] == 2
    d = json.loads((rd / "autoflow_ep02.json").read_text(encoding="utf-8"))
    assert d["verdict"] == "halted_error" and recs[0]["id"] in d["next_action"]
    assert AF.pending_done(rd) == []                                                           # daemon 不再空转
    AF.record_run_error(rd, 2, err)                                                           # 第 4 次：不重复登记
    assert len(issues.read_text(encoding="utf-8").splitlines()) == 1
    AF.record_run_error(rd, 2, ValueError("别的错"))                                          # 换了错误 → 计数从 1 起
    assert json.loads((rd / "autoflow_ep02.json").read_text(encoding="utf-8"))["run_error"]["count"] == 1
    AF.clear_run_error(rd, 2)
    assert "run_error" not in json.loads((rd / "autoflow_ep02.json").read_text(encoding="utf-8"))
    src = (ROOT / "tools/script_rsi/autoflow.py").read_text(encoding="utf-8")
    assert "record_run_error(run_dir, a.episode, e)" in src and "clear_run_error(run_dir, a.episode)" in src


def test_p1_3_weak_props_need_a_v1_name():
    import sys
    if str(ROOT / "services/api") not in sys.path:
        sys.path.insert(0, str(ROOT / "services/api"))
    from ns_api import script_chat as S
    g = json.loads((ROOT / "config/v1_guard.json").read_text(encoding="utf-8"))
    weak = g["weak_props"]["items"]
    assert set(weak) == {"图纸", "名单", "验收", "老公"} and not set(weak) & set(g["props"])
    V2 = "series10_v2"
    assert S.v1_hits("卓琳把名单拍在桌上，让她验收图纸；她叫了一声老公", V2) == []            # 常用词单独出现放行
    hits = S.v1_hits("林晚把名单拍在桌上", V2)
    assert "林晚" in hits and "名单" in hits                                                   # 有 V1 专名时弱词一并报出
    assert "门卡" in S.v1_hits("她刷了门卡", V2)                                               # 强道具词照旧
