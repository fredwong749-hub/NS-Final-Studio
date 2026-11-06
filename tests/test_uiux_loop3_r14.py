"""UIUX-LOOP-3 第 14 轮（11-06，PS-MASTER 定规则）：最新成片不按 mtime 挑。
活的例子：ep01_v64_post.mp4（预览版，4 镜占位）被同步重新 touch 过，mtime 比 ep01_v65.mp4（16/16 真视频）新 → /preview 和 KPI 都挑了 v64_post。
规则：① 合成闸门通过的 > 没有闸门记录的（timeline 还没同步到）> 预览 / 闸门没过的；② 同一档版本号大的在前；③ *.part / 0 字节 / 旁边有 .part 的一律不列。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "services/render", "services/post", "services/render_router", "tools/autopilot"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _tl(verdict, preview, missing=()):
    return {"preview": preview, "duration_s": 60.0, "shots": [{"shot": "ep01-S1", "index": 1, "kind": "video", "start_s": 0, "duration_s": 5}],
            "gates": {"verdict": verdict, "missing_shots": [{"shot": m, "reason": "没有视频版本"} for m in missing]}}


def test_rank_gate_pass_then_version_not_mtime(tmp_path):
    from ns_api import cuts as C
    C._TL_CACHE.clear()
    ep = tmp_path / "episodes"
    now = time.time()
    # v64_post：预览版、闸门没过，但 mtime 最新（同步 touch 过）
    _w(ep / "ep01_v64_post.mp4", "a"); _w(ep / "ep01_v64_post.timeline.json", _tl("fail", True, ["S2", "S4"]))
    os.utime(ep / "ep01_v64_post.mp4", (now, now))
    # v65：timeline 还没同步到（没有闸门记录），mtime 旧
    _w(ep / "ep01_v65.mp4", "b"); os.utime(ep / "ep01_v65.mp4", (now - 300, now - 300))
    # v60：闸门通过的成片，mtime 最旧
    _w(ep / "ep01_v60.mp4", "c"); _w(ep / "ep01_v60.timeline.json", _tl("pass", False))
    os.utime(ep / "ep01_v60.mp4", (now - 3600, now - 3600))
    # v58：也通过，版本更低
    _w(ep / "ep01_v58.mp4", "d"); _w(ep / "ep01_v58.timeline.json", _tl("pass", False))
    os.utime(ep / "ep01_v58.mp4", (now - 10, now - 10))
    # 正在写的：.part、0 字节、旁边有 .part 的
    _w(ep / "ep01_v66.mp4.part", "x")
    _w(ep / "ep01_v66.timeline.json.part", "")
    _w(ep / "ep01_v67.mp4", "")
    _w(ep / "ep01_v68.mp4", "y"); _w(ep / "ep01_v68.mp4.part", "y")
    names = [f.name for f in C.episode_films(ep, 1)]
    assert names == ["ep01_v60.mp4", "ep01_v58.mp4", "ep01_v65.mp4", "ep01_v64_post.mp4"], names
    assert C.latest_film(ep, 1)["name"] == "ep01_v60.mp4"
    assert C.film_tier(ep / "ep01_v60.mp4") == 0 and C.film_tier(ep / "ep01_v65.mp4") == 1 and C.film_tier(ep / "ep01_v64_post.mp4") == 2


def test_no_pass_film_picks_unknown_gate_by_version_over_preview(tmp_path):
    """活的情况：只有 v64_post（预览）和 v65（没 timeline）→ v65"""
    from ns_api import cuts as C
    C._TL_CACHE.clear()
    ep = tmp_path / "episodes"
    now = time.time()
    _w(ep / "ep01_v64_post.mp4", "a"); _w(ep / "ep01_v64_post.timeline.json", _tl("fail", True, ["S2"]))
    os.utime(ep / "ep01_v64_post.mp4", (now, now))
    _w(ep / "ep01_v65.mp4", "b"); os.utime(ep / "ep01_v65.mp4", (now - 400, now - 400))
    f = C.latest_film(ep, 1)
    assert f["name"] == "ep01_v65.mp4" and f["gate"] is None
    # 同一档（都是预览）→ 版本号大的在前，不看 mtime
    _w(ep / "ep01_v63_post.mp4", "c"); _w(ep / "ep01_v63_post.timeline.json", _tl("fail", True, ["S2"]))
    os.utime(ep / "ep01_v63_post.mp4", (now + 50, now + 50))
    names = [f.name for f in C.episode_films(ep, 1)]
    assert names == ["ep01_v65.mp4", "ep01_v64_post.mp4", "ep01_v63_post.mp4"], names


def test_cuts_list_and_kpi_follow_rank(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_render import pipeline as P
    from ns_api import cuts as C
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    C._TL_CACHE.clear()
    ep = tmp_path / "data" / "episodes"
    now = time.time()
    _w(ep / "ep01_v64_post.mp4", "a"); _w(ep / "ep01_v64_post.timeline.json", _tl("fail", True, ["S2"]))
    os.utime(ep / "ep01_v64_post.mp4", (now, now))
    _w(ep / "ep01_v65.mp4", "b"); os.utime(ep / "ep01_v65.mp4", (now - 400, now - 400))
    _w(ep / "ep01_v66.mp4.part", "writing")
    app = FastAPI()
    app.include_router(C.router)
    r = TestClient(app).get("/api/episodes/1/cuts").json()
    assert [x["name"] for x in r["cuts"]] == ["ep01_v65.mp4", "ep01_v64_post.mp4"]
    assert r["cuts"][0]["gate"] is None and r["cuts"][1]["gate"]["kind"] == "preview"
    from ns_api import episode_kpi as K
    reg = {"run": "r", "episodes": [{"ep": 1, "title": "一", "shots": [{"shot": "ep01-S1", "index": 1, "objects": {"first": {"status": "passed"}}}]}]}
    out = K.build(registry=reg, renders=tmp_path, snapshot=None, local_starts={"1": now - 60}, now=now, url=lambda r: r, vurl=lambda r: r,
                  film_of=lambda n: C.latest_film(ep, n, tmp_path / "data"))
    film = out["episodes"][0]["film"]
    assert film["name"] == "ep01_v65.mp4" and film["kind_word"] == "整集成片" and film["word"] == "闸门记录还没同步到本机"
