"""W17 RELEASE-AUTO：发版流水线（tools/autopilot/release_tick.py + tools/qa/system_version.py build_tree_from_list / run_watched）。
全部在临时 git 仓 + 打桩的 cut / deploy / rs 上跑：不 commit 真仓库、不碰服务器、不写真实 data/。"""
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SV = _load("tools/qa/system_version.py", "ns_sv_release_t")
RT = _load("tools/autopilot/release_tick.py", "ns_release_tick_t")


def _git(repo, *a):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *a], cwd=repo,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    for f, t in {"a.txt": "a0\n", "b.txt": "b0\n", "c.txt": "c0\n"}.items():
        (r / f).write_text(t)
    (r / "docs/master").mkdir(parents=True)
    (r / "docs/CHANGELOG_AGENTS.md").write_text("# log\n")
    (r / "docs/master/V2_LIVE.md").write_text("# V2 LIVE\nold line\n")
    (r / "config/pipeline").mkdir(parents=True)
    (r / "config/pipeline/runs.json").write_text(json.dumps({"primary": "series10_v2", "runs": {"series10_v2": {}}}))
    (r / ".gitignore").write_text("data/\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    (r / "LIST.txt").write_text("a.txt\n")
    monkeypatch.setattr(SV, "CUT_LOCK", tmp_path / "cut_lock.json")      # 真机此刻可能有 cut 在跑：锁文件换成临时的
    return r


CFG = {"enabled": True, "pytest_n": 4, "xdist_stall_min": 10, "hosts": ["gpu33", "gpu36"], "verify_shot": 8, "verify_run": "series10_v2",
       "handover": {"min_stage": "出图", "laptop_ps1": "ops/autostart/restart_producer.ps1",
                    "legacy_procs": [{"name": "bench2", "host": "gpu33", "match": r"bench2\.py"},
                                     {"name": "bakeoff", "host": "gpu36", "match": r"run\.py gen --models=|score_srv\.py", "cwd_match": "/bakeoff/"}]}}


def _req(repo, **kw):
    req = {"schema": "nsfs.release_request/1", "list": "LIST.txt",
           "reviews": [{"group": f"G{i}", "verdict": "可入", "p0": []} for i in range(2, 8)],      # W17b P1-3：G2–G7 必须齐
           "requested_by": "MASTER-WSL", "at": "2026-11-03T14:00:00", "deploy": True, "handover": True, **kw}
    p = repo / RT.REQ_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
    return req


class FakeRunner:
    def __init__(self, dry_ok=True, cut_ok=True, deploy_ok=True, gate=None):
        self.calls, self.dry_ok, self.cut_ok, self.deploy_ok, self.gate = [], dry_ok, cut_ok, deploy_ok, gate

    def cut(self, tree, dry):
        self.calls.append(("cut", tree, dry))
        if self.gate:
            self.gate.wait(10)
        ok = self.dry_ok if dry else self.cut_ok
        return {"ok": ok, "id": "sv-20261103-09", "tree": tree, "commit": None if dry else "c0ffee1234",
                "reason": None if ok else "闸门不过：定向 pytest：1 failed", "gates": [{"id": "pytest", "ok": ok, "detail": "x"}]}

    def deploy(self, sv_id, hosts, shot, run):
        self.calls.append(("deploy", sv_id, tuple(hosts), shot, run))
        return {"ok": self.deploy_ok, "hosts": {h: {"ok": True} for h in hosts},
                "verify": {"ok": self.deploy_ok, "reason": None if self.deploy_ok else "gpu36 golden 不一致"},
                "reason": None if self.deploy_ok else "verify 不过"}


def _issues(repo):
    p = repo / RT.ISSUES_REL
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---------------------------------------------------------------- 拼树
def test_build_tree_from_list_blob_delete_and_untouched_index(repo):
    (repo / "a.txt").write_text("a1\n")
    (repo / "c.txt").unlink()
    (repo / "d.txt").write_text("d1\n")
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input="b-approved\n", capture_output=True, text=True, timeout=60).stdout.strip()
    (repo / "b.txt").write_text("b-worktree-later\n")
    (repo / "LIST.txt").write_text(f"# 注释\na.txt\nb.txt@{blob}\nc.txt\n\nd.txt\n", encoding="utf-8")
    st0 = _git(repo, "status", "--porcelain")
    out = SV.build_tree_from_list(repo / "LIST.txt", "HEAD", repo=repo)
    names = _git(repo, "ls-tree", "-r", "--name-only", out["tree"]).split()
    assert "c.txt" not in names and "d.txt" in names and out["removed"] == ["c.txt"]
    assert _git(repo, "cat-file", "-p", f"{out['tree']}:b.txt") == "b-approved\n"      # path@blob 用复审时的版本，不用工作树
    assert _git(repo, "cat-file", "-p", f"{out['tree']}:a.txt") == "a1\n"
    assert _git(repo, "status", "--porcelain") == st0                                 # 仓库 index / HEAD 没动


