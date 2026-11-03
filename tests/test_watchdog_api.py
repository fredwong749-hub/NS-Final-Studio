"""W27：看门狗规则 10——:8800 不在 → ps1 -Force -Revive 补起（一轮最多一次）→ 再探；桩掉 HTTP 与 subprocess。"""
from __future__ import annotations

import importlib.util
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOW = time.mktime(time.strptime("2026-11-03 12:00:00", "%Y-%m-%d %H:%M:%S"))
sp = importlib.util.spec_from_file_location("watchdog_api_t", ROOT / "tools/master/watchdog.py")
W = importlib.util.module_from_spec(sp)
sp.loader.exec_module(W)


def _ctx(tmp: Path, probes: list[bool], enabled=True):
    cfg = dict(W.DEFAULT_CFG)
    cfg["api_revive"] = {**W.DEFAULT_CFG["api_revive"], "enabled": enabled}
    c = W.Ctx(tmp, NOW, cfg)
    seq = list(probes)
    c.api_up = lambda: seq.pop(0) if len(seq) > 1 else seq[0]
    c.sleep = lambda s: None
    c.notes, c.calls = [], []
    c.live_note = lambda line: c.notes.append(line)
    return c


def _stub_sub(monkeypatch, calls):
    def fake(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(W.subprocess, "run", fake)


def test_down_then_revived_writes_live_no_issue(tmp_path, monkeypatch):
    c = _ctx(tmp_path, [False, True])
    _stub_sub(monkeypatch, c.calls)
    assert W.r10_api_8800(c) == []
    assert len(c.calls) == 1 and c.calls[0][-2:] == ["-Force", "-Revive"] and c.calls[0][0] == "powershell"
    assert len(c.notes) == 1 and "8800" in c.notes[0]


def test_down_after_revive_registers_once(tmp_path, monkeypatch):
    c = _ctx(tmp_path, [False])
    _stub_sub(monkeypatch, c.calls)
    out = W.r10_api_8800(c)
    assert len(c.calls) == 1 and len(out) == 1
    assert out[0]["blocking"] and out[0]["key"] == "r10:api_8800" and not c.notes


def test_disabled_does_not_call_ps1(tmp_path, monkeypatch):
    c = _ctx(tmp_path, [False], enabled=False)
    _stub_sub(monkeypatch, c.calls)
    out = W.r10_api_8800(c)
    assert c.calls == [] and len(out) == 1 and out[0]["blocking"]


def test_at_most_one_revive_per_round(tmp_path, monkeypatch):
    c = _ctx(tmp_path, [False])
    _stub_sub(monkeypatch, c.calls)
    W.r10_api_8800(c)
    W.r10_api_8800(c)
    assert len(c.calls) == 1


def test_up_or_dry_never_revives(tmp_path, monkeypatch):
    c = _ctx(tmp_path, [True])
    _stub_sub(monkeypatch, c.calls)
    assert W.r10_api_8800(c) == [] and c.calls == []
    d = _ctx(tmp_path, [False])
    d.dry = True
    assert len(W.r10_api_8800(d)) == 1 and d.calls == []
