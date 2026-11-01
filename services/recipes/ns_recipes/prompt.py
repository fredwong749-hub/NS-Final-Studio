"""H3 提示词（确定性组装，严格按官方格式）。

官方：data/ab/owner_workflows/minimax_h3_official_skills/h3-prompt-writing/references/base-en.txt（I2VA / FL2VA）、
ref-en.txt（Ref2VA 六段）。

边界：正文内容只来自写作方（Shot Spec 的 h3.text 与人物表 EN / VOICE 短语）。本模块只做**格式**：
- 指令行按模式生成（I2VA / FL2VA，S.SS 按实际帧数）；
- I2VA 时按官方 Case 2 把 `Picture 1` 写成 `<Picture 1>`、删掉引用不存在的 Picture 2 的子句（conformance B3 / F1）；
- 重试时在 [Shot 1] 风格句之后插入本镜锚点句（官方 fallback 第 1 次重试），锚点只拼写作方给的英文短语 + 站位词表；
- Ref2VA 六段的标签定义 / summary / retention 是结构句，detailed_description 是写作方正文加 <Subject N> 标签。
写作方没写 H3 正文 → 返回 needs_writer，系统不代写。
"""
from __future__ import annotations

import re

from ns_schema.shot_spec import ShotSpec

I2VA_LINE = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
FL2VA_FMT = ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
             "0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {s}-second mark of the "
             "target video.")
FIELDS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
REF_FIELDS = ("subject_definitions", "summary", "retention_analysis", "detailed_description",
              "overall_soundscape", "non_diegetic_music")

POS_EN = {"左": "on the left side of the frame", "中": "in the center of the frame", "右": "on the right side of the frame"}
DEPTH_EN = {"前": "in the foreground", "中": "in the midground", "后": "in the background"}
# VIDEO-RCA 11-01：“镜头”只表示身体朝向画面前方；不再写 facing the camera（重试锚点句里 127/538 条编译稿带这句，
# 等于让演员对镜头——与 R11-2 / K-REN-G02 冲突；首帧看镜头 → 片头看镜头 49/54，见 docs/video_rca/RCA_r1.md）
FACING_EN = {"镜头": "with the body turned toward the front of the frame and the gaze angled off to one side", "左": "facing frame-left", "右": "facing frame-right",
             "背对": "with the back to the camera", "侧左": "in profile facing frame-left",
             "侧右": "in profile facing frame-right", "侧": "in profile"}


class NeedsWriter(Exception):
    """缺写作方内容（H3 正文等），不能编译"""


def seconds_label(frames: int, fps: int = 24) -> str:
    return f"{frames / fps:.2f}"


def split_fields(text: str) -> tuple[str | None, dict[str, str]]:
    """→ (第一行指令或 None, {字段: 值})。字段按 'name:' 开头识别，值可跨行（合并成一段）"""
    lines = (text or "").strip("\n").splitlines()
    first = None
    if lines and not any(lines[0].lstrip().startswith(f + ":") for f in FIELDS + REF_FIELDS):
        first = lines[0].strip()
        lines = lines[1:]
    out: dict[str, str] = {}
    cur = None
    for ln in lines:
        m = re.match(r"^\s*([a-z_]+):\s?(.*)$", ln)
        if m and m.group(1) in FIELDS + REF_FIELDS:
            cur = m.group(1)
            out[cur] = m.group(2).strip()
        elif cur and ln.strip():
            out[cur] = (out[cur] + " " + ln.strip()).strip()
    return first, out


_SETTLE_RE = re.compile(r",?\s*(?:and\s+)?(?:(?:she|he|they|it|the [a-z ]{1,30}?)\s+)?settles?\s+into\s+[^.]*?"
                        r"established by Picture 2(?: at the end of the shot)?", re.I)
_SENT_P2_RE = re.compile(r"[^.!?]*\bPicture 2\b[^.!?]*[.!?]\s*")