def test_build_tree_rejects_missing_item(repo):
    (repo / "LIST.txt").write_text("nope.txt\n")
    with pytest.raises(RuntimeError, match="nope.txt"):
        SV.build_tree_from_list(repo / "LIST.txt", "HEAD", repo=repo)


# ---------------------------------------------------------------- release_once
def test_green_path_cut_dry_cut_deploy_and_records(repo):
    (repo / "a.txt").write_text("a1\n")
    _req(repo)
    fr = FakeRunner()
    res = RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)
    assert res["status"] == "done" and res["deployed"] is True and res["sv"] == "sv-20261103-09"
    assert [c[0] for c in fr.calls] == ["cut", "cut", "deploy"] and fr.calls[0][2] is True and fr.calls[1][2] is False
    assert fr.calls[0][1] == fr.calls[1][1] == res["tree"]                             # dry 和正式 cut 用同一棵树
    assert fr.calls[2][1:] == ("sv-20261103-09", ("gpu33", "gpu36"), 8, "series10_v2")
    saved = json.loads((repo / RT.RES_REL).read_text(encoding="utf-8"))
    assert saved["status"] == "done" and saved["schema"] == "nsfs.release_result/1"
    assert "发版 sv-20261103-09（release_tick 自动" in (repo / "docs/CHANGELOG_AGENTS.md").read_text(encoding="utf-8")
    assert "✅ 发版（release_tick）：sv-20261103-09" in (repo / "docs/master/V2_LIVE.md").read_text(encoding="utf-8").splitlines()[1]
    assert _issues(repo) == []
    again = RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)                         # 同一份请求只跑一次
    assert again["status"] == "already" and len(fr.calls) == 3


def test_gate_red_stops_and_reports(repo):
    _req(repo)
    fr = FakeRunner(dry_ok=False)
    res = RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)
    assert res["status"] == "failed" and res["step"] == "cut --dry" and len(fr.calls) == 1   # 红了就停：不 cut、不 deploy
    iss = _issues(repo)
    assert len(iss) == 1 and iss[0]["who"] == "release_tick" and iss[0]["blocking"] is True and iss[0]["step"] == "release:cut --dry"
    assert "⚠ 卡点（release_tick）" in (repo / "docs/master/V2_LIVE.md").read_text(encoding="utf-8")
    assert "发版 sv-" not in (repo / "docs/CHANGELOG_AGENTS.md").read_text(encoding="utf-8")
    assert RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)["status"] == "already" and len(_issues(repo)) == 1   # 不每拍重复登记


def test_deploy_red_is_not_deployed(repo):
    _req(repo)
    res = RT.release_once(repo, sv=SV, runner=FakeRunner(deploy_ok=False), cfg=CFG)
    assert res["status"] == "failed" and res["step"] == "deploy" and res["deployed"] is False
    assert _issues(repo)[0]["step"] == "release:deploy"


