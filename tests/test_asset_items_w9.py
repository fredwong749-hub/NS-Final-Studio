"""W9 ASSET-ITEMS（11-03）：单品 / 饰品作业从根上修——物件图规格、按 kind 分流的 Q9 口径、单品编译不带人像段、拒因写人话、
旧规格失败作业按新规则重排、“无”/ 项目方编号不出图。全部用临时目录，不碰真实数据 / GPU。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/api", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import asset_checks as AC  # noqa: E402
import asset_jobs as AJ  # noqa: E402
import asset_worker as AW  # noqa: E402


def _q9(defects, status="fail"):
    return {"items": [{"id": "Q9", "title": "本地看图复核", "status": status, "detail": "x", "evidence": {"defects": defects, "model": "m"}}]}


def _st(post, stage):
    return next(i for i in AC.q9_asset(post, stage)["items"] if i["id"] == "Q9")


# ------------------------------------------------------------------ (a) 规格
@pytest.mark.parametrize("label,slot,must,must_not", [
    ("右手腕缠两圈的黑色相机皮带", "accessory", ["黑色相机皮带", "颜色：黑色", "纯白"], ["右手腕", "缠两圈"]),
    ("鲜红色长指甲", "nails", ["穿戴甲片", "鲜红色", "没有手"], []),
    ("金色细链手包", "accessory", ["金色细链手包", "颜色：金色"], []),
    ("驼色皮夹克、黑色圆领T恤、黑色工装裤", "outfit", ["平铺", "没有人穿", "没有人台"], []),
    ("黑色丝绒细高跟", "shoes", ["一双黑色丝绒细高跟", "材质：丝绒"], []),
])
def test_item_spec_is_an_object_shot(label, slot, must, must_not):
    f = AJ.item_render_fields(label, slot)
    for w in must:
        assert w in f["img"], (w, f["img"])
    for w in must_not:
        assert w not in f["img"]
    assert "没有人脸" in f["img"] and "没有模特" in f["img"]
    assert "品牌" not in f["img"] and "品牌" not in f["negative"]          # preflight I13（K-REN-959）
    assert f["item_rule"] == AJ.ITEM_RULE and "写实空镜摄影" in f["suffix"]
    assert "人台" in f["negative"] and "手指" in f["negative"]


def test_no_item_labels_are_not_rendered():
    assert AJ.no_item("无") and AJ.no_item("SH1 或 SH2") and AJ.no_item("SH2")
    assert AJ.no_item("金色细链手包") is None and AJ.no_item("黑色短靴") is None
    gap = {"kind": "item", "who": "祁念", "what": "祁念 造型O4 的饰品“无”没有图"}
    story = {"characters": [{"id": "lead_f", "name": "祁念"}]}
    assert AJ.plan_from_gap(gap, story, [], 1) is None
    gap2 = {"kind": "item", "who": "祁念", "what": "祁念 造型O4 的鞋“SH1 或 SH2”没有图"}
    assert AJ.plan_from_gap(gap2, story, [], 1) is None


def test_item_checks_are_object_contract():
    spec = {"label": "金色细链手包", "slot": "accessory", **AJ.item_render_fields("金色细链手包", "accessory")}
    its, person = AW.vlm_items({"kind": "item", "spec": spec})
    assert person is False
    assert any("没有人" in x and "人脸" in x for x in its)
    assert any("只有这一样东西" in x and "金色细链手包" in x for x in its)
    assert any("颜色是金色" in x for x in its)
    suit = {"label": "驼色皮夹克、黑色圆领T恤、黑色工装裤", "slot": "outfit", **AJ.item_render_fields("驼色皮夹克、黑色圆领T恤、黑色工装裤", "outfit")}
    sits = AW.vlm_items({"kind": "item", "spec": suit})[0]
    assert any("每一件" in x and "黑色工装裤" in x for x in sits) and not any("材质看起来是皮" in x for x in sits)
    assert any("纯白" in x and "文字" in x for x in its)
    nails = {"label": "鲜红色长指甲", "slot": "nails", **AJ.item_render_fields("鲜红色长指甲", "nails")}
    assert any("穿戴甲片" in x for x in AW.vlm_items({"kind": "item", "spec": nails})[0])


# ------------------------------------------------------------------ (b) 契约按 kind 分流
def test_q9_item_drops_person_only_defects_but_keeps_object_ones():
    assert _st(_q9(["eye_contact", "framing_mismatch"]), "item")["status"] == "pass"      # 一只鞋没有“看镜头 / 景别”
    assert _st(_q9(["eye_contact"]), "scene")["status"] == "fail"                          # 别的 kind 不变
    assert _st(_q9(["framing_mismatch"]), "sheet")["status"] == "fail"
    assert _st(_q9(["extra_person"]), "item")["status"] == "pass"                          # 由物件契约“画面里没有人”兜（更严）
    assert _st(_q9(["extra_person"]), "scene")["status"] == "fail"
    for d in ("brand_logo", "underage_look"):                                              # 物件图相关的 blocking 照旧拦
        q = _st(_q9(["eye_contact", d]), "item")
        assert q["status"] == "fail" and d in q["detail"], d
    assert "品牌字母或 logo" in _st(_q9(["brand_logo"]), "item")["detail"]                 # 缺陷写中文名
    un = _q9([], "untested")
    un["items"][0]["evidence"]["contradiction"] = ["eye_contact"]
    assert _st(un, "item")["status"] == "pass"                                              # 只在不判项上矛盾 → 按其余重判
    un2 = _q9(["brand_logo"], "untested")
    un2["items"][0]["evidence"]["contradiction"] = ["brand_logo"]
    assert _st(un2, "item")["status"] == "untested"


# ------------------------------------------------------------------ (c) 编译：单品不带人像 / 镜头语言段
def test_item_compiles_without_person_paragraph(monkeypatch):
    seen = {}

    class FakeFJ:
        @staticmethod
        def build_first(run, ep, shot, g, mode="shot"):
            seen["mode"] = mode
            return {"prompt": "单品物件图：x，光线：影棚均匀柔光，写实空镜摄影，画面中没有任何人物", "refs": []}

        @staticmethod
        def trace_of(jc):
            return {}

    import types
    import ns_agent
    monkeypatch.setitem(sys.modules, "ns_agent.frame_job", FakeFJ)
    monkeypatch.setattr(ns_agent, "frame_job", FakeFJ, raising=False)
    monkeypatch.setenv("NS_RUN", "demo")
    monkeypatch.setattr(AW, "script_for", lambda job: types.SimpleNamespace(episodes=[types.SimpleNamespace(shots=[None])], globals=None))
    monkeypatch.setattr(AW, "empty_suffix", lambda jc, spec: jc)
    job = {"kind": "item", "run": "demo", "spec": AJ.item_render_fields("黑色短靴", "shoes")}
    AW._compile(job)
    assert seen["mode"] == "sheet"                                   # 不加镜头语言 / 融合句 / 视线句
    FakeFJ.build_first = staticmethod(lambda *a, **k: {"prompt": "x，人物和场景是同一次拍摄：环境光染到皮肤和衣服上", "refs": []})
    with pytest.raises(RuntimeError, match="人像"):
        AW._compile(job)


# ------------------------------------------------------------------ 卡点写人话
def test_reject_reason_is_human_readable():
    r = {"label": {"q9": "fail", "prompt_vlm": "fail", "ocr": "fail", "age": "na"},
         "postflight": AC.q9_asset(_q9(["brand_logo"]), "item"),
         "vlm": {"questions": ["画面里没有人、没有模特", "画面主体只有这一样东西：金色细链手包"],
                 "items": [{"n": 1, "ok": False, "text": "不符合，画面里有模特"}, {"n": 2, "ok": True, "text": "符合"}],
                 "ocr": {"status": "fail", "text": "SCHU"}}}
    s = AW.reject_reason(r)
    assert "prompt_vlm=fail（看图逐条核对）" in s and "“画面里没有人、没有模特”→ 不符合，画面里有模特" in s
    assert "品牌字母或 logo" in s and "读到了字：SCHU" in s
    summ = AW.reject_summary([r, r])
    assert summ.startswith("2 张候选里") and "不过 2 张" in summ


# ------------------------------------------------------------------ 旧作业按新规则收拾
def _job(root, jid, label, slot, state="failed", **kw):
    j = {"schema": AJ.SCHEMA, "id": jid, "run": "demo", "episode": 1, "episodes": [1], "kind": "item", "state": state, "attempts": 2,
         "spec": {"cid": "c", "name": "N", "look": "A", "label": label, "slot": slot, "img": f"单品产品图，纯白背景，只拍这一件：{label}"},
         "log": [], **kw}
    p = root / "data" / "pipeline" / "asset_jobs" / "demo" / f"{jid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return p


def test_refresh_items_requeues_old_rule_and_closes_no_item(tmp_path, monkeypatch):
    monkeypatch.setattr(AJ, "guard_run", lambda root, run: None)
    p1 = _job(tmp_path, "item-c-A-acc1", "右手腕缠两圈的黑色相机皮带", "accessory")
    p2 = _job(tmp_path, "item-c-O4-饰品", "无", "饰品")
    p3 = _job(tmp_path, "item-c-O4-鞋", "SH1 或 SH2", "鞋", state="pending")
    p4 = _job(tmp_path, "item-c-A-shoes1", "黑色短靴", "shoes", state="awaiting_pick")
    out = AJ.refresh_items(tmp_path, "demo")
    assert out["requeued"] == ["item-c-A-acc1"] and sorted(out["closed"]) == ["item-c-O4-鞋", "item-c-O4-饰品"]
    j1 = json.loads(p1.read_text(encoding="utf-8"))
    assert j1["state"] == "pending" and j1["attempts"] == 0 and j1["spec"]["item_rule"] == AJ.ITEM_RULE
    assert "右手腕" not in j1["spec"]["img"] and "黑色相机皮带" in j1["spec"]["img"]
    j2 = json.loads(p2.read_text(encoding="utf-8"))
    assert j2["state"] == "done" and "没有这件单品" in j2["result"]["closed_reason"]
    assert "项目方" in json.loads(p3.read_text(encoding="utf-8"))["result"]["closed_reason"]
    assert json.loads(p4.read_text(encoding="utf-8"))["state"] == "awaiting_pick"
    assert AJ.refresh_items(tmp_path, "demo") == {"closed": [], "requeued": [], "respec": []}   # 只重排一次
