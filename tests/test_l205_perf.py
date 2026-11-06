"""L-205（项目方 11-06：KPI 一集 ≤ 50 分钟）—— PERF-AUDIT 审出的 producer 吞吐上限（P1–P6），全部临时目录 + mock，不碰 GPU / 网络：
P1 出图后打分线程池不再写死 3 · P2 非硬项看图子检查不跑（硬项照跑）· P3 打分积压只数“等着开始打分”的图、下限 道×深度×2 ·
P4 打分链路只在 ssh / 传输错误时熔断、只重打分退避 60 s、并发上限跟线程池 · P5 远端打分只重试一次（10 s）·
P6 探道并发、TICK 10 s、集摘要 3 s 超时、视频 loop_once 后台单飞。"""
import json
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/autopilot", "services/render_router", "services/agent", "packages/schema", "services/recipes", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import producer as PR  # noqa: E402

SRC = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")


def _producer(tmp_path, lanes=None, lane_probe=None):
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True, exist_ok=True)
    return PR.Producer(paths, script=object(), lanes=lanes or {}, lane_probe=lane_probe or (lambda u: {"ok": True, "n": 0}),
                       train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)


# ================================================================ P1 打分线程池
def test_p1_post_pool_size_from_lanes_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "prefetch_depth", lambda: 2)
    assert PR.post_pool_workers(tmp_path, 6) == 12                  # 6 道 × 深度 2
    assert PR.post_pool_workers(tmp_path, 1) == 6                   # 下限 6（原写死 3）
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/producer.json").write_text(json.dumps({"post_pool": {"max_workers": 9}}), encoding="utf-8")
    assert PR.post_pool_workers(tmp_path, 6) == 9                   # 配置优先
    fx = PR.FrameExec(PR.Paths(root=tmp_path), script=None, post_workers=7)
    assert fx.post_workers == 7 and fx.post_pool._max_workers == 7
    fx.post_pool.shutdown()
    assert "max_workers=3, thread_name_prefix=\"producer-postflight\"" not in SRC
    assert SRC.count("post_workers=post_pool_workers(paths.root, len(pr.lanes) or None)") == 2   # 两个启动入口都按道数开
    real = json.loads((ROOT / "config/pipeline/producer.json").read_text(encoding="utf-8"))
    assert "post_pool" in real


# ================================================================ P2 非硬项看图子检查不跑
def _gc(monkeypatch, skip=True, extra=None):
    import ns_agent.gen_contract as G
    conf = {"blocking_items": ["Q1", "count", "text", "adult", "gaze", "FL"], "vqa_skip_nonblocking": skip,
            "image_thresholds": {"Q1x_scene": {"enabled": True}}, **(extra or {})}
    monkeypatch.setattr(G, "cfg", lambda: conf)
    return conf


def test_p2_skip_nonblocking_only_non_hard_items(monkeypatch):
    from ns_agent.vqa import contract as VQ
    _gc(monkeypatch)
    assert VQ.skip_nonblocking("Q1a") and VQ.skip_nonblocking("Q1x") and VQ.skip_nonblocking("Q10")
    assert not VQ.skip_nonblocking("Q1") and not VQ.skip_nonblocking("gaze") and not VQ.skip_nonblocking("FL")
    _gc(monkeypatch, extra={"blocking_items": ["Q1", "Q1x"]})
    assert not VQ.skip_nonblocking("Q1x")                           # 名单里显式写了 → 照跑
    _gc(monkeypatch, skip=False)
    assert not VQ.skip_nonblocking("Q1a")                           # 开关关 = 全跑
    _gc(monkeypatch, extra={"blocking_items": None})
    assert not VQ.skip_nonblocking("Q1a")                           # 没有 L-196 名单 = 旧口径全跑
    real = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    assert real["vqa_skip_nonblocking"] is True


def test_p2_q1a_q1x_skipped_without_vlm(monkeypatch):
    from ns_agent.vqa import contract as VQ
    _gc(monkeypatch)
    monkeypatch.setattr(VQ, "_emb_of", lambda *a: (_ for _ in ()).throw(AssertionError("Q1x 不该跑")))
    pf = {"items": [{"id": "Q1a", "status": "pass", "evidence": {"q1a_mode": "seg"}}]}
    assert VQ.q1a_vlm(pf, "x.png") is None and pf["items"][0]["evidence"]["vlm"] == VQ.SKIPPED and pf["items"][0]["status"] == "pass"
    it = VQ.q1x("ep01-S1", "image", "x.png", pf)
    assert it["status"] == "na" and it["record_only"] and it["evidence"]["skipped"] == "skipped_nonblocking"
    assert [i["id"] for i in pf["items"]] == ["Q1a", "Q1x"]


