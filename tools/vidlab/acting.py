"""VIDLAB 表演节拍（线 2“表情死板”根因实验；只写物理微动作，不写剧情 / 情绪内容，Claude 只写系统）。

两种系统层写法（A/B 用，通过后再进编译层 services/recipes/ns_recipes/prompt.py，带 recipe 开关 prompt.acting_*）：
- ACT_CUE：一句全局“脸一直在演”提示（放在视线句之后、第一个分拍时间码之前，同 open_motion_cue 的位置规则）。
- micro_beats(body)：在每个 “At 00:0X” 分拍句末尾补一个微表情分句（眉 / 眨眼 / 呼吸 / 嘴角，按拍轮换），
  主语取该拍里第一个 his/her/he/she；最后一拍插在 “as the shot ends” 之前。依据：MiniMax-H3 HF #96 “几乎不眨眼，建议写明第几秒眨眼”
  （docs/research/h3_deep/01_official.md）；官方指南“按时间写可观察变化”。
"""
from __future__ import annotations

import re

ACT_CUE = ("Every visible face keeps acting the whole time with small natural micro-expressions: the brows lift and draw "
           "together slightly as each thought changes, the eyelids blink naturally every two to three seconds, a slow breath "
           "visibly rises in the chest and shoulders, and the lips and jaw keep shifting subtly between the lines.")

MICRO = ["{p} brows lifting slightly as {s} blinks",
         "a slow breath rising in {p} chest",
         "{p} brows drawing together for a moment as {s} blinks twice",
         "the corners of {p} mouth tightening briefly"]
PRON = {"his": ("his", "he"), "he": ("his", "he"), "her": ("her", "she"), "she": ("her", "she")}
BEAT = re.compile(r"\bAt \d{2}:\d{2}(?:\.\d+)?,")


def _subject(seg: str) -> tuple[str, str] | None:
    s = re.sub(r"<d>.*?</d>", " ", seg)
    m = re.search(r"\b(his|her|he|she)\b", s, re.I)
    return PRON[m.group(1).lower()] if m else None


def micro_beats(body: str, offset: int = 0) -> tuple[str, list[str]]:
    starts = [m.start() for m in BEAT.finditer(body)]
    if not starts:
        return body, []
    out, notes, last = [], [], 0
    bounds = starts + [len(body)]
    out.append(body[:starts[0]])
    for k, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        seg = body[a:b]
        sub = _subject(seg)
        if not sub:
            out.append(seg)
            continue
        clause = MICRO[(k + offset) % len(MICRO)].format(p=sub[0], s=sub[1])
        if " as the shot ends" in seg:
            seg2 = seg.replace(" as the shot ends", f", {clause}, as the shot ends", 1)
        else:
            m = re.search(r"\.(\s*)$", seg)
            seg2 = (seg[:m.start()] + f", {clause}." + m.group(1)) if m else seg
        if seg2 != seg:
            notes.append(clause)
        out.append(seg2)
    return "".join(out), notes
