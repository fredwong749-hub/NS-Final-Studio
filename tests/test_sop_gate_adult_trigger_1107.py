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


def test_q9_na_accepted_when_producer_passed():
    """L-215：producer 终判 ok=true 且无阻断、Q9 na（前序只记录、没跑看图）→ 闸门同口径算过；ok=false 或有阻断仍不过"""
    q9 = {"id": "Q9", "status": "na", "evidence": {"key": "x"}}
    assert SG._q9_pass({"ok": True, "blocking": [], "items": [q9]})
    assert not SG._q9_pass({"ok": False, "blocking": [], "items": [q9]})
    assert not SG._q9_pass({"ok": True, "blocking": ["Q1"], "items": [q9]})
    assert not SG._q9_pass({"ok": True, "blocking": [], "items": [{"id": "Q9", "status": "fail"}]})


def test_retro_record_only_when_not_enforced(tmp_path, monkeypatch):
    """L-215：retro_enforce=false → 复盘没 done 也不挡出图（res.retro 照记）"""
    monkeypatch.setattr(SG, "config", lambda root=None: {"enabled": True, "retro_enforce": False, "retro_parallel": True})
    monkeypatch.setattr(SG, "retro_state", lambda run, ep, root: "missing")
    called = {}
    import inspect
    src = inspect.getsource(SG.judge)
    assert 'config(root).get("retro_mode", "enforce") != "record"' in src
