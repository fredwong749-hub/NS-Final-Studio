"""判词自洽检查（PS-MASTER 11-04）：用真实判词原文做夹具——结论与证据矛盾 → 作废重问，重问仍矛盾 → untested，不算 fail。"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/autopilot", "tools/pipeline", ""):
    sys.path.insert(0, str(ROOT / p))

from ns_agent.vqa import client as VC  # noqa: E402
from ns_agent.vqa import contract as VQ  # noqa: E402
from ns_agent.vqa import selfcheck as SC  # noqa: E402

CAST = [{"name": "卓琳", "x": "左"}, {"name": "唐瑶", "x": "右"}]
S16_V2 = "右眼看向右下鞋尖，非直视镜头"
S8_LAST = "瞳孔偏向画面右侧，未直视镜头"
S15_V1 = "原文说唐瑶在左、卓琳在右，画面唐瑶在右、卓琳在左，站位不符"
S15_V2 = "原文说唐瑶在右、卓琳在左，画面唐瑶在左、卓琳在右"
S9_V13 = "脚上穿的是黑色短靴，与造型 A 中‘黑色短靴’描述不符"
S9_ITEM = "江予白的穿着与造型 A 一致（只核对画面里看得到的部分）：黑色短靴；米色风衣"


def test_gaze_negated_direct_look_is_contradiction():
    for e in (S16_V2, S8_LAST, "看向右下，并非直视镜头", "没有看镜头，看向窗外"):
        assert VQ.eye_contradiction({"s": "defect", "e": e}), e
    assert not VQ.eye_contradiction({"s": "defect", "e": "两只眼睛直视镜头，瞳孔居中"})
    assert not VQ.eye_contradiction({"s": "ok", "e": S16_V2})
    assert VQ.eye_contradiction({"s": "ok", "e": "眼睛正对镜头"})


def test_gaze_sanitize_marks_untested_and_reasks_both_frames(monkeypatch):
    for e in (S16_V2, S8_LAST):                              # S16 首帧 / S8 尾帧
        v = {"checks": {"eye_contact": {"s": "defect", "e": e}}, "defects": ["eye_contact"], "unsure": []}
        VQ.sanitize(v)
        assert v["checks"]["eye_contact"]["s"] == "untested" and v["contradiction"] == ["eye_contact"] and v["defects"] == []
        monkeypatch.setattr(VC, "generate", lambda req, **k: {"text": '{"gaze": "没看镜头", "e": "瞳孔朝向右下方鞋尖"}'})
        VQ.reask_eye(v, "x.png")
        assert v["checks"]["eye_contact"]["s"] == "ok" and not v["contradiction"]          # 重问自洽 → 好图放行
    v = {"checks": {"eye_contact": {"s": "defect", "e": S16_V2}}, "defects": ["eye_contact"], "unsure": []}
    VQ.sanitize(v)
    monkeypatch.setattr(VC, "generate", lambda req, **k: {"text": '{"gaze": "看镜头", "e": "眼睛没有看镜头"}'})   # 重问仍矛盾
    VQ.reask_eye(v, "x.png")
    assert v["contradiction"] == ["eye_contact"] and v["checks"]["eye_contact"]["s"] == "untested"
    st, _, _ = VQ.q9(v)
    assert st == "untested"                                                              # 不算 fail


def test_position_claim_vs_cast():
    assert SC.truth_positions(CAST) == {"卓琳": "左", "唐瑶": "右"}
    assert "判词称原文" in SC.position_contradiction(S15_V1, CAST)       # v1：把原文读反 → 作废
    assert SC.position_contradiction(S15_V2, CAST) is None                    # v2：原文复述对了，画面侧是真判断，不作废
    assert SC.position_contradiction("原文说唐瑶在右，画面唐瑶在右，站位不符", CAST)  # 原文与画面同侧却判不符
    assert SC.position_contradiction(S15_V1, None) is None and SC.position_contradiction(S15_V1, [{"name": "唐瑶", "x": "中"}]) is None


def test_outfit_contradiction_s9_v13():
    assert SC.outfit_contradiction(S9_V13, S9_ITEM)
    assert not SC.outfit_contradiction("脚上穿的是白色短靴，与黑色短靴不符", S9_ITEM)
    assert not SC.outfit_contradiction("没有看到鞋", S9_ITEM)


def _bundle(monkeypatch, first, reask, cast=CAST, items=None):
    AC = importlib.import_module("tools.pipeline.asset_checks")
    items = items or [S9_ITEM, "唐瑶在右、卓琳在左"]
    calls = []

    def ask(q, image, label, px=1400000):
        calls.append(label)
        return {"text": first if label == "asset_bundle" else reask}
    monkeypatch.setattr(AC, "_ask", ask)
    return AC.bundle_check("x.png", items, True, cast=cast), calls


def test_bundle_shoe_contradiction_reask_ok(monkeypatch):
    first = f"1. 不符合，{S9_V13}\n2. 符合，站位一致\n年龄：成年\n文字：无\n总结：有不符合"
    b, calls = _bundle(monkeypatch, first, "1. 符合，黑色短靴一致")
    assert calls == ["asset_bundle", "asset_bundle_reask"] and b["status"] == "pass" and b["items"][0]["ok"]


def test_bundle_shoe_contradiction_stays_untested(monkeypatch):
    first = f"1. 不符合，{S9_V13}\n2. 符合，站位一致\n年龄：成年\n文字：无\n总结：有不符合"
    b, _ = _bundle(monkeypatch, first, f"1. 不符合，{S9_V13}")
    assert b["status"] == "untested" and b["items"][0].get("untested") and not b["items"][0]["ok"]
    AC = importlib.import_module("ns_agent.gen_contract.accept")
    lab, _ = AC.judge_bundle({"items": []}, {"status": "pass"}, b)
    assert lab["prompt"] == "untested"
    assert AC.verdict({"items": []}, {**lab, "identity": "pass", "outfit": "pass", "vlm_review": "pass", "age": "pass", "ocr": "pass"}, b)[0] == "retry"


def test_bundle_position_row_reasked_with_truth(monkeypatch):
    first = f"1. 符合\n2. 不符合，{S15_V1}\n年龄：成年\n文字：无\n总结：有不符合"
    b, calls = _bundle(monkeypatch, first, "1. 符合，卓琳在左、唐瑶在右")
    assert calls[-1] == "asset_bundle_reask" and b["status"] == "pass"


def test_bundle_genuine_fail_untouched(monkeypatch):
    first = "1. 不符合，脚上穿的是白色高跟鞋\n2. 符合\n年龄：成年\n文字：无\n总结：有不符合"
    b, calls = _bundle(monkeypatch, first, "")
    assert calls == ["asset_bundle"] and b["status"] == "fail"


def test_q10_position_selfcheck(monkeypatch):
    VA = importlib.import_module("tools.vqa.accept")
    d = {"people_count": "符合", "positions": "不符", "e": S15_V1}
    good = lambda req, **k: {"text": '{"positions": "符合", "e": "卓琳在左、唐瑶在右"}'}      # noqa: E731
    d2, undecided = VA.position_selfcheck("ep01-S15", "x.png", d, cast=CAST, ask=good)
    assert d2["positions"] == "符合" and not undecided
    bad = lambda req, **k: {"text": '{"positions": "不符", "e": "原文说唐瑶在左，画面唐瑶在右"}'}   # noqa: E731
    d3, undecided = VA.position_selfcheck("ep01-S15", "x.png", d, cast=CAST, ask=bad)
    assert undecided and d3["positions"] == "不符"
    d4, undecided = VA.position_selfcheck("ep01-S15", "x.png", {"positions": "不符", "e": S15_V2}, cast=CAST, ask=bad)
    assert not undecided and d4["e"] == S15_V2                                   # 原文复述对 = 不重问
    from ns_agent.vqa import continuity as CT
    monkeypatch.setattr(CT, "shot_rec", lambda sid: {"img_prompt": "x"})
    monkeypatch.setattr(VC, "generate", lambda req, **k: {"text": json.dumps({"people_count": "符合", "positions": "不符", "e": S15_V1, "action": "符合", "scene": "符合"})})
    monkeypatch.setattr(VA, "position_selfcheck", lambda sid, image, d, **k: ({**d, "reask": {}}, True))
    r = VA.prompt_check("ep01-S15", "x.png")
    assert r["status"] == "untested" and r["infra"]                              # 不算 fail


def test_v1_names_removed_from_rule_text():
    cfg = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    zh = " ".join(str(c.get("zh")) for c in {**cfg["checks"], **(cfg.get("video_checks") or {})}.values())
    assert not any(n in zh for n in ("林晚", "顾沉", "lin_wan", "gu_chen"))
    for f in (ROOT / "config/prompts").glob("vqa_*.md"):
        assert not any(n in f.read_text(encoding="utf-8") for n in ("林晚", "顾沉"))
