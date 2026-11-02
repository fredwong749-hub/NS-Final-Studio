"""K-OPS-V01：系统版本工具（tools/qa/system_version.py，CODE-RSI r3）。不提交、不推送，只测纯函数与闸门判定。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ns_system_version_t", ROOT / "tools/qa/system_version.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)


def test_next_id_increments_per_day():
    assert SV.next_id("20261101", []) == "sv-20261101-01"
    assert SV.next_id("20261101", ["sv-20261101-01", "sv-20261101-02", "sv-20261031-07"]) == "sv-20261101-03"
    assert SV.next_id("20261102", ["sv-20261101-09"]) == "sv-20261102-01"


def test_pick_tests_includes_smoke_and_related():
    t = SV.pick_tests(["tools/qa/syntax_guard.py", "tests/test_push_check.py", "docs/x.md"])
    assert "tests/test_syntax_guard.py" in t and "tests/test_push_check.py" in t
    assert all((ROOT / x).exists() for x in t)


def test_gate_blocks_on_decision_cross(monkeypatch):
    outs = {"syntax_guard.py": (0, "syntax_guard PASS"), "compile.py": (0, "OK"),
            "decision_check.py": (0, "合计 62：✅ 60  ❌ 1  ⏳ 1  ⏭ 0"), "decision_propagation.py": (0, "ok")}

    def fake(cmd, timeout=1800, cwd=None):
        return next((v for k, v in outs.items() if any(k in c for c in cmd)), (0, ""))
    monkeypatch.setattr(SV, "sh", fake)
    rows = {r["id"]: r for r in SV.gates([], run_tests=False)}
    assert not rows["decision"]["ok"] and rows["syntax"]["ok"]
    outs["decision_check.py"] = (0, "合计 62：✅ 61  ❌ 0  ⏳ 1  ⏭ 0")     # ⏳ 可以
    assert {r["id"]: r for r in SV.gates([], run_tests=False)}["decision"]["ok"]


def test_flat_config_keys():
    assert SV._flat({"a": {"b": 1, "c": {"d": 2}}, "e": []}) == {"a.b": 1, "a.c.d": 2, "e": []}


def test_iter_gate_warns_when_changes_not_in_a_version(monkeypatch):
    import types
    spec = importlib.util.spec_from_file_location("ns_iter_gate_sv", ROOT / "tools/qa/iter_gate.py")
    IG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(IG)
    g = IG.Gate(types.SimpleNamespace(loop="CODE-RSI", changed=["tools/qa/system_version.py"], ui=False))
    monkeypatch.setattr(IG, "sh", lambda cmd, timeout=900: (0, " M tools/qa/system_version.py\n"))
    g.v2_version()
    assert g.rows[-1]["id"] == "V2" and g.rows[-1]["status"] == "warn" and not g.rows[-1]["required"]
    monkeypatch.setattr(IG, "sh", lambda cmd, timeout=900: (0, ""))
    g.v2_version()
    assert g.rows[-1]["status"] == "pass"


def test_push_secret_scan_patterns():
    key = '"api' + '_key": "' + "abcdefghijklmnopqrstu" + '"'          # 拼出来，免得本文件自己被密钥扫描命中
    for bad in (key, "sk-" + "a" * 30, "ghp_" + "b" * 36, "-----BEGIN " + "PRIVATE KEY-----"):
        assert SV.PUSH_SECRET_RE.search(bad), bad
    for ok in ('"api_key": ""', "token budget 4096", "sk-short"):
        assert not SV.PUSH_SECRET_RE.search(ok), ok


class _FakeRS:
    """记录每次 push 时模块全局（ROOT / CODE_DIRS）——验证代码只从 tag 快照推、数据推送不带代码"""

    def __init__(self, live: Path):
        self.ROOT, self.CODE_DIRS, self.R = live, ["tools"], "/srv/repo"
        self.calls = []

    def push(self, h, code_only=False, tier=2, yes=False, gate=True, **kw):
        self.calls.append(("push", h, code_only, Path(self.ROOT), list(self.CODE_DIRS), gate))
        return {"sent": 1}

    def verify_sha(self, h, files, fix=True):
        self.calls.append(("verify", h, Path(self.ROOT), sorted(files)))
        return {"checked": len(files), "mismatch": [], "fixed": []}

    guard_rc = 0
    deps_rc = 0
    OFF = "/srv/off"

    def ssh(self, h, cmd, data=None, tries=3):
        if "server_deps" in cmd:
            return ('{"problems": []}' + chr(10) + f'rc={self.deps_rc}').encode()
        if "decisions_guard" in cmd:
            return ('{"problems": []}' + chr(10) + f'rc={self.guard_rc}').encode()
        return b"ok"

    def restart(self, h):
        self.calls.append(("restart", h))
        return "restarted"

    def alive(self, h):
        return "producer alive"


class _FakeRQ:
    def __init__(self):
        self.reqs = []

    def request(self, host, reason, by, urgent=False):
        self.reqs.append((host, reason))
        return {"id": "q1"}


class _FakePC:
    def __init__(self):
        self.runs = []

    def run(self, code_only=False, tier=2, rs=None, skip_guard=False, **kw):
        self.runs.append((code_only, Path(rs.ROOT), list(rs.CODE_DIRS)))
        # 模拟旧闸门：源目录里有 tag 之外的新代码文件就判 P3 没推到
        stray = (Path(rs.ROOT) / "tools/new_after_cut.py")
        if rs.CODE_DIRS and stray.exists():
            return {"verdict": "FAIL", "problems": [{"kind": "P3", "file": "tools/new_after_cut.py", "why": "代码文件没推到"}]}
        return {"verdict": "PASS", "problems": []}


def test_deploy_ignores_new_code_file_after_cut_and_reports_drift(tmp_path, monkeypatch):
    """K-OPS-F06（总调度 01:3x 批准）：cut 之后工作树新建代码文件，deploy 仍成功；代码只从快照推，drift 只报"""
    live, snap = tmp_path / "live", tmp_path / "snap"
    (live / "tools").mkdir(parents=True)
    (snap / "tools").mkdir(parents=True)
    (live / "tools/a.py").write_text("x = 1\n")
    (snap / "tools/a.py").write_text("x = 1\n")
    (live / "tools/new_after_cut.py").write_text("y = 2\n")          # cut 之后新建
    rs, pc = _FakeRS(live), _FakePC()
    rq = _FakeRQ()
    r = SV.deploy_host(rs, "gpu36", snap, ["tools/a.py"], ["tools/a.py"], "sv-20991231-01", "abc", restart=True, pc=pc, rq=rq)
    assert rq.reqs == [("gpu36", "system_version deploy sv-20991231-01")] and r["restart"].startswith("queued ")   # K-OPS-W16：写队列不直接重启
    assert not any(c[0] == "restart" for c in rs.calls)
    assert r["ok"], r
    pushes = [c for c in rs.calls if c[0] == "push"]
    code = [c for c in pushes if c[2]]
    data = [c for c in pushes if not c[2]]
    assert not code                                                     # 代码不再整批推，改由 verify_sha 按快照 sha 补
    assert data and all(c[4] == [] for c in data)                      # 数据推送不带代码目录
    assert all(c[5] is False for c in pushes)                          # 闸门由 deploy_host 对快照 / 数据各跑一次
    assert pc.runs[0][1] == snap and pc.runs[1][2] == []
    assert rs.ROOT == live and rs.CODE_DIRS == ["tools"]               # 全局已还原
    monkeypatch.setattr(SV, "git", lambda *a: "")
    monkeypatch.setattr(SV, "pending_changes", lambda: [("?", "tools/new_after_cut.py"), ("M", "docs/x.md")])
    assert SV.drift_files("sv-20991231-01", ["tools"]) == ["tools/new_after_cut.py"]


def test_deploy_host_fails_on_bad_snapshot(tmp_path):
    rs, pc = _FakeRS(tmp_path), _FakePC()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/new_after_cut.py").write_text("")
    r = SV.deploy_host(rs, "gpu36", tmp_path, [], [], "sv-x", "c", restart=False, pc=pc)   # 快照本身坏了照样拦
    assert r["ok"] is False and "快照推送前检查不通过" in r["error"]


def test_deploy_refuses_after_failed_cut_and_old_versions():
    """K-OPS-F07：cut 失败（晚于最新 tag）→ deploy 拒绝，不会把上一版重新部署；非最新版本要 --allow-old"""
    tags = ["sv-20261102-02", "sv-20261102-03"]
    tt = lambda t: 1000.0                                                        # noqa: E731  最新 tag 时间
    failed = {"ok": False, "at": 2000.0, "at_iso": "02:00", "reason": "compile 红"}
    assert "cut 失败" in SV.deploy_guard(None, last_cut=failed, tags=tags, tag_time=tt)
    assert "cut 失败" in SV.deploy_guard("sv-20261102-03", last_cut=failed, tags=tags, tag_time=tt)
    ok = {"ok": True, "at": 1001.0}
    assert SV.deploy_guard(None, last_cut=ok, tags=tags, tag_time=tt) is None
    assert "不是最新版本" in SV.deploy_guard("sv-20261102-02", last_cut=ok, tags=tags, tag_time=tt)
    assert SV.deploy_guard("sv-20261102-02", allow_old=True, last_cut=ok, tags=tags, tag_time=tt) is None
    old_fail = {"ok": False, "at": 500.0}                                        # 失败在最新 tag 之前（之后已成功 cut）
    assert SV.deploy_guard(None, last_cut=old_fail, tags=tags, tag_time=tt) is None


def test_cli_records_cut_and_chains_exit_code():
    s = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    m = s[s.index("def main("):]
    assert "record_cut(out, a.dry)" in m and 'return 0 if out.get("ok") else 1' in m   # cut 失败退出码 1：cut && deploy 不会继续
    d = s[s.index("def deploy(sv"):s.index("def rollback(")]
    assert d.index("deploy_guard(") < d.index("load_rs()")


def test_cut_takes_state_snapshot_and_rollback_mentions_restore():
    """K-OPS-X06（DISTILL）：cut 打完 tag 做状态快照（失败不影响发版）；rollback 命令里有 restore"""
    class SS:
        def snapshot(self, sv):
            return {"tar": f"data/system_versions/{sv}/state_snapshot.tar", "files": 119, "tar_sha256": "ab"}

    class Bad:
        def snapshot(self, sv):
            raise OSError("disk")
    r = SV.take_state_snapshot("sv-x", SS())
    assert r["ok"] and r["files"] == 119
    assert SV.take_state_snapshot("sv-x", Bad())["ok"] is False
    s = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    cut = s[s.index("def cut("):s.index("def push_remote(") if "def push_remote(" in s[s.index("def cut("):] else len(s)]
    assert cut.index('git("tag", "-a"') < cut.index("take_state_snapshot(sv)")
    rb = s[s.index("def rollback("):]
    assert "state_snapshot.py restore" in rb


def test_collection_problems_reports_files():
    """K-OPS-F08：收集阶段出错报具体文件；xdist 收集不一致单独提示"""
    out = ("ERROR collecting tests/test_a.py\nERROR collecting tests/test_b.py\n"
           "Different tests were collected between gw2 and gw10. The difference is:\n"
           "--- gw2\n+++ gw10\n-tests/test_c.py::test_x[foo]\n+tests/test_c.py::test_x[bar]\n")
    p = SV.collection_problems(out)
    assert "tests/test_a.py" in p and "tests/test_b.py" in p
    assert any("xdist" in x and "tests/test_c.py" in x for x in p)


def test_cut_gates_run_on_frozen_snapshot_and_commit_frozen_tree():
    """K-OPS-F08 静态检查：冻结窗口 → 冻结树 → 快照 → 闸门对快照跑 → commit-tree 冻结树（不 git add 活的工作树）→ finally 解锁"""
    s = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    c = s[s.index("def cut("):s.index("PUSH_SECRET_RE")]
    order = [c.index(x) for x in ("cut_lock(True", "freeze_tree(", "build_snapshot(", "gates(", "commit-tree", "update-ref")] + [c.rindex("finally:")]
    assert order == sorted(order)
    assert 'git("add", "-A")' not in c and "root=Path(snap[\"dir\"])" in c
    assert "cut_lock(False" in c[c.rindex("finally:"):]


def test_lock_status_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(SV, "CUT_LOCK", tmp_path / "cut_lock.json")
    monkeypatch.setattr(SV, "DATA", tmp_path)
    assert SV.cut_locked() is None
    SV.cut_lock(True, "sv-x")
    assert SV.cut_locked()["sv"] == "sv-x"
    assert SV.cut_locked(now=__import__("time").time() + 46 * 60) is None      # 45 分钟到期自动失效
    SV.cut_lock(False, "sv-x")
    assert SV.cut_locked() is None and (tmp_path / "cut_lock.json").exists()   # 不删文件



def test_deploy_does_not_queue_restart_when_server_decision_files_missing(tmp_path):
    """K-OPS-F09：服务器决策文件不齐（例：config/pipeline/run.json 没到）→ 不排重启，老进程继续生产"""
    rs, pc, rq = _FakeRS(tmp_path), _FakePC(), _FakeRQ()
    (tmp_path / "tools").mkdir()
    rs.guard_rc = 1
    r = SV.deploy_host(rs, "gpu36", tmp_path, [], [], "sv-x", "c", restart=True, pc=pc, rq=rq)
    assert r["ok"] is False and "决策文件不齐" in r["error"] and rq.reqs == []



def test_deploy_refuses_restart_when_server_deps_missing(tmp_path):
    """服务器 venv 缺 mediapipe / 模型 sha 不符 → 不排重启（config/deploy/server_deps.yaml）"""
    rs, pc, rq = _FakeRS(tmp_path), _FakePC(), _FakeRQ()
    (tmp_path / "tools").mkdir()
    rs.deps_rc = 1
    r = SV.deploy_host(rs, "gpu33", tmp_path, [], [], "sv-x", "c", restart=True, pc=pc, rq=rq)
    assert r["ok"] is False and "运行依赖不齐" in r["error"] and rq.reqs == []


def test_gates_include_vqa_regression_and_hotfix_ledger(tmp_path, monkeypatch):
    s = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    g = s[s.index("def gates("):s.index("def staged_problems(")]
    assert "tools/vqa/regression_check.py" in g
    monkeypatch.setattr(SV, "INCIDENTS", tmp_path / "inc.jsonl")
    SV.record_incident("sv-x", "hotfix", "sv-y", "n")
    rec = __import__("json").loads((tmp_path / "inc.jsonl").read_text(encoding="utf-8").strip())
    assert rec["sv"] == "sv-x" and rec["kind"] == "hotfix" and rec["fixed_by"] == "sv-y"


def test_urgent_deploy_pauses_then_restarts_now(tmp_path):
    """K-OPS-F13 修订：urgent 部署推完、核对过才暂停派单，当场重启；核对不过不暂停；重启失败恢复派单"""
    class RQ(_FakeRQ):
        def process(self, h, rs):
            return {"ok": True, "secs": 5}
    rs, pc, rq = _FakeRS(tmp_path), _FakePC(), RQ()
    (tmp_path / "tools").mkdir()
    cmds = []
    orig = rs.ssh
    rs.ssh = lambda h, cmd, data=None, tries=3: (cmds.append(cmd), orig(h, cmd, data, tries))[1]
    r = SV.deploy_host(rs, "gpu36", tmp_path, [], [], "sv-x", "c", restart=True, pc=pc, rq=rq, urgent=True)
    assert r["ok"] and "当场执行 ok=True" in r["restart"]
    pi = next(i for i, c in enumerate(cmds) if "pause" in c)
    assert pi > next(i for i, c in enumerate(cmds) if "decisions_guard" in c)      # 推送和核对都在暂停之前（暂停窗口只剩重启）
    rs2, rq2 = _FakeRS(tmp_path), RQ()
    rs2.deps_rc = 1
    cmds2 = []
    o2 = rs2.ssh
    rs2.ssh = lambda h, cmd, data=None, tries=3: (cmds2.append(cmd), o2(h, cmd, data, tries))[1]
    r2 = SV.deploy_host(rs2, "gpu36", tmp_path, [], [], "sv-x", "c", restart=True, pc=pc, rq=rq2, urgent=True)
    assert r2["ok"] is False and not any("pause" in c for c in cmds2)   # 依赖不齐：根本不暂停，老进程照常派单
    class RQBad(_FakeRQ):
        def process(self, h, rs):
            return {"ok": False, "error": "drain timeout"}
    rs3 = _FakeRS(tmp_path)
    cmds3 = []
    o3 = rs3.ssh
    rs3.ssh = lambda h, cmd, data=None, tries=3: (cmds3.append(cmd), o3(h, cmd, data, tries))[1]
    r3 = SV.deploy_host(rs3, "gpu36", tmp_path, [], [], "sv-x", "c", restart=True, pc=pc, rq=RQBad(), urgent=True)
    assert r3.get("resumed_after_fail") and "resume" in cmds3[-1]          # 暂停后重启失败：恢复派单


def test_quiet_since_waits_for_quiet(monkeypatch, tmp_path):
    """预冻结：冻结目录最近改动不足 60 s 就等；够了才放行"""
    f = tmp_path / "tools" / "x.py"
    f.parent.mkdir()
    f.write_text("x=1")
    monkeypatch.setattr(SV, "ROOT", tmp_path)
    monkeypatch.setattr(SV, "pending_changes", lambda: [("M", "tools/x.py"), ("M", "docs/y.md")])
    now = [f.stat().st_mtime + 5]
    slept = []
    q = SV.quiet_since(60, max_wait=600, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)), clock=lambda: now[0])
    assert q["ok"] and slept and q["last_file"] == "tools/x.py"


def test_cut_sets_exempt_and_prefreeze():
    s = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    c = s[s.index("def cut("):s.index("PUSH_SECRET_RE")]
    assert c.index('NS_FREEZE_EXEMPT') < c.index("cut_lock(True") < c.index("quiet_since(60)") < c.index("freeze_tree(")
    assert "FREEZE_DRIFT" in c and "LOCK_HISTORY" in s


def test_hot_files_skip_recently_changed_tier1_data(tmp_path):
    """总调度 11-02 15:4x：部署时第一级数据里最近 120 s 还在改的文件不推（交给常驻同步循环之后补）"""
    import time as _t

    class RS:
        CODE_DIRS = ["tools"]

        def push_dirs(self, code_only, tier):
            return (["data"], ["data"])

        def local_manifest(self, dirs):
            now = _t.time()
            return {"data/import/script_v2.json": (10, now - 5), "data/assets/identity_refs/a.png": (10, now - 3600),
                    "data/renders/x.png": (10, now - 1)}

        def tier_of(self, f, sz):
            return 2 if f.startswith("data/renders/") else 1
    assert SV.hot_files(RS()) == ["data/import/script_v2.json"]
    assert SV.hot_files(object()) == []                                   # 量不了 → 不跳过任何文件


def test_verified_install_refuses_truncated_stdin(tmp_path):
    """11-02 16:02：gpu36 expected_refs.json 被写成 0 字节——stdin 传丢时不许替换，命令失败"""
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if not bash:
        import pytest
        pytest.skip("no bash")
    dest = (tmp_path / "e.json").as_posix()
    (tmp_path / "e.json").write_bytes(b"old")
    cmd = SV._verified_install(dest, b'{"a": 1}')
    bad = subprocess.run([bash, "-c", cmd], input=b"", capture_output=True, timeout=60)
    assert bad.returncode != 0 and (tmp_path / "e.json").read_bytes() == b"old"
    ok = subprocess.run([bash, "-c", cmd], input=b'{"a": 1}', capture_output=True, timeout=60)
    assert ok.returncode == 0 and (tmp_path / "e.json").read_bytes() == b'{"a": 1}'


def test_deploy_hold_data_not_pushed(tmp_path):
    """总调度 17:4x：--hold-data 列的数据本次部署不推（first_frame_jobs.json 等新代码上线、重编、测试绿后才推）"""
    rs, pc = _FakeRS(tmp_path), _FakePC()
    (tmp_path / "tools").mkdir(exist_ok=True)
    seen = {}
    orig_push = rs.push

    def push(h, code_only=False, tier=2, yes=False, gate=True, **kw):
        w = getattr(rs, "wanted", None)
        if w is not None and not code_only:
            seen["held"] = w("data/pipeline/runs/series10_v1/assets/first_frame_jobs.json", {}, {}, 0, set())
            seen["other"] = w("data/import/script_v2.json", {}, {}, 0, set())
        return orig_push(h, code_only=code_only, tier=tier, yes=yes, gate=gate, **kw)
    rs.push = push
    r = SV.deploy_host(rs, "gpu36", tmp_path, [], [], "sv-x", "c", restart=False, pc=pc,
                       hold_data=["data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"])
    assert "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json" in r["hot_skipped"]
    assert seen == {"held": False, "other": True}
