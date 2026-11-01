"""UIRSI：实时推送扫描器 + 分段进度（临时目录，不碰生产数据）。"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from ns_api import live as L  # noqa: E402


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _bump(p: Path) -> None:
    t = time.time() + 5
    os.utime(p, (t, t))


def test_watcher_events(tmp_path, monkeypatch):
    roots = {k: tmp_path / k for k in ("runs", "renders", "assets", "episodes", "ab")}
    roots["voices"] = tmp_path / "voices.json"
    roots["tts"] = tmp_path / "tts"
    w = L.Watcher(roots=roots)
    monkeypatch.setattr(w, "_jobs", lambda: jobs)
    jobs = [{"id": "j1", "shot_id": "ep01-S2", "state": "queued", "stage": "image"}]
    tk = roots["renders"] / "ep01" / "S2" / "takes.json"
    _w(tk, {"takes": [], "active": {}})
    _w(roots["runs"] / "series_t" / "ep01" / "P3_ep01_screenplay.json", {})
    _w(roots["voices"], {})
    assert w.scan_once() == []                      # 第一次只记基线
    _w(tk, {"takes": [{"n": 1, "stage": "image"}], "active": {}})
    _bump(tk)
    _w(roots["runs"] / "series_t" / "ep01" / "P4_ep01.md", {})
    (roots["runs"] / "series_t" / "video" / "ep01").mkdir(parents=True)
    (roots["runs"] / "series_t" / "video" / "ep01" / "ep01-S2_take1.mp4").write_bytes(b"x")
    jobs = [{"id": "j1", "shot_id": "ep01-S2", "state": "running", "stage": "image"}]
    evs = w.scan_once()
    got = {(e["type"], e.get("shot"), e["field"]) for e in evs}
    assert ("frame", "ep01-S2", "new") in got
    assert ("stage", None, "P4_ep01.md") in got
    assert ("video", "ep01-S2", "draft") in got
    assert ("job", "ep01-S2", "running") in got
    assert all(e.get("episode") == 1 for e in evs)
    assert w.scan_once() == []                      # 没变化不推
    _w(tk, {"takes": [{"n": 1, "stage": "image"}], "active": {"image": 1}})
    _bump(tk)
    _w(roots["voices"], {"a": 1})
    _bump(roots["voices"])
    got = {(e["type"], e["field"]) for e in w.scan_once()}
    assert ("frame", "active") in got and ("voice", "voices") in got
    assert [e["seq"] for e in w.since(0)] == sorted(e["seq"] for e in w.since(0)) and w.since(w.seq) == []


def test_progress(monkeypatch):
    monkeypatch.setattr(L, "_script_stages", lambda run: {1: {"P3": "ok", "P4": "needs_writer", "running": False}})
    monkeypatch.setattr(L, "_voice_counts", lambda ep: (3, 5))
    monkeypatch.setattr(L, "_cut_done", lambda n: False)
    eps = [{"number": 1, "title": "一", "shots": [
        {"id": "ep01-S1", "first_frame": "/a.png", "last_frame_target": None, "video": None},
        {"id": "ep01-S2", "first_frame": None, "last_frame_target": None, "video": None}]}]
    jobs = [{"id": "a", "shot_id": "ep01-S2", "stage": "image", "state": "failed", "error": "显存不够\n详情", "created_at": "2026-11-01T01:00:00"},
            {"id": "b", "shot_id": "ep01-S1", "stage": "last", "state": "running", "eta_s": 60, "created_at": "2026-11-01T01:01:00",
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 20))}]
    p = L.compute_progress("series_t", eps, jobs, {"episodes": [{"number": 1}]})
    s = p["episodes"][0]["segs"]
    assert (s["script"]["done"], s["board"]["failed"], s["board"]["reasons"]) == (1, 1, ["要返修"])
    assert (s["first"]["done"], s["first"]["total"], s["first"]["failed"]) == (1, 2, 1) and "S2：显存不够" in s["first"]["reasons"][0]
    assert s["last"]["running"] == 1 and 35 <= s["last"]["eta_s"] <= 41
    assert (s["voice"]["done"], s["voice"]["total"], s["cut"]["done"]) == (3, 5, 0)
    assert p["total"]["first"]["done"] == 1 and p["total"]["first"]["total"] == 2 and p["order"][0] == "script"


def test_progress_regression_reason(monkeypatch):
    monkeypatch.setattr(L, "_script_stages", lambda run: {})
    monkeypatch.setattr(L, "_cut_done", lambda n: False)
    L._hw.clear()
    L._memo.clear()
    eps = [{"number": 1, "title": "一", "shots": [{"id": "ep01-S1", "first_frame": "/a.png"}]}]
    sc = {"episodes": [{"number": 1}]}
    monkeypatch.setattr(L, "_voice_counts", lambda ep: (6, 6))
    p = L.compute_progress(None, eps, [], sc, now=1000.0)
    assert "regressed" not in p["episodes"][0]["segs"]["voice"]
    L._memo.clear()
    monkeypatch.setattr(L, "_voice_counts", lambda ep: (3, 6))
    p = L.compute_progress(None, eps, [], sc, now=1010.0)
    r = p["episodes"][0]["segs"]["voice"]["regressed"]
    assert (r["from"], r["to"]) == (6, 3) and "重配" in r["reason"]
    assert p["total"]["voice"]["regressed"]["from"] == 6
    L._memo.clear()
    p = L.compute_progress(None, eps, [], sc, now=1010.0 + L.REGRESS_KEEP_S + 5)
    assert "regressed" not in p["episodes"][0]["segs"]["voice"]      # 超过保留时间就当新基线
