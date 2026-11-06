"""UIUX-LOOP-3 第 12 轮（11-06）：项目方看不到最新成片。
① /api/episodes/{n}/cuts 写死 data/episodes/ → V2（data/episodes/series10_v2/）的 66 版成片一版都列不出来（成片页“第 1 集还没有成片”）；
   /api/episodes/{n}/preview 的地址写死 renders/epNN/_final → 放的是 V1 的旧预览。按剧取目录（run_paths.episodes_dir，K-OPS-F24 同口径）。
② 合成闸门结论（timeline.json gates.verdict / missing_shots）要写在版本上：闸门没过 = 预览版（缺镜用静帧 / 黑场占位），不冒充成片。
③ KPI 面板每集带 film（最新一版 + 闸门一句话）；连播本集（/preview）优先给比巡检预览新的最新成片，并带 film 字段。
④ 成片页钟点改 JST（以前 time.localtime = 笔记本美东）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "services/render", "services/post", "services/render_router", "tools/autopilot"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_render import pipeline as P  # noqa: E402


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _tl(shots_kinds, *, verdict, missing=(), preview=True, post=False, duration=70.0):
    shots = []
    t = 0.0
    for i, k in enumerate(shots_kinds, start=1):
        shots.append({"shot": f"ep01-S{i}", "index": i, "kind": k, "placeholder": k != "video", "missing": k != "video",
                      "start_s": t, "duration_s": 5.0, "file": f"data/x/S{i}.mp4" if k == "video" else None})
        t += 5.0
    tl = {"episode": "ep01", "preview": preview, "duration_s": duration, "shots": shots,
          "gates": {"verdict": verdict, "missing_shots": [{"shot": m, "reason": "没有视频版本"} for m in missing], "overflow": []}}
    if post:
        tl["post"] = {"by": "DIRECTOR post_pass", "at": "2026-11-06 16:56:49", "steps": ["grade", "sfx", "loudnorm"]}
    return tl


def test_film_gate_words():
    from ns_api import cuts as C
    g = C.film_gate(_tl(["video", "black"], verdict="fail", missing=["S2"], post=True))
    assert g["kind"] == "preview" and g["kind_word"] == "预览版" and g["word"] == "合成闸门没过：缺 1 镜用占位"
    assert g["missing"] == [{"shot": "S2", "reason": "没有视频版本"}] and g["post"]["steps"] == ["grade", "sfx", "loudnorm"]
    g2 = C.film_gate(_tl(["video"], verdict="pass", preview=False))
    assert g2["kind"] == "final" and g2["kind_word"] == "成片" and g2["word"] == "合成闸门通过"
    # 装配器标 preview 的，哪怕闸门过了也还是预览版
    assert C.film_gate(_tl(["video"], verdict="pass", preview=True))["kind"] == "preview"
    assert C.film_gate(None) is None
    assert C.film_gate({"shots": []})["word"] == "没有闸门记录"


def test_episodes_dir_by_run(tmp_path):
    """V2 剧 = data/episodes/<run>/；legacy 剧 = data/episodes/；沙箱 data → <data>/episodes（旧行为）"""
    from ns_api import run_paths as RP
    (tmp_path / "config/pipeline").mkdir(parents=True)
    _w(tmp_path / "config/pipeline/runs.json", {"primary": "s_v2", "legacy_unprefixed_run": "s_v1",
                                                 "runs": {"s_v1": {"priority": 0, "status": "archived"}, "s_v2": {"priority": 1, "status": "producing"}}})
    assert RP.episodes_dir(tmp_path) == tmp_path / "data" / "episodes" / "s_v2"
    assert RP.episodes_dir(tmp_path, "s_v1") == tmp_path / "data" / "episodes"
    assert RP.episodes_for_data(tmp_path / "data") == tmp_path / "data" / "episodes"
    # 真实仓库：当前剧不是 legacy → 带前缀
    real = RP.episodes_dir()
    assert real.parent == ROOT / "data" / "episodes" or real == ROOT / "data" / "episodes"


@pytest.fixture
def box(tmp_path, monkeypatch):
    from ns_api import cuts as C
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    C.JOBS.clear()
    C._TL_CACHE.clear()
    ep = tmp_path / "data" / "episodes"
    _w(ep / "ep01_v63_post.mp4", "a")
    _w(ep / "ep01_v63_post.timeline.json", _tl(["video", "black", "video"], verdict="fail", missing=["S2"], post=True))
    _w(ep / "ep01_v9.mp4", "b")
    _w(ep / "ep01_v9.timeline.json", _tl(["video", "video", "video"], verdict="pass", preview=False))
    _w(ep / "_work" / "ep01_PREVIEW_未完成_v64.mp4", "半成品不算")
    _w(ep / "ep010_v1.mp4", "别的集")
    now = time.time()
    os.utime(ep / "ep01_v9.mp4", (now - 600, now - 600))
    os.utime(ep / "ep01_v63_post.mp4", (now - 60, now - 60))
    return tmp_path


def test_latest_film_and_cuts_list(box):
    from ns_api import cuts as C
    ep = box / "data" / "episodes"
    # r14：闸门通过的 v9 排在预览版 v63_post 前面（哪怕 v63_post 的 mtime 更新）
    f = C.latest_film(ep, 1)
    assert f["name"] == "ep01_v9.mp4" and f["version"] == 9 and f["url"].startswith("/files/episodes/ep01_v9.mp4?v=")
    assert f["video_shots"] == 3 and f["placeholder_shots"] == 0 and f["gate"]["kind"] == "final"
    assert len(f["at"]) == 19 and "T" in f["at"]
    assert C.latest_film(ep, 2) is None and C.latest_film(box / "nope", 1) is None
    app = FastAPI()
    app.include_router(C.router)
    c = TestClient(app)
    r = c.get("/api/episodes/1/cuts").json()
    names = [x["name"] for x in r["cuts"]]
    assert names == ["ep01_v9.mp4", "ep01_v63_post.mp4"], names   # 闸门通过的在前；_work / ep010 不算
    b, a = r["cuts"]
    assert a["gate"]["kind"] == "preview" and "预览" in a["tags"] and a["gate"]["word"] == "合成闸门没过：缺 1 镜用占位"
    assert b["gate"]["kind"] == "final" and "预览" not in b["tags"] and b["gate"]["verdict"] == "pass"
    # 钟点 JST：和文件 mtime 按 +09:00 算出来的一致
    from datetime import datetime
    from ns_api.clock import JST
    assert a["mtime"] == datetime.fromtimestamp((ep / "ep01_v63_post.mp4").stat().st_mtime, JST).strftime("%Y-%m-%dT%H:%M:%S")


def test_preview_prefers_newer_film_and_fixes_url(box):
    from ns_api import cuts as C
    from ns_api import ep_preview as EP
    app = FastAPI()
    app.include_router(EP.router)
    c = TestClient(app)
    # 没有巡检预览 → 给最新成片
    d = c.get("/api/episodes/1/preview").json()
    assert d["source"] == "film" and d["film"]["name"] == "ep01_v9.mp4" and d["film"]["kind_word"] == "成片"   # r14：闸门通过的优先
    assert d["url"].startswith("/files/episodes/ep01_v9.mp4") and d["stale"] is False
    assert [s["kind"] for s in d["shots"]] == ["video", "video", "video"] and d["placeholder_shots"] == 0
    assert d["shots"][1]["start_s"] == 5.0 and d["duration_s"] == 70.0
    # 预览版的映射：占位镜灰
    pvw = EP._film_view(C.latest_film(box / "data" / "episodes", 1) | {"url": "x", "at": "t", "mtime": 1.0, "name": "ep01_v63_post.mp4"},
                        C._tl(box / "data" / "episodes" / "ep01_v63_post.mp4"))
    assert [s["kind"] for s in pvw["shots"]] == ["video", "placeholder", "video"] and pvw["placeholder_shots"] == 1
    # 巡检预览更新 → 给预览，但地址按文件真实位置（renders/…/_final），不写死 renders/epNN
    fin = box / "data" / "renders" / "ep01" / "_final"
    _w(fin / "preview_latest.mp4", "p")
    _w(fin / "preview_latest_manifest.json", {"built_at_iso": "2026-11-06T20:00:00", "built_at": time.time(), "duration_s": 10.0,
                                              "video_shots": 0, "placeholder_shots": 2, "shots": [{"shot": "ep01-S1", "index": 1, "kind": "placeholder"}]})
    d2 = c.get("/api/episodes/1/preview").json()
    assert d2["source"] == "preview" and d2["film"] is None and d2["url"].startswith("/files/renders/ep01/_final/preview_latest.mp4?v=")
    # 成片又更新 → 回到成片
    now = time.time() + 5
    os.utime(box / "data" / "episodes" / "ep01_v9.mp4", (now, now))
    assert c.get("/api/episodes/1/preview").json()["source"] == "film"
    # 第 2 集什么都没有 → 404（口径不变）
    assert c.get("/api/episodes/2/preview").status_code == 404
    C._TL_CACHE.clear()


def test_kpi_carries_latest_film(tmp_path):
    from ns_api import episode_kpi as K
    reg = {"run": "r", "episodes": [{"ep": 1, "title": "一", "shots": [{"shot": "ep01-S1", "index": 1, "objects": {"first": {"status": "passed"}}}]},
                                    {"ep": 2, "title": "二", "shots": [{"shot": "ep02-S1", "index": 1, "objects": {}}]}]}
    film = {"name": "ep01_v63_post.mp4", "version": 63, "url": "/files/episodes/r/ep01_v63_post.mp4?v=1", "at": "2026-11-06T19:24:30",
            "mtime": 1.0, "size": 1, "duration_s": 73.7, "shots": 16, "video_shots": 11, "placeholder_shots": 5,
            "gate": {"verdict": "fail", "missing": [{"shot": "S4", "reason": "x"}], "missing_n": 1, "preview": True, "kind": "preview",
                     "kind_word": "预览版", "word": "合成闸门没过：缺 1 镜用占位", "post": {"at": "t", "steps": ["grade"]}, "overflow": []}}
    out = K.build(registry=reg, renders=tmp_path, snapshot=None, local_starts={"1": 1_800_000_000.0 - 60}, now=1_800_000_000.0,
                  url=lambda r: r, vurl=lambda r: r, film_of=lambda ep: film if ep == 1 else None)
    e1, e2 = out["episodes"]
    assert e1["film"]["version"] == 63 and e1["film"]["kind_word"] == "预览版" and e1["film"]["missing"] == ["S4"] and e1["film"]["post"] is True
    assert e2["film"] is None
    # 没给 film_of（旧调用）→ None，不报错
    assert K.build(registry=reg, renders=tmp_path, snapshot=None, local_starts={}, now=1_800_000_000.0, url=lambda r: r, vurl=lambda r: r)["episodes"][0]["film"] is None