def test_not_approved_does_nothing(repo):
    _req(repo, reviews=[{"group": f"G{i}", "verdict": "待复审" if i == 5 else "可入", "p0": []} for i in range(2, 8)])
    fr = FakeRunner()
    res = RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)
    assert res["status"] == "not_approved" and fr.calls == [] and _issues(repo) == []
    _req(repo, reviews=[{"group": f"G{i}", "verdict": "可入", "p0": ["P0-1 缺测试"] if i == 2 else []} for i in range(2, 8)])
    assert RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)["status"] == "not_approved" and fr.calls == []


def test_only_one_release_at_a_time(repo):
    _req(repo)
    gate = threading.Event()
    fa = FakeRunner(gate=gate)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", RT.release_once(repo, sv=SV, runner=fa, cfg=CFG)), daemon=True)
    t.start()
    for _ in range(200):
        if fa.calls:
            break
        time.sleep(0.05)
    assert fa.calls, "A 没进到 cut"
    _req(repo, requested_by="另一个请求")                                              # 第二个请求在 A 跑的时候到
    fb = FakeRunner()
    b = RT.release_once(repo, sv=SV, runner=fb, cfg=CFG)
    assert b["status"] == "busy" and fb.calls == []
    gate.set()
    t.join(15)
    assert out["a"]["status"] == "done"
    assert RT.release_once(repo, sv=SV, runner=fb, cfg=CFG)["status"] == "done" and fb.calls       # A 结束后 B 才跑


def test_cut_lock_active_means_wait(repo):
    _req(repo)
    SV.CUT_LOCK.write_text(json.dumps({"active": True, "sv": "sv-x", "expires_t": time.time() + 600, "note": "cut B dry"}))
    fr = FakeRunner()
    assert RT.release_once(repo, sv=SV, runner=fr, cfg=CFG)["status"] == "busy" and fr.calls == []
    assert not (repo / RT.RES_REL).exists()


def test_disabled_and_idle(repo):
    assert RT.release_once(repo, sv=SV, runner=FakeRunner(), cfg=CFG)["status"] == "idle"
    _req(repo)
    assert RT.release_once(repo, sv=SV, runner=FakeRunner(), cfg={**CFG, "enabled": False})["status"] == "disabled"


# ---------------------------------------------------------------- handover（L-152）
class FakeRS:
    HOSTS = {"gpu33": [0], "gpu36": [0]}

    def __init__(self):
        self.restarts, self.cmds = [], []

    def request_restart(self, host, reason, by="x", urgent=False):
        self.restarts.append((host, reason, by))
        return {"id": f"rq-{host}"}

    def ssh(self, host, cmd, data=None, timeout=900, tries=5):
        self.cmds.append((host, cmd))
        if cmd.startswith("kill"):
            return "".join(f"STOPPED {p}\n" for p in cmd.split(";")[0].split()[2:]).encode()
        rows = {"gpu33": ["136364\t1\t/root/build_sage\t/root/env/comfy/bin/python bench2.py h3 1,3,0 kitchen h3b",
                          "5001\t1\t/root/work/fredw/offline_20261101/repo\tpython -u tools/autopilot/producer.py serve --run series10_v2 bench2.py"],
                "gpu36": ["2440296\t1\t/root/work/fredw/bakeoff/srv\tbash -c run.py gen --models=qa_base; score_srv.py",
                          "2440298\t2440296\t/root/work/fredw/bakeoff/srv\tpython run.py gen --models=qa_base,qa_native",
                          "7777\t1\t/tmp\tpython run.py gen --models=other"]}[host]
        return ("\n".join(rows) + "\n").encode()


def _deployed(repo, handover=True, attempted=False):
    res = {"schema": RT.RES_SCHEMA, "status": "done", "deployed": True, "deployed_hosts": ["gpu33", "gpu36"], "sv": "sv-20261103-09",
           "request": {"handover": handover}}
    if attempted:
        res["handover"] = {"attempted": True, "at": "x"}
    p = repo / RT.RES_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")


