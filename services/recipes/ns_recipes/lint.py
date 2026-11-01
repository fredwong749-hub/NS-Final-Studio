"""RenderPlan 静态校验（只查格式 / 参数一致性，不评内容）。level：error = 不能提交；warn = 提示写作方 / 总调度"""
from __future__ import annotations

import re

from . import graph as G
from .prompt import FIELDS, I2VA_LINE, REF_FIELDS

NEG_WORDS_RE = re.compile(r"\b(no|not|never|without|avoid|don't|doesn't|nothing|none|nobody|neither|nor)\b", re.I)


def _issue(level, code, msg):
    return {"level": level, "code": code, "message": msg}


def lint_prompt(text: str, mode: str, recipe: dict, spec=None, frames: int | None = None) -> list[dict]:
    out = []
    p = recipe.get("prompt", {})
    if mode == "ref2va":
        heads = [m.group(1) for m in re.finditer(r"^([a-z_]+):", text, re.M)]
        want = list(REF_FIELDS)
        if [h for h in heads if h in want] != want:
            out.append(_issue("error", "RL-R1", f"Ref2VA 六段顺序不对：{heads}"))
        m = re.search(r"^detailed_description:(.*?)(?=^overall_soundscape:)", text, re.M | re.S)
        n = len((m.group(1) if m else "").split())
        lo, hi = p.get("words_min"), p.get("words_max")
        if lo and n < lo:
            out.append(_issue("warn", "RL-R2", f"detailed_description {n} 词，官方建议 {lo}–{hi}（写作方补充细节）"))
    else:
        first = text.splitlines()[0] if text else ""
        if mode == "i2va" and first != I2VA_LINE:
            out.append(_issue("error", "RL-A1", "I2VA 第一行不是官方指令句"))
        if mode == "fl2va" and not first.startswith("How the reference pictures align"):
            out.append(_issue("error", "RL-A1", "FL2VA 第一行不是官方指令句"))
        if mode == "i2va" and re.search(r"\bPicture 2\b", text):
            out.append(_issue("error", "RL-A4", "I2VA 正文仍引用 Picture 2（没有送尾帧）"))
        if mode == "i2va" and re.search(r"(?<!<)\bPicture 1\b(?!>)", text):
            out.append(_issue("warn", "RL-A5", "I2VA 里 Picture 1 没写成 <Picture 1>"))
        heads = [m.group(1) for m in re.finditer(r"^([a-z_]+):", text, re.M)]
        if heads != list(FIELDS):
            out.append(_issue("error", "RL-A2", f"三字段不全或顺序不对：{heads}"))
    sm = re.search(r"^overall_soundscape:[ \t]*(.*)$", text, re.M)
    if p.get("require_soundscape") and (not sm or not sm.group(1).strip() or sm.group(1).strip() == "N/A"):
        out.append(_issue("error", "RL-S1", "overall_soundscape 为空（H3 不会处理静音，MiniMax HF #76）"))
    if p.get("period_before_d_close"):
        for m in re.finditer(r"<d>(.*?)</d>", text, re.S):
            if not re.search(r"[。！？!?.…—~～」”\"]\s*$", m.group(1)):
                out.append(_issue("warn", "RL-D1", f"</d> 前没有句末标点：…{m.group(1)[-12:]}（交写作方）"))
    outside = re.sub(r"<d>.*?</d>", " ", text, flags=re.S)
    if p.get("no_negative") and mode != "ref2va":
        body = outside.split("\n", 1)[-1]
        neg = sorted({w.lower() for w in NEG_WORDS_RE.findall(body)})
        if neg:
            out.append(_issue("warn", "RL-N1", f"<d> 外有否定词 {neg}（官方：否定会把概念写进去；交写作方）"))
    if len(text) > int(p.get("max_chars", 7000)):
        out.append(_issue("error", "RL-A12", f"提示词 {len(text)} 字符，超过 {p.get('max_chars')}"))
    if "off-screen voiceover" in text and "lips remain completely closed" not in text:
        out.append(_issue("warn", "RL-V1", "画外音 <d> 后缺官方句 “… lips remain completely closed.”（交写作方）"))
    if spec is not None:
        for c in spec.visible:
            if c.en_phrase and c.en_phrase.strip().rstrip(".") not in text:
                out.append(_issue("warn", "RL-X1", f"{c.name} 的人物表 EN外貌短语没有逐字出现在正文（交写作方）"))
        out += lint_people_eyeline(text, spec, p)
        if p.get("timeline", True) and frames:
            out += timeline_for_spec(text, spec, frames, int(recipe.get("frames", {}).get("fps", 24)))
        speakers = spec.on_screen_speakers
        mx = p.get("max_speakers")
        if mx and len(speakers) > mx:
            out.append(_issue("warn", "RL-D7", f"本镜画内说话人 {len(speakers)} 个，配方上限 {mx}"))
    return out


