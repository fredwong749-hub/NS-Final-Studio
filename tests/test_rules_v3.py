"""R3（fredw-92/R3，docs/production_rules_v3.md）：v3 字段（人物表 / 出场人物 / 用到的场景 / 造型 / 人物 / 衔接）的
导入与格式校验。合成占位剧本（格式占位，不是剧情文本）。每条新规则：最小合格 v3 稿通过；缺字段 / 写错时报该编号与级别。"""
import importlib.util
import sys
from pathlib import Path

import pytest

from ns_agent.importer.script_md import import_script
from ns_schema.h3_lint import alignment_line, frames_for_seconds, lint_h3
from ns_schema.script import ScriptImport

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load("_r3_vqs", "tools/validate_qwen_script.py")
sys.path.insert(0, str(ROOT / "tools"))
STRICT = _load("_r3_vss", "tools/validate_script_strict.py")

EN_LW = "a young adult woman with long placeholder hair and straight bangs"
VOICE_LW = "a soft placeholder voice at a slow pace"
EN_M = "an adult man with short placeholder hair"
VOICE_M = "a low placeholder voice at a measured pace"
OUTFIT = "a placeholder fitted dress with placeholder heels"
SOUND = "Placeholder room tone hums steadily. Placeholder fabric rustles softly."
LINE = "占位台词一。"

PEOPLE_HEAD = "| 角色 | 角色id | 中文外貌句 | EN外貌短语 | VOICE声线短语 |\n|---|---|---|---|---|\n"
SCENE_HEAD = "| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |\n|---|---|---|---|---|---|\n"
LW_ROW = f"| 林晚 | lin_wan | 系统锁 | {EN_LW} | {VOICE_LW} |\n"
M_ROW = f"| 占位男 | ch_extra_a | 占位年龄｜占位体型｜占位发型｜占位服装色｜占位标志物｜占位特征 | {EN_M} | {VOICE_M} |\n"
SCENE_A = "| sk_place_a | 占位名称A | 占位空间A | 占位时段A | 占位光线A | 占位陈设甲、占位陈设乙 |\n"
SCENE_B = "| sk_place_b | 占位名称B | 占位空间B | 占位时段B | 占位光线B | 占位陈设丙 |\n"


def head(people=LW_ROW + M_ROW, scenes=SCENE_A + SCENE_B, locks="【林晚】占位锁",
         lora="图像LoRA\n  hh12clear  占位说明\n视频LoRA\n  lnwan01  占位说明"):
    return ("# 全局头\n\n**每条prompt统一前缀**：\n```\n" + locks + "\n```\n\n"
            "**LoRA 触发词表**：\n```\n" + lora + "\n```\n\n"
            + (f"**全剧人物表**：\n{PEOPLE_HEAD}{people}\n" if people is not None else "")
            + f"**全剧场景表**：\n{SCENE_HEAD}{scenes}\n---\n\n")


def h3(seconds=10, en=EN_LW, outfit=OUTFIT, voice=VOICE_LW, move="The camera pushes in with small amplitude as she "
       "lifts her chin.", line=LINE, d_first=False):
    align = alignment_line(frames_for_seconds(seconds))
    first = (f"[Shot 1] Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing "
             f"and lighting established by Picture 1, {en}, wearing {outfit}, stands at the center.")
    speak = f"The on-screen young adult woman with {voice} (S1) says: <d>[Chinese] {line}</d>"
    if d_first:
        first = first[:-1] + f" and (S1) with {voice} says: <d>[Chinese] {line}</d>"
        speak = ""
    body = " ".join(x for x in (first, move, speak,
                                "She settles into the pose and composition established by Picture 2 at the end of the shot.")
                    if x)
    return (f"{align}\n\nintegrated_multimodal_description: {body}\n\noverall_soundscape: {SOUND}"
            f"\n\nnon_diegetic_music: N/A")


