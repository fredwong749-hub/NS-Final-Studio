# 11-08 总指令 第二部分 裁决 #4（R2 第三层）：冒烟夹具剧（runs.json kind=smoke）平时 paused，
# 也要进期望 refs 表，否则 G4 窗口里笔记本冒烟 producer 被 K-OPS-F03 拒派（"期望 refs 表里没有剧 smoke_v2"）
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/factory"))
import inbox as IB

REG = {"primary": "main", "runs": {
    "main": {"status": "producing"},
    "smoke_v2": {"status": "paused", "kind": "smoke"},
    "old": {"status": "archived"},
    "s2": {"status": "paused"},
}}


def _fake(tmp_path, have=("main", "smoke_v2", "old", "s2")):
    def import_path(r, root):
        p = tmp_path / f"{r}.json"
        if r in have:
            p.write_text("{}", encoding="utf-8")
        return p
    return SimpleNamespace(primary_run=lambda root: "main", registry=lambda root: REG,
                           list_runs=lambda root, status=None: list(REG["runs"]), import_path=import_path)


def test_paused_smoke_run_is_in_expected_table(tmp_path, monkeypatch):
    monkeypatch.setattr(IB, "_runs_for", lambda root: _fake(tmp_path))
    prim, runs = IB._runs(tmp_path)
    assert prim == "main" and "smoke_v2" in runs


def test_other_paused_or_archived_runs_still_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(IB, "_runs_for", lambda root: _fake(tmp_path))
    _p, runs = IB._runs(tmp_path)
    assert "old" not in runs and "s2" not in runs and runs[0] == "main"


def test_smoke_run_without_import_file_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(IB, "_runs_for", lambda root: _fake(tmp_path, have=("main",)))
    _p, runs = IB._runs(tmp_path)
    assert runs == ["main"]
