"""第二季继承第一季资产项目（总调度 11-02；K-AST-W18）：asset_refs.json 的 "inherits"。
- project_cfg：父项目起逐层合并，字典深合并（faces / item_map），子项目写的路径覆盖；
- sheet_of：子季选定表有这条用子季的，没有回落父季；
- load_looks：父季造型在前，子季同 id 覆盖、新 id 追加；
- 第一季（无 inherits）行为不变。全部写临时目录。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router"):
    sys.path.insert(0, str(ROOT / p))
from ns_agent import asset_refs as AR  # noqa: E402

from PIL import Image  # noqa: E402


def _png(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8)).save(p)


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(AR, "ROOT", tmp_path)
    cfg = tmp_path / "asset_refs.json"
    cfg.write_text(json.dumps({"projects": {
        "s1": {"run_dir": "r1", "looks_file": "r1/looks.json", "sheets_file": "r1/sheets.json", "faces": {"lin_wan": ["f/lw.png"]},
               "item_map": {"lin_wan": {"A": {"鞋": "LW-S01"}}}, "shot_looks_file": "r1/shot_looks.json"},
        "s2": {"inherits": "s1", "run_dir": "r2", "looks_file": "r2/looks.json", "sheets_file": "r2/sheets.json",
               "item_map": {"lin_wan": {"D": {"鞋": "LW-S09"}}}, "shot_looks_file": "r2/shot_looks.json"}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "CFG", cfg)
    _png(tmp_path / "sheets/lw_A.png")
    _png(tmp_path / "sheets/lw_D.png")
    (tmp_path / "r1").mkdir()
    (tmp_path / "r2").mkdir()
    (tmp_path / "r1/sheets.json").write_text(json.dumps({"sheet:lin_wan_lookA": {"file": "sheets/lw_A.png"}}), encoding="utf-8")
    (tmp_path / "r2/sheets.json").write_text(json.dumps({"sheet:lin_wan_lookD": {"file": "sheets/lw_D.png"}}), encoding="utf-8")
    (tmp_path / "r1/looks.json").write_text(json.dumps([{"char_id": "lin_wan", "looks": [{"id": "A", "zh": "服装=米白衬衫"}]}]), encoding="utf-8")
    (tmp_path / "r2/looks.json").write_text(json.dumps([{"char_id": "lin_wan", "looks": [{"id": "D", "zh": "服装=黑色风衣"}]}]), encoding="utf-8")


def test_project_cfg_merges_chain(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    c2 = AR.project_cfg("s2")
    assert c2["faces"]["lin_wan"] == ["f/lw.png"]                                 # 身份脸继承第一季
    assert c2["item_map"]["lin_wan"]["A"]["鞋"] == "LW-S01" and c2["item_map"]["lin_wan"]["D"]["鞋"] == "LW-S09"
    assert c2["shot_looks_file"] == "r2/shot_looks.json" and c2["inherits"] == "s1"   # 每镜造型是本季自己的
    assert AR.project_chain("s2") == ["s2", "s1"] and "inherits" not in AR.project_cfg("s1")


def test_sheet_of_falls_back_to_parent(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert AR.sheet_of("s2", "lin_wan", "A") == "sheets/lw_A.png"                # 本季没登记 → 用第一季现行设定图
    assert AR.sheet_of("s2", "lin_wan", "D") == "sheets/lw_D.png"                # 本季新造型
    assert AR.sheet_of("s1", "lin_wan", "D") is None                              # 第一季不受第二季影响


def test_load_looks_merges_parent_and_child(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(AR, "hub_extra_looks", lambda project, data: [])
    monkeypatch.setattr(AR, "extra_parts", lambda cid, lid: [])
    monkeypatch.setattr(AR, "wardrobe", lambda: {})
    monkeypatch.setattr(AR, "item_map", lambda project: {})
    l2 = AR.load_looks("s2")
    assert set(l2["lin_wan"]) == {"A", "D"}
    assert set(AR.load_looks("s1")["lin_wan"]) == {"A"}


def test_cycle_safe(monkeypatch, tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"projects": {"a": {"inherits": "b"}, "b": {"inherits": "a"}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "CFG", cfg)
    assert AR.project_chain("a") == ["a", "b"]
