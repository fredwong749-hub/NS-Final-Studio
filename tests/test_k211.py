"""K-WRT-211（fb-0001）：镜面 / 玻璃场景手不碰反光面；≤8 秒的镜手部动作 ≤2 拍（tools/script_rsi/rubric_code.mirror_hand_checks）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
RC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RC)


class S:
    def __init__(self, i, d=6):
        self.index, self.duration = i, d


def blk(i, img, beats, h3=""):
    return f"**镜{i}｜img**：{img}\n**场景**：sk_elevator｜轿厢\n**分拍**：{beats}\n```text\n{h3}\n```"


def test_hand_on_mirror_flagged_frame_ok():
    bad = blk(1, "中景，林晚靠在轿厢镜面墙前", "0–2秒｜林晚的掌心贴在镜面上｜视线=门；2–4秒｜林晚呼吸｜视线=门；4–6秒｜林晚抬眼｜视线=门")
    ok = blk(2, "中景，林晚站在全身镜前", "0–2秒｜林晚的左手扶着全身镜镜框｜视线=镜；2–4秒｜林晚呼吸｜视线=镜；4–6秒｜林晚抬眼｜视线=镜",
             "her hand resting on the mirror frame")
    en_bad = blk(3, "中景，林晚在镜面墙前", "0–2秒｜林晚呼吸｜视线=门；2–4秒｜林晚呼吸｜视线=门；4–6秒｜林晚抬眼｜视线=门",
                 "her palm pressed against the mirror")
    r = RC.mirror_hand_checks([S(1), S(2), S(3)], [bad, ok, en_bad])
    assert not r[1][0] and "镜1" in r[1][1] and "镜3" in r[1][1] and "镜2" not in r[1][1]


def test_busy_hands_over_two_beats():
    b = blk(1, "近景，林晚坐在桌前", "0–2秒｜林晚的手拿起纸｜视线=纸；2–4秒｜林晚的手把纸对折｜视线=纸；4–6秒｜林晚的手指攥紧纸角｜视线=门")
    r = RC.mirror_hand_checks([S(1)], [b])
    assert not r[2][0] and "3 拍" in r[2][1]
    assert "0–2秒" in r[2][1] and "4–6秒" in r[2][1] and "改法" in r[2][1]     # 失败原因带命中的拍 + 改法，写手包能定位
    assert RC.mirror_hand_checks([S(1, 10)], [b])[2][0]          # 镜长 > 8 秒不判


# K211-F 11-03：series10_v2 ep01 镜7 原文（V2 写法）——首帧状态 + 一处新动作 + 延续，只算 1 拍，不能判 3 拍
EP01_S7 = ("0–2秒｜江予白的右手已经把相机放进包里，捏着拉链头拉到一半停住，胸口起伏一次，视线钉在白幕中央的方向｜视线=画面左侧白幕中央的方向｜表情=眉头微收，嘴唇抿着｜反应=—｜运镜=固定｜声音=拉链拉到一半停住的一声；"
           "2–4秒｜他开口，只说两个字，嘴唇开合清楚，捏拉链头的手指收紧，说完嘴唇合上｜视线=画面左侧白幕中央的方向｜表情=嘴唇开合后合上，眼睑抬着｜反应=—｜运镜=固定｜声音=日光灯管的电流声；"
           "4–6秒｜他的左肘在灯架横杆上压得更实，喉头动了一下，视线钉在原处，捏着拉链头的手指到镜尾还在收紧｜视线=画面左侧白幕中央的方向｜表情=眉头微收，下颌绷紧｜反应=—｜运镜=固定｜声音=灯架横杆被肘压出的轻响")


def test_v2_state_and_continuation_are_not_new_hand_actions():
    b = blk(7, "近景，江予白站在环形灯架后", EP01_S7)
    r = RC.mirror_hand_checks([S(7)], [b])
    assert r[2][0], r[2][1]
    assert RC.hand_action("江予白的右手已经把相机放进包里，捏着拉链头拉到一半停住｜视线=门") is None     # 首帧状态
    assert RC.hand_action("捏着拉链头的手指到镜尾还在收紧｜视线=门") is None                           # 延续上一拍
    assert RC.hand_action("她没有抬手，手指一直搭在桌沿｜视线=门") is None                              # 否定 / 保持
    assert RC.hand_action("捏拉链头的手指收紧｜视线=门") == "手指收"                                     # 真的新动作
    # 三拍各起一个新动作照样判（“已经”只豁免写了它的那一拍）
    bad = blk(7, "近景", "0–2秒｜他的右手已经放下相机，左手拿起包｜视线=门；2–4秒｜他的手指收紧｜视线=门；4–6秒｜他的手把包推开｜视线=门")
    assert not RC.mirror_hand_checks([S(7)], [bad])[2][0]


def test_rule_enforced_and_wired():
    """总调度 11-02：K-WRT-211 不能是假强制——规则 enforced:true + check 指向本文件，生成索引一致，检查真的接进补丁环和导入闸门"""
    import json
    import yaml
    rules = yaml.safe_load((ROOT / "knowledge/rules/writer_series10.yaml").read_text(encoding="utf-8"))["rules"]
    r = next(x for x in rules if x["id"] == "K-WRT-211")
    assert r.get("enforced") is True and "tests/test_k211.py" in (r.get("check") or [])
    idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
    items = idx.get("rules") if isinstance(idx, dict) else idx
    g = next(x for x in items if x.get("id") == "K-WRT-211")
    assert g.get("enforced") is True
    af = (ROOT / "tools/script_rsi/autoflow.py").read_text(encoding="utf-8")
    ra = (ROOT / "tools/script_rsi/rubric_audit.py").read_text(encoding="utf-8")
    assert "mirror_hand_checks" in af and "mirror_hand_checks" in ra


def test_v2_clean_cut_run_enforces_v3_and_k211():
    """V2（CLEAN_CUT.json 的 run）不靠逐集 .v3 标记：补丁环和导入闸门整季开 v3 / K-WRT-211"""
    ag = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    ra = (ROOT / "tools/script_rsi/rubric_audit.py").read_text(encoding="utf-8")
    assert 'or clean_cut(run_dir)' in ag and '"CLEAN_CUT.json").exists()' in ra
