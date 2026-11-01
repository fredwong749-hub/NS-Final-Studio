"""fredw-92/CHR：定妆候选模板（人物文字领头、中文取景、保留摄影意图）+ 资产“作废候选”标记。"""
from __future__ import annotations

import json
import re

import pytest

from tests.test_ref_switch_w5 import FakeComfy, _wait, env, script  # noqa: F401  (fixtures)
from ns_api import asset_edit as AED
from ns_api import jobs as J
from ns_render import makeup_template as MT
from ns_render.refs import ROLE_FACE

LOCK = "34岁成年男性CEO，黑色高定衬衫，成熟克制英俊"   # 现有角色锁原文（测试只当不透明字符串用）


def _ascii_letters(s: str) -> int:
    return len(re.findall(r"[A-Za-z]", s))


@pytest.mark.parametrize("view", list(MT.VIEWS))
def test_person_text_leads_and_framing_is_chinese(view):
    p = MT.makeup_prompt(LOCK, "服装=黑色高定衬衫", view)
    assert p.startswith("人物：" + LOCK + "。")                  # 人物文字最前，原样
    assert p.index("造型：服装=黑色高定衬衫。") < p.index("定妆照·")
    frame = MT.VIEWS[view][1]
    # 取景模板基本是中文：英文字母只允许镜头参数 “mm” / “f”
    assert _ascii_letters(frame) <= 4, frame
    for en in ("head and shoulders", "front view", "lens", "studio backdrop", "No text"):
        assert en not in p


def test_photographic_intent_kept():
    front, half, full, turn = (MT.VIEWS[v][1] for v in ("front", "half", "full", "turn"))
    assert "85mm" in front and "f/8" in front and "头肩" in front and "毛孔" in front
    assert "50mm" in half and "f/8" in half and "腰部以上" in half
    assert "从头到脚" in full and "50mm" in full
    assert all(k in turn for k in ("正面", "侧面", "背面", "左边缘"))
    for f in (front, half, full, turn):
        assert "中灰" in f and "无水印" in f
    assert MT.view_size("turn") == (1344, 768) and MT.view_size("front") == (768, 1344)


def test_ref_line_after_person_text():
    p = MT.makeup_prompt(LOCK, "", "front", name="顾沉", ref_index=1)
    assert p.startswith("人物：" + LOCK)
    ref = ROLE_FACE.format(i=1, name="顾沉")
    assert ref in p and p.index(ref) > p.index(LOCK) and p.index(ref) < p.index("定妆照·")
    assert "造型：" not in p                                       # 没给造型就不写空的造型段


def test_empty_person_or_bad_view_rejected():
    with pytest.raises(ValueError):
        MT.makeup_prompt("  ", "x", "front")
    with pytest.raises(ValueError):
        MT.makeup_prompt(LOCK, "x", "side")


# ------------------------------------------------------------------ 作废候选

def _gen(c, fc, monkeypatch, label="候选·待复审 · ep02 定妆 正面肖像"):
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    r = c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "原话", "gpu": 0, "label": label, "seed": 3})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["state"] == "done", job
    return job["result"]


def test_void_gens_and_refs_keep_files(env, monkeypatch):
    c, store, root = env
    fc = FakeComfy()
    rec = _gen(c, fc, monkeypatch)
    ref = AED.add_ref(AED.resolve_asset(store, "lin_wan"), b"\x89PNG\r\n\x1a\nxx", ".png", "identity", "upload")
    quote = "全部作废，按新描述重出"
    # 项目方作废必须带原话
    r = c.post("/api/assets/lin_wan/void", json={"gen_ids": [rec["gen_id"]], "by": "owner"})
    assert r.status_code == 422
    r = c.post("/api/assets/lin_wan/void", json={"gen_ids": ["ag-nope"], "by": "owner", "owner_quote": quote})
    assert r.status_code == 404
    r = c.post("/api/assets/lin_wan/void", json={"gen_ids": [rec["gen_id"]], "ref_ids": [ref["ref_id"]],
                                                 "by": "owner", "owner_quote": quote, "reason": "测试"})
    assert r.status_code == 200, r.text
    g = r.json()["gens"][0]
    assert g["label"] == "作废候选 · ep02 定妆 正面肖像" and g["label_before"].startswith("候选·待复审")
    assert g["void"]["by"] == "owner" and g["void"]["owner_quote"] == quote
    # 文件不删
    assert (AED.A.ROOT / g["file"]).is_file() and (AED.A.ROOT / ref["file"]).is_file()
    # 资产详情里看得到
    d = c.get("/api/assets/lin_wan").json()
    assert next(x for x in d["gens"] if x["gen_id"] == rec["gen_id"])["void"]["owner_quote"] == quote
    assert next(x for x in d["refs"] if x["ref_id"] == ref["ref_id"])["void"]
    # 再作废一次：label 不叠加
    c.post("/api/assets/lin_wan/void", json={"gen_ids": [rec["gen_id"]], "by": "owner", "owner_quote": quote})
    gens = json.loads((AED.data_dir() / "asset_gens.json").read_text(encoding="utf-8"))["lin_wan"]
    assert next(x for x in gens if x["gen_id"] == rec["gen_id"])["label"] == "作废候选 · ep02 定妆 正面肖像"
    # 作废参考不能再用作生成参考
    r = c.post("/api/assets/lin_wan/gen-jobs", json={"prompt": "x", "refs": [{"ref_id": ref["ref_id"]}], "gpu": 0})
    assert r.status_code == 422 and "作废" in r.text
