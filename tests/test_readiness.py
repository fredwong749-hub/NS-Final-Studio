"""就绪闸门 + 一条链显示（docs/audit/shot_readiness_and_continuity.md §4）。
全部在临时 data 目录里：假的 renders_gpu3 树（gpu3 链有 / 无 / status.json blocked）、假的笔记本 takes；
不调用桥（post_rerender 被替换），/render 只验证 gpu3 负责时在入队前就被 409 拒绝。"""
import calendar
import json
import os
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_agent.looks import DEFAULT_SCRIPT_JSON
from ns_api import app as app_mod
from ns_api import readiness as RD
from ns_render import pipeline as P
from ns_schema.script import ScriptImport

pytestmark = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(scope="module")
def script() -> ScriptImport:
    return ScriptImport.model_validate_json(Path(DEFAULT_SCRIPT_JSON).read_text(encoding="utf-8"))


def _v3(script: ScriptImport) -> ScriptImport:
    """ep01 补齐 v3 字段（sound_h3 / 亲密声 / 配乐 / BGM / 时长），其它集保持原样"""
    sc = script.model_copy(deep=True)
    ep = sc.episodes[0]
    ep.music_bgm = "Sparse piano, slow tempo, soft dynamics."
    for s in ep.shots:
        s.sound = s.sound or "环境声"
        s.sound_h3 = "Quiet office lobby room tone, soft footsteps."
        s.sound_intimate = "soft breathing"
        s.music_cue = "进入，强度1"
        s.duration, s.duration_source = 8, "script"
    return sc


@pytest.fixture()
def env(tmp_path, script, monkeypatch):
    data = tmp_path / "data"
    (data / "renders").mkdir(parents=True)
    g3 = data / "renders_gpu3"
    g3.mkdir()
    own = tmp_path / "shot_ownership.json"
    own.write_text(json.dumps({"projects": {"weita": {"owner": "gpu3"}}}), encoding="utf-8")
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(RD, "GPU3_ROOT", g3)
    monkeypatch.setattr(RD, "OWNERSHIP_FILE", own)
    monkeypatch.setattr(app_mod, "_script", _v3(script))
    yield TestClient(app_mod.app), data, own


def gpu3_shot(data: Path, shot: str, *, image=True, last=True, video=False, status: dict | None = None,
              mirror_image=True, video_before_image=False):
    ep, sn = shot.split("-")
    d = data / "renders_gpu3" / ep / sn
    (d / "takes").mkdir(parents=True, exist_ok=True)
    takes, active = [], {}
    if image:
        f = f"renders_gpu3/{ep}/{sn}/takes/image_001.png"
        if mirror_image:
            (data / f).write_bytes(PNG)
        takes.append({"stage": "image", "n": 1, "file": f, "created_at": "2026-10-29T02:00:00Z"})
        active["image"] = 1
    if video:
        f = f"renders_gpu3/{ep}/{sn}/takes/video_001.mp4"
        (data / f).write_bytes(b"mp4")
        (data / f.replace(".mp4", "_last.png")).write_bytes(PNG)
        takes.append({"stage": "video", "n": 1, "file": f, "last_frame": f.replace(".mp4", "_last.png"),
                      "created_at": "2026-10-29T01:00:00Z" if video_before_image else "2026-10-29T03:00:00Z"})
        active["video"] = 1
    if last:
        (d / "last.png").write_bytes(PNG)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")
    if status is not None:
        (d / "status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")


def laptop_shot(data: Path, shot: str):
    ep, sn = shot.split("-")
    d = data / "renders" / ep / sn
    (d / "takes").mkdir(parents=True, exist_ok=True)
    f = f"renders/{ep}/{sn}/takes/image_001.png"
    (data / f).write_bytes(PNG)
    (d / "takes.json").write_text(json.dumps({"takes": [
        {"stage": "image", "n": 1, "file": f, "prompt": "x", "created_at": "2026-10-29T10:00:00"}],
        "active": {"image": 1}}), encoding="utf-8")


def ep1(c) -> dict:
    return next(e for e in c.get("/api/episodes").json() if e["number"] == 1)


def item(s: dict, key: str) -> dict:
    return next(i for i in s["readiness"]["items"] if i["key"] == key)


