"""写作方表演 / 视线 / 节奏机检 QW-A1–A5（ACTING 2026-11-01；规则与出处见 docs/acting/PERFORMANCE_RULES.md）。

项目方原话：
  R11-2 “演员的眼睛不要看镜头……剧情镜头还是很慢”
  R11-3 “对于没有render video的集数,重写修改剧本bugs,不看镜头,镜头节奏很慢,通过修改时间轴的提示词”
  R11-6 “演员的眼神,表情,语气等应该怎么做才合理有画面感”
  R11-8 “每个镜头第一帧,演员都看着镜头,而且停顿1秒多,这个是不合理的”
  R11-9 “当画面出现超过一个人,第二个等,他们面部表情,眼神是没有……按照minimax h3的镜头提示词写”

  QW-A1  每拍写视线落点（视线= 不空，不写“前方 / 远处 / 虚空”这类没有落点的词）                 K-WRT-A01
  QW-A2  不写看镜头 / 直视镜头 / 看观众（分拍、img、motion、H3）                                     K-WRT-A02
  QW-A3  节奏：第一拍（从 0 秒起）就有看得见的动作；拍长 ≤ 2.5 秒；不连着两拍都是静止 / 保持          K-WRT-A03
  QW-A4  每拍写表情（表情= 不空，写具体的面部动作，不写“情绪复杂 / 很激动”这类空词）                   K-WRT-A04
  QW-A5  多人镜：除本拍主角外，每个在画的人都在 反应= 里写出“名字：视线 + 表情”；H3 正文视线 / 表情短语数 ≥ 在画人数  K-WRT-A05
  ── SCRIPT-RSI 11-01（项目方 18:2x“所有图片不要看镜头……把演员的演戏规则、导演的规则、镜头的规则都做上去”，D-SCR-07）──
  QW-A6  脸 / 身体朝向不写“正面朝镜头 / 面向镜头 / 正对镜头”，H3 不写 facing the camera / front view：朝向写成朝某人或某物  K-WRT-A06
  QW-A7  img（首帧的唯一来源）里每个在画的人都写视线落点（看谁 / 看什么）；首帧看镜头 → 片头看镜头 49/54        K-WRT-A07
  QW-A8  H3 正文第一个时间码之前写出首帧时在画的人的视线落点；单人镜正文也要有视线短语                            K-WRT-A08
  QW-AX1  轴线：同一场景相邻两镜同两人左右位置互换（越轴），衔接里要写明“越轴 / HARD CUT”                         K-WRT-104

只查格式与可实现性，不评价剧情。级别跟 writer_lints.WRITER_LINT_LEVEL（导入关口 warn；写作链路 p4_adapter / qwen_repair_loop 为 block）。
"""
from __future__ import annotations

import re

RULES: dict[str, tuple[str, str]] = {
    "QW-A1": ("warn", "每一拍的 视线= 写出具体落点：画内的人（名字 / 部位）、物件，或画外有名有姓的声源；不空着，不写“前方 / 远处 / 虚空”"),
    "QW-A2": ("warn", "任何地方都不写看镜头：不写“看向镜头 / 直视镜头 / 对着镜头笑 / 看着观众”，H3 不写 looks into the camera / at the lens / at the viewer"),
    "QW-A3": ("warn", "节奏：第一拍（0 秒起）就写一个看得见的动作（动作已经在进行，不是先定住再开始）；每拍 ≤ 2.5 秒；不要连着两拍都是“保持 / 定住 / 静止”"),
    "QW-A4": ("warn", "每一拍的 表情= 写具体面部动作（眉、眼睑、嘴角、下颌、呼吸），不空着，不写“情绪复杂 / 很激动 / 很有张力”这类空词"),
    "QW-A5": ("warn", "多人镜：本拍主角以外，每个在画的人都在 反应= 里写“名字：视线落点 + 表情”（例 反应=顾沉：视线落在她手上，下颌绷紧）；"
                      "H3 正文每个在画的人各有一句视线和表情"),
    "QW-A6": ("warn", "脸和身体的朝向不写“正面朝镜头 / 面向镜头 / 正对镜头 / 朝着镜头”（出图会让人直视镜头），写成朝向画里的人或物"
                      "（例：四分之三侧脸朝向顾沉 / 身体朝向窗边）；H3 不写 facing the camera / toward the camera / front view"),
    "QW-A7": ("warn", "img 是首帧的唯一来源：每个在画的人都写一句视线落点——看画里的谁或什么（例：林晚的视线落在顾沉的手上；顾沉垂眼看着文件）；"
                      "不写“看着前方 / 远处”，闭眼、背对写明即可；落点在画外时写方位 + 物（视线投向画面右侧的门口），img 和结束状态（motion 里 —— 之后那段）都不写画外角色的名字（QW-CH4）"),
    "QW-A8": ("warn", "H3 正文第一个时间码（At 00:0x）之前，写出开场那一刻每个在画的人眼睛落在哪里（例：her eyes resting on the bowl in her hands）；"
                      "单人镜正文里也至少写一处视线"),
    "QW-AX1": ("warn", "轴线：同一场景相邻两镜、同样两个人，**人物** 行里的左右位置不要互换（越轴会让视线方向反过来）；确实要越轴，就在 **衔接** 里写“越轴”或 HARD CUT 并说明原因"),
}

