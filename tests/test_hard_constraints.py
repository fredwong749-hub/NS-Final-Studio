"""K-WRT-205：成年硬约束机检。修“A minor”误判时不能放宽：只排除音乐调式上下文。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import hard_constraints as HC  # noqa: E402


def blk(t):
    return HC.scan(t)[0]


def test_music_keys_are_not_flagged():
    for t in ["68 BPM, A minor, sparse chords", "Solo piano at 62 BPM in A minor.", "in C# minor and B-flat minor",
              "F sharp minor strings", "62 BPM, minor key, soft kick", "in a minor key with a heartbeat kick",
              "a minor chord progression", "Pianos in D minor"]:
        assert blk(t) == [], t


def test_minor_as_person_still_blocks():
    for t in ["she is a minor", "minors in the room", "a Minor, alone", "She looks like a minor.", "MINOR"]:
        assert "minor" in blk(t), t


def test_other_block_words_and_age():
    assert "schoolgirl" in blk("a schoolgirl outfit")
    assert "校服" in blk("穿着校服")
    assert "underage" in blk("underage")
    s = {"characters": [{"name": "甲", "age": 21}], "episodes": []}
    assert any(i["rule"] == "HC-01" for i in HC.check_story(s, None))
    s = {"characters": [{"name": "甲", "age": 22}], "episodes": []}
    assert not [i for i in HC.check_story(s, None) if i["level"] == "block"]


def test_offroster_name_in_logline():
    s = {"characters": [{"name": "林晚", "age": 22}], "episodes": [{"episode": 8, "logline": "Alex按响门铃"}]}
    assert any(i["rule"] == "HC-05" for i in HC.check_story(s, None))


def test_look_lock():
    assert HC.check_look_lock("她为他改换发色，心跳减半")
    assert HC.check_look_lock("她把头发染成了黑色")
    assert HC.check_look_lock("She dyes her hair black.")
    assert not HC.check_look_lock("雾霾天蓝色及腰直发（比参考图略深，带一点灰的真实染发色），齐刘海")
    assert not HC.check_look_lock("her waist-length misty sky-blue straight hair sways")
    assert HC.check_look_lock("左耳后小痣", ["痣", "mole"])
    assert HC.check_look_lock("a small mole behind her ear", ["痣", "mole"])


def test_marker_recoat_same_style_ok_but_restyle_blocked():
    ok = ["她当着他的面拆掉旧甲、由他一笔笔为她改涂钻石水晶甲，十指在暖光里闪成另一种物证",
          "5厘米超长透明水晶甲、镶满钻石饰品", "he repaints her clear diamond-studded crystal nails stroke by stroke"]
    for t in ok:
        assert not HC.check_look_lock(t), t
    bad = ["把水晶甲换成红色短甲", "她的指甲涂成了黑色", "换个颜色的美甲", "红色指甲油", "her nails painted red",
           "black nail polish", "short nails", "指甲剪成短的"]
    for t in bad:
        assert HC.check_look_lock(t), t


def test_w38_nail_lock_v1_only():
    """W38（ep01 S1）：V2 卓琳的标志物就是“long bright red nails”——资产包剧（nail_lock=False）不按 V1 林晚甲锁拦；发色改变照拦"""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sp = importlib.util.spec_from_file_location("hc_w38", root / "tools/pipeline/hard_constraints.py")
    HC = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(HC)
    t = "a small gold-chain clutch, long bright red nails standing at the left"
    assert HC.check_look_lock(t)                                   # V1 口径：拦
    assert HC.check_look_lock(t, nail_lock=False) == []            # V2：不拦
    assert HC.check_look_lock("她把头发染成了金色", nail_lock=False)  # 发色改变：V2 也拦