def test_gpu3_chain_shown_laptop_only_history(env):
    c, data, _ = env
    gpu3_shot(data, "ep01-S1", video=True, status={"status": "ok", "owner": "gpu3"})
    laptop_shot(data, "ep01-S1")
    s = ep1(c)["shots"][0]
    assert s["owner"] == "gpu3" and s["frames_source"] == "gpu3"
    assert s["first_frame"].startswith("/files/renders_gpu3/ep01/S1/takes/image_001.png")
    assert s["last_frame_target"].startswith("/files/renders_gpu3/ep01/S1/last.png")
    assert s["video"].startswith("/files/renders_gpu3/ep01/S1/takes/video_001.mp4")
    assert s["last_frame_source"] == "gpu3"
    # 笔记本帧只作历史，不和 gpu3 视频混在同一行
    assert s["laptop_history"]["first"].startswith("/files/renders/ep01/S1/")
    assert s["laptop_history"]["note"] == "笔记本旧版本，未用于视频"
    assert s["stale"] == {} and s["latest_take"]["image"] is None
    assert item(s, "first")["ok"] and item(s, "last")["ok"]
    assert item(s, "continuity")["ok"]                    # 本集第一镜
    assert s["readiness"]["ready"] is True, s["readiness"]["blocked_reasons"]


def test_gpu3_owned_without_chain_is_empty_not_laptop(env):
    c, data, _ = env
    laptop_shot(data, "ep01-S2")
    s = ep1(c)["shots"][1]
    assert s["owner"] == "gpu3" and s["frames_source"] == "none"
    assert s["first_frame"] is None and s["video"] is None      # 不拿笔记本帧顶替
    assert s["laptop_history"]["first"]
    f = item(s, "first")
    assert not f["ok"] and f["level"] == "fail" and "gpu3 还没出首帧" in f["reason"]
    assert not s["readiness"]["ready"]


def test_laptop_project_uses_laptop_chain(env):
    c, data, own = env
    own.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    laptop_shot(data, "ep01-S1")
    shots = ep1(c)["shots"]
    assert shots[0]["owner"] == "laptop" and shots[0]["frames_source"] == "laptop"
    assert shots[0]["first_frame"].startswith("/files/renders/ep01/S1/")
    assert shots[0]["laptop_history"] is None
    assert not item(shots[0], "last")["ok"]
    assert shots[1]["frames_source"] == "none"
    # 镜头级 status.json owner=gpu3 → 这一镜归 gpu3
    gpu3_shot(data, "ep01-S3", status={"owner": "gpu3", "status": "ok"})
    s3 = ep1(c)["shots"][2]
    assert s3["owner"] == "gpu3" and s3["frames_source"] == "gpu3"
    # 笔记本项目里有 gpu3 链的镜头也显示 gpu3 链
    gpu3_shot(data, "ep01-S4")
    assert ep1(c)["shots"][3]["frames_source"] == "gpu3"


def test_blocked_status_and_continuity(env):
    c, data, _ = env
    gpu3_shot(data, "ep01-S1", status={"status": "ok"})
    gpu3_shot(data, "ep01-S2", status={"status": "blocked", "blocked_reasons": ["H3 声音提示词缺失"],
                                       "continuity": {"verdict": "fail", "reasons": ["服装颜色不同"]}})
    gpu3_shot(data, "ep01-S3", status={"status": "ok", "continuity": {"verdict": "pass"}})
    gpu3_shot(data, "ep01-S4", status={"status": "ok"})
    e = ep1(c)
    s1, s2, s3, s4 = e["shots"][:4]
    assert not s2["readiness"]["ready"]
    assert "gpu3：H3 声音提示词缺失" in s2["readiness"]["blocked_reasons"]
    cont = item(s2, "continuity")
    assert cont["level"] == "fail" and "服装颜色不同" in cont["reason"] and "ep01-S1" in cont["reason"]
    assert item(s3, "continuity")["ok"] and s3["readiness"]["ready"]
    u = item(s4, "continuity")
    assert not u["ok"] and u["level"] == "warn" and u["reason"].startswith("未检查")
    assert e["readiness"]["ready"] == 2 and e["readiness"]["total"] == len(e["shots"])
    r = c.get("/api/readiness", params={"ep": 1}).json()
    assert r[0]["ready"] == 2 and r[0]["shots"][1]["readiness"]["gpu3_status"] == "blocked"