TIME_SPLIT = re.compile(r"[；;](?=\s*\d+(?:\.\d+)?\s*(?:秒|s)?\s*[–\-~～至到]\s*\d)")
BEAT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[–\-~～至到]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[｜|]?\s*")
EMPTY = ("", "—", "-", "–", "无", "同上", "/")
# SCRIPT-RSI 11-01：画外 / 方向词单独出现也没有落点（E1：画外要写有名有姓的声源）——“对面 / 画外 / 一旁 / 上方”补进来
VAGUE_GAZE = re.compile(r"^(?:看着?|望着?|盯着?|看向|望向|投向|移向|落在|停在)?(?:前方|远处|虚空|空中|空气|远方|某处|前面|对面|画外|画面外|"
                        r"一旁|旁边|侧面|一侧|左侧|右侧|左边|右边|上方|下方|别处|四周|远处某处)$")
# QW-A6 朝向镜头（中文）：正对 / 朝向 / 面向 / 面朝 / 朝着 / 朝 + 镜头；前 3 字有 侧 / 背 / 腰 / 臀 / 腿 / 鞋 / 脚 的是侧面或身体局部朝向，不算
FACE_CAM_ZH = re.compile(r"(?:正对|朝向|面向|面朝|朝着|对着|朝)镜头")
FACE_CAM_SKIP = re.compile(r"[侧背腰臀腿鞋脚膝]")
FACE_CAM_EN = re.compile(r"\b(?:facing|faces|face|turned|turns|turning)\b[^.,;]{0,24}?\b(?:camera|lens|viewer)\b|\bfront view\b", re.I)
# QW-A7 img 视线词（去掉写实套话“眼睛为真实人眼大小”后再查）
IMG_GAZE = re.compile(r"视线|目光|眼神|看|望|盯|瞥|注视|凝视|垂眼|垂眸|抬眼|闭眼|闭着眼|闭上眼|阖眼|对视|眼睛半闭|眼睛望|眼睛看")
IMG_NOGAZE_OK = re.compile(r"背对|背影|背身|背朝|后脑")
IMG_VAGUE = re.compile(r"(?:视线|目光|眼神)(?:落在|看向|望向|投向|停在)?(?:前方|远处|虚空|远方|画外|某处|空中)(?![的里中处]?[一-鿿]{0,2}(?:人|门|窗|灯|桌|她|他))")
REALISM_EYES = re.compile(r"眼睛为真实人眼大小")
STAMP_RE = re.compile(r"\bAt \d{1,2}:\d{2}")
VAGUE_EXPR = re.compile(r"^(?:情绪复杂|复杂|很激动|激动|很有张力|有张力|戏剧性|强烈|有情绪|情绪|丰富|自然|正常|平常|一般)$")
# 看镜头（中文）：看 / 望 / 盯 / 直视 / 注视 / 凝视 / 视线 / 眼神 / 目光 … 镜头 / 观众 / 摄像机；“侧面朝向镜头 / 背对镜头”是身体朝向，不算
CAM_ZH = re.compile(r"(?:看|望|盯|瞥|直视|注视|凝视|对视|瞪|视线|眼神|目光|眼睛)[^，。；｜、]{0,4}(?:镜头|观众|摄像机|屏幕前)|"
                    r"对着镜头(?:笑|看|眨|抛|挑|眯|勾)|迎着镜头")
CAM_EN = re.compile(r"\b(?:look(?:s|ing)?|star(?:es|ing)|gaz(?:es|ing)|glanc(?:es|ing))\s+(?:straight\s+|directly\s+)?"
                    r"(?:in(?:to)?|at|toward)\s+(?:the\s+)?(?:camera|lens|viewer|audience)\b|"
                    r"\b(?:eyes|gaze)\s+(?:on|to|toward|into)\s+(?:the\s+)?(?:camera|lens|viewer)\b|"
                    r"\beye contact with (?:the )?(?:camera|viewer|audience)\b", re.I)
