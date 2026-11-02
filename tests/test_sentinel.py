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


# ------------------------------------------------------------------ GPU 24 小时（K-OPS-S09）
def test_gpu24_classify_sums_to_window():
    from tools.sentinel import gpu_hours as G
    t0, t1 = T0, T0 + 3600
    hist = {"n": 3, "rows": [
        [t0 + 100, t0 + 160, True, "PRODUCER", 2, "S4", "first_frame"],     # 收下 → 真正在跑
        [t0 + 300, t0 + 360, True, "PRODUCER", 2, "S5", "first_frame"],     # 被回滚作废 → 空跑
        [t0 + 600, t0 + 900, True, "VQAGATE", None, None, None],            # 借道
    ]}
    ev = [{"t": t0 + 90, "ev": "dispatch", "lane": "gpu33:0", "obj": "first:ep02-S4"},
          {"t": t0 + 200, "ev": "rendered", "lane": "gpu33:0", "obj": "first:ep02-S4", "take": 1, "gpu_s": 60},
          {"t": t0 + 380, "ev": "rendered", "lane": "gpu33:0", "obj": "first:ep02-S5", "take": 2, "gpu_s": 60},
          {"t": t0 + 1000, "ev": "master_reject", "obj": "first:ep02-S5", "take": 2, "reason": "覆盖配置缺失、身份脸用错"}]
    r = G.classify("gpu33:0", t0, t1, hist, ev)
    assert sum(r[b] for b in G.BUCKETS) == 3600
    assert 50 <= r["productive"] <= 80 and r["borrowed"] >= 290 and r["idle_burn"] >= 60
    assert r["no_data"] <= 110                                              # 历史起点之前 = 无数据（不猜）


def test_gpu24_no_history_is_no_data():
    from tools.sentinel import gpu_hours as G
    r = G.classify("gpu36:0", T0, T0 + 3600, None, [])
    assert r["no_data"] == 3600


# ------------------------------------------------------------------ RSI 线（K-OPS-S08）
def test_rsi_stale_and_flat():
    c = C["S14_rsi_lines"]
    sm = {"image": {"name": "出图", "lead": "IMGLAB", "score": 50, "target": None, "track": [[T0, 40], [T0 + 60, 50], [T0 + 120, 50], [T0 + 180, 49], [T0 + 240, 50]]},
          "video": {"name": "视频", "lead": "VIDLAB", "score": None, "target": None, "track": []}}
    fs = {f["key"]: f for f in J.j_rsi(sm, T0 + 300, dict(c, program_start=None))}
    assert fs["S14:image:flat"]["violated"] and fs["S14:image:flat"]["owner_loop"] == "IMGLAB"
    assert not fs["S14:image:stale"]["violated"]
    fs2 = {f["key"]: f for f in J.j_rsi(sm, T0 + 240 + 7201, dict(c, program_start=None))}
    assert fs2["S14:image:stale"]["violated"]


def test_rsi_load_normalizes_aliases(tmp_path):
    from tools.sentinel import rsi
    p = tmp_path / "scores.jsonl"
    p.write_text('{"at": "2026-11-02T04:00:00", "line": "线1", "score": 41, "parts": {"人物一致性": 60}, "sv": "sv-05"}\nnot json\n', encoding="utf-8")
    recs, bad = rsi.load(C["S14_rsi_lines"], p)
    assert recs[0]["line"] == "image" and recs[0]["score"] == 41 and len(bad) == 1


