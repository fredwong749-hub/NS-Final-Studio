"""SENTINEL（K-OPS-S02…S07）：判定、工单去重 / 自动关单、探针故障、回放（夹具 tests/fixtures/sentinel/replay_20261102.json）。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.autopilot import policy  # noqa: E402
from tools.sentinel import judges as J  # noqa: E402
from tools.sentinel.store import IssueStore  # noqa: E402

C = {k: v["value"] for k, v in policy.load()["sentinel"].items()}
T0 = 1_793_550_000.0


# ------------------------------------------------------------------ 工单库
def test_store_dedup_and_resolve(tmp_path):
    st = IssueStore(tmp_path)
    bad = J.F("S2", "gpu33", True, "全空")
    r1 = st.apply([bad], T0, {"S2": "DEBUG-RSI"})
    r2 = st.apply([bad], T0 + 60, {"S2": "DEBUG-RSI"})
    assert len(r1["opened"]) == 1 and not r2["opened"]                   # 同一问题只开一张
    rec = r1["opened"][0]
    assert rec["decider"] == "code" and rec["owner_loop"] == "DEBUG-RSI" and rec["status"] == "open"
    assert {"id", "slo", "evidence", "first_seen", "owner_loop", "status"} <= set(rec)
    r3 = st.apply([J.F("S2", "gpu33", False, "恢复")], T0 + 180, {})
    assert r3["resolved"][0]["status"] == "resolved" and r3["resolved"][0]["resolved_at"] and r3["resolved"][0]["duration_s"] == 180
    lines = [json.loads(x) for x in (tmp_path / "issues.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["status"] for x in lines] == ["open", "resolved"]
    snap = json.loads((tmp_path / "open.json").read_text(encoding="utf-8"))
    assert snap["n_open"] == 0


def test_store_missing_data_does_not_resolve(tmp_path):
    st = IssueStore(tmp_path)
    st.apply([J.F("S4", "port:base", True, "断")], T0, {})
    st.apply([], T0 + 60, {})                                             # 没测到 ≠ 恢复
    assert len(st.open_issues()) == 1


def test_store_severity_and_owner_override(tmp_path):
    st = IssueStore(tmp_path)
    fs = J.j_identity({"rows": [{"run": "series10_s2", "cid": "lin_wan", "ok": False, "why": "解析成 ref2va", "got": "a", "want": "b"}]})
    rec = st.apply(fs, T0, {"S6": "FACTORY"})["opened"][0]
    assert rec["severity"] == "P0" and rec["owner_loop"] == "WORKFLOW / FACTORY"


# ------------------------------------------------------------------ 判定
def test_pause_uses_policy_decision():
    ctrl = {"paused": True, "paused_by": "NETFIX 切香港线路", "paused_at": "2026-11-02T00:52:01"}
    t = J.ts("2026-11-02T00:52:01")
    assert not J.j_pause("laptop", ctrl, t + 120, policy.pause_decision)[0]["violated"]
    assert J.j_pause("laptop", ctrl, t + 240, policy.pause_decision)[0]["violated"]


def test_gpu_idle_needs_ready_and_span():
    c = C["S2_gpu_all_idle_s"]
    hist = [(T0 + i * 60, [0, 0, 0]) for i in range(4)]
    assert J.j_gpu_idle("gpu33", hist, {"server": 0, "laptop_partition": 0}, False, T0 + 180, c)[0]["violated"] is False
    f = J.j_gpu_idle("gpu33", hist, {"server": 0, "laptop_partition": 3}, False, T0 + 180, c)[0]
    assert f["violated"] and f["evidence"]["both_sides_not_dispatching"]
    assert not J.j_gpu_idle("gpu33", hist, {"server": 5}, True, T0 + 180, c)[0]["violated"]        # 暂停归 S7
    assert not J.j_gpu_idle("gpu33", hist[:-1] + [(T0 + 180, [0, 40, 0])], {"server": 5}, False, T0 + 180, c)[0]["violated"]


def test_score_p50_and_backlog():
    c = C["S3_score_p50_s"]
    fs = {f["key"]: f for f in J.j_score("gpu33", [(T0, 600.0), (T0 + 10, 900.0)], [T0 + 20], T0 + 60, c)}
    assert fs["S3:p50:gpu33"]["violated"] and fs["S3:backlog:gpu33"]["violated"]
    fs = {f["key"]: f for f in J.j_score("gpu33", [(T0, 30.0), (T0 + 10, 40.0)], [], T0 + 60, c)}
    assert not fs["S3:p50:gpu33"]["violated"] and not fs["S3:backlog:gpu33"]["violated"]


def test_vqa_endpoint_matches_declared_backend():
    router = '{"loaded": true, "gpu": "router", "instances": 3}'
    old = '{"loaded": true, "gpu": 0, "queue": 0}'
    assert J.vqa_kind(router, '{"error": "not found"}') == "router_nf4"
    assert J.vqa_kind(old, '{"error": "not found"}') == "nf4"
    assert J.vqa_kind(None, '{"object":"list","data":[]}') == "vllm"
    assert J.j_vqa_endpoint("gpu36", 8870, "nf4", "router_nf4")[0]["violated"]          # 01:5x 旧 server.py 占 8870
    assert not J.j_vqa_endpoint("laptop", 8870, "nf4", "nf4")[0]["violated"]             # 笔记本 nf4 专用实例 = 声明（L-100）
    assert J.j_vqa_endpoint("gpu36", 8870, None, "router_nf4") == []


def test_ports_recover_threshold():
    c = C["S4_recover_s"]
    f = J.j_ports({"base": {"ok": False, "down_since": T0}}, T0 + 31, c)[0]
    assert f["violated"]
    assert not J.j_ports({"base": {"ok": False, "down_since": T0}}, T0 + 20, c)[0]["violated"]


def test_parity_and_handback():
    fs = J.j_parity("gpu33", {"config/vqa.json": "a", "x": None}, {"config/vqa.json": "b", "x": None}, ["config/vqa.json", "x"])
    assert [f["violated"] for f in fs] == [True]                                                     # 两边都缺 = 一致，不出 finding
    assert J.j_parity("gpu33", {"config/vqa.json": "a"}, {}, ["config/vqa.json"]) == []          # 服务器没回 = 未测
    rec = {"ready": True, "by": "WORKFLOW resident_sync.push_required"}
    assert J.j_handback("gpu33", "server", rec, policy.handback_ok(rec))[0]["violated"]


def test_cut_and_deploy_after_failed_cut():
    lc = {"ok": False, "id": "sv-04", "at": T0, "at_iso": "x", "reason": "闸门不过"}
    assert J.j_cut(lc)[0]["violated"]
    assert J.j_deploy_after_failed_cut({"id": "sv-03", "at": "2026-11-02T02:30:00"}, lc)[0]["violated"] is (J.ts("2026-11-02T02:30:00") > T0)
    assert J.j_sv_lag("gpu36", "sv-01", ["sv-01", "sv-02", "sv-03"], C["S5_release"])[0]["violated"]


def test_human_wait_and_gap():
    c = C["S13_human_wait"]
    assert J.is_human_wait("驳回重出 2 次都没换上，等总调度定") and not J.is_human_wait("首帧过契约")
    f = J.j_human_wait("gpu33", {"first:ep01-S1": (T0, "等总调度定")}, T0 + 601, c)[0]
    assert f["violated"] and f["evidence"]["n"] == 1
    assert J.j_pipeline_gap("gpu33", 200, 0, 77, 77, c)[0]["violated"]
    assert not J.j_pipeline_gap("gpu33", 200, 3, 77, 0, c)[0]["violated"]


def test_ui_rules_findings():
    fs = J.j_ui({"pages": {"overview": {"color_capsules": ["描边胶囊｜待重出"], "broken_imgs": [], "contradictions": ["卡 0/6 忙 但渲染任务在办 2"]}}},
                C["S9_ui_rules"])
    v = {f["key"]: f["violated"] for f in fs}
    assert v == {"S9:overview:color": True, "S9:overview:broken": False, "S9:overview:contradiction": True}


def test_probe_fault_is_ticket(tmp_path, monkeypatch):
    """K-OPS-S06：探针抛异常 → {SLO}:probe_fault 工单（不当正常）"""
    from tools.sentinel import probes as P
    from tools.sentinel import sentinel as S

    def boom(ctx):
        raise RuntimeError("读不到")
    monkeypatch.setitem(P.PROBES, "S12", boom)
    monkeypatch.setattr(S, "LOG", tmp_path / "sentinel.log")
    st = IssueStore(tmp_path)
    S.tick({"S12"}, force=True, store=st)
    keys = {r["key"] for r in st.open_issues()}
    assert "S12:probe_fault" in keys


# ------------------------------------------------------------------ 回放（夹具 = 当晚日志的最小证据集）
FIX = ROOT / "tests/fixtures/sentinel/replay_20261102.json"


@pytest.mark.skipif(not FIX.exists(), reason="回放夹具未生成（tools/sentinel/replay.py extract）")
def test_replay_beats_humans():
    from tools.sentinel import replay
    r = replay.run(json.loads(FIX.read_text(encoding="utf-8")))["events"]
    must = ["pause_0052", "gpu36_0109", "score_backlog", "port8870", "refs_0124", "vqa_redeploy", "gpu33_0222", "base_0224", "gaze_miss"]
    for ev in must:
        assert r[ev]["lead_min"] is not None and r[ev]["lead_min"] > 0, (ev, r[ev])