STATIC_RE = re.compile(r"^(?:保持|仍然|仍旧|依旧|依然|定住|定格|静止|凝固|不动|停住|停在|维持|静静)")
MOVE_RE = re.compile(r"抬|转|看向|望向|移向|眨|吸气|呼气|起伏|伸|握|捏|抓|松开|走|迈|起身|坐下|站起|落|推|拉|放下|拿|递|接过|"
                     r"笑|皱|咬|抿|靠|低头|抬头|侧头|摇头|点头|颤|抖|摸|抚|拨|撩|按|敲|点|翻|滑|跪|俯|仰|回身|回头|侧身|"
                     r"倾|贴近|后退|前倾|挪|蹭|抱|搂|吻|舔|喘|垂眼|闭眼|睁眼|眯|扬|挑眉|收紧|放松|摆|晃|跳|闪|亮|升|飘|压")
GAZE_ZH = re.compile(r"看|望|盯|瞥|视线|目光|眼神|垂眼|抬眼|闭眼|眼睛|眸|对视|注视|凝视")
EXPR_ZH = re.compile(r"嘴|唇|眉|笑|皱|抿|咬|下颌|下巴|睫|脸|神情|表情|泪|红|眯|瞪|绷|松|颤|呼吸|喘|鼻|舌")
GAZE_EN = re.compile(r"\b(?:eyes?|gaze|gazes|gazing|looks?|looking|glances?|glancing|stares?|staring|watch(?:es|ing)?)\b", re.I)
EXPR_EN = re.compile(r"\b(?:smil\w*|grin\w*|frown\w*|brows?|lips?|jaw|expression|scowl\w*|blush\w*|tears?|narrow\w*|"
                     r"soften\w*|tighten\w*|flinch\w*|wince\w*|smirk\w*|lashes|pout\w*|mouth)\b", re.I)
BEAT_MAX_S = 2.5
LEVEL = {"value": "warn"}


def _issue(rule_id: str, detail: str, field: str) -> dict:
    return {"rule_id": rule_id, "level": LEVEL["value"], "detail": detail, "field": field, "rule": RULES[rule_id][1]}


def _kv(rest: str) -> dict:
    out = {}
    for p in re.split(r"[｜|]", rest):
        m = re.match(r"^\s*([^=＝]{1,4})\s*[=＝]\s*(.*)$", p)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def parse_beats(text: str) -> list[dict]:
    out = []
    for it in (x.strip() for x in TIME_SPLIT.split(text or "") if x.strip()):
        m = BEAT_RE.match(it)
        if not m:
            continue
        rest = it[m.end():]
        parts = [p.strip() for p in re.split(r"[｜|]", rest)]
        action = next((p for p in parts if p and "=" not in p and "＝" not in p), "")
        kv = _kv(rest)
        out.append({"t0": float(m.group(1)), "t1": float(m.group(2)), "action": action, "gaze": kv.get("视线", ""),
                    "expr": kv.get("表情", ""), "react": kv.get("反应", ""), "raw": it})
    return out


HOLD_RE = re.compile(r"一动不动|静止|定格|凝固|停顿|定住|僵住|保持不动|静静地(?:站|坐|躺)着?$")


def _moving(b: dict) -> bool:
    """动作栏不空、不以“保持 / 定住 / 静止…”开头、也不含“一动不动 / 定格 / 停顿”（宁可漏报：动词表列不全，不按动词表判有没有动）"""
    a = b["action"]
    return bool(a) and not STATIC_RE.match(a) and not HOLD_RE.search(a)


def _h3_body(h3: str) -> str:
    m = re.search(r"(?:integrated_multimodal_description|detailed_description):(.*?)(?=overall_soundscape:|$)", h3 or "", re.S)
    return re.sub(r"<d>.*?</d>", " ", m.group(1) if m else (h3 or ""), flags=re.S)


def person_clauses(body: str, names: list[str]) -> dict:
    """img 按逗号 / 分号切小句，按主语归人（SCRIPT-RSI 11-01；frame_job._covered 用同一套切法）：
    小句以某人名字开头 → 主语换成他；“她 / 他 / 双手…”等无名小句沿用上一个主语；
    小句里出现“<名字>的视线 / 目光 / 眼神”也记给这个人。→ {名字: 归给他的小句拼起来}"""
    out = {n: "" for n in names}
    cur = None
    for cl in re.split(r"[，,；;。]", body or ""):
        c = cl.strip()
        if not c:
            continue
        lead = next((n for n in names if c.startswith(n) or c[1:].startswith(n)), None)
        if lead:
            cur = lead
        for n in names:
            if re.search(re.escape(n) + r"(?:的)?(?:视线|目光|眼神|垂眼|垂眸|抬眼|闭眼|看|望|盯|瞥)", c):
                out[n] += c + "，"
        if cur:
            out[cur] += c + "，"
    return out


