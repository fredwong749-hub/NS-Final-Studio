"""L-134 待办通知中心：GET /api/owner/inbox = 待你看队列 + 写作闸门；处理完（闸门通过）自动消失，已归档的剧不出通知。"""
import json

import pytest

from ns_api import owner_inbox as OI
from ns_api import script_autoflow as SA
from ns_api import script_library as SLIB


def _w(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(SLIB, "REPO", tmp_path)
    _w(tmp_path / "config" / "pipeline" / "runs.json", {"runs": {"cur": {"status": "preparing"}, "old": {"status": "archived"}}})
    for r in ("cur", "old"):
        _w(tmp_path / "data" / "pipeline" / "runs" / r / "autoflow.json", {"verdict": "x"})
    _w(tmp_path / "data" / "pipeline" / "runs" / "cur" / "P1_storyline.json", {"title": "透明高跟"})
    st = {"verdict": "awaiting_owner_p1", "owner_gates": {"gates": {}}, "p1_review": {"latest": {"mean": 36}, "threshold": {"min_mean": 34}}, "episodes": {}}
    box = {"st": st}
    monkeypatch.setattr(SA, "status", lambda run: box["st"])
    monkeypatch.setattr(OI.OQ, "build", lambda root, now=None: {"items": [{"id": "d1", "kind": "decide"}], "counts": {"decide": 1, "spot": 0, "pick": 0}, "count": 1})
    return tmp_path, box


def test_gate_notification_then_disappears(env):
    root, box = env
    r = OI.inbox(root)
    g = [x for x in r["items"] if x["kind"] == "gate"]
    assert len(g) == 1 and g[0]["title"] == "《透明高跟》故事线写好了，等你看" and "36" in g[0]["detail"]
    assert g[0]["link"] == "#/script-create?new=1&flow=cur&anchor=story"            # 深链接：带 run 和锚点
    assert r["count"] == 2 and r["counts"] == {"gate": 1, "decide": 1, "spot": 0, "pick": 0}   # 顶栏数 = 队列 + 闸门，同一个来源
    box["st"]["owner_gates"]["gates"]["P1"] = {"status": "approved"}                 # 项目方点了“用这版”
    assert [x for x in OI.inbox(root)["items"] if x["kind"] == "gate"] == []


def test_owner_direction_notification(env):
    root, box = env
    box["st"].update(verdict="owner_direction")
    box["st"]["p1_review"]["owner_direction"] = {"why": "四轮评审都在 32 分左右，没到 34", "fill_note": "第 3 集一句简介还没写完，写手会自动补上。"}
    g = [x for x in OI.inbox(root)["items"] if x["kind"] == "gate"][0]
    assert "没到门槛" in g["title"] and "总调度转给你定方向" in g["detail"] and "写手会自动补上" in g["detail"]
    assert "不要" not in g["detail"] + g["title"]                                    # L-123：不放“不要”


def test_archived_run_gives_no_notification(env):
    root, box = env
    box["st"].update(verdict="awaiting_owner_p1")
    runs = [x["run"] for x in OI.inbox(root)["items"] if x["kind"] == "gate"]
    assert runs == ["cur"]          # old 已归档不出通知
