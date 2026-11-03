"""MASTER-WSL 14:14：双人镜 A 版第 3 槽按当前剧主角（P1 role=主角）取，不再写死 V1 lin_wan / 林晚"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("producer_lead_t", ROOT / "tools/autopilot/producer.py")
PR = importlib.util.module_from_spec(sp)
sp.loader.exec_module(PR)


def test_lead_char_from_p1(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "ROOT", tmp_path)
    d = tmp_path / "data/pipeline/runs/s_t"
    d.mkdir(parents=True)
    (d / "P1_storyline.json").write_text(json.dumps({"characters": [
        {"char_id": "ch_b", "role": "对手"}, {"char_id": "lead_f", "role": "主角"}]}, ensure_ascii=False), encoding="utf-8")
    assert PR.lead_char("s_t") == "lead_f"
    assert PR.lead_char("missing") is None and PR.lead_char(None) is None


def test_no_lead_falls_back_with_note():
    job = {"prompt": "x"}
    out = PR.lead_sheet_variant("p", 1, None, job, {}, lead=None)
    assert out["prompt"] == "x" and "主角" in out["variant_note"]


def test_real_v2_lead_and_no_v1_literal_in_code():
    assert PR.lead_char("series10_v2") == "lead_f"
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert '"lin_wan"' not in src and "林晚造型设定图" not in src
    assert PR.linwan_sheet_variant is PR.lead_sheet_variant


def _fake_ar(monkeypatch, slots, capacity=3, sheet=True):
    import sys
    import types
    from dataclasses import dataclass, field

    @dataclass
    class Slot:
        n: int
        kind: str
        file: str
        character: str
        labels: list
        members: list = field(default_factory=list)
        faces: int = 0
        line: str = ""

    @dataclass
    class Plan:
        slots: list
        capacity: int
        prompt_prefix: str

        @property
        def files(self):
            return [s.file for s in self.slots]

    for s in slots:
        s.line = f"[{s.kind}:{s.character}]"
    plan = Plan(slots, capacity, "".join(s.line for s in slots))
    ref = types.SimpleNamespace(role="sheet", character="lead_f", file="sheet.png", look_id="O4", label="设定图", source="x")
    sr = types.SimpleNamespace(refs=[ref] if sheet else [], characters=[{"character": "lead_f", "look": "O4"}])
    fake = types.SimpleNamespace(plan_for=lambda *a, **k: (sr, plan), Slot=Slot, _line=lambda p, s: f"[{s.kind}:{s.character}]",
                                 record=lambda sr_, p: {"slots": [{"kind": s.kind, "character": s.character} for s in p.slots]})
    monkeypatch.setitem(sys.modules, "ns_agent.asset_refs", fake)
    import ns_agent
    monkeypatch.setattr(ns_agent, "asset_refs", fake, raising=False)
    return Slot, plan


def test_three_person_faceboard_kept(monkeypatch):
    """ISS-1103-141532：三人镜脸板槽不能被当成非脸丢掉"""
    Slot, plan = _fake_ar(monkeypatch, [])
    plan.slots[:] = [Slot(1, "faceboard", "fb.png", "ch_a", ["甲", "乙", "丙"], [{"file": "a.png"}, {"file": "b.png"}, {"file": "c.png"}], 3),
                     Slot(2, "board", "b1.png", "ch_a", ["服装"]), Slot(3, "board", "b2.png", "ch_c", ["服装"])]
    for s in plan.slots:
        s.line = f"[{s.kind}:{s.character}]"
    plan.prompt_prefix = "".join(s.line for s in plan.slots)
    job = {"prompt": plan.prompt_prefix + "正文"}
    out = PR.lead_sheet_variant("p", 1, None, job, {}, lead="lead_f")
    kinds = [s["kind"] for s in out["asset_refs"]["slots"]]
    assert kinds == ["faceboard", "sheet"] and out["prompt"].endswith("正文")
    assert out["face_files"] == ["a.png", "b.png", "c.png"]


def test_capacity_full_keeps_default(monkeypatch):
    Slot, plan = _fake_ar(monkeypatch, [], capacity=2)
    plan.slots[:] = [Slot(1, "face", "a.png", "ch_a", ["甲"]), Slot(2, "face", "b.png", "ch_b", ["乙"])]
    for s in plan.slots:
        s.line = f"[{s.kind}:{s.character}]"
    plan.prompt_prefix = "".join(s.line for s in plan.slots)
    job = {"prompt": plan.prompt_prefix + "正文"}
    out = PR.lead_sheet_variant("p", 1, None, job, {}, lead="lead_f")
    assert out["prompt"] == job["prompt"] and "上限" in out["variant_note"]