def test_gpu24_wait_reasons_and_top_tickets():
    from tools.sentinel import gpu_hours as G
    t0, t1 = T0, T0 + 3600
    hist = {"n": 1, "rows": [[t0, t0 + 10, True, "VQAGATE", None, None, None]]}   # 历史从窗口起点就有 = 之后的空白都有证据
    ev = [{"t": t0, "ev": "pause", "src": "laptop"}, {"t": t0 + 1200, "ev": "resume", "src": "laptop"},
          {"t": t0 + 1800, "ev": "pf_minute", "src": "laptop"}]
    r = G.classify("gpu33:0", t0, t1, hist, ev, {})
    w = r["waiting_reasons"]
    assert sum(w.values()) == r["waiting"] and w["pause"] >= 1180 and 60 <= w["no_jobs"] <= 80 and w["hold"] == 0
    res = {"waiting_reasons": {"seconds": {"pause": 5000, "no_jobs": 3000, "service_down": 100, "unknown": 9000},
                               "pct_of_waiting": {"pause": 29, "no_jobs": 18, "service_down": 1, "unknown": 52},
                               "zh": G.WAIT_ZH, "owner": G.WAIT_OWNER}}
    fs = {f["key"]: f for f in J.j_wait_top(res, 2)}
    assert fs["GPU24:wait:pause"]["violated"] and fs["GPU24:wait:pause"]["owner_loop"] == "DEBUG-RSI"
    assert fs["GPU24:wait:no_jobs"]["violated"] and fs["GPU24:wait:no_jobs"]["owner_loop"] == "FACTORY"
    assert not fs["GPU24:wait:service_down"]["violated"] and fs["GPU24:wait:unknown"]["violated"]


def test_vlm_from_samples(tmp_path):
    from tools.sentinel import gpu_hours as G
    p = tmp_path / "s.jsonl"
    p.write_text('{"t": %d, "host": "gpu36", "smi": [[2, 80, 9000]]}' % (T0 + 600) + chr(10), encoding="utf-8")
    r = G.vlm_from_samples("gpu36:2", T0, T0 + 3600, p)
    assert r["productive"] >= 90 and r["no_data"] >= 3400 and sum(r[b] for b in G.BUCKETS) == 3600


def test_s1_uses_history_window_not_instant(monkeypatch):
    """S1 = lane_util.measure 的 /history 执行时间并集（窗口占用），不是 nvidia-smi 瞬时值（总调度 04:1x 核实 gpu33:1 0% 误报）"""
    from tools.debug import lane_util
    from tools.sentinel import probes as P
    seen = {}

    def fake(minutes, lanes=None, fetch=None, now=None):
        seen["minutes"] = minutes
        return {"at": "x", "window_min": minutes, "lanes": {"gpu33:1": {"util": 0.77, "jobs": 9}}}
    monkeypatch.setattr(lane_util, "measure", fake)
    ctx = P.Ctx(policy.load()["sentinel"], {})
    fs = P.p_s1(ctx)
    assert seen["minutes"] == C["S1_lane_util_min"]["window_min"]
    assert fs[0]["evidence"]["util"] == 0.77 and fs[0]["evidence"]["window_min"] == seen["minutes"]


def test_backlog_near_warns_before_top():
    c = C["S3_score_p50_s"]
    ev = [{"t": T0 + i, "ev": "rendered", "obj": f"first:ep01-S{i}"} for i in range(42)] + [{"t": T0 + 50, "ev": "passed", "obj": "first:ep01-S0"}]
    n = J.scoring_backlog(ev, T0 + 100)
    assert n == 41
    assert J.j_backlog_near("gpu33", 42, 48, c)[0]["violated"]          # 88% ≥ 80%：到顶前预警
    assert not J.j_backlog_near("gpu33", 30, 48, c)[0]["violated"]


# ------------------------------------------------------------------ S15 / S16（K-OPS-S10）
def test_flow_tick_stale_or_dry():
    c = C["S15_flow_tick"]
    assert not J.j_flow_tick({"t": T0, "dry": False}, None, T0 + 60, c)[0]["violated"]
    assert J.j_flow_tick({"t": T0, "dry": False}, None, T0 + 301, c)[0]["violated"]
    assert J.j_flow_tick({"t": T0, "dry": True}, None, T0 + 10, c)[0]["violated"]
    assert J.j_flow_tick(None, None, T0, c)[0]["violated"]


def test_laptop_procs_missing_resident_sync():
    procs = C["S16_laptop_procs"]["procs"]
    lines = ['"C:/Python312/python.exe" -u tools/autopilot/producer.py serve',
             '"C:/Python312/pythonw.exe" -u "D:\\NS-Final Studio\\tools\\netfix\\tunnel_supervisor.py" serve --conf x']
    fs = {f["key"]: f for f in J.j_procs(lines, procs)}
    assert not fs["S16:producer"]["violated"] and not fs["S16:tunnel_supervisor"]["violated"]
    assert fs["S16:resident_sync"]["violated"] and fs["S16:resident_sync"]["owner_loop"] == "WORKFLOW"
    assert J.j_procs(None, procs) == []


