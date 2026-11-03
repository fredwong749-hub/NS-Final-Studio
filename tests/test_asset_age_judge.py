"""W6b 11-03（A6 审计 P1-A）：年龄判词器失败关闭。反例集 = A6 审计表（AUDIT_A6_W6_ASSET_SHEET_20261103.md §1）全部条目 + 任务单点名的三句。
每条写明：W6 版（取首个判词）的结果 → 本版结果。W6 版在本文件里按原写法复原，用来证明表里的“旧”列不是凭空写的。"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import asset_checks as AC  # noqa: E402

_W6_RE = re.compile(r"像未成年|未成年|无人物|成年")


def w6_age_status(t: str) -> str:
    """W6 版（11-03 05:00 前）原样复原：取第一个出现的判词"""
    t = (t or "").strip()
    if not t:
        return "untested"
    m = _W6_RE.search(t)
    if not m:
        return "fail"
    return "na" if m.group(0) == "无人物" else ("pass" if m.group(0) == "成年" else "fail")


# (回答, W6 旧结果, 新结果)
CASES = [
    # —— W6 修好的“成年不在句首也算”：保留 pass
    ("画面里的人看起来是“成年”，因面部成熟度、体态和妆容均符合成年人特征。", "pass", "pass"),
    ("年龄：成年", "pass", "pass"),
    ("成年，人物面部与身形比例符合成年女性特征，无未成年视觉元素。", "pass", "pass"),   # s1101 原话
    ("成年，人物面部与身形比例符合成年女性特征。", "pass", "pass"),                       # s1102 原话
    ("成年", "pass", "pass"),
    ("成年女性，约 25 岁，不像未成年", "pass", "pass"),
    # —— A6 判为不合理的 fail→pass 翻转：本版全部 fail
    ("她是成年人；旁边的孩子未成年", "pass", "fail"),
    ("这个人是成年人，但另一位像未成年", "pass", "fail"),
    ("不像成年人，更像未成年", "pass", "fail"),
    ("不是成年人", "pass", "fail"),
    ("非成年", "pass", "fail"),
    ("大概率成年，但也可能是未成年", "pass", "fail"),
    # —— A6 列出的“新旧都放过”：本版 fail
    ("成年？不确定", "pass", "fail"),
    ("成年女性，约 17 岁", "pass", "fail"),
    ("成年，但旁边那位看起来未成年", "pass", "fail"),
    # —— 一直正确的：保持
    ("像未成年", "fail", "fail"),
    ("看起来像未成年但穿着成熟", "fail", "fail"),
    ("未成年", "fail", "fail"),
    ("未成年，另一位成年", "fail", "fail"),
    ("没有人", "fail", "fail"),
    ("adult", "fail", "fail"),
    ("minor", "fail", "fail"),
    ("不确定", "fail", "fail"),
    ("约15岁", "fail", "fail"),
    ("15岁左右的少女", "fail", "fail"),
    ("像未成年，脸型稚嫩", "fail", "fail"),
    ("看起来是未成年人", "fail", "fail"),
    ("无人物", "na", "na"),
    ("", "untested", "untested"),
    # —— 补充的失败关闭线索
    ("成年，但脸有些稚气", "pass", "fail"),
    ("成年 teen look", "pass", "fail"),
    ("成年，十六岁左右", "pass", "fail"),
    ("看起来并非成年", "pass", "fail"),
    ("成年，穿着校服", "pass", "fail"),
    ("无人物，背景里有成年人的影子", "na", "fail"),
    ("成年女性，非常成熟", "pass", "pass"),
    ("成年人，eighteen 以上", "pass", "pass"),
    # —— W6c+（A6b 第 23 轮 P2：新判词器还放过的 4 句 + 同类）：全部 fail
    ("不能确定是否成年", "pass", "fail"),
    ("成年，但未必", "pass", "fail"),
    ("成年，八岁", "pass", "fail"),
    ("成年，七八岁左右", "pass", "fail"),
    ("成年，十七八岁", "pass", "fail"),
    ("成年，十几岁", "pass", "fail"),
    ("成年，不一定", "pass", "fail"),
    ("成年，没法判断", "pass", "fail"),
    ("成年，不好判断", "pass", "fail"),
    # —— A6b 列为“pass 且合理”的：保持 pass
    ("成年，18岁", "pass", "pass"),
    ("成年，十八岁左右", "pass", "pass"),
    ("成年，二十出头", "pass", "pass"),
    ("成年，二十几岁", "pass", "pass"),
    ("成年，无未成年视觉元素，无儿童", "pass", "pass"),
    ("成年，没有任何未成年迹象，年龄约20岁", "pass", "pass"),
    ("成年，1.8 米高", "pass", "pass"),
    ("成年，1998年生", "pass", "pass"),
    ("成年，不算年轻", "pass", "pass"),
    ("成年女性，没有稚气", "pass", "pass"),
]


@pytest.mark.parametrize("text,old,new", CASES, ids=[c[0][:20] or "<空>" for c in CASES])
def test_age_judge_counterexamples(text, old, new):
    assert w6_age_status(text) == old
    assert AC._age_status(text) == new


def test_parse_bundle_age_line_uses_new_judge():
    p = AC.parse_bundle("1. 符合，单人\n年龄：她是成年人；旁边的孩子未成年\n文字：无\n总结：全部符合", 1)
    assert p["age"]["status"] == "fail"
    p = AC.parse_bundle("1. 符合，单人\n年龄：成年，人物面部与身形比例符合成年女性特征，无未成年视觉元素。\n文字：无\n总结：全部符合", 1)
    assert p["age"]["status"] == "pass"


def test_age_check_judges_whole_answer_not_first_line(monkeypatch):
    monkeypatch.setattr(AC, "_ask", lambda *a, **k: {"text": "成年\n她看起来约16岁"})
    assert AC.age_check("x.png")["status"] == "fail"
    monkeypatch.setattr(AC, "_ask", lambda *a, **k: {"text": "成年\n面部与体态均为成年女性特征"})
    assert AC.age_check("x.png")["status"] == "pass"


# ------------------------------------------------------------------ W6c+（A6b P2）：生产 bundle 路径按整段回答判年龄
def test_bundle_age_judges_continuation_line():
    """“年龄：成年⏎理由：约 16 岁，穿校服”——原来只取“年龄”那一行 → pass；现在续行一起判 → fail"""
    t = "1. 符合，单人\n年龄：成年\n理由：约 16 岁，穿校服\n文字：无\n总结：全部符合"
    assert AC.parse_bundle(t, 1)["age"]["status"] == "fail"
    assert AC.parse_bundle(t, 1)["age"]["status"] == AC._age_status("年龄：成年\n理由：约 16 岁，穿校服")   # 与 age_check 同口径
    t2 = "1. 符合，单人\n年龄：成年\n理由：面部与体态均为成年女性特征\n文字：无\n总结：全部符合"
    assert AC.parse_bundle(t2, 1)["age"]["status"] == "pass"


def test_bundle_age_fails_on_minor_cue_anywhere_in_answer():
    """逐条核对行里说了“像未成年 / 16 岁”，年龄行却写成年 → 整段判 fail；核对行里的“可能”“？”不连坐年龄"""
    t = "1. 符合，单人\n2. 不符合，看起来像未成年\n年龄：成年\n文字：无\n总结：有不符合"
    assert AC.parse_bundle(t, 2)["age"]["status"] == "fail"
    t = "1. 符合，单人，约16岁\n年龄：成年\n文字：无\n总结：全部符合"
    assert AC.parse_bundle(t, 1)["age"]["status"] == "fail"
    t = "1. 不符合，背景可能有杂物？\n2. 符合，外观是成年人，不像未成年\n年龄：成年，面部成熟\n文字：无\n总结：有不符合"
    assert AC.parse_bundle(t, 2)["age"]["status"] == "pass"
    assert AC.parse_bundle("1. 符合\n文字：无\n总结：全部符合", 1)["age"]["status"] == "untested"     # 没答年龄 = 不算过