def lint_graph(wf: dict, recipe: dict, frames: int, w: int, h: int) -> list[dict]:
    out = []
    banned = set(recipe["sampling"].get("banned_nodes") or [])
    for nid, n in wf.items():
        if n["class_type"] in banned:
            out.append(_issue("error", "RL-G1", f"节点 {nid} {n['class_type']} 在禁用列表"))
    out += [_issue("error", "RL-G2", e) for e in G.dangling_links(wf)]
    fr = recipe["frames"]
    if (frames - 5) % 17 or not fr["min"] <= frames <= fr["max"]:
        out.append(_issue("error", "RL-G3", f"帧数 {frames} 不在 17k+5 网格或超出 {fr['min']}–{fr['max']}"))
    if w % 32 or h % 32:
        out.append(_issue("error", "RL-G4", f"分辨率 {w}×{h} 不是 32 的倍数"))
    mp = w * h / 1_000_000
    if mp > float(recipe["resolution"].get("max_megapixels_3090", 99)) + 1e-9:
        out.append(_issue("error", "RL-G5", f"{w}×{h} = {mp:.2f} MP 超过 3090 上限"))
    loras = [lo["file"].lower() for lo in G.enabled_loras(recipe).values()]
    turbo = [x for x in loras if "turbo" in x]
    shift = tuple(recipe["sampling"]["shift"])
    if turbo and all("768p" in x for x in turbo) and shift != (6.0, 3.0):
        out.append(_issue("error", "RL-G6", "768p Turbo LoRA 必须 shift 6/3"))
    if turbo and any("pika" in x for x in loras):
        out.append(_issue("error", "RL-G7", "Pika Flex 不能叠 Turbo"))
    if any(k in recipe["sampling"]["sampler"].lower() for k in ("ancestral", "sde")):
        out.append(_issue("error", "RL-G8", "H3 不用 ancestral / SDE 采样器"))
    return out


# ---------------------------------------------------------------------------------------------
# 时间轴（sysimpl-v2，ep02 v1 项目方 bug：切换生硬 / 表情互动生硬 / 时间轴粗 / 节奏慢）
# 只查格式与槽位是否齐（有没有时间、有没有写视线 / 表情 / 对方反应 / 衔接 / 结尾动作），不评写了什么。
# ---------------------------------------------------------------------------------------------
STAMP_RE = re.compile(r"\bAt (\d{1,2}):(\d{2}(?:\.\d{1,3})?),\s*")
# 自然语言分拍（备选写法：防官方切镜时间码被 H3 当成镜内硬切）：“At the 2-second mark,” / “At the 4.5-second mark,”
STAMP_NL_RE = re.compile(r"\bAt the (\d{1,2}(?:\.\d{1,2})?)-second mark,\s*")


def find_stamps(text: str) -> list[tuple[int, int, float]]:
    """→ [(start, end, 秒)]：两种分拍写法都认（官方时间码 `At 00:SS.mmm,` / 自然语言 `At the N-second mark,`）"""
    out = [(m.start(), m.end(), int(m.group(1)) * 60 + float(m.group(2))) for m in STAMP_RE.finditer(text)]
    out += [(m.start(), m.end(), float(m.group(1))) for m in STAMP_NL_RE.finditer(text)]
    return sorted(out)


GAZE_RE = re.compile(r"\b(eyes?|gaze[sd]?|gazing|look(?:s|ed|ing)?|glanc\w*|eyeline|star(?:e|es|ed|ing)|watch\w*|"
                     r"peer(?:s|ed|ing)?|pupils?)\b", re.I)
EXPR_RE = re.compile(r"\b(brows?|eyebrows?|lips?|mouth|jaw|eyelids?|lids|lashes|blink\w*|smil\w*|smirk\w*|frown\w*|"
                     r"swallow\w*|grimac\w*|purs\w*|bit(?:e|es|ing)|nostrils?|chin|wince\w*|squint\w*|"
                     r"expression)\b", re.I)
