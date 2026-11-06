"""W-PROD 11-07 K 块：①“视线从画外…”不算露脸（ep03-S4 K-REN-708 误报）；② 一集两套造型用逐镜登记代替整集排期（ep03 祁念 O1 + O2）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "tools/master"):
    sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import framing as FR  # noqa: E402
import episode_ready as ER  # noqa: E402

INSERT = ("特写，俯拍机位，黎岸的左手在画面右侧伸向茶几上的手机，手腕一只钢带腕表，黎岸的上身在画外上方，"
          "黎岸的视线从画外上方落在手机屏幕上；冷白的屏幕光打在水杯上")


def test_offscreen_gaze_is_not_a_face():
    assert "视线" not in FR.strip_offscreen_gaze(INSERT)
    assert FR.closeup_subject(INSERT, "特写") != "face"
    assert not AR.partial_face_visible("黎岸", INSERT, ["黎岸"])


def test_onscreen_gaze_still_counts_as_face():
    img = "特写，黎岸的左手拿着手机，黎岸的视线落在手机屏幕上"
    assert FR.closeup_subject(img, "特写") == "face"
    assert AR.partial_face_visible("黎岸", img, ["黎岸"])


def _gaps(monkeypatch, reg, ovs=None, hub=None, shots=(1, 3)):
    monkeypatch.setattr(AR, "face_of", lambda run, cid: "f.png")
    monkeypatch.setattr(AR, "episode_look_override", lambda run, cid, ep: hub)
    monkeypatch.setattr(AR, "registry_looks", lambda run: reg)
    monkeypatch.setattr(AR, "shot_overrides", lambda run: (ovs or {}, {}))
    mchars = {"lead_f": {"display_name": "祁念", "looks": {"O1": {}, "O2": {}}}}
    return [g["kind"] for g in ER.character_gaps("r", "lead_f", "祁念", 3, mchars, shots=shots)]


def test_per_shot_registration_counts_as_schedule(monkeypatch):
    reg = {"ep03-S1": {"lead_f": "O1"}, "ep03-S3": {"lead_f": {"look": "O2"}}}
    assert "schedule" not in _gaps(monkeypatch, reg)


def test_canvas_override_counts_as_schedule(monkeypatch):
    ovs = {"ep03-S1": {"lead_f": {"look": "O1"}}, "ep03-S3": {"lead_f": {"look": "O2"}}}
    assert "schedule" not in _gaps(monkeypatch, {}, ovs=ovs)


def test_partial_or_unknown_registration_still_needs_schedule(monkeypatch):
    assert "schedule" in _gaps(monkeypatch, {"ep03-S1": {"lead_f": "O1"}})                       # 镜3 没登记
    assert "schedule" in _gaps(monkeypatch, {"ep03-S1": {"lead_f": "O1"}, "ep03-S3": {"lead_f": "O9"}})   # 不在清单
    assert "schedule" in _gaps(monkeypatch, {}, shots=None)                                        # 不给镜号 = 旧口径
    assert "schedule" not in _gaps(monkeypatch, {}, hub="O1")                                      # 整集排期照旧
