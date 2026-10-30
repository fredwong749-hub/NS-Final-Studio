"""Who says what: script_v2.json shots → spoken lines with a resolved speaker.

The importer keeps the script's notes verbatim (DialogueLine.speaker_note: "顾沉低声", "她，很小声", "他",
"合上盒子" ...). This module turns them into speaker ids (config/voices.json "characters"):

- a named character anywhere in the note wins by position ("画外，店员的招呼声" → clerk);
- 她 / 自言自语 / 自答 / 对镜 → lin_wan;
- 他 → the male in the shot: a named male in the same shot's notes, else in its prompts
  (img/motion/raw dialogue), else the last male of the episode, else 顾沉;
- a note without a speaker ("合上盒子", "停顿两秒", "一顿") continues the previous speaker;
- no note: a continuation of an unclosed quote (importer split on "／") keeps the speaker, otherwise turns
  alternate (A, B, A ...);
- notes the importer left inside the text ("（她，一口气）“……") are pulled out; pure stage text
  ("（沉默三秒）", "—", "（无——全镜无对白…）") is not spoken.

Voiceover (🎙) is always 林晚's inner voice in this script.
"""

import re
from dataclasses import asdict, dataclass

LEAD_NOTE = re.compile(r"^\s*[（(]([^（）()]*)[）)]\s*")
PAREN = re.compile(r"[（(][^（）()]*[）)]")
SPLIT_INLINE = re.compile(r"[（(]([^（）()]*)[）)]")

NAMED = (  # (token, speaker id); searched by position in the note
    ("女穿孔师", "piercer"), ("穿孔师", "piercer"), ("纹身师", "tattooist"),
    ("男同事", "male_coworker"), ("同事", "coworker"), ("店员", "clerk"),
    ("顾沉", "gu_chen"), ("陈宇", "chen_yu"), ("林晚", "lin_wan"),
    ("Alex", "alex"), ("Ryan", "ryan"), ("Kai", "kai"), ("Leo", "leo"),
    ("四声齐", "chorus_men"), ("四个男人齐", "chorus_men"),
)
HER = ("她", "自言自语", "自答", "对镜")
HIM = ("他",)
MALES = {"gu_chen", "chen_yu", "tattooist", "male_coworker", "alex", "ryan", "kai", "leo"}
MALE_NAMES = (("顾沉", "gu_chen"), ("陈宇", "chen_yu"), ("纹身师", "tattooist"), ("男同事", "male_coworker"),
              ("Alex", "alex"), ("Ryan", "ryan"), ("Kai", "kai"), ("Leo", "leo"))
DEFAULT_MALE = "gu_chen"
NARRATOR = "lin_wan"
SILENT_MARKERS = ("留白", "无对白", "无——")


@dataclass(frozen=True)
class SpokenLine:
    kind: str  # dialogue | voiceover
    shot: int  # shot index (1-based)
    line: int  # 0-based index among the shot's spoken lines (dialogue); 0 for the voiceover
    speaker: str
    text: str  # cleaned for TTS
    note: str = ""  # speaker note / voiceover note, verbatim
    raw: str = ""  # script text as imported
    how: str = ""  # how the speaker was resolved (for the timeline)

    @property
    def key(self) -> str:
        return f"S{self.shot}#{self.line}" if self.kind == "dialogue" else f"S{self.shot}#vo"

    def to_dict(self) -> dict:
        return asdict(self)