def test_gpu24_empty_history_after_restart_is_no_data():
    """ComfyUI 重启清空 /history：空历史不能当“没执行”，rendered.gpu_s 照样算真正在跑，其余记无数据"""
    from tools.sentinel import gpu_hours as G
    ev = [{"t": T0 + 600, "ev": "rendered", "lane": "gpu33:3", "obj": "first:ep01-S1", "take": 1, "gpu_s": 60}]
    r = G.classify("gpu33:3", T0, T0 + 3600, {"n": 0, "rows": []}, ev, {})
    assert r["waiting"] == 0 and 60 <= r["productive"] <= 80 and r["no_data"] >= 3500


# ------------------------------------------------------------------ S17 / S18 / 时区存疑（总调度 08:0x）
def test_shot_render_rate():
    c = C["S17_shot_render_rate"]
    ev = [{"t": T0 + i * 60, "ev": "rendered", "obj": "first:ep05-S3", "lane": "gpu33:0", "take": 70 + i} for i in range(9)]
    ev += [{"t": T0, "ev": "rendered", "obj": "first:ep01-S1", "lane": "gpu33:1", "take": 2}]
    fs = {f["key"]: f for f in J.j_shot_rate(ev, T0 + 600, c)}
    assert fs["S17:first:ep05-S3"]["violated"] and fs["S17:first:ep05-S3"]["evidence"]["last_take"] == 78
    assert not fs["S17:first:ep01-S1"]["violated"]


def test_temp_holds_expiry():
    c = C["S18_temp_holds"]
    holds = {"gpu36:0": {"why": "滚动重启", "at": J.iso(T0), "by": "DEBUG-RSI"},
             "gpu33:1": {"why": "A/B", "at": J.iso(T0), "expires_at": J.iso(T0 + 1800), "by": "IMGLAB"}}
    fs = {f["key"]: f for f in J.j_temp_holds(holds, T0 + 901, c)}
    assert fs["S18:gpu36:0"]["violated"] and fs["S18:gpu36:0"]["owner_loop"] == "DEBUG-RSI"
    assert not fs["S18:gpu33:1"]["violated"]
    assert {f["key"]: f for f in J.j_temp_holds(holds, T0 + 1801, c)}["S18:gpu33:1"]["violated"]


def test_tz_suspect_only_without_epoch():
    """EST 写的 ts 但带 epoch t 的 pause：以 t 为准照算 pause（11-02 08:1x 核对 t 与东京时间一致）；只有 ts 没有 t 才算时区存疑"""
    from tools.sentinel import gpu_hours as G
    t0 = T0
    est_ts = J.iso(t0 + 100 - 14 * 3600)
    assert G.tz_suspect({"t": t0 + 100, "ts": est_ts}) is False and G.tz_suspect({"ts": est_ts}) is True
    ev = [{"t": t0 + 100, "ts": est_ts, "ev": "pause", "src": "laptop"}, {"t": t0 + 1300, "ev": "resume", "src": "laptop"}]
    hist = {"n": 1, "rows": [[t0, t0 + 5, True, "VQAGATE", None, None, None]]}
    w = G.classify("gpu33:0", t0, t0 + 3600, hist, ev, {})["waiting_reasons"]
    assert 1150 <= w["pause"] <= 1250 and w["tz_suspect"] == 0


def test_ctrl_history_gives_hold(tmp_path):
    from tools.sentinel import gpu_hours as G
    p = tmp_path / "h.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"t": T0 + 600, "src": "temp_holds", "state": {"gpu36:0": {"why": "重启"}}},
        {"t": T0 + 1800, "src": "temp_holds", "state": {}}]) + "\n", encoding="utf-8")
    ctrl = G.ctrl_intervals(T0, T0 + 3600, p)
    hist = {"n": 1, "rows": [[T0, T0 + 5, True, "VQAGATE", None, None, None]]}
    w = G.classify("gpu36:0", T0, T0 + 3600, hist, [], {}, ctrl)["waiting_reasons"]
    assert 1150 <= w["hold"] <= 1250