def shot(i, *, img=None, scene="sk_place_a｜占位细节", cast="林晚（在画｜中｜中）", link=None,
         motion=None, seconds=10, cue="延续，强度1，对白避让", dialogue=f"（林晚）“{LINE}”", vo=None, h3_text=None,
         note=""):
    link = link if link is not None else ("换场" if i == 1 else "接力｜承：占位延续")
    parts = [f"**镜{i}｜img{note}**：{img or f'中景，林晚，占位名称A，占位画面{i}'}"]
    if scene is not None:
        parts.append(f"**场景**：{scene}")
    if cast is not None:
        parts.append(f"**人物**：{cast}")
    if link != "":
        parts.append(f"**衔接**：{link}")
    parts.append(f"**motion**：{motion or 'lnwan01，camera push in 缓慢推近，占位动作，眼神占位——中景，林晚占位结束状态'}")
    if seconds is not None:
        parts.append(f"**时长**：{seconds}秒")
    parts.append(f"**sound**：占位声音；【配乐】{cue}；【H3 audio】{SOUND}")
    if dialogue:
        parts.append(f"**对白**：{dialogue}")
    if vo:
        parts.append(vo)
    parts.append("**H3提示词**：\n```text\n" + (h3_text or h3(seconds or 10)) + "\n```")
    return "\n".join(parts)


def episode(shots=None, n=1, cast="林晚", scenes="sk_place_a",
            looks=f"**造型｜林晚**：服装=新：占位裙｜鞋=新：占位鞋｜妆=新：占位妆｜发=新：占位发｜EN={OUTFIT}",
            extra_head=""):
    shots = shots or [shot(i) for i in range(1, 7)]
    parts = [f"## ep{n:02d}《占位标题》", "**剧情**：占位剧情。"]
    if cast is not None:
        parts.append(f"**出场人物**：{cast}")
    if scenes is not None:
        parts.append(f"**用到的场景**：{scenes}")
    if looks:
        parts.append(looks)
    parts.append("**配乐**：占位配乐说明；【BGM】Placeholder BGM prompt with soft piano.")
    if extra_head:
        parts.append(extra_head)
    return "\n\n".join(parts) + "\n\n" + "\n\n".join(shots) + "\n\n---\n"