def to_i2va_body(body: str) -> tuple[str, list[str]]:
    """FL2VA 正文 → I2VA 正文（官方 Case 2）。只改图片引用，不改其余文字。→ (正文, 改动说明)"""
    notes = []
    b = body
    new = _SETTLE_RE.sub("", b)
    if new != b:
        notes.append("删去 settles into … established by Picture 2 子句")
        b = new
    new = _SENT_P2_RE.sub("", b)
    if new != b:
        notes.append("删去其余引用 Picture 2 的句子")
        b = new
    new = re.sub(r"(?<!<)\bPicture 1\b(?!>)", "<Picture 1>", b)
    if new != b:
        notes.append("Picture 1 → <Picture 1>")
        b = new
    b = re.sub(r"\s+\.", ".", b)
    b = re.sub(r"(?<!\.)\.\.(?!\.)", ".", b)   # 整句 “She settles into … Picture 2 …” 删掉后留下的 “..”（PROMPT v2）
    b = re.sub(r"\s{2,}", " ", b).strip()
    return b, notes


def anchor_sentence(spec: ShotSpec) -> str | None:
    """重试锚点句：在画角色 EN 外貌短语 + 造型 EN + 站位 / 朝向（词表映射），地标只取写作方给的 EN"""
    parts = []
    for c in spec.visible:
        if not c.en_phrase:
            continue
        p = c.en_phrase.strip().rstrip(".")
        if c.look:
            p += f" in {c.look.strip().rstrip('.')}"
        pos = [x for x in (POS_EN.get(c.screen_x or ""), DEPTH_EN.get(c.depth or ""), FACING_EN.get(c.facing or "")) if x]
        if pos:
            p += " " + ", ".join(pos)
        parts.append(p)
    lms = [lm.name for lm in spec.scene.landmarks if lm.name and lm.name.isascii()]
    if not parts and not lms:
        return None
    s = "The frame keeps " + "; ".join(parts) if parts else "The frame keeps the established layout"
    if lms:
        s += ", with " + ", ".join(lms) + " in place"
    return s + "."


def _insert_after_style(body: str, sentence: str) -> str:
    m = re.match(r"^(\[Shot 1\]\s*(?:Live-action, cinematic(?:, shallow depth of field)?,)?)\s*", body)
    if m:
        return body[:m.end(1)] + " " + sentence + " " + body[m.end():]
    return sentence + " " + body


# VIDEO-RCA 11-01（K-REN-701）：景别看不见的下半身部件（鞋 / 高跟 / 脚 / 腿…）出现在描述句里 → H3 拉远或下摇去“画出来”。
# 同出图 framing.HIDE（K-REN-101）的取舍表，只作用于正文第一句（[Shot 1] 构图 + 人物外貌造型），不动分拍动作句；
# 只删“以逗号 / and 分隔的造型分句”，不改写作方用词。开关 prompt.hide_offframe_parts（_base 默认值见 provenance）。
_LOWER_EN = r"skirt|miniskirt|trousers?|pants|jeans|legs?|knees?|thighs?|heels?|stilettos?|shoes?|sneakers?|boots?|socks?|stockings?|feet|foot|toes?|ankles?|pumps"
_FEET_EN = r"heels?|stilettos?|shoes?|sneakers?|boots?|socks?|feet|foot|toes?|ankles?|pumps"
_HIDE_EN = {"极近特写": _LOWER_EN, "大特写": _LOWER_EN, "特写": _LOWER_EN, "中近景": _LOWER_EN, "近景": _LOWER_EN,
            "中景": _FEET_EN}


def hide_offframe_parts(body: str, size: str | None) -> tuple[str, list[str]]:
    """→ (正文, 删掉的分句)。只处理第一句：按 ', ' 切成分句，再按 ' with ' / ' and ' 切成单品；
    含该景别隐藏词的单品删掉，分句里其余单品保留（“an ivory blouse with a dark grey pencil skirt and a cropped blazer”
    在近景 → “an ivory blouse and a cropped blazer”）。构图 / 机位分句（begins / camera / shot）不动。"""
    pat = _HIDE_EN.get(size or "")
    if not pat:
        return body, []
    m = re.match(r"(.*?\.)(\s|$)", body, re.S)
    if not m:
        return body, []
    rx = re.compile(r"\b(?:" + pat + r")\b", re.I)
    keep, gone = [], []
    for i, part in enumerate(m.group(1).rstrip(".").split(", ")):
        if i == 0 or not rx.search(part) or re.search(r"\b(?:begins|camera|shot)\b", part, re.I):
            keep.append(part)
            continue
        toks = re.split(r"\s+(with|and)\s+", part)        # [单品, 连接词, 单品, …]
        items, joins = toks[0::2], toks[1::2]
        left = [(j, it) for j, it in zip([None] + joins, items) if not rx.search(it)]
        gone += [it for it in items if rx.search(it)]
        if left and left[0][1] == items[0]:
            s = left[0][1]
            for j, it in left[1:]:
                s += f" {j} {it}"
            keep.append(s)
    if not gone:
        return body, []
    return ", ".join(keep) + "." + body[m.end(1):], gone