def test_master_pause_split_and_not_ticketed():
    """总调度下的暂停单列“总调度暂停”、派单方照实写，不算到 DEBUG-RSI 头上、不开单（总调度 08:2x）"""
    from tools.sentinel import gpu_hours as G
    ev = [{"t": T0 + 100, "ev": "pause", "by": "总调度 fredw-2b", "note": "为 IMGFIX", "src": "laptop"},
          {"t": T0 + 1300, "ev": "resume", "by": "总调度", "src": "laptop"}]
    hist = {"n": 1, "rows": [[T0, T0 + 5, True, "VQAGATE", None, None, None]]}
    w = G.classify("gpu33:0", T0, T0 + 3600, hist, ev, {})["waiting_reasons"]
    assert 1150 <= w["pause_master"] <= 1250 and w["pause"] == 0
    segs = G.pause_segments(ev, T0, T0 + 3600, [{"by_match": "总调度", "start": J.iso(T0 + 100), "label": "总调度全局暂停（为 IMGFIX）"}])
    assert segs[0]["label"] == "总调度全局暂停（为 IMGFIX）" and segs[0]["by"].startswith("总调度")
    res = {"waiting_reasons": {"seconds": {"pause_master": 9000, "pause": 100, "no_jobs": 50}, "pct_of_waiting": {}, "zh": G.WAIT_ZH, "owner": G.WAIT_OWNER}}
    fs = {f["key"]: f for f in J.j_wait_top(res, 2)}
    assert not fs["GPU24:wait:pause_master"]["violated"] and fs["GPU24:wait:pause"]["violated"]


def test_by_run_splits_seasons():
    from tools.sentinel import gpu_hours as G
    from tools.autopilot import runs as RUNS
    prim = RUNS.primary_run()
    ev = [{"t": T0, "ev": "rendered", "obj": "first:ep01-S1", "take": 1, "lane": "gpu33:0", "gpu_s": 36},
          {"t": T0, "ev": "rendered", "obj": "series10_s2/first:ep01-S1", "take": 1, "lane": "gpu36:0", "gpu_s": 72}]
    r = G.by_run(ev, T0 - 1)
    assert r[prim]["renders"] == 1 and r["series10_s2"]["renders"] == 1 and r["series10_s2"]["gpu_h"] == 0.02


def test_capacity_floor():
    c = C["S19_capacity_floor"]
    f = J.j_capacity({"gpu33": 2, "gpu36": 3}, [], ["series10_s2:ep08"], c)[0]
    assert f["violated"] and "导入了没放单" in f["title"] and f["owner_loop"] == c["owner_loop"]
    assert not J.j_capacity({"gpu33": 2, "gpu36": 3}, ["series10_s2:ep01"], [], c)[0]["violated"]      # 有下一批
    assert not J.j_capacity({"gpu33": 6, "gpu36": 6}, [], [], c)[0]["violated"]
    assert J.j_capacity({}, [], [], c) == []
    fs = {x["key"]: x for x in J.j_capacity({"gpu33": 0, "gpu36": 40}, [], [], c)}
    assert not fs["S19:capacity"]["violated"] and fs["S19:capacity:gpu33"]["violated"] and not fs["S19:capacity:gpu36"]["violated"]


def test_capacity_not_producing_and_host_text():
    c = C["S19_capacity_floor"]
    fs = {x["key"]: x for x in J.j_capacity({"gpu33": 1, "gpu36": 30}, [], [], c, {"gpu33": {"series10_s2": 60}})}
    h = fs["S19:capacity:gpu33"]
    assert h["violated"] and "gpu36 还剩 30" in h["title"] and "60 个 ready 属于非 producing" in h["title"]
    assert not fs["S19:capacity"]["violated"]                                  # 合计可派 31 ≥ 10


