"""写作方 P4 机检（ITERAUDIT 2026-11-01，项目方原话：“记得每一次发现bugs,找到solution后,把规则写到系统code去,这样,剧本llm更好去自动改进”）。

把今晚在出图 / 出片里发现、已在系统层修过的问题，同时变成写作方能看到（writer_knowledge.md，compile.py 生成）和
P4 校验能拦（这里的 QW-W*，接进 tools/validate_qwen_script.py）的规则，让写作模型的自动返修环自己改：

  QW-W1  外层衣物（西装外套 / 风衣 / 开衫…）在画就要写进 img（ep01 西装外套漏写，系统事后补丁）        K-WRT-Q01
  QW-W2  分拍全是“保持 / 定住 / 静止”，整镜没有一个看得见的身体动作（ep01-S2 出成静止画面）          K-WRT-Q03
  QW-W3  只有 🎙 的镜：说话人在画时不写开口 / 张嘴 / 说话类动作，嘴型写闭合（独白镜嘴在动）            K-WRT-Q04
  QW-W4  下装写明具体品类：不用“西装裙 / 套裙 / 职业裙”（铅笔裙写成西装裙，被画成西裤）               K-WRT-Q05
  QW-T1 / P2  单镜时长按台词需要、总时长靠加镜不靠拉长（R11-2 / R11-3 节奏慢；固定 warn）           K-WRT-Q07
  QW-W9  人物在画的特写 / 近景 / 中景：img 光线写“光源 + 方向 / 落点”（RESEARCH 真人写实调研）             K-WRT-X05
  QW-W10 局部特写写的是手，动作句又写到肩 / 颈 / 锁骨 / 胸口（ep05-S3/S5 驳回 8 次，VIDEO10 W5）            K-WRT-V10
  QW-W11 分拍写了对身上正穿着的衣服的整理动作（抚平外套下摆…）：视频把外套先脱再穿（VIDEO-RCA 8/8）       K-WRT-702
  QW-W12 穿外套的人在一镜里做坐→站 / 站→坐 / 起身离开等大幅姿态变化：外套会变形，拆成“站定起始”的下一镜（VIDEO-RCA r4） K-WRT-704
  （QW-CH6 局部角色不写脸 / 头发：已在 validate_qwen_script 里，规则 K-WRT-Q02 补写作方说明）

级别：WRITER_LINT_LEVEL（默认 "warn"，导入关口不因旧稿拦死）；写作链路（tools/pipeline/p4_adapter.py、
tools/qwen_repair_loop.py）设为 "block"，这样不过就进返修环。只查格式与可实现性，不评价剧情。
"""
from __future__ import annotations

import re

WRITER_LINT_LEVEL = "warn"

