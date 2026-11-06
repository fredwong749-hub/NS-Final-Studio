"""L-209 S2.2 集关闭标记（W-S22）：临时目录 + 合成夹具，不连服务器、不出图。
  · 关闭口径：最新一版成片 timeline gates.verdict=pass 才关闭；fail（11-07 ep01 v71 缺 S1）不关闭；项目方定稿 = 关闭
  · enforce：关闭的集 0 新派单（producer 出图 / 只重打分、vidgen 作业、night control）；record：照派、记 ep_closed_skip；每对象每小时一条
  · 重开：项目方修改 / 重出（master_rejects）、成人镜触发（owner_triggers）自动重开；API 只认项目方、先审计；CLI 给总调度
  · L-207：enforce 下关闭的集 stage=done，不当 active 占卡集
  · 推送：episode_state.json 在 control_files 里、服务器端整文件覆盖、merge_pull 不回拉
  · 不碰 gpu33:2"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/api", "services/render_router", "tools/autopilot", "tools/series10_video", "ops/offline"):
    sys.path.insert(0, str(ROOT / p))
import episode_state as ES  # noqa: E402

RUN = "rx_s22"


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _final(root: Path, ep: int, n: int, verdict: str, missing=()):
    d = root / "data/episodes" / RUN
    d.mkdir(parents=True, exist_ok=True)
    (d / f"ep{ep:02d}_v{n}.mp4").write_bytes(b"x")
    _w(d / f"ep{ep:02d}_v{n}.timeline.json", {"gates": {"verdict": verdict, "missing_shots": [{"shot": s} for s in missing]}})


def _mode(root: Path, m: str):
    _w(root / ES.CFG_REL, {"take_sig": {"mode": "record"}, ES.KEY: {"mode": m}})


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ES, "_legacy", lambda run, root: False)
    ES._logged.clear()
    _w(tmp_path / "data/producer/runs" / RUN / "registry.json", {"episodes": [{"ep": 1}, {"ep": 2}]})
    return tmp_path


def _skips(root):
    p = ES.skips_path(RUN, root)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ------------------------------------------------------------------ 口径
def test_fail_gate_assembly_is_not_closed(env):
    _final(env, 1, 71, "fail", ["S1"])
    d = ES.compute(RUN, env)
    assert d["closed"] == [] and "fail" in d["episodes"]["1"]["why"] and "S1" in d["episodes"]["1"]["why"]
    assert d["episodes"]["2"]["closed"] is False


def test_pass_gate_closes_latest_version_wins(env):
    _final(env, 1, 70, "pass")
    assert ES.compute(RUN, env)["closed"] == [1]
    _final(env, 1, 71, "fail", ["S1"])            # 更新一版合成没过闸 → 不再关闭
    assert ES.compute(RUN, env)["closed"] == []
    _final(env, 1, 72, "pass")
    d = ES.compute(RUN, env)
    assert d["closed"] == [1] and d["episodes"]["1"]["assembly"]["version"] == 72
    assert ES.closed_eps(RUN, env) == {1}


def test_default_mode_record_and_off_does_not_write(env):
    assert ES.mode(env) == "record"
    _mode(env, "bogus")
    assert ES.mode(env) == "record"
    _mode(env, "off")
    _final(env, 1, 3, "pass")
    ES.compute(RUN, env)
    assert not ES.state_path(RUN, env).exists()


def test_owner_final_closes_and_reopen_clears(env):
    _final(env, 2, 5, "fail", ["S3"])
    assert ES.mark_final(RUN, 2, "项目方", root=env)["closed"] is True
    assert ES.closed_eps(RUN, env) == {2}
    r = ES.reopen(RUN, 2, "项目方", "再改改", root=env)
    assert r["closed"] is False and "owner_final" not in r
    audit = [json.loads(x) for x in (env / ES.AUDIT_REL).read_text(encoding="utf-8").splitlines()]
    assert [a["action"] for a in audit] == ["final", "reopen"]


# ------------------------------------------------------------------ 执行器：挡 / 记
def test_skip_enforce_record_off_and_hourly_throttle(env):
    _final(env, 1, 9, "pass")
    ES.compute(RUN, env)
    _mode(env, "enforce")
    assert ES.skip(RUN, "first:ep01-S2", actor="t", root=env, now=1000.0) is True
    assert ES.skip(RUN, "first:ep01-S2", actor="t", root=env, now=1500.0) is True     # 照挡，不重复记
    assert ES.skip(RUN, "first:ep02-S2", actor="t", root=env, now=1500.0) is False    # 没关闭的集不挡
    assert ES.skip(RUN, "first:ep01-S2", actor="t", root=env, now=1000.0 + 3601) is True
    lg = _skips(env)
    assert len(lg) == 2 and all(x["ev"] == "ep_closed_skip" and x["skipped"] and x["mode"] == "enforce" for x in lg)
    _mode(env, "record")
    assert ES.skip(RUN, "video:ep01-S4", actor="t", root=env, now=9000.0) is False
    assert _skips(env)[-1]["mode"] == "record" and _skips(env)[-1]["skipped"] is False
    _mode(env, "off")
    n = len(_skips(env))
    assert ES.skip(RUN, "video:ep01-S5", actor="t", root=env, now=9000.0) is False and len(_skips(env)) == n


def _producer(env, monkeypatch, dispatched):
    import producer as PR
    paths = PR.Paths(root=env, pd=env / "data/producer/runs" / RUN)
    monkeypatch.setattr(paths, "run_id", RUN, raising=False)
    lanes = {"gpu33:0": "fake://0", "gpu33:1": "fake://1", "gpu36:0": "fake://2"}
    pr = PR.Producer(paths, script=object(), lanes=lanes, lane_probe=lambda url: {"ok": True, "n": 0, "agents": []})
    for k, v in {"higher_priority_busy": lambda p: None, "decision_file_problems": lambda r: [], "local_only_shots": lambda s: set(),
                 "adult_shot_ids": lambda s: set(), "owner_trigger_ids": lambda p: set(),
                 "asset_hold_objects": lambda *a: set()}.items():
        monkeypatch.setattr(PR, k, v)
    for k, v in {"sop_gate_block": lambda o: False, "hard_capped": lambda o: False, "obj_rate_exceeded": lambda o, c: False,
                 "lanes_allowed": lambda o, free: list(free), "rung_strategy": lambda *a: None, "rung_ab": lambda *a: None,
                 "rung": lambda o, a: {"name": "第 1 次", "seed": 1}, "dispatch_fanout": lambda c, f: None, "logf": lambda *a, **k: None}.items():
        monkeypatch.setattr(pr, k, v)

    class Pool:
        def submit(self, fn, o, *a):
            dispatched.append(o["id"])
    pr.pool = Pool()
    pr._dispatch_only = None
    return pr


def _reg():
    def S(ep, i):
        o = {"id": f"first:ep{ep:02d}-S{i}", "shot": f"ep{ep:02d}-S{i}", "kind": "first", "ep": ep, "status": "ready"}
        return {"shot": o["shot"], "index": i, "objects": {"first": o, "last": {**o, "id": f"last:{o['shot']}", "kind": "last", "status": "pending"}}}
    return {"episodes": [{"ep": 1, "shots": [S(1, 1)]}, {"ep": 2, "shots": [S(2, 1)]}]}


@pytest.mark.parametrize("m,want", [("enforce", ["first:ep02-S1"]), ("record", ["first:ep01-S1", "first:ep02-S1"]),
                                    ("off", ["first:ep01-S1", "first:ep02-S1"])])
def test_producer_dispatch_frames_closed(env, monkeypatch, m, want):
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    _mode(env, m)
    got = []
    pr = _producer(env, monkeypatch, got)
    pr._ep_closed = pr.ep_closed_now()
    lanes = {ln: {"free": True} for ln in ("gpu33:0", "gpu33:1")}
    pr.dispatch_frames(_reg(), lanes, {"hold_lanes": []})
    assert sorted(got) == want
    assert "gpu33:2" not in str(pr.lane_busy)
    lg = _skips(env)
    if m == "off":
        assert lg == []
    else:
        assert [x["obj"] for x in lg] == ["first:ep01-S1"] and lg[0]["skipped"] is (m == "enforce")


def test_producer_rescore_closed_enforce(env, monkeypatch):
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    _mode(env, "enforce")
    pr = _producer(env, monkeypatch, [])
    pr._ep_closed = pr.ep_closed_now()
    monkeypatch.setattr(pr, "_rescore_dispatchable", lambda o: 2 if o["status"] == "ready" else None)
    subs = []

    class RP:
        def submit(self, fn, o, rt):
            subs.append(o["id"])
            return type("F", (), {"done": lambda s: False})()
    pr.rescore_pool = RP()
    assert pr.dispatch_rescores(_reg()) == 1 and subs == ["first:ep02-S1"]


# ------------------------------------------------------------------ 视频侧
def test_vidgen_jobs_skip_closed(env, monkeypatch):
    import run_ctx as RC
    import vidgen as V
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    monkeypatch.setattr(RC, "ROOT", env)
    monkeypatch.setitem(RC.__dict__, "_ES", ES)
    vid = env / "vid"
    _w(vid / "jobs.json", {"shots": [{"ep": 1, "shot": "ep01-S1", "host": "gpu36"}, {"ep": 2, "shot": "ep02-S1", "host": "gpu36"}]})
    _w(vid / "control_gpu36.json", {"jobs": "jobs.json", "eps": [1, 2]})
    monkeypatch.setattr(V, "VID", vid)
    monkeypatch.setattr(V, "RUN_ID", RUN)
    monkeypatch.setattr(V, "_claims", lambda: {})
    r = object.__new__(V.Runner)
    r.host, r.ctrl_p, r.st = "gpu36", vid / "control_gpu36.json", {"shots": {}}
    for m, want in (("enforce", ["ep02-S1"]), ("record", ["ep01-S1", "ep02-S1"])):
        _mode(env, m)
        assert sorted(r.jobs()[0]) == want
    assert any(x["actor"] == "vidgen" for x in _skips(env))


def test_night_wired():
    import night as N   # noqa: PLC0415
    assert "closed_skip" in inspect.getsource(N.loop_once) and "closed_skip" in inspect.getsource(N.dispatch_hosts)
    assert "enforce_closed" in inspect.getsource(N.roles_for_host)


# ------------------------------------------------------------------ L-207
def test_lane_roles_closed_not_active(env):
    import lane_roles_producer as LRO
    reg = {"run": RUN, "episodes": []}
    stages = {1: "frames", 2: "frames"}
    out = dict(stages)
    for ep in {1}:
        out[ep] = "done"
    assert LRO.active_episode(out)["ep"] == 2
    # 直接走 episode_stages：closed 参数 + 现读（enforce）
    cfg = {"enabled": True, "from_episode": 1}
    E = lambda ep: {"ep": ep, "shots": [{"shot": f"ep{ep:02d}-S1", "objects": {"first": {"status": "ready"}, "last": {"status": "pending"},
                                                                          "video": {"status": "pending"}}}], "objects": {}}
    reg["episodes"] = [E(1), E(2)]
    st = LRO.episode_stages(reg, cfg, closed={1})
    assert st[1] == "done" and LRO.active_episode(st)["ep"] == 2
    st0 = LRO.episode_stages(reg, cfg, closed=set())
    assert LRO.active_episode(st0)["ep"] == 1


def test_lane_roles_closed_enforced_reads_mode(env):
    import lane_roles_producer as LRO
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    _mode(env, "record")
    assert LRO.closed_enforced(RUN, env) == set()
    _mode(env, "enforce")
    assert LRO.closed_enforced(RUN, env) == {1}


# ------------------------------------------------------------------ 重开
def _close1(env):
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    assert ES.closed_eps(RUN, env) == {1}


def test_reopen_on_owner_redo(env):
    pd = env / "data/producer/runs" / RUN
    _w(pd / "master_rejects.json", {"first:ep01-S2": {"by": "界面修改（项目方）", "at": "2026-11-07T01:00:00", "reject_n": 0,
                                                      "edit": {"text": "旧的"}}})
    _close1(env)                                       # 关闭前已有的修改不触发重开
    ES.compute(RUN, env)
    assert ES.closed_eps(RUN, env) == {1}
    rj = json.loads((pd / "master_rejects.json").read_text(encoding="utf-8"))
    rj["first:ep02-S1"] = {"by": "界面修改（项目方）", "at": "2026-11-07T04:00:00", "reject_n": 0, "edit": {"text": "别集"}}
    rj["first:ep01-S3"] = {"by": "AUTO_REGEN", "at": "2026-11-07T04:00:00", "reject_n": 0}      # 系统自己的不算项目方
    _w(pd / "master_rejects.json", rj)
    assert ES.compute(RUN, env)["closed"] == [1]
    rj["last:ep01-S5"] = {"by": "界面修改（项目方）", "at": "2026-11-07T04:10:00", "reject_n": 0, "edit": {"text": "改"}}
    _w(pd / "master_rejects.json", rj)
    d = ES.compute(RUN, env)
    assert d["closed"] == [] and d["episodes"]["1"]["reopened"]["source"] == "auto" and "last:ep01-S5" in d["episodes"]["1"]["why"]
    assert ES.compute(RUN, env)["closed"] == []        # 重开一直有效
    _final(env, 1, 5, "pass")                          # 出了新一版过闸成片 → 再次关闭
    assert ES.compute(RUN, env)["closed"] == [1]


def test_reopen_on_adult_trigger(env):
    pd = env / "data/producer/runs" / RUN
    _w(pd / "owner_triggers.json", {"objects": ["first:ep01-S1"]})
    _close1(env)
    _w(pd / "owner_triggers.json", {"objects": ["first:ep01-S1", "first:ep02-S4"]})
    assert ES.compute(RUN, env)["closed"] == [1]
    _w(pd / "owner_triggers.json", {"objects": ["first:ep01-S1", "first:ep02-S4", "first:ep01-S6", "last:ep01-S6"]})
    d = ES.compute(RUN, env)
    assert d["closed"] == [] and "ep01-S6" in d["episodes"]["1"]["why"]


def test_reopen_api_owner_only_and_audited(env, monkeypatch):
    from ns_api import auth
    from ns_api import episode_reopen as ER
    _close1(env)
    monkeypatch.setattr(ER, "REPO", env)
    monkeypatch.setattr(ER, "_es", lambda: ES)
    monkeypatch.setattr(ER, "_run_of", lambda run: RUN)
    pushed = []
    monkeypatch.setattr(ER, "_push", lambda: pushed.append(1))
    app = FastAPI()
    app.include_router(ER.router)
    for user in (None, {"name": "查看者", "role": "viewer"}, {"name": "agent", "role": "agent"}):
        monkeypatch.setattr(auth, "user_of", lambda request, u=user: u)
        assert TestClient(app).post("/api/owner/episode-reopen", json={"ep": 1}).status_code == 403
    assert ES.closed_eps(RUN, env) == {1} and not (env / ES.AUDIT_REL).exists()
    monkeypatch.setattr(auth, "user_of", lambda request: {"name": "项目方", "role": "owner"})
    r = TestClient(app).post("/api/owner/episode-reopen", json={"ep": 1, "why": "S3 再改"})
    assert r.status_code == 200 and r.json()["state"]["closed"] is False and pushed == [1]
    a = json.loads((env / ES.AUDIT_REL).read_text(encoding="utf-8").splitlines()[-1])
    assert a["by"] == "项目方" and a["action"] == "reopen" and a["ep"] == 1
    assert TestClient(app).get("/api/owner/episode-state").json()["episodes"]["1"]["closed"] is False


def test_api_registered_in_app():
    src = (ROOT / "services/api/ns_api/app.py").read_text(encoding="utf-8")
    assert "episode_reopen as EPREOPEN" in src and "app.include_router(EPREOPEN.router)" in src


def test_cli_reopen_requires_by(env, monkeypatch, capsys):
    _close1(env)
    monkeypatch.setattr(ES, "ROOT", env)
    with pytest.raises(SystemExit):
        ES._cli(["reopen", "--run", RUN, "--ep", "1"])
    assert ES._cli(["reopen", "--run", RUN, "--ep", "1", "--by", "PS-MASTER（项目方对话指示）"]) == 0
    assert ES.closed_eps(RUN, env) == set()


# ------------------------------------------------------------------ 推送通道
def test_control_files_and_overwrite_and_no_pullback():
    import resident_sync as RS
    files = RS.control_files()
    assert any(f.endswith(f"data/pipeline/runs/{RS.RUN_ID}/episode_state.json") for f in files)
    assert 'rel.endswith("/episode_state.json")' in RS.REMOTE_MERGE
    assert "episode_state_tick()" in inspect.getsource(RS.push_control)
    import merge_pull as MP
    assert "episode_state.json" in MP.SKIP_NAMES


def test_remote_merge_overwrites_snapshot(tmp_path):
    import subprocess
    import resident_sync as RS
    rel = f"data/pipeline/runs/{RUN}/episode_state.json"
    dst = tmp_path / rel
    _w(dst, {"episodes": {"1": {"closed": True, "reopened_at": "2099-01-01T00:00:00"}}, "closed": [1]})
    src = tmp_path / "src.json"
    _w(src, {"episodes": {"1": {"closed": False}}, "closed": []})
    code = tmp_path / "m.py"
    code.write_text(RS.REMOTE_MERGE.replace("__R__", str(tmp_path).replace("\\", "/")), encoding="utf-8")
    subprocess.run([sys.executable, str(code), rel, str(src)], check=True, capture_output=True, timeout=60)
    assert json.loads(dst.read_text(encoding="utf-8")) == {"episodes": {"1": {"closed": False}}, "closed": []}


def test_never_touches_gpu33_2():
    for f in ("tools/autopilot/episode_state.py", "services/api/ns_api/episode_reopen.py"):
        assert "gpu33:2" not in (ROOT / f).read_text(encoding="utf-8")


# ------------------------------------------------------------------ Fable 复审修正
def test_lip_redo_assembly_not_closed(env):
    d = env / "data/episodes" / RUN
    _final(env, 1, 8, "pass")
    _w(d / "ep01_v8.timeline.json", {"episode": 1, "gates": {"verdict": "pass"}, "shots": [{"index": 2, "shot": "ep01-S2"}],
                                     "speech": [{"shot": 2, "kind": "dialogue"}],
                                     "h3_dialogue": [{"shot": 2, "dialogue": "tts_fallback", "fallback_reason": "x"}]})
    r = ES.compute(RUN, env)
    assert r["closed"] == [] and "口型" in r["episodes"]["1"]["why"] and r["episodes"]["1"]["assembly"]["lip_redo"] == ["ep01-S2"]


def test_reopen_survives_cross_process_race(env):
    """API 写了审计 + 状态，resident_sync 拿着旧快照把状态盖回去 → 下一次 compute 按审计补回重开"""
    _close1(env)
    stale = json.loads(ES.state_path(RUN, env).read_text(encoding="utf-8"))
    ES.reopen(RUN, 1, "项目方", "改", root=env)
    assert ES.closed_eps(RUN, env) == set()
    _w(ES.state_path(RUN, env), stale)                 # 另一进程用旧快照写回（丢了重开）
    assert ES.closed_eps(RUN, env) == {1}
    d = ES.compute(RUN, env)
    assert d["closed"] == [] and d["episodes"]["1"]["reopened"]["by"] == "项目方"
    _final(env, 1, 5, "pass")                          # 新一版过闸 → 关闭，旧审计不再重放
    assert ES.compute(RUN, env)["closed"] == [1]
    assert ES.compute(RUN, env)["closed"] == [1]


def test_final_replayed_from_audit(env):
    _final(env, 2, 3, "fail", ["S1"])
    ES.compute(RUN, env)
    ES.mark_final(RUN, 2, "项目方", root=env)
    ES.state_path(RUN, env).unlink()                   # 状态丢了
    assert ES.compute(RUN, env)["closed"] == [2]


def test_laptop_only_guard(env, monkeypatch):
    _close1(env)
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    with pytest.raises(RuntimeError):
        ES.reopen(RUN, 1, "x", root=env)
    with pytest.raises(RuntimeError):
        ES.mark_final(RUN, 1, "x", root=env)
    monkeypatch.setattr(ES, "ROOT", env)
    assert ES._cli(["reopen", "--run", RUN, "--ep", "1", "--by", "x"]) == 2
    assert ES._cli(["final", "--run", RUN, "--ep", "1", "--by", "x"]) == 2
    assert ES.closed_eps(RUN, env) == {1} and not (env / ES.AUDIT_REL).exists()


def test_producer_es_import_failure_logged_once(env, monkeypatch):
    import producer as PR
    logs = []
    pr = _producer(env, monkeypatch, [])
    monkeypatch.setattr(pr, "logf", lambda ev, **k: logs.append(ev))
    monkeypatch.setitem(PR._ES_FAIL, "err", "ImportError('x')")
    monkeypatch.setitem(PR._ES_FAIL, "t", PR.time.time())
    for _ in range(50):
        assert pr.ep_closed_skip("first:ep01-S1", "frames") is False
    assert pr.ep_closed_now() == set()
    assert logs.count("ep_closed_err") == 1


def test_producer_mode_read_once_per_tick(env, monkeypatch):
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    _mode(env, "enforce")
    pr = _producer(env, monkeypatch, [])
    pr._ep_closed = pr.ep_closed_now()
    n = []
    real = ES.mode
    monkeypatch.setattr(ES, "mode", lambda root=None: n.append(1) or real(root))
    for _ in range(20):
        assert pr.ep_closed_skip("first:ep01-S1", "frames") is True
    assert n == []


def test_take_sig_closed_not_starving_open(env, monkeypatch):
    """复审 1：enforce 下关闭集的镜不进 check_run（不占每拍换代名额）；单独报 sig_stale_closed，变化时记一条"""
    import producer as PR
    import take_sig as TS
    _final(env, 1, 4, "pass")
    ES.compute(RUN, env)
    _mode(env, "enforce")
    _w(env / "config/pipeline/state.json", {"take_sig": {"mode": "enforce", "every_s": 0}, ES.KEY: {"mode": "enforce"}})
    logs = []
    pr = _producer(env, monkeypatch, [])
    monkeypatch.setattr(pr, "logf", lambda ev, **k: logs.append((ev, k)))
    pr._ep_closed = pr.ep_closed_now()
    monkeypatch.setattr(PR, "shots_of_all", lambda p: ["ep01-S1", "ep01-S2", "ep02-S1"])
    monkeypatch.setattr(pr, "script", lambda: object())
    seen = []

    def fake_check(root, run, shots, load_takes, *, mode, log, **k):
        seen.append((list(shots), mode))
        return {"mode": mode, "stale": {"first": len(shots), "last": 0, "video": 0}, "unknown": {}, "regen": [], "skipped": {}}
    monkeypatch.setattr(TS, "check_run", fake_check)
    monkeypatch.setattr(TS, "cfg", lambda root: {"mode": "enforce", "every_s": 0, "max_regen_per_tick": 2, "max_pending": 6,
                                                 "unknown_unrecoverable": "leave"})
    hb = pr.take_sig_tick()
    assert seen[0] == (["ep02-S1"], "enforce")              # 关闭集的镜不进换代
    assert seen[1] == (["ep01-S1", "ep01-S2"], "record")    # 关闭集只算不换
    assert pr._take_sig_hb["sig_stale_closed"] == {"1": 2} and hb
    pr._take_sig_chk = 0
    pr.take_sig_tick()
    assert [e for e, _ in logs].count("sig_stale_closed") == 1      # 没变化不重复记
    _mode(env, "record")
    pr._ep_closed = pr.ep_closed_now()
    seen.clear()
    pr._take_sig_chk = 0
    pr.take_sig_tick()
    assert seen[0][0] == ["ep01-S1", "ep01-S2", "ep02-S1"]   # record 行为不变
