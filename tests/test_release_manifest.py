"""交付清单 / 租约 / cut --manifests（RSI release 线 72）。全部在临时 git 仓库里跑。"""
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


M = _load("tools/release/manifest.py", "rel_manifest_t")
SV = _load("tools/qa/system_version.py", "sv_for_manifest_t")
RT = _load("tools/autopilot/release_tick.py", "rt_for_manifest_t")


def g(repo, *a):
    r = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def w(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def mk_manifest(repo, mid, files, **kw):
    d = {"worker": mid.split("-")[0], "files": files, "tests": kw.pop("tests", []), "depends_on": [],
         "default_off_switches": [], "notes": "", **kw}
    w(repo, f"data/system_versions/deliverables/{mid}.json", json.dumps(d))


def repo_fx(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    g(repo, "init", "-q")
    g(repo, "config", "user.email", "a@b")
    g(repo, "config", "user.name", "t")
    g(repo, "config", "core.autocrlf", "false")
    w(repo, "pkg/old.py", "X = 1\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "base")
    return repo


def test_check_missing_file_and_ok(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py", "pkg/nope.py"])
    rep = M.manifest_check(["w1-1105"], repo, pin=False)
    assert not rep["ok"] and any("nope.py" in e for e in rep["errors"])
    mk_manifest(repo, "w1-1105", ["pkg/a.py"])
    rep = M.manifest_check(["w1-1105"], repo, pin=True)
    assert rep["ok"], rep
    assert (repo / "data/system_versions/pins/w1-1105.json").exists()
    assert rep["pins"]["w1-1105"]["pkg/a.py"] == g(repo, "hash-object", "pkg/a.py").strip()


def test_companion_gap_import_and_config(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/old.py", "from pkg import newmod\nCFG = 'config/new_cfg.json'\n")   # 已跟踪文件被改
    w(repo, "pkg/newmod.py", "Y = 2\n")
    w(repo, "config/new_cfg.json", "{}")
    w(repo, "tests/test_new.py", "def test_x():\n    open('config/new_cfg.json')\n")
    mk_manifest(repo, "w1-1105", ["pkg/old.py"], tests=["tests/test_new.py"])
    rep = M.manifest_check(["w1-1105"], repo, pin=False)
    needs = {(x["file"], x["needs"]) for x in rep["gaps"]}
    assert ("pkg/old.py", "pkg/newmod.py") in needs
    assert ("pkg/old.py", "config/new_cfg.json") in needs
    assert ("tests/test_new.py", "config/new_cfg.json") in needs
    assert not rep["ok"]
    # 补进另一份清单后缺口消失
    mk_manifest(repo, "w2-1105", ["pkg/newmod.py", "config/new_cfg.json"])
    rep = M.manifest_check(["w1-1105", "w2-1105"], repo, pin=False)
    assert rep["ok"], rep["errors"]


def test_overlap_different_blobs_and_same(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/old.py", "X = 2\n")
    mk_manifest(repo, "w1-1105", ["pkg/old.py"])
    mk_manifest(repo, "w2-1105", ["pkg/old.py"])
    rep = M.manifest_check(["w1-1105", "w2-1105"], repo, pin=False)
    assert rep["ok"] and rep["warnings"]          # 同文件同 blob：只警告（两人看到同一份）


def test_overlap_pinned_blob_conflict(tmp_path, monkeypatch):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/old.py", "X = 2\n")
    mk_manifest(repo, "w1-1105", ["pkg/old.py"])
    mk_manifest(repo, "w2-1105", ["pkg/old.py"])
    seq = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(M, "blob_of", lambda root, rel, write=False: next(seq))
    rep = M.manifest_check(["w1-1105", "w2-1105"], repo, pin=False)
    assert not rep["ok"] and any(e.startswith("重叠") for e in rep["errors"])


def test_depends_on_missing(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py"], depends_on=["ghost-1105"])
    rep = M.manifest_check(["w1-1105"], repo, pin=False)
    assert any("ghost-1105" in e for e in rep["errors"])


def test_lease_take_conflict_release_expiry_glob(tmp_path):
    repo = tmp_path
    now = time.time()
    r1 = M.lease_take("A", ["services/agent/*.py"], repo, now=now)
    assert not r1["conflicts"]
    r2 = M.lease_take("B", ["services/agent/frame_job.py"], repo, now=now)
    assert r2["conflicts"] and r2["conflicts"][0]["worker"] == "A"
    assert len(M.leases_active(repo, now)) == 2
    # 同 worker 续租合并
    M.lease_take("A", ["docs/x.md"], repo, now=now)
    a = [x for x in M.leases_active(repo, now) if x["worker"] == "A"][0]
    assert a["paths"] == ["services/agent/*.py", "docs/x.md"]
    M.lease_release("A", ["docs/x.md"], repo, now=now)
    a = [x for x in M.leases_active(repo, now) if x["worker"] == "A"][0]
    assert a["paths"] == ["services/agent/*.py"]
    M.lease_release("A", None, repo, now=now)
    assert [x["worker"] for x in M.leases_active(repo, now)] == ["B"]
    assert M.leases_active(repo, now + 7 * 3600) == []          # 6h 过期


def test_check_warns_on_other_workers_lease(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py"])
    M.lease_take("other", ["pkg/*.py"], repo)
    rep = M.manifest_check(["w1-1105"], repo, pin=False)
    assert rep["ok"] and rep["lease_hits"] and rep["lease_hits"][0]["lease_worker"] == "other"
    M.lease_take("w1", ["pkg/a.py"], repo)
    M.lease_release("other", None, repo)
    assert M.manifest_check(["w1-1105"], repo, pin=False)["lease_hits"] == []


def test_build_tree_pins_blob_not_worktree(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    w(repo, "pkg/old.py", "X = 9\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py", "pkg/old.py"])
    out = SV.build_tree_from_manifests(["w1-1105"], "HEAD", repo=repo)
    names = g(repo, "ls-tree", "-r", "--name-only", out["tree"]).split()
    assert "pkg/a.py" in names and "pkg/old.py" in names
    assert "data/system_versions/deliverables/w1-1105.json" not in names
    assert g(repo, "show", f"{out['tree']}:pkg/old.py") == "X = 9\n"
    # 钉住：之后工作树又被别人改了，树里仍是钉住的内容（用钉 blob 直接拼）
    pin = json.loads((repo / "data/system_versions/pins/w1-1105.json").read_text())["blobs"]
    lst = tmp_path / "l.txt"
    lst.write_text("".join(f"{p}@{b}\n" for p, b in pin.items()), encoding="utf-8")
    w(repo, "pkg/old.py", "X = 10\n")
    t2 = SV.build_tree_from_list(lst, "HEAD", repo=repo)["tree"]
    assert g(repo, "show", f"{t2}:pkg/old.py") == "X = 9\n"


def test_build_tree_refuses_on_gap(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/old.py", "from pkg import newmod\n")
    w(repo, "pkg/newmod.py", "Y = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/old.py"])
    try:
        SV.build_tree_from_manifests(["w1-1105"], "HEAD", repo=repo)
        assert False, "应拒绝"
    except RuntimeError as e:
        assert "伴随缺口" in str(e)


def test_release_tick_accepts_manifests():
    base = {"schema": "nsfs.release_request/1", "reviews": [{"group": "G2", "verdict": "可入", "p0": []}]}
    assert RT.validate_request({**base, "manifests": ["w1-1105"]}) == []
    assert RT.validate_request({**base, "list": "docs/system_versions/LIST_x.txt"}) == []
    assert RT.validate_request({**base})
    assert RT.validate_request({**base, "manifests": []})


def test_cli_lease_and_check(tmp_path, monkeypatch, capsys):
    repo = repo_fx(tmp_path)
    monkeypatch.setattr(SV, "ROOT", repo)
    monkeypatch.setattr(M, "ROOT", repo)
    monkeypatch.setattr(SV, "load_manifest_mod", lambda: M)
    assert SV.main(["lease", "take", "--worker", "A", "--paths", "x/*"]) == 0
    assert SV.main(["lease", "take", "--worker", "B", "--paths", "x/y.py"]) == 3
    assert SV.main(["lease", "list"]) == 0
    w(repo, "pkg/a.py", "A = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py"])
    assert SV.main(["manifest-check", "w1-1105", "--no-pin"]) == 0
