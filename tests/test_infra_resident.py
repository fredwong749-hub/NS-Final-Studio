"""W7 基础设施韧性（K-OPS-W05 / W06 / W07，WORKFLOW 11-01）：
- infra_watchdog：隧道连续 2 次探测失败才杀 ssh、之后每 4 拍重试；跳板 TCP 不通时不杀；空转 / night / producer 报警开关只记一次；
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
    monkeypatch.setattr(W, "ssh_pids_for", lambda p: [1000 + p])
    monkeypatch.setattr(W, "kill", lambda pid: killed.append(pid))
    monkeypatch.setattr(W, "loop_running", lambda s: True)
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


def test_tunnel_killed_after_two_fails_then_every_four(monkeypatch, tmp_path):
    up = set(W.TUNNELS) - {18188}
    killed, _ = _stub(monkeypatch, tmp_path, up)
    st = {}
    t = 1000.0
    for i in range(7):
        st = W.tick(st, now=t + 30 * i)
    assert killed.count(1000 + 18188) == 2          # 第 2 拍、第 6 拍
    assert st["fails"]["18188"] == 7 and st["fails"]["18288"] == 0


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
    assert est["mb"] == 25.0 and est["eta_min"] > 20
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


def test_loop_ssh_signature_and_orphans():
    """总调度 22:09：手动起的隧道 ssh（不归循环管）要被识别成孤儿接管；循环自己的 ssh 不能误杀"""
    loop36 = '"ssh.exe" -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o IPQoS=throughput -L 18288:127.0.0.1:8188'
    manual = '"ssh.exe" -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=30 -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -L 18288:127.0.0.1:8188'
    loop33 = '"ssh.exe" -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -L 15180:127.0.0.1:5180 -L 18188:127.0.0.1:8188'
    assert W.is_loop_ssh("tunnel_gpu36.sh", loop36) and not W.is_loop_ssh("tunnel_gpu36.sh", manual)
    assert W.is_loop_ssh("tunnel.sh", loop33) and not W.is_loop_ssh("tunnel.sh", loop36)


def test_full_rebuild_after_six_fails(monkeypatch, tmp_path):
    up = set(W.TUNNELS) - {18288}
    killed, _ = _stub(monkeypatch, tmp_path, up)
    started = []
    monkeypatch.setattr(W, "loop_pids", lambda sc: [777])
    monkeypatch.setattr(W, "start_loop", lambda sc: started.append(sc))
    monkeypatch.setattr(W, "orphan_ssh", lambda sc: [])
    st = {}
    for i in range(7):
        st = W.tick(st, now=9000.0 + 30 * i)
    assert 777 in killed and started == ["tunnel_gpu36.sh"]           # 第 6 拍：连同循环整体重建


def test_dead_loop_restarted_after_kill(monkeypatch, tmp_path):
    up = set(W.TUNNELS) - {18288}
    killed, _ = _stub(monkeypatch, tmp_path, up)
    started = []
    monkeypatch.setattr(W, "loop_running", lambda sc: sc != "tunnel_gpu36.sh")
    monkeypatch.setattr(W, "start_loop", lambda sc: started.append(sc))
    monkeypatch.setattr(W, "orphan_ssh", lambda sc: [])
    st = {}
    for i in range(2):
        st = W.tick(st, now=9500.0 + 30 * i)
    assert "tunnel_gpu36.sh" in started


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
    monkeypatch.setattr(RS, "ssh", lambda h, cmd, **k: calls.append(cmd) or (b'{"0": [0, 0], "1": [0, 0]}' if cmd == "python3 -" else b"ok"))
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
