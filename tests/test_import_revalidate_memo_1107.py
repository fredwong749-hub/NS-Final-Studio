# 11-07 冒烟 A6：进程内记忆命中也要落盘；测试剧预期 block 豁免
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/master"))
import import_revalidate as R


def _setup(tmp_path, monkeypatch):
    src = tmp_path / "data/pipeline/runs/smoke_v2/P4_ep01.md"
    src.parent.mkdir(parents=True)
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(R, "imported_source", lambda run, ep, root, a=None, b=None: {"path": src, "sha": "s1"})
    monkeypatch.setattr(R, "ruleset_fingerprint", lambda root: {"fp": "f1"})
    monkeypatch.setattr(R, "_report_issue", lambda *a, **k: None)
    R._MEMO.clear()
    rep = {"blocking": 2, "counts": {"QW-E2|block": 1, "QW-E3|block": 1}, "episodes_found": 1}
    return lambda root, path, ep, t: rep


def test_memo_hit_rewrites_missing_file(tmp_path, monkeypatch):
    runner = _setup(tmp_path, monkeypatch)
    R.revalidate("smoke_v2", 1, root=tmp_path, cfg=dict(R.DEFAULT), runner=runner)
    cp = R._cache_path(tmp_path, "smoke_v2")
    assert cp.exists()
    cp.unlink()                                    # 冒烟第二遍：目录被隔离清空
    r2 = R.revalidate("smoke_v2", 1, root=tmp_path, cfg=dict(R.DEFAULT), runner=runner)
    assert r2["cached"] and cp.exists()
    assert "ep01|s1|f1" in json.loads(cp.read_text(encoding="utf-8"))["results"]


def test_expected_blocks_waived_only_for_listed_run(tmp_path, monkeypatch):
    runner = _setup(tmp_path, monkeypatch)
    cfg = {**R.DEFAULT, "expected_blocks": {"smoke_v2": ["QW-E2", "QW-E3"]}}
    r = R.revalidate("smoke_v2", 1, root=tmp_path, cfg=cfg, runner=runner)
    assert r["blocking"] == 0 and r["waived"] == {"QW-E2": 1, "QW-E3": 1}
    R._MEMO.clear()
    r = R.revalidate("series10_v2", 1, root=tmp_path, cfg=cfg, runner=runner)
    assert r["blocking"] == 2
