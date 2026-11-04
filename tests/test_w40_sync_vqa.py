"""W40 SYNC+VQA-RESIDENT：run 级产物增量同步 + gpu36 看图服务纳管 + score_infra 上限报警（STATE 坏点①②）。
全部假 ssh / 假 bulk / 临时目录，不连服务器；跑远端探测脚本的用例在本机子进程里跑（带 timeout=，只读临时文件）。"""
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
sys.path.insert(0, str(ROOT / "tools/netfix"))
import resident_sync as RS  # noqa: E402

RUN = "rx_w40"


def _w(root: Path, rel: str, data: bytes = b"x", mtime: float | None = None) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "RUN_ID", RUN)
    monkeypatch.setattr(RS, "RUN_SYNC_STATE", tmp_path / "data/autopilot/run_sync.json")
    monkeypatch.setattr(RS, "VQA_STATE", tmp_path / "data/autopilot/vqa_guard.json")
    monkeypatch.setattr(RS, "HOSTS", {"gpu33": [1], "gpu36": [2]})
    monkeypatch.setattr(RS, "log", lambda *a: None)
    monkeypatch.setattr(RS._RUNS, "list_runs", lambda status=None: [RUN])
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": RUN, "legacy_unprefixed_run": "series10_legacy_x", "runs": {RUN: {"status": "producing", "assets_manifest": "assets_v2/manifest.json"}}}), encoding="utf-8")
    return tmp_path