RULES: dict[str, tuple[str, str]] = {
    "QW-W1": ("warn", "本镜造型里的外层衣物（西装外套 / 风衣 / 大衣 / 开衫 / 披肩…）在画时必须写进 img（写品名，脱下 / 搭在手臂也写明）"),
    "QW-W2": ("warn", "分拍里至少一拍写一个看得见的身体动作（抬手、转头、视线移向、呼吸起伏、起身…）；“保持 / 定住 / 静止 / 凝固”不算动作"),
    "QW-W3": ("warn", "只有 🎙（没有台词）的镜：说话人在画时嘴是闭着的——分拍 / motion 不写开口、张嘴、说话、嘴唇动；**嘴型** 写 <角色>=闭合"),
    "QW-W5": ("warn", "衔接写“接力｜承：动作｜<动作>”时，本镜 img 或第一拍要接上这个动作 / 物件（同一个手部动作、同一件物件）"),
    "QW-W4": ("warn", "下装写明具体品类和长度（铅笔裙 / 包臀裙 / A字裙 / 百褶裙 / 直筒西裤 / 阔腿裤…）；不用“西装裙 / 套裙 / 职业裙”（会被画成西裤）"),
    # RSI r3（R11-2 / R11-3 节奏慢，K-WRT-Q07）：级别固定 warn——返修环不能改镜数和时长（repair_chain 不变量），只在写 P4 初稿时起作用
    "QW-T1": ("warn", "单镜时长按需要写：没有台词 / 独白的镜 ≤6 秒；有台词的镜不超过 max(6, 台词字数 ÷ 4.5 + 1.5) 秒；多出来的时间拆成新镜，不是拉长这一镜"),
    # RESEARCH（R11-12 / R11-13 真人写实调研，K-WRT-X05）：光线写成“光源 + 方向 / 落点”，没有落点的光会被画成均匀平光
    "QW-W9": ("warn", "人物在画的特写 / 近景 / 中景，img 的光线写成“光源 + 方向或落点”（例：台灯暖光从右侧逆光勾出发丝与颈线）；"
                      "只写“暖黄居家灯光 / 光线柔和”这类没有方向的光，出图会落成均匀平光、脸更像磨皮"),
    # VIDEO10 W5（总调度 11-01，CONSENT ITERAUDIT -> VIDEO10）：系统把这种镜的局部扩大为“手与肩颈”（ns_agent.framing.part_name），
    # 写作方要么把手以外的部位移出本镜，要么把景别写成近景；只查可实现性，不评价内容
    "QW-W10": ("warn", "局部 / 大特写写的是手（手套、指尖、握笔…），同一句又写到肩、颈、锁骨或胸口：模型会出成带肩颈 / 脸的近景。"
                       "只要手，就把肩颈部位挪到下一镜；肩颈也要入画，就把景别写成“近景（手与肩颈）”"),
    "QW-T2": ("warn", "目标总时长用镜数凑，不用拉长单镜：本集平均镜长 >6.5 秒、而镜数还没到上限时，先加镜（无台词过渡 / 反应 / 局部特写镜）"),
    # RSI r7（VIDEO-RCA r2 实测，K-WRT-702）：分拍写了对身上正穿着的衣服的整理动作 → 8/8 外套先消失再穿回；去掉这一拍 0/2
    "QW-W11": ("warn", "分拍动作不要写对身上正穿着的衣服的整理动作（抚平外套下摆、拉衣角、收紧衣领 / smooths the hem of her blazer…）："
                       "视频模型会把外套先脱掉再穿回。想表达整理 / 镇定，写不碰衣服的动作：手放回身侧、深吸一口气、肩膀放松"),
    # VIDEO-RCA r4（总调度 11-02 定 K-WRT-704 转正，CONSENT ITERAUDIT -> VIDEO_RCA）：ep01-S3 坐→站外套变形 10/10，
    # 拆成“镜 B 从站定开始”2/2 外套保持；与 DIRECTOR K-EDT-811（大动作不叠运镜）/ K-EDT-812（动作匹配切）对齐
    "QW-W12": ("warn", "穿外套 / 西装 / 大衣的人，不在一镜里做完坐→站、站→坐、起身离开这类大幅姿态变化：视频里外套会变形或消失。"
                       "拆成两镜：这一镜停在准备起身，下一镜从已经站好开始（衔接写“接力｜承：动作｜起身”，剪辑用动作匹配切）"),
}
# QW-W12：全身姿态切换词（中文分拍 / H3 英文分拍）
POSE_CHANGE_ZH = re.compile(r"起身|站起|站了起来|坐下|坐回|落座|从椅子上站|离开座位|起立")
POSE_CHANGE_EN = re.compile(r"\b(rises?|rising|rose|stands? up|standing up|stood up|gets? up|getting up|got up|sits? down|sitting down|sat down)\b", re.I)
# QW-W11：动作词 + 衣物词（同一拍 / 同一英文分句里）。中文分拍和 H3 英文分拍都查
GARMENT_ACT_ZH = re.compile(r"(整理|抚平|抹平|理了理|理一理|拉了拉|拉一拉|拉紧|拉直|拽|扯|收紧|掀起|撩起|扣上|系紧|拢了拢|拢紧|捋平)"
                            r"[^，。；｜]{0,8}(外套|西装|西服|大衣|风衣|夹克|开衫|裙摆|裙子|裙|衣摆|衣角|衣领|领口|袖口|下摆|衬衫)")
NOT_GARMENT_ACT = re.compile(r"\b(eyes|gaze|glance|head|chin|face)\b", re.I)     # “lifts her eyes to the coat”是视线，不是整理衣服
GARMENT_OFF = re.compile(r"脱|解开|褪下|滑落|take[sn]? off|taking off|slips? off|slid off|remov(?:e|es|ed|ing)|unbutton|unzip|strip", re.I)
GARMENT_ACT_EN = re.compile(r"\b(smooth|adjust|tug|straighten|tighten|pull|draw|lift|tuck|button|zip|fix|smooth)(?:s|es|ed|ing)?\b"
                            r"[^.;]{0,40}?\b(blazer|jacket|coat|skirt|blouse|shirt|collar|cuff|hem|sleeve|lapel)s?\b", re.I)