def build_base(spec: ShotSpec, recipe: dict, mode: str, frames: int, attempt: int = 1) -> dict:
    """I2VA / FL2VA 提示词。→ {text, fields, notes}"""
    if not spec.h3.text:
        raise NeedsWriter(f"{spec.id} 没有 H3 正文")
    _first, f = split_fields(spec.h3.text)
    body = f.get("integrated_multimodal_description")
    if not body:
        raise NeedsWriter(f"{spec.id} H3 正文缺 integrated_multimodal_description")
    notes = []
    if mode == "i2va":
        body, n = to_i2va_body(body)
        notes += n
        line = I2VA_LINE
    elif mode == "fl2va":
        line = FL2VA_FMT.format(s=seconds_label(frames))
    else:
        raise ValueError(f"build_base 不处理模式 {mode}")
    if (recipe.get("prompt") or {}).get("hide_offframe_parts"):
        body, gone = hide_offframe_parts(body, getattr(spec.camera, "size", None))
        if gone:
            notes.append("删去景别外造型分句（prompt.hide_offframe_parts）：" + " | ".join(gone))
    # ACTING 11-01（R11-2 / R11-8）：开头即动 + 视线落点，两句系统固定提示（_base.yaml prompt.open_motion_cue / eyeline_cue），
    # 放在第一个分拍时间码之前（官方 I2VA 顺序：首帧锚点 → 动作起势 → 连续发展；没有时间码就放句末）
    for key in ("open_motion_cue", "eyeline_cue", "outfit_cue"):   # outfit_cue：VIDEO-RCA 11-01 服装保持（待验 VRCA-E5）
        c2 = ((recipe.get("prompt") or {}).get(key) or "").strip()
        if c2 and c2 not in body:
            m = re.search(r"\bAt (?:\d{1,2}:\d{2}|the \d)", body)
            body = (body[:m.start()] + c2 + " " + body[m.start():]) if m else (body.rstrip() + " " + c2)
            notes.append(f"插入系统提示句（prompt.{key}）")
    cue = (recipe.get("prompt") or {}).get("min_motion_cue")
    if cue:
        # VIDEO10 11-01（ep01-S2 固定机位微表演，4 个 seed 动作量 0.34–0.44 < 0.5）：系统层“最低动作”提示句，
        # 只描述物理（呼吸、重心、眨眼、动作做完整），不加剧情内容；放在第一个分拍时间码之前（没有时间码就放句末）
        m = re.search(r"\bAt (?:\d{1,2}:\d{2}|the \d)", body)
        body = (body[:m.start()] + cue.strip() + " " + body[m.start():]) if m else (body.rstrip() + " " + cue.strip())
        notes.append("插入最低动作提示句（prompt.min_motion_cue）")
    if attempt >= 2 and recipe.get("prompt", {}).get("retry_anchor_prefix"):
        a = anchor_sentence(spec)
        if a:
            body = _insert_after_style(body, a)
            notes.append(f"第 {attempt} 次：插入锚点句")
    sound = f.get("overall_soundscape") or (spec.audio.soundscape_en or "")
    if not f.get("overall_soundscape") and sound:
        notes.append("overall_soundscape 取自剧本【H3 audio】")
    music = f.get("non_diegetic_music") or "N/A"
    text = (f"{line}\n\nintegrated_multimodal_description: {body}\n\n"
            f"overall_soundscape: {sound}\n\nnon_diegetic_music: {music}")
    return {"text": text, "fields": {"integrated_multimodal_description": body, "overall_soundscape": sound,
                                     "non_diegetic_music": music}, "notes": notes, "first_line": line}


