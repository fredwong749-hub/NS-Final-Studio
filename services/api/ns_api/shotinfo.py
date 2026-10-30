"""
镜头卡需要的结构化字段（canvas-ui-spec-v2 §3.5.2）：运镜四要素、表情线索、剧本原文、尾帧提示词兜底。

这是 API 侧的**轻量版**解析（纯文本规则，确定性）。编译器（ns_agent.compiler）以后若输出同名字段，
以编译器为准：调用方先 getattr(compiled, ...)，没有才用这里的结果。
"""
import re

# 景别：长词在前，命中第一个
SIZE_WORDS = ("大远景", "远景", "大全景", "全景", "中全景", "全身", "中景", "中近景", "近景", "极近特写", "大特写",
              "特写", "极近")
ANGLE_WORDS = ("低机位仰拍", "高机位俯拍", "低机位", "高机位", "仰拍", "俯拍", "顶拍", "鸟瞰", "平视", "侧拍", "侧面",
               "背影", "过肩", "主观视角", "POV", "镜面倒影", "车内")
MOVE_EN = re.compile(r"((?:extreme )?slow motion|camera [a-z ]+|static camera|handheld(?: follow)?|orbit|"
                     r"push in|pull (?:back|out)|tracking(?: shot)?|dolly [a-z]+|pan (?:left|right)|tilt (?:up|down)|"
                     r"crane [a-z]+|zoom [a-z]+)", re.I)
MOVE_ZH = ("极缓推近", "缓慢推近", "缓推", "推近", "缓慢拉远", "拉远", "缓慢上摇", "上摇", "下摇", "左摇", "右摇", "跟拍",
           "环绕", "轻微手持", "手持", "固定", "慢动作", "定格", "升格", "甩镜")
LENS_RE = re.compile(r"(\d{2,3}\s?mm|广角|超广角|长焦|微距|鱼眼|移轴)")

# 表情线索：可观察的面部 / 呼吸 / 手部动作（Seedance 规范：2–4 个可观察线索）
EXPR_CUES = ("眼神", "眼里", "眼睛", "眼眶", "睫毛", "瞳孔", "嘴角", "嘴唇", "抿", "咬唇", "咬着", "笑", "泪", "哭",
             "脸红", "泛红", "红晕", "呼吸", "喘", "皱眉", "眉", "闭眼", "睁眼", "抬眼", "瞥", "害羞", "紧张", "委屈",
             "羞", "愣", "怔", "神情", "表情", "脸色", "颤", "咽", "叹", "绷紧", "发抖")
CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?]|——")
TRIGGER_PREFIX = re.compile(r"^([a-z0-9_]+[，,])+", re.I)


def strip_triggers(text: str) -> str:
    return TRIGGER_PREFIX.sub("", text or "").strip()


def _first(words: tuple[str, ...], text: str) -> str:
    hits = [(text.find(w), -len(w), w) for w in words if w in text]
    return min(hits)[2] if hits else ""


def parse_camera(text: str) -> dict:
    """从一段文字里拆出 景别 / 机位 / 运镜 / 焦段（各取第一个命中）"""
    text = text or ""
    m = MOVE_EN.search(text)
    move = m.group(1).strip() if m else ""
    zh = _first(MOVE_ZH, text)
    if zh and zh not in move:
        move = f"{move} {zh}".strip()
    lens = LENS_RE.search(text)
    return {"size": _first(SIZE_WORDS, text), "angle": _first(ANGLE_WORDS, text), "move": move,
            "lens": lens.group(1).replace(" ", "") if lens else ""}