PACE_MAX_S = 6.0          # K-WRT-005：单镜 ≤6 秒（超过剪辑会拆刀）
PACE_AVG_S = 6.5          # 本集平均镜长线（K-EDT-I01 剪辑每刀 ≤4.5 秒；单镜一刀时写作侧放宽到 6.5）
SPEECH_CPS = 4.5          # 中文台词每秒字数（defect_hunt DH-S06 用 5 字 / 秒为“说不完”上限）

OUTER_WORDS = ("西装外套", "西服外套", "外套", "西服", "风衣", "大衣", "夹克", "开衫", "披肩", "斗篷", "皮衣", "羽绒服", "马甲",
               "blazer", "Blazer")
OUTER_RE = re.compile("|".join(sorted(map(re.escape, OUTER_WORDS), key=len, reverse=True)))
HIDE_SIZES = ("大特写", "极近特写")
STATIC_RE = re.compile(r"^(?:保持|仍然|仍旧|依旧|依然|定住|定格|静止|凝固|不动|停住|停在|维持)")
MOVE_RE = re.compile(r"抬|转|看向|望向|移向|眨|呼吸|吸气|呼气|起伏|伸|握|捏|抓|松开|走|迈|起身|坐下|站起|落|推|拉|放下|拿|递|接过|"
                     r"笑|皱|咬|抿|靠|低头|抬头|侧头|摇头|点头|颤|抖|摸|抚|拨|撩|按|敲|点|翻|滑|跪|俯|仰|回身|回头|侧身|"
                     r"倾|贴近|后退|前倾|挪|蹭|抱|搂|吻|舔|喘|垂眼|闭眼|睁眼|眯|扬|挑眉|收紧|放松|摆|晃")
TIME_SPLIT = re.compile(r"[；;](?=\s*\d+(?:\.\d+)?\s*(?:秒|s)?\s*[–\-~～至到]\s*\d)")
BEAT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[–\-~～至到]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[｜|]?\s*")
SPEAK_RE = re.compile(r"开口|张嘴|张口|说话|说道|低声说|轻声说|小声说|念出|念着|嘴唇(?:[^，。；]{0,4})(?:动|翕|开合|蠕)|唇齿开合")
AMBIG_LOWER_RE = re.compile(r"西装裙|套裙|职业裙")
LIGHT_SIZES = re.compile(r"特写|近景|中景")
LIGHT_RE = re.compile(r"(?<!反)光|灯|霓虹|烛|阳光|月光")
LIGHT_DIR_RE = re.compile(r"左|右|侧|顶|上方|头顶|背后|身后|逆光|正面|迎面|窗外|门缝|从|斜|下方|脚下|前方|后方|"
                          r"勾出|打在|落在|照在|洒在|映在|铺在|擦过|掠过")


def _issue(rule_id: str, detail: str, field: str) -> dict:
    return {"rule_id": rule_id, "level": WRITER_LINT_LEVEL, "detail": detail, "field": field, "rule": RULES[rule_id][1]}


def look_slots_at(looks: list, name: str, shot_index: int) -> dict:
    """角色在镜N 的造型槽位：起始造型行 + 镜M起（M ≤ N）换装行覆盖变了的槽位"""
    out: dict = {}
    for lk in sorted((x for x in looks if x.character == name), key=lambda x: x.from_shot or 0):
        if (lk.from_shot or 0) <= shot_index:
            out.update(lk.slots or {})
    return out


def extras_of(sh) -> dict:
    return {e.label.split("（")[0].strip(): e.text for e in (sh.extras or [])}


FIELDS = {"站位", "地标", "光线", "分拍", "镜头运动", "嘴型", "台词时段", "独白时段", "出画", "下镜", "尾帧曝光", "镜型", "硬切"}