def test_p2_accept_label_skips_outfit_keeps_prompt_and_count(monkeypatch):
    from tools.vqa import accept as ACC
    calls = []
    monkeypatch.setattr(ACC, "prompt_check", lambda *a, **k: calls.append("prompt") or {"status": "pass"})
    monkeypatch.setattr(ACC, "count_check", lambda *a, **k: calls.append("count") or {"status": "pass"})
    monkeypatch.setattr(ACC, "outfit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("服装不该跑")))
    monkeypatch.setattr(ACC, "identity", lambda pf: {"status": "pass"})
    for par in (False, True):
        monkeypatch.setattr(ACC, "_parallel_on", lambda par=par: par)
        calls.clear()
        lab = ACC.label("ep01-S1", "image", "x.png", {}, skip_outfit=True)
        assert sorted(calls) == ["count", "prompt"]                 # 提示词核对（含看图人数）+ 人数检测照跑
        assert lab["outfit"]["skipped"] == "skipped_nonblocking" and lab["ok"] == "pass"


def test_p2_vqa_gate_blocking_checks_still_run(monkeypatch):
    """开关打开时硬项相关的看图检查（视线重问 L-200、背影多脸 / 人数复核、Q1 复核带、Q10 验收入口）照跑"""
    from ns_agent.vqa import contract as VQ
    _gc(monkeypatch)
    calls = []
    monkeypatch.setattr(VQ, "enforced", lambda: True)
    monkeypatch.setattr(VQ, "inspect_for", lambda *a, **k: calls.append("inspect") or {"defects": []})
    monkeypatch.setattr(VQ, "ref_files", lambda refs: [])
    for name in ("sanitize", "reask_eye", "recheck_strangers", "q1_band_review", "hair_primary", "q1d", "accept_gate", "apply"):
        monkeypatch.setattr(VQ, name, lambda *a, _n=name, **k: calls.append(_n))
    monkeypatch.setattr(VQ, "_emb_of", lambda *a: (_ for _ in ()).throw(AssertionError("Q1x 不该跑")))
    pf = {"ok": True, "blocking": [], "items": [{"id": "Q1a", "status": "pass", "evidence": {}}]}
    PR.vqa_gate("ep01-S1", "image", "renders/x.png", {"prompt": "p"}, pf)
    for must in ("inspect", "reask_eye", "recheck_strangers", "q1_band_review", "accept_gate", "apply"):
        assert must in calls, must
    assert pf["items"][0]["evidence"]["vlm"] == "skipped_nonblocking"
    assert next(i for i in pf["items"] if i["id"] == "Q1x")["status"] == "na"


# ================================================================ P3 打分积压
def test_p3_backlog_counts_only_waiting_and_floor(tmp_path, monkeypatch):
    t = time.time()
    assert PR.dynamic_backlog([], t, 6, 2) == 24                   # 下限 道 × 深度 × 2
    monkeypatch.setattr(PR, "higher_priority_busy", lambda p: None)
    monkeypatch.setattr(PR, "decision_file_problems", lambda *a, **k: [])
    pr = object.__new__(PR.Producer)
    pr.mu = threading.RLock()
    pr.p = PR.Paths(root=tmp_path)
    pr.scoring = {f"first:ep01-S{i}" for i in range(6)}
    pr.score_backlog_max, pr._backlog_env, pr.score_done, pr.lanes, pr.depth = 2, 2, [], {"gpu33:0": "u"}, 2
    pr.frames = types.SimpleNamespace(post_workers=6)              # 6 张都在打分线程里跑 → 等着开始的 0 张
    logs = []
    pr.logf = lambda ev, **kw: logs.append(ev)
    pr.dispatch_frames({"episodes": []}, {"gpu33:0": {"free": True}}, {})
    assert "score_backlog" not in logs
    pr.frames = types.SimpleNamespace(post_workers=3)              # 3 张在跑、3 张等 → 超上限 2 → 停派
    pr.dispatch_frames({"episodes": []}, {"gpu33:0": {"free": True}}, {})
    assert logs.count("score_backlog") == 1 and logs[-1] == "score_backlog"


# ================================================================ P4 熔断 / 退避 / 并发
def test_p4_chain_trips_only_on_transport(tmp_path):
    pr = _producer(tmp_path)
    assert PR.is_transport_error("ssh: connect to host gpu33 port 22: Connection refused")
    assert PR.is_transport_error("URLError(timed out)") and not PR.is_transport_error("TimeoutError()")
    assert not PR.is_transport_error("Q9 untested：看图排队") and not PR.is_transport_error("")
    pr.score_chain_trip("看图 untested", err="Q9 untested")
    pr.score_chain_trip("共用验收 retry", err="")
    assert pr._score_down_until == 0
    pr.score_chain_trip("ssh 断", err="ssh exit status 255")
    assert pr._score_down_until > PR.now()
    pr._score_down_until = 0
    pr.score_chain_trip("线程回不来")                              # err=None：调用方已判定链路问题（reap 超时）
    assert pr._score_down_until > PR.now()
    assert PR.SCORE_RETRY_S == 60 and SRC.count("backoff_until=now() + SCORE_RETRY_S") == 2
    assert "backoff_until=now() + 300" not in SRC


def test_p4_rescore_cap_follows_post_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "RESCORE_MAX", 0)
    monkeypatch.setattr(PR, "prefetch_depth", lambda: 2)
    pr = _producer(tmp_path, lanes={f"gpu33:{i}": "u" for i in range(6)})
    assert pr.rescore_max == 12 and pr.rescore_pool._max_workers == 14
    led = {f"first:ep01-S{i}": {"rescore_take": 1} for i in range(1, 16)}
    pr.p.ledger.write_text(json.dumps(led), encoding="utf-8")
    gate = threading.Event()
    pr._rescore_one = lambda o, n: gate.wait(5)
    reg = {"episodes": [{"ep": 1, "shots": [{"shot": f"ep01-S{i}", "index": i, "objects": {"first": {
        "id": f"first:ep01-S{i}", "kind": "first", "shot": f"ep01-S{i}", "ep": 1, "status": "ready", "waiting_for": "空闲道"}}}
        for i in range(1, 16)]}]}
    assert pr.dispatch_rescores(reg) == 12
    gate.set()
    pr.rescore_pool.shutdown(wait=True)