OPEN_RE = re.compile(r"\b(already|still|continu\w*|mid-\w+|keeps?)\b", re.I)
SETTLE_RE = re.compile(r"\b(settl\w*|holds? the pose|freez\w*|remains? still|stays? still|comes? to rest|"
                       r"stops? moving|motionless)\b", re.I)
ONGOING_END_RE = re.compile(r"\b(as the shot ends|still \w+ing|continues? to|keeps? \w+ing)\b", re.I)
SLOW_RE = re.compile(r"\b(slowly|gently|gradually|softly|lingering|languid\w*|leisurely|at slow speed)\b", re.I)
LISTEN_CLOSED_RE = re.compile(r"lips? (?:stay|stays|remain|remains|are|kept|pressed)?\s*(?:closed|shut|together)|"
                              r"closed lips|with (?:her|his) lips closed", re.I)
CUES = {"f": re.compile(r"\b(she|her|hers|herself|woman|girl)\b", re.I),
        "m": re.compile(r"\b(he|him|his|himself|man|guy)\b", re.I)}
P2_SENT_RE = re.compile(r"[^.!?]*\bPicture 2\b[^.!?]*[.!?]\s*$")
BEAT_MIN, BEAT_MAX, BEAT_HARD = 1.0, 2.6, 3.1
WORDS_PER_S_MIN = 15


def _sex(phrase: str | None) -> str | None:
    p = (phrase or "").lower()
    if re.search(r"\b(woman|girl|female|lady)\b", p):
        return "f"
    if re.search(r"\b(man|boy|male|guy)\b", p):
        return "m"
    return None


def split_beats(body: str, duration: float) -> list[dict]:
    """正文 → [{t0, t1, text}]：第一拍 = [Shot 1] 到第一个 At 时间；之后每个 `At 00:SS.mmm,` 一拍。
    FL2VA 末句（settles into … Picture 2）不算进最后一拍。"""
    b = re.sub(r"<d>.*?</d>", " <d/> ", body or "", flags=re.S)
    b = P2_SENT_RE.sub("", b.strip())
    stamps = find_stamps(b)
    out, pos, t = [], 0, 0.0
    for s, e, ts in stamps:
        out.append({"t0": t, "t1": ts, "text": b[pos:s]})
        pos, t = e, ts
    out.append({"t0": t, "t1": float(duration), "text": b[pos:]})
    return out