# ------------------------------------------------------------------ G26 声明 vs 实际
def test_decl_vs_actual():
    decl = {"gpu33:0": {"gpu": 0, "comfy_port": 8188}, "gpu33:1": {"gpu": 1, "comfy_port": 8189}, "gpu33:3": {"gpu": 3, "comfy_port": 8191}}
    actual = {"8188": {"pid": 11, "cuda_arg": 0, "stats_ok": True},
              "8189": {"pid": 12, "cuda_arg": None, "cvd": "2", "stats_ok": True},           # 跑到坏卡 2 上
              "8191": {"pid": None, "stats_ok": False, "err": "refused"}}
    fs = {f["key"]: f for f in J.j_decl_vs_actual("gpu33", decl, actual, [2], {"2": [12]})}
    assert not fs["G26:gpu33:0"]["violated"]
    assert fs["G26:gpu33:1"]["violated"] and "实际跑在 GPU 2" in fs["G26:gpu33:1"]["title"]
    assert fs["G26:gpu33:3"]["violated"] and "没有进程在听" in fs["G26:gpu33:3"]["title"]
    assert fs["G26:gpu33:broken2"]["violated"]
    assert J.lane_gpu_actual({"smi_gpus": [0, 1]}) is None                                 # 不唯一不判


def test_g26_waits_for_sv09(monkeypatch):
    from tools.sentinel import probes as P
    monkeypatch.setattr(P, "jl", lambda p, default=None: {"id": "sv-20261102-04"} if "system_version" in str(p) else default)
    ctx = P.Ctx(policy.load()["sentinel"], {})
    assert P.p_g26(ctx) == [] and "sv-20261102-09" in ctx.mem["g26_state"]


def test_scratchpad_procs():
    c = C["S20_scratchpad_procs"]
    sp = "C:\\Users\\fredw\\AppData\\Local\\Temp\\claude\\C--Users-fredw\\abc\\scratchpad\\"
    procs = [{"pid": 1, "name": "python.exe", "cmd": f'python.exe "{sp}lend_any.py" gpu36:0'},
             {"pid": 2, "name": "python.exe", "cmd": f'python.exe "{sp}fix_prod.py"'},
             {"pid": 3, "name": "python.exe", "cmd": "python.exe -u tools/autopilot/producer.py serve"},
             {"pid": 4, "name": "python.exe", "cmd": f'python.exe tools/qa/data_parity.py --out "{sp}out.json"'},      # 只是输出写到 scratchpad
             {"pid": 5, "name": "bash.exe", "cmd": f'bash -c "source {sp}snapshot-bash-1793516248100-q1sni9.sh; ls"'}]
    fs = {f["key"]: f for f in J.j_scratch_procs(procs, c)}
    assert set(fs) == {"S20:lend_any.py", "S20:fix_prod.py"}
    assert fs["S20:lend_any.py"]["owner_loop"] == "DEBUG-RSI" and "已知，sv-10 收编" in fs["S20:lend_any.py"]["title"]
    assert fs["S20:fix_prod.py"]["owner_loop"] == "总调度"
    assert J.j_scratch_procs(None, c) == []


def test_legacy_reads_and_freeze_drift():
    c = C["S21_state_legacy_read"]
    rows = [{"at": J.iso(T0) + "+0900", "name": "netfix/partition", "old_path": "config/netfix/partition.json", "caller": "probes.py:126", "host": "x"}]
    fs = {f["key"]: f for f in J.j_legacy_reads(rows, ["netfix/partition", "pipeline/run"], T0 + 60, c, lambda cl: "SENTINEL")}
    assert fs["S21:netfix/partition"]["violated"] and fs["S21:netfix/partition"]["owner_loop"] == "SENTINEL"
    assert not fs["S21:pipeline/run"]["violated"]
    assert not {f["key"]: f for f in J.j_legacy_reads(rows, ["netfix/partition"], T0 + 90000, c)}["S21:netfix/partition"]["violated"]
    drift = [{"sv": "sv-20261102-09", "at": J.iso(T0), "files": ["tools/sentinel/probes.py", "tools/qa/iter_gate.py"]}]
    own = {"tools/sentinel/probes.py": "SENTINEL", "tools/qa/iter_gate.py": "SYSARCH"}.get
    fs = {f["key"]: f for f in J.j_freeze_drift(drift, {"ok": False, "at": T0 + 10}, own)}
    assert fs["S22:sv-20261102-09:SENTINEL"]["violated"] and fs["S22:sv-20261102-09:SYSARCH"]["owner_loop"] == "SYSARCH"
    assert not any(f["violated"] for f in J.j_freeze_drift(drift, {"ok": True, "at": T0 + 10}, own))


