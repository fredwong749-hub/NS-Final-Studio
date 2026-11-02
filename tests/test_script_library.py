"""剧本库 + 造型卡“使用场景”：全在临时目录里造一部小剧，不碰生产数据。"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import script_library as SL

RUN = "demo_s1"


def _w(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _outline(ep, intimate, scenes):
    beats = [{"id": f"B{i}", "summary": "x", "scene_id": sid, "characters": chars, "est_s": 10, "purpose": "setup"} for i, (sid, chars) in enumerate(scenes, 1)]
    return {"episode": ep, "title": f"第{ep}集", "logline": f"梗概{ep}", "intimate": intimate, "target_duration_s": 60,
            "scenes": list(dict.fromkeys(s for s, _ in scenes)), "beats": beats}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(SL, "REPO", tmp_path)
    d = tmp_path / "data" / "pipeline" / "runs" / RUN
    _w(tmp_path / "config" / "pipeline" / "runs.json", {"primary": RUN, "legacy_unprefixed_run": RUN, "runs": {
        RUN: {"status": "producing"}, "old_s0": {"status": "done"}, "gone": {"status": "deleted"}}})
    for r in ("old_s0", "gone"):
        (tmp_path / "data" / "pipeline" / "runs" / r).mkdir(parents=True)
    _w(d / "P0_brief.json", {"title": "样片", "outline": "提纲", "episodes": {"from": 1, "to": 2}, "episode_lines": {"1": "a"}})
    _w(d / "P1_storyline.json", {"title": "样片", "scenes": [
        {"scene_id": "sk_gu_apartment", "name": "顾沉公寓", "time_of_day": "夜"},
        {"scene_id": "sk_office_night", "name": "深夜办公区", "time_of_day": "深夜"},
        {"scene_id": "sk_alley_ballroom", "name": "街巷与酒会厅", "time_of_day": "黄昏"}]})
    _w(d / "P2_ep01_outline.json", _outline(1, False, [("sk_office_night", ["林晚"]), ("sk_office_night", ["林晚", "顾沉"])]))
    _w(d / "ep02" / "P2_ep02_outline.json", _outline(2, True, [("sk_gu_apartment", ["林晚", "顾沉"]), ("sk_alley_ballroom", ["顾沉"])]))
    _w(d / "autoflow_ep01.json", {"verdict": "awaiting_reviewer", "awaiting": {"role": "reviewer", "step": "factcheck_ep01"}})
    _w(d / "writer_out" / "P4_ep01_r1.md", "<!-- rules_version: v2 -->\n<!-- 整集重写 r1：按七段规则 -->\n## ep01")
    _w(d / "writer_out" / "patch_ep01_a2.json", {"patches": [{"line": 1, "new": "x"}]})
    _w(d / "writer_out" / "factcheck_ep01_a1.json", "```json\n{\"ok\": false, \"deviations\": [\"人物名不一致\"]}\n```")
    _w(d / "writer_out" / "factcheck_ep01_a2.json", "```json\n{\"ok\": true, \"deviations\": []}\n```")
    _w(d / "judge_out" / "judge_ep01.result.json", {"mean": 30.6, "sigma": 0.4, "stable": True, "verdict": "stable", "problems": []})
    _w(tmp_path / "data" / "autopilot" / "coverage.json", {"live_runs": {"now": [{"run": RUN, "episode": 2, "stage": "chain", "what": "P4 没过校验"}]}})
    app = FastAPI()
    app.include_router(SL.router)
    return TestClient(app)


def test_classify_objective():
    assert SL.classify_scene("sk_gu_apartment", "顾沉公寓")["privacy"] == "私密"
    assert SL.classify_scene("sk_office_night")["privacy"] == "公开"
    b = SL.classify_scene("sk_alley_ballroom", "街巷与酒会厅")
    assert (b["place_kind"], b["privacy"]) == ("室内外", "社交")
    assert SL.classify_scene("sk_unknown_x")["privacy"] is None   # 对不上不猜


def test_library_cards_history_and_pipeline(client):
    j = client.get("/api/script-library").json()
    assert [c["run"] for c in j["current"]] == [RUN]
    assert [c["run"] for c in j["history"]] == ["old_s0"]          # 已删除的不出现
    c = j["current"][0]
    assert c["title"] == "样片" and c["duration_s"] == 120 and c["intimate_eps"] == 1
    assert c["state"] == "writing" and c["state_text"] == "写作中 1/2"   # ep01 核查中、ep02 无 autoflow 视作已导入
    states = {(p["ep"], p["state"]) for p in j["pipeline"]}
    assert (1, "checking") in states and (2, "writing") in states


def test_detail_versions_factcheck_judge(client):
    j = client.get(f"/api/script-library/{RUN}").json()
    e1, e2 = j["episodes"]
    assert e1["logline"] == "梗概1" and e1["state"] == "checking"
    labels = {v["label"]: v["reason"] for v in e1["versions"]}
    assert labels["r1"].startswith("整集重写 r1") and labels["补丁 2"] == "补丁 1 处"
    assert e1["factcheck"]["ok"] is True and e1["factcheck"]["attempt"] == 2 and e1["factcheck"]["rounds"] == 2
    assert e1["judge"]["verdict"] == "stable"
    assert e2["factcheck"] is None and e2["judge"] is None
    assert e2["intimate"] is True
    gu = next(s for s in e2["scenes"] if s["scene_id"] == "sk_gu_apartment")
    assert gu["privacy"] == "私密" and gu["intimate"] is True       # 本集 intimate + 私密 + 两人在场
    ball = next(s for s in e2["scenes"] if s["scene_id"] == "sk_alley_ballroom")
    assert ball["intimate"] is False


def test_deleted_and_unknown_404_and_brief(client):
    assert client.get("/api/script-library/gone").status_code == 404
    assert client.get("/api/script-library/nope").status_code == 404
    assert client.get("/api/script-library/..%2Fx").status_code == 404
    b = client.get(f"/api/script-library/{RUN}/brief").json()
    assert b["title"] == "样片" and b["episode_lines"] == {"1": "a"}


def test_character_usage_for_looks(client):
    u = SL.character_usage(RUN, "顾沉")
    assert [x["ep"] for x in u] == [1, 2]
    assert [s["name"] for s in u[1]["scenes"]] == ["顾沉公寓", "街巷与酒会厅"]
    assert SL.character_usage(RUN, "路人") == []


def test_ep_progress_video_locked_ratio(client, tmp_path):
    for ep, locks in ((1, [True, False, False, True]),):
        for i, lk in enumerate(locks, 1):
            _w(tmp_path / "data" / "renders" / f"ep{ep:02d}" / f"S{i}" / "takes.json", {"locked": {"video": 3} if lk else {}})
    c = client.get("/api/script-library").json()["current"][0]
    assert c["ep_progress"] == [0.5, 0.0] and c["ep_video_have"][0] == 0.5


def test_scene_type_slot_passthrough(client, tmp_path):
    o = _outline(1, False, [("sk_office_night", ["林晚"])])
    o["beats"][0]["scene_type"] = "约会"
    _w(tmp_path / "data" / "pipeline" / "runs" / RUN / "P2_ep01_outline.json", o)
    e1 = client.get(f"/api/script-library/{RUN}").json()["episodes"][0]
    assert e1["scenes"][0]["scene_type"] == "约会"


def test_poster_cover_preferred(tmp_path, monkeypatch):
    """海报 manifest.current 存在时，卡片封面读它（tools/poster）"""
    monkeypatch.setattr(SL, "REPO", tmp_path)
    _w(tmp_path / "data" / "posters" / RUN / "portrait_A_zh.jpg", "x")
    assert SL._poster_cover(RUN) is None
    _w(tmp_path / "data" / "posters" / RUN / "manifest.json", {"current": {"file": f"data/posters/{RUN}/portrait_A_zh.jpg"}})
    assert SL._poster_cover(RUN).startswith(f"/files/posters/{RUN}/portrait_A_zh.jpg")


def test_story_runs_list_carries_autoflow_brief(tmp_path, monkeypatch):
    """W-30：左侧列表要用的写作状态（verdict / P1G / 闸门 / 评审轮数上限）由 /api/story-runs 带出，前端和页头用同一个 p1Status"""
    from ns_api import story_runs as SR
    from ns_api import script_autoflow as SA
    monkeypatch.setattr(SR, "RUNS", tmp_path)
    d = tmp_path / "r1"
    _w(d / "P0_brief.json", {"title": "x"})
    _w(d / "autoflow.json", {"verdict": "awaiting_p1_judges"})
    monkeypatch.setattr(SA, "status", lambda rid: {"verdict": "p1_review_failed", "stages": [{"id": "P1G", "status": "x"}, {"id": "P2", "status": "y"}],
                                                   "owner_gates": {"enabled": True, "gates": {}}, "p1_review": {"latest": {"n": 3, "passed": False, "mean": 27.3, "top_fixes": ["别带"]},
                                                                                                               "threshold": {"max_rounds": 4}}})
    b = SR._autoflow_brief(d)
    assert b["verdict"] == "p1_review_failed" and [s["id"] for s in b["stages"]] == ["P1G"] and b["p1_review"]["threshold"]["max_rounds"] == 4
    assert "top_fixes" not in b["p1_review"]["latest"]
    assert SR._autoflow_brief(tmp_path / "none") is None


def test_run_title_survives_p1_revision_rename(tmp_path):
    """W-32：P1 返修期间正式 P1_storyline.json 被改名留档，剧名读最新一份 P1_storyline.v*.json；剧本库和 story-runs 同一个函数"""
    import os
    import time
    d = tmp_path / "r"
    _w(d / "P0_brief.json", {"title": ""})
    assert SL.run_title_of(d) == ""
    _w(d / "P1_storyline.v1.json", {"title": "旧名"})
    old = d / "P1_storyline.v1.json"
    os.utime(old, (time.time() - 100, time.time() - 100))
    _w(d / "P1_storyline.v2.json", {"title": "透明高跟"})
    assert SL.run_title_of(d) == "透明高跟"
    _w(d / "P1_storyline.json", {"title": "定稿名"})
    assert SL.run_title_of(d) == "定稿名"
    from ns_api import story_runs as SR
    assert SR._title_of(d) == "定稿名"


def test_archived_run_cannot_be_target_or_continue_source(tmp_path, monkeypatch):
    """W-37（完全切割 L-126）：已归档的剧不能作为写作目标，也不能出现在 registry_from（续写来源）里；story-runs 列表带 registry_status"""
    import pytest as _pt
    from fastapi import HTTPException
    from ns_api import script_autoflow as SA
    from ns_api import story_runs as SR
    monkeypatch.setattr(SA, "REPO", tmp_path)
    _w(tmp_path / "config" / "pipeline" / "runs.json", {"runs": {"old_v1": {"status": "archived"}, "cur": {"status": "producing"}}})
    with _pt.raises(HTTPException) as e1:
        SA._reject_archived("old_v1", None)
    assert e1.value.status_code == 409
    with _pt.raises(HTTPException) as e2:
        SA._reject_archived("new_run", {"registry_from": ["old_v1"]})
    assert e2.value.status_code == 409          # 和 script_autoflow 里 CLOSED 源剧检查统一用 409
    SA._reject_archived("cur", {"registry_from": ["cur"]})        # 没归档的不拦
    monkeypatch.setattr(SL, "REPO", tmp_path)
    assert SR._registry_status("old_v1") == "archived" and SR._registry_status("drill_x") is None