def lint_timeline(text: str, duration: float, *, sexes: list[str] | None = None, strict: bool = True,
                  allow_slow: bool = False, faces: bool = True) -> list[dict]:
    """sysimpl-v2 时间轴校验。strict=True（写作时用的是 sysimpl-v2）→ 缺项为 error（block）；否则只 warn。
    sexes：本镜在画、看得见脸的角色性别（'f' / 'm'），≥2 个不同性别时检查每拍有没有写到对方。
    faces=False：本镜没有露脸角色（手部 / 局部 / 空镜），不查视线和表情槽位。"""
    lv = "error" if strict else "warn"
    out = []
    m = re.search(r"(?:integrated_multimodal_description|detailed_description):\s*(.*?)(?=^\s*overall_soundscape:|\Z)",
                  text or "", re.S | re.M)
    body = (m.group(1) if m else text or "").strip()
    stamps = [x[2] for x in find_stamps(re.sub(r"<d>.*?</d>", "", body, flags=re.S))]
    if not stamps:
        out.append(_issue(lv, "RL-T1", f"正文没有按秒分拍（{duration:.2f}s 镜头应每 1.5–2 秒一个 `At 00:SS.mmm,`）"))
    else:
        if any(b <= a for a, b in zip(stamps, stamps[1:])) or stamps[0] <= 0:
            out.append(_issue(lv, "RL-T1", f"分拍时间不是严格递增或从 0 开始：{stamps}"))
        if stamps[-1] >= duration:
            out.append(_issue(lv, "RL-T1", f"分拍时间 {stamps[-1]:.2f}s 超过镜长 {duration:.2f}s"))
    beats = split_beats(body, duration)
    for i, bt in enumerate(beats):
        span = bt["t1"] - bt["t0"]
        tag = f"第 {i + 1} 拍 {bt['t0']:.1f}–{bt['t1']:.1f}s"
        if stamps and span > BEAT_HARD:
            out.append(_issue(lv, "RL-T2", f"{tag} 长 {span:.1f}s，超过 {BEAT_MAX}s（每 1.5–2 秒一拍）"))
        elif stamps and span > BEAT_MAX:
            out.append(_issue("warn", "RL-T2", f"{tag} 长 {span:.1f}s，建议 ≤ 2 秒"))
        elif stamps and 0 < span < BEAT_MIN and i < len(beats) - 1:
            out.append(_issue("warn", "RL-T2", f"{tag} 只有 {span:.1f}s，太碎"))
        tx = bt["text"]
        if faces and not GAZE_RE.search(tx):
            out.append(_issue(lv, "RL-T3", f"{tag} 没写视线落点（eyes / gaze / looks / glances …）"))
        if faces and not EXPR_RE.search(tx):
            out.append(_issue(lv, "RL-T3", f"{tag} 没写表情变化（brows / lips / mouth / jaw / blink / smile …）"))
        ss = sorted(set(sexes or []))
        if len(ss) >= 2 and not all(CUES[s].search(tx) for s in ss):
            out.append(_issue(lv, "RL-T4", f"{tag} 双人镜没写到另一位在画角色的可见反应"))
        if len(ss) >= 2 and "<d/>" in tx:
            nxt = beats[i + 1]["text"] if i + 1 < len(beats) else ""
            if not (LISTEN_CLOSED_RE.search(tx) or LISTEN_CLOSED_RE.search(nxt)):
                out.append(_issue("warn", "RL-T4", f"{tag} 台词拍没写听者 lips closed（防嘴型串到听者）"))
    if beats:
        first = beats[0]["text"]
        sents = re.split(r"(?<=[.!?])\s+", first.strip())
        if not OPEN_RE.search(" ".join(sents[1:]) or first):
            out.append(_issue("warn" if not strict else "error", "RL-T5",
                              "开头没有衔接句（锚点句后写第 0 秒已在进行的动作：already / still / continues / mid-）"))
        last = beats[-1]["text"]
        if SETTLE_RE.search(last):
            out.append(_issue(lv, "RL-T6", f"最后一拍写了定住类词 {SETTLE_RE.search(last).group(0)!r}（结尾要留仍在进行的动作）"))
        elif not ONGOING_END_RE.search(last):
            out.append(_issue("warn", "RL-T6", "最后一拍没写到镜尾仍在进行的动作（… as the shot ends）"))
    slow = sorted({w.lower() for w in SLOW_RE.findall(re.sub(r"<d>.*?</d>", " ", body, flags=re.S))})
    if slow and not allow_slow:
        out.append(_issue("warn", "RL-T7", f"正文有偏慢词 {slow}（项目方要求正常偏快节奏）"))
    nw = len(re.sub(r"<d>.*?</d>", " ", body, flags=re.S).split())
    if duration and nw / duration < WORDS_PER_S_MIN:
        out.append(_issue("warn", "RL-T7", f"正文 {nw} 词 / {duration:.1f}s = {nw / duration:.0f} 词每秒，动作量偏少（建议 18–25）"))
    return out


def timeline_for_spec(text: str, spec, frames: int, fps: int = 24, strict: bool | None = None) -> list[dict]:
    """compile 用：镜长取实际帧数 / fps；strict 默认看 Shot Spec 的写作规则版本是否含 sysimpl-v2 及以上"""
    if strict is None:   # 开关 config/recipes/timing_lint.json（默认 warn）+ 写作规则 ≥ sysimpl-v2
        from ns_schema.shot_spec import rules_at_least
        strict = spec is not None and rules_at_least(spec, 2)
    sexes = [s for s in (_sex(c.en_phrase) for c in (spec.faces if spec is not None else [])) if s]
    slow_ok = bool(spec is not None and spec.camera.speed == "slow")
    faces = spec is None or bool(spec.faces)
    return lint_timeline(text, frames / fps, sexes=sexes, strict=strict, allow_slow=slow_ok, faces=faces)