def scan_fields(md_text: str) -> dict:
    """导入器不把 **分拍** / **嘴型** 等增补字段挂到镜头上（ns_recipes.spec_import.scan_new_fields 同一做法）→ {(集, 镜): {标签: 原文}}"""
    from ns_agent.importer.script_md import EP_RE, FIELD_RE, SHOT_RE
    out: dict = {}
    ep = shot = None
    for raw in (md_text or "").splitlines():
        line = raw.rstrip().replace(r"\*", "*")
        if m := EP_RE.match(line):
            ep, shot = int(m.group(1)), None
            continue
        if line.startswith("## ") or line.startswith("# "):
            ep = shot = None
            continue
        if ep is None:
            continue
        if m := SHOT_RE.match(line):
            shot = int(m.group(1))
            continue
        if shot is not None and (m := FIELD_RE.match(line)):
            label = m.group(1).split("（")[0].strip()
            if label in FIELDS:
                out.setdefault((ep, shot), {})[label] = (m.group(2) or "").strip()
    return out


def beats_of(text: str) -> list[str]:
    out = []
    for it in (x.strip() for x in TIME_SPLIT.split(text or "") if x.strip()):
        m = BEAT_RE.match(it)
        if not m:
            continue
        rest = it[m.end():]
        parts = [p.strip() for p in re.split(r"[｜|]", rest)]
        out.append(next((p for p in parts if p and "=" not in p and "＝" not in p), ""))
    return out


def check_shot(sh, ep, img: str, size: str | None, fields: dict | None = None) -> list[dict]:
    out: list[dict] = []
    cast = sh.cast or []
    on = [c.name for c in cast if c.presence == "在画"]
    ex = {**extras_of(sh), **(fields or {})}
    # QW-W1 外层衣物要写进 img
    if size not in HIDE_SIZES:
        for name in on:
            cloth = look_slots_at(ep.looks or [], name, sh.index).get("服装", "")
            for item in re.split(r"[＋+、，,；;／/]", cloth):
                m = OUTER_RE.search(item)
                if not m:
                    continue
                core = m.group(0)
                if core not in img and item.strip() not in img and not ("外套" in core and "外套" in img):
                    out.append(_issue("QW-W1", f"{name} 本镜造型有外层「{item.strip()}」，img 没写（在画时外层看得见；"
                                               f"脱下 / 搭在手臂上也要写明）", "img"))
    # QW-W2 分拍至少一个看得见的身体动作
    bs = beats_of(ex.get("分拍", ""))
    if bs and (sh.duration or 0) >= 3:
        moving = [b for b in bs if b and not STATIC_RE.match(b) and MOVE_RE.search(b)]
        if not moving:
            out.append(_issue("QW-W2", f"{len(bs)} 拍都没有看得见的身体动作（{'；'.join(b[:12] for b in bs[:3])}）", "分拍"))
    # QW-W3 只有 🎙 的镜：在画说话人嘴闭着
    if sh.voiceover and sh.voiceover.text and not sh.dialogue and sh.voiceover.speaker in on:
        who = sh.voiceover.speaker
        txt = "；".join([ex.get("分拍", ""), sh.motion_prompt or ""])
        if SPEAK_RE.search(txt):
            out.append(_issue("QW-W3", f"只有 🎙 的镜，{who} 在画，分拍 / motion 却写了开口说话（{SPEAK_RE.search(txt).group(0)}）",
                              "分拍"))
        mouth = ex.get("嘴型", "")
        if re.search(re.escape(who) + r"\s*[=＝:：]\s*(?:张开|开|说话|动)", mouth):
            out.append(_issue("QW-W3", f"只有 🎙 的镜，**嘴型** 却写 {who} 张开", "嘴型"))
    # QW-W4 下装品类（img 里）
    m = AMBIG_LOWER_RE.search(img)
    if m:
        out.append(_issue("QW-W4", f"img 写了「{m.group(0)}」：写明裙型 / 裤型（铅笔裙 / 包臀裙 / A字裙 / 西裤…）", "img"))
    # QW-W9 光线要有方向 / 落点（人物在画的特写 / 近景 / 中景；局部 / 大特写不查）
    if on and size and LIGHT_SIZES.search(size) and not re.search(r"局部|大特写|极近特写", size):
        segs = [x for x in re.split(r"[，。；;]", img or "") if LIGHT_RE.search(x)]
        if not segs:
            out.append(_issue("QW-W9", "img 没写光线：写一句“光源 + 方向或落点”（例：窗外冷光从左侧落在脸颊上）", "img"))
        elif not any(LIGHT_DIR_RE.search(x) for x in segs):
            out.append(_issue("QW-W9", f"光线「{'、'.join(x.strip()[:16] for x in segs[:2])}」没有方向 / 落点：补上从哪边来、落在哪里", "img"))
    # QW-W10 手部局部 + 肩颈部位（和 ns_agent.framing.part_name 的“手与肩颈”判定同一组词）
    if size and re.search(r"局部|大特写|极近特写|特写", size):
        hit = W10_RE.search(img or "")
        hands = [(img.find(w), w) for w in W10_HAND if w in (img or "")]
        if hit and hands and min(hands)[0] < hit.start() and not re.search("|".join(W10_FACE), img or ""):
            out.append(_issue("QW-W10", f"局部写的是「{min(hands)[1]}」，又写到「{hit.group(0)}」", "img"))
    # QW-W11 对身上正穿着的衣服做整理动作（K-WRT-702）：分拍字段 + H3 正文的分拍段（At 00:0x 之后）
    beats_zh = ex.get("分拍", "")
    h3 = getattr(sh, "h3_prompt", None) or ""
    h3_beats = h3[h3.find("At 00:"):] if "At 00:" in h3 else ""
    # QW-W12 穿外层衣物的在画人物 + 全身姿态切换（K-WRT-704）
    outer_on = [n for n in on if OUTER_RE.search(look_slots_at(ep.looks or [], n, sh.index).get("服装", ""))]
    pz = POSE_CHANGE_ZH.search(beats_zh + "；" + (getattr(sh, "motion_prompt", None) or ""))
    pe = POSE_CHANGE_EN.search(h3_beats)
    if outer_on and (pz or pe):
        out.append(_issue("QW-W12", f"{'、'.join(outer_on)} 穿着外层衣物，分拍里有「{(pz or pe).group(0)}」：拆成“站定起始”的下一镜",
                          "分拍" if pz else "H3提示词"))
    # 情节本身就是穿脱（脱下 / 解开 / take off / slips off…）不算：K-WRT-702 要求这类单独成镜、首尾帧画出前后，不在这里拦
    if GARMENT_OFF.search(beats_zh + " " + h3_beats):
        return out
    m = GARMENT_ACT_ZH.search(beats_zh) or GARMENT_ACT_ZH.search(getattr(sh, "motion_prompt", None) or "")
    if m:
        out.append(_issue("QW-W11", f"分拍写了对身上衣服的整理动作「{m.group(0)}」（视频会把衣服先脱再穿）", "分拍"))
    else:
        m = next((x for x in GARMENT_ACT_EN.finditer(h3_beats) if not NOT_GARMENT_ACT.search(x.group(0))), None)
        if m:
            out.append(_issue("QW-W11", f"H3 分拍写了对身上衣服的整理动作“{m.group(0)}”（视频会把衣服先脱再穿）", "H3提示词"))
    return out