def test_laptop_lane_reach():
    c = C["S23_laptop_lane_reach"]
    hist = {"gpu33:0": [[T0 + i * 60, i % 3 == 0] for i in range(5)], "gpu36:0": [[T0 + i * 60, True] for i in range(5)]}
    cur = {"gpu33:0": False, "gpu36:0": True}
    fs = {f["key"]: f for f in J.j_lane_reach(hist, cur, T0 + 240, c)}
    assert fs["S23:gpu33:0"]["violated"] and not fs["S23:gpu36:0"]["violated"]
    assert fs["S23:half_down"]["violated"] and fs["S23:half_down"]["owner_loop"] == "NETFIX"     # 1/2 ≥ 半数
    fs2 = {f["key"]: f for f in J.j_lane_reach(hist, {"gpu33:0": True, "gpu36:0": True}, T0 + 240, c)}
    assert not fs2["S23:half_down"]["violated"]


def test_ssh_loops():
    c = dict(C["S20_scratchpad_procs"]["ssh_loop"], owner_loop="总调度")
    shells = {10: {"cmd": "bash -c 'while true; do ssh gpu36 nvidia-smi; sleep 60; done'", "created_t": T0 - 3 * 3600},
              11: {"cmd": "bash -c 'ls'", "created_t": T0 - 3 * 3600},
              12: {"cmd": "bash -c 'tools/vqa/poll.sh'", "created_t": T0 - 600}}
    spawns = {10: [T0 - 600, T0 - 300, T0 - 60], 12: [T0 - 100, T0 - 50, T0 - 10]}
    fs = {f["key"]: f for f in J.j_ssh_loops(shells, spawns, T0, c, lambda cmd: "VQAGATE" if "vqa" in cmd else None)}
    assert fs["S20:ssh_loop:10"]["violated"] and fs["S20:ssh_loop:10"]["owner_loop"] == "总调度"
    assert "S20:ssh_loop:11" not in fs                                         # 老 shell 但没起 ssh
    assert not fs["S20:ssh_loop:12"]["violated"] and fs["S20:ssh_loop:12"]["owner_loop"] == "VQAGATE"   # 起 ssh 但没满 2 小时


def test_scratchpad_readonly_exempt():
    c = C["S20_scratchpad_procs"]
    sp = "C:/Users/fredw/AppData/Local/Temp/claude/x/scratchpad/"
    fs = {f["key"]: f for f in J.j_scratch_procs([{"pid": 1, "cmd": f"sh {sp}watch_green.sh"}], c)}
    assert not fs["S20:watch_green.sh"]["violated"] and "只读" in fs["S20:watch_green.sh"]["evidence"]["exempt"]
    fs = {f["key"]: f for f in J.j_scratch_procs([{"pid": 1, "cmd": f"sh {sp}watch_green.sh; ssh gpu33 ls"}], c)}
    assert fs["S20:watch_green.sh"]["violated"]                                  # 命令行里有 ssh 就不豁免


def test_api_latency():
    c = C["S24_api_latency"]
    slow = {"/api/season": [[T0 + i, 0.05, 200] for i in range(18)] + [[T0 + 18, 6.0, 200], [T0 + 19, 25.0, 200]]}
    fs = {f["key"]: f for f in J.j_api_latency(slow, c)}
    assert fs["S24:/api/season"]["violated"] and fs["S24:/api/season"]["owner_loop"] == "UIRSI2"
    fast = {"/api/episodes": [[T0 + i, 0.1, 200] for i in range(20)]}
    assert not J.j_api_latency(fast, c)[0]["violated"]
    assert J.j_api_latency({"/api/x": [[T0, 0.1, 200]]}, c) == []                        # 样本不足不判
    fails = {"/api/season": [[T0 + i, 0.05, 200] for i in range(18)] + [[T0 + 18, 0.1, 0], [T0 + 19, 0.1, 0]]}
    assert J.j_api_latency(fails, c)[0]["violated"]                                     # 失败按超时计


def test_clip_resident():
    c = C["S25_clip_resident"]
    fs = {f["key"]: f for f in J.j_clip("gpu36", {"pid": 9, "pid_alive": False, "health": "ERR refused", "reloads_1h": 5}, c)}
    assert fs["S25:gpu36:alive"]["violated"] and fs["S25:gpu36:reload"]["violated"] and fs["S25:gpu36:alive"]["owner_loop"] == "FACTORY"
    fs = {f["key"]: f for f in J.j_clip("gpu33", {"pid": 9, "pid_alive": True, "health": "timeout", "reloads_1h": 1}, c)}
    assert not fs["S25:gpu33:alive"]["violated"] and not fs["S25:gpu33:reload"]["violated"]     # 忙时 /health 超时不算挂