def _tree(root: Path, t: float) -> None:
    rd = f"data/pipeline/runs/{RUN}"
    for rel in [f"{rd}/P4_ep01.md", f"{rd}/autoflow_ep01.json", f"{rd}/images/refcrops/c1.png", f"{rd}/images/refcrops/_derived_index.json",
                f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json", f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json",
                f"data/import/runs/{RUN}/script_v2.json", "assets_v2/manifest.json",
                # 不该推的
                f"{rd}/writer_tasks/P4_ep01_a1.json", f"{rd}/autoflow.log", f"{rd}/segment_fix.jsonl", f"{rd}/_producer.json",
                f"{rd}/video/state_gpu33.json", f"{rd}/judge_p1/r2/x.json", f"{rd}/_rejected_L126/a.md",
                f"data/pipeline/asset_jobs/{RUN}/_sop_backoff.json", f"data/pipeline/asset_jobs/{RUN}/face-x.log",
                f"data/import/runs/{RUN}/backups/script_v2.1.json", f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json.bak-w38-0145"]:
        _w(root, rel, b"data-" + rel.encode(), t)


def test_sources_cover_sop_gate_reads_and_skip_server_owned(sandbox):
    _tree(sandbox, time.time() - 100)
    loc, rem_paths = RS.run_sync_local()
    rd = f"data/pipeline/runs/{RUN}"
    assert set(loc) == {f"{rd}/P4_ep01.md", f"{rd}/autoflow_ep01.json", f"{rd}/images/refcrops/c1.png",
                        f"{rd}/images/refcrops/_derived_index.json", f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json",
                        f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json", f"data/import/runs/{RUN}/script_v2.json",
                        "assets_v2/manifest.json"}
    assert "assets_v2/manifest.json" in rem_paths and f"data/pipeline/sop_gate/{RUN}" in rem_paths


def test_todo_only_missing_or_laptop_newer():
    loc = {"a": (5, 100.0), "b": (5, 100.0), "c": (9, 200.0), "d": (1, 100.0)}
    rem = {"a": (5, 100.0), "b": (5, 150.0), "c": (3, 100.0)}          # b 服务器更新（W38 在服务器上改的）→ 不盖
    assert RS.run_sync_todo(loc, rem) == ["d", "c"]                     # 小文件先
    assert RS.run_sync_todo(loc, {"a": (5, 99.0)}) == ["d", "b", "c"]  # 2 s 内的时钟抖动不算新


def _untar(blob: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        return {m.name: tf.extractfile(m).read() for m in tf.getmembers()}


def test_tick_pushes_small_stdin_big_hk_and_verifies(sandbox, monkeypatch):
    t = time.time() - 100
    _tree(sandbox, t)
    big = f"data/pipeline/runs/{RUN}/images/refboards/b1.png"
    _w(sandbox, big, b"B" * (RS.RUN_SYNC_BIG + 10), t)
    remote: dict = {f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json": (999, t + 500)}     # 服务器更新的证据
    cmds, bulks = [], []

    def fake_ssh(host, cmd, data=None, **k):
        cmds.append(cmd)
        assert "timeout" in k
        if "tar xf - " in cmd:
            for name, b in _untar(data).items():
                remote[name] = (len(b), t)
        elif ".inbox/" in cmd:
            name = cmd.split(".inbox/")[1].split(" ")[0]
            for n2, b in _untar(bulks[-1][1][name]).items():
                remote[n2] = (len(b), t)
        return b"ok"

    def fake_bulk(host, files, remote_dir, timeout=0):
        assert remote_dir.endswith("/.inbox") and timeout > 0
        bulks.append((host, {rn: Path(lp).read_bytes() for lp, rn in files}))
        return subprocess.CompletedProcess(["sftp"], 0, b"", b"")

    r = RS.run_sync_tick("gpu33", ssh_fn=fake_ssh, bulk_fn=fake_bulk, rem_fn=lambda h, p: dict(remote))
    assert r.get("error") is None and r["sent"] == 8 and r["via"] == {"stdin": 7, "hk": 1}
    assert remote[f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json"] == (999, t + 500)       # 没盖
    assert bulks and big in _untar(next(iter(bulks[0][1].values())))
    st = json.loads(RS.RUN_SYNC_STATE.read_text(encoding="utf-8"))
    assert st["sync:gpu33"]["fails"] == 0 and st["last:gpu33"]["sent"] == 8
    # 第二拍：没差异 → 不发任何安装命令
    n = len(cmds)
    r2 = RS.run_sync_tick("gpu33", ssh_fn=fake_ssh, bulk_fn=fake_bulk, rem_fn=lambda h, p: dict(remote))
    assert r2["todo"] == 0 and len(cmds) == n


def test_bulk_unavailable_falls_back_to_stdin(sandbox):
    t = time.time() - 100
    big = f"data/pipeline/runs/{RUN}/images/refboards/b1.png"
    _w(sandbox, big, b"B" * (RS.RUN_SYNC_BIG + 10), t)
    remote, seen = {}, []

    def fake_ssh(host, cmd, data=None, **k):
        seen.append(cmd)
        if "tar xf - " in cmd:
            for name, b in _untar(data).items():
                remote[name] = (len(b), t)
        return b"ok"
    r = RS.run_sync_tick("gpu33", ssh_fn=fake_ssh, bulk_fn=lambda *a, **k: None, rem_fn=lambda h, p: dict(remote))
    assert r["via"] == {"stdin": 1, "hk": 0}                                     # hk 不可用 → 退回命令主连接
    assert big in remote and not any(".inbox/" in c for c in seen)


def test_failure_reports_blocking_once_then_resets(sandbox):
    _tree(sandbox, time.time() - 100)
    issues = []

    def boom(host, cmd, data=None, **k):
        raise RuntimeError("ssh gpu33 失败（rc=255）")
    fn = lambda step, what, hint: issues.append((step, what)) or f"ISS-{len(issues)}"      # noqa: E731
    for _ in range(4):
        r = RS.run_sync_tick("gpu33", ssh_fn=boom, bulk_fn=lambda *a, **k: None, rem_fn=lambda h, p: {}, issue_fn=fn)
        assert "error" in r
    assert len(issues) == 1 and issues[0][0] == "同步" and "gpu33" in issues[0][1]      # 第 2 拍登一次，之后不重登
    st = json.loads(RS.RUN_SYNC_STATE.read_text(encoding="utf-8"))
    assert st["sync:gpu33"]["fails"] == 4 and st["sync:gpu33"]["issue"] == "ISS-1"
    # 复核没到也算失败（不静默）
    remote = {}
    r = RS.run_sync_tick("gpu33", ssh_fn=lambda *a, **k: b"ok", bulk_fn=lambda *a, **k: None, rem_fn=lambda h, p: dict(remote), issue_fn=fn)
    assert "复核仍缺" in r["error"]
    # 恢复：全部到位 → 计数清零、卡点标记清掉，下次再坏会再登
    loc, _ = RS.run_sync_local()
    remote.update(loc)
    r = RS.run_sync_tick("gpu33", ssh_fn=lambda *a, **k: b"ok", rem_fn=lambda h, p: dict(remote), issue_fn=fn)
    st = json.loads(RS.RUN_SYNC_STATE.read_text(encoding="utf-8"))
    assert r["todo"] == 0 and st["sync:gpu33"]["fails"] == 0 and st["sync:gpu33"]["issue"] is None


def test_control_files_include_run_level_ready(sandbox):
    fs = RS.control_files()
    assert f"data/autopilot/runs/{RUN}/ready_episodes.json" in fs and "data/autopilot/ready_episodes.json" in fs
    assert fs.count(f"data/autopilot/runs/{RUN}/ready_episodes.json") == 1


def test_push_control_distinct_tmp_names(sandbox, monkeypatch):
    for rel in ("data/autopilot/ready_episodes.json", f"data/autopilot/runs/{RUN}/ready_episodes.json"):
        _w(sandbox, rel, json.dumps({"episodes": {"1": {"ready_at": "2026-11-04T00:00:00", "shots": ["ep01-S1"]}}}).encode())
    monkeypatch.setattr(RS, "STATE", sandbox / "data/autopilot/resident_sync.json")
    cats = []

    def fake_ssh(host, cmd, data=None, **k):
        if cmd.startswith("cat > /tmp/ctl_") and "merge" not in cmd:
            cats.append(cmd.split("cat > ", 1)[1])
        return b"merged"
    monkeypatch.setattr(RS, "ssh", fake_ssh)
    done = RS.push_control("gpu33")
    assert f"data/autopilot/runs/{RUN}/ready_episodes.json" in done
    assert len(cats) == len(set(cats)) == 2


def test_vqa_env_never_gpu2(sandbox):
    (sandbox / "config/vqa.json").write_text(json.dumps({"model": {"gpus": [0, 1, 2], "comfy_ports": {"0": 8188, "1": 8189}, "port": 8870}}),
                                             encoding="utf-8")
    e = RS.vqa_env()
    assert e["VQA_GPUS"] == "0,1" and e["VQA_COMFY"] == "0:8188,1:8189" and e["port"] == 8870


def _fake_remote(vqa: dict, lan: dict, si: dict):
    def fn(host, cmd, data=None, **k):
        src = (data or b"").decode("utf-8")
        if "server_pids" in src:
            assert host == "gpu36"
            return (json.dumps(vqa) + "\n").encode()
        if "/health" in src and "WIN" not in src:
            return (json.dumps(lan) + "\n").encode()
        return (json.dumps(si.get(host, {"n": 0})) + "\n").encode()
    return fn


def test_vqa_tick_started_notes_live_and_reports_after_two_down(sandbox):
    lives, issues = [], []
    issue = lambda step, what, hint: issues.append((step, what)) or "ISS-v"      # noqa: E731
    down = {"now": time.time(), "started": [["server", 1], ["watcher", 2]], "server_pids": [1], "watcher_pids": [2], "health": None,
            "health_error": "ConnectionRefused"}
    lan = {"ok": False, "error": "refused"}
    r = RS.vqa_tick(ssh_fn=_fake_remote(down, lan, {}), issue_fn=issue, live_fn=lives.append)
    assert r["started"] and lives and "已自动拉起" in lives[0] and issues == []
    down2 = dict(down, started=[])
    RS.vqa_tick(ssh_fn=_fake_remote(down2, lan, {}), issue_fn=issue, live_fn=lives.append)
    RS.vqa_tick(ssh_fn=_fake_remote(down2, lan, {}), issue_fn=issue, live_fn=lives.append)
    assert [s for s, _ in issues] == ["看图"] and "不通" in issues[0][1]          # 连续 2 拍不通登一次；内网不通但本机也不通 → 不另登
    up = {"now": time.time(), "started": [], "server_pids": [1], "watcher_pids": [2],
          "health": {"loaded": True, "queue": 0, "served": 3, "last_job": time.time()}}
    r = RS.vqa_tick(ssh_fn=_fake_remote(up, {"ok": True}, {}), issue_fn=issue, live_fn=lives.append)
    st = json.loads(RS.VQA_STATE.read_text(encoding="utf-8"))
    assert r["local_ok"] and st["vqa:health"]["fails"] == 0 and st["vqa:health"]["issue"] is None


def test_vqa_tick_lan_stuck_and_score_infra_cap(sandbox, monkeypatch):
    monkeypatch.setattr(RS, "lan_proxy_keepalive", lambda: "lan_proxy alive")
    issues = []
    issue = lambda step, what, hint: issues.append((step, what)) or f"ISS-{len(issues)}"      # noqa: E731
    now = time.time()
    stuck = {"now": now, "started": [], "server_pids": [1], "watcher_pids": [2],
             "health": {"loaded": False, "queue": 7, "last_job": now - 3600, "why_waiting": "显存不足"}}
    si = {"gpu33": {"n": RS.SCORE_INFRA_MAX, "counts": {"score_infra": RS.SCORE_INFRA_MAX}, "objs": ["first:ep01-S5"], "errors": [["", 12]]}}
    for _ in range(2):
        RS.vqa_tick(ssh_fn=_fake_remote(stuck, {"ok": False, "error": "timeout"}, si), issue_fn=issue, live_fn=lambda s: None)
    steps = sorted(s for s, _ in issues)
    assert steps == ["出图检测", "看图", "看图"]                                    # 卡住 1 次 + 内网 1 次 + score_infra 1 次，都不重登
    assert any("score_infra" in w and "gpu33" in w for _, w in issues)
    assert any("排队 7 张" in w for _, w in issues) and any("内网入口不通" in w for _, w in issues)


def test_vqa_probe_script_never_starts_when_port_answers_and_scans_proc(sandbox):
    src = RS.REMOTE_VQA
    assert 'START and down and not r["pids"]' in src and "/cmdline" in src and "start_new_session=True" in src
    assert '["pgrep"' not in src                                                  # bash -c 外壳命令行里也带脚本路径，pgrep -f 会误数
    assert "kill" not in src                                                      # 只起不在的，不杀在跑的


def test_vqa_probe_script_runs_locally_no_start(sandbox, tmp_path):
    """探测脚本本身能跑（本机子进程、START=False、指向没人听的端口）：输出 JSON，health=None，不起任何进程"""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    svcs = [{"name": "vqa", "port": port, "script": str(tmp_path / "server.py").replace("\\", "/"), "cwd": str(tmp_path), "argv": ["x"],
             "env": {}, "log": str(tmp_path / "l.log")},
            {"name": "watcher", "script": "tools/vqa/watch.py", "cwd": str(tmp_path), "argv": ["x"], "env": {}, "log": str(tmp_path / "w.log")}]
    script = RS.REMOTE_VQA.replace("__START__", "False").replace("__SVCS__", json.dumps(svcs))
    r = subprocess.run([sys.executable, "-"], input=script, capture_output=True, text=True, timeout=60)
    out = json.loads([ln for ln in r.stdout.splitlines() if ln.startswith("{")][-1])
    assert out["health"] is None and out["started"] == [] and "health_error" in out and out["server_pids"] == []
    assert set(out["services"]) == {"vqa", "watcher"}


def test_vqa_services_never_gpu2(sandbox):
    (sandbox / "config/vqa.json").write_text(json.dumps({"model": {"gpus": [0, 1, 2], "port": 8870, "lan_url": "http://10.0.0.36:8870"},
                                                         "anomaly": {"gpu": 2}}), encoding="utf-8")
    svcs = {x["name"]: x for x in RS.vqa_services("gpu36")}
    assert set(svcs) == {"vqa", "watcher", "anomaly", "anomaly_lan"}
    assert svcs["anomaly"]["env"]["CUDA_VISIBLE_DEVICES"] == "1" and svcs["anomaly"]["port"] == 8893
    assert svcs["vqa"]["env"]["VQA_GPUS"] == "0,1"
    assert "8893" in svcs["anomaly_lan"]["match"] and "--bind" in svcs["anomaly_lan"]["argv"]
    assert "10.0.0.36" in svcs["anomaly_lan"]["argv"]
    json.dumps(list(svcs.values()))                                              # 能塞进远端脚本


def test_anomaly_resident_sh_refuses_gpu2():
    src = (ROOT / "ops/factory/anomaly_resident.sh").read_text(encoding="utf-8")
    assert "CUDA_VISIBLE_DEVICES=2" not in src and "CUDA_VISIBLE_DEVICES=$GPU" in src and 'GPU=${ANOMALY_GPU:-1}' in src
    assert '[ "$GPU" = 2 ] && {' in src


def test_vqa_tick_anomaly_down_reports_and_started_notes(sandbox):
    lives, issues = [], []
    issue = lambda step, what, hint: issues.append((step, what)) or "ISS-a"      # noqa: E731
    ok_h = {"loaded": True, "queue": 0, "last_job": time.time()}
    p = {"now": time.time(), "started": [["anomaly", 9]], "server_pids": [1], "watcher_pids": [2], "health": ok_h,
         "services": {"vqa": {"pids": [1], "health": ok_h}, "anomaly": {"pids": [9], "health": None, "health_error": "refused"},
                      "anomaly_lan": {"pids": [3]}}}
    RS.vqa_tick(ssh_fn=_fake_remote(p, {"ok": True}, {}), issue_fn=issue, live_fn=lives.append)
    assert lives and "anomaly" in lives[0] and "GPU1" in lives[0] and issues == []
    p2 = dict(p, started=[])
    RS.vqa_tick(ssh_fn=_fake_remote(p2, {"ok": True}, {}), issue_fn=issue, live_fn=lives.append)
    assert [x for x, _ in issues] == ["出图检测"] and "8893" in issues[0][1]
    p3 = dict(p2, services=dict(p["services"], anomaly={"pids": [9], "health": {"loaded": True}}))
    r = RS.vqa_tick(ssh_fn=_fake_remote(p3, {"ok": True}, {}), issue_fn=issue, live_fn=lives.append)
    assert r["anomaly"] == 1 and r["anomaly_loaded"] is True
    assert json.loads(RS.VQA_STATE.read_text(encoding="utf-8"))["vqa:anomaly"]["fails"] == 0


def test_score_infra_script_counts_window(tmp_path):
    now = time.time()
    rows = [{"t": now - 10, "ev": "score_infra", "obj": "first:ep01-S5", "error": ""},
            {"t": now - 20, "ev": "rescore_timeout", "obj": "first:ep01-S7"},
            {"t": now - 99999, "ev": "score_infra", "obj": "old"},
            {"t": now - 5, "ev": "rendered", "obj": "first:ep01-S2"}]
    p = tmp_path / "log.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\nnot json\n", encoding="utf-8")
    script = RS.REMOTE_SCORE_INFRA.replace("__P__", str(p).replace("\\", "/")).replace("__WIN__", "1800")
    r = subprocess.run([sys.executable, "-"], input=script, capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["n"] == 2 and out["counts"] == {"score_infra": 1, "rescore_timeout": 1} and out["objs"] == ["first:ep01-S5", "first:ep01-S7"]


def test_loop_wires_w40_threads_and_cli():
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    body = src.split("def loop(pull_every_s", 1)[1].split("\ndef ", 1)[0]
    assert "target=run_sync_thread" in body and "target=vqa_thread" in body
    assert 'cmd == "run_sync"' in src and 'cmd == "vqa"' in src
    assert "for rel in control_files():" in src


def test_changed_during_push_is_not_failure(sandbox):
    t = time.time() - 100
    rel = f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json"
    _w(sandbox, rel, b"v1", t)
    remote, issues = {}, []

    def fake_ssh(host, cmd, data=None, **k):
        _w(sandbox, rel, b"v2-longer", t + 50)                                   # 推的途中 asset_worker 改写了
        for name, b in _untar(data).items():
            remote[name] = (len(b), t)
        return b"ok"
    r = RS.run_sync_tick("gpu33", ssh_fn=fake_ssh, rem_fn=lambda h, p: dict(remote),
                         issue_fn=lambda *a: issues.append(a) or "ISS")
    assert r.get("error") is None and r["changed_during"] == 1 and issues == []


def test_proc_scan_counts_only_python_with_exact_script(tmp_path):
    """探测脚本的 pids()：本机没有 /proc（Windows）→ 空表不抛；源码按 argv 精确认脚本"""
    src = RS.REMOTE_VQA
    assert '"python" in os.path.basename(argv[0]) and script in argv[1:]' in src
