"""UIRSI 新建剧本接口：/api/story-runs（提纲 → 写作链 P0→P4）。

写作模型用假的 call_llm 代替（不联网、不花钱）；临时 runs 目录、临时草稿目录。验证：
提纲校验 422、逐段推进到 P3、没过校验 → needs_writer + 问题清单、返修后通过、改原文重新校验并把下游挪开（不删）、
P4 通过才能送导入且只存为草稿（导入仍要项目方确认）、同时只跑一个（409）、命令行旧 runs 能列出。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

STORYLINE = {"schema": "nsfs.storyline/1", "title": "T", "premise": "p", "world": {"setting": "s"},
             "characters": [{"name": "甲", "char_id": "ch_a", "role": "主角", "age": 22, "gender": "女", "zh_look": "系统锁",
                             "en_phrase": "a 22-year-old East Asian woman with long black hair",
                             "voice_phrase": "a bright young female voice, brisk pace"}],
             "scenes": [{"scene_id": "sk_room", "name": "房间", "space": "小房间", "time_of_day": "夜", "light": "台灯暖光",
                         "fixtures": "桌子、椅子"}],
             "episodes": [{"episode": 1, "title": "一", "owner_line": "原话", "logline": "原话展开", "characters": ["甲"],
                           "scenes": ["sk_room"]}]}
OUTLINE = {"schema": "nsfs.episode_outline/1", "episode": 1, "title": "一", "logline": "原话展开", "intimate": False,
           "target_duration_s": 60, "characters": ["甲"], "scenes": ["sk_room"],
           "beats": [{"id": "B1", "summary": "坐下", "scene_id": "sk_room", "characters": ["甲"], "est_s": 30, "purpose": "hook"},
                     {"id": "B2", "summary": "起身", "scene_id": "sk_room", "characters": ["甲"], "est_s": 30, "purpose": "payoff"}],
           "carry_out": "站着"}
SCREENPLAY = {"schema": "nsfs.screenplay/1", "episode": 1, "title": "一", "target_duration_s": 60, "scenes": [
    {"no": 1, "scene_id": "sk_room", "beat_ids": ["B1", "B2"], "characters": ["甲"],
     "lines": [{"kind": "action", "text": "她坐下"}, {"kind": "dialogue", "speaker": "甲", "text": "好。"}]}]}
BRIEF = {"title": "测试剧", "outline": "提纲原文", "episodes": {"from": 1, "to": 1}, "episode_lines": {"1": "原话"}}


class FakeWriter:
    """按连接返回固定稿件；bad 里的连接先返回坏稿（直到 fix）"""

    def __init__(self):
        self.calls: list[str] = []
        self.bad: set[str] = set()

    def __call__(self, system, user_msgs, *, max_tokens, reasoning, tag, budget, meta):
        link = meta["link"]
        self.calls.append(link)
        if link in self.bad:
            content = "{\"schema\": \"nsfs.episode_outline/1\"}"
        else:
            content = {"P0-P1": STORYLINE, "P1-P2": OUTLINE, "P2-P3": SCREENPLAY}.get(link, "## ep01《一》\n")
            content = json.dumps(content, ensure_ascii=False) if isinstance(content, dict) else content
        return {"content": content, "finish": "stop", "usage": {}, "usd": 0.0, "model": "fake"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    import run_chain as RC
    from ns_api import script_chat as SC
    from ns_api import script_inbox as SI
    from ns_api import story_runs as SR
    monkeypatch.setattr(SR, "RUNS", tmp_path / "data" / "pipeline" / "runs")
    monkeypatch.setattr(SI, "DATA", tmp_path / "data")
    monkeypatch.setattr(SI, "REPO", tmp_path)
    monkeypatch.setattr(SC, "registry_tables", lambda reg: ([], [], []))
    fw = FakeWriter()
    monkeypatch.setattr(RC, "call_llm", fw)
    monkeypatch.setattr(RC, "LEDGER", tmp_path / "ledger.jsonl")
    real_validate = RC.validate

    def validate(link, text, ctx):   # P4 用假校验（真校验要生产登记 + 导入器），其余段走真校验
        if link == "P3-P4":
            from ns_schema.upstream_common import Report
            rep = Report("P4")
            if "坏" in text:
                rep.add("QW-E2", "block", "镜数超了", "shots")
            rep.obj = text
            return rep, text, ""
        return real_validate(link, text, ctx)
    monkeypatch.setattr(RC, "validate", validate)
    SR.join_all()          # UIRSI r43：上一个测试（或别的测试文件）留下的写作线程先收完，再清表
    SR._threads.clear()
    app = FastAPI()
    app.include_router(SR.router)
    yield TestClient(app), SR, fw, tmp_path
    # 收尾：本测试起的线程全部结束后才撤 monkeypatch（env 先于 monkeypatch 收尾）——
    # 否则线程会在撤掉假写作网关后改调真网关、写到别的测试的临时目录，并行跑时偶发 error / running（根因，见 story_runs.wait）
    SR.join_all()
    SR._threads.clear()


def _start(c, SR, upto="P3"):
    r = c.post("/api/story-runs", json={"brief": BRIEF, "episode": 1, "upto": upto, "budget_usd": 1})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    SR.wait(rid)
    return rid


def test_bad_brief_422(env):
    c, SR, fw, _ = env
    r = c.post("/api/story-runs", json={"brief": {"outline": "  ", "episodes": {"from": 1, "to": 1}}, "episode": 1})
    assert r.status_code == 422
    assert any(i["rule"] == "BR-02" for i in r.json()["detail"]["issues"])
    r = c.post("/api/story-runs", json={"brief": BRIEF, "episode": 5})
    assert r.status_code == 422
    assert not fw.calls


def test_runs_to_p3_stage_by_stage(env):
    c, SR, fw, tmp = env
    rid = _start(c, SR)
    d = c.get(f"/api/story-runs/{rid}").json()
    assert d["status"] == "ok", d.get("error")
    st = {s["node"]: s["status"] for s in d["stages"]}
    assert st == {"P0": "ok", "P1": "ok", "P2": "ok", "P3": "ok", "P4": "pending"}
    assert fw.calls == ["P0-P1", "P1-P2", "P2-P3"]          # 逐段推进，已过的段复用、不重复调用
    a = c.get(f"/api/story-runs/{rid}/artifact/P1").json()
    assert a["kind"] == "json" and a["json"]["characters"][0]["name"] == "甲"
    assert c.get("/api/story-runs").json()["runs"][0]["id"] == rid


def test_needs_writer_then_retry(env):
    c, SR, fw, _ = env
    fw.bad.add("P1-P2")
    rid = _start(c, SR)
    d = c.get(f"/api/story-runs/{rid}").json()
    assert d["status"] == "needs_writer"
    p2 = next(s for s in d["stages"] if s["node"] == "P2")
    assert p2["status"] == "needs_writer" and p2["blocking"] > 0 and p2["issues"][0]["level"] == "block"
    assert p2["rounds"] == 3                                 # 首写 + 2 轮带错误重写
    assert next(s for s in d["stages"] if s["node"] == "P3")["status"] == "pending"
    fw.bad.clear()
    r = c.post(f"/api/story-runs/{rid}/retry", json={})
    assert r.status_code == 200
    SR.wait(rid)
    d = c.get(f"/api/story-runs/{rid}").json()
    assert d["status"] == "ok" and all(s["status"] == "ok" for s in d["stages"][:4]), d.get("error")
    sup = list((SR.RUNS / rid / "superseded").rglob("P2_ep01_outline.json*"))
    assert sup, "返修前的产物挪到 superseded/，不删"


def test_edit_revalidates_and_supersedes_downstream(env):
    c, SR, fw, _ = env
    rid = _start(c, SR)
    bad = dict(OUTLINE, beats=[dict(OUTLINE["beats"][0], est_s=5)])
    r = c.put(f"/api/story-runs/{rid}/artifact/P2", json={"text": json.dumps(bad, ensure_ascii=False)})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "needs_writer" and j["report"]["blocking"] > 0
    assert "P3_ep01_screenplay.json" in j["superseded"]
    assert (SR.RUNS / rid / "edits").is_dir()                # 旧版留底
    r = c.put(f"/api/story-runs/{rid}/artifact/P2", json={"text": json.dumps(OUTLINE, ensure_ascii=False)})
    assert r.json()["status"] == "ok"
    n = len(fw.calls)
    r = c.post(f"/api/story-runs/{rid}/resume", json={})
    assert r.status_code == 200, r.text
    SR.wait(rid)
    d = c.get(f"/api/story-runs/{rid}").json()
    assert fw.calls[n:] == ["P2-P3"], (d.get("status"), d.get("error"), [(x["node"], x["status"]) for x in d["stages"]])   # 改过的 P2 被复用，只重写下游
    assert c.put(f"/api/story-runs/{rid}/artifact/P0", json={"text": "x"}).status_code == 422


def test_send_to_import_only_when_p4_ok(env):
    c, SR, fw, tmp = env
    rid = _start(c, SR, upto="P4")
    d = c.get(f"/api/story-runs/{rid}").json()
    assert d["status"] == "ok"
    r = c.post(f"/api/story-runs/{rid}/send-to-import")
    assert r.status_code == 200, r.text
    draft = tmp / "data" / "staging_input" / f"story_{rid}.md"
    assert "## ep01《一》" in draft.read_text(encoding="utf-8")   # 原样（带写稿规则版本章）
    assert r.json()["import_href"] == "#/script-create?tab=import"
    assert not (tmp / "data" / "import").exists()            # 没有导入，只是候选
    c.put(f"/api/story-runs/{rid}/artifact/P4", json={"text": "## ep01《一》坏\n"})
    assert c.post(f"/api/story-runs/{rid}/send-to-import").status_code == 409


def test_one_at_a_time(env, monkeypatch):
    import threading

    c, SR, fw, _ = env
    gate = threading.Event()
    orig = fw.__call__

    def slow(*a, **k):
        gate.wait(5)
        return orig(*a, **k)
    import run_chain as RC
    monkeypatch.setattr(RC, "call_llm", slow)
    r = c.post("/api/story-runs", json={"brief": BRIEF, "episode": 1, "upto": "P1"})
    assert r.status_code == 200
    r2 = c.post("/api/story-runs", json={"brief": BRIEF, "episode": 1, "upto": "P1"})
    assert r2.status_code == 409
    d = c.get(f"/api/story-runs/{r.json()['id']}").json()
    assert d["status"] == "running" and d["stages"][1]["status"] == "running"
    gate.set()
    SR.wait(r.json()["id"])


def test_lists_cli_runs_readonly(env):
    c, SR, fw, _ = env
    d = SR.RUNS / "ep02_cli"
    d.mkdir(parents=True)
    (d / "P0_brief.json").write_text(json.dumps({"schema": "nsfs.brief/1", "title": "旧", "outline": "x",
                                                 "episodes": {"from": 2, "to": 2}}), encoding="utf-8")
    (d / "P2_ep02_outline.json").write_text("{}", encoding="utf-8")
    runs = c.get("/api/story-runs").json()["runs"]
    row = next(r for r in runs if r["id"] == "ep02_cli")
    assert row["episode"] == 2 and not row["ui"]
    assert {s["node"]: s["status"] for s in row["stages"]}["P2"] == "unchecked"


def test_series_layout_readonly_per_episode(env):
    """整季运行（SERIES：根目录 P0/P1，epNN/ 里 P2–P4）：按集看、只读、按集送导入"""
    c, SR, fw, tmp = env
    d = SR.RUNS / "series_t"
    (d / "ep01").mkdir(parents=True)
    (d / "ep02").mkdir()
    (d / "P0_brief.json").write_text(json.dumps({"schema": "nsfs.brief/1", "title": "季", "outline": "x",
                                                 "episodes": {"from": 1, "to": 2}}), encoding="utf-8")
    (d / "P1_storyline.json").write_text(json.dumps(STORYLINE, ensure_ascii=False), encoding="utf-8")
    (d / "ep01" / "P4_ep01.md").write_text("## ep01《一》\n", encoding="utf-8")
    (d / "ep01" / "P4_ep01.md.report.json").write_text(json.dumps({"status": "ok", "report": {"ok": True}}), encoding="utf-8")
    (d / "ep02" / "P4_ep02.md.report.json").write_text(json.dumps({"status": "needs_writer", "report": {"blocking": 2}}), encoding="utf-8")
    j = c.get("/api/story-runs/series_t?ep=2").json()
    assert j["series"] and j["readonly"] and j["episode"] == 2 and j["status"] == "needs_writer"
    assert [x["stages"]["P4"] for x in j["series_eps"]] == ["ok", "needs_writer"]
    assert c.get("/api/story-runs/series_t/artifact/P4?ep=1").json()["text"].startswith("## ep01")
    assert c.post("/api/story-runs/series_t/retry", json={}).status_code == 409
    assert c.post("/api/story-runs/series_t/send-to-import?ep=2").status_code == 409
    r = c.post("/api/story-runs/series_t/send-to-import?ep=1")
    assert r.status_code == 200 and (tmp / "data" / "staging_input" / "story_series_t_ep01.md").exists()
    assert c.get("/api/story-runs/series_t?ep=1").json()["sent_to_import"]["path"].endswith("story_series_t_ep01.md")


def test_story_images_grouped(env):
    """IMGGEN 的新图（runs/<id>/images/）：按镜头号和人物归组，给画布 / 资产中心先显示"""
    c, SR, fw, tmp = env
    img = SR.RUNS / "series_img" / "images"
    for rel in ("ep01/S3_first.png", "ep01/S3_last.png", "ep02/ep02_S10_ff.webp", "chars/a_lan/a_lan_sheet.png", "sheets/ch_b/ch_b_lookC_s202.png", "readme.txt"):
        f = img / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    import ns_api.story_runs as M
    old = M.REPO
    M.REPO = tmp
    try:
        j = c.get("/api/story-images").json()
    finally:
        M.REPO = old
    assert j["run"] == "series_img" and j["count"] == 5 and "ch_b" in j["chars"]
    assert {x["kind"] for x in j["by_shot"]["ep01-S3"]} == {"first", "last"}
    assert j["by_shot"]["ep02-S10"][0]["kind"] == "first"
    assert j["chars"]["a_lan"][0]["kind"] == "sheet"
    assert j["by_shot"]["ep01-S3"][0]["url"].startswith("/files/pipeline/runs/series_img/images/")


def test_sheet_pick_owner_gate_and_thumbs(env):
    """挑设定图：项目方闸门（缺原话 403）；只记 ui_sheet_picks.json；缩略图 / 造型 / 种子解析；_thumbs 不单独算"""
    c, SR, fw, tmp = env
    img = SR.RUNS / "series_pick" / "images"
    for rel in ("sheets/ch_a/ch_a_lookA_s101.png", "sheets/ch_a/ch_a_lookA_s202.png", "_thumbs/ch_a_lookA_s101.jpg"):
        f = img / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    import ns_api.story_runs as M
    old = M.REPO
    M.REPO = tmp
    try:
        j = c.get("/api/story-images").json()
        assert j["count"] == 2
        a = j["chars"]["ch_a"]
        assert [x["seed"] for x in a] == [101, 202] and a[0]["look"] == "A" and a[0]["thumb"].endswith(".jpg?v=" + a[0]["thumb"].split("=")[-1])
        body = {"run": "series_pick", "char": "ch_a", "path": "sheets/ch_a/ch_a_lookA_s202.png"}
        assert c.post("/api/story-images/pick", json=body).status_code == 403                       # 不是项目方
        assert c.post("/api/story-images/pick", json={**body, "by": "unauthenticated"}).status_code == 403
        r = c.post("/api/story-images/pick", json={**body, "by": "owner"})                           # 点选即生效，不要原话
        assert r.status_code == 200 and r.json()["look"] == "A"
        assert c.get("/api/story-images").json()["picks"]["ch_a"]["A"]["path"].endswith("s202.png")
        assert c.post("/api/story-images/pick", json={"run": "series_pick", "char": "ch_a", "path": "", "look": "A", "by": "owner"}).status_code == 200
        assert "A" not in c.get("/api/story-images").json()["picks"].get("ch_a", {})                  # 撤销
        assert c.post("/api/story-images/pick", json={**body, "path": "../../x.png", "by": "owner", "owner_quote": "x"}).status_code == 404
    finally:
        M.REPO = old
