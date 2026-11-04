"""L-187（项目方 11-04）：L-183“重试用尽自动取最高分”改为开关 review_adopt_auto，默认关；手工 CLI review-adopt 不受影响。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import producer as PR  # noqa: E402


def _paths(tmp_path, cfg=None):
    if cfg is not None:
        d = tmp_path / "config" / "pipeline"
        d.mkdir(parents=True)
        (d / "producer.json").write_text(json.dumps(cfg), encoding="utf-8")
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True, exist_ok=True)
    return paths


def test_switch_missing_or_bad_is_off(tmp_path):
    assert PR.review_adopt_auto(tmp_path) is False                       # 文件不存在
    p = _paths(tmp_path, {"fanout": {}})
    assert PR.review_adopt_auto(p.root) is False                         # 键缺失


def test_switch_repo_default_off():
    assert PR.review_adopt_auto(ROOT) is False


def test_off_does_not_adopt(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(PR, "review_adopt", lambda *a, **k: called.append(1) or 5)
    paths = _paths(tmp_path)
    assert PR.auto_review_adopt(paths, "first:ep01-S4", {1, 2}) is None
    assert not called
    assert "review_adopt_skipped" in paths.log.read_text(encoding="utf-8")


def test_off_string_true_still_off(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "review_adopt", lambda *a, **k: 5)
    paths = _paths(tmp_path, {"review_adopt_auto": "true"})
    assert PR.auto_review_adopt(paths, "first:ep01-S4") is None


def test_on_calls_review_adopt(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(PR, "review_adopt", lambda paths, oid, n=None, by="", ns=None: seen.update(oid=oid, ns=ns) or 5)
    paths = _paths(tmp_path, {"review_adopt_auto": True})
    assert PR.auto_review_adopt(paths, "first:ep01-S4", {1, 2}) == 5
    assert seen == {"oid": "first:ep01-S4", "ns": {1, 2}}


def test_manual_cli_works_with_switch_off(tmp_path, monkeypatch, capsys):
    paths = _paths(tmp_path, {"review_adopt_auto": False})
    monkeypatch.setattr(PR, "Paths", lambda *a, **k: paths)
    monkeypatch.setattr(PR, "review_adopt", lambda p, oid, n=None, by="": 4)
    monkeypatch.setattr(PR, "default_run", lambda: "r")
    from unittest.mock import MagicMock
    monkeypatch.setattr(PR, "_runs", lambda: MagicMock())
    rc = PR.main(["review-adopt", "--obj", "first:ep01-S4", "--by", "W"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["adopted"] == 4
    assert json.loads(paths.ledger.read_text(encoding="utf-8"))["first:ep01-S4"]["final"] == "passed"
