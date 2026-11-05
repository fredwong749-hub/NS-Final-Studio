"""UI-STATUS 11-05：全剧总览按实时来源显示（重导入后旧成片不算完成 / 旧卡点不再挡格子 / 下游已有新产物时提示词证据过期不挡 / 常驻 pid 精确判活）。"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from ns_api import pipeline_status as PS  # noqa: E402
from ns_api import sop as SOP  # noqa: E402

JST = timezone(timedelta(hours=9))
RUN = "series10_v2"


def _gate():
    sp = importlib.util.spec_from_file_location("t_sg_live", ROOT / "tools" / "master" / "sop_gate.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _w(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _root(tmp_path: Path) -> Path:
    _w(tmp_path / "config/pipeline/runs.json", json.dumps({"primary": RUN, "legacy_unprefixed_run": "series10", "runs": {RUN: {"status": "producing"}}}))
    return tmp_path


def _epoch(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=JST).timestamp()


def test_old_preview_not_done_after_reimport(tmp_path):
    G, r = _gate(), _root(tmp_path)
    mp4 = _w(r / f"data/episodes/{RUN}/ep01_v6.mp4")
    os.utime(mp4, (_epoch("2026-11-05T10:46:00"), _epoch("2026-11-05T10:46:00")))
    assert G.check_preview(r, RUN, 1)["ok"]                          # 没有导入记录 = 旧行为
    _w(r / f"data/pipeline/runs/{RUN}/episode_run/ep01_state.json", json.dumps({"import": {"sha": "x", "at": "2026-11-05T19:10:52"}}))
    res = G.check_preview(r, RUN, 1)
    assert not res["ok"] and res.get("stale_preview") and "旧版剧本拼的" in res["why"]
    assert "旧版剧本拼的整集预览已作废" in PS.plain("整集预览", False, res["why"], 1)
    os.utime(mp4, (_epoch("2026-11-05T22:00:00"),) * 2)               # 导入之后拼的 = 完成
    assert G.check_preview(r, RUN, 1)["ok"]


def test_import_event_from_producer_log(tmp_path):
    G, r = _gate(), _root(tmp_path)
    ev = {"ts": "2026-11-05T19:10:52", "t": 1793873452.04, "ev": "imported_staged", "status": 200, "episodes": [1]}
    _w(r / f"data/producer/runs/{RUN}/log.jsonl", json.dumps(ev) + "\n")
    assert abs(G.current_import_at(r, RUN, 1) - 1793873452.04) < 1
    assert G.current_import_at(r, RUN, 2) is None                      # 别的集没导入过


def test_pid_alive_is_exact(monkeypatch):
    spec = importlib.util.spec_from_file_location("t_afr", ROOT / "tools" / "factory" / "autoflow_resident.py")
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    assert A._pid_alive(os.getpid()) and not A._pid_alive(0)
    if os.name == "nt":
        class R:
            stdout = '"other.exe","1419960","Console","1","41,996 K"\n'
        monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: R())
        assert not A._pid_alive(41996)                                 # 子串（内存数 / 更长 pid）不再误判活着


def test_stale_provider_prompt_proof_and_video_doing(monkeypatch):
    rows = [{"stage": s, "ok": True, "why": ""} for s in ("剧本", "导入闸门", "资产就绪")] + [
        {"stage": "提示词", "ok": False, "why": "证据过期（2026-11-04T23:54:11 之后导入稿或资产清单变了，重跑 probe-prompts）"},
        {"stage": "出图", "ok": False, "why": "12/16 镜有首帧；缺 镜1"},
        {"stage": "出图检测", "ok": False, "why": "12/16 镜首帧过契约 + Q9；缺 镜1"},
        {"stage": "尾帧", "ok": True, "why": ""}, {"stage": "视频", "ok": False, "why": "0/16 镜有片段"},
        {"stage": "整集预览", "ok": False, "why": "没有整集预览片"}]

    class G:
        @staticmethod
        def current_import_at(*a):
            return 1.0

        @staticmethod
        def shot_frames(*a):
            return {i: {"image": True, "checked": True, "last": True} for i in range(1, 12)}

        @staticmethod
        def _runs():
            raise RuntimeError("no renders")
    monkeypatch.setattr(PS, "_takes_since", lambda G_, run, ep, stage, since: 3 if stage == "image" else 0)
    monkeypatch.setattr(PS, "producer_state", lambda run: {"alive": True, "age_s": 5, "paused": False})
    monkeypatch.setattr(PS, "_night_rendering", lambda run, ep: False)
    adj, live = PS.live_adjust(G, RUN, 1, rows)
    assert next(r for r in adj if r["stage"] == "提示词")["ok"] and live["video_ready"] == 11
    cells = PS.fold(adj, 1, live)
    assert [cells[s]["state"] for s, *_ in PS.STEPS] == ["done", "done", "done", "doing", "doing", "todo"]
    assert "11 镜首尾帧定稿" in cells["video"]["plain"]
    # 没有下游新产物时：仍是“过期”，且文案不再是“在等系统…”
    monkeypatch.setattr(PS, "_takes_since", lambda *a: 0)
    adj2, _ = PS.live_adjust(G, RUN, 1, rows)
    assert not next(r for r in adj2 if r["stage"] == "提示词")["ok"]
    assert "重新核对" in PS.plain("提示词", False, rows[3]["why"], 1)


def test_issues_older_than_import_do_not_block():
    steps = [{"id": s, "label": s} for s in SOP.STEP_IDS]
    cell = lambda st: {"state": st, "plain": st, "why": ""}  # noqa: E731
    ep = {"episode": 1, "stage": "出图", "plain": "", "retro": None, "import_at": "2026-11-05 19:10:52",
          "cells": {"script": cell("done"), "assets": cell("done"), "board": cell("done"), "frames": cell("doing"), "video": cell("todo"), "cut": cell("todo")}}
    old = {"id": "A", "run": "r", "episode": 1, "step": "9", "who": "SYSAUDIT-F", "blocking": True, "status": "open", "what": "没有任何一台机器在跑", "time": "2026-11-03 03:33:10"}
    new = {"id": "B", "run": "r", "episode": 1, "step": "9", "who": "WATCHDOG", "blocking": True, "status": "open", "what": "新的卡点", "time": "2026-11-05 20:00:00"}
    v = SOP.stepbar_view({"run": "r", "title": "t", "episodes_total": 1, "steps": steps, "episodes": [ep]}, [old])
    c = v["episodes"][0]["cells"]["frames"]
    assert c["state"] == "doing" and not c["block"] and c["issues"][0]["old"] is True           # 旧卡点仍列出，但不挡
    v2 = SOP.stepbar_view({"run": "r", "title": "t", "episodes_total": 1, "steps": steps, "episodes": [ep]}, [old, new])
    assert v2["episodes"][0]["cells"]["frames"]["state"] == "blocked"                          # 导入之后的新卡点照常挡