def write(tmp_path, text, name="v3.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def issues(rep):
    out = [(i["rule_id"], i["level"], "全局") for i in rep.get("global_issues", [])]
    for ep in rep["episodes"]:
        out += [(i["rule_id"], i["level"], "集") for i in ep["issues"]]
        out += [(i["rule_id"], i["level"], s["id"]) for s in ep["shots"] for i in s["issues"]]
    return out


def strict(tmp_path, text):
    return STRICT.strict_validate(write(tmp_path, text))


def has(rep, rule, level):
    got = issues(rep)
    assert any(r == rule and lv == level for r, lv, _ in got), (rule, level, got)


V3_RULE_PREFIXES = ("QW-G", "QW-P", "QW-E4", "QW-E5", "QW-E6", "QW-E7", "QW-CH", "QW-LK", "QW-K", "QW-M1", "QW-D",
                    "QW-SC7", "QW-SC8", "QW-C4", "H3-X1", "H3-X3")


# ------------------------------------------------------------------ 导入

def test_import_v3_fields(tmp_path):
    vo = "**🎙（林晚，镜尾）**：占位独白。"
    looks = (f"**造型｜林晚**：服装=新：占位裙｜鞋=新：占位鞋｜妆=新：占位妆｜发=新：占位发｜饰品=新：占位耳钉｜EN={OUTFIT}\n\n"
             "**造型｜林晚｜镜3起**：服装=新：占位外套｜EN=a placeholder coat")
    shots = [shot(1, cast="林晚（在画｜左｜前）、占位男（画外）", dialogue=f"（林晚，轻声）“{LINE}”", vo=vo)] + \
        [shot(i) for i in range(2, 7)]
    imp = import_script(write(tmp_path, head() + episode(shots, cast="林晚、占位男", looks=looks)))
    reg = {e.name: e for e in imp.globals.character_registry}
    assert set(reg) == {"林晚", "占位男"} and reg["林晚"].en == EN_LW and reg["占位男"].voice == VOICE_M
    assert reg["林晚"].char_id == "lin_wan" and reg["林晚"].defined_in == [None]
    ep = imp.episodes[0]
    assert ep.cast == ["林晚", "占位男"] and ep.scene_ids == ["sk_place_a"]
    assert [(lk.character, lk.from_shot) for lk in ep.looks] == [("林晚", None), ("林晚", 3)]
    assert ep.looks[0].slots["饰品"] == "新：占位耳钉" and ep.looks[0].en == OUTFIT and ep.looks[1].slots == {"服装": "新：占位外套"}
    s1, s2 = ep.shots[:2]
    assert [(c.name, c.presence, c.x, c.depth) for c in s1.cast] == [("林晚", "在画", "左", "前"), ("占位男", "画外", None, None)]
    assert (s1.link, s1.link_carry) == ("换场", None) and (s2.link, s2.link_carry) == ("接力", "占位延续")
    assert s1.dialogue[0].speaker == "林晚" and s1.voiceover.speaker == "林晚"
    assert s1.img_prompt.startswith("中景") and s1.motion_prompt and s1.scene_id == "sk_place_a"
    assert not any("无法归属" in w or "人物表" in w for w in imp.warnings), imp.warnings
    assert not any(e.label in ("出场人物", "用到的场景", "人物", "衔接") or e.label.startswith("造型") for e in ep.extras)
    back = ScriptImport.model_validate_json(imp.model_dump_json())
    assert back.globals.character_registry[1].name == "占位男" and back.episodes[0].shots[0].cast[1].presence == "画外"


def test_character_table_conflict_and_format(tmp_path):
    local = "**本集人物表**：\n" + PEOPLE_HEAD + f"| 占位男 | ch_extra_a | 占位年龄｜占位体型｜占位发型｜占位服装色｜占位标志物｜占位特征 | an older man with gray hair | {VOICE_M} |\n"
    imp = import_script(write(tmp_path, head() + episode(extra_head=local)))
    e = {x.name: x for x in imp.globals.character_registry}["占位男"]
    assert e.defined_in == [None, 1] and [(c.field, c.episode) for c in e.conflicts] == [("EN外貌短语", 1)]
    assert any("占位男" in w and "EN外貌短语" in w for w in imp.warnings)


def test_old_script_imports_and_v3_rules_silent_at_gate(tmp_path):
    T = _load("_r3_t", "tests/test_validate_qwen_script.py")
    p = write(tmp_path, T.episode(), "old.md")
    imp = import_script(p)
    s = imp.episodes[0].shots[0]
    assert imp.globals.character_registry == [] and s.cast is None and s.link is None and imp.episodes[0].cast is None
    rep = V.validate(p)
    assert rep["v3"] is False and rep["blocking"] == 0
    assert not [r for r, _, _ in issues(rep) if r.startswith(V3_RULE_PREFIXES)]
    st = STRICT.strict_validate(p)          # 剧本创作（严格）：v3 字段必须写
    assert st["v3"] is True
    for rule in ("QW-E4", "QW-E5", "QW-CH1", "QW-LK1"):
        has(st, rule, "block")


# ------------------------------------------------------------------ 合格稿

def test_minimal_valid_v3_draft_passes(tmp_path):
    text = head() + episode()
    rep = V.validate(write(tmp_path, text, "a.md"))
    assert rep["v3"] is True and rep["blocking"] == 0, issues(rep)
    st = strict(tmp_path, text)
    assert st["blocking"] == 0, [x for x in issues(st) if x[1] == "block"]
    v3_warns = [x for x in issues(st) if x[0].startswith(V3_RULE_PREFIXES)]
    assert v3_warns == [], v3_warns
    assert all(isinstance(s["img_chars"], int) for s in st["episodes"][0]["shots"])     # IMG-C2：只统计


def test_gate_checks_v3_when_draft_declares_it(tmp_path):
    """导入关口：写了任一 v3 字段 = 声明 v3 格式，缺的字段按 block 报（同 S-back 场景规则）"""
    shots = [shot(1)] + [shot(i, cast=None) for i in range(2, 7)]
    rep = V.validate(write(tmp_path, head() + episode(shots)))
    assert rep["v3"] is True
    has(rep, "QW-CH1", "block")


# ------------------------------------------------------------------ 全局头 / 人物表 / 场景表

@pytest.mark.parametrize("kw,rule,level", [
    ({"locks": ""}, "QW-G1", "warn"),
    ({"lora": "图像LoRA\n  hh12clear  占位说明\n其它段\n  zz  占位"}, "QW-G2", "warn"),
    ({"people": LW_ROW + "| 占位男 | ch_extra_a | 占位 |\n"}, "QW-P1", "block"),
    ({"people": LW_ROW + M_ROW.replace("ch_extra_a", "Extra-A")}, "QW-P2", "block"),
    ({"people": LW_ROW.replace("lin_wan", "ch_lin") + M_ROW}, "QW-P2", "block"),
    ({"people": LW_ROW + M_ROW + M_ROW.replace("占位男", "占位男二")}, "QW-P2", "block"),
    ({"people": LW_ROW.replace(EN_LW, "占位外貌") + M_ROW}, "QW-P3", "block"),
    ({"people": LW_ROW.replace(EN_LW, "a woman with no bangs") + M_ROW}, "QW-P3", "block"),
    ({"people": LW_ROW.replace(VOICE_LW, "soft and slow") + M_ROW}, "QW-P4", "block"),
    ({"people": LW_ROW.replace(VOICE_LW, "") + M_ROW}, "QW-P4", "block"),
    ({"people": LW_ROW + M_ROW.replace("占位年龄｜", "")}, "QW-P6", "warn"),
    ({"scenes": SCENE_A.replace("占位空间A", "林晚站在窗边") + SCENE_B}, "QW-SC8", "block"),
    ({"scenes": SCENE_A.replace("占位陈设甲、占位陈设乙", "甲、乙、丙、丁") + SCENE_B}, "QW-SC8", "block"),
])
def test_global_rules(tmp_path, kw, rule, level):
    has(strict(tmp_path, head(**kw) + episode()), rule, level)


def test_character_conflict_qw_p5(tmp_path):
    local = "**本集人物表**：\n" + PEOPLE_HEAD + LW_ROW.replace(VOICE_LW, "a different placeholder voice")
    # fredw-92/D2：改写全剧人物表（继承）里已登记的角色 = QW-P7（返修附原文）
    has(strict(tmp_path, head() + episode(extra_head=local)), "QW-P7", "block")


def test_speaker_without_registry_voice_qw_p4(tmp_path):
    has(strict(tmp_path, head(people=LW_ROW.replace(VOICE_LW, "")) + episode()), "QW-P4", "block")


# ------------------------------------------------------------------ 集头

def test_episode_head_rules(tmp_path):
    has(strict(tmp_path, head() + episode(cast=None)), "QW-E4", "block")
    has(strict(tmp_path, head() + episode(cast="林晚、占位男")), "QW-E4", "block")          # 多了人
    has(strict(tmp_path, head() + episode(cast="林晚、路人")), "QW-E4", "block")            # 没登记
    has(strict(tmp_path, head() + episode(scenes=None)), "QW-E5", "block")
    has(strict(tmp_path, head() + episode(scenes="sk_place_a、sk_place_b")), "QW-E5", "block")
    has(strict(tmp_path, head() + episode(scenes="sk_place_a、sk_nope")), "QW-E5", "block")
    has(strict(tmp_path, head() + episode(looks="")), "QW-E6", "block")
    has(strict(tmp_path, head() + episode(looks=f"**造型｜林晚**：服装=新：占位裙｜鞋=新：占位鞋｜EN={OUTFIT}")),
        "QW-E6", "block")                                                                       # 缺妆、发
    has(strict(tmp_path, head() + episode(looks="**造型｜林晚**：服装=新：占位裙｜鞋=新：占位鞋｜妆=新：占位妆｜发=新：占位发｜"
                                                 "裙=新：占位｜EN=占位")), "QW-E6", "block")     # 槽位名 + EN 中文
    has(strict(tmp_path, head() + episode(looks=f"**造型｜林晚**：服装=占位旧单品｜鞋=新：占位鞋｜妆=新：占位妆｜发=新：占位发｜EN={OUTFIT}")),
        "QW-E6b", "warn")


def test_costume_change_qw_e7(tmp_path):
    base = f"**造型｜林晚**：服装=新：占位裙｜鞋=新：占位鞋｜妆=新：占位妆｜发=新：占位发｜EN={OUTFIT}"
    has(strict(tmp_path, head() + episode(looks=base + "\n\n**造型｜林晚｜镜9起**：服装=新：占位外套｜EN=a placeholder coat")),
        "QW-E7", "block")
    has(strict(tmp_path, head() + episode(looks=base + "\n\n**造型｜林晚｜镜3起**：服装=新：占位外套｜EN=a placeholder coat")),
        "QW-E7", "warn")
    shots = [shot(i, note="（换装）" if i == 3 else "",
                  h3_text=h3(outfit="a placeholder coat") if i >= 3 else None) for i in range(1, 7)]
    rep = strict(tmp_path, head() + episode(shots, looks=base + "\n\n**造型｜林晚｜镜3起**：服装=新：占位外套｜EN=a placeholder coat"))
    assert not [x for x in issues(rep) if x[0] in ("QW-E7", "H3-X1")], issues(rep)   # 镜3 起锚点用换装后的 EN


def test_k1_shot_count_and_total(tmp_path):
    rep = V.validate(write(tmp_path, head() + episode([shot(i, seconds=13) for i in range(1, 7)])))   # 78 秒
    has(rep, "QW-E3", "warn")
    rep = V.validate(write(tmp_path, head() + episode([shot(i, seconds=15) for i in range(1, 8)]), "b.md"))   # 105 秒
    has(rep, "QW-E3", "block")
    rep = V.validate(write(tmp_path, head() + episode([shot(i) for i in range(1, 6)]), "c.md"))     # 5 镜
    has(rep, "QW-E2", "block")


# ------------------------------------------------------------------ 每镜

def _six(tmp_path, bad_shot, i=2, **ep_kw):
    shots = [bad_shot if k == i else shot(k) for k in range(1, 7)]
    return strict(tmp_path, head() + episode(shots, **ep_kw))


@pytest.mark.parametrize("kw,rule,level", [
    ({"cast": None}, "QW-CH1", "block"),
    ({"cast": "林晚（在画｜中间｜中）"}, "QW-CH1", "block"),
    ({"cast": "林晚（在画｜中｜中）、她（画外）"}, "QW-CH1", "block"),
    ({"cast": "林晚（在画｜中｜中）、路人（画外）"}, "QW-CH2", "block"),
    ({"cast": "林晚（在画｜中｜中）、占位男（在画｜左｜后）、甲（在画｜右｜后）、乙（局部｜手｜左）"}, "QW-CH3", "block"),
    ({"img": "中景，林晚，占位男，占位名称A，占位画面"}, "QW-CH4", "block"),
    ({"cast": "林晚（在画｜中｜中）、占位男（在画｜左｜后）"}, "QW-CH4", "warn"),
    ({"dialogue": f"（占位男）“{LINE}”"}, "QW-CH5", "block"),
    ({"cast": "林晚（在画｜中｜中）、占位男（画外）", "dialogue": f"（占位男，低声）“{LINE}”"}, "QW-CH5", "block"),
    ({"link": ""}, "QW-LK1", "block"),
    ({"link": "接续"}, "QW-LK1", "block"),
    ({"link": "接力"}, "QW-LK1", "block"),
    ({"link": "接力｜承：占位", "scene": "sk_place_b｜占位细节", "img": "中景，林晚，占位名称B，占位画面"}, "QW-LK2", "block"),
    ({"link": "接力｜承：占位", "img": "大远景，林晚，占位名称A，占位画面",
      "motion": "lnwan01，camera pull out 缓慢拉远，占位动作，眼神占位——远景，林晚占位结束状态"}, "QW-LK2", "warn"),
    ({"link": "换场"}, "QW-LK3", "block"),
    ({"motion": "lnwan01，camera push in 缓慢推近，占位动作，眼神占位——林晚占位结束状态静止"}, "QW-K1", "block"),
    ({"motion": "lnwan01，camera push in 缓慢推近，占位动作，眼神占位——特写，林晚占位结束状态"}, "QW-K2", "block"),
    ({"motion": "lnwan01，static shot 固定机位，占位动作，眼神占位——近景，林晚占位结束状态"}, "QW-K2", "block"),
    ({"motion": "lnwan01，camera push in 缓慢推近，占位动作，眼神占位——中景，林晚背对镜头占位结束状态"}, "QW-K3", "warn"),
    ({"img": "中景，林晚，占位画面"}, "QW-SC7", "warn"),
    ({"cue": "推高，强度1，对白避让"}, "QW-M1", "block"),
    ({"cue": "延续，强度5，对白避让"}, "QW-M1", "block"),
    ({"cue": "延续，强度1，无需避让"}, "QW-M1", "block"),
    ({"cue": "延续，强度1"}, "QW-M1", "block"),
    ({"dialogue": f"（她）“{LINE}”"}, "QW-D1", "block"),
    ({"dialogue": f"（林晚，旁白）“{LINE}”"}, "QW-D1", "block"),
    ({"vo": "**🎙（她，镜尾）**：占位独白。", "cue": "延续，强度1，对白避让，独白避让"}, "QW-D2", "block"),
    ({"motion": "lnwan01，camera pan left 缓慢左摇，占位动作，眼神占位——中景，林晚占位结束状态"}, "QW-C4", "warn"),
    ({"h3_text": h3(en="a young adult woman")}, "H3-X1", "block"),
    ({"h3_text": h3(outfit="a placeholder outfit")}, "H3-X1", "block"),
    ({"h3_text": h3(voice="a soft voice at a slow pace")}, "H3-X3", "block"),
    ({"h3_text": h3(d_first=True)}, "H3-X2", "warn"),
    ({"seconds": None}, "S1-W2", "block"),
    ({"seconds": 3}, "S1-W2", "block"),
])
def test_shot_rules(tmp_path, kw, rule, level):
    has(_six(tmp_path, shot(2, **kw)), rule, level)


def test_vo_with_registered_speaker_passes(tmp_path):
    rep = _six(tmp_path, shot(2, vo="**🎙（林晚，镜尾）**：占位独白。", cue="延续，强度1，对白避让，独白避让"))
    assert not [x for x in issues(rep) if x[0] in ("QW-D2", "QW-M1", "QW-CH5")], issues(rep)


def test_shot1_link_and_transition_words(tmp_path):
    has(strict(tmp_path, head() + episode([shot(1, link="接力｜承：占位")] + [shot(i) for i in range(2, 7)])), "QW-LK1", "block")
    rep = _six(tmp_path, shot(2, link="换场", note="（次日）"))
    assert "QW-LK3" not in [x[0] for x in issues(rep)]


def test_four_second_shot_and_static_shot_accepted(tmp_path):
    rep = _six(tmp_path, shot(2, seconds=4, motion="lnwan01，static shot 固定机位，占位动作，眼神占位——中景，林晚占位结束状态",
                              h3_text=h3(4, move="The camera holds a static shot as she lifts her chin.")))
    got = [x for x in issues(rep) if x[2] == "ep01-S2" and x[1] == "block"]
    assert got == [], got
    assert rep["episodes"][0]["shots"][1]["frames"] == 107 == frames_for_seconds(4)


def test_h3_lint_a12_block_and_x2():
    long = h3() + " x" * 4000
    r = {x["rule_id"]: x for x in lint_h3(long, frames=243)}
    assert not r["H3-A12"]["ok"] and r["H3-A12"]["level"] == "block"
    assert {x["rule_id"]: x for x in lint_h3(h3(d_first=True), frames=243)}["H3-X2"]["ok"] is False


def test_h3_a9_inner_body_part_is_not_abstract():
    from ns_schema.h3_lint import ABSTRACT_RE
    assert not ABSTRACT_RE.search("her fingers trace the inner calf and the inner thigh")
    assert ABSTRACT_RE.search("her inner thoughts") and ABSTRACT_RE.search("innermost")


def test_repair_text_has_no_conflicting_scope(tmp_path):
    rep = _six(tmp_path, shot(2, cast=None))
    text = rep["episodes"][0]["shots"][1]["repair"]
    assert "QW-CH1" in text and "其它镜头不要输出" not in text and "请输出" not in text
    assert "其它镜头不要输出" in V.repair_request(1, 2, [{"rule_id": "QW-CH1", "level": "block", "detail": "x"}])


def test_merge_globals_and_compact_header_keep_registry():
    from import_script import merge_globals
    from ns_schema.script import CharacterEntry, ScriptGlobals
    g = merge_globals(ScriptGlobals(character_registry=[CharacterEntry(name="甲", en="a"), CharacterEntry(name="乙")]),
                      ScriptGlobals(character_registry=[CharacterEntry(name="甲", en="b")]))
    # fredw-92 2026-10-31 定：登记冲突保留先登记的（fredw-92/D2 改期望）
    assert [(e.name, e.en) for e in g.character_registry] == [("甲", "a"), ("乙", "")]
    from ns_api.script_chat import compact_header
    out = compact_header(head().split("\n---")[0])
    assert "**全剧人物表**" in out and EN_LW in out and "**全剧场景表**" in out


def test_compiler_uses_cast_line_when_present():
    """第五部分 4.1：有 **人物** 行时入镜角色 = 在画 + 局部；没有时沿用关键词判定"""
    from ns_agent.compiler import present_characters
    from ns_schema.script import CastEntry, Shot
    s = Shot(episode=1, index=1, source_line=1, cast=[CastEntry(name="林晚", presence="局部", part="手", x="左"),
                                                     CastEntry(name="顾沉", presence="画外")])
    assert present_characters(s, "中景，顾沉站在门口", ["林晚", "顾沉"]) == ["林晚"]