def build_ref2va(spec: ShotSpec, recipe: dict, frames: int, ref_slots: list[dict], attempt: int = 1) -> dict:
    """官方 ref-en 六段。ref_slots：[{role: first_frame}, {role: identity, character: name}, …]，顺序 = <Picture N> 编号"""
    base = build_base(spec, recipe, "i2va", frames, attempt)
    body = base["fields"]["integrated_multimodal_description"]
    pic_of = {}
    for i, s in enumerate(ref_slots, 1):
        pic_of[(s["role"], s.get("character"))] = i
    subj_lines, ret_lines, subj_of = [], [], {}
    k = 0
    for c in spec.visible:
        if not c.en_phrase:
            continue
        k += 1
        subj_of[c.name] = k
        src = pic_of.get(("identity", c.name))
        osrc = pic_of.get(("outfit", c.name))
        look = f", wearing {c.look.strip().rstrip('.')}" if c.look else ""
        if osrc:   # 造型参考（去头的设定图正面栏）：只取服装 / 鞋 / 饰品，不取脸、姿势和背景
            look += f" exactly as shown in <Picture {osrc}> (outfit reference only: clothing, shoes and accessories)"
        if src:
            subj_lines.append(f"<Subject {k}> is {c.en_phrase.strip().rstrip('.')} whose face and hair come from "
                              f"<Picture {src}>{look}.")
        else:
            subj_lines.append(f"<Subject {k}> is {c.en_phrase.strip().rstrip('.')}{look}.")
        ret_lines.append(f"<Subject {k}> (appears in [Shot 1]): fully_preserved - identity, face, hairstyle and "
                         f"clothing follow the reference" + (f"; the outfit follows <Picture {osrc}>, ignoring its pose, "
                                                              f"its background and its missing head." if osrc else "."))
    ff = pic_of.get(("first_frame", None))
    if ff:
        subj_lines.insert(0, f"<Picture {ff}> is the first frame of [Shot 1].")
        ret_lines.insert(0, f"<Picture {ff}> ([Shot 1] first frame): fully_preserved - the opening composition, "
                            f"positions and lighting.")
    kinds = (["keyframe completion"] if ff else []) + (["reference generation"] if subj_of else [])
    subj_list = " and ".join(f"<Subject {n}>" for n in subj_of.values()) or "the subjects"
    summary = f"[{' + '.join(kinds) or 'reference generation'}] The target video " \
              + (f"begins from <Picture {ff}> and " if ff else "") + f"keeps the identities of {subj_list} in a single shot."
    # 正文：去掉 I2VA 里的 <Picture 1>（首帧在 Ref2VA 里编号可能不同）→ 用 ff 编号；EN 短语后加 <Subject N>
    if ff:
        d = body.replace("<Picture 1>", f"<Picture {ff}>")
    else:
        # 纯 Ref2VA（不给首帧）：参考图不是首帧（ref-en §2.2），去掉“begins in … established by <Picture 1>”首帧锚定子句
        d = re.sub(r"\s*begins in the (?:position|pose)[^.]*?established by <Picture 1>", "", body)
        d = re.sub(r",?[^,.]*\bestablished by <Picture 1>", "", d)
        d = d.replace("<Picture 1>", "the opening frame")
        d = re.sub(r",\s*,", ",", d)
    for c in spec.visible:
        n = subj_of.get(c.name)
        if n and c.en_phrase and c.en_phrase in d:
            d = d.replace(c.en_phrase, f"{c.en_phrase} (<Subject {n}>)", 1)
    style = recipe.get("prompt", {}).get("style_lead", "").strip().rstrip(",")
    d = re.sub(r"^\[Shot 1\]\s*Live-action, cinematic(?:, shallow depth of field)?,\s*", "[Shot 1] ", d)
    d = re.sub(r"^\[Shot 1\] ([a-z])", lambda m: "[Shot 1] " + m.group(1).upper(), d)
    style_sentence = f"The target video is {style.lower()}." if style else ""
    detailed = f"{style_sentence}\n{d}".strip()
    parts = {
        "subject_definitions": "\n".join(subj_lines),
        "summary": summary,
        "retention_analysis": "\n".join(ret_lines),
        "detailed_description": detailed,
        "overall_soundscape": base["fields"]["overall_soundscape"],
        "non_diegetic_music": base["fields"]["non_diegetic_music"],
    }
    text = "\n\n".join(f"{k}: {v}" for k, v in parts.items())
    return {"text": text, "fields": parts, "notes": base["notes"] + ["Ref2VA 六段（ref-en）"], "first_line": None}
