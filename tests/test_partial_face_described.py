"""总调度 11-01 决定 1（ep03-S6）：cast=局部但 img 写到脸 / 头发 → (a) 系统挂身份脸、Q1 按其阈值判；(b) P4 校验 QW-CH6 警告。"""
import json
import sys
from pathlib import Path

import pytest

from ns_agent import asset_refs as AR
from ns_agent.gen_contract import postflight

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("img,name,want", [
    ("近景，林晚侧脸朝镜；顾沉在前景虚化，黑色短发向后梳，白衬衫袖口卷起", "顾沉", True),          # ep03-S6
    ("陈宇，嘴唇半张，暖黄顶灯从上方偏前落下", "陈宇", True),
    ("顾沉的手掌贴在她耳侧的发上，视线看向她的眼睛", "顾沉", False),                            # 代词后是她的
    ("顾沉的手从画面右侧伸入；顾沉公寓客厅，光沿耳廓与发丝边缘勾出细线", "顾沉", False),           # 名字当地点
    ("林晚侧腰与腰线占画面中央，黑色漆皮束腰，镜面冷光，真实皮肤质感，自然的轻微不对称，眼睛为真实人眼大小", "林晚", False),
])
def test_face_described(img, name, want):
    assert AR.face_described(name, img, ["林晚", "顾沉", "陈宇"]) is want


FIXTURE = ROOT / "tests/fixtures/reflock/ep03_s6_before_repair.json"


def test_ep03_s6_original_flagged():
    """固定夹具：05:59 写作返修之前的 ep03-S6 原文（cast 局部｜左手，img 写“黑色短发向后梳”）→ 判为写到脸 / 头发"""
    sh = json.loads(FIXTURE.read_text(encoding="utf-8"))
    on = [n for n, _ in AR.cast_on_screen(sh)]
    assert ("顾沉", "局部") in AR.cast_on_screen(sh) and AR.face_described("顾沉", sh["img_prompt"], on)


def test_live_script_validator_consistent():
    """现行 P4 稿（随写作返修变化）：不断言内容，只断言系统前后一致——每一镜 QW-CH6 报出的人 == asset_refs.face_described 判出的人"""
    sys.path.insert(0, str(ROOT / "tools"))
    import validate_qwen_script as V
    md = ROOT / "data/pipeline/runs/series10_v1/ep03/P4_ep03.md"
    if not md.exists():
        pytest.skip("没有 ep03 P4 稿")
    imp = V.import_script(md)
    rep = V.validate(md)
    by = {s["index"]: s for e in rep["episodes"] for s in e["shots"]}
    for sh in imp.episodes[0].shots:
        on = [n for n, _ in AR.cast_on_screen(sh)]
        want = sorted(n for n, pr in AR.cast_on_screen(sh) if pr == "局部" and AR.face_described(n, sh.img_prompt, on))
        got = sorted({n for i in by[sh.index]["issues"] if i["rule_id"] == "QW-CH6"
                      for n in i["detail"].split("：", 1)[-1].split("、")})
        assert got == want, (sh.index, got, want)


def test_q1_described_partial_uses_identity_threshold():
    rec = {"size": "近景", "subject": None, "zones": ["face"], "primary": "lin_wan", "slots": [], "missing": [],
           "characters": [{"character": "lin_wan"}, {"character": "gu_chen", "presence": "局部", "face_described": True}]}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}, {"name": "顾沉", "presence": "局部"}]}
    lw = {"h_ratio": 0.15, "bbox": [0, 0, 10, 10], "sims": {"lin_wan": 0.83, "gu_chen": 0.05}}
    loc = {"Q2": [], "Q4": None, "Q7": None}

    def q1(gu):
        r = {"faces": [lw, {"h_ratio": 0.2, "bbox": [20, 0, 30, 10], "sims": {"lin_wan": 0.02, "gu_chen": gu}}], "text": []}
        return next(i for i in postflight.evaluate("x.png", req, remote=r, local=loc).items if i.id == "Q1")
    assert q1(0.66).status == "pass"
    assert q1(0.50).status == "fail"                     # 过 recognize_floor 但不过他自己的 0.6
    only_lw = {"faces": [lw], "text": []}                # 只写到头发、脸没入画：不要求出脸
    assert next(i for i in postflight.evaluate("x.png", req, remote=only_lw, local=loc).items if i.id == "Q1").status == "pass"


def test_p4_lint_warns_partial_face():
    sys.path.insert(0, str(ROOT / "tools"))
    import validate_qwen_script as V
    assert V.RULES["QW-CH6"][0] == "warn"
    src = (ROOT / "tools/validate_qwen_script.py").read_text(encoding="utf-8")
    assert "face_described(c.name, img, on_names)" in src


def test_shoe_trigger_does_not_override_face_closeup():
    """REFLOCK 11-01（ep02-S1）：脸部特写里带鞋触发词 hh12clear——主体判定与编译器一致：仍是脸部特写，不是下半身"""
    from ns_agent import framing as FR
    img = "hh12clear，特写，低机位，林晚穿米白衬衫，透明12cm细高跟的鞋尖踩在电梯地板上，她侧身站立，四分之三侧脸朝左，垂眼看向地板"
    assert FR.closeup_subject(img, "特写") == "face"
    assert FR.lower_focus(img) is False and FR.lower_focus(img, kept_triggers=["hh12clear"]) is False
    assert AR.visible_zones(img, ["hh12clear"])[1] == "face"