def _stage(idx):
    return lambda root, run: {"stages": RT.STAGES_FALLBACK, "best_index": idx, "best_stage": RT.STAGES_FALLBACK[idx] if idx >= 0 else None,
                              "best_episode": 1, "run_stage": "剧本"}


def test_handover_conditions_not_met_does_nothing(repo):
    rs, lap = FakeRS(), []
    lapf = lambda *a: lap.append(a) or {"ok": True}  # noqa: E731
    out = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=_stage(4), laptop_fn=lapf, cfg=CFG)   # 还没有 release_result
    assert out.get("skipped") and not rs.restarts and not rs.cmds and not lap
    _deployed(repo)
    out = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=_stage(3), laptop_fn=lapf, cfg=CFG)   # 阶段 = 提示词 < 出图
    assert "stage" in out["skipped"] and not rs.restarts and not rs.cmds and not lap
    _deployed(repo, handover=False)
    out = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=_stage(5), laptop_fn=lapf, cfg=CFG)
    assert "handover_requested" in out["skipped"] and not rs.restarts and not lap


def test_handover_dry_lists_four_steps_without_acting(repo):
    _deployed(repo)
    rs, lap = FakeRS(), []
    out = RT.handover_once(repo, apply=False, sv=SV, rs=rs, stage_fn=_stage(4), laptop_fn=lambda *a: lap.append(a), cfg=CFG)
    assert out["mode"] == "dry" and out["ready"] and [s["n"] for s in out["steps"]] == [1, 2, 3, 4]
    assert not rs.restarts and not rs.cmds and not lap
    txt = RT.format_handover(out)
    assert "restart_producer.ps1" in txt and "L-152 handover" in txt and "bench2" in txt and "V2_LIVE" in txt


def test_handover_apply_runs_steps_once(repo):
    _deployed(repo)
    rs, lap = FakeRS(), []
    out = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=_stage(4),
                           laptop_fn=lambda root, ps1, run: lap.append((ps1, run)) or {"ok": True, "out": "producer[series10_v2] restarted"}, cfg=CFG)
    assert out["ok"] and lap == [("ops/autostart/restart_producer.ps1", "series10_v2")]
    assert rs.restarts == [("gpu33", "L-152 handover", "release_tick"), ("gpu36", "L-152 handover", "release_tick")]
    killed = [json.loads(x) for x in (repo / RT.KILLED_REL).read_text(encoding="utf-8").splitlines()]
    assert sorted((k["host"], k["pid"]) for k in killed) == [("gpu33", 136364), ("gpu36", 2440296), ("gpu36", 2440298)]  # producer / 别处的 run.py 不停
    assert all(k["signal"] == "TERM" and k["result"] == "STOPPED" for k in killed)
    assert not any("rm " in c for _h, c in rs.cmds)                                   # 只停不删
    saved = json.loads((repo / RT.RES_REL).read_text(encoding="utf-8"))
    assert saved["handover"]["attempted"] and saved["handover"]["done"]
    assert (repo / "docs/master/V2_LIVE.md").read_text(encoding="utf-8").count("换代 L-152") == 3
    again = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=_stage(4), laptop_fn=lambda *a: lap.append(a), cfg=CFG)
    assert "not_attempted" in again["skipped"] and len(lap) == 1 and len(rs.restarts) == 2


def test_handover_step_failure_reports_issue(repo):
    _deployed(repo)
    rs = FakeRS()
    out = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=_stage(4), laptop_fn=lambda *a: {"ok": False, "error": "pwsh 不在"}, cfg=CFG)
    assert out["ok"] is False
    iss = _issues(repo)
    assert len(iss) == 1 and iss[0]["step"] == "handover:laptop_producer" and iss[0]["who"] == "release_tick"
    # W17b P1-5：第 ① 步失败即停——不投服务器重启、不停旧进程
    assert rs.restarts == [] and rs.cmds == [] and not (repo / RT.KILLED_REL).exists()
    ho = json.loads((repo / RT.RES_REL).read_text(encoding="utf-8"))["handover"]
    assert ho["aborted_at"] == "laptop_producer" and ho["skipped"] == ["server_restart", "stop_legacy"] and ho["done"] is False


