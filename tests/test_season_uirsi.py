"""UIRSI：全剧总览结构接口（假剧本，候选读不到时为空）。"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import season as S  # noqa: E402

SCRIPT = {"globals": {"scene_library": [{"scene_id": "sk_a", "name": "电梯"}, {"scene_id": "sk_b", "name": "家"}]},
          "episodes": [
              {"number": 1, "title": "一", "scene_ids": ["sk_a"], "looks": [{"character": "林晚", "from_shot": 2}],
               "shots": [{"index": 1, "scene_id": "sk_a", "link": "换场", "link_carry": "无", "img_prompt": "x，特写，林晚",
                          "cast": [{"name": "林晚", "presence": "在画"}], "duration": 5},
                         {"index": 2, "scene_id": "sk_a", "link": "接力", "link_carry": "动作｜抬手", "img_prompt": "中近景",
                          "cast": [{"name": "林晚", "presence": "局部"}, {"name": "顾沉", "presence": "画外"}], "duration": 8}]},
              {"number": 2, "title": "二", "scene_ids": ["sk_b"], "looks": [],
               "shots": [{"index": 1, "scene_id": "sk_b", "link": "换场", "img_prompt": "全景", "cast": [], "duration": 6}]}]}


def test_season(monkeypatch):
    monkeypatch.setattr(S, "_script", lambda: (SCRIPT, 1.0))
    monkeypatch.setattr(S, "_cands", lambda ep: {"ep01-S1": {"image": {"active": None, "takes": [
        {"n": 1, "url": "/files/a.png", "ok": False}, {"n": 2, "url": "/files/b.png", "ok": True}]}}})
    S._cache.update(key=None, val=None)
    app = FastAPI()
    app.include_router(S.router)
    d = TestClient(app).get("/api/season").json()["episodes"]
    a, b = d[0]["shots"]
    assert a["size"] == "特写" and a["scene"] == "电梯" and a["carry"] is None and a["cand_url"] == "/files/b.png" and a["cand_n"] == 1
    assert b["size"] == "中近景" and b["link"] == "接力" and b["carry"] == "动作｜抬手" and b["switch"] == ["林晚"]
    assert [c["presence"] for c in b["cast"]] == ["局部", "画外"] and b["cand_url"] is None
    assert d[1]["scenes"] == ["家"] and d[1]["shots"][0]["id"] == "ep02-S1"
