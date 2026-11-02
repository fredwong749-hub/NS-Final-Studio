"""冻结锁第 1 层（ops/hooks/freeze_guard.py，Claude Code PreToolUse hook；项目方 11-02 12:1x 批准；SYSARCH K-OPS-Y03）。
不起真 cut：lock_guard.lock_state 换成假的。"""
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("freeze_guard_t", ROOT / "ops/hooks/freeze_guard.py")
FG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FG)


def _run(monkeypatch, capsys, path, rc=None, boom=False):
    sys.path.insert(0, str(ROOT))
    import tools.qa.lock_guard as LG

    def fake():
        if boom:
            raise RuntimeError("lock-status 查不了")
        return rc, {}
    monkeypatch.setattr(LG, "lock_state", fake)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})))
    assert FG.main() == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


@pytest.mark.parametrize("rel", ["tools/qa/arch_scan.py", "services/api/ns_api/app.py", "knowledge/rules/x.yaml", "tests/test_x.py",
                                 "ops/hooks/freeze_guard.py", "config/vqa.json"])
def test_locked_denies_code_dirs(monkeypatch, capsys, rel):
    assert _run(monkeypatch, capsys, ROOT / rel, rc=3) == "deny"


@pytest.mark.parametrize("rel", ["docs/master/ARCH_ROADMAP.md", "data/sysarch/baseline.json"])
def test_locked_allows_docs_and_data(monkeypatch, capsys, rel):
    assert _run(monkeypatch, capsys, ROOT / rel, rc=3) == "allow"


def test_unlocked_allows(monkeypatch, capsys):
    assert _run(monkeypatch, capsys, ROOT / "tools/qa/arch_scan.py", rc=0) == "allow"


def test_lock_unknown_fails_closed_only_for_code(monkeypatch, capsys):
    assert _run(monkeypatch, capsys, ROOT / "tools/qa/arch_scan.py", boom=True) == "deny"
    assert _run(monkeypatch, capsys, ROOT / "docs/x.md", boom=True) == "allow"


def test_outside_repo_allowed(monkeypatch, capsys, tmp_path):
    assert _run(monkeypatch, capsys, tmp_path / "tools/x.py", rc=3) == "allow"


def test_bad_stdin_allows(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert FG.main() == 0
