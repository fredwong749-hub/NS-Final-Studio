"""W45 SERVER-DEV：cut 七门 / 工人 pytest 搬 gpu33（tools/qa/remote_gates.py、remote_pytest.py、system_version --on）。
全部离线：临时 git 仓库 + 进程内“服务器”（op 函数直接调），不连真网；子进程都带 timeout=。"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


RG = _load("tools/qa/remote_gates.py", "w45_rg_test")
RP = _load("tools/qa/remote_pytest.py", "w45_rp_test")
SV = RG.load_sv()


def _git(repo, *a, env=None):
    r = subprocess.run(["git", *a], cwd=repo, capture_output=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.decode().strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(RG, "git_exe", lambda repo=None: "git")
    r = tmp_path / "repo"
    (r / "tools").mkdir(parents=True)
    (r / "tools/a.py").write_bytes(b"print('a')\n")
    (r / "tools/run.sh").write_bytes(b"#!/bin/sh\necho hi\n")
    (r / "README.md").write_bytes(b"hello\n")
    _git(r, "init", "-q")
    _git(r, "config", "core.autocrlf", "false")          # Windows 全局 autocrlf=true 会让工作区文件 sha ≠ blob sha
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "update-index", "--chmod=+x", "tools/run.sh")
    _git(r, "commit", "-qm", "x")
    return r


def _cfg(tmp_path):
    return {"host": "gpu33", "remote_python": "/py", "snap_root": str(tmp_path / "srv/cut_snapshots"),
            "work_root": str(tmp_path / "srv/w45"), "prod_repo": str(tmp_path / "prod"), "pytest_n": 8, "poll_s": 0}


class FakeServer:
    """进程内服务器：拦 call_op 的 sh_fn，解包 runner_bundle 后直接调 server_op"""

    def __init__(self, tmp_path):
        self.tmp, self.calls = tmp_path, []

    def __call__(self, host, cmd, data, timeout):
        self.calls.append((host, cmd, len(data or b"")))
        op = cmd.rsplit("_op ", 1)[1].split()[0]
        inbox = self.tmp / f"inbox{len(self.calls)}"
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(inbox, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(inbox)
        out = RG.server_op(op, inbox) if op != "spawn" else {"job": "j", "pid": 1}
        return subprocess.CompletedProcess([], 0, (json.dumps(out) + "\n").encode(), b"")


def test_check_dest_only_two_roots(tmp_path):
    cfg = _cfg(tmp_path)
    assert RG.check_dest(cfg["snap_root"] + "/sv-1", cfg).endswith("sv-1")
    assert RG.check_dest(cfg["work_root"] + "/x", cfg)
    for bad in (str(tmp_path / "prod/x"), cfg["snap_root"], cfg["snap_root"] + "/../evil", "/root/work/fredw/offline_x/repo"):
        with pytest.raises(ValueError):
            RG.check_dest(bad, cfg)


def test_manifest_and_blob_tar_roundtrip(repo):
    m = RG.tree_manifest("HEAD", repo)
    by = {p: (mode, sha) for mode, sha, p in m}
    assert by["tools/run.sh"][0] == "100755" and by["README.md"][0] == "100644"
    raw = RG.blob_tar(m, repo)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        names = {x.name: x for x in tf.getmembers()}
        assert tf.extractfile(names["tools/a.py"]).read() == b"print('a')\n"
        assert names["tools/run.sh"].mode == 0o755
    assert RG.blob_sha_file(repo / "README.md") == by["README.md"][1]


def test_stage_pushes_only_missing_then_reuses_own_snapshot(repo, tmp_path):
    cfg = _cfg(tmp_path)
    prod = Path(cfg["prod_repo"])
    (prod / "tools").mkdir(parents=True)
    (prod / "tools/a.py").write_bytes(b"print('a')\n")         # 同 sha → 从 producer 仓库复制
    (prod / "README.md").write_bytes(b"old\n")                 # sha 不同 → 要推
    (prod / "data").mkdir()
    (prod / "data/x.json").write_bytes(b"{}")
    (prod / "data/night.pid").write_bytes(b"123")
    srv = FakeServer(tmp_path)
    logs = []
    d1 = cfg["snap_root"] + "/sv-1"
    b = RG.stage_tree(cfg, "gpu33", "HEAD", d1, cfg["snap_root"], ["data"], sh_fn=srv, log=logs.append, repo=repo)
    assert not b.get("error"), b
    assert b["pushed"] == 2 and b["copied"] == 1
    assert (Path(d1) / "README.md").read_text() == "hello\n"
    assert os.access(Path(d1) / "tools/run.sh", os.X_OK) or os.name == "nt"
    assert (Path(d1) / "data/x.json").exists() and not (Path(d1) / "data/night.pid").exists()   # 不带 pid（W22 口径）
    assert (prod / "README.md").read_text() == "old\n"                        # producer 仓库不被改
    # 第二次：改一个文件 → 只推这一个，其余从自己的上一份快照硬链
    (repo / "README.md").write_bytes(b"hello2\n")
    _git(repo, "commit", "-qam", "y")
    d2 = cfg["snap_root"] + "/sv-2"
    b2 = RG.stage_tree(cfg, "gpu33", "HEAD", d2, cfg["snap_root"], [], sh_fn=srv, log=logs.append, repo=repo)
    assert b2["pushed"] == 1 and b2["hardlinked"] + b2["from_store"] == 3 and b2["copied"] == 0, b2   # 全部硬链（上一份快照 / 内容寻址库）
    assert (Path(d2) / "README.md").read_text() == "hello2\n" and (Path(d1) / "README.md").read_text() == "hello\n"
    assert Path(json.loads((Path(cfg["snap_root"]) / "_latest.json").read_text())["dir"]) == Path(d2)


def test_build_same_dest_renamed_not_deleted(repo, tmp_path):
    cfg = _cfg(tmp_path)
    srv = FakeServer(tmp_path)
    d = cfg["snap_root"] + "/sv-1"
    RG.stage_tree(cfg, "gpu33", "HEAD", d, cfg["snap_root"], [], sh_fn=srv, log=lambda *_: None, repo=repo)
    (Path(d) / "marker").write_bytes(b"keep")
    RG.stage_tree(cfg, "gpu33", "HEAD", d, cfg["snap_root"], [], sh_fn=srv, log=lambda *_: None, repo=repo)
    olds = list(Path(cfg["snap_root"]).glob("sv-1.old*"))
    assert olds and (olds[0] / "marker").read_text() == "keep"


def test_build_fails_closed_when_blob_missing(repo, tmp_path):
    m = RG.tree_manifest("HEAD", repo)
    out = RG.op_build({"dest": str(tmp_path / "d"), "manifest": m, "latest_roots": [], "prod": None}, None, sv=SV)
    assert "拼树失败" in out["error"]


def test_build_rejects_paths_outside_manifest(repo, tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        ti = tarfile.TarInfo("../evil.py")
        ti.size = 1
        tf.addfile(ti, io.BytesIO(b"x"))
    p = tmp_path / "payload.bin"
    p.write_bytes(buf.getvalue())
    with pytest.raises(ValueError):
        RG.op_build({"dest": str(tmp_path / "d"), "manifest": RG.tree_manifest("HEAD", repo), "prod": None}, p, sv=SV)


def test_op_cmd_and_bundle_only_touch_work_root(tmp_path):
    cfg = _cfg(tmp_path)
    c = RG.op_cmd(cfg, "plan")
    assert cfg["work_root"] in c and "_op plan" in c and "rm " not in c
    with tarfile.open(fileobj=io.BytesIO(RG.runner_bundle({"a": 1}, b"zz"))) as tf:
        names = set(tf.getnames())
    assert {"runner/tools/qa/remote_gates.py", "runner/tools/qa/system_version.py", "args.json", "payload.bin"} <= names


def test_call_op_error_on_nonzero_rc(tmp_path):
    bad = lambda h, c, d, t: subprocess.CompletedProcess([], 255, b"", b"mux down")
    assert "rc=255" in RG.call_op(_cfg(tmp_path), "gpu33", "plan", {}, sh_fn=bad)["error"]


def test_parse_poll_and_wait_job_streams_until_done(tmp_path):
    assert RG.parse_poll(b"RUNNING\nSIZE 5\nabc") == ("RUNNING", None, 5, b"abc")
    assert RG.parse_poll(b"RC 1\nSIZE 0\n")[:2] == ("DONE", 1)
    seq = [b"RUNNING\nSIZE 4\nab", b"RUNNING\nSIZE 4\ncd", b"RC 0\nSIZE 6\nef"]
    offs = []

    def sh(host, cmd, data, timeout):
        offs.append(int(cmd.split("tail -c +")[1].split()[0]))
        return subprocess.CompletedProcess([], 0, seq.pop(0), b"")
    logs = []
    r = RG.wait_job({"poll_s": 0}, "gpu33", "/w/j", 100, log=logs.append, sh_fn=sh, sleep=lambda s: None)
    assert r == {"state": "done", "rc": 0, "job": "/w/j"} and "".join(logs) == "abcdef" and offs == [1, 3, 5]


def test_wait_job_dead_and_lost(tmp_path):
    dead = lambda h, c, d, t: subprocess.CompletedProcess([], 0, b"DEAD\nSIZE 0\n", b"")
    assert RG.wait_job({}, "h", "/j", 10, sh_fn=dead, sleep=lambda s: None)["state"] == "dead"
    down = lambda h, c, d, t: subprocess.CompletedProcess([], 255, b"", b"")
    assert RG.wait_job({}, "h", "/j", 1e9, sh_fn=down, sleep=lambda s: None, max_conn_fail=3)["state"] == "lost"


FAKE_SV = '''
import time
ENV = {}
PY = "py"
PY_PATHS = ("services/agent",)
ROOT = None
def sh(cmd, timeout=1800, cwd=None, env=None):
    return 0, "ok"
def run_watched(cmd, timeout, cwd=None, env=None, stall_s=None):
    return 0, "3 passed in 0.1s", {}
def gates(changed, run_tests=True, root=None, env=None, sv=None, log_dir=None):
    rows = []
    for gid, script in (("syntax", "tools/qa/syntax_guard.py"), ("decision", "tools/qa/decision_check.py")):
        code, _ = sh([PY, script], 600)
        rows.append({"id": gid, "name": gid, "ok": code == 0, "detail": "d"})
    code, _, _ = run_watched([PY, "-m", "pytest", "-q"], 100)
    rows.append({"id": "pytest", "name": "pytest", "ok": code == 0, "detail": "d", "n": int(__import__("os").environ["NS_CUT_PYTEST_N"])})
    return rows
def metrics(rows, root, env):
    return {"tests_collected": 3}
'''


def test_run_gates_job_times_each_gate_and_writes_result(tmp_path, monkeypatch):
    fake = types.ModuleType("w45_fake_sv")
    exec(FAKE_SV, fake.__dict__)
    job = tmp_path / "j"
    job.mkdir()
    (job / "job.json").write_text(json.dumps({"dest": str(tmp_path / "snap"), "job_args": {"sv": "sv-x", "changed": [], "n": 7,
                                                                                           "want_metrics": True}}), encoding="utf-8")
    for k in ("NS_FREEZE_EXEMPT", "NS_CUT_PYTEST_N", "CUDA_VISIBLE_DEVICES"):
        monkeypatch.setenv(k, os.environ.get(k, ""))      # 用完还原
    res = RG.run_gates_job(job, sv=fake)
    rows = {r["id"]: r for r in res["gates"]}
    assert set(res["timings"]) == {"syntax", "decision", "pytest"} and rows["pytest"]["n"] == 7
    assert all(r["elapsed_s"] is not None for r in res["gates"]) and res["metrics"] == {"tests_collected": 3}
    assert json.loads((job / "result.json").read_text(encoding="utf-8"))["gates"][0]["id"] == "syntax"
    assert fake.sh.__name__ == "sh"                       # 打桩已还原


def test_gate_key():
    assert RG.gate_key(["py", "tools/qa/arch_scan.py", "--check"]) == "arch"
    assert RG.gate_key(["py", "-m", "pytest", "--collect-only"]) == "pytest_collect"
    assert RG.gate_key(["py", "-m", "pytest", "-q"]) == "pytest"


def test_gates_on_precedence(monkeypatch):
    monkeypatch.delenv("NS_CUT_ON", raising=False)
    monkeypatch.setattr(SV, "release_cfg", lambda root=None: {"gates_on": "gpu33"})
    assert SV.gates_on(None) == "gpu33" and SV.gates_on("local") is None
    monkeypatch.setenv("NS_CUT_ON", "local")
    assert SV.gates_on(None) is None and SV.gates_on("gpu36") == "gpu36"
    monkeypatch.setattr(SV, "release_cfg", lambda root=None: {})
    monkeypatch.delenv("NS_CUT_ON")
    assert SV.gates_on(None) is None


def test_run_on_server_fallback_and_fail_closed(monkeypatch):
    fake = types.SimpleNamespace(remote_cut_gates=lambda *a, **k: {"error": "rc=255"})
    monkeypatch.setattr(SV, "load_remote_gates", lambda: fake)
    monkeypatch.setattr(SV, "release_cfg", lambda root=None: {"gates_on_fallback": "local"})
    srv, extra = SV.run_on_server("t", "sv", [], True, True, "gpu33")
    assert srv is None and "rc=255" in extra["gates_on_fallback"]
    monkeypatch.setattr(SV, "release_cfg", lambda root=None: {"gates_on_fallback": "fail"})
    srv, _ = SV.run_on_server("t", "sv", [], True, True, "gpu33")
    assert srv[1][0]["ok"] is False
    ok = types.SimpleNamespace(remote_cut_gates=lambda *a, **k: {"snapshot": {"dir": "gpu33:/x"}, "gates": [{"id": "syntax", "ok": True}],
                                                                 "timings": {"syntax": 1.0}})
    monkeypatch.setattr(SV, "load_remote_gates", lambda: ok)
    srv, extra = SV.run_on_server("t", "sv", [], True, True, "gpu33")
    assert srv[0]["dir"] == "gpu33:/x" and extra["gates_on"] == "gpu33"
    assert SV.run_on_server("t", "sv", [], True, True, None) == (None, {})


def test_worktree_tree_includes_untracked_without_touching_index(repo):
    (repo / "tools/new.py").write_bytes(b"x = 1\n")
    before = (repo / ".git/index").read_bytes()
    t = RG.worktree_tree(repo)
    assert any(p == "tools/new.py" for _m, _s, p in RG.tree_manifest(t, repo))
    assert (repo / ".git/index").read_bytes() == before
    assert not list((repo / ".git").glob("nsfs_w45_index_*"))


def test_remote_pytest_argv():
    assert RP.build_argv(["tests/test_a.py"], None, None) == ["{PY}", "-m", "pytest", "-p", "no:cacheprovider", "tests/test_a.py"]
    a = RP.build_argv(["tests/test_a.py", "tests/test_b.py", "-q"], None, None)
    assert a[a.index("-n") + 1] == "16"
    assert RP.build_argv(["-n", "4", "tests/a.py", "tests/b.py"], None, None).count("-n") == 1
    assert RP.build_argv([], None, "$PY tools/qa/arch_scan.py --check") == ["bash", "-c", "$PY tools/qa/arch_scan.py --check"]


@pytest.mark.skipif(os.name == "nt", reason="WSL 专用分支")
def test_rssh_run_strips_wsl_prefix_on_linux(monkeypatch):
    RS = _load("tools/netfix/rssh.py", "w45_rssh_test")
    seen = []
    monkeypatch.setattr(RS, "enabled", lambda: True)
    monkeypatch.setattr(RS, "_note", lambda *a, **k: None)
    monkeypatch.setattr(RS.subprocess, "run", lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess(argv, 0, b"", b""))
    RS.run("gpu33", "date", timeout=5)
    assert seen[0][0] == "ssh" and "ProxyCommand=false" in seen[0]


def test_overlay_laptop_evidence_wins_and_is_cached(repo, tmp_path):
    """笔记本独有证据：小文件按内容进服务器 _blobs/<sha>（第二次不再推）、优先于服务器数据；大文件服务器有就用服务器的"""
    cfg = _cfg(tmp_path)
    prod = Path(cfg["prod_repo"])
    (prod / "data/rsi").mkdir(parents=True)
    (prod / "data/rsi/scores.jsonl").write_bytes(b"server\n")
    (prod / "data/rsi/other.json").write_bytes(b"{}")
    (prod / "data/music").mkdir(parents=True)
    (prod / "data/music/ep01.wav").write_bytes(b"S" * 10)
    lap = tmp_path / "lap"
    (lap / "data/rsi").mkdir(parents=True)
    (lap / "data/rsi/scores.jsonl").write_bytes(b"laptop\n")
    (lap / "data/music").mkdir(parents=True)
    (lap / "data/music/ep01.wav").write_bytes(b"L" * 50)
    (lap / "data/script_rsi").mkdir(parents=True)
    (lap / "knowledge/rules").mkdir(parents=True)
    (lap / "knowledge/rules/r.yaml").write_bytes(b"evidence: ['data/rsi/scores.jsonl', 'data/music/ep01.wav', 'data/script_rsi/']\n")
    files, dirs = RG.overlay_list(lap, big=20)
    assert {f[0]: f[2] for f in files} == {"data/rsi/scores.jsonl": False, "data/music/ep01.wav": True} and dirs == ["data/script_rsi"]
    srv = FakeServer(tmp_path)
    d1 = cfg["snap_root"] + "/sv-1"
    b = RG.stage_tree(cfg, "gpu33", "HEAD", d1, cfg["snap_root"], ["data/rsi", "data/music"], sh_fn=srv, log=lambda *_: None,
                      repo=repo, overlay=(files, dirs), ov_root=lap, ov_gate=lambda seen: None)
    assert not b.get("error"), b
    assert (Path(d1) / "data/rsi/scores.jsonl").read_bytes() == b"laptop\n"         # 笔记本版本优先
    assert (Path(d1) / "data/rsi/other.json").exists()                              # 同目录其余照常从服务器接
    assert (Path(d1) / "data/music/ep01.wav").read_bytes() == b"S" * 10             # 大文件：服务器有 → 用服务器的
    assert (Path(d1) / "data/script_rsi").is_dir()
    assert (prod / "data/rsi/scores.jsonl").read_bytes() == b"server\n"              # 生产数据没被改
    plan2 = RG.op_plan({"manifest": [], "overlay": files, "store": cfg["snap_root"] + "/_blobs", "prod": str(prod)})
    assert plan2["overlay_missing"] == []                                            # 第二次不再推


def test_expand_data_rels_skips_server_only_children(tmp_path):
    (tmp_path / "data/a").mkdir(parents=True)
    (tmp_path / "data/b.json").write_bytes(b"{}")
    assert RG.expand_data_rels(["data", "assets/x.png"], tmp_path) == ["data/a", "data/b.json", "assets/x.png"]


def test_mirror_list_scope_and_sha_cache(tmp_path):
    (tmp_path / "data/pipeline").mkdir(parents=True)
    (tmp_path / "data/pipeline/a.json").write_bytes(b"{}")
    (tmp_path / "data/pipeline/big.json").write_bytes(b"x" * 50)
    (tmp_path / "data/pipeline/img.png").write_bytes(b"p")
    (tmp_path / "data/pipeline/night.pid").write_bytes(b"1")
    (tmp_path / "data/_offline_pull/gpu33").mkdir(parents=True)
    (tmp_path / "data/_offline_pull/gpu33/x.json").write_bytes(b"{}")
    (tmp_path / "data/music").mkdir(parents=True)
    (tmp_path / "data/music/b.flac").write_bytes(b"f" * 100)
    m = {"roots": ["data"], "max_bytes": 20, "skip_prefixes": ["data/_offline_pull"], "media_exts": [".png", ".flac"],
         "extra": ["data/music/b.flac"]}
    cache = {}
    got = RG.mirror_list(m, tmp_path, cache)
    assert [e[0] for e in got] == ["data/music/b.flac", "data/pipeline/a.json"]     # 媒体 / 大文件 / pid / 归档不进，extra 进
    assert got[1][1] == RG.blob_sha_file(tmp_path / "data/pipeline/a.json") and "data/pipeline/a.json" in cache
    cache["data/pipeline/a.json"][2] = "f" * 40                                     # 大小 / mtime 没变 → 用缓存，不重读
    assert RG.mirror_list(m, tmp_path, cache)[1][1] == "f" * 40


def test_push_overlay_batches_wait_gate_and_store(tmp_path):
    cfg = {**_cfg(tmp_path), "mirror": {"batch_mb": 0.000001}}     # 1 字节一批
    (tmp_path / "lap").mkdir()
    ents = []
    for i in range(3):
        (tmp_path / f"lap/f{i}.json").write_bytes(b"%d" % i)
        ents.append([f"f{i}.json", "0" * 40, False])
    srv, gates_called = FakeServer(tmp_path), []
    r = RG.push_overlay(cfg, "gpu33", ents, {"0" * 40}, tmp_path / "lap", sh_fn=srv, log=lambda *_: None,
                        gate=lambda seen: gates_called.append(seen) or "t")
    assert r["sent"] == 3 and len(gates_called) == 3                                  # 每批前都过 run_sync 闸
    store = Path(cfg["snap_root"]) / "_blobs"
    assert all((store / e[1]).is_file() and RG.blob_sha_file(store / e[1]) == e[1] for e in ents)   # sha 现算并回填


def test_wait_run_sync_tick(tmp_path):
    st = tmp_path / "data/autopilot/run_sync.json"
    st.parent.mkdir(parents=True)
    st.write_text(json.dumps({"last:gpu33": {"at": "t1"}}), encoding="utf-8")
    cfg = {"mirror": {"run_sync_state": "data/autopilot/run_sync.json", "wait_tick_s": 100}}
    clock = iter(range(0, 1000, 10))

    def sleep(_s):
        st.write_text(json.dumps({"last:gpu33": {"at": "t2"}}), encoding="utf-8")
    assert RG.wait_run_sync_tick(cfg, "gpu33", None, tmp_path, sleep=sleep, clock=lambda: next(clock)) == "t2"
    clock2 = iter(range(0, 1000, 60))                                                  # 一直不变 → 等满 wait_tick_s 就放行
    assert RG.wait_run_sync_tick(cfg, "gpu33", "t2", tmp_path, sleep=lambda s: None, clock=lambda: next(clock2)) == "t2"


def test_lfs_pointer_resolved_to_real_content(repo):
    """仓库 *.png 走 Git LFS：git archive 给真内容，cat-file 只有指针 → 清单换成真内容 sha、打包真内容（11-04 实测服务器快照里是 131 字节指针）"""
    import hashlib
    real = b"\x89PNG\r\n\x1a\n" + b"x" * 500
    oid = hashlib.sha256(real).hexdigest()
    ptr = f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(real)}\n".encode()
    (repo / "img.png").write_bytes(ptr)
    _git(repo, "add", "img.png")
    _git(repo, "commit", "-qm", "lfs")
    obj = repo / ".git/lfs/objects" / oid[:2] / oid[2:4] / oid
    obj.parent.mkdir(parents=True)
    obj.write_bytes(real)
    m = {p: sha for _m, sha, p in RG.tree_manifest("HEAD", repo)}
    assert m["img.png"] == RG.blob_sha_file(obj)
    with tarfile.open(fileobj=io.BytesIO(RG.blob_tar([["100644", m["img.png"], "img.png"]], repo))) as tf:
        assert tf.extractfile("img.png").read() == real
    obj.rename(obj.with_name("gone"))                     # 没有真内容 → 保留指针并报出来
    RG._LFS_SRC.clear()
    (repo / "data/qa/remote_gates/sha_cache.json").write_text("{}", encoding="utf-8")
    logs = []
    m2 = {p: sha for _m, sha, p in RG.tree_manifest("HEAD", repo, log=logs.append)}
    assert m2["img.png"] != m["img.png"] and "LFS" in logs[0]


def test_push_overlay_retries_batch_on_link_drop(tmp_path):
    cfg = {**_cfg(tmp_path), "mirror": {"batch_mb": 6}}
    (tmp_path / "lap").mkdir()
    (tmp_path / "lap/a.json").write_bytes(b"{}")
    srv, n = FakeServer(tmp_path), {"k": 0}

    def flaky(host, cmd, data, timeout):
        n["k"] += 1
        if n["k"] == 1:
            return subprocess.CompletedProcess([], 255, b"", b"Connection closed")
        return srv(host, cmd, data, timeout)
    r = RG.push_overlay(cfg, "gpu33", [["a.json", "0" * 40, False]], {"0" * 40}, tmp_path / "lap", sh_fn=flaky,
                        log=lambda *_: None, gate=lambda seen: "t")
    assert r["sent"] == 1 and n["k"] == 2


def test_throttle_small_batches_and_sleep_until_file(tmp_path):
    cfg = {**_cfg(tmp_path), "mirror": {"batch_mb": 6},
           "throttle": {"max_kbps": 0.001, "batch_mb": 0.000001, "until_file": str(tmp_path / "done.mp4")}}
    (tmp_path / "lap").mkdir()
    ents = []
    for i in range(2):
        (tmp_path / f"lap/f{i}.json").write_bytes(b"%d" % i)
        ents.append([f"f{i}.json", "0" * 40, False])
    slept = []
    r = RG.push_overlay(cfg, "gpu33", ents, {"0" * 40}, tmp_path / "lap", sh_fn=FakeServer(tmp_path), log=lambda *_: None,
                        gate=lambda seen: seen, sleep_fn=slept.append)
    assert r["sent"] == 2 and len(slept) == 2 and all(x > 0 for x in slept)   # 1 字节一批、每批后睡
    (tmp_path / "done.mp4").write_bytes(b"x")
    assert RG.throttle_of(cfg) is None                                          # ep01 成片出现 → 解除


def test_defer_lfs_only_when_throttled_and_not_priority(tmp_path):
    RG._LFS_PTR.update({"r" * 40: "p" * 40, "q" * 40: "o" * 40})
    m = [["100644", "r" * 40, "a.png"], ["100644", "q" * 40, "b.png"], ["100644", "z" * 40, "c.py"]]
    cfg = {"throttle": {"until_file": str(tmp_path / "done.mp4")}, "mirror": {"extra": ["b.png"]}}
    assert RG.defer_lfs(cfg, m, {"a.png", "b.png", "c.py"}) == ["a.png"]
    assert m[0][1] == "p" * 40 and m[1][1] == "q" * 40 and m[2][1] == "z" * 40   # 优先清单里的仍推真内容
    (tmp_path / "done.mp4").write_bytes(b"x")
    m2 = [["100644", "q" * 40, "x.png"]]
    assert RG.defer_lfs(cfg, m2, {"x.png"}) == [] and m2[0][1] == "q" * 40        # 解除限速 → 不延后
