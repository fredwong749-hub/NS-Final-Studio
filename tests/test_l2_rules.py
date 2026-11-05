"""L2 镜头语言代码判定（K-WRT-810–815；rubric_code.l2_checks / writer_lints.check_l2）：集头镜头规划、运镜词表 + 动机 + 固定占比、
焦段档位、轴线 / 视线方向、剪辑点、竖屏构图"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


RC = _load("rubric_code_l2t", "tools/script_rsi/rubric_code.py")
WL = _load("writer_lints_l2t", "tools/qa/writer_lints.py")
RUN = "series10_v2"


def shot(i, cast=(("祁念", "中"),), scene="sk_white_cyc"):
    return NS(index=i, scene_id=scene, cast=[NS(name=n, presence="在画", x=x) for n, x in cast])


def block(i, size="中景", move="推近｜小幅｜起幅=中景 → 落幅=中景略紧｜动机=她开口，推向说话人", lens="summicron_35_f2",
          motion="camera push in 小幅推近，她说了一句——中景，她站着", cam="推近｜幅度=小｜速度=正常",
          comp="前景=椅背略在焦外｜中景=祁念在上三分之一偏左、在焦点上｜背景=白幕｜视线方向=祁念向右看灯架，右侧留出空间",
          cut="动作匹配切｜她的手抬起"):
    return (f"**镜{i}｜img**：{size}，侧 45° 机位，祁念站着\n**镜头**：{lens}\n**构图**：{comp}\n**镜头运动**：{cam}\n**运镜**：{move}\n"
            f"**下镜**：{cut}\n**motion**：{motion}")


HEAD = "## ep01《x》\n**本集镜头规划**：轴线=卓琳左 / 祁念中 / 唐瑶右｜焦段=中景 summicron_35_f2｜coverage=主镜头 → 过肩 → 单人"


def test_good_episode_passes():
    assert RC.l2_checks([shot(1)], [block(1)], HEAD, RUN) == {}


def test_plan_required_in_head():
    r = RC.l2_checks([shot(1)], [block(1)], "## ep01《x》\n**剧情**：y", RUN)
    assert "plan#0" in r and not r["plan#0"][0]
    assert "plan#0" not in RC.l2_checks([shot(1)], [block(1)], "", RUN)       # 没给集头不判


def test_move_vocab_enabled_motivation_and_consistency():
    r = RC.l2_checks([shot(1)], [block(1, move="横移｜小幅｜起幅=中景 → 落幅=中景｜动机=跟随")], HEAD, RUN)
    assert "move#1" in r and "disabled" in r["move#1"][1]                     # truck 词表 disabled
    r = RC.l2_checks([shot(1)], [block(1, move="螺旋飞升｜小幅｜动机=x")], HEAD, RUN)
    assert "move#1" in r and "不在运镜词表" in r["move#1"][1]
    r = RC.l2_checks([shot(1)], [block(1, move="推近｜小幅｜起幅=中景 → 落幅=中景略紧")], HEAD, RUN)
    assert "move#1" in r and "动机=" in r["move#1"][1]
    r = RC.l2_checks([shot(1)], [block(1, motion="static shot 固定镜头，她说了一句——中景，她站着")], HEAD, RUN)
    assert "move#1" in r and "motion" in r["move#1"][1]                        # 运镜 push_in 与 motion static 不一致
    r = RC.l2_checks([shot(1)], [block(1, cam="固定镜头｜幅度=小｜速度=正常")], HEAD, RUN)
    assert "move#1" in r and "镜头运动" in r["move#1"][1]
    # 按剧运镜：V2 可用，别的剧 / 没给剧 不可用（失败关闭）
    b = block(1, move="高速急推急停｜中幅｜起幅=中景 → 落幅=中近景｜动机=登场爆点",
              motion="bolt_push_settle 高速急推急停（机械臂式），她转头——中近景，她站着", cam="高速急推急停｜幅度=中｜速度=快")
    assert "move#1" not in RC.l2_checks([shot(1)], [b], HEAD, RUN)
    assert "move#1" in RC.l2_checks([shot(1)], [b], HEAD, None)
    assert "move#1" in RC.l2_checks([shot(1)], [block(1, move="")], HEAD, RUN)


def test_static_ratio_capped_at_20_percent():
    st = dict(move="固定镜头｜小幅｜起幅=中景 → 落幅=中景不变｜动机=人物出画，机位不动", motion="static shot 固定镜头，她走出画——中景，空椅子",
              cam="固定镜头｜幅度=小｜速度=正常")
    shots = [shot(i) for i in range(1, 6)]
    assert "static#0" not in RC.l2_checks(shots, [block(1, **st)] + [block(i) for i in range(2, 6)], HEAD, RUN)        # 1/5 = 20%
    r = RC.l2_checks(shots, [block(1, **st), block(2, **st)] + [block(i) for i in range(3, 6)], HEAD, RUN)              # 2/5 = 40%
    assert "static#0" in r and "40%" in r["static#0"][1]


def test_lens_id_and_same_scene_same_size_same_focal():
    r = RC.l2_checks([shot(1)], [block(1, lens="")], HEAD, RUN)
    assert "lens#1" in r and "没写【镜头】" in r["lens#1"][1]
    r = RC.l2_checks([shot(1)], [block(1, lens="徕卡 50mm")], HEAD, RUN)
    assert "lens#1" in r and "不是 lenses.yaml" in r["lens#1"][1]
    two = [shot(1), shot(2)]
    assert "lens#2" not in RC.l2_checks(two, [block(1), block(2)], HEAD, RUN)
    r = RC.l2_checks(two, [block(1), block(2, lens="summicron_50_f2")], HEAD, RUN)
    assert "lens#2" in r and "焦段不同" in r["lens#2"][1]
    # 不同景别档可以换焦段；不同场也不比
    assert "lens#2" not in RC.l2_checks(two, [block(1), block(2, size="近景", lens="summilux_50_f14")], HEAD, RUN)
    assert "lens#2" not in RC.l2_checks([shot(1), shot(2, scene="sk_b")], [block(1), block(2, lens="summicron_50_f2")], HEAD, RUN)


def test_axis_gaze_direction_matches_cast_side():
    two = (("卓琳", "左"), ("祁念", "右"))
    ok = "前景=祁念的肩略在焦外｜中景=卓琳在焦点上｜背景=白幕｜视线方向=卓琳向右看祁念的脸，祁念向右前看灯架"
    assert "axis#1" not in RC.l2_checks([shot(1, two)], [block(1, comp=ok)], HEAD, RUN)
    bad = ok.replace("卓琳向右看祁念", "卓琳向左看祁念")
    r = RC.l2_checks([shot(1, two)], [block(1, comp=bad)], HEAD, RUN)
    assert "axis#1" in r and "矛盾" in r["axis#1"][1]
    # 看的不是人物（灯架）不判
    assert "axis#1" not in RC.l2_checks([shot(1, two)], [block(1, comp=ok.replace("祁念向右前看灯架", "祁念向左看灯架"))], HEAD, RUN)


def test_cut_types_and_hard_cut_reason():
    for c in ("视线匹配切｜她看向门口", "声音先行 0.4 秒｜下一镜的鞋跟声提前进", "硬切｜理由=换段，幻想段结束", "叠化 0.3 秒｜时间过渡"):
        assert "cut#1" not in RC.l2_checks([shot(1)], [block(1, cut=c)], HEAD, RUN), c
    r = RC.l2_checks([shot(1)], [block(1, cut="硬切｜她站着")], HEAD, RUN)
    assert "cut#1" in r and "理由" in r["cut#1"][1]
    r = RC.l2_checks([shot(1)], [block(1, cut="淡出｜她站着")], HEAD, RUN)
    assert "cut#1" in r and "类型" in r["cut#1"][1]


def test_vertical_single_person_composition():
    r = RC.l2_checks([shot(1)], [block(1, comp="前景=椅背｜中景=祁念在正中｜背景=白幕｜视线方向=祁念向右看灯架")], HEAD, RUN)
    assert "vert#1" in r
    two = (("卓琳", "左"), ("祁念", "右"))
    comp = "前景=祁念的肩｜中景=卓琳在焦点上｜背景=白幕｜视线方向=卓琳向右看祁念"
    assert "vert#1" not in RC.l2_checks([shot(1, two)], [block(1, comp=comp)], HEAD, RUN)     # 多人镜不判（走 L1 三层）


def test_writer_lint_check_l2():
    text = "# t\n## ep01《a》\n**剧情**：x\n" + block(1, move="推近｜小幅｜起幅=中景 → 落幅=中景略紧") + "\n"
    ep = NS(number=1, shots=[shot(1)])
    out = WL.check_l2(ep, text, RUN)
    ids = sorted(i["rule_id"] for i in out)
    assert ids == ["QW-L3", "QW-L8"], ids
    assert all(i["level"] == "warn" for i in out)
