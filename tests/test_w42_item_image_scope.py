"""W42 Q2-OUTFIT（11-04）：V2 清单单品按 (角色, 造型) 取，不借别的角色的同名单品。

根因：A_outfit1 / A_acc1 / A_shoes1 在江雨白、卓琳、唐瑶下同名，旧 item_image 全清单找第一个命中 →
唐瑶 S10 的服装参考拿成卓琳的 A_outfit1，出图带错参考、Q2 比对也对着错图（ep01 首帧 Q2 全 fail）。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/render_router", "services/agent", "services/post", "packages/qc", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402

V2 = "series10_v2"
need_v2 = pytest.mark.skipif(not AR.manifest_rel(V2) or not (ROOT / AR.manifest_rel(V2)).is_file(), reason="V2 资产包清单缺")

FAKE = {"characters": {
    "ch_a": {"looks": {"A": {"items": {"A_outfit1": {"file": "a/A_outfit1.png"}, "A_acc1": {"file": "a/A_acc1.png"}}}}},
    "ch_b": {"looks": {"A": {"items": {"A_outfit1": {"file": "b/A_outfit1.png"}}},
                       "B": {"items": {"B_only": {"file": "b/B_only.png"}}}}},
    "lead": {"items": {"SH1": {"file": "lead/SH1.png"}},
             "looks": {"O4": {"items": {"SH1": {"file": "lead/O4_SH1.png"}}}}},
}}


@pytest.fixture
def fake_manifest(monkeypatch):
    monkeypatch.setattr(AR, "manifest_rel", lambda project: "fake.json" if project else None)
    monkeypatch.setattr(AR, "manifest", lambda project: FAKE)
    monkeypatch.setattr(AR, "_manifest_file", lambda e: e.get("file") if isinstance(e, dict) else None)


def test_scoped_to_own_character(fake_manifest):
    assert AR.item_image("A_outfit1", "p", "ch_b", "A") == "b/A_outfit1.png"
    assert AR.item_image("A_outfit1", "p", "ch_a", "A") == "a/A_outfit1.png"


def test_never_borrows_other_characters_item(fake_manifest):
    assert AR.item_image("A_acc1", "p", "ch_b", "A") is None        # ch_b 没有 A_acc1：不拿 ch_a 的


def test_look_item_preferred_then_character_then_other_looks(fake_manifest):
    assert AR.item_image("SH1", "p", "lead", "O4") == "lead/O4_SH1.png"
    assert AR.item_image("SH1", "p", "lead", "O1") == "lead/SH1.png"
    assert AR.item_image("B_only", "p", "ch_b", "A") == "b/B_only.png"


def test_without_cid_ambiguous_fails_closed(fake_manifest):
    assert AR.item_image("A_outfit1", "p") is None                  # 两个角色同名：不猜
    assert AR.item_image("A_acc1", "p") == "a/A_acc1.png"           # 唯一：照旧


@need_v2
def test_v2_ep01_no_cross_character_items():
    from ns_agent import run_paths as RP
    src = Path(RP.runs_module(ROOT).script_path(V2, ROOT))
    if not src.is_file():
        pytest.skip("V2 导入稿缺")
    doc = json.loads(src.read_text(encoding="utf-8"))
    ep = next((e for e in doc.get("episodes") or [] if int(e.get("number") or 0) == 1), None)
    if ep is None:
        pytest.skip("V2 没有第 1 集")
    seen = 0
    for s in ep.get("shots") or []:
        sr = AR.resolve_shot(V2, ep, s)
        for r in sr.refs:
            if r.role == "item" and r.source == "wardrobe" and r.character:
                seen += 1
                assert f"/characters/{r.character}/" in r.file.replace("\\", "/"), (s.get("index"), r.character, r.file)
    assert seen
