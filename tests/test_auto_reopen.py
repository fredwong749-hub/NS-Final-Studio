"""L-163 auto_reopen：补丁预算被别的项耗尽 / 有项从没出过包 → daemon 自动重开预算（不清逐项计数）；
试满 / 只剩结构项 / 自动重开用满 / 没进展 → 照旧诊断 + 卡点交总调度"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


AG = _load("autoflow_agent_autoreopen_t", "tools/script_rsi/autoflow_agent.py")
AF = AG.AF
RI = _load("report_issue_autoreopen_t", "tools/master/report_issue.py")

TL = ("p4", {"id": "TL-3", "shots": [3], "why": "时间轴不全"})
CAM = ("p4", {"id": "QW-C2", "shots": [4], "why": "运镜写法"})
V2 = ("v2", {"id": 1, "shots": [5], "why": "代码判定：缺段：['镜5缺构图']；段顺序不对的镜：无"})


def _env(tmp_path, monkeypatch, packets=10):
    rd = tmp_path / "series10_t"
    for sub in ("writer_tasks", "writer_out"):
        (rd / sub).mkdir(parents=True)
    for i in range(1, packets + 1):
        (rd / "writer_tasks" / f"patch_ep01_a{i}.json").write_text("{}", encoding="utf-8")
    issues, live = tmp_path / "issues.jsonl", tmp_path / "V2_LIVE.md"
    live.write_text("# live\n", encoding="utf-8")
    monkeypatch.setattr(RI, "ISSUES", issues)
    monkeypatch.setattr(RI, "LIVE", live)
    real = AG._load
    monkeypatch.setattr(AG, "_load", lambda n, r: RI if n == "report_issue" else real(n, r))
    return rd, issues


def _st(rd, used):
    st = AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": dict(used), "fact_devs": None}
    st.save()
    return st


def _exhaust(rd, st, fails):
    return AG.patch_exhausted(rd, 1, st, fails, 10, "补丁已出 10 次（本轮预算 10）")


def test_never_targeted_item_auto_reopens_without_issue(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd, {"p4#TL-3": 2})                       # TL-3 试满；QW-C2 从没出过包（预算被耗光）
    d = _exhaust(rd, st, [TL, CAM])
    assert d["auto_reopen"]["eligible"] == ["p4#QW-C2"]
    assert st.d["verdict"] == "reopened" and AG.patch_budget_used(rd, 1, st.d["agent"]) == 0
    assert st.d["agent"]["used"] == {"p4#TL-3": 2}     # 逐项计数不清：试满的不会再派
    assert not issues.exists()                         # 不登记卡点、不交总调度
    assert st.d["agent_history"][-1]["step"] == "auto_reopen" and not st.d["agent_history"][-1].get("manual")


def test_all_tried_out_escalates(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd, {"p4#TL-3": 2, "p4#QW-C2": 2})
    d = _exhaust(rd, st, [TL, CAM])
    assert "auto_reopen" not in d and st.d["verdict"] == "not_importable" and issues.exists()


def test_only_structural_left_escalates(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd, {})
    d = _exhaust(rd, st, [V2])                         # 缺段 = 结构项，L-158 整集返修管，不自动重开补丁预算
    assert "auto_reopen" not in d and st.d["verdict"] == "not_importable"


def test_no_progress_or_cap_escalates(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd, {})
    assert _exhaust(rd, st, [TL, CAM]).get("auto_reopen")          # 第 1 次：2 项
    for i in range(11, 21):
        (rd / "writer_tasks" / f"patch_ep01_a{i}.json").write_text("{}", encoding="utf-8")
    d = _exhaust(rd, st, [TL, CAM])                                # 失败项没变少 → 不再自动
    assert "auto_reopen" not in d and st.d["verdict"] == "not_importable"


def test_cap_counts_since_last_manual_reopen(tmp_path, monkeypatch):
    rd, _ = _env(tmp_path, monkeypatch)
    st = _st(rd, {})
    st.d["agent_history"] = [{"step": "auto_reopen", "fails": 9}] * AG.AUTO_REOPEN_MAX
    st.save()
    assert "auto_reopen" not in _exhaust(rd, st, [TL])             # 已满 3 次
    AG.reopen(rd, 1, "人工", by="T")                              # 人工 reopen 后重新计数
    st2 = AF.Status(rd, 1, 0.0)
    assert _exhaust(rd, st2, [TL]).get("auto_reopen")
