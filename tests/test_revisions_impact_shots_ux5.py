"""UX5 实现：POST /api/revisions/impact-shots（形象 / 单品 / 场景的影响面，只读）。

前端按集摘要算出“用到这个资产的镜头”，这个接口只补每格当前 / 定稿状态；口径与 /api/revisions/impact 一致：
已定稿默认不勾、GPU 时间同一套估算、不写任何东西、不提交任务。全部在临时项目根里跑。
"""
from __future__ import annotations

from test_asset_revs_p0 import client, root  # noqa: F401 — 复用 P0 的临时项目根与客户端夹具


def test_impact_shots_marks_locked_unselected(client, root):  # noqa: F811
    r = client.post("/api/revisions/impact-shots",
                    json={"shots": ["ep02-S1", "ep02-S2", "ep02-S2", "ep99-S1", "bad id"], "label": "林晚 · 形象 A"}).json()
    cells = {(c["shot_id"], c["stage"]): c for c in r["cells"]}
    assert set(cells) == {("ep02-S1", "image"), ("ep02-S2", "image")}          # 去重；不存在 / 非法的跳过
    assert cells[("ep02-S1", "image")]["locked"] is True
    assert cells[("ep02-S1", "image")]["default_selected"] is False
    assert cells[("ep02-S1", "image")]["chain"] == ["last", "video"]
    assert cells[("ep02-S2", "image")]["default_selected"] is True
    assert all(c["estimated"] for c in r["cells"])
    assert r["counts"]["locked"] == 1 and r["counts"]["unlocked"] == 1
    assert r["gpu_estimate_s"]["default_selected"] == {"jobs": 1, "serial": 60.0, "parallel": 30.0}
    assert r["changes"][0]["label"] == "林晚 · 形象 A" and r["requires_owner"] is False
    assert not (root / "data" / "assets" / "revisions.jsonl").exists()        # 只读


def test_impact_shots_stages_and_validation(client):  # noqa: F811
    r = client.post("/api/revisions/impact-shots", json={"shots": ["ep02-S1"], "stages": ["video"]}).json()
    assert [(c["shot_id"], c["stage"]) for c in r["cells"]] == [("ep02-S1", "video")]
    assert r["cells"][0]["locked"] is False and r["cells"][0]["default_selected"] is True
    assert client.post("/api/revisions/impact-shots", json={"shots": []}).status_code == 422
    assert client.post("/api/revisions/impact-shots", json={"shots": ["ep02-S1"], "stages": ["cut"]}).status_code == 422


def test_impact_unchanged_after_refactor(client):  # noqa: F811
    r = client.post("/api/revisions/impact", json={"changes": [{"key": "identity:lin_wan"}]}).json()
    assert r["counts"] == {"cells": 2, "shots": 2, "locked": 1, "owner_locked": 1, "unlocked": 1, "estimated": 1}
    assert r["changes"][0]["key"] == "identity:lin_wan" and r["requires_owner"] is True
