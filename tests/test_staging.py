"""K-WRT-H15 / H16 人物摆位判定（tools/script_rsi/staging.py）：接触动作、正面直立对镜头、双人紧景别。不调网关、不写真实数据。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ST():
    spec = importlib.util.spec_from_file_location("staging", ROOT / "tools" / "script_rsi" / "staging.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_contact_required_for_each_on_screen_person(ST):
    img = "中景，侧面机位，林晚坐在吧台高脚凳上，林晚的右手握着酒杯，顾沉站在她身后，顾沉的视线落在林晚的背上"
    r = ST.check_shot(img, [("林晚", "在画"), ("顾沉", "在画")])
    assert not r["ok"] and r["no_contact"] == ["顾沉"] and not r["tight_pair"]
    r2 = ST.check_shot(img.replace("顾沉站在她身后", "顾沉的手扶着吧台站在她身后"), [("林晚", "在画"), ("顾沉", "在画")])
    assert r2["ok"]


def test_partial_person_not_judged(ST):
    r = ST.check_shot("近景，平视机位，林晚靠在门框上，林晚的视线落在门外，顾沉的肩在画面左前景虚化", [("林晚", "在画"), ("顾沉", "局部")])
    assert r["ok"]


def test_frontal_upright_flagged(ST):
    r = ST.check_shot("全景，平视机位，林晚正面站在画面中央看向镜头，林晚的手拿着包", [("林晚", "在画")])
    assert r["frontal"] == ["林晚"] and not r["ok"]


def test_tight_pair_flagged_but_medium_ok(ST):
    cast = [("林晚", "在画"), ("顾沉", "在画")]
    img = "中近景，过肩机位，林晚靠在墙上，顾沉的手撑在墙上"
    assert ST.check_shot(img, cast)["tight_pair"] == ["林晚", "顾沉"]
    assert ST.check_shot(img.replace("中近景", "中景"), cast)["ok"]
    assert ST.check_shot("近景，林晚靠在墙上", [("林晚", "在画"), ("顾沉", "局部")])["ok"]


def test_why_names_rules(ST):
    r = ST.check_shot("近景，林晚站着，顾沉站着", [("林晚", "在画"), ("顾沉", "在画")])
    w = ST.why(r)
    assert "K-WRT-H15" in w and "K-WRT-H16" in w


def test_rules_registered():
    t = (ROOT / "knowledge/rules/writer_hollywood.yaml").read_text(encoding="utf-8")
    assert "id: K-WRT-H15" in t and "id: K-WRT-H16" in t and "tests/test_staging.py" in t
    af = (ROOT / "tools/script_rsi/autoflow.py").read_text(encoding="utf-8")
    ra = (ROOT / "tools/script_rsi/rubric_audit.py").read_text(encoding="utf-8")
    assert "staging.py" in af and "staging.py" in ra
