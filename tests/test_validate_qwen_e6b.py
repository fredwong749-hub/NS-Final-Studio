"""QW-E6b 造型单品登记（tools/validate_qwen_script.py；总调度 11-02：组合串拆开、去“（产品）”后缀、只查 服装 / 鞋 / 其他）。不写真实数据。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_qwen_script", ROOT / "tools" / "validate_qwen_script.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def test_combo_split_and_skip():
    assert V.look_items("米白色修身细针织上衣、黑色镜面漆皮超短裙") == ["米白色修身细针织上衣", "黑色镜面漆皮超短裙"]
    assert V.look_items("黑色漆皮束腰与黑色镜面漆皮超短裙") == ["黑色漆皮束腰", "黑色镜面漆皮超短裙"]
    assert V.look_items("0件") == [] and V.look_items("新：红色丝绒长裙") == [] and V.look_items("沿用") == []
    assert V.look_items("12cm透明细高跟（hh12clear）") == ["12cm透明细高跟"]


def test_wardrobe_suffix_and_attribute_slots(tmp_path, monkeypatch):
    w = tmp_path / "wardrobe.json"
    w.write_text('{"items": [{"name": "米白色修身细针织上衣（产品）"}, {"name": "黑色镜面漆皮超短裙"}]}', encoding="utf-8")
    monkeypatch.setattr(V, "WARDROBE", w)
    names = V._wardrobe_names()
    assert "米白色修身细针织上衣" in names and "米白色修身细针织上衣（产品）" in names
    assert all(it in names for it in V.look_items("米白色修身细针织上衣、黑色镜面漆皮超短裙"))
    assert set(V.E6B_SLOTS) == {"服装", "鞋", "其他"}          # 发 / 妆 / 甲 / 饰品 不查
