"""K-WRT-206：P3-P4 系统预拼片段必须同时满足 H3-X1 / H3-X3 / H3-X4 / H3-D8（用真实 lint 校验，不调用 LLM）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import chainlib  # noqa: E402,F401  (设置 sys.path)
import p4_fragments as PF  # noqa: E402
from ns_schema import h3_lint as L  # noqa: E402
from ns_schema import llm_output_check as LOC  # noqa: E402

LIN = {"name": "林晚", "age": 22, "gender": "女",
       "en_phrase": "a 22-year-old Chinese woman with waist-length misty sky-blue straight hair with a blunt fringe, cool pale skin and a tall slender build",
       "voice_phrase": "a mid-high sweet breathy voice, natural pace"}
GU = {"name": "顾沉", "age": 34, "gender": "男",
      "en_phrase": "a 34-year-old East Asian man with short black hair, a composed handsome face, fair skin and a broad-shouldered build",
      "voice_phrase": "a low restrained voice, natural pace"}
LOOK = "a black patent leather corset with a black patent leather mini skirt, transparent 12cm stiletto heels"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _prompt(body: str) -> str:
    return f"integrated_multimodal_description: {body}\n\noverall_soundscape: Quiet room tone."


def _d8(prompt):
    return next(r for r in L.lint_h3_extra(prompt, dialogue=["你来了。"]) if r["rule_id"] == "H3-D8")


def test_on_screen_speaker_passes_x1_x3_d8():
    p = _prompt(f"[Shot 1] Live-action, a medium shot at eye level with {PF.anchors(LIN, LOOK)} on the left of the frame. "
                f"The camera pushes in with small amplitude as she turns. {_cap(PF.speaker_on(LIN))}: "
                f"<d>[Chinese] 你来了。</d> She keeps her eyes on the door as the shot ends.")
    rs = L.lint_h3_registry(p, anchors=[("林晚 EN", LIN["en_phrase"]), ("林晚 造型", LOOK)],
                            voices=[("林晚", LIN["voice_phrase"])])
    assert all(r["ok"] for r in rs), rs
    assert _d8(p)["ok"], _d8(p)


def test_off_screen_speaker_passes_x3_x4_d8():
    p = _prompt(f"[Shot 1] Live-action, a close-up at eye level with {PF.anchors(LIN, LOOK)} in the center of the frame. "
                f"The camera holds a static shot as her fingertip lifts. {_cap(PF.speaker_off(GU))} "
                f"<d>[Chinese] 你来了。</d> while her lips remain closed. She keeps breathing as the shot ends.")
    rs = L.lint_h3_registry(p, anchors=[("林晚 EN", LIN["en_phrase"])], voices=[("顾沉", GU["voice_phrase"])])
    assert all(r["ok"] for r in rs), rs
    assert _d8(p)["ok"], _d8(p)
    res = LOC.check_writer_output(p, dialogue=["你来了。"], absent_phrases={"顾沉": [GU["en_phrase"]]})
    assert not [e for e in res.errors if e["rule"] == "P1"], res.errors   # H3-X4


def test_block_lists_every_look_and_both_speaker_forms():
    looks = [{"name": "林晚", "looks": [{"id": "A", "en": "an ivory blouse"}, {"id": "B", "en": LOOK}]}]
    t = PF.block_for([LIN, GU], looks)
    assert PF.anchors(LIN, "an ivory blouse") in t and PF.anchors(LIN, LOOK) in t
    assert PF.speaker_on(GU) in t and PF.speaker_off(GU) in t and GU["en_phrase"] in t


def test_repair_lines_name_shot_and_fragment():
    md = "**镜3｜img**：特写\n**人物**：林晚（在画｜中｜前）、顾沉（画外）\n"
    gate = {"episodes": [{"shots": [{"id": "ep07-S3", "issues": [
        {"level": "block", "rule_id": "H3-X4", "detail": f"不在画的角色 顾沉 的外貌出现在正文里（等于让他在场）：{GU['en_phrase']}"},
        {"level": "block", "rule_id": "H3-X3", "detail": f"说话人首次出现的句子缺少 VOICE：(S1) 顾沉：{GU['voice_phrase']}"},
        {"level": "block", "rule_id": "H3-X1", "detail": f"锚点句（首句）缺少：林晚 EN外貌短语：{LIN['en_phrase']}"}]}]}]}
    out = "\n".join(PF.repair_lines(gate, md, [LIN, GU]))
    assert "镜3（H3-X4）" in out and PF.speaker_off(GU) in out           # 画外 → 画外片段
    assert "镜3（H3-X3）" in out and PF.speaker_on(GU) not in out
    assert f"「{LIN['en_phrase']}」" in out
    assert PF.spec_lines([{"rule": "P4-SPEC", "level": "block", "field": "ep02-S4.motion.beats",
                           "message": "[SS-M2] 分拍只写到 6.0s，镜长 7.0s"}])[0].startswith("镜4：")


def test_speech_lines_point_to_cause():
    md = ("**镜5｜img**：特写\n**🎙（林晚，OS）**：心跳一下。\n**镜7｜img**：全景\n**🎙（林晚，OS）**：疼是真的。\n**🎙（林晚，OS）**：可她的眼睛。\n"
          "**镜8｜img**：中景\n**🎙（林晚，OS）**：心跳一下。\n")
    out = "\n".join(PF.speech_lines(md, [("林晚", "提案拖了。")], [("林晚", "疼是真的。"), ("林晚", "可她的眼睛。")]))
    assert "镜7（LK34-03）" in out and "2 条 🎙" in out
    assert "镜8（LK34-03）" in out and "镜5" in out
    assert "「提案拖了。」" in out


def test_multi_vo_moves_to_named_free_shot_and_cue_both():
    md = ("**镜6｜img**：特写\n**对白**：（阿岚）“好了。”\n**镜7｜img**：全景\n**🎙（林晚，OS）**：镜子里这个人。\n"
          "**镜8｜img**：中景\n**🎙（林晚，OS）**：疼是真的。\n**🎙（林晚，OS）**：可她的眼睛。\n")
    out = "\n".join(PF.speech_lines(md, [], []))
    assert "「疼是真的。」整条移到镜6" in out
    md2 = "**镜6｜img**：特写\n**人物**：林晚（在画｜中｜前）\n**对白**：（林晚）“嗯。”\n**🎙（林晚，OS）**：我知道。\n"
    gate = {"episodes": [{"shots": [{"id": "ep07-S6", "issues": [
        {"level": "block", "rule_id": "QW-M1", "detail": "【配乐】本镜有台词，要写对白避让"}]}]}]}
    assert "对白避让，独白避让" in "\n".join(PF.repair_lines(gate, md2, [LIN]))


def test_fix_cue_avoid_only_touches_cue_enum():
    md = ("## ep05\n**镜6｜img**：特写\n**对白**：（阿岚，低声）“好了。”\n**🎙（林晚，OS）**：疼。\n"
          "**sound**：细响；【配乐】落下，强度1，独白避让；【H3 audio】Soft.\n**镜7｜img**：全景\n"
          "**sound**：风声；【配乐】延续，强度1，对白避让；【H3 audio】Wind.\n")
    new, log = PF.fix_cue_avoid(md)
    assert "【配乐】落下，强度1，对白避让，独白避让；" in new and "【配乐】延续，强度1，无需避让；" in new
    assert len(log) == 2 and new.replace("对白避让，独白避让", "独白避让").replace("无需避让", "对白避让") == md


def test_fix_cue_avoid_limited_to_named_shots():
    md = ("**镜1｜img**：特写\n**sound**：x；【配乐】进入，强度1，独白避让；【H3 audio】A.\n"
          "**镜6｜img**：特写\n**对白**：（阿岚）“好了。”\n**sound**：y；【配乐】落下，强度1，独白避让；【H3 audio】B.\n")
    new, log = PF.fix_cue_avoid(md, {6})
    assert "进入，强度1，独白避让" in new and "落下，强度1，对白避让" in new and len(log) == 1


def test_missing_line_and_split_plan():
    md = ("**镜2｜img**：中景\n**时长**：6秒\n**场景**：sk_a｜x\n**人物**：顾沉（在画｜左｜前）\n**对白**：（顾沉，低沉）“今晚四个人。”\n"
          "**镜3｜img**：近景\n**时长**：6秒\n**场景**：sk_a｜x\n**人物**：林晚（在画｜中｜前）\n"
          "**镜4｜img**：近景\n**时长**：7秒\n**场景**：sk_a｜x\n**人物**：林晚（在画｜中｜前）\n"
          "**镜5｜img**：中景\n**时长**：7秒\n**场景**：sk_b｜y\n**人物**：林晚（在画｜中｜前）、陈宇（局部｜手｜右）\n"
          "**对白**：（陈宇，疑惑）“这是什么？”／（林晚，压稳）“腰链。”\n")
    speech = [("顾沉", "今晚四个人。"), ("顾沉", "林晚。"), ("陈宇", "这是什么？"), ("林晚", "腰链。")]
    opts = PF.missing_line_options(md, speech, 1)
    assert [o["shot"] for o in opts] == [4, 3] and opts[0]["presence"] == "画外"
    plan = PF.split_two_speaker_plan(md, 5, 4)
    assert plan["split"][0]["line"] == ("陈宇", "这是什么？") and plan["merge"]["shots"] == [3, 4]


LOOK_B = "a black patent leather corset with a black patent leather mini skirt"
LOOK_C = "a misty blue knit long dress, white sneakers"
LOOKS = [{"name": "林晚", "looks": [{"id": "B", "en": LOOK_B}, {"id": "C", "en": LOOK_C}]}]


def _md(anchor, header_shot=5, img_note=""):
    return (f"## ep09\n**造型｜林晚**：服装=束腰｜EN={LOOK_B}\n**造型｜林晚｜镜{header_shot}起**：服装=针织｜EN={LOOK_C}\n\n"
            f"**镜4｜img{img_note}**：中近景\n**H3提示词**：\n```text\nintegrated_multimodal_description: [Shot 1] A medium close-up with "
            f"{anchor}, seated at the table. She lifts her cup as the shot ends.\n```\n")


def _gate(phrases):
    return {"episodes": [{"shots": [{"id": "ep09-S4", "issues": [
        {"level": "block", "rule_id": "H3-X1", "detail": "锚点句（首句）缺少：" + "；".join(phrases)}]}]}]}


def test_auto_fix_renumbers_stale_look_switch_header():
    md = _md(f"{LIN['en_phrase']} in {LOOK_C}", 5, "（换装：镜4起林晚换造型C）")
    new, log = PF.fix_anchors(md, _gate([f"林晚 造型 EN：{LOOK_B}"]), [LIN], LOOKS)
    assert "**造型｜林晚｜镜4起**" in new and "镜5起" not in new and len(log) == 1
    assert f"{LIN['en_phrase']} in {LOOK_C}" in new          # 锚点句不动


def test_auto_fix_replaces_wrong_registered_look():
    md = _md(f"{LIN['en_phrase']} in {LOOK_C}", 6)
    new, log = PF.fix_anchors(md, _gate([f"林晚 造型 EN：{LOOK_B}"]), [LIN], LOOKS)
    assert f"{LIN['en_phrase']} in {LOOK_B}" in new and "镜6起" in new


def test_auto_fix_inserts_after_en_phrase_or_adds_missing_anchor():
    md = _md(LIN["en_phrase"], 6)
    new, _ = PF.fix_anchors(md, _gate([f"林晚 造型 EN：{LOOK_B}"]), [LIN], LOOKS)
    assert f"{LIN['en_phrase']} in {LOOK_B}, seated" in new
    md = _md("a woman", 6)
    new, _ = PF.fix_anchors(md, _gate([f"林晚 EN外貌短语：{LIN['en_phrase']}", f"林晚 造型 EN：{LOOK_B}"]), [LIN], LOOKS)
    first = new.split("integrated_multimodal_description: ", 1)[1].split(". ", 1)[0]
    assert LIN["en_phrase"] in first and LOOK_B in first
