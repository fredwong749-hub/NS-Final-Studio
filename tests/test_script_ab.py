"""剧本 A/B 对比：两版同集逐镜字段；选择只由项目方记录（占位剧本，不是剧情文本）"""
from pathlib import Path

from fastapi.testclient import TestClient

from ns_api import script_ab as AB
from ns_api import script_inbox as SI
from ns_api.app import app

c = TestClient(app)

SCRIPT = """## ep01《占位》

**剧情**：占位

**配乐**：【BGM】Sparse piano at a slow tempo.

**镜1｜img**：`占位画面{tag}`

**motion**：`占位运动——占位结束`

**时长**：8秒

**sound**：【H3 audio】Room tone.【配乐】进入，强度1

**对白**：无
"""


def _setup(monkeypatch, tmp_path):
    a, b = tmp_path / "A.md", tmp_path / "B.md"
    a.write_text(SCRIPT.format(tag="甲"), encoding="utf-8")
    b.write_text(SCRIPT.format(tag="乙"), encoding="utf-8")
    monkeypatch.setattr(SI, "REPO", tmp_path)
    monkeypatch.setattr(SI, "DATA", tmp_path / "data")
    monkeypatch.setattr(SI, "_allowed", lambda path: tmp_path / Path(path).name)
    monkeypatch.setattr(AB, "CHOICES", tmp_path / "data" / "import" / "ab_choices.jsonl")
    return a, b


def test_episode_side_by_side(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    r = c.get("/api/script-ab/episode", params={"a": "A.md", "b": "B.md", "ep": 1}).json()
    sa, sb = r["a"]["episode"]["shots"][0], r["b"]["episode"]["shots"][0]
    assert sa["img"].endswith("甲") and sb["img"].endswith("乙")
    assert sa["last_state"] == "占位结束" and sa["duration"] == 8
    assert sa["renders"] == {"first": None, "last": None, "video": None}


def test_choice_owner_only(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    body = {"ep": 1, "shot": "ep01-S1", "pick": "B", "a": "A.md", "b": "B.md", "by": "someone"}
    assert c.post("/api/script-ab/choice", json=body).status_code == 403
    body["by"] = "owner"
    assert c.post("/api/script-ab/choice", json={**body, "pick": "C"}).status_code == 422
    row = c.post("/api/script-ab/choice", json=body).json()
    assert row["pick"] == "B" and len(row["a_sha256"]) == 64
    assert [x["pick"] for x in c.get("/api/script-ab/choices", params={"ep": 1}).json()] == ["B"]
