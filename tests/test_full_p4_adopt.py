"""K211-F 11-03（总调度裁定 B / L-150）：整集返修稿收稿后就是唯一事实来源——
adopt_full_p4：旧 P4 / final 留档、新稿成 canon、补丁状态清零、patch_base 重置、未交稿补丁作废；chain_step 与 intake_full_p4 共用；
intake_full_p4：补丁环进行中的整集稿先缓着（full_p4_deferred），补丁处理完下一拍收，不再丢；
requeue_full_p4 / reopened：daemon 对 reopened 自动推进（autoflow.pending_done）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/recipes",):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


AG = _load("autoflow_agent_adopt_t", "tools/script_rsi/autoflow_agent.py")
AF = AG.AF


class Rep:
    def __init__(self, ok=False, blocking=1):
        self.ok, self._b, self.issues, self.hard_blocks = ok, blocking, [], []

    def as_dict(self):
        return {"blocking": self._b, "issues": []}


def _run(tmp_path: Path, packets: int, done: tuple = ()) -> Path:
    rd = tmp_path / "series10_t"
    (rd / "writer_tasks").mkdir(parents=True)
    (rd / "writer_out").mkdir()
    for i in range(1, packets + 1):
        (rd / "writer_tasks" / f"patch_ep01_a{i}.json").write_text("{}", encoding="utf-8")
        if i in done:
            (rd / "writer_out" / f"patch_ep01_a{i}.json").write_text("{}", encoding="utf-8")
            (rd / "writer_out" / f"patch_ep01_a{i}.json.done").write_text("ok", encoding="utf-8")
    (rd / "P4_ep01.md").write_text("OLD P4", encoding="utf-8")
    (rd / "P4_ep01.final.md").write_text("OLD FINAL", encoding="utf-8")
    return rd


def test_adopt_full_p4_single_source_and_budget_reset(tmp_path, monkeypatch):
    rd = _run(tmp_path, 12, done=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))      # a12 还没交稿
    monkeypatch.setenv("NSFS_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setattr(AG, "ROOT", tmp_path)                            # void_request 的隔离区落在临时目录
    st = AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": ["patch_ep01_a1"], "used": {"v3#1": 2}, "fact_devs": [], "full_p4_done": ["P4_ep01_a4.md"],
                     "camera_queue": [{"shot": 2}], "duration_queue": []}
    st.save()
    out = AG.adopt_full_p4(rd, 1, st, "NEW P4", Rep(ok=False, blocking=1), rd / "writer_out" / "P4_ep01_a4.md", "整集稿收为正式 P4（阻断 1）")
    assert (rd / "P4_ep01.md").read_text(encoding="utf-8") == "NEW P4"
    assert not (rd / "P4_ep01.final.md").exists()                                                   # 旧 final 不再是第二个事实来源
    assert (rd / f"P4_ep01.v{out['tag']}.md").read_text(encoding="utf-8") == "OLD P4"
    assert (rd / f"P4_ep01.final.v{out['tag']}.md").read_text(encoding="utf-8") == "OLD FINAL"       # 留档不删
    rep = json.loads((rd / "P4_ep01.md.report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "needs_writer" and rep["source"].endswith("P4_ep01_a4.md") and (rd / "P4_ep01.md.v2").exists()
    # 未交稿的 a12 作废（.void + 包移走），已交稿的 11 个记为已处理；预算基线 = 剩余包数，用量 0
    assert out["voided"] == ["patch_ep01_a12"] and (tmp_path / "inbox" / "requests" / "series10_t__patch_ep01_a12.void").exists()
    assert not (rd / "writer_tasks" / "patch_ep01_a12.json").exists()
    ag = json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))["agent"]
    assert ag["processed"] == [f"patch_ep01_a{i}" for i in range(1, 10)] + ["patch_ep01_a10", "patch_ep01_a11"] or len(ag["processed"]) == 11
    assert ag["used"] == {} and ag["fact_devs"] is None and ag["patch_base"] == 11 == out["patch_base"]
    assert AG.patch_budget_used(rd, 1, ag) == 0
    assert ag["full_p4_done"] == ["P4_ep01_a4.md"] and ag["camera_queue"] == [{"shot": 2}]          # 收稿记录 / 排队的运镜包不丢
    assert st.d["agent_history"][-1]["accepted"] is True and "基线 11" in st.d["agent_history"][-1]["note"]


def _fake_rch(ok=False, blocking=1):
    return SimpleNamespace(validate=lambda link, text, ctx: (Rep(ok, blocking), "OBJ:" + text.strip(), ""))


def test_intake_defers_while_patch_pending_then_adopts(tmp_path, monkeypatch):
    rd = _run(tmp_path, 1)                                      # a1 出了包、没交稿 → 补丁环进行中
    (rd / "writer_out" / "P4_ep01_a4.md").write_text("## ep01 NEW", encoding="utf-8")
    (rd / "writer_out" / "P4_ep01_a4.md.done").write_text("ok", encoding="utf-8")
    monkeypatch.setenv("NSFS_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setattr(AG, "ROOT", tmp_path)
    monkeypatch.setattr(AG, "l141_fix", lambda *a, **k: None)
    monkeypatch.setattr(AG, "segment_fix", lambda *a, **k: None)
    monkeypatch.setattr(AG, "mark_dirty", lambda *a, **k: None)
    real_load = AG._load
    monkeypatch.setattr(AG, "_load", lambda n, r: SimpleNamespace(enabled=lambda rd_: False) if n == "owner_gate" else real_load(n, r))
    import ns_recipes.spec_import as SI
    monkeypatch.setattr(SI, "stamp", lambda obj, v: f"STAMPED {obj}")
    st = AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": {}, "fact_devs": None}
    st.save()
    ctx = {"screenplay": {"scenes": []}}
    AG.intake_full_p4(_fake_rch(), rd, 1, st, ctx)
    ag = st.d["agent"]
    assert ag["full_p4_deferred"] == ["P4_ep01_a4.md"] and ag.get("full_p4_done", []) == []           # 缓着，不是丢掉
    assert st.d["agent_history"][-1]["accepted"] is None and "先缓着" in st.d["agent_history"][-1]["note"]
    assert (rd / "P4_ep01.final.md").read_text(encoding="utf-8") == "OLD FINAL"
    AG.intake_full_p4(_fake_rch(), rd, 1, st, ctx)                                                   # 再来一拍：不重复记历史
    assert sum(1 for h in st.d["agent_history"] if h["step"] == "P4_ep01_a4.md") == 1
    # 补丁 a1 交了稿、处理完了 → 下一拍正规收稿（已交稿的包记为已处理、不作废）
    (rd / "writer_out" / "patch_ep01_a1.json").write_text("{}", encoding="utf-8")
    (rd / "writer_out" / "patch_ep01_a1.json.done").write_text("ok", encoding="utf-8")
    st.d["agent"]["processed"] = ["patch_ep01_a1"]
    AG.intake_full_p4(_fake_rch(), rd, 1, st, ctx)
    ag = st.d["agent"]
    assert ag["full_p4_done"] == ["P4_ep01_a4.md"] and ag["full_p4_deferred"] == []
    assert (rd / "P4_ep01.md").read_text(encoding="utf-8") == "STAMPED OBJ:## ep01 NEW" and not (rd / "P4_ep01.final.md").exists()
    assert ag["patch_base"] == 1 and ag["processed"] == ["patch_ep01_a1"] and ag["used"] == {}
    assert st.d["agent_history"][-1]["accepted"] is True and "整集稿收为正式 P4" in st.d["agent_history"][-1]["note"]


def test_intake_rejects_hard_blocked_draft(tmp_path, monkeypatch):
    rd = _run(tmp_path, 0)
    (rd / "writer_out" / "P4_ep01_a5.md").write_text("## ep01 BAD", encoding="utf-8")
    (rd / "writer_out" / "P4_ep01_a5.md.done").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(AG, "l141_fix", lambda *a, **k: None)
    monkeypatch.setattr(AG, "segment_fix", lambda *a, **k: None)
    st = AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": {}, "fact_devs": None}
    rep = Rep(ok=False, blocking=1)
    rep.hard_blocks = [{"rule_id": "QW-T1"}]                                                          # 单镜 >6 秒：non_tl_blocking = 99
    rch = SimpleNamespace(validate=lambda link, text, ctx: (rep, "OBJ", ""))
    AG.intake_full_p4(rch, rd, 1, st, {"screenplay": {}})
    assert (rd / "P4_ep01.md").read_text(encoding="utf-8") == "OLD P4" and st.d["agent_history"][-1]["accepted"] is False


def test_requeue_sets_reopened_and_daemon_picks_it(tmp_path):
    rd = _run(tmp_path, 0)
    st = AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": {}, "fact_devs": None, "full_p4_done": ["P4_ep01_a4.md"]}
    st.set(verdict="awaiting_writer", awaiting={"output": "nowhere/x.json"})
    assert AF.pending_done(rd) == []                                                                 # 等写手、没 .done：不推进
    assert AG.requeue_full_p4(rd, 1, "P4_ep01_a9.md", "x")["ok"] is False
    out = AG.requeue_full_p4(rd, 1, "P4_ep01_a4.md", "总调度裁定 B", by="K211-F")
    d = json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))
    assert out["ok"] and d["agent"]["full_p4_done"] == [] and d["verdict"] == "reopened" and d["agent_history"][-1]["manual"]
    assert AF.pending_done(rd) == [1]                                                                # reopened = 可推进，下一拍自动接手
    AG.reopen(rd, 1, "预算重开", by="K211-F")
    assert AF.pending_done(rd) == [1]
    st2 = AF.Status(rd, 1, 0.0)
    st2.set(verdict="not_importable")
    assert AF.pending_done(rd) == []                                                                 # 终态不空转


def test_chain_step_and_intake_share_adopt():
    src = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    chain = src.split("def chain_step(")[1].split("\ndef ")[0]
    intake = src.split("def intake_full_p4(")[1].split("\ndef ")[0]
    assert "adopt_full_p4(run_dir, ep, st, stamp(obj, rules_version())" in chain and "canon.write_text(stamp(" not in chain
    assert "adopt_full_p4(run_dir, ep, st, stamp(obj, rules_version()), rep, q" in intake and "old.rename(" not in intake
    assert "full_p4_deferred" in intake
    # REVIEW-A P1①：chain_step 第一分支不再信旧 report.json 的 blocking≤6（会绕过 hard_blocks），只按现行规则重验
    assert 'pr_.get("status") == "needs_writer"' not in chain and "if patchable_p4(RCH, canon, ctx):" in chain