# ================================================================ P5 远端打分重试
def test_p5_remote_score_single_retry_10s():
    body = SRC.split("    def _postflight(self, sid, stage, n, file_rel, job, host, host_path=None)", 1)[1][:4000]
    assert "for k in range(2 if host_path else 0)" in body and "time.sleep(10)" in body
    assert "time.sleep(30 * (k + 1))" not in SRC


# ================================================================ P6 每拍开销
def test_p6_probe_lanes_parallel_and_error_isolated(tmp_path):
    def probe(u):
        if u == "bad":
            raise OSError("connection refused")
        time.sleep(0.4)
        return {"ok": True, "n": 0}
    pr = _producer(tmp_path, lanes={"gpu33:0": "a", "gpu33:1": "b", "gpu33:3": "c", "gpu36:0": "bad"}, lane_probe=probe)
    t0 = time.time()
    qs = pr.probe_queues()
    assert time.time() - t0 < 1.0                                   # 串行要 1.2 s
    assert qs["gpu33:0"]["ok"] and qs["gpu36:0"]["ok"] is False and "refused" in qs["gpu36:0"]["error"]
    assert PR.TICK_S == 10
    assert 'api/episodes/summary", timeout=3)' in SRC


def test_p6_video_loop_once_background_single_flight(tmp_path, monkeypatch):
    p = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    vb = PR.VideoBridge(p)
    gate, n = threading.Event(), []
    fake = types.SimpleNamespace(RUN_ID=p.run_id, STATE=tmp_path / "night_state.json", loop_once=lambda st: n.append(1) or gate.wait(5))
    monkeypatch.setitem(sys.modules, "night", fake)
    monkeypatch.setenv("NS_RUN", p.run_id)                          # _night_mod 用 setdefault 钉 NS_RUN：交给 monkeypatch 还原，不漏到后面的测试
    ctrl = {"workers": {"video": "producer"}, "auto_force_eps": False}
    t0 = time.time()
    vb.tick({"episodes": []}, ctrl, False, lambda ev, **kw: None)
    vb.tick({"episodes": []}, ctrl, False, lambda ev, **kw: None)  # 上一轮没完：不再起
    assert time.time() - t0 < 1.0                                   # 不挡主循环
    gate.set()
    vb._takeover_th.join(5)
    assert n == [1]
