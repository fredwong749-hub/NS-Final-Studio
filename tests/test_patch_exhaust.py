"""K211-F 11-03：补丁环用满 PATCH_MAX / 剩余项全试满后不许静默停住——写诊断（work_epNN/patch_diag.json）、登记 report_issue 交总调度、
verdict not_importable；同一 k 只登记一次；reopen 记 patch_base 基线，重开后预算从 0 起算（之前按文件数算，重开第一拍又用满）。
series10_v2 ep01 实测：k211#2 一次都没出过包，预算被 v3#1 / cam#2 / 8 条 TL-* 耗完，系统只写了一句“交总调度”。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AG = _load("autoflow_agent_k211f", "tools/script_rsi/autoflow_agent.py")
RI = _load("report_issue_k211f", "tools/master/report_issue.py")


def _run(tmp_path: Path, packets: int) -> Path:
    rd = tmp_path / "series10_t"
    (rd / "writer_tasks").mkdir(parents=True)
    for i in range(1, packets + 1):
        (rd / "writer_tasks" / f"patch_ep01_a{i}.json").write_text("{}", encoding="utf-8")
    return rd


FAILS = [("k211", {"id": "2", "shots": [7], "why": "代码判定：≤8 秒镜手部动作超过 2 拍：['镜7（3 拍）']"}),
         ("p4", {"id": "TL-9", "shots": [9], "why": "ep01-S9.timeline：[TL-9] 镜9 时间轴不全"}),
         ("p4", {"id": "QW-T1", "shots": [6], "why": "ep01-S6：[QW-T1] 镜6 时长 7 秒"})]


def test_exhausted_writes_diag_and_reports_once(tmp_path, monkeypatch):
    rd = _run(tmp_path, AG.PATCH_MAX)
    issues, live = tmp_path / "issues.jsonl", tmp_path / "V2_LIVE.md"
    live.write_text("# live\n", encoding="utf-8")
    # patch_exhausted 用 _load 取 report_issue：把它换成本测试已载入、改了 ISSUES / LIVE 的那份
    monkeypatch.setattr(RI, "ISSUES", issues)
    monkeypatch.setattr(RI, "LIVE", live)
    monkeypatch.setattr(AG, "_load", lambda name, rel: RI if name == "report_issue" else _load(name, rel))
    st = AG.AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": {"v3#1": 2, "p4#TL-9": 2}, "fact_devs": None}
    # L-163：有没出过包的项会先自动重开（tests/test_auto_reopen.py）；这里测自动重开已用满之后的交总调度路径
    st.d["agent_history"] = [{"step": "auto_reopen", "fails": 9}] * AG.AUTO_REOPEN_MAX + [
                             {"step": "patch_ep01_a1", "accepted": False, "note": "I6 lint 每个码不比原稿多 不满足", "fails": 3},
                             {"step": "patch_ep01_a2", "accepted": True, "note": "", "fails": 3}]
    diag = AG.patch_exhausted(rd, 1, st, FAILS, AG.PATCH_MAX, "补丁已出 10 次仍有 3 项失败")
    # 诊断落盘，内容能让总调度直接定位
    p = rd / "work_ep01" / "patch_diag.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d == diag and d["never_targeted"] == ["k211#2", "p4#QW-T1"] and d["tried_out"] == ["p4#TL-9"]
    assert "p4#QW-T1" in d["structural"] and any("从没出过补丁包" in x for x in d["plan"]) and any("误判" in x for x in d["plan"])
    assert d["history"][0]["note"].startswith("I6") and any("I2 / I6" in x for x in d["plan"])
    # 卡点登记了一条（阻断，步骤 5 补丁环），V2_LIVE 有一行
    recs = [json.loads(x) for x in issues.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["blocking"] and recs[0]["step"] == "5" and "k211#2" in recs[0]["what"]
    assert "⚠ 卡点（autoflow 补丁环）" in live.read_text(encoding="utf-8")
    # 状态：not_importable + next_action 带卡点 id 和诊断路径
    s = json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))
    assert s["verdict"] == "not_importable" and recs[0]["id"] in s["next_action"] and "patch_diag.json" in s["next_action"]
    assert s["agent"]["exhausted_reports"][0]["issue"] == recs[0]["id"]
    assert any(h["step"] == "patch_ep01_exhausted" for h in s["agent_history"])
    # daemon 每 30 秒再跑一次：同一 k 不重复登记
    st2 = AG.AF.Status(rd, 1, 0.0)
    AG.patch_exhausted(rd, 1, st2, FAILS, AG.PATCH_MAX, "补丁已出 10 次仍有 3 项失败")
    assert len(issues.read_text(encoding="utf-8").splitlines()) == 1


def test_report_failure_does_not_crash_loop(tmp_path, monkeypatch):
    rd = _run(tmp_path, 3)
    monkeypatch.setattr(AG, "_load", lambda name, rel: (_ for _ in ()).throw(RuntimeError("no report_issue")))
    st = AG.AF.Status(rd, 1, 0.0)
    st.d["agent_history"] = [{"step": "auto_reopen", "fails": 9}] * AG.AUTO_REOPEN_MAX     # L-163 自动重开已用满
    AG.patch_exhausted(rd, 1, st, FAILS, 3, "试满")
    s = json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))
    assert s["verdict"] == "not_importable" and "登记失败" in s["next_action"] and (rd / "work_ep01" / "patch_diag.json").exists()


def test_reopen_resets_budget_baseline(tmp_path):
    rd = _run(tmp_path, AG.PATCH_MAX + 1)
    st = AG.AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": {"v3#1": 2}, "fact_devs": None}
    st.save()
    assert AG.patch_budget_used(rd, 1, st.d["agent"]) == AG.PATCH_MAX + 1 >= AG.PATCH_MAX
    out = AG.reopen(rd, 1, "K211-F 测试", by="K211-F")
    assert out["used_before"] == {"v3#1": 2} and out["patch_base"] == AG.PATCH_MAX + 1
    st2 = AG.AF.Status(rd, 1, 0.0)
    ag = st2.d["agent"]
    assert ag["used"] == {} and ag["patch_base"] == AG.PATCH_MAX + 1 and AG.patch_budget_used(rd, 1, ag) == 0
    assert st2.d["verdict"] == "reopened" and st2.d["agent_history"][-1]["step"] == "reopen"
    # 重开后再出 PATCH_MAX 个包才再次用满
    for i in range(AG.PATCH_MAX + 2, 2 * AG.PATCH_MAX + 2):
        (rd / "writer_tasks" / f"patch_ep01_a{i}.json").write_text("{}", encoding="utf-8")
    assert AG.patch_budget_used(rd, 1, ag) == AG.PATCH_MAX


def test_post_step_calls_exhausted_not_bare_set():
    src = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    assert "patch_budget_used(run_dir, ep, ag) >= PATCH_MAX" in src and src.count("patch_exhausted(run_dir, ep, st, fails, k,") == 2
    assert 'next_action=f"补丁已出 {k} 次仍有失败项，交总调度")' not in src