def test_scorecard_combine_and_tickets():
    from tools.sentinel import scorecard as SC
    r = SC._combine({"a": 1.0, "b": None}, {"a": 50, "b": 50}, [], 95)
    assert r["score"] == 50.0 and r["lowest"] == "b"                                  # 未测按 0，不当满分
    r = SC._combine({"a": 1.0, "b": 1.0}, {"a": 50, "b": 50}, ["深链接"], 95)
    assert r["score"] == 95 and r["capped"]                                           # 有未测标准时封顶 95
    fs = {f["key"]: f for f in J.j_scorecard({"ui": r, "script": {"score": 100.0, "parts": {}, "lowest": None}}, {"ui": "NAVIA"})}
    assert fs["SC:ui"]["violated"] and fs["SC:ui"]["owner_loop"] == "NAVIA（抄送总调度）" and not fs["SC:script"]["violated"]


def test_autoflow_resident_and_review_chain():
    c = C["S26_autoflow_resident"]
    assert not J.j_autoflow_resident({"t": T0}, None, T0 + 60, c)[0]["violated"]
    assert J.j_autoflow_resident({"t": T0}, None, T0 + 121, c)[0]["violated"]
    assert J.j_autoflow_resident(None, None, T0, c)[0]["violated"]
    c2 = C["S27_p1_review_chain"]
    rounds = [{"name": "r2", "done": [T0, T0 + 10, T0 + 20], "result_t": None}, {"name": "r3", "done": [T0, T0 + 5, T0 + 9], "result_t": T0 + 60},
              {"name": "r4", "done": [T0], "result_t": None}]
    fs = {f["key"]: f for f in J.j_review_chain(rounds, T0 + 400, c2)}
    assert fs["S27:r2"]["violated"] and not fs["S27:r3"]["violated"] and "S27:r4" not in fs


def test_scratch_parent_child_counted_once():
    c = C["S20_scratchpad_procs"]
    sp = "C:/Users/fredw/AppData/Local/Temp/claude/x/scratchpad/"
    procs = [{"pid": 1, "ppid": 0, "cmd": f"D:/.venv/Scripts/python.exe {sp}job.py"}, {"pid": 2, "ppid": 1, "cmd": f"C:/Python312/python.exe {sp}job.py"}]
    f = J.j_scratch_procs(procs, c)[0]
    assert f["evidence"]["pids"] == [1]


def test_review_rounds_scans_all_rn(tmp_path):
    """S27 扫描所有 rN 轮次目录（r4、r10 以后都要看到），不是只看 r1–r3"""
    from tools.sentinel import probes as P
    base = tmp_path / "judge_p1"
    for d in ["", "r2", "r3", "r4", "r10"]:
        for k in (1, 2, 3):
            o = base / d / f"judge_{k}" / "out"
            o.mkdir(parents=True, exist_ok=True)
            (o / "p1_review.json.done").write_text("ok", encoding="utf-8")
    (base / "RESULT.json").write_text("{}", encoding="utf-8")
    names = {r["name"]: r for r in P.review_rounds(base, 3)}
    assert set(names) == {"r1", "r2", "r3", "r4", "r10"}
    assert names["r10"]["result_t"] is None and len(names["r10"]["done"]) == 3


def test_ui_measure_tickets():
    m = {"at": "x", "pages": {"/#/settings": {"jargon": ["seed", "LoRA"], "color_capsules": [], "contradictions": []},
                              "/#/overview": {"jargon": [], "color_capsules": ["描边胶囊｜待重出"], "contradictions": []},
                              "/#/cut": {"error": "timeout"}}}
    fs = {f["key"]: f for f in J.j_ui_measure(m, "UIRSI")}
    assert fs["S9:sc/#/settings:jargon"]["violated"] and not fs["S9:sc/#/settings:clean"]["violated"]
    assert fs["S9:sc/#/overview:clean"]["violated"] and "S9:sc/#/cut:jargon" not in fs