def check_shot(sh, ep, img: str, size: str | None, fields: dict | None = None, level: str = "warn") -> list[dict]:
    LEVEL["value"] = level
    out: list[dict] = []
    fields = fields or {}
    beats_txt = fields.get("分拍", "")
    on = [c.name for c in (sh.cast or []) if c.presence == "在画"]
    beats = parse_beats(beats_txt)
    tag = lambda b: f"{b['t0']:g}–{b['t1']:g}秒"  # noqa: E731
    # QW-A2 看镜头（任何字段）
    for field, txt in (("分拍", beats_txt), ("img", img or ""), ("motion", sh.motion_prompt or "")):
        m = CAM_ZH.search(txt)
        if m:
            out.append(_issue("QW-A2", f"{field} 写了看镜头：「{m.group(0)}」", field))
    h3 = getattr(sh, "h3_prompt", None) or ""
    m = CAM_EN.search(_h3_body(h3))
    if m:
        out.append(_issue("QW-A2", f"H3 写了看镜头：“{m.group(0)}”", "H3提示词"))
    # QW-A6 朝向镜头（img / 分拍 / motion；H3）
    for field, txt in (("img", img or ""), ("分拍", beats_txt), ("motion", sh.motion_prompt or "")):
        for m in FACE_CAM_ZH.finditer(txt):
            if not FACE_CAM_SKIP.search(txt[max(0, m.start() - 3):m.start()]):
                out.append(_issue("QW-A6", f"{field} 写了朝向镜头：「{txt[max(0, m.start() - 4):m.end()]}」（写成朝向画里的人或物）", field))
                break
    m = FACE_CAM_EN.search(_h3_body(h3))
    if m and not re.search(r"\bback\b", m.group(0), re.I):
        out.append(_issue("QW-A6", f"H3 写了朝向镜头：“{m.group(0)}”", "H3提示词"))
    # QW-A7 img 里每个在画的人都写视线落点（首帧来源）
    if on and img:
        body = REALISM_EYES.sub("", img)
        segs = person_clauses(body, [n for n in on if n in body])
        for n, seg in segs.items():
            if IMG_NOGAZE_OK.search(seg):
                continue
            if not IMG_GAZE.search(seg):
                out.append(_issue("QW-A7", f"img 里 {n} 没写视线落点（首帧会默认看镜头）：写“{n}的视线落在<画里的人 / 物>上”；"
                                           f"落点在画外时写方位 + 物（“视线投向画面右侧的门口”），img 和结束状态都不写画外角色的名字（QW-CH4）", "img"))
            elif IMG_VAGUE.search(seg):
                out.append(_issue("QW-A7", f"img 里 {n} 的视线「{IMG_VAGUE.search(seg).group(0)}」没有落点（写看谁 / 看什么）", "img"))
    # QW-A8 H3：首帧视线（第一个时间码之前）+ 单人镜也要有视线
    if on and h3:
        body = _h3_body(h3)
        st = STAMP_RE.search(body)
        head = body[:st.start()] if st else body
        if not GAZE_EN.search(head):
            out.append(_issue("QW-A8", "H3 正文第一个时间码之前没写开场时的视线落点（例：her eyes resting on the bowl）", "H3提示词"))
        elif len(on) == 1 and not GAZE_EN.search(body):
            out.append(_issue("QW-A8", "H3 正文没有视线短语", "H3提示词"))
    if not beats:
        return out
    faces = bool(on)
    # QW-A1 / QW-A4 每拍视线、表情（有在画的人才要求）
    if faces:
        for b in beats:
            g = b["gaze"].strip()
            if g in EMPTY:
                out.append(_issue("QW-A1", f"{tag(b)} 没写 视线=", "分拍"))
            elif VAGUE_GAZE.match(g):
                out.append(_issue("QW-A1", f"{tag(b)} 视线=「{g}」没有落点（写看谁 / 看什么）", "分拍"))
            e = b["expr"].strip()
            if e in EMPTY:
                out.append(_issue("QW-A4", f"{tag(b)} 没写 表情=", "分拍"))
            elif VAGUE_EXPR.match(e):
                out.append(_issue("QW-A4", f"{tag(b)} 表情=「{e}」是空词（写眉、眼睑、嘴角、下颌的具体动作）", "分拍"))
    # QW-A3 节奏
    first = min(beats, key=lambda b: b["t0"])
    if first["t0"] <= 0.5 and not _moving(first):
        out.append(_issue("QW-A3", f"第一拍 {tag(first)} 没有看得见的动作（「{first['action'][:16]}」）：镜头一开始就要在动，不是先定住",
                          "分拍"))
    for b in beats:
        if b["t1"] - b["t0"] > BEAT_MAX_S + 1e-6:
            out.append(_issue("QW-A3", f"{tag(b)} 一拍 {b['t1'] - b['t0']:.1f} 秒，超过 {BEAT_MAX_S} 秒（拆成两拍、各写一个动作）", "分拍"))
    srt = sorted(beats, key=lambda b: b["t0"])
    for a, b in zip(srt, srt[1:]):
        if not _moving(a) and not _moving(b):
            out.append(_issue("QW-A3", f"{tag(a)} 与 {tag(b)} 连着两拍都没有动作（静止 / 保持）", "分拍"))
            break
    # QW-A5 多人镜：每个在画的人都有视线 + 表情
    if len(on) >= 2:
        prev = on[0]
        for b in srt:
            # 本拍主角 = 动作栏里最先出现的在画人名；没写名字（“她抬眼”）沿用上一拍主角。视线栏里的名字是被看的人，不算主角
            hits = sorted((b["action"].find(n), n) for n in on if n in b["action"])
            subj = hits[0][1] if hits else prev
            prev = subj
            for other in (n for n in on if n != subj):
                seg = ""
                m = re.search(re.escape(other) + r"\s*[:：]?(.{0,40}?)(?=(?:[；;]\s*[^\d\s；;]{1,6}\s*[:：])|$)", b["react"])
                if m:
                    seg = other + m.group(1)
                if not seg:
                    out.append(_issue("QW-A5", f"{tag(b)} 多人镜：{other} 在画，反应= 里没写 {other}（写“{other}：视线落点 + 表情”）", "分拍"))
                    continue
                miss = [w for w, rx in (("视线", GAZE_ZH), ("表情", EXPR_ZH)) if not rx.search(seg)]
                if miss:
                    out.append(_issue("QW-A5", f"{tag(b)} 多人镜：{other} 的反应缺{'和'.join(miss)}（「{seg[:20]}」）", "分拍"))
        if h3:
            body = _h3_body(h3)
            g, e = len(GAZE_EN.findall(body)), len(EXPR_EN.findall(body))
            if g < len(on) or e < len(on):
                out.append(_issue("QW-A5", f"H3 正文在画 {len(on)} 人，视线短语 {g} 个、表情短语 {e} 个（每人各写一句视线和表情，"
                                           f"如 “He glances at her hand, his jaw tight.”）", "H3提示词"))
    return out


