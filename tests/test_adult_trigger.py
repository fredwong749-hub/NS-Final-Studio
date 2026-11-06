"""W-ADULT（L-128 不变项 + L-210）：成人镜“本人触发”入口。全部临时目录 + 合成夹具（剧本里没有任何画面描述），不连服务器、不出图。
  · POST /api/owner/adult-trigger 只认登录的项目方；没登录 / 查看令牌 / agent → 403，什么都不写
  · 先审计（data/pipeline/owner_adult_triggers.jsonl）再原子写 producer 读的 owner_triggers.json；只收成人镜
  · GET 只回文字（镜号 / 秒数 / 状态），不回图、不回画面描述、不回判定原因
  · producer：没触发的成人镜照旧不派；触发了的按普通镜算阶段 → 出图道是 gpu33 / gpu36 的道（不钉笔记本、永不含 gpu33:2）
  · 送到服务器的通道：resident_sync.control_files 含每部在产剧的触发清单；服务器端按对象合并后 objects = 笔记本的；merge_pull 不回拉
  · 网页：按钮只给项目方、只显示文字、一键确认"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/api", "tools/autopilot", "tools/factory", "ops/offline"):
    sys.path.insert(0, str(ROOT / p))
from ns_api import adult_trigger as AT  # noqa: E402
from ns_api import auth  # noqa: E402

RUN = "rx_adult"
SECRET = "SYNTH_SECRET_DESC"        # 夹具里的“画面描述 / 判定原因”占位：任何接口回包都不许出现
OWNER = {"name": "项目方", "role": "owner"}


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _shot(ep: int, i: int, adult: bool) -> dict:
    return {"episode": ep, "index": i, "duration": 5 + i, "adult": adult, "adult_reasons": [SECRET] if adult else [],
            "img_prompt": SECRET, "h3_prompt": SECRET}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    sc = {"episodes": [{"number": 1, "shots": [_shot(1, 1, False), _shot(1, 2, True)]},
                       {"number": 2, "shots": [_shot(2, 1, True), _shot(2, 2, True), _shot(2, 3, False)]}]}
    _w(tmp_path / "script.json", sc)
    pd = tmp_path / "data/producer/runs" / RUN
    reg = {"episodes": [{"ep": 2, "shots": [
        {"shot": "ep02-S1", "objects": {"first": {"status": "running"}, "last": {"status": "pending"}, "video": {"status": "pending"}}},
        {"shot": "ep02-S3", "objects": {"first": {"status": "failed", "last_error": "ep02-S3 未提交：成人画面资产（" + SECRET + "）"},
                                        "last": {"status": "pending"}, "video": {"status": "pending"}}}]}]}
    _w(pd / "registry.json", reg)
    monkeypatch.setattr(AT, "REPO", tmp_path)
    monkeypatch.setattr(AT, "known_runs", lambda root=None: [RUN])
    monkeypatch.setattr(AT, "producer_dir", lambda run, root=None: tmp_path / "data/producer/runs" / run)
    monkeypatch.setattr(AT, "script_path", lambda run, root=None: tmp_path / "script.json")
    pushed = []
    monkeypatch.setattr(AT, "push_now", lambda root=None: pushed.append(1))
    return {"root": tmp_path, "pd": pd, "pushed": pushed}


def _client(monkeypatch, user):
    app = FastAPI()
    app.include_router(AT.router)
    monkeypatch.setattr(auth, "user_of", lambda request: user)
    return TestClient(app)


def _trig(env) -> dict:
    return json.loads((env["pd"] / "owner_triggers.json").read_text(encoding="utf-8"))


def _audit(env) -> list[dict]:
    p = env["root"] / "data/pipeline/owner_adult_triggers.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ------------------------------------------------------------------ API
@pytest.mark.parametrize("user", [None, {"name": "查看者（截图检查）", "role": "viewer"}, {"name": "PRODUCER", "role": "agent"}])
def test_non_owner_rejected_and_nothing_written(env, monkeypatch, user):
    c = _client(monkeypatch, user)
    r = c.post("/api/owner/adult-trigger", json={"run": RUN, "episode": 2, "by": "owner"})
    assert r.status_code == 403
    assert not (env["pd"] / "owner_triggers.json").exists() and _audit(env) == [] and env["pushed"] == []
    assert c.get("/api/owner/adult-trigger").json()["can_trigger"] is False


def test_owner_episode_trigger_writes_audit_then_file(env, monkeypatch):
    c = _client(monkeypatch, OWNER)
    r = c.post("/api/owner/adult-trigger", json={"run": RUN, "episode": 2, "note": "今晚出"})
    assert r.status_code == 200, r.text
    objs = set(_trig(env)["objects"])
    assert objs == {f"{k}:ep02-{s}" for k in ("first", "last", "video") for s in ("S1", "S2", "S3")}   # S3 = 成人画面资产被拦的镜
    assert not any("ep01" in o or o.endswith("ep02-S4") for o in objs)
    a = _audit(env)
    assert len(a) == 1 and a[0]["by"] == "项目方" and a[0]["run"] == RUN and a[0]["note"] == "今晚出" and set(a[0]["objects"]) == objs
    assert _trig(env)["items"]["first:ep02-S1"]["by"] == "项目方"
    assert env["pushed"] == [1]
    assert not list(env["pd"].glob("*.tmp"))
    # 重复点：只记审计，不重写、不再推
    r2 = c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": ["ep02-S1"]})
    assert r2.status_code == 200 and r2.json()["added"] == [] and len(_audit(env)) == 2 and env["pushed"] == [1]


def test_per_shot_trigger_and_non_adult_refused(env, monkeypatch):
    c = _client(monkeypatch, OWNER)
    assert c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": ["ep01-S1"]}).status_code == 400      # 不是成人镜
    assert c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": ["first:ep01-S2", "x:ep01-S2"]}).status_code == 400
    assert c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": []}).status_code == 400
    assert c.post("/api/owner/adult-trigger", json={"run": "other", "objects": ["ep01-S2"]}).status_code == 404
    assert not (env["pd"] / "owner_triggers.json").exists() and _audit(env) == []
    r = c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": ["ep01-S2"]})
    assert r.status_code == 200 and set(_trig(env)["objects"]) == {"first:ep01-S2", "last:ep01-S2", "video:ep01-S2"}


def test_atomic_write_failure_keeps_old_file(env, monkeypatch):
    c = _client(monkeypatch, OWNER)
    c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": ["ep01-S2"]})
    before = (env["pd"] / "owner_triggers.json").read_bytes()

    def boom(a, b):
        raise OSError("disk full")
    monkeypatch.setattr(AT.os, "replace", boom)
    with pytest.raises(OSError):
        AT.apply(RUN, ["first:ep02-S2"], "项目方", "", env["root"])
    assert (env["pd"] / "owner_triggers.json").read_bytes() == before          # 旧文件原样
    assert not list(env["pd"].glob("*.tmp"))                                     # 临时文件清掉
    assert _audit(env)[-2]["objects"] == ["first:ep02-S2"] and _audit(env)[-2]["status"] == "requested"   # 审计先落盘
    assert _audit(env)[-1]["status"] == "write_failed" and "disk full" in _audit(env)[-1]["error"]         # 复审：失败标记


def test_get_lists_text_only_with_states(env, monkeypatch):
    c = _client(monkeypatch, OWNER)
    c.post("/api/owner/adult-trigger", json={"run": RUN, "objects": ["ep02-S1"]})
    r = c.get("/api/owner/adult-trigger", params={"run": RUN})
    assert r.status_code == 200 and SECRET not in r.text
    d = r.json()
    assert d["can_trigger"] is True
    rows = {s["shot"]: s for e in d["episodes"] for s in e["shots"]}
    assert set(rows) == {"ep01-S2", "ep02-S1", "ep02-S2", "ep02-S3"}
    assert rows["ep02-S1"]["state"] == "rendering" and rows["ep02-S2"]["state"] == "waiting" and rows["ep01-S2"]["seconds"] == 7
    for s in rows.values():
        assert set(s) == {"shot", "index", "seconds", "state", "state_word"}     # 只有文字字段：没有图 / 描述 / 原因
    assert AT.shot_state("ep09-S1", {"first:ep09-S1"}, {"first": {"status": "passed"}, "last": {"status": "best_effort"},
                                                        "video": {"status": "passed"}}) == "done"
    assert AT.shot_state("ep09-S1", {"first:ep09-S1"}, {}) == "triggered"


# ------------------------------------------------------------------ producer：未触发不派、触发后走服务器出图道
def test_producer_untriggered_skipped_triggered_dispatchable_on_server_lanes(tmp_path):
    import hosts as H
    import producer as P
    import lane_roles_producer as LRO
    trig = {"first:ep01-S2", "last:ep01-S2", "video:ep01-S2"}
    adult = {"ep01-S2"}
    o_first = {"id": "first:ep01-S2", "shot": "ep01-S2"}
    assert P.adult_blocked(o_first, adult, set()) is True                       # 没点 = 不派（L-128）
    assert P.adult_blocked(o_first, adult, trig) is False                       # 点了 = 进派单
    assert P.adult_blocked({"id": "first:ep01-S1", "shot": "ep01-S1"}, adult, set()) is False
    assert P.triggered_shots(trig | {"rx/first:ep03-S1", "video:ep05-S1", "junk"}) == {"ep01-S2", "ep03-S1"}
    p = P.Paths(root=tmp_path, run_id="rx_adult_p")
    p.pd.mkdir(parents=True)
    (p.pd / "owner_triggers.json").write_text("[1, 2]", encoding="utf-8")       # 格式坏 = 一个都不放
    assert P.owner_trigger_ids(p) == set()

    cfg = {"enabled": True, "from_episode": 1, "phases": {
        "frames": {"image": ["gpu33:0", "gpu33:1", "gpu33:2", "gpu36:0", "gpu36:1"], "review": ["gpu33:3"], "video": ["gpu36:2"]},
        "videos": {"image": [], "review": ["gpu33:3"], "video": ["gpu33:0", "gpu36:2"]}}}
    passed = {"status": "passed"}
    reg = {"episodes": [{"ep": 1, "shots": [
        {"shot": "ep01-S1", "objects": {"first": passed, "last": passed, "video": {"status": "pending"}}},
        {"shot": "ep01-S2", "objects": {"first": {"status": "ready"}, "last": {"status": "pending"}, "video": {"status": "pending"}}}]}]}
    # 没触发：成人镜不计 → 本集首尾帧段已完 → 没有出图道（成人镜也派不出去）
    ph0 = LRO.episode_phases(reg, cfg, adult - P.triggered_shots(set()))
    assert ph0[1] == "videos" and LRO.lanes_now(cfg, ph0, 1, "image") == []
    # 触发后：按普通镜算 → 回到首尾帧段 → 出图道 = gpu33 / gpu36（自有服务器），没有笔记本、没有坏卡 gpu33:2
    ph1 = LRO.episode_phases(reg, cfg, adult - P.triggered_shots(trig))
    lanes = LRO.lanes_now(cfg, ph1, 1, "image")
    assert ph1[1] == "frames" and lanes and "gpu33:2" not in lanes
    assert all(P.is_server_lane(ln) and H.owner_lane(ln) for ln in lanes)
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert "if adult_blocked(o, adult_shots, owner_triggers):" in src
    assert "adult_shot_ids(self.script()) - triggered_shots(owner_trigger_ids(self.p))" in src


def test_real_lane_roles_image_lanes_are_server_lanes():
    """L-210：现行 config/pipeline/lane_roles.json 首尾帧段的出图道全在 gpu33 / gpu36，且没有 gpu33:2"""
    import producer as P
    cfg = json.loads((ROOT / "config/pipeline/lane_roles.json").read_text(encoding="utf-8"))
    img = cfg["phases"]["frames"]["image"]
    assert img and "gpu33:2" not in img and all(P.is_server_lane(ln) for ln in img)


# ------------------------------------------------------------------ 送到服务器的通道
def test_control_files_include_owner_triggers(monkeypatch, tmp_path):
    import resident_sync as RS
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "RUN_ID", RUN)
    monkeypatch.setattr(RS, "log", lambda *a: None)
    monkeypatch.setattr(RS._RUNS, "list_runs", lambda status=None: [RUN])
    _w(tmp_path / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "series10_v1",
                                                "runs": {RUN: {"status": "producing"}, "series10_v1": {"status": "archived"}}})
    fs = RS.control_files()
    assert f"data/producer/runs/{RUN}/owner_triggers.json" in fs
    assert f"data/producer/runs/{RUN}/master_rejects.json" in fs           # 复审 11-07：V2 项目方“修改”也要推到服务器


def test_server_merge_takes_laptop_objects(tmp_path):
    """服务器上的 push_control 合并脚本：笔记本新清单的 objects 一定落到服务器那份（不按时间被旧值挡住）"""
    import resident_sync as RS
    rel = f"data/producer/runs/{RUN}/owner_triggers.json"
    _w(tmp_path / rel, {"objects": ["first:ep01-S2"], "items": {"first:ep01-S2": {"by": "项目方", "at": "2026-11-07T09:00:00"}},
                        "updated_at": "2026-11-07T09:00:00"})
    new = {"objects": ["first:ep01-S2", "first:ep02-S1"], "items": {"first:ep01-S2": {"by": "项目方", "at": "2026-11-07T09:00:00"},
                                                                    "first:ep02-S1": {"by": "项目方", "at": "2026-11-07T10:00:00"}},
           "updated_at": "2026-11-07T10:00:00"}
    _w(tmp_path / "new.json", new)
    (tmp_path / "merge.py").write_text(RS.REMOTE_MERGE.replace("__R__", tmp_path.as_posix()), encoding="utf-8")
    r = subprocess.run([sys.executable, str(tmp_path / "merge.py"), rel, str(tmp_path / "new.json")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / rel).read_text(encoding="utf-8"))["objects"] == new["objects"]


def test_merge_pull_never_pulls_triggers_back():
    import merge_pull as MP
    assert "owner_triggers.json" in MP.SKIP_NAMES


# ------------------------------------------------------------------ 网页
def _code(p: str) -> str:
    src = (ROOT / "apps/web/src" / p).read_text(encoding="utf-8")
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("//", "/*", "*")))


def test_ui_owner_only_text_only_one_click_confirm():
    ui = _code("v3/AdultTrigger.tsx")
    hp = _code("v3/AdultTrigger.helpers.ts")
    assert 'me?.role !== "owner"' in ui and "can_trigger" in ui
    assert "出这一集的成人镜" in ui and "出这一镜" in ui and "确认" in ui
    for bad in ("<img", "<video", "SafeImg", "thumb(", "prompt", "first_frame", "img_summary", "adult_reasons"):
        assert bad not in ui and bad not in hp, bad
    assert "/api/owner/adult-trigger" in hp and 'method: "POST"' in hp
    assert "AdultEpButton" in _code("v3/pages/SeasonPage.tsx") and "AdultQueuePanel" in _code("v3/pages/OwnerQueuePage.tsx")


def test_ui_no_tech_or_reject_words():
    from test_ui_no_tech_words_assetux import BANNED, TECH, visible_strings
    for f in ("v3/AdultTrigger.tsx", "v3/AdultTrigger.helpers.ts"):
        for s in visible_strings((ROOT / "apps/web/src" / f).read_text(encoding="utf-8")):
            assert not TECH.search(s) and not BANNED.search(s), f"{f}：{s}"
            assert not any(w in s for w in ("路由", "触发", "API", "接口")), f"{f}：{s}"


def test_api_messages_plain():
    import re
    src = (ROOT / "services/api/ns_api/adult_trigger.py").read_text(encoding="utf-8")
    from test_ui_no_tech_words_assetux import TECH
    for m in re.finditer(r"HTTPException\(\d+, \"([^\"]+)\"", src):
        assert not TECH.search(m.group(1)), m.group(1)
    for v in AT.STATE_WORD.values():
        assert not TECH.search(v)
    assert os.environ.get("NS_ADULT_TRIGGER_PUSH", "on") in ("on", "off", "0", "false", "")
