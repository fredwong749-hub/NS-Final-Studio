"""REVIEW-B 11-05（项目方“逐一再一次检查全部代码”）：对 sv-20261104-06 之后内容 / 编译 / 渲染 / 检查线代码的复审修补。
① L-196 硬闸：Q10 里看图人数闸（prompt.people_count，L-191）是人数硬项，不能被只记录；
② L-196 人数硬项时严格人数闸不随首帧档（base35 / turbo_previz）变；
③ staging._face_hidden 主语按小句里最靠前的人名（与 asset_refs.clause_subject 同口径）；
④ prompt_v2.rewrite_negations 不把 非常 / 别墅 / 无人 / 不远处 当否定句丢掉。"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages" / "schema"), str(ROOT / "services" / "agent")]

from ns_agent.gen_contract import blocking as BL  # noqa: E402
from ns_schema import prompt_v2 as PV  # noqa: E402
from tools.vqa import accept as ACC  # noqa: E402

CONF = {"blocking_items": ["Q1", "count", "text", "adult"]}


def _pf(*items):
    return {"ok": False, "blocking": [i["id"] for i in items], "items": list(items), "reasons": []}


def _q10(prompt_status="pass", why="", count_status="pass"):
    return {"id": "Q10", "status": "fail", "detail": "x",
            "evidence": {"identity": {"status": "pass"}, "outfit": {"status": "pass"},
                         "prompt": {"status": prompt_status, "why": why}, "count": {"status": count_status}}}


# ---------------------------------------------------------------- ① Q10 看图人数闸是硬项
def test_q10_vlm_people_count_fail_still_blocks():
    pf = BL.apply(_pf(_q10("fail", "people_count 不符：画面可见 4 人，分镜最多 3 人（在画 3）：多画了人", "deferred")), copy.deepcopy(CONF))
    assert pf["blocking"] == ["Q10"] and pf["ok"] is False
    it = pf["items"][0]
    assert it["status"] == "fail" and not it.get("record_only")


def test_q10_vlm_people_count_from_generic_bad_list_blocks():
    pf = BL.apply(_pf(_q10("fail", "people_count、positions不符：画面只有一个人", "deferred")), copy.deepcopy(CONF))
    assert pf["blocking"] == ["Q10"]


def test_q10_prompt_fail_without_people_is_record_only():
    pf = BL.apply(_pf(_q10("fail", "positions不符：祁念在左", "pass")), copy.deepcopy(CONF))
    assert pf["blocking"] == [] and pf["ok"] is True
    assert pf["items"][0]["status"] == "na" and pf["items"][0]["record_only"]


def test_q10_prompt_untested_is_not_hard():
    pf = BL.apply(_pf(_q10("untested", "本地看图没跑成", "pass")), copy.deepcopy(CONF))
    assert pf["blocking"] == []


def test_q10_count_not_in_hard_set_keeps_people_record_only():
    pf = BL.apply(_pf(_q10("fail", "people_count 不符：多画了人", "deferred")), {"blocking_items": ["Q1"]})
    assert pf["blocking"] == []


# ---------------------------------------------------------------- ② 严格人数闸跟 L-196 硬项走
def test_people_gate_on_when_count_is_hard(monkeypatch):
    from ns_agent import gen_contract as GCm
    monkeypatch.setattr(GCm, "cfg", lambda: {"blocking_items": ["Q1", "count"], "image_thresholds": {"Q10_accept": {}}})
    assert ACC.people_gate_on("series10_v1") is True       # v1 首帧档 preview，原来会关


def test_people_gate_follows_tier_when_count_not_hard(monkeypatch):
    from ns_agent import gen_contract as GCm
    from ns_agent import frame_job as FJ
    monkeypatch.setattr(GCm, "cfg", lambda: {"image_thresholds": {"Q10_accept": {}}})
    monkeypatch.setattr(FJ, "first_frame_tier", lambda project, force=None: ("preview", {}))
    assert ACC.people_gate_on("x") is False
    monkeypatch.setattr(FJ, "first_frame_tier", lambda project, force=None: ("base35", {"steps": 35}))
    assert ACC.people_gate_on("x") is True


def test_live_config_count_hard_means_strict_people_gate():
    from ns_agent.gen_contract import cfg as GC
    if "count" in (GC().get("blocking_items") or []):
        assert ACC.people_gate_on("series10_v2") is True


# ---------------------------------------------------------------- ③ staging 主语按位置
def _staging():
    spec = importlib.util.spec_from_file_location("staging", ROOT / "tools" / "script_rsi" / "staging.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_staging_face_hidden_subject_is_first_name_in_clause():
    ST = _staging()
    clauses = ["中景", "卓琳蹲在祁念左前、背对镜头", "祁念看着她"]
    names = ["祁念", "卓琳"]                       # cast 顺序把祁念排前面
    assert ST._face_hidden("卓琳", clauses, names) is True
    assert ST._face_hidden("祁念", clauses, names) is False


def test_staging_check_shot_ots_pair_counts_one_face():
    ST = _staging()
    img = "中近景，卓琳蹲在祁念左前、背对镜头，只以右肩与后脑入画；祁念坐在椅子上看着她的手"
    r = ST.check_shot(img, [("祁念", "在画"), ("卓琳", "在画")])
    assert r["tight_pair"] == []


# ---------------------------------------------------------------- ④ 否定句改写不过度匹配
def test_rewrite_negations_keeps_non_negation_words():
    s, negs = PV.rewrite_negations("非常安静的化妆间，别墅客厅，无人的走廊，不远处的落地灯，不锈钢台面")
    assert s == "非常安静的化妆间，别墅客厅，无人的走廊，不远处的落地灯，不锈钢台面" and negs == []


def test_rewrite_negations_still_drops_real_negations():
    s, negs = PV.rewrite_negations("没有正面补光，顶灯从上方打来，不看镜头，没有多余的人")
    assert "正面留在阴影里" in s and "不看镜头" not in s and negs == ["多余的人"]