W10_HAND = ("手", "指", "甲", "腕")
W10_RE = re.compile(r"锁骨|颈|肩|胸")
W10_FACE = ("脸", "眼", "唇", "嘴", "眉", "视线", "表情", "目光")   # 写到脸的是脸部特写，不归这条


def _bigrams(t: str) -> set:
    t = re.sub(r"[\s，。、；：！？“”‘’（）()｜|—…]|她的|他的|她|他|的|在|着|了", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _speech_chars(sh) -> int:
    n = sum(len(re.sub(r"[\s，。！？、…—“”‘’：；,.!?]", "", d.text or "")) for d in (sh.dialogue or []))
    vo = getattr(sh, "voiceover", None)
    return n + (len(re.sub(r"[\s，。！？、…—“”‘’：；,.!?]", "", vo.text)) if vo is not None and vo.text else 0)


def _shot_cap(ep) -> int | None:
    try:
        from ns_agent.importer.script_md import shot_cap
        return shot_cap(ep)
    except Exception:  # noqa: BLE001
        return None


def check_pacing(ep) -> list[dict]:
    """QW-T1 / QW-T2（K-WRT-Q07）。级别固定 warn（不跟 WRITER_LINT_LEVEL 升 block）：逐镜返修不能改镜数 / 时长"""
    out, shots = [], [s for s in getattr(ep, "shots", []) if getattr(s, "duration", None)]
    warn = lambda rid, d, f: {**_issue(rid, d, f), "level": "warn"}   # noqa: E731
    for sh in shots:
        ch = _speech_chars(sh)
        lim = PACE_MAX_S if not ch else max(PACE_MAX_S, -(-int(ch / SPEECH_CPS * 10 + 15) // 10))
        if sh.duration > lim:
            out.append(warn("QW-T1", f"镜{sh.index} 时长 {sh.duration} 秒，{'没有台词 / 独白' if not ch else f'台词 {ch} 字'}，上限 {lim:g} 秒", "时长"))
    if shots:
        avg, cap = sum(s.duration for s in shots) / len(shots), _shot_cap(ep)
        if avg > PACE_AVG_S and (cap is None or len(shots) < cap):
            out.append(warn("QW-T2", f"本集 {len(shots)} 镜、平均 {avg:.1f} 秒（>{PACE_AVG_S:g}）；镜数上限 {cap if cap else '?'}，还能加镜", "时长"))
    return out


# HOLLYWOOD r7（总调度 fredw-2b 11-02 批复，L-098 / L-102，CONSENT 总调度 -> HOLLYWOOD）：可核对清单里能机检的 27 条
# （tools/script_rsi/rubric_code.py）并进写作 lint——写作方自检直接调用；级别固定 RUBRIC_LEVEL（默认 warn，不跟 WRITER_LINT_LEVEL 升 block，
# 不影响现行稿与各返修环）；导入闸门（validate_qwen_script --rubric-gate / producer import-staged）把它升为 block
RUBRIC_LEVEL = "warn"
RULES["QW-RB1"] = ("warn", "HOLLYWOOD 可核对清单的代码判定条目（rubric_code，K-WRT-H07 / H08）：字段写全、分拍按秒切到镜长、镜1 近景或中景、"
                           "近景不写下半身、台词后下一镜写听者反应、分拍不写穿脱过程、不写回头 / 看镜头、不用情绪直陈句、人物卡原文（发型 / 服装 / 饰品）")
_RUBRIC = None


def _rubric():
    global _RUBRIC
    if _RUBRIC is None:
        import importlib.util
        from pathlib import Path as _P
        spec = importlib.util.spec_from_file_location("rubric_code", _P(__file__).resolve().parents[2] / "tools" / "script_rsi" / "rubric_code.py")
        _RUBRIC = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_RUBRIC)
    return _RUBRIC


def check_rubric(ep, text: str) -> list[dict]:
    """QW-RB1：rubric_code 代码判定失败的条目，一条一个 issue（集级）"""
    try:
        items = _rubric().episode_issues(ep, text)
    except Exception as e:  # noqa: BLE001  rubric 自身出错不拦校验，只记一条
        items = [("error", f"rubric_code 运行失败：{e!r}"[:200])]
    return [{"rule_id": "QW-RB1", "level": RUBRIC_LEVEL, "detail": f"[{it}] {why}"[:300], "field": "清单", "rule": RULES["QW-RB1"][1]}
            for it, why in items]


def check_episode(ep, fields: dict | None = None) -> list[dict]:
    out = check_pacing(ep)
    names = {c.name for s in getattr(ep, "shots", []) for c in (s.cast or [])}
    for sh in getattr(ep, "shots", []):     # QW-W5 接力承接（DH-S17）
        carry = sh.link_carry or ""
        if sh.link != "接力" or not carry.startswith("动作"):
            continue
        beat = re.split(r"[；;]", ((fields or {}).get((ep.number, sh.index)) or {}).get("分拍", ""), 1)[0]
        strip = lambda t: re.sub("|".join(map(re.escape, names)) or "^$", "", t)   # noqa: E731
        want, have = _bigrams(strip(carry.split("｜", 1)[-1])), _bigrams(strip((sh.img_prompt or "") + beat))
        if want and len(want & have) / len(want) < 0.2:
            out.append(_issue("QW-W5", f"镜{sh.index} 承：{carry[:30]}——img 和第一拍都没接上这个动作", "衔接"))
    for lk in ep.looks or []:
        cloth = (lk.slots or {}).get("服装", "")
        m = AMBIG_LOWER_RE.search(cloth)
        if m:
            out.append(_issue("QW-W4", f"造型｜{lk.character}{('｜镜' + str(lk.from_shot) + '起') if lk.from_shot else ''} 服装写了"
                                       f"「{m.group(0)}」：写明裙型 / 裤型（铅笔裙 / 包臀裙 / A字裙 / 西裤…）", "造型"))
    return out
