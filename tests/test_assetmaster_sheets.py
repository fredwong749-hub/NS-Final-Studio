"""ASSETMASTER 设定图：选暂定要过单品一致性检查（K-AST-260）；adopt 必须同步写 sheets_chosen.json（K-AST-261 解析器读这份）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/assetmaster", "tools/series10_imggen", "services/render_router", "services/agent", "packages/schema", "tools/pipeline"):
    sys.path.insert(0, str(ROOT / p))

import choose as CH  # noqa: E402
import gen_look_sheets as GS  # noqa: E402


def test_item_check_required():
    live = {"lin_wan_lookB": {"chosen": {"seed": "303", "file": "x303.png", "ok": True}},
            "gu_chen_lookA": {"chosen": {"seed": "101", "file": "g.png", "ok": True}},
            "chen_yu_lookA": {"chosen": {"seed": "101", "file": "c.png", "ok": True}}}
    checks = {"lin_wan_lookB": {"seed": "505", "verdict": "pass"}, "gu_chen_lookA": {"seed": "101", "verdict": "pass", "how": "目检"}}
    CH.enforce_item_check(live, checks)
    assert live["lin_wan_lookB"]["chosen"]["ok"] is False          # 选中的 seed 与目检记录不一致 → 不 adopt
    assert live["gu_chen_lookA"]["chosen"]["ok"] is True and live["gu_chen_lookA"]["chosen"]["item_check"]["how"] == "目检"
    assert live["chen_yu_lookA"]["chosen"]["ok"] is False and "K-AST-260" in live["chen_yu_lookA"]["chosen"]["why"]


def test_adopt_atomic_versioned_no_delete(tmp_path, monkeypatch):
    """K-AST-261：adopt 同步写 sheets_chosen.json（解析器读这份）；新图复制成带版本的新文件名、先 prewarm 裁切再切指针；
    不删除任何旧裁切（排队作业还在引用：01:29 job b30ec4a4e11e Errno 2）"""
    run = tmp_path / "run"
    (run / "assets").mkdir(parents=True)
    old_crop = run / "images/refcrops/gu_chen_lookA_s101_front_nohead.png"
    old_crop.parent.mkdir(parents=True)
    old_crop.write_bytes(b"old")
    (tmp_path / "new.png").write_bytes(b"newsheet")
    (run / "assets/registered_refs.json").write_text(json.dumps([{"asset": "gu_chen", "role": "item", "look": "A", "src": "old.png"}]), encoding="utf-8")
    (run / "assets/sheets_chosen.json").write_text(json.dumps({"sheet:gu_chen_lookA": {"file": "old.png", "char": "gu_chen"}}), encoding="utf-8")
    res = tmp_path / "sheets_v2.json"
    res.write_text(json.dumps({"gu_chen_lookA": {"chosen": {"seed": "101", "file": "new.png", "ok": True}}}), encoding="utf-8")
    seen = []

    def fake_prewarm(rel, project="series10_v1"):
        sc = json.loads((run / "assets/sheets_chosen.json").read_text(encoding="utf-8"))
        seen.append((rel, sc["sheet:gu_chen_lookA"]["file"]))       # 预热时指针还没切
        return []

    monkeypatch.setattr(GS, "ROOT", tmp_path)
    monkeypatch.setattr(GS, "RUN", run)
    monkeypatch.setattr(GS, "RES", res)
    monkeypatch.setattr(GS, "OUT", tmp_path / "sheets_v2")
    monkeypatch.setattr(GS, "prewarm", fake_prewarm)
    GS.adopt(type("A", (), {"only": "gu_chen_lookA", "prewarm": True})())
    new = "sheets_v2/adopted/gu_chen_lookA_v2_s101.png"
    assert seen == [(new, "old.png")]
    sc = json.loads((run / "assets/sheets_chosen.json").read_text(encoding="utf-8"))
    assert sc["sheet:gu_chen_lookA"]["file"] == new and sc["sheet:gu_chen_lookA"]["file_v1"] == "old.png"
    assert (tmp_path / new).read_bytes() == b"newsheet"
    reg = json.loads((run / "assets/registered_refs.json").read_text(encoding="utf-8"))
    assert reg[0]["src"] == new and reg[0]["sheets_v1_src"] == "old.png"
    assert old_crop.exists()                                        # 旧裁切一个不删