def test_warn_levels_and_missing_reasons(env, script, monkeypatch):
    c, data, _ = env
    sc = _v3(script)
    s = sc.episodes[0].shots[0]
    s.duration_source, s.sound_h3, s.music_cue = "default", "", ""
    sc.episodes[0].music_bgm = ""
    monkeypatch.setattr(app_mod, "_script", sc)
    gpu3_shot(data, "ep01-S1", mirror_image=False, video=True, video_before_image=True)
    row = ep1(c)["shots"][0]
    d = item(row, "duration")
    assert d["ok"] and d["level"] == "warn" and "默认" in d["reason"]
    assert item(row, "sound")["level"] == "fail" and "H3" in item(row, "sound")["reason"]
    assert not item(row, "music_cue")["ok"] and not item(row, "bgm")["ok"]
    # 镜像缺首帧文件 → 经桥代理读取，黄色提醒
    f = item(row, "first")
    assert f["ok"] and f["level"] == "warn" and row["first_frame"] == "/api/gpu3-media/renders_gpu3/ep01/S1/takes/image_001.png"
    # 视频早于当前首帧 → 视频用的不是这张首帧
    assert item(row, "chain")["level"] == "fail"


def test_episode_continuity_sheet(env):
    c, data, _ = env
    (data / "renders_gpu3" / "ep01").mkdir(parents=True, exist_ok=True)
    (data / "renders_gpu3" / "ep01" / "continuity_sheet.jpg").write_bytes(b"jpg")
    assert ep1(c)["readiness"]["continuity_sheet"].startswith("/files/renders_gpu3/ep01/continuity_sheet.jpg")


def test_laptop_render_refused_when_gpu3_owns(env):
    c, data, _ = env
    n_jobs = len(app_mod._jobs)
    r = c.post("/api/shots/ep01-S1/render", json={"stage": "image"})
    assert r.status_code == 409 and "gpu3 负责此镜" in r.json()["detail"]
    assert len(app_mod._jobs) == n_jobs                     # 没有入队


def test_gpu3_rerender_request(env, monkeypatch):
    c, _, _ = env
    sent = []
    monkeypatch.setattr(RD, "post_rerender", lambda req: (sent.append(req), {"requests": [{"id": "x"}], "errors": []})[1])
    r = c.post("/api/shots/ep01-S2/gpu3-rerender", json={"stage": "last"})
    assert r.status_code == 200, r.text
    q = sent[0]
    assert q["schema"] == "nsfs_canvas.rerender/v1" and q["shot"] == "ep01-S2" and q["project"] == "weita"
    assert q["stage"] == "image" and q["overrides"] == {"last_only": True}
    assert c.post("/api/shots/ep01-S2/gpu3-rerender", json={"stage": "nope"}).status_code == 400

    def down(req):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(RD, "post_rerender", down)
    assert c.post("/api/shots/ep01-S2/gpu3-rerender", json={"stage": "video"}).status_code == 502


def test_gpu3_media_proxy_rejects_outside(env):
    c, data, _ = env
    assert c.get("/api/gpu3-media/renders/ep01/S1/x.png").status_code == 400
    gpu3_shot(data, "ep01-S1")
    r = c.get("/api/gpu3-media/renders_gpu3/ep01/S1/last.png")      # 镜像里有 → 直接返回本地文件
    assert r.status_code == 200 and r.content == PNG


def test_last_frame_older_than_first_is_different_chain(env):
    """尾帧 last.png 早于当前首帧 take = 不是由这张首帧编辑得到（ep01 S3/S5 的真实情况）"""
    c, data, _ = env
    gpu3_shot(data, "ep01-S1")
    old = calendar.timegm((2026, 10, 28, 12, 0, 0, 0, 0, 0))
    os.utime(data / "renders_gpu3" / "ep01" / "S1" / "last.png", (old, old))
    last = item(ep1(c)["shots"][0], "last")
    assert not last["ok"] and last["level"] == "fail" and "不同链" in last["reason"]
