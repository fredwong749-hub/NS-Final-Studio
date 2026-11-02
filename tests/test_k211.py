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
    assert RC.mirror_hand_checks([S(1, 10)], [b])[2][0]          # 镜长 > 8 秒不判