# ---------------------------------------------------------------- xdist 僵死自愈
def test_run_watched_kills_stalled_tree():
    t0 = time.time()
    code, out, info = SV.run_watched([sys.executable, "-c", "import time; time.sleep(60)"], 120, stall_s=0.6, poll_s=0.1,
                                     cpu_fn=lambda pid: 0.0)
    assert info["stalled"] and code == 125 and time.time() - t0 < 30


def test_run_watched_normal_exit():
    busy = iter(range(0, 10 ** 6, 5))                                                   # CPU 一直在涨 = 没僵死（Windows 起 python 慢）
    code, out, info = SV.run_watched([sys.executable, "-c", "print('ok 5 passed')"], 60, stall_s=0.5, poll_s=0.1, cpu_fn=lambda pid: float(next(busy)))
    assert code == 0 and "5 passed" in out and not info["stalled"]


def test_proc_tree_cpu_sums_descendants_only():
    table = [(10, 1, 5.0), (11, 10, 2.0), (12, 11, 0.5), (13, 1, 9.0)]
    assert SV.proc_tree_cpu(10, table) == 2.5


def test_gates_xdist_stall_retries_with_half_n(monkeypatch):
    monkeypatch.setenv("NS_CUT_PYTEST_N", "4")
    monkeypatch.setenv("NS_CUT_XDIST_STALL_S", "600")
    outs = {"decision_check.py": (0, "合计 2：✅ 2  ❌ 0  ⏳ 0")}
    monkeypatch.setattr(SV, "sh", lambda cmd, timeout=1800, cwd=None, env=None: next((v for k, v in outs.items() if any(k in c for c in cmd)), (0, "ok")))
    calls = []

    def fake_watch(cmd, timeout, cwd=None, env=None, stall_s=600, **kw):
        calls.append(cmd[cmd.index("-n") + 1] if "-n" in cmd else "serial")
        return (125, "", {"stalled": True, "elapsed_s": 601.0, "cpu_delta": 0.2}) if len(calls) == 1 else (0, "7 passed in 3s", {"stalled": False})
    monkeypatch.setattr(SV, "run_watched", fake_watch)
    rows = {r["id"]: r for r in SV.gates([], run_tests=True)}
    assert calls == ["4", "serial"]                                                    # 僵死 → 直接退到不带 -n 的串行
    py = rows["pytest"]
    assert py["ok"] and py["xdist_heal"]["n"] == 4 and py["xdist_heal"]["retry_n"] == 0 and py["xdist_heal"]["retry_stalled"] is False
    assert py["passed"] == 7 and py["n"] == 4


def test_pytest_n_zero_means_no_xdist(monkeypatch):
    monkeypatch.setenv("NS_CUT_PYTEST_N", "0")
    assert SV.pytest_n() == 0
    monkeypatch.setenv("NS_CUT_PYTEST_N", "-1")
    assert SV.pytest_n() == 0
    outs = {"decision_check.py": (0, "合计 2：✅ 2  ❌ 0  ⏳ 0")}
    monkeypatch.setattr(SV, "sh", lambda cmd, timeout=1800, cwd=None, env=None: next((v for k, v in outs.items() if any(k in c for c in cmd)), (0, "ok")))
    seen = []
    monkeypatch.setattr(SV, "run_watched", lambda cmd, timeout, **kw: seen.append((cmd, timeout)) or (0, "3 passed", {"stalled": False}))
    SV.gates([], run_tests=True)
    assert len(seen) == 1 and "-n" not in seen[0][0] and seen[0][1] >= 3600


def test_release_cfg_defaults_and_repo_file():
    cfg = SV.release_cfg()
    assert cfg["enabled"] is True and cfg["pytest_n"] == 4 and cfg["hosts"] == ["gpu33", "gpu36"]
    assert any(e["name"] == "bench2" for e in cfg["handover"]["legacy_procs"])
