"""11-07：阶段闸门读项目方触发清单——已触发的成人镜按普通镜走（以前闸门一律当“等项目方”，触发后整集仍被挡）"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "master"))
import sop_gate as SG  # noqa: E402


def test_triggered_adult_not_pending(tmp_path, monkeypatch):
    pd = tmp_path / "pd"
    pd.mkdir()
    (pd / "owner_triggers.json").write_text(json.dumps({"objects": ["first:ep03-S1", "last:ep03-S1", "video:ep03-S1", "first:ep04-S2"]}), encoding="utf-8")
    class R:
        @staticmethod
        def producer_dir(run, root):
            return pd
    monkeypatch.setattr(SG, "_runs", lambda: R)
    monkeypatch.setattr(SG, "_ep_shots", lambda run, ep, root: [{"index": 1, "adult": True}, {"index": 2, "adult": True}, {"index": 3}])
    assert SG.triggered_adult_shots("r", 3, tmp_path) == {1}
    assert SG.adult_shots_of("r", 3, tmp_path) == {2}


def test_unreadable_triggers_fail_closed(tmp_path, monkeypatch):
    class R:
        @staticmethod
        def producer_dir(run, root):
            return tmp_path / "missing"
    monkeypatch.setattr(SG, "_runs", lambda: R)
    monkeypatch.setattr(SG, "_ep_shots", lambda run, ep, root: [{"index": 1, "adult": True}])
    assert SG.adult_shots_of("r", 3, tmp_path) == {1}
