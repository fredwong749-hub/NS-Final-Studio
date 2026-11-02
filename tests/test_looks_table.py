"""P1 造型表检查（tools/script_rsi/looks_table.py；V2 任务书第 1 步）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("looks_table", ROOT / "tools" / "script_rsi" / "looks_table.py")
LT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LT)


def look(i, use="职场：ep01、ep02", en="an ivory blouse with a pencil skirt"):
    return {"id": i, "use": use, "zh": "服装=米白衬衫｜鞋=12cm透明细高跟｜饰品=细银链", "en": en}


def test_ok_and_coverage():
    looks = [{"name": "林晚", "char_id": "lin_wan", "marker": "钻石水晶甲", "looks": [look("A"), look("B", "私域：ep03")]}]
    sl = {"characters": [{"name": "林晚"}], "episodes": [{"episode": 1, "characters": ["林晚"]}, {"episode": 3, "characters": ["林晚"]}]}
    assert LT.check(looks, sl) == []
    sl["episodes"].append({"episode": 4, "characters": ["林晚"]})
    assert any("ep04" in p for p in LT.check(looks, sl))


def test_problems():
    bad = [{"name": "顾沉", "char_id": "gu_chen", "marker": "", "looks": [{"id": "A", "use": "办公室", "zh": "服装=西装", "en": "no tie"}]}]
    p = LT.check(bad, {"characters": [{"name": "顾沉"}, {"name": "陈宇"}]})
    txt = "；".join(p)
    for k in ("陈宇 没有造型", "1 套", "marker", "鞋", "否定词", "集号"):
        assert k in txt


def test_lead_f_fixed_looks_and_schedule():
    lead = {"name": "女主", "char_id": "lead_f", "marker": "蓝色长发",
            "looks": [{"id": i, "use": "全季：ep01", "zh": "服装=x｜鞋=SH1｜饰品=无", "en": "a black patent trench coat"} for i in ("O1", "O2", "O3", "O4")],
            "schedule": [{"episode": 1, "outfit": "O4", "shoes": "SH1"}, {"episode": 2, "outfit": "O1+O4", "shoes": "SH2", "intimate_outfit": "O2"}]}
    sl = {"characters": [{"name": "女主"}], "episodes": [{"episode": 1, "characters": ["女主"]}, {"episode": 2, "characters": ["女主"], "intimate": True}]}
    assert LT.lead_f_check(lead, sl) == []
    lead["schedule"][0]["outfit"] = "O2"
    sl["episodes"][1]["intimate"] = False
    p = "；".join(LT.lead_f_check(lead, sl))
    assert "日常造型只能是 O1 / O4" in p and "没标 intimate" in p