def tts_text(text: str) -> str:
    """Script text → what the TTS reads: no quotes/markdown/stage parentheses, dashes become pauses."""
    t = PAREN.sub("", text or "")
    for a, b in (("“", ""), ("”", ""), ("‘", ""), ("’", ""), ('"', ""), ("*", ""), ("「", ""), ("」", ""),
                 ("\\", ""), ("～", "，"), ("~", "，")):
        t = t.replace(a, b)
    t = re.sub(r"—{1,}", "，", t)
    t = re.sub(r"…+|\.{3,}", "…", t)
    t = re.sub(r"[，,]\s*([。？！?!…])", r"\1", t)
    t = re.sub(r"([，。？！…])[，]+", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.lstrip("，。、；：").strip()
    return t


def speakable(text: str) -> bool:
    if any(m in (text or "") for m in SILENT_MARKERS) and not re.search(r"[“\"]", text or ""):
        return False
    t = tts_text(text)
    return any(ch.isalnum() for ch in t)


def speaker_from_note(note: str | None) -> tuple[str | None, str]:
    """(speaker id or None for "he"/unknown, kind) where kind is named | her | him | none."""
    if not note:
        return None, "none"
    hits = []
    for token, sid in NAMED:
        i = note.find(token)
        if i >= 0:
            hits.append((i, -len(token), sid, "named"))
    for token in HER:
        i = note.find(token)
        if i >= 0:
            hits.append((i, -len(token), NARRATOR, "her"))
    for token in HIM:
        i = note.find(token)
        if i >= 0:
            hits.append((i, -len(token), None, "him"))
    if not hits:
        return None, "none"
    _, _, sid, kind = min(hits)
    return sid, kind


def shot_males(shot: dict) -> list[str]:
    """Named males mentioned in the shot (notes first, then prompts), in order of first mention."""
    found: list[str] = []
    for line in shot.get("dialogue") or []:
        sid, kind = speaker_from_note(line.get("speaker_note"))
        if kind == "named" and sid in MALES and sid not in found:
            found.append(sid)
    text = " ".join(str(shot.get(k) or "") for k in ("dialogue_raw", "img_prompt", "motion_prompt"))
    hits = sorted((text.find(tok), sid) for tok, sid in MALE_NAMES if tok in text)
    for _, sid in hits:
        if sid not in found:
            found.append(sid)
    return found


def _segments(line: dict) -> list[tuple[str | None, str, str]]:
    """One importer line → [(note, text, raw)]: pulls a leading "（note）" out of the text and splits
    "（她）完了。（他）这是什么？" into two lines."""
    note, text = line.get("speaker_note"), line.get("text") or ""
    raw = text
    if note is None:
        m = LEAD_NOTE.match(text)
        if m:
            note, text = m.group(1).strip() or None, text[m.end():]
    parts = SPLIT_INLINE.split(text)
    # parts = [text0, note1, text1, note2, text2 ...]
    out = [(note, parts[0], raw)]
    for i in range(1, len(parts) - 1, 2):
        n, t = parts[i].strip(), parts[i + 1]
        sid, kind = speaker_from_note(n)
        if kind in ("named", "her", "him") and speakable(t):
            out.append((n, t, raw))
        else:  # a mid-line action ("然后笑倒"): stays with the current line
            note0, t0, r0 = out[-1]
            out[-1] = (note0, t0 + t, r0)
    return out


def resolve_episode(episode: dict, overrides: dict[str, str] | None = None) -> list[SpokenLine]:
    """All spoken lines of an episode in script order (per shot: dialogue lines, then the voiceover)."""
    overrides = overrides or {}
    ep = int(episode.get("number", 0))
    last_male = None
    lines: list[SpokenLine] = []
    for shot in episode.get("shots") or []:
        idx = int(shot["index"])
        males = shot_males(shot)
        shot_male = males[0] if males else (last_male or DEFAULT_MALE)
        speakers: list[str] = []
        open_quote = False
        n = 0
        for line in shot.get("dialogue") or []:
            for note, text, raw in _segments(line):
                continuation = open_quote
                if "“" in text or "”" in text:
                    open_quote = text.count("“") > text.count("”") or (open_quote and "”" not in text)
                if not speakable(text):
                    continue
                sid, kind = speaker_from_note(note)
                if kind == "named":
                    how = f"note:{note}"
                elif kind == "her":
                    how = f"note:{note}"
                elif kind == "him":
                    sid = shot_male
                    how = f"he→{sid} ({'shot' if males else 'episode/default'})"
                elif note and speakers:  # an action note: same speaker continues
                    sid, how = speakers[-1], f"action note '{note}' → previous speaker"
                elif continuation and speakers:
                    sid, how = speakers[-1], "continuation of the quote"
                elif len(speakers) >= 2 and speakers[-1] != speakers[-2]:
                    sid, how = speakers[-2], "alternating turns"
                elif speakers:
                    sid = shot_male if speakers[-1] == NARRATOR else NARRATOR
                    how = "alternating turns"
                else:
                    sid, how = NARRATOR, "no note: 林晚"
                key = f"ep{ep:02d}-S{idx}#{n}"
                if key in overrides:
                    sid, how = overrides[key], "config line_overrides"
                if sid in MALES:
                    last_male = sid
                speakers.append(sid)
                lines.append(SpokenLine("dialogue", idx, n, sid, tts_text(text), note or "", raw, how))
                n += 1
        vo = shot.get("voiceover")
        if vo and speakable(vo.get("text") or ""):
            key = f"ep{ep:02d}-S{idx}#vo"
            sid = overrides.get(key, NARRATOR)
            lines.append(SpokenLine("voiceover", idx, 0, sid, tts_text(vo["text"]), vo.get("note") or "",
                                    vo["text"], "voiceover = 林晚 inner voice" if key not in overrides
                                    else "config line_overrides"))
    return lines