# ACTING 11-01（项目方 R11-9 原话：“当画面出现超过一个人,第二个等,他们面部表情,眼神是没有,这是剧本提示词的错误,写入剧本镜头规则
# 按照minimax h3的镜头提示词写”）：多人露脸镜，H3 正文里视线短语 / 表情短语的个数都要 ≥ 露脸人数（官方 ref-en 多人例：每人一句
# “Her annoyance softens as she looks toward …”）。系统固定提示句（prompt.eyeline_cue / open_motion_cue / min_motion_cue）不计。
# 粗检（按个数，不按人归属）：warn，交写作方（QW-W9 是写作侧逐人检查）。RL-E2：H3 正文写了看镜头 / 看观众
GAZE_EN_RE = re.compile(r"\b(?:eyes?|gaze|gazes|gazing|looks?|looking|glances?|glancing|stares?|staring|watch(?:es|ing)?|eyeline)\b", re.I)
EXPR_EN_RE = re.compile(r"\b(?:smil\w*|grin\w*|frown\w*|brows?|lips?|jaw|expression|scowl\w*|blush\w*|tears?|"
                        r"narrow\w*|soften\w*|tighten\w*|flinch\w*|wince\w*|smirk\w*|lashes|pout\w*|mouth)\b", re.I)
CAMERA_GAZE_RE = re.compile(r"\b(?:look(?:s|ing)?|star(?:es|ing)|gaz(?:es|ing)|glanc(?:es|ing))\s+(?:straight\s+|directly\s+)?"
                            r"(?:in(?:to)?|at|toward)\s+(?:the\s+)?(?:camera|lens|viewer|audience)\b|"
                            r"\b(?:eyes|gaze)\s+(?:on|to|toward|into)\s+(?:the\s+)?(?:camera|lens|viewer)\b|"
                            r"\beye contact with (?:the )?(?:camera|viewer|audience)\b", re.I)


SYS_CAMERA_FACING_RE = re.compile(r"\b(?:facing|faces|turned toward|turns toward|toward)\s+(?:the\s+)?(?:camera|lens|viewer)\b", re.I)



def system_facing_camera(text: str) -> str | None:
    """RL-E3 的派单期版本（K-OPS-Q24 扩展到提示词，AUDIT 20:15）：只看编译稿里的系统锚点句“The frame keeps …”，
    命中朝向镜头 → 返回命中片段。vidgen.PROMPT_FACING_RE 与本模块 SYS_CAMERA_FACING_RE 必须同一模式（测试核对）"""
    sys_txt = " ".join(re.findall(r"The frame keeps[^.]*\.", text or ""))
    m = SYS_CAMERA_FACING_RE.search(sys_txt)
    return m.group(0) if m else None

def lint_people_eyeline(text: str, spec, p: dict) -> list[dict]:
    out = []
    m = re.search(r"^(?:integrated_multimodal_description|detailed_description):(.*?)(?=^overall_soundscape:)", text or "", re.M | re.S)
    body = m.group(1) if m else (text or "")
    for k in ("eyeline_cue", "open_motion_cue", "min_motion_cue", "outfit_cue"):
        c = (p.get(k) or "").strip()
        if c:
            body = body.replace(c, " ")
    body = re.sub(r"<d>.*?</d>", " ", body, flags=re.S)
    # VIDEO-RCA 11-01（RL-E3）：系统编译句（锚点句 / 站位词表）不得让人朝向镜头——写作方正文另由 RL-E2 管
    sys_txt = " ".join(re.findall(r"The frame keeps[^.]*\.", text or "")) + " " + " ".join(
        (p.get(k) or "") for k in ("eyeline_cue", "open_motion_cue", "min_motion_cue", "outfit_cue"))
    fc = SYS_CAMERA_FACING_RE.search(sys_txt)
    if fc:
        out.append(_issue("error", "RL-E3", f"编译稿含朝向镜头的系统句：“{fc.group(0)}”（K-REN-702：首帧 / 正文朝镜头 → 片头看镜头 49/54）"))
    cg = CAMERA_GAZE_RE.search(body)
    if cg:
        out.append(_issue("warn", "RL-E2", f"H3 正文写了看镜头：“{cg.group(0)}”（项目方 R11-2：演员不看镜头；交写作方）"))
    n = len(getattr(spec, "faces", None) or [])
    if n >= 2:
        g, e = len(GAZE_EN_RE.findall(body)), len(EXPR_EN_RE.findall(body))
        if g < n or e < n:
            out.append(_issue("warn", "RL-E1", f"多人镜 {n} 张露脸，H3 正文视线短语 {g} 个、表情短语 {e} 个，少于人数"
                                               f"（R11-9：每个在画的人都要写视线和表情；交写作方）"))
    return out
