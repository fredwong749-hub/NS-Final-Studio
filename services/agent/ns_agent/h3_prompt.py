"""
H3 FL2VA 提示词（SOP_production.md §9A.1 四块结构）的纯函数构建器。

来源优先级（S1-W7–W9）：剧本 `**H3提示词**`（Shot.h3_prompt，原样）> 本构建器的笔记本草稿。
构建器不翻译、不新写描述：
- 正文英文只来自调用方传入的 body_en（画布修改 / 将来剧本 v3 的英文正文）；没有就把剧本 motion 中文原文放进结构里，
  lint 会报 H3-A7「需要英文正文（剧本 v3 提供）」。
- overall_soundscape 来自 soundscape 参数（编译器按 画布 > 剧本【H3 audio】> 剧本 sound 行 给出）。
- non_diegetic_music 固定 N/A（项目规则，配乐交给后期 BGM）。
- 对白：(S1)/(S2) 按首次开口顺序编号，说话人说明在 <d> 外，<d>[Chinese] 剧本原文逐字</d>；画外台词按 H3-D5；
  🎙 内心独白永远不进（H3-D6）。不加引号，不加负面词，不拼图像风格后缀。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ns_schema.h3_lint import ALIGN_PREFIX, FIELDS, VO_PHRASE, alignment_line, frames_for_seconds, parse_h3

MUSIC = "N/A"
# 剧本说话人括号里表示“人不在画面里出声”的写法（H3-D5）
OFFSCREEN_MARKS = ("画外", "电话", "语音", "OS", "V.O", "VO")
LIPS_CLOSED = "The on-screen character's lips remain closed."


@dataclass
class H3Draft:
    text: str
    body: str
    soundscape: str
    music: str
    frames: int
    source: str                     # script | laptop
    english_body: bool = False
    english_soundscape: bool = False
    missing: list[str] = field(default_factory=list)   # 缺英文的块：body / soundscape
    speakers: dict[str, str] = field(default_factory=dict)   # 说话人 key → S1/S2…
    offscreen: list[str] = field(default_factory=list)       # 画外台词原文（给 lint H3-D5）


_CJK = re.compile(r"[㐀-鿿]")


def _english(text: str) -> bool:
    outside = re.sub(r"<d>.*?</d>", " ", text or "", flags=re.S)
    return bool(outside.strip()) and not _CJK.search(outside)


def assemble(frames: int, body: str, soundscape: str, music: str = MUSIC) -> str:
    """四块结构：对齐句、空行、三个字段（字段之间空一行）"""
    body = body.strip()
    if not body.startswith("[Shot 1]"):
        body = "[Shot 1] " + body
    return (f"{alignment_line(frames)}\n\n{FIELDS[0]}: {body}\n\n{FIELDS[1]}: {(soundscape or '').strip()}"
            f"\n\n{FIELDS[2]}: {music}")


def replace_field(text: str, name: str, value: str) -> str:
    """替换已有 H3 提示词里的一个字段值（其它部分原样保留）；不是 H3 结构就原样返回"""
    if not (text or "").startswith(ALIGN_PREFIX):
        return text
    if name == FIELDS[0] and not value.strip().startswith("[Shot 1]"):
        value = "[Shot 1] " + value.strip()
    pat = re.compile(rf"(?m)^({re.escape(name)}:[ \t]?)(.*?)(?=\n\n[A-Za-z_]+:|\Z)", re.S)
    return pat.sub(lambda m: m.group(1) + value.strip(), text, count=1)


def speaker_key(note: str | None, names: tuple[str, ...] = ()) -> str:
    """说话人归并：括号里出现的角色名优先；否则取开头的 她/他；都没有就用整段说明"""
    note = (note or "").strip()
    for n in names:
        if n and n in note:
            return n
    if note[:1] in ("她", "他"):
        return note[:1]
    return note or "?"


def is_offscreen(note: str | None, stage: str | None = None) -> bool:
    t = f"{note or ''}{stage or ''}"
    return any(m in t for m in OFFSCREEN_MARKS)


def dialogue_sentences(dialogue, names: tuple[str, ...] = ()) -> tuple[list[str], dict[str, str], list[str]]:
    """剧本对白 → H3 句子（说话人说明用剧本括号原文，在 <d> 外；<d> 内只放 [Chinese] + 原文）"""
    ids: dict[str, str] = {}
    out, offscreen = [], []
    for d in dialogue or []:
        text = getattr(d, "text", None) if not isinstance(d, dict) else d.get("text")
        if not text or not text.strip():
            continue
        note = getattr(d, "speaker_note", None) if not isinstance(d, dict) else d.get("speaker_note")
        stage = getattr(d, "stage", None) if not isinstance(d, dict) else d.get("stage")
        key = speaker_key(note, names)
        sid = ids.setdefault(key, f"S{len(ids) + 1}")
        who = (note or "").strip()
        lead = f"{who} " if who else ""
        if is_offscreen(note, stage):
            offscreen.append(text)
            out.append(f"{lead}({sid}) {VO_PHRASE}: <d>[Chinese] {text}</d> {LIPS_CLOSED}")
        else:
            out.append(f"{lead}({sid}) says: <d>[Chinese] {text}</d>")
    return out, ids, offscreen


def strip_triggers(text: str, triggers: list[str]) -> str:
    for t in triggers or []:
        text = text.lstrip()
        for sep in ("，", ",", " "):
            if text.startswith(t + sep):
                text = text[len(t) + 1:]
                break
        else:
            if text.startswith(t):
                text = text[len(t):]
    return text.strip()


def build(shot, soundscape: str, *, frames: int | None = None, body_en: str | None = None,
          names: tuple[str, ...] = ()) -> H3Draft:
    """笔记本构建器。shot：ns_schema.script.Shot（或同名属性的对象）。"""
    frames = frames or frames_for_seconds(getattr(shot, "duration", 10) or 10)
    sents, ids, offscreen = dialogue_sentences(getattr(shot, "dialogue", None), names)
    if body_en and body_en.strip():
        body = body_en.strip()
    else:
        motion = strip_triggers(getattr(shot, "motion_prompt", "") or "", getattr(shot, "motion_triggers", []) or [])
        body = " ".join([x for x in [motion.rstrip("。.") + "。" if motion else ""] + sents if x])
    if not body.startswith("[Shot 1]"):
        body = "[Shot 1] " + body
    text = assemble(frames, body, soundscape)
    eb, es = _english(body), _english(soundscape)
    return H3Draft(text=text, body=body, soundscape=(soundscape or "").strip(), music=MUSIC, frames=frames,
                   source="laptop", english_body=eb, english_soundscape=es,
                   missing=[k for k, ok in (("body", eb), ("soundscape", es)) if not ok],
                   speakers=ids, offscreen=offscreen)


def for_shot(shot, soundscape: str, *, soundscape_edited: bool = False, body_edit: str | None = None,
             names: tuple[str, ...] = ()) -> H3Draft:
    """本镜的 H3 提示词：剧本 **H3提示词** 原样（画布只可改正文 / 环境声），否则笔记本构建器"""
    frames = frames_for_seconds(getattr(shot, "duration", 10) or 10)
    script_text = (getattr(shot, "h3_prompt", None) or "").strip("\n")
    _, ids, offscreen = dialogue_sentences(getattr(shot, "dialogue", None), names)
    if script_text:
        text = script_text
        if body_edit and body_edit.strip():
            text = replace_field(text, FIELDS[0], body_edit)
        if soundscape_edited and soundscape:
            text = replace_field(text, FIELDS[1], soundscape)
        f = parse_h3(text)["fields"]
        body, sc = f.get(FIELDS[0], ""), f.get(FIELDS[1], "")
        eb, es = _english(body), _english(sc)
        return H3Draft(text=text, body=body, soundscape=sc, music=f.get(FIELDS[2], ""), frames=frames,
                       source="script", english_body=eb, english_soundscape=es,
                       missing=[k for k, ok in (("body", eb), ("soundscape", es)) if not ok],
                       speakers=ids, offscreen=offscreen)
    return build(shot, soundscape, frames=frames, body_en=body_edit, names=names)


def lint_inputs(shot) -> dict:
    """lint_h3 的可选参数（剧本侧事实）：seconds、dialogue、offscreen、monologue"""
    _, _, offscreen = dialogue_sentences(getattr(shot, "dialogue", None))
    vo = getattr(shot, "voiceover", None)
    return {"seconds": getattr(shot, "duration", 10) or 10,
            "dialogue": [d.text for d in getattr(shot, "dialogue", []) or [] if d.text and d.text.strip()],
            "offscreen": offscreen,
            "monologue": [vo.text] if vo is not None and getattr(vo, "text", "") else []}
