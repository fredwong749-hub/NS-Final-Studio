"""V2 完全切割检查（tools/script_rsi/v1_leak.py，L-126）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v1_leak", ROOT / "tools" / "script_rsi" / "v1_leak.py")
VL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VL)

V = {"names": ["林晚", "顾沉"], "char_ids": ["lin_wan"], "scenes": ["sk_office_night", "深夜写字楼办公区角落"], "titles": ["漆皮之下·十日"],
     "props": ["门卡", "束腰"], "allow_text": ["黑色漆皮双排扣长风衣（系腰带）"]}


def test_hits_names_scenes_props():
    hits = VL.scan("林晚在 sk_office_night 拿起门卡", V)
    assert {h["kind"] for h in hits} == {"names", "scenes", "props"}


def test_owner_outfit_names_allowed():
    assert VL.scan("她穿黑色漆皮双排扣长风衣（系腰带）走进雨里", V) == []


def test_real_vocab_builds():
    v = VL.vocab(current="series10_v2")
    assert "林晚" in v["names"] and any(s.startswith("sk_") for s in v["scenes"])


def test_rejected_drafts_join_vocab():
    """L-127：本 run 被退回的 P1（_rejected_*/writer_out_P1_a1.json）的人物 / 场景 / 剧名也算旧内容；女主固定 id lead_f 不算"""
    v = VL.vocab(current="series10_v2")
    rej = list((ROOT / "data/pipeline/runs/series10_v2").glob("_rejected_*/writer_out_P1_a1.json"))
    if rej:
        assert "lead_f" not in v["char_ids"]
        assert any(t not in ("漆皮之下·十日",) for t in v["titles"])


def test_empty_allow_text_does_not_break_scan():
    """11-02 bug：allow_text 里混进空串，body.replace('', ' ') 把每个字隔开，所有命中都漏掉"""
    v = dict(V, allow_text=["", "黑色漆皮双排扣长风衣（系腰带）"])
    assert {h["word"] for h in VL.scan("林晚拿起门卡", v)} == {"林晚", "门卡"}