def camera_info(edit_camera: str | None, img_prompt: str, motion_prompt: str) -> dict:
    """edit 优先（人工）；否则从剧本 img（景别/机位/焦段）+ motion（运镜）自动解析。

    人工 camera 字符串约定：画布按「景别，机位，运镜，焦段」顺序用中文逗号拼接，这里按同一规则拆回。
    人工写的部分沿用 edit，没写的部分仍用自动解析的值（各字段分别标 source）。"""
    img, mot = strip_triggers(img_prompt), strip_triggers(motion_prompt)
    auto = parse_camera(img)
    auto_m = parse_camera(mot)
    for k in ("size", "angle", "lens"):
        auto[k] = auto[k] or auto_m[k]
    auto["move"] = auto_m["move"] or auto["move"]
    out = {"text": "", "source": "none", "sources": {}}
    if edit_camera:
        e = parse_camera(edit_camera)
        if not any(e.values()):              # 没有可识别的词：整段当运镜
            e["move"] = edit_camera.strip()
        for k in ("size", "angle", "move", "lens"):
            out[k] = e[k] or auto[k]
            out["sources"][k] = "edit" if e[k] else ("auto" if auto[k] else "none")
        out["source"], out["text"] = "edit", edit_camera
    else:
        for k in ("size", "angle", "move", "lens"):
            out[k] = auto[k]
            out["sources"][k] = "auto" if auto[k] else "none"
        if any(auto[k] for k in ("size", "angle", "move", "lens")):
            out["source"] = "auto"
        out["text"] = "·".join(auto[k] for k in ("size", "angle", "move", "lens") if auto[k])
    return out


def expression_cues(img_prompt: str, motion_prompt: str, limit: int = 4) -> list[str]:
    """从 motion（优先）和 img 原文里抽出含表情线索的短句，最多 limit 条"""
    out: list[str] = []
    for text in (strip_triggers(motion_prompt), strip_triggers(img_prompt)):
        for c in CLAUSE_SPLIT.split(text):
            c = c.strip(" 、")
            if not c or MOVE_EN.match(c) or len(c) > 28:
                continue
            if any(w in c for w in EXPR_CUES) and c not in out:
                out.append(c)
            if len(out) >= limit:
                return out
    return out


def expression_info(edit_expression: str | None, img_prompt: str, motion_prompt: str) -> dict:
    if edit_expression:
        return {"text": edit_expression, "source": "edit", "cues": [edit_expression]}
    cues = expression_cues(img_prompt, motion_prompt)
    return {"text": "，".join(cues), "source": "auto" if cues else "none", "cues": cues}


def action_text(motion_prompt: str) -> str:
    """动作原文：去掉触发词和开头的运镜指令"""
    body = strip_triggers(motion_prompt)
    m = MOVE_EN.match(body)
    if m:
        body = body[m.end():].lstrip("，, ")
        zh = _first(MOVE_ZH, body[:8])
        if zh and body.startswith(zh):
            body = body[len(zh):].lstrip("，, ")
    return body


def script_text(img_note: str | None, motion_prompt: str) -> str:
    act = action_text(motion_prompt)
    return f"【{img_note}】{act}" if img_note else act


LAST_PREFIX = ("以图1（本镜首帧）为底图：保持人物面部、发型、妆容、服装、场景、光线与色调完全一致，"
               "只把画面改为镜头结束时的状态：")


def fallback_last_prompt(motion_prompt: str, image_style: str = "") -> str:
    """编译器还没有 last_prompt 时的兜底：motion 原文的最后两个动作分句 = 结束状态 ⚠ 规则待定"""
    clauses = [c.strip() for c in CLAUSE_SPLIT.split(action_text(motion_prompt)) if c.strip()]
    end = "，".join(clauses[-2:]) if clauses else ""
    return LAST_PREFIX + end + (f"，{image_style}" if image_style else "")


def focus(prompt: str, body: str) -> str:
    """从剧本原文出现的位置开始（跳过前面的角色 DNA 锁）；找不到就返回全文"""
    for k in (16, 10, 6):
        i = prompt.find(body[:k]) if len(body) >= k else -1
        if i > 0:
            return prompt[i:]
    return prompt


LAST_MARKERS = ("结束时的瞬间：", "结束时的状态：", "结束状态：", "只把画面改为")


def focus_last(prompt: str) -> str:
    """尾帧提示词跳过「保持图1…」固定前缀，从结束状态开始"""
    for m in LAST_MARKERS:
        i = prompt.find(m)
        if i >= 0:
            return prompt[i + len(m):].lstrip("：:，, ")
    return prompt
