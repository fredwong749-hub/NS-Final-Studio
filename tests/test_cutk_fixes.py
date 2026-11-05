"""cut K 修复：①manifest 里的 data/ 路径不进发版树（否则快照不链接数据目录）；②快照对“树里带了部分文件的目录”补链其余；③picture_index 不 import research 脚本。"""
import re
from pathlib import Path

from tests.test_release_manifest import M, SV, g, mk_manifest, repo_fx, w

ROOT = Path(__file__).resolve().parents[1]


def test_build_list_text_drops_data_paths(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    w(repo, "data/x/y.json", "{}\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py", "data/x/y.json"])
    text, rep = M.build_list_text(["w1-1105"], repo)
    assert "pkg/a.py@" in text and "data/x/y.json" not in text
    assert any("data/x/y.json" in x for x in rep["warnings"])


def test_snapshot_links_rest_of_data_dir_when_tree_has_some(tmp_path, monkeypatch):
    repo = repo_fx(tmp_path)
    w(repo, ".gitignore", "data/\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "ign")
    w(repo, "data/a.txt", "a\n")
    w(repo, "data/sub/b.txt", "b\n")
    monkeypatch.setattr(SV, "ROOT", repo)
    # 模拟“树里带了 data/ 下一个文件”：先在 dest 里放一个同目录文件，再调用 build_snapshot 的补链分支
    dest = tmp_path / "snap"
    (dest / "data").mkdir(parents=True)
    (dest / "data/tracked.txt").write_text("t\n", encoding="utf-8")
    n = SV._hardlink_tree_missing(repo / "data", dest / "data")
    assert n == 2 and (dest / "data/sub/b.txt").exists() and (dest / "data/tracked.txt").exists()


def test_picture_index_has_no_research_import():
    src = (ROOT / "tools/imglab/picture_index.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+tools\.(research|vidlab)", src, re.M)
    assert "dof_metrics" in src


def test_manifest_check_does_not_silently_repin(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py"])
    M.manifest_check(["w1-1105"], repo, pin=True)
    pin_file = repo / "data/system_versions/pins/w1-1105.json"
    first = pin_file.read_text(encoding="utf-8")
    assert '"pinned_by": "w1"' in first and "pinned_at" in first
    w(repo, "pkg/a.py", "A = 2\n")                       # 别人改了工作树后再跑检查
    rep = M.manifest_check(["w1-1105"], repo, pin=True)
    assert rep["ok"] and pin_file.read_text(encoding="utf-8") == first
    assert any("工作树已变" in x for x in rep["warnings"])
    old_blob = rep["pins"]["w1-1105"]["pkg/a.py"]
    assert old_blob != g(repo, "hash-object", "pkg/a.py").strip()
    rep2 = M.manifest_check(["w1-1105"], repo, pin=True, repin=True, by="w1-author")
    assert rep2["pins"]["w1-1105"]["pkg/a.py"] == g(repo, "hash-object", "pkg/a.py").strip()
    assert '"pinned_by": "w1-author"' in pin_file.read_text(encoding="utf-8")


def test_manifest_new_path_needs_repin(tmp_path):
    repo = repo_fx(tmp_path)
    w(repo, "pkg/a.py", "A = 1\n")
    w(repo, "pkg/b.py", "B = 1\n")
    mk_manifest(repo, "w1-1105", ["pkg/a.py"])
    M.manifest_check(["w1-1105"], repo, pin=True)
    mk_manifest(repo, "w1-1105", ["pkg/a.py", "pkg/b.py"])
    rep = M.manifest_check(["w1-1105"], repo, pin=True)
    assert not rep["ok"] and any("--repin" in e for e in rep["errors"])