def check_episode(ep, fields: dict | None = None) -> list[dict]:
    """QW-AX1 轴线（K-WRT-104，SCRIPT-RSI 11-01）：同场景相邻两镜，同样两个在画的人左右互换，且衔接没写越轴 / HARD CUT"""
    out = []
    shots = sorted(getattr(ep, "shots", []) or [], key=lambda s: s.index)
    pos = lambda sh: {c.name: getattr(c, "x", None) for c in (sh.cast or []) if c.presence == "在画" and getattr(c, "x", None) in ("左", "右")}  # noqa: E731
    for a, b in zip(shots, shots[1:]):
        if not a.scene_id or a.scene_id != b.scene_id:
            continue
        pa, pb = pos(a), pos(b)
        common = [n for n in pa if n in pb]
        flips = [(x, y) for i, x in enumerate(common) for y in common[i + 1:]
                 if pa[x] != pa[y] and pb[x] != pb[y] and pa[x] == pb[y]]
        link = f"{getattr(b, 'link', '') or ''}{getattr(b, 'link_carry', '') or ''}{((fields or {}).get((ep.number, b.index)) or {}).get('衔接', '')}"
        if flips and not re.search(r"越轴|HARD CUT|翻转|反打越轴", link, re.I):
            x, y = flips[0]
            iss = _issue("QW-AX1", f"镜{a.index}→镜{b.index} 同在 {a.scene_id}：{x}{pa[x]}/{y}{pa[y]} 变成 {x}{pb[x]}/{y}{pb[y]}（越轴）", "人物")
            iss["shot"] = b.index
            out.append(iss)
    return out
