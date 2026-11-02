"""场景定稿行 / 衔接点 / 不重复描述环境（tools/script_rsi/scene_lock.py，K-WRT-H23–H25）。不写真实数据。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def SL():
    spec = importlib.util.spec_from_file_location("scene_lock", ROOT / "tools" / "script_rsi" / "scene_lock.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class C:
    def __init__(self, name, x, presence="在画"):
        self.name, self.x, self.presence = name, x, presence


class S:
    def __init__(self, i, cast, sid="sk_office_night"):
        self.index, self.cast, self.scene_id = i, cast, sid


HEAD = ("## ep01《x》\n**场景定稿｜sk_office_night**：陈设=办公桌、转椅、台灯｜主光=深夜办公室·台灯（office_night_lamp）｜"
        "站位=林晚：左·坐在转椅上；顾沉：右·站在门边｜屏幕方向=林晚在左、面朝右；顾沉在右、面朝左\n")


def blk(i, link, img="中景，林晚坐在转椅上，林晚的手扶着办公桌", light="深夜办公室·台灯（office_night_lamp）｜…"):
    return f"**镜{i}｜img**：{img}\n**衔接**：{link}\n**灯光**：{light}"


def test_parse_locks(SL):
    lk = SL.parse_locks(HEAD)["sk_office_night"]
    assert lk["陈设"] == ["办公桌", "转椅", "台灯"] and lk["站位"]["顾沉"]["side"] == "右" and not lk["missing"]


def test_axis_light_link_env(SL):
    shots = [S(1, [C("林晚", "左"), C("顾沉", "右")]), S(2, [C("林晚", "右"), C("顾沉", "左")]), S(3, [C("林晚", "左")])]
    blocks = [blk(1, "换场｜承：无", img="中景，林晚坐在转椅上，落地窗外的城市霓虹在背景虚化成光斑"),
              blk(2, "同场换机位｜承：环境｜空调声", light="夜街·霓虹｜…"),
              blk(3, "同场换机位｜承：视线｜林晚看向门口", img="近景，林晚的手扶着办公桌，落地窗外城市霓虹在背景虚化成光斑")]
    r = SL.check_episode(HEAD, shots, blocks)
    assert not r["H23"][0] and "越轴" in r["H23"][1] and "主光" in r["H23"][1]
    assert not r["H24"][0] and "镜2" in r["H24"][1]
    assert not r["H25"][0] and "镜3" in r["H25"][1]


def test_move_cue_updates_blocking(SL):
    shots = [S(1, [C("林晚", "左"), C("顾沉", "右")]), S(2, [C("林晚", "右"), C("顾沉", "左")])]
    assert not SL.check_episode(HEAD, shots, [blk(1, "换场｜承：无"), blk(2, "同场换机位｜承：视线｜林晚看向顾沉")])["H23"][0]
    assert SL.check_episode(HEAD, shots, [blk(1, "换场｜承：无"), blk(2, "同场换机位｜承：动作｜林晚移到右；顾沉移到左")])["H23"][0]


def test_missing_lock_line(SL):
    r = SL.check_episode("## ep01《x》\n", [S(1, [C("林晚", "左")])], [blk(1, "换场｜承：无")])
    assert not r["H23"][0] and "没有场景定稿行" in r["H23"][1]


def test_axis_counts_partial_over_shoulder(SL):
    """总调度 11-02：过肩镜里局部入画的人也占画面一侧——ep03 镜10 林晚右、顾沉（局部｜右肩｜左）对调了定稿左右，要判越轴"""
    shots = [S(1, [C("林晚", "左"), C("顾沉", "右")]), S(2, [C("林晚", "右"), C("顾沉", "左", "局部")])]
    r = SL.check_episode(HEAD, shots, [blk(1, "换场｜承：无"), blk(2, "同场换机位｜承：视线｜林晚看向顾沉")])
    assert not r["H23"][0] and "镜2" in r["H23"][1]
    ok = [S(1, [C("林晚", "左"), C("顾沉", "右")]), S(2, [C("林晚", "左"), C("顾沉", "右", "局部")])]
    assert SL.check_episode(HEAD, ok, [blk(1, "换场｜承：无"), blk(2, "同场换机位｜承：视线｜林晚看向顾沉")])["H23"][0]
