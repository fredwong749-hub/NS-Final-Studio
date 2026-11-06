"""W7 基础设施韧性（K-OPS-W05 / W06 / W07，WORKFLOW 11-01）：
- infra_watchdog：隧道只探测、只报警（修复归 NETFIX tunnel_supervisor，SYSARCH 4-3 删了旧修复段）；空转 / night / producer 报警开关只记一次；
- resident_sync：清单比对只发不同 / 被截断的文件，跳过 pid / 租约 / control 等本机状态，分批不超上限。
全部打桩，不连服务器、不写真实 data/。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import infra_watchdog as W  # noqa: E402
import resident_sync as RS  # noqa: E402


def _stub(monkeypatch, tmp_path, up: set, relay_ok=True, dispatchable=()):
    killed, alerts = [], []
    monkeypatch.setattr(W, "probe", lambda p, path="/system_stats", timeout=6: ({} if path == "/system_stats" else
                                                                                 {"queue_running": [], "queue_pending": []}) if p in up else None)
    monkeypatch.setattr(W, "queue_len", lambda p: 0 if p in up else None)
    monkeypatch.setattr(W, "dispatchable_shots", lambda: list(dispatchable))
    monkeypatch.setattr(W, "_append", lambda rec: alerts.append(rec))
    monkeypatch.setattr(W, "log", lambda *a: None)
    monkeypatch.setattr(W, "VID", tmp_path)
    monkeypatch.setattr(W, "ROOT", tmp_path)
    import socket

    def conn(addr, timeout=8):
        if not relay_ok:
            raise OSError("down")
        class C:
            def close(self):
                pass
        return C()
    monkeypatch.setattr(socket, "create_connection", conn)
    return killed, alerts


def test_tunnel_down_alerts_but_never_repairs(monkeypatch, tmp_path):
    """SYSARCH 4-3：看门狗只报警不修；连续 ALERT_AFTER 拍不通才开 A-TUNNEL，恢复即关"""
    up = set(W.TUNNELS) - {18188}
    killed, alerts = _stub(monkeypatch, tmp_path, up)
    assert not hasattr(W, "kill") and not hasattr(W, "start_loop")     # 修复段已删
    st = {}
    for i in range(W.ALERT_AFTER):
        st = W.tick(st, now=1000.0 + 30 * i)
    assert st["fails"]["18188"] == W.ALERT_AFTER and st["fails"]["18288"] == 0
    assert [a["id"] for a in alerts if a["state"] == "open" and a["id"].startswith("A-TUNNEL-1")] == ["A-TUNNEL-18188"]
    monkeypatch.setattr(W, "probe", lambda p, path="/system_stats", timeout=6: {} if path == "/system_stats" else {"queue_running": [], "queue_pending": []})
    monkeypatch.setattr(W, "queue_len", lambda p: 0)
    st = W.tick(st, now=2000.0)
    assert any(a["id"] == "A-TUNNEL-18188" and a["state"] == "closed" for a in alerts)


def test_relay_down_no_kill_and_alert(monkeypatch, tmp_path):
    killed, alerts = _stub(monkeypatch, tmp_path, set(), relay_ok=False)
    st = {}
    for i in range(3):
        st = W.tick(st, now=2000.0 + 30 * i)
    assert killed == [] and any(a["id"] == "A-RELAY" and a["state"] == "open" for a in alerts)


def test_idle_alert_opens_once_and_closes(monkeypatch, tmp_path):
    killed, alerts = _stub(monkeypatch, tmp_path, set(W.TUNNELS), dispatchable=["ep02-S3"])
    st = {}
    for i in range(25):                               # 12.5 分钟全空闲 + 有可派镜
        st = W.tick(st, now=3000.0 + 30 * i)
    opened = [a for a in alerts if a["id"] == "A-IDLE" and a["state"] == "open"]
    assert len(opened) == 1
    monkeypatch.setattr(W, "dispatchable_shots", lambda: [])
    st = W.tick(st, now=4000.0)
    assert any(a["id"] == "A-IDLE" and a["state"] == "closed" for a in alerts)


def test_resident_push_diff_and_skip():
    loc = {"tools/a.py": (10, 200.0), "tools/b.py": (10, 100.0), "data/x.png": (100, 50.0), "data/y.png": (100, 50.0)}
    rem = {"tools/a.py": (10, 100.0), "tools/b.py": (10, 100.0), "data/x.png": (40, 60.0)}   # x 远端是截断
    assert RS.diff_push(loc, rem) == ["data/x.png", "data/y.png", "tools/a.py"]
    for rel in ("data/producer/control.json", "data/producer/leases/a.json", "data/producer/heartbeat.json",
                "ops/logs/tunnel.log", "data/_offline_pull/gpu33/x", "tools/__pycache__/a.pyc"):
        assert RS.skipped(rel), rel
    assert not RS.skipped("data/renders/ep01/S1/takes.json")
    b = RS.batches(["a", "b", "c"], {"a": (RS.BATCH - 1,), "b": (10,), "c": (10,)})
    assert b == [["a"], ["b", "c"]]


def test_resident_mode_suppresses_laptop_alarms(monkeypatch, tmp_path):
    killed, alerts = _stub(monkeypatch, tmp_path, set(W.TUNNELS), dispatchable=["ep02-S3"])
    (tmp_path / "data/producer").mkdir(parents=True)
    (tmp_path / "data/producer/control.json").write_text('{"paused": true, "paused_by": "SERVER_RESIDENT"}', encoding="utf-8")
    st = {}
    for i in range(30):
        st = W.tick(st, now=5000.0 + 30 * i)
    assert st["resident"] and not any(a["id"] in ("A-IDLE", "A-NIGHT", "A-PROD") and a["state"] == "open" for a in alerts)


def test_push_tiers_and_warn(monkeypatch):
    assert RS.tier_of("tools/a.py", 1000) == 1 and RS.tier_of("config/x.json", 1000) == 1
    assert RS.tier_of("tools/big.json", 5 * 1024 * 1024) == 2
    assert RS.tier_of("data/pipeline/runs/series10_v1/assets/first_frame_jobs.json", 1400000) == 1
    assert RS.tier_of("data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png", 200000) == 1
    assert RS.tier_of("data/renders/ep01/S1/takes/image_004.png", 2000000) == 2
    est = RS.estimate(["a", "b"], {"a": (15_000_000, 0), "b": (10_000_000, 0)})
    assert est["mb"] == 25.0 and est["eta_min"] == round(25.0 * 1000 / RS.LINK_KBPS / 60, 1)   # FIX-ORCH O4：LINK_KBPS 按实测（不写死旧值）
    # 超过 20 MB 不带 yes：只报估计，不推
    monkeypatch.setattr(RS, "ssh", lambda *a, **k: b"0")
    monkeypatch.setattr(RS, "log", lambda *a: None)
    monkeypatch.setattr(RS, "STATE", Path(__file__).parent / "__no_state__.json")
    monkeypatch.setattr(RS, "required_data", lambda: set())
    monkeypatch.setattr(RS, "local_manifest", lambda dirs: {"tools/a.py": (25_000_000, 10.0)})
    monkeypatch.setattr(RS, "tier_of", lambda rel, size: 1)
    monkeypatch.setattr(RS, "remote_manifest", lambda h, d: {})
    r = RS.push("gpu33", tier=1, gate=False)              # push_gate 另有 tools/qa/push_check.py 自己的测试
    assert r["blocked"] == "over_warn" and r["sent"] == 0


def test_verify_sha_detects_and_repushes(monkeypatch, tmp_path):
    """K-OPS-W09（总调度 18:5x）：第一级推送逐个核 sha；不一致的强制重推后再核"""
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "log", lambda *a: None)
    monkeypatch.setattr(RS, "js", lambda p, d: None)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/a.py").write_text("print(1)\n")
    (tmp_path / "tools/b.py").write_text("print(2)\n")
    good = {f: RS.local_sha(f) for f in ("tools/a.py", "tools/b.py")}
    remote = {"tools/a.py": good["tools/a.py"], "tools/b.py": "0" * 64}
    pushed = []

    def fake_ssh(host, cmd, data=None, **kw):
        if "sha256sum" in cmd:
            names = data.decode().split("\n")
            return "".join(f"{remote[n]}  {n}\n" for n in names if n in remote).encode()
        pushed.append(cmd)
        remote["tools/b.py"] = good["tools/b.py"]           # 重推后服务器上对了
        return b"ok"
    monkeypatch.setattr(RS, "ssh", fake_ssh)
    r = RS.verify_sha("gpu33", ["tools/a.py", "tools/b.py"])
    assert r["mismatch"] == [] and r["fixed"] == ["tools/b.py"] and len(pushed) == 1


def test_pull_handed_to_puller_when_acked_grows(monkeypatch, tmp_path):
    """NETFIX 01:5x：puller 的 acked_total 增长之后，resident_sync 停掉该台的 20 分钟定时 pull（之前两者并存，merge 幂等）"""
    import json as _j
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(RS, "log", lambda *a: None)
    (tmp_path / "data/netfix").mkdir(parents=True)
    ps = tmp_path / "data/netfix/puller_status.json"
    ps.write_text(_j.dumps({"hosts": {"gpu36": {"acked_total": 0}}}), encoding="utf-8")
    assert RS.puller_took_over("gpu36") is False          # 记基线
    assert RS.puller_took_over("gpu36") is False          # 没增长
    ps.write_text(_j.dumps({"hosts": {"gpu36": {"acked_total": 3}}}), encoding="utf-8")
    assert RS.puller_took_over("gpu36") is True
    ps.write_text(_j.dumps({"hosts": {"gpu36": {"acked_total": 3}}}), encoding="utf-8")
    assert RS.puller_took_over("gpu36") is True           # 一旦接管就一直停


def test_restart_queue_merges_gaps_and_urgent(monkeypatch, tmp_path):
    """DJ-20：同一台 30 分钟内最多执行一次、合并多条请求；紧急请求可插队并记审计；执行前先排空"""
    import restart_queue as RQ
    monkeypatch.setattr(RQ, "REQ", tmp_path / "req.jsonl")
    monkeypatch.setattr(RQ, "DONE", tmp_path / "done.jsonl")
    monkeypatch.setattr(RS, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(RS, "log", lambda *a: None)
    calls = []
    monkeypatch.setattr(RS, "ssh", lambda h, cmd, **k: calls.append(cmd) or (b'{"0": [0, 0], "1": [0, 0]}' if cmd == "python3 -" else
                                                                       b'{"paused_by": null}' if 'base64 -d)" ' in cmd else b"ok"))   # pause_state：没被别人暂停
    monkeypatch.setattr(RS, "restart", lambda h, mode=None: calls.append("RESTART") or "started")
    RQ.request("gpu36", "deploy sv-1", "FACTORY")
    RQ.request("gpu36", "代码推送", "WORKFLOW")
    r1 = RQ.process("gpu36")
    assert r1["ok"] and len(r1["request_ids"]) == 2 and calls.count("RESTART") == 1 and any("pause" in c for c in calls)
    RQ.request("gpu36", "又一次", "NETFIX")
    assert RQ.process("gpu36") is None and calls.count("RESTART") == 1          # 30 分钟内：留着不执行
    RQ.request("gpu36", "服务器卡死", "总调度", urgent=True)
    r3 = RQ.process("gpu36")
    assert r3["urgent_jump"] is True and calls.count("RESTART") == 2 and len(r3["request_ids"]) == 2
    assert RQ.pending("gpu36") == []


def test_restart_drain_ignores_scoring_backlog_and_caps(monkeypatch):
    """总调度 04:1x（K-OPS-W23）：排空只看 ComfyUI 执行中 + 排队；打分积压不算；前 60 s 等全空，之后只等当前单，90 s 上限照常重启"""
    import restart_queue as RQ
    t = {"now": 0.0}
    clock = lambda: t["now"]                                  # noqa: E731
    def sleep(s):
        t["now"] += s
    seq = []
    monkeypatch.setattr(RQ, "comfy_queue", lambda h, rs: seq.pop(0) if seq else {"0": [1, 3]})
    # ① 立刻全空（打分积压 42 与此无关，根本不读 heartbeat）
    seq[:] = [{"0": [0, 0], "1": [0, 0]}]
    r = RQ.drain("gpu33", RS, sleep=sleep, clock=clock)
    assert r["drained"] and r["drain_mode"] == "full" and r["drain_s"] == 0
    # ② 一直有排队、执行中在 60 s 后清零 → current_only
    t["now"] = 0.0
    seq[:] = [{"0": [1, 2]}] * 6 + [{"0": [0, 2]}]
    r = RQ.drain("gpu33", RS, sleep=sleep, clock=clock)
    assert r["drained"] and r["drain_mode"] == "current_only" and 60 <= r["drain_s"] <= 90
    # ③ 一直在执行 → 90 s 上限，照常往下走
    t["now"] = 0.0
    seq[:] = []
    r = RQ.drain("gpu33", RS, sleep=sleep, clock=clock)
    assert r["drained"] is False and r["drain_mode"] == "timeout" and r["drain_s"] <= RQ.DRAIN_MAX_S + RQ.DRAIN_POLL_S
    assert "heartbeat" not in RQ.process.__code__.co_consts.__repr__()


def test_tunnel_flap_alert(monkeypatch, tmp_path):
    """13:2x 探针缺口：道断几十秒又恢复、凑不够连续 ALERT_AFTER 拍 → 也要报 A-TUNNEL-FLAP；半数道同时不通立刻报"""
    killed, alerts = _stub(monkeypatch, tmp_path, set(W.TUNNELS))
    st = {}
    for i in range(W.FLAP_WINDOW):
        up = set(W.TUNNELS) - ({18188} if i % 2 == 0 else set())          # 18188 隔拍断一次
        monkeypatch.setattr(W, "probe", lambda p, path="/system_stats", timeout=6, up=up: ({} if path == "/system_stats" else {"queue_running": [], "queue_pending": []}) if p in up else None)
        monkeypatch.setattr(W, "queue_len", lambda p, up=up: 0 if p in up else None)
        st = W.tick(st, now=5000.0 + 30 * i)
    ids = [a["id"] for a in alerts if a["state"] == "open"]
    assert "A-TUNNEL-FLAP" in ids and "A-TUNNEL-18188" not in ids                # 连续不够，但抖动报了
    killed2, alerts2 = _stub(monkeypatch, tmp_path, {18188, 18189})              # 5 条里 3 条同时不通
    st2 = W.tick({}, now=6000.0)
    assert any(a["id"] == "A-TUNNEL-FLAP" and a["state"] == "open" for a in alerts2)


# ---------------------------------------------------------------- W12 RESIDENT-RELOAD（C-02）：常驻每拍重载 asset_worker 时依赖整组一致 + 失败关闭可见
# 事故 11-03 04:56：W8 改 asset_worker 读 sop_gate.BACKOFF_S，常驻进程里 sop_gate 是早先缓存的旧版不重载 → 每拍 AttributeError，资产线全停

def _w12_load(name, rel):
    import importlib.util as _u
    sp = _u.spec_from_file_location(name, ROOT / rel)
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _w12_stale(monkeypatch, name: str, rel: str):
    """在 sys.modules 里放一份“进程早先 import 的旧版”：__file__ / __spec__ 指向真实源文件，但缺新符号、没有版本戳"""
    import importlib.util as _u
    import types
    m = types.ModuleType(name)
    m.__file__ = str(ROOT / rel)
    m.__spec__ = _u.spec_from_file_location(name, ROOT / rel)
    monkeypatch.setitem(sys.modules, name, m)
    return m


def test_w12_resident_asset_tick_survives_stale_dependency(monkeypatch, tmp_path):
    """复现：依赖模块（sop_gate / asset_jobs）新增符号、顶层 asset_worker 引用它，常驻进程里缓存的是旧依赖 →
    修复后载入 asset_worker 会按版本戳把依赖重载到当前代码，不再 AttributeError；asset_tick 不出 error"""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    import tools.master  # noqa: F401  父包先在
    sg = _w12_stale(monkeypatch, "tools.master.sop_gate", "tools/master/sop_gate.py")
    aj = _w12_stale(monkeypatch, "asset_jobs", "tools/pipeline/asset_jobs.py")
    assert not hasattr(sg, "BACKOFF_S") and not hasattr(aj, "jobs_dir")       # 旧版：缺 asset_worker 顶层要引用的符号
    AW = _w12_load("asset_worker_w12", "tools/pipeline/asset_worker.py")      # 修复前：这里 AttributeError BACKOFF_S
    assert sys.modules["tools.master.sop_gate"] is sg and hasattr(sg, "BACKOFF_S")   # 同一模块对象就地更新
    assert hasattr(aj, "jobs_dir") and set(AW.RELOADED_DEPS) >= {"tools.master.sop_gate", "asset_jobs"}
    assert AW.SOP_BACKOFF_S == sg.BACKOFF_S
    AW2 = _w12_load("asset_worker_w12b", "tools/pipeline/asset_worker.py")    # 下一拍：文件没变 → sop_gate 不再重载（asset_jobs 按原口径每次重载）
    assert "tools.master.sop_gate" not in AW2.RELOADED_DEPS
    # 常驻 asset_tick 走同一条载入路径：不出 error（tick 本体打桩，不碰真实作业）
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import autoflow_resident as AR

    class FakeAW:
        RELOADED_DEPS = ["tools.master.sop_gate"]

        @staticmethod
        def active_runs(root):
            return {"v2": 1}

        @staticmethod
        def tick(runs=None):
            return {"started": ["v2/j1"]}
    r = AR.asset_tick(["v2"], aw=FakeAW)
    assert "error" not in r and r["started"] == ["v2/j1"] and r["reloaded_deps"] == ["tools.master.sop_gate"]


def test_w12_sync_deps_version_stamp(tmp_path, monkeypatch):
    """版本戳：没戳 → 重载并记戳；戳一致 → 不动；文件变了 → 重载；fresh 只记戳；重载失败原样外抛且不更新戳（下一拍再试）"""
    import importlib.util as _u
    import os
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    AW = _w12_load("asset_worker_w12c", "tools/pipeline/asset_worker.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    dep = tmp_path / "w12dep.py"
    dep.write_text("A = 1\n", encoding="utf-8")
    sp = _u.spec_from_file_location("w12dep", dep)
    m = _u.module_from_spec(sp)
    mods = {"w12dep": m}
    sys.modules["w12dep"] = m
    try:
        sp.loader.exec_module(m)
        deps = {"w12dep": "w12dep.py"}
        assert AW.sync_deps(deps, root=tmp_path, modules=mods, fresh={"w12dep"}) == []   # 刚 import：只记戳
        assert AW.sync_deps(deps, root=tmp_path, modules=mods) == []                      # 没变
        dep.write_text("A = 1\nBACKOFF_S = (60, 120)\n", encoding="utf-8")
        st = dep.stat()
        os.utime(dep, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        assert AW.sync_deps(deps, root=tmp_path, modules=mods) == ["w12dep"] and m.BACKOFF_S == (60, 120)
        dep.write_text("A = (\n", encoding="utf-8")                                       # 坏代码
        os.utime(dep, ns=(st.st_atime_ns, st.st_mtime_ns + 2 * 10**9))
        try:
            AW.sync_deps(deps, root=tmp_path, modules=mods)
            raise AssertionError("坏代码应失败关闭")
        except SyntaxError:
            pass
        dep.write_text("A = 2\nBACKOFF_S = (60, 120)\n", encoding="utf-8")                # 修好：戳没被坏代码更新 → 再试成功
        os.utime(dep, ns=(st.st_atime_ns, st.st_mtime_ns + 3 * 10**9))
        assert AW.sync_deps(deps, root=tmp_path, modules=mods) == ["w12dep"] and m.A == 2
        other = type(m)("w12dep")                                                          # 测试替身（__file__ 不是声明的源文件）不碰
        assert AW.sync_deps(deps, root=tmp_path, modules={"w12dep": other}) == []
    finally:
        sys.modules.pop("w12dep", None)


def test_w12_resident_load_failure_fail_closed_and_visible(monkeypatch, tmp_path):
    """asset_worker 载入失败 → phase=load；连续 ≥3 拍 → 心跳 state=reload_failed + 登记一次 P0 卡点（who=resident）；恢复后清零；master_check ⑥ 显示"""
    import json
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import autoflow_resident as AR
    monkeypatch.setattr(AR, "HEARTBEAT", tmp_path / "hb.json")
    monkeypatch.setattr(AR, "LIFELOG", tmp_path / "life.log")

    def bad_load(name, rel):
        raise AttributeError("module 'tools.master.sop_gate' has no attribute 'BACKOFF_S'")
    monkeypatch.setattr(AR, "_load", bad_load)
    r = AR.asset_tick(["v2"])
    assert r["phase"] == "load" and "BACKOFF_S" in r["error"] and AR.asset_fail_state(r) == "reload_failed"

    seq = [r] * 4 + [{}]
    hbs, reported = [], []

    def tick_fn(procs):
        return {"runs": ["v2"], "started": [], "assets": seq[len(hbs)]}

    def capture(rec):
        hbs.append(dict(rec))
    monkeypatch.setattr(AR, "_write_hb", capture)
    AR.run_loop(1, once=False, tick_fn=tick_fn, sleep=lambda s: None, max_ticks=5,
                reporter=lambda **kw: reported.append(kw) or {"id": "ISS-W12"})
    assert [h.get("state") for h in hbs] == ["ok", "ok", "reload_failed", "reload_failed", "ok"]
    assert [h.get("asset_error_streak") for h in hbs] == [1, 2, 3, 4, None]
    assert len(reported) == 1 and reported[0]["who"] == "resident" and reported[0]["blocking"] and "P0" in reported[0]["what"]
    assert hbs[3]["asset_issue"] == "ISS-W12" and "asset_issue" not in hbs[4]
    assert "恢复" in (tmp_path / "life.log").read_text(encoding="utf-8")
    # 真实 report_issue 写进临时 issues / V2_LIVE（不碰真实 data/）
    RI = _w12_load("report_issue_w12", "tools/master/report_issue.py")
    live = tmp_path / "live.md"
    live.write_text("# LIVE\n", encoding="utf-8")
    iid = AR.report_asset_stuck(r, 3, ["v2"], reporter=lambda **kw: RI.report(**kw, issues=tmp_path / "iss.jsonl", live=live))
    rec = json.loads((tmp_path / "iss.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["id"] == iid and rec["who"] == "resident" and rec["blocking"] and "卡点（resident）" in live.read_text(encoding="utf-8")
    # master_check ⑥
    MC = _w12_load("master_check_w12", "tools/master/master_check.py")
    lines = MC.sec_resident_assets(hbs[3])
    assert len(lines) == 1 and "⚠" in lines[0] and "reload_failed" in lines[0] and "ISS-W12" in lines[0]
    assert MC.sec_resident_assets(hbs[4]) == [] and "未到登记线" in MC.sec_resident_assets(hbs[0])[0]


# ---------------------------------------------------------------- W12b RELOAD-PYC（A12 第 27 轮 P1-1）：同秒 + 同 size 的改动，reload 不能执行 __pycache__ 里的旧字节码
# pyc 头只校验源文件秒级 mtime + size；版本戳（mtime_ns）判出了变化，但不删 pyc 时 importlib.reload 仍执行旧代码（MARK 停在旧值，静默）

def _w12b_write_same_sec(path, text, sec, ns):
    """写源文件并把 mtime 钉在同一秒内的不同纳秒（模拟一秒内两次同长度改动）"""
    import os
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(sec * 10**9 + ns, sec * 10**9 + ns))


def test_w12b_sync_deps_same_second_same_size_reads_new_code(tmp_path, monkeypatch):
    import importlib.util as _u
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    AW = _w12_load("asset_worker_w12b_pyc", "tools/pipeline/asset_worker.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    dep = tmp_path / "w12bdep.py"
    sec = 1_700_000_000
    _w12b_write_same_sec(dep, "MARK = 4\n", sec, 100)
    import importlib
    m = importlib.import_module("w12bdep")
    try:
        pyc = __import__("pathlib").Path(_u.cache_from_source(str(dep)))
        assert m.MARK == 4 and pyc.exists()                    # 旧字节码已落盘（复现前提）
        mods = {"w12bdep": m}
        deps = {"w12bdep": "w12bdep.py"}
        assert AW.sync_deps(deps, root=tmp_path, modules=mods, fresh={"w12bdep"}) == []
        _w12b_write_same_sec(dep, "MARK = 5\n", sec, 200)      # 同秒、同 size
        assert AW.sync_deps(deps, root=tmp_path, modules=mods) == ["w12bdep"]
        assert m.MARK == 5                                       # 修复前：4（reload 执行了旧 pyc）
        _w12b_write_same_sec(dep, "MARK = 6\n", sec, 300)      # 再来一次：reload 刚写的新 pyc 也不能被复用
        assert AW.sync_deps(deps, root=tmp_path, modules=mods) == ["w12bdep"] and m.MARK == 6
    finally:
        sys.modules.pop("w12bdep", None)


def test_w12b_resident_load_same_second_same_size_reads_new_code(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import autoflow_resident as AR
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(AR, "ROOT", tmp_path)
    src = tmp_path / "w12b_res.py"
    sec = 1_700_000_000
    _w12b_write_same_sec(src, "MARK = 4\n", sec, 100)
    assert AR._load("w12b_res_a", "w12b_res.py").MARK == 4
    _w12b_write_same_sec(src, "MARK = 5\n", sec, 200)
    assert AR._load("w12b_res_b", "w12b_res.py").MARK == 5      # 修复前：4


def test_w12b_import_dep_stamps_lazy_dep_no_extra_reload(tmp_path, monkeypatch):
    """A12 P2-2：懒加载的依赖第一次 import 就记戳 → 下一拍 sync_deps 不再因“无戳”多重载一次"""
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    AW = _w12_load("asset_worker_w12b_lazy", "tools/pipeline/asset_worker.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "w12blazy.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(AW, "RELOAD_DEPS", {"w12blazy": "w12blazy.py"})
    try:
        m = AW.import_dep("w12blazy", root=tmp_path)
        assert m.X == 1 and AW.import_dep("w12blazy", root=tmp_path) is m
        assert AW.sync_deps({"w12blazy": "w12blazy.py"}, root=tmp_path) == []
    finally:
        sys.modules.pop("w12blazy", None)


def test_w12b_heartbeat_carries_reloaded_deps(monkeypatch, tmp_path):
    """A12 P2-3：上拍重载了谁写进心跳（不只 life.log）"""
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import autoflow_resident as AR
    hbs = []
    monkeypatch.setattr(AR, "_write_hb", lambda rec: hbs.append(rec))
    monkeypatch.setattr(AR, "life", lambda msg, path=None: None)
    tick = lambda procs: {"started": [], "runs": ["v2"], "assets": {"reloaded_deps": ["asset_jobs", "asset_checks"]}}
    assert AR.run_loop(1, once=True, tick_fn=tick, sleep=lambda s: None) == 0
    assert hbs[-1]["reloaded_deps"] == ["asset_jobs", "asset_checks"] and hbs[-1]["state"] == "ok"
