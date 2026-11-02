"""叙事质量代码判定 N01–N07（tools/script_rsi/narrative_code.py，K-WRT-N01–N07）。纯代码，不调网关。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def NC():
    spec = importlib.util.spec_from_file_location("narrative_code", ROOT / "tools" / "script_rsi" / "narrative_code.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class C:
    def __init__(self, name, presence="在画"):
        self.name, self.presence = name, presence


class D:
    def __init__(self, text):
        self.text = text


class S:
    def __init__(self, i, dur=6, dialogue=(), cast=("林晚",), vo=None):
        self.index, self.duration = i, dur
        self.dialogue = [D(t) for t in dialogue]
        self.cast = [C(n) for n in cast]
        self.voiceover = vo


def blk(i, size, beats):
    return f"**镜{i}｜img**：{size}，林晚\n**分拍**：" + "；".join(beats)


def test_empty_shot_and_scale_rhythm(NC):
    shots = [S(1), S(2), S(3)]
    blocks = [blk(1, "近景", ["0–2秒｜她推开门｜视线=门", "2–4秒｜抬手｜视线=桌", "4–6秒｜放下杯子｜视线=杯"]),
              blk(2, "近景", ["0–2秒｜保持不动｜视线=窗", "2–4秒｜静止｜视线=窗", "4–6秒｜凝视｜视线=窗"]),
              blk(3, "近景", ["0–2秒｜手机亮起｜视线=手机", "2–4秒｜拿起手机｜视线=屏幕", "4–6秒｜屏幕上出现一行字｜视线=屏幕"])]
    r = NC.episode_checks(shots, blocks)
    assert not r["N01"]["ok"] and "2" in r["N01"]["detail"]          # 镜2 空镜
    assert not r["N06"]["ok"]                                          # 连续 3 镜近景
    assert r["N03"]["ok"] and r["N07"]["ok"]
    assert r["N05"]["value"] == "reveal"


def test_subtext_and_turn(NC):
    shots = [S(1, dialogue=["我很生气"]), S(2, dialogue=["没事"]), S(3, cast=("林晚", "顾沉")), S(4)]
    blocks = [blk(1, "近景", ["0–2秒｜抬眼｜视线=他", "2–4秒｜手指收紧｜表情=抿嘴", "4–6秒｜转身｜视线=门"]),
              blk(2, "中景", ["0–2秒｜指尖在抖｜视线=杯", "2–4秒｜放下杯子｜表情=笑", "4–6秒｜起身｜视线=门"]),
              blk(3, "特写", ["0–2秒｜门被推开｜视线=门", "2–4秒｜他走进来｜视线=她", "4–6秒｜她站起｜视线=他"]),
              blk(4, "中景", ["0–2秒｜两人对视｜视线=他", "2–4秒｜她伸手｜视线=手", "4–6秒｜停在半空｜视线=手"])]
    r = NC.episode_checks(shots, blocks)
    assert r["N02"]["value"] == 0.5                                    # 镜1 直说情绪不算承载
    assert r["N04"]["ok"]                                              # 镜3 新人物入画落在 35%–75%
    assert r["N05"]["value"] == "interrupted"


def test_season_endings_no_repeat_in_3(NC):
    assert NC.season_endings({1: "reveal", 2: "question", 3: "interrupted"})["ok"]
    assert NC.season_endings({1: "interrupted", 2: "interrupted", 3: "reveal"})["repeats_at"] == [2] or \
        NC.season_endings({1: "interrupted", 2: "interrupted", 3: "reveal"})["ok"] is True
    bad = NC.season_endings({2: "interrupted", 3: "interrupted", 4: "interrupted"})
    assert not bad["ok"] and bad["repeats_at"] == [4]


def test_k_wrt_h14_solo_episode_conflict():
    import importlib.util as iu
    spec = iu.spec_from_file_location("rubric_code_solo", ROOT / "tools" / "script_rsi" / "rubric_code.py")
    RC = iu.module_from_spec(spec)
    spec.loader.exec_module(RC)

    class Cast:
        def __init__(self, name, presence):
            self.name, self.presence = name, presence

    class Shot:
        def __init__(self, i, cast, dialogue=()):
            self.index, self.cast, self.dialogue, self.duration = i, cast, list(dialogue), 6
    solo = [Shot(1, [Cast("林晚", "在画")]), Shot(2, [Cast("林晚", "在画"), Cast("顾沉", "画外")]), Shot(3, [Cast("林晚", "在画")])]
    assert RC.is_solo(solo) == {"林晚"}
    assert not RC.is_solo([Shot(1, [Cast("林晚", "在画"), Cast("顾沉", "在画")])])
    blocks_ok = ["**镜1｜img**：近景，林晚\n**分拍**：0–2秒｜抬眼｜视线=窗",
                 "**镜2｜img**：近景，林晚，手机亮起\n**分拍**：0–2秒｜手机屏幕亮起｜视线=手机",
                 "**镜3｜img**：近景，林晚\n**分拍**：0–2秒｜她把手机扣下｜视线=桌面"]
    ok, why = RC.solo_conflict(solo, blocks_ok)
    assert ok and "镜2" in why and "镜3" in why
    blocks_no_choice = blocks_ok[:2] + ["**镜3｜img**：近景，林晚\n**分拍**：0–2秒｜保持凝视｜视线=窗"]
    assert not RC.solo_conflict(solo, blocks_no_choice)[0]
    blocks_no_pressure = ["**镜1｜img**：近景，林晚\n**分拍**：0–2秒｜抬眼｜视线=窗"] * 3
    assert not RC.solo_conflict([Shot(1, [Cast("林晚", "在画")])] * 3, blocks_no_pressure)[0]


def test_allowed_endings_respects_all_windows():
    import importlib.util
    spec = importlib.util.spec_from_file_location("narrative_code", ROOT / "tools" / "script_rsi" / "narrative_code.py")
    NC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(NC)
    t = {1: "gaze_out", 2: "reveal", 3: "interrupted", 4: "interrupted", 5: "reveal", 6: "gaze_out",
         7: "question", 8: "interrupted", 9: "question", 10: "gaze_out"}
    assert NC.allowed_endings(t, 4) == ["reveal+question", "question"]
    assert NC.allowed_endings(t, 9) == ["reveal+question", "reveal"]
    assert set(NC.ENDING_HOW) == set(NC.ENDING_TYPES)
