"""HOLLYWOOD r6 修尺子（总调度 fredw-2b 派，11-02；G1 / L-102：判定要落成代码）：可核对清单里能机检的条目改为代码判定。

清单原文：config/prompts/hollywood_rubric.json（写作网关产出，10 项 × 5 条）。本文件只判“能逐字 / 逐字段核对”的部分，
不评价内容好坏；需要理解剧情的条目（冲突、转折、目标阻碍赌注、潜台词两层意思等）仍交评审（7 个评审逐条取多数）。

    CODE_ITEMS  : 整条由代码判定（24 条）
    MIXED_ITEMS : 机检部分由代码判、判断部分由评审判，两者都满足才算满足（3 条）
    LLM_ITEMS   : 整条交评审（23 条）

判定口径都比原条件“只严不松”：拿不准的写法（缺字段、对不上人物卡原文）一律记不满足。
"""
from __future__ import annotations

import re
from pathlib import Path

DIMS = ["hook5s", "conflict", "turns", "gos", "show", "specificity", "pika", "consistency", "subtext", "endhook"]

CODE_ITEMS = {"hook5s": [1, 4, 5], "conflict": [1], "turns": [1], "show": [1, 3, 5], "specificity": [3, 4, 5],
              "pika": [2, 3, 4], "consistency": [1, 2, 3, 4, 5], "subtext": [3, 4, 5], "endhook": [3, 5]}
MIXED_ITEMS = {"specificity": {1: "只判“每镜 img 写了具体动作瞬间”这一部分（景别 / 人物 / 视线三项由代码判）",
                               2: "只判“每个时间段只写一个主动作”这一部分（按秒切段由代码判）"},
               "pika": {5: "只判“动作写连续、匀速、幅度小”和“首帧写正在做某个动作的瞬间、不写站好亮相”这两部分（脸红词与时长由代码判）"}}
LLM_ITEMS = {d: [i for i in range(1, 6) if i not in CODE_ITEMS.get(d, []) and i not in MIXED_ITEMS.get(d, {})] for d in DIMS}

BLUSH = re.compile(r"flush|blush|redden|脸红|涨红|红晕|泛红", re.I)
SIZES = ["大特写", "中近景", "中全景", "特写", "近景", "中景", "全景", "远景"]
CLOSE = {"大特写", "特写", "近景", "中近景", "中景"}
NEAR_MID = {"近景", "中近景", "中景"}
LOWER = re.compile(r"鞋|高跟|细跟|腿|脚")
EMO_ADJ = re.compile(r"(很|好|非常|特别|太|真)(生气|愤怒|震惊|难过|伤心|害怕|紧张|开心|高兴|委屈|心动|激动|失望|痛苦|讨厌)")
VAGUE = re.compile(r"一些东西|之类的|各种|某些东西|什么的|等等|某种东西")
DRESS_PROCESS = re.compile(r"披上|抖开|拉好|穿上|脱下|换上|系好|扣上|套上")
LOOK_CAMERA = re.compile(r"(?<![不别勿没])(?:看镜头|看向镜头|直视镜头|望向镜头)|转头看向镜头|回头看|looks? (?:at|into|toward) the camera|into the lens", re.I)
DIRECT = re.compile(r"我其实|其实我是|我是想|我想让你知道|说实话|老实说|我恨你因为|我这么做是因为")
GARMENT = re.compile(r"裙|衫|衣|裤|外套|西装|束腰|风衣|毛衣|卫衣|胸衣|连体|夹克|背心|吊带")
BEAT = re.compile(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\s*秒｜([^；]*)")
ACC_PREFIX = re.compile(r"^(左腕|右腕|腕上|颈间|在颈间|在手上|手上|耳垂|耳间|指间|腰侧|左手无名指|右手)")


def _field(block: str, label: str) -> str:
    for ln in block.split("\n"):
        if ln.startswith(f"**{label}**"):
            return ln.split("：", 1)[1] if "：" in ln else ""
    return ""


def _img(block: str) -> str:
    first = block.split("\n", 1)[0]
    return first.split("：", 1)[1] if "：" in first else ""


REF_LEAD = re.compile(r"^(?:图\d+是[^。]*。)+")


FRAMING_SENT = re.compile(r"(大特写|中近景|中全景|特写|近景|中景|全景|远景)构图")


def _size(img: str) -> str | None:
    m = FRAMING_SENT.search(img)          # 编译稿：编译器固定写一句“<景别>构图（…）”（K-REN-101 景别句）
    if m:
        return m.group(1)
    head = REF_LEAD.sub("", img)[:60]   # 剧本 img：开头可能先写 LoRA 触发词
    return next((s for s in SIZES if s in head), None)


def _beats(block: str) -> list[tuple[float, float, str]]:
    return [(float(a), float(b), t.strip()) for a, b, t in BEAT.findall(_field(block, "分拍"))]


def parse_looks(head: str) -> dict[str, list[tuple[int, dict]]]:
    """集头造型行 → {人物: [(起始镜号, {服装, 发, 饰品, ...}), ...]}；“｜镜N起”的行继承前一套未写的字段"""
    out: dict[str, list[tuple[int, dict]]] = {}
    for ln in head.split("\n"):
        m = re.match(r"\*\*造型｜([^｜*]+)(?:｜镜(\d+)起)?\*\*：(.*)", ln)
        if not m:
            continue
        name, start, body = m.group(1), int(m.group(2) or 1), m.group(3)
        kv = {}
        for part in body.split("｜"):
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k.strip()] = v.strip()
        prev = out.get(name, [])
        base = dict(prev[-1][1]) if prev else {}
        base.update(kv)
        out.setdefault(name, []).append((start, base))
    for v in out.values():
        v.sort(key=lambda t: t[0])
    return out


def look_at(looks, name: str, shot: int) -> dict:
    cur = {}
    for start, kv in looks.get(name, []):
        if start <= shot:
            cur = kv
    return cur


NEW_NOTE = re.compile(r"（新：[^）]*）|（新：[^（）]*$")          # 造型行里新单品的登记注“（新：<品名>，<材质>）”（QW-E6b），不是正文
COUNT = re.compile(r"\s*\d+\s*[件枚个条串只对副]\s*")


def garment_tokens(kv: dict) -> list[str]:
    v = NEW_NOTE.sub("", kv.get("服装", ""))
    toks = [t.strip() for t in re.split(r"配|，|、|外罩|搭|,", _outer_strip(v)) if t.strip()]
    toks = [re.sub(r"^新[：:]\s*", "", t) for t in toks]     # 断点④：不带括号的“新：<品名>”（S2 ep04）
    return [t for t in toks if GARMENT.search(t)]


def _outer_strip(v: str) -> str:
    """去掉所有（…）注释（含嵌套），只留品名"""
    out, depth = "", 0
    for ch in v:
        if ch == "（":
            depth += 1
        elif ch == "）":
            depth = max(0, depth - 1)
        elif depth == 0:
            out += ch
    return out


def hair_core(kv: dict) -> str:
    return re.split(r"[（(，,]", kv.get("发", ""))[0].strip()


def _outer_paren(v: str) -> str | None:
    """“3件（a、b（注）、c）”→ “a、b（注）、c”（最外层括号，允许嵌套）"""
    i = v.find("（")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(v)):
        depth += {"（": 1, "）": -1}.get(v[j], 0)
        if depth == 0:
            return v[i + 1:j]
    return v[i + 1:]


def _split_top(v: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in v:
        depth += {"（": 1, "）": -1}.get(ch, 0)
        if ch in "、，" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def accessory_tokens(kv: dict) -> list[str]:
    v = NEW_NOTE.sub("", kv.get("饰品", ""))
    inner = _outer_paren(v) if re.match(r"^\s*\d+\s*[件枚个条串只对副]\s*（", v) else None
    items = _split_top(inner) if inner is not None else [x.split("，")[0] for x in re.split(r"、|；", _outer_strip(v))]
    out = []
    for it in items:
        it = COUNT.sub("", ACC_PREFIX.sub("", re.sub(r"（.*", "", re.sub(r"^新[：:]\s*", "", it.strip())))).strip()
        it = re.sub(r"(在颈间|在手上|在颈前)$", "", it)
        if len(it) >= 2 and not re.match(r"^(挂|在|戴|系|别)", it):
            out.append(it[-3:] if len(it) > 3 else it)
    return out


# L-107（项目方 AI 运镜资料 docs/reference/camera_moves_20261102.md §四 避坑；DIRECTOR 词表 config/director/camera_moves.yaml）
CAMERA_VOCAB = Path(__file__).resolve().parents[2] / "config" / "director" / "camera_moves.yaml"
ORBIT = re.compile(r"Arc|Orbit|环绕|绕拍", re.I)
DOLLY = re.compile(r"Push|Pull|Dolly|Zoom|推|拉", re.I)


def camera_vocab() -> set[str] | None:
    """词表里 enabled 的运镜名；词表还没出来 → None（只按避坑规则查）"""
    if not CAMERA_VOCAB.exists():
        return None
    import yaml
    d = yaml.safe_load(CAMERA_VOCAB.read_text(encoding="utf-8")) or {}
    items = d.get("moves") or d.get("camera_moves") or d
    out = set()
    if isinstance(items, dict):
        items = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in items.items()]
    for it in items or []:
        if isinstance(it, dict) and it.get("enabled", True) is not False:
            for k in ("name", "en", "zh", "id"):
                if it.get(k):
                    out.add(str(it[k]).strip().lower())
            out |= {str(x).strip().lower() for x in it.get("aliases") or []}     # 别名同样认（DIRECTOR 词表的 aliases）
    return out


def camera_problem(mv: str, cam_line: str, motion: str, vocab: set[str] | None) -> str:
    """一镜的运镜问题（空 = 没问题）：多种运镜叠写；环绕 + 推拉冲突（避坑①）；Arc 幅度不是小；不在 enabled 词表里"""
    if re.search(r"[+＋、/]|和|并|然后|先.*再", mv):
        return "一镜写了两种以上运镜（复杂运动要拆成两镜，避坑③）"
    if ORBIT.search(mv) and (DOLLY.search(mv) or DOLLY.search(motion.split("，")[0] if motion else "")):
        return "环绕 + 推拉冲突（避坑①）"
    if ORBIT.search(mv) and "幅度=小" not in cam_line:
        return "环绕幅度不是小"
    if vocab is not None and mv and mv.lower() not in vocab:
        return f"运镜“{mv}”不在词表 enabled 里"
    return ""


# K-WRT-H14（总调度 11-02 定，S2 ep06 林晚独角戏）：全集只有一个人在画的集 = 独角戏（solo），conflict#1 不判“同框 / 多说话人”，
# 改判“内在冲突”：① 画面里出现外部压力源（画外具名人物、手机消息 / 来电 / 门铃 / 敲门 / 屏幕文字），② 之后主角做出一个可见的选择动作。
PRESSURE = re.compile(r"手机|消息|短信|来电|电话|铃|门铃|敲门|屏幕|通知|弹出|震动|提示音")
CHOICE = re.compile(r"放下|拿起|回复|删掉|删除|关掉|扣下|扣在|走向|推开|按下|不接|拒接|点开|拉黑|打开|合上|转身|离开|站起|坐下|锁上|挂断|接起|写下|撕|扔")


def is_solo(shots: list) -> set[str]:
    """→ 唯一在画人物名的集合（恰好 1 个名字时为独角戏），否则空集"""
    names = {c.name for s in shots for c in (s.cast or []) if c.presence in ("在画", "局部")}
    return names if len(names) == 1 else set()


def solo_conflict(shots: list, blocks: list[str]) -> tuple[bool, str]:
    press_at, choice_at = None, None
    for k, (s, b) in enumerate(zip(shots, blocks)):
        txt = _img(b) + " " + _field(b, "分拍") + " " + _field(b, "表演节拍")
        offscreen = any(c.presence == "画外" for c in (s.cast or []))
        if press_at is None and (offscreen or PRESSURE.search(txt)):
            press_at = k
            continue
        if press_at is not None and CHOICE.search(_field(b, "分拍") + " " + _field(b, "表演节拍")):
            choice_at = k
            break
    if press_at is None:
        return False, "没有外部压力源入画（画外具名人物 / 手机消息 / 来电 / 门铃 / 敲门 / 屏幕文字）"
    if choice_at is None:
        return False, f"镜{shots[press_at].index} 出现压力源，之后没有可见的选择动作"
    return True, f"压力源镜{shots[press_at].index} → 选择镜{shots[choice_at].index}"


def code_checks(chunk: str, shots: list, blocks: list[str], head: str, lint_codes: dict, imgs: list[str] | None = None) -> dict:
    """→ {dim: {id: (met: bool, 说明)}}，只含 CODE_ITEMS 与 MIXED_ITEMS 的条目。shots = 导入器解析的 Shot（按镜号排序），blocks = 对应镜头块原文"""
    R: dict = {d: {} for d in DIMS}
    if imgs is not None:     # r7：用编译后的首帧提示词（image_jobs.frame_prompt）代替剧本 img 行，看编译层补齐后的结果
        blocks = [f"**镜{s.index}｜img**：{im}\n" + (b.split("\n", 1)[1] if "\n" in b else "") for s, b, im in zip(shots, blocks, imgs)]
    n = len(shots)
    looks = parse_looks(head)
    full = "\n".join(blocks)
    w11 = int(lint_codes.get("QW-W11", 0))
    vis = [[c.name for c in (s.cast or []) if c.presence == "在画"] for s in shots]

    def put(d, i, ok, why):
        R[d][i] = (bool(ok), why)

    b1, s1 = blocks[0], shots[0]
    bt1 = _beats(b1)
    put("hook5s", 1, 4 <= int(s1.duration or 0) <= 6 and len([b for b in bt1 if b[0] < 5 and b[2]]) >= 2,
        f"镜1 时长 {s1.duration}，0–5 秒内分拍 {len([b for b in bt1 if b[0] < 5])} 段")
    sz1 = _size(_img(b1))
    put("hook5s", 4, sz1 in NEAR_MID and not LOWER.search(_img(b1)), f"镜1 景别 {sz1}；img 下半身词 {LOWER.findall(_img(b1))}")
    put("hook5s", 5, not BLUSH.search(b1) and w11 == 0 and ("视线=" in _field(b1, "分拍") or s1.dialogue),
        f"镜1 脸红词 {BLUSH.findall(b1)}；QW-W11 {w11}")
    two = any(len(v) >= 2 for v in vis)
    spk = [str(d.speaker) for s in shots for d in s.dialogue]
    solo = is_solo(shots)
    if solo:      # K-WRT-H14：独角戏集 conflict#1 改判“内在冲突”
        ok, why_ = solo_conflict(shots, blocks)
        put("conflict", 1, ok, f"独角戏集（在画只有 {sorted(solo)}）：{why_}")
    else:
        put("conflict", 1, two or len(set(spk)) >= 2, f"同框镜 {sum(len(v) >= 2 for v in vis)}；说话人 {sorted(set(spk))}")
    put("turns", 1, 10 <= n <= 20 and [s.index for s in shots] == list(range(1, n + 1)), f"{n} 镜")
    bad = [s.index for s, b in zip(shots, blocks) if s.voiceover and s.voiceover.text and not re.search(r"视线=[^｜；]{2,}", _field(b, "分拍"))]
    put("show", 1, not bad, f"有 🎙 但分拍没写视线落点的镜：{bad or '无'}")
    speech = [d.text for s in shots for d in s.dialogue] + [s.voiceover.text for s in shots if s.voiceover and s.voiceover.text]
    hits = [m.group(0) for t in speech for m in EMO_ADJ.finditer(t)]
    put("show", 3, not hits, f"情绪形容词直陈：{hits or '无'}")
    put("show", 5, not BLUSH.search(full) and w11 == 0, f"脸红词 {sorted(set(BLUSH.findall(full)))}；QW-W11 {w11}")
    vg = VAGUE.findall(full)
    put("specificity", 3, not vg, f"模糊词：{vg or '无'}")
    put("specificity", 4, int(lint_codes.get("QW-A7", 0)) == 0, f"QW-A7（视线落点）{lint_codes.get('QW-A7', 0)}")
    low = [s.index for s, b in zip(shots, blocks) if _size(_img(b)) in CLOSE and LOWER.search(_img(b))]
    put("specificity", 5, not low, f"近 / 中景 img 写了下半身的镜：{low or '无'}")
    # 混合条目的机检部分
    miss1 = [s.index for s, b, v in zip(shots, blocks, vis) if not _size(_img(b)) or any(nm not in _img(b) for nm in v) or "视线" not in _img(b)]
    put("specificity", 1, not miss1, f"img 缺景别 / 人物名 / 视线的镜：{miss1 or '无'}")
    seg_bad = [s.index for s, b in zip(shots, blocks) if len(_beats(b)) < 2 or abs(max(x[1] for x in _beats(b)) - int(s.duration or 0)) > 0.25]
    put("specificity", 2, not seg_bad, f"分拍没按秒切到镜长的镜：{seg_bad or '无'}")
    put("pika", 2, w11 == 0, f"QW-W11 {w11}")
    cam_bad, vocab = [], camera_vocab()
    for s, b in zip(shots, blocks):
        cam = _field(b, "镜头运动")
        mv = cam.split("｜")[0].strip()
        why = camera_problem(mv, cam, _field(b, "motion"), vocab)
        if not _size(_img(b)) or why:
            cam_bad.append(f"{s.index}{('（' + why + '）') if why else '（景别缺失）'}")
    put("pika", 3, not cam_bad, f"景别缺失 / 运镜问题的镜：{cam_bad or '无'}")
    lk = [s.index for s, b in zip(shots, blocks) if LOOK_CAMERA.search(b)]
    a5 = int(lint_codes.get("QW-A5", 0))
    put("pika", 4, not lk and a5 == 0 and not miss1, f"看镜头 / 回头写法的镜 {lk or '无'}；QW-A5 {a5}；img 视线缺失 {miss1 or '无'}")
    dur_bad = [s.index for s in shots if not (4 <= int(s.duration or 0) <= 15)]
    put("pika", 5, not BLUSH.search(full) and not dur_bad, f"脸红词 {sorted(set(BLUSH.findall(full)))}；时长越界 {dur_bad or '无'}")
    # 人物一致性（对照集头造型行原文）
    c1, c2, c3 = [], [], []
    for s, b, v in zip(shots, blocks, vis):
        img = _img(b)
        for nm in v:
            kv = look_at(looks, nm, s.index)
            if not kv:
                continue
            hc = hair_core(kv)
            hair_by_ref = f"{nm}的脸部参考（只取脸和发型）" in img        # 编译稿：发型由脸部参考图承担（技术契约句）
            if nm not in img or (hc and hc not in img and not hair_by_ref):
                c1.append(f"镜{s.index}{nm}")
            # 编译稿：本镜造型设定图 / 参考板已挂上并写明“服装、鞋、饰品必须与图N一致”= 服装饰品由参考图承担（技术契约句）
            outfit_by_ref = bool(re.search(rf"{re.escape(nm)}本镜造型\w*的设定图|{re.escape(nm)}本镜的参考板", img))
            miss = [] if outfit_by_ref else [t for t in garment_tokens(kv) if t not in img]
            if miss:
                c2.append(f"镜{s.index}{nm}缺{miss}")
            am = [] if outfit_by_ref else [t for t in accessory_tokens(kv) if t not in img]
            if am:
                c3.append(f"镜{s.index}{nm}缺{am}")
    put("consistency", 1, not c1, f"人物名 / 发型原文缺失：{c1[:6] or '无'}")
    put("consistency", 2, not c2, f"服装原文缺失：{c2[:6] or '无'}")
    put("consistency", 3, not c3, f"饰品原文缺失：{c3[:6] or '无'}")
    ch_bad = []
    for nm, lst in looks.items():
        for start, _ in lst[1:]:
            if start <= n:
                b = blocks[start - 1]
                if not re.search(r"换|已换|换装", _img(b) + _field(b, "motion")):
                    ch_bad.append(f"镜{start}{nm}没写换装")
    proc = [s.index for s, b in zip(shots, blocks) if DRESS_PROCESS.search(_field(b, "分拍"))]
    put("consistency", 4, not ch_bad and not proc, f"换装镜：{ch_bad or '无问题'}；分拍写穿脱过程的镜：{proc or '无'}")
    leak = []
    for nm, lst in looks.items():
        if len(lst) < 2:
            continue
        for k, (start, kv) in enumerate(lst):
            end = lst[k + 1][0] if k + 1 < len(lst) else n + 1
            others = {t for j, (_, kv2) in enumerate(lst) if j != k for t in garment_tokens(kv2)} - set(garment_tokens(kv))
            for s, b, v in zip(shots, blocks, vis):
                if start <= s.index < end and nm in v and any(t in _img(b) for t in others):
                    leak.append(f"镜{s.index}{nm}")
    put("consistency", 5, not leak, f"服装与本段造型不符（混入另一套）的镜：{leak or '无'}")
    dr = [m.group(0) for t in [d.text for s in shots for d in s.dialogue] for m in DIRECT.finditer(t)]
    put("subtext", 3, not dr, f"说破意图的句子：{dr or '无'}")
    sub4 = []
    for k, (s, b) in enumerate(zip(shots, blocks)):
        if len(s.dialogue) > 2:
            sub4.append(f"镜{s.index}台词{len(s.dialogue)}句")
        for d in s.dialogue:
            listeners = [c.name for c in (s.cast or []) if c.name != str(d.speaker)]
            if not listeners:
                continue
            nb = blocks[k + 1] if k + 1 < n else b
            txt = _field(nb, "分拍")
            if not any(nm in txt for nm in listeners):
                sub4.append(f"镜{s.index}台词后{'下一镜' if k + 1 < n else '本镜'}分拍没写听者反应")
    put("subtext", 4, not sub4, "；".join(sub4[:5]) or "每镜 ≤2 句且都有听者反应")
    nod = [s.index for s, b in zip(shots, blocks) if s.dialogue and "视线=" not in _field(b, "分拍")]
    put("subtext", 5, not BLUSH.search(full) and w11 == 0 and not nod, f"脸红词 / QW-W11 {w11} / 台词镜分拍无视线 {nod or '无'}")
    bl, sl = blocks[-1], shots[-1]
    d_ = int(sl.duration or 0)
    tail = [x for x in _beats(bl) if abs(x[1] - d_) <= 0.25 and x[0] >= d_ - 2 - 0.25 and x[2]]
    put("endhook", 3, 4 <= d_ <= 6 and bool(tail), f"末镜时长 {d_}；最后 2 秒分拍段 {len(tail)}")
    put("endhook", 5, not BLUSH.search(bl) and w11 == 0 and bool(_size(_img(bl))), f"末镜景别 {_size(_img(bl))}；脸红词 {BLUSH.findall(bl)}")
    return R


def share() -> dict:
    nc = sum(len(v) for v in CODE_ITEMS.values())
    nm = sum(len(v) for v in MIXED_ITEMS.values())
    return {"code": nc, "mixed": nm, "llm": 50 - nc - nm, "code_ratio": nc / 50, "code_or_mixed_ratio": (nc + nm) / 50}


SHOT_HEAD = re.compile(r"^\*\*镜(\d+)｜img")
EP_HEAD = re.compile(r"^##\s*ep(\d+)")


def episode_chunk(text: str, ep_no: int) -> str:
    """整份剧本 → 这一集的原文（从 ## epNN 到下一个 ## ep）"""
    lines = text.splitlines()
    starts = [(i, int(m.group(1))) for i, ln in enumerate(lines) for m in [EP_HEAD.match(ln.replace(r"\*", "*"))] if m]
    for k, (i, n) in enumerate(starts):
        if n == ep_no:
            end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
            return "\n".join(lines[i:end])
    return ""


def split_blocks(chunk: str) -> tuple[str, list[str]]:
    """一集原文 → (集头, [镜头块原文])；镜头块到下一个镜头 / --- 为止"""
    lines = chunk.splitlines()
    idx = [i for i, ln in enumerate(lines) if SHOT_HEAD.match(ln)]
    head = "\n".join(lines[: idx[0]] if idx else lines)
    blocks = []
    for k, i in enumerate(idx):
        j = idx[k + 1] if k + 1 < len(idx) else len(lines)
        blk = lines[i:j]
        while blk and (not blk[-1].strip() or blk[-1].strip() == "---"):
            blk.pop()
        blocks.append("\n".join(blk))
    return head, blocks


def episode_issues(ep, text: str, lint_codes: dict | None = None) -> list[tuple[str, str]]:
    """写作自检 / 导入校验用（writer_lints.check_rubric）：→ [(条目, 说明)]，只含代码判定失败的条目。
    lint_codes 为空时 QW-W11 / QW-A5 / QW-A7 三项由校验器自己的规则报，这里不重复（相关条目按满足计）"""
    chunk = episode_chunk(text, ep.number)
    if not chunk:
        return []
    head, blocks = split_blocks(chunk)
    shots = sorted(ep.shots, key=lambda s: s.index)
    if len(blocks) != len(shots) or not shots:
        return [("structure", f"镜头块 {len(blocks)} 个与解析出的镜头 {len(shots)} 个对不上，无法逐条核对")]
    cc = code_checks(chunk, shots, blocks, head, lint_codes or {})
    return [(f"{d}#{i}", why) for d in DIMS for i, (ok, why) in cc[d].items() if not ok]


# ------------------------------------------------------------------ 镜头块 v2 + 【灯光】（K-WRT-805 / 806，DIRECTOR r4 / L-111；第二季起）
# 单一来源：config/director/shot_spec_v2.yaml（segments[].md_label、required）、config/director/lighting.yaml（schemes[].id / zh、sources.*.zh）、
# config/director/lenses.yaml（lenses[].id / zh）。DIRECTOR 确认写法 (a)：每段单独一行、字段标签、顺序固定；**镜头** 与 **声音** 可缺。
_DIR = Path(__file__).resolve().parents[2] / "config" / "director"
SIDE_WORDS = re.compile(r"左侧|右侧|上方|身后|正面|左边|右边|头顶|背后|侧面|画面左|画面右")
RATIO = re.compile(r"\d+\s*[:：]\s*\d+")
KELVIN = re.compile(r"\d{4}\s*K|暖|冷")


def _yaml(name: str):
    import yaml
    return yaml.safe_load((_DIR / name).read_text(encoding="utf-8")) or {}


def v2_spec() -> tuple[list[tuple[str, str, bool]], dict]:
    """→ ([(段 id, md_label, 必填)], 灯光词表)"""
    spec = _yaml("shot_spec_v2.yaml")
    segs = [(s["id"], s.get("md_label", ""), bool(s.get("required"))) for s in spec.get("segments") or []]
    light = _yaml("lighting.yaml")
    return segs, light


def uses_v2(blocks: list[str]) -> bool:
    """第二季起的写法：任一镜出现 **机位与景别**： 就按 v2 判（第一季稿不判，由导演层自动补，标 auto）"""
    return any("**机位与景别**：" in b for b in blocks)


def light_sources(lt: str) -> list[str]:
    """【灯光】行“动机光源=”字段里的光源项（去掉括号里的方位）；没有这个字段 = []"""
    m = re.search(r"动机光源=([^｜]+)", lt)
    if not m:
        return []
    return [x for x in (re.sub(r"（[^）]*）|\([^)]*\)", "", t).strip() for t in re.split(r"[，、,；;]", m.group(1))) if x]


def source_seen(item: str, ctx: str, vocab: list[str]) -> bool:
    """总调度 11-02 灯光规则修订：动机光源的本意 = 光从画面里看得见的东西来。光源项（或它的任意两字片段，如“柜台油灯”→“油灯”、“石板地面”→“石板”）
    出现在本镜 / 本场的场景描述、道具里，或者是 lighting.yaml sources 词表里的词，都算合规"""
    if any(w and (w in item or item in w) for w in vocab):
        return True
    return item in ctx or (len(item) > 2 and any(item[i:i + 2] in ctx for i in range(len(item) - 1)))


def v2_checks(shots: list, blocks: list[str], scene_text: str = "") -> dict:
    """→ {1: (ok, 说明), 2: (ok, 说明)}：① 七段（必填五段）齐全且顺序固定；② 【灯光】是方案名，或三要素（动机光源 + 方向、布光比、色温）齐全；
    动机光源（总调度 11-02 修订）：“动机光源=”里的每一项出现在本镜 **机位与景别** / **构图** / img / **场景** 行、或本场场景描述（scene_text：
    剧本头 + 集头里的场景表 / 用到的场景），或在 lighting.yaml sources 词表里，都算合规；方向、布光比、色温要求不变"""
    segs, light = v2_spec()
    schemes = {str(s.get("zh", "")).strip() for s in light.get("schemes") or []} | {str(s.get("id", "")).strip() for s in light.get("schemes") or []}
    src_words = [w for v in (light.get("sources") or {}).values() for w in (v.get("zh") or [])]
    miss, order_bad, light_bad = [], [], []
    for s, b in zip(shots, blocks):
        lines = b.split("\n")
        pos = {}
        for sid, lab, req in segs:
            idx = next((i for i, ln in enumerate(lines) if lab and ln.startswith(lab)), None)
            if idx is None:
                if req:
                    miss.append(f"镜{s.index}缺{lab.strip('*：')}")
            else:
                pos[sid] = idx
        got = [sid for sid, _lab, _r in segs if sid in pos]
        if [pos[x] for x in got] != sorted(pos[x] for x in got):
            order_bad.append(s.index)
        lab_l = next((lab for sid, lab, _r in segs if sid == "lighting"), "**灯光**：")
        lt = next((ln[len(lab_l):].strip() for ln in lines if ln.startswith(lab_l)), "")
        if not lt:
            light_bad.append(f"镜{s.index}没写灯光")
            continue
        if any(x and x in lt for x in schemes):
            continue
        ctx = " ".join(ln for ln in lines if ln.startswith(("**机位与景别**", "**构图**", "**场景**")) or SHOT_HEAD.match(ln)) + " " + (scene_text or "")
        items = light_sources(lt)
        probs = []
        if items:
            unseen = [x for x in items if not source_seen(x, ctx, src_words)]
            old_ok = any(w in lt and w in ctx for w in src_words)      # 修订前的判法过了的，修订后不变严
            if len(unseen) == len(items) and not old_ok:
                probs.append(f"动机光源“{unseen[0]}”在本镜画面 / 本场场景描述 / 道具里都没出现，也不在 lighting.yaml 词表里")
        elif not [w for w in src_words if w in lt]:
            probs.append("没写动机光源（写“动机光源=<画面里看得见的光源>（方位）”，或用 lighting.yaml sources 词表里的词）")
        if not SIDE_WORDS.search(lt):
            probs.append("没写光源方向（左侧 / 右侧 / 上方 / 身后 / 正面）")
        if not RATIO.search(lt):
            probs.append("没写布光比（如 3:1）")
        if not KELVIN.search(lt):
            probs.append("没写色温（K 值或暖 / 冷）")
        if probs:
            light_bad.append(f"镜{s.index}：" + "、".join(probs))
    # 缺段清单不截断（CODER-PS 11-03 12:2x）：原来 miss[:8] 只列前 2 镜，L-158 整集返修包把这句当判定原文给写手，
    # 写手按“只改点名的镜”执行 → 每次只补 2 镜，ep02 镜5–11 两次返修用满上限仍缺。返修要一次补全，清单必须全量
    return {1: (not miss and not order_bad, f"缺段：{miss or '无'}；段顺序不对的镜：{order_bad or '无'}"),
            2: (not light_bad, f"灯光问题：{light_bad[:8] or '无'}")}


# ---- v3（总调度 11-02，JUDGE 第二季共性弱点 → 能代码判的两条；K-WRT-H19 / H20）
V3_NEW_INFO = re.compile(r"亮起|出现|发现|看见|看到|打开|掉出|露出|显示|弹出|推开|揭开|认出|震了|震动|抽出|抽走|递到|递过|放到|放下|拿起|拿出|"
                         r"入画|响起|响了|落下|掉在|划掉|按下|塞进|扣下|翻开|撕开|亮出")
V3_WALK = re.compile(r"转身|转过身|回身|走向|走到|走过|走开|走近|走出|走进|走回|踱|穿过|起身走|迈步|往前走|朝[^｜；]{0,6}走")


def _img_line(block: str) -> str:
    return next((ln.split("：", 1)[1] for ln in block.split("\n") if SHOT_HEAD.match(ln)), "")


def _bigrams(t: str) -> set[str]:
    t = re.sub(r"[\s，。；、：|｜（）()“”\"*]", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def v3_checks(shots: list, blocks: list[str]) -> dict:
    """→ {1: 结尾钩子在画面里, 2: 一镜一个主动作}（K-WRT-H19 / H20）。
    ① 末镜最后 2 秒（落在镜长最后 2 秒内的分拍）出现新信息动作词（V3_NEW_INFO：新动作 / 新物件 / 新人入画），不能只靠 OS 疑问；
       且末镜不重复前一镜：两镜 img 二字片段重合率 ≥ 0.7 且景别相同 = 重复。
    ② 分拍里不写转身 / 走动（V3_WALK；与 config/prompts/hollywood_pika_reference.md“一镜只放一个主动作、站起 / 转身走开写成镜尾起势”对齐）；
       新人进画写“入画”，不写“走进”。"""
    if not shots:
        return {1: (False, "没有镜"), 2: (False, "没有镜")}
    last, lb = shots[-1], blocks[-1]
    dur = float(last.duration or 0)
    tail = [t for a, e, t in _beats(lb) if e > dur - 2 - 0.01]
    has_new = any(V3_NEW_INFO.search(t) for t in tail)
    rep = False
    if len(blocks) >= 2:
        a, b = _bigrams(_img_line(blocks[-2])), _bigrams(_img_line(lb))
        jac = len(a & b) / max(1, len(a | b))
        size = lambda t: next((x for x in ("大特写", "中近景", "中全景", "特写", "近景", "中景", "全景", "远景") if x in t[:12]), None)
        rep = jac >= 0.7 and size(_img_line(blocks[-2])) == size(_img_line(lb))
    end_ok = has_new and not rep
    end_why = ("末镜最后 2 秒有新信息" if has_new else f"末镜最后 2 秒（{dur - 2:.0f}–{dur:.0f} 秒）没有新动作 / 新物件 / 新人入画：{'；'.join(t[:30] for t in tail) or '无分拍'}") + \
              ("；末镜与前一镜几乎重复（img 重合 ≥ 0.7 且景别相同）" if rep else "")
    walk = []
    for s, b in zip(shots, blocks):
        for _a, _e, t in _beats(b):
            m = next((x for x in V3_WALK.finditer(t) if not re.search(r"(没有|没|不|未|别)$", t[:x.start()])), None)   # “没有回身”不算
            if m and "入画" not in t:
                walk.append(f"镜{s.index}“{m.group(0)}”")
                break
    return {1: (end_ok, end_why), 2: (not walk, f"写了转身 / 走动的镜：{walk[:8] or '无'}")}


# ---- K-WRT-211（fb-0001，总调度 11-02 授权 HOLLYWOOD 补 check）：镜面 / 玻璃场景手不碰反光面；≤8 秒的镜手部动作 ≤2 处
MIRROR_CTX = re.compile(r"镜面|镜子|全身镜|镜墙|玻璃|落地窗|反光|mirror|glass|reflect", re.I)
HAND_ON_MIRROR = re.compile(
    r"(掌心|手掌|手|指尖|指节|手指)[^。；｜，,]{0,10}(贴|按|扶|抵|撑|压|碰|摸)[^。；｜，,]{0,6}(镜面|镜子|镜墙|玻璃|落地窗|反光)(?!框|边|柜)"
    r"|(hand|palm|fingertips?|knuckles?)[^.,;]{0,40}\b(on|against)\b (the )?(mirror|glass|window)(?! ?(frame|edge|border|sill|cabinet))", re.I)
HAND_ACT = re.compile(r"(掌心|手掌|指尖|指节|手指|(?<![一二三四五六七八九十对双])手(?![机表帕套段法艺术]))[^，；｜]{0,8}"
                      r"(抬|收|按|握|拨|推|拿|放|递|攥|松|捏|摸|扶|撑|压|点|划|塞|抽|翻|捻|揉|抓|勾|贴|折|拉|扣|捧|托)")
# K211-F 11-03（series10_v2 ep01 镜7 实测误判）：V2 分拍写法里“右手已经把相机放进包里”是首帧状态、“手指到镜尾还在收紧”是上一拍动作的延续，
# 都不是这一拍新起的手部动作；手名到动词之间出现这些词就不算一处（“没有抬手”这类否定同理）
HAND_STATE = re.compile(r"已经|早已|仍在|还在|仍旧|依旧|照旧|一直|始终|保持|维持|停在|没有|不再|不动|到镜尾")


def hand_action(beat_text: str) -> str | None:
    """这一拍动作段里第一处“新起的手部动作”原文；状态 / 延续 / 否定写法（HAND_STATE）不算。没有 → None"""
    for m in HAND_ACT.finditer(beat_text.split("｜")[0]):
        if not HAND_STATE.search(m.group(0)):
            return m.group(0)
    return None


def mirror_hand_checks(shots: list, blocks: list[str]) -> dict:
    """→ {1: 镜面场景手不碰反光面, 2: ≤8 秒的镜手部动作 ≤2 处}（K-WRT-211）。
    ① 本镜 img / **场景** 行有镜面 / 玻璃 / 落地窗等反光面，且 分拍 / 表演节拍 / motion / H3 写了手贴 / 按 / 扶 / 抵在反光面上（镜框、镜边、镜柜不算）；
    ② 镜长 ≤8 秒的镜，分拍里带新起手部动作（手 / 掌 / 指 + 抬收按握拨推拿放递…；“已经…”首帧状态 / “还在…”延续 / 否定不算）的拍超过 2 拍。
    失败原因里写出命中的拍和原文，补丁包能直接定位到行（之前只写“镜7（3 拍）”，写手不知道改哪一拍）。"""
    touch, busy = [], []
    for s, b in zip(shots, blocks):
        lines = b.split("\n")
        ctx = " ".join(ln for ln in lines if SHOT_HEAD.match(ln) or ln.startswith("**场景**"))
        act = " ".join(ln for ln in lines if ln.startswith(("**分拍**", "**表演节拍**", "**motion**"))) + " " + " ".join(lines[i] for i in range(len(lines)) if "```" not in lines[i] and not lines[i].startswith("**"))
        if MIRROR_CTX.search(ctx):
            m = HAND_ON_MIRROR.search(act)
            if m:
                touch.append(f"镜{s.index}“{m.group(0)[:20]}”")
        if int(s.duration or 0) <= 8:
            hits = [(a, e, h) for a, e, t in _beats(b) if (h := hand_action(t))]
            if len(hits) > 2:
                busy.append(f"镜{s.index}（{len(hits)} 拍：" + "、".join(f"{a:g}–{e:g}秒“{h}”" for a, e, h in hits) + "）")
    hint = ("；改法：只改这一镜 **分拍** / **表演节拍**（及对应 H3 正文），留 ≤2 拍手部动作，其余拍改写成视线 / 呼吸 / 肩线 / 表情；"
            "“已经…”写首帧状态、“到镜尾还在…”写延续都不算新动作" if busy else "")
    return {1: (not touch, f"镜面场景手碰反光面：{touch[:8] or '无'}"), 2: (not busy, f"≤8 秒镜手部动作超过 2 拍：{busy[:8] or '无'}{hint}")}


# ---- L1（L-188，项目方 11-04“用 L1”；PLAN_HOLLYWOOD_LOOK §6；K-WRT-L1a / L1b / L1c）：平光禁用词、多人三层构图。只在写作 / 导入闸门用，不碰已导入的剧
FLAT_LIGHT = re.compile(r"正面高亮|正面平光|平光|(?:把|将)?(?:影子|阴影)(?:全部|都)?打平|打平(?:了)?(?:影子|阴影)|白幕反射(?:补|打|照)?脸|反射补脸|无影(?:光|灯)?|均匀(?:的)?(?:柔)?(?:光|布光)")
L1_LIGHT_LABELS = ("**灯光**", "**光线**", "**场景**", "【灯光】", "【光线】", "【场景】")
L1_COMP_LABELS = ("**构图**", "【构图】")
L1_LAYERS = (("前景", ("前景",)), ("中景", ("中景",)), ("背景", ("背景", "后景")))


def _label_lines(block: str, labels: tuple) -> list[str]:
    return [ln for ln in block.split("\n") if ln.lstrip().startswith(labels)]


def l1_checks(shots: list, blocks: list[str]) -> dict:
    """→ {"flat#<镜号>": (ok, 说明), "layers#<镜号>": (ok, 说明)}，只返回有问题的镜（失败项）。
    flat：【灯光】/【光线】/【场景】行出现平光句 -> 阻断；layers：两人以上在画（cast presence=在画）的镜，【构图】缺前景 / 中景 / 背景任一层 -> 阻断"""
    bad: dict = {}
    for s, b in zip(shots, blocks):
        hit = [m.group(0) for ln in _label_lines(b, L1_LIGHT_LABELS) for m in FLAT_LIGHT.finditer(ln)]
        if hit:
            bad[f"flat#{s.index}"] = (False, f"镜{s.index} 灯光 / 光线 / 场景行写了平光句「{'、'.join(dict.fromkeys(hit))}」："
                                              "改写有动机主光（方向 + 光比 ≤3:1）+ 负补光 + 背景比人物低 1–2 档")
        on = [c.name for c in (s.cast or []) if getattr(c, "presence", "") == "在画"]
        if len(on) >= 2:
            comp = " ".join(_label_lines(b, L1_COMP_LABELS))
            miss = [nm for nm, ws in L1_LAYERS if not any(w in comp for w in ws)]
            if miss:
                bad[f"layers#{s.index}"] = (False, f"镜{s.index} {len(on)} 人在画，构图缺{'、'.join(miss)}："
                                                    "写“前景=谁的什么部位略在焦外｜中景=谁在焦点上｜背景=谁或什么陈设”，cast 的 depth 与之一致")
    return bad


# ---- L2（镜头语言，项目方 11-05“镜头取景缺一致性、没有运镜、像手机拍的”；K-WRT-810–815）：集头镜头规划、运镜词表 + 动机 + 固定占比、
#      焦段档位、轴线 / 视线方向、剪辑点、竖屏构图。只在写作 / 导入闸门用，不碰已导入的剧
L2_STATIC_MAX = 0.20                      # 固定镜头整集占比上限（K-WRT-813）
L2_PLAN_LABEL = "本集镜头规划"
L2_CUT_TYPES = ("动作匹配切", "视线匹配切", "声音匹配切", "声音先行", "硬切", "叠化")
L2_GAZE = re.compile(r"([一-龥]{2,3})(?:向|往)(左|右)(?:前方|后方|前|后|上|下)?(?:看|望|瞥|扫)([^，；｜。]*)")
L2_LENSES = Path(__file__).resolve().parents[2] / "config" / "director" / "lenses.yaml"
_L2_CACHE: dict = {}


def _camera_norm_mod():
    """services/agent/ns_agent/camera_norm.py（按文件路径载入；词表 + enabled 判定单一来源）"""
    if "cn" not in _L2_CACHE:
        import importlib.util
        f = Path(__file__).resolve().parents[2] / "services" / "agent" / "ns_agent" / "camera_norm.py"
        sp = importlib.util.spec_from_file_location("rubric_camera_norm", f)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _L2_CACHE["cn"] = m
    return _L2_CACHE["cn"]


def lens_ids() -> set[str]:
    if "lens" not in _L2_CACHE:
        import yaml
        d = yaml.safe_load(L2_LENSES.read_text(encoding="utf-8")) if L2_LENSES.exists() else {}
        _L2_CACHE["lens"] = {str(x["id"]) for x in (d.get("lenses") or [])}
    return _L2_CACHE["lens"]


def l2_move_id(text: str) -> str | None:
    """【运镜】/【镜头运动】首段、motion 触发词后前两段 → 词表 id（camera_norm.match_zh，最长别名优先）"""
    head = "，".join([p for p in re.split(r"[｜|]", text or "", 1)][:1])
    return _camera_norm_mod().match_zh(head) if head.strip() else None


def l2_motion_id(motion: str) -> str | None:
    segs = [p.strip() for p in re.split(r"[，,]", motion or "") if p.strip()]
    cn = _camera_norm_mod()
    for k in range(min(3, len(segs))):          # 触发词可能占第一段；运镜 id 本身（bolt_push_settle）是一段
        t = segs[k].lower()
        if cn.move(t):
            return t
        mid = cn.match_zh(segs[k])
        if mid:
            return mid
    return None


def l2_checks(shots: list, blocks: list[str], head: str = "", run: str | None = None) -> dict:
    """→ {"<项>#<镜号|0>": (ok, 说明)}，只返回失败项。
    plan#0   集头缺“本集镜头规划”段（轴线 / 焦段档位 / coverage）                                   K-WRT-810
    axis#n   【构图】视线方向=“甲向左看乙”与人物行里乙的左右位置矛盾                                  K-WRT-811
    lens#n   【镜头】缺或不是 lenses.yaml 的 id；lens#scene 同场同景别两镜焦段不同（跳档）              K-WRT-812
    move#n   【运镜】首段不在词表 / 本剧不可用 / 没写“动机=”；与 motion、【镜头运动】的运镜不是同一种   K-WRT-813
    static#0 固定镜头占比 > 20%                                                                       K-WRT-813
    cut#n    【下镜】类型不在 动作匹配切 / 视线匹配切 / 声音匹配切 / 声音先行 / 硬切 / 叠化；硬切没写理由  K-WRT-814
    vert#n   单人镜【构图】没写“上三分之一”或“留出空间 / 留白”（竖屏）                                 K-WRT-815"""
    bad: dict = {}
    cn = _camera_norm_mod()
    if head is not None and head != "" and L2_PLAN_LABEL not in head:
        bad["plan#0"] = (False, f"集头缺“{L2_PLAN_LABEL}”段：写本集每场的轴线、焦段档位（lenses.yaml id）、主镜头 / 过肩 / 单人分配")
    n_static = 0
    lens_by_key: dict[tuple, dict] = {}
    for s, b in zip(shots, blocks):
        i = s.index
        cam = _field(b, "运镜")
        mid = l2_move_id(cam)
        if not cam:
            bad[f"move#{i}"] = (False, f"镜{i} 没写【运镜】：写词表运镜名｜幅度｜起幅 → 落幅｜动机=…")
        elif mid is None:
            bad[f"move#{i}"] = (False, f"镜{i} 【运镜】首段“{cam.split('｜')[0][:12]}”不在运镜词表 config/director/camera_moves.yaml 里")
        elif not cn.is_enabled(mid, run, motion=_field(b, "motion") or None):
            bad[f"move#{i}"] = (False, f"镜{i} 【运镜】{mid} 在词表里 disabled 或本剧不可用（视频端会退回固定）：换 enabled 的运镜")
        elif "动机=" not in cam:
            bad[f"move#{i}"] = (False, f"镜{i} 【运镜】没写“动机=”：每镜运镜要写它为什么动（情绪 / 发现 / 跟随 / 高点…），固定镜头写为什么不动")
        else:
            others = {k: v for k, v in (("motion", l2_motion_id(_field(b, "motion"))), ("镜头运动", l2_move_id(_field(b, "镜头运动"))))
                      if v is not None and v != mid}
            if others:
                bad[f"move#{i}"] = (False, f"镜{i} 【运镜】{mid} 与 " + "、".join(f"{k} 的 {v}" for k, v in others.items()) + " 不是同一种运镜")
        if mid == "static":
            n_static += 1
        lens = _field(b, "镜头").strip()
        lid = lens.split("｜", 1)[0].strip()
        if not lens:
            bad[f"lens#{i}"] = (False, f"镜{i} 没写【镜头】：写 config/director/lenses.yaml 的 id（同场同景别档同焦段）")
        elif lid not in lens_ids():
            bad[f"lens#{i}"] = (False, f"镜{i} 【镜头】“{lid[:24]}”不是 lenses.yaml 的 id")
        else:
            key = (getattr(s, "scene_id", None) or "", _size(_img(b)) or "")
            prev = lens_by_key.setdefault(key, {"shot": i, "lens": lid})
            if prev["lens"] != lid:
                bad[f"lens#{i}"] = (False, f"镜{i} 与镜{prev['shot']} 同场同景别（{key[1]}）焦段不同（{prev['lens']} / {lid}）：同场同景别档用同一焦段")
        pos = {c.name: getattr(c, "x", None) for c in (s.cast or []) if getattr(c, "presence", "") == "在画"}
        comp = _field(b, "构图")
        gaze = comp.split("视线方向=", 1)[1] if "视线方向=" in comp else ""
        for who, d, rest in L2_GAZE.findall(gaze):
            tgt = next((nm for nm in pos if nm != who and nm in rest), None)
            if tgt and pos.get(tgt) in ("左", "右") and pos[tgt] != d:
                bad[f"axis#{i}"] = (False, f"镜{i} 构图视线方向“{who}向{d}看{tgt}”与人物行 {tgt} 在{pos[tgt]}矛盾（轴线 / 视线不一致）")
                break
        cut = _field(b, "下镜")
        ctype = cut.split("｜", 1)[0].strip()
        if cut and not any(ctype.startswith(t) for t in L2_CUT_TYPES):
            bad[f"cut#{i}"] = (False, f"镜{i} 【下镜】类型“{ctype[:10]}”不在 {' / '.join(L2_CUT_TYPES)} 里")
        elif ctype.startswith("硬切") and "理由" not in cut:
            bad[f"cut#{i}"] = (False, f"镜{i} 【下镜】硬切没写理由：同场相邻镜用动作 / 视线 / 声音匹配切，硬切写“理由=…”")
        if len(pos) == 1 and comp and not (re.search(r"三分之一|1/3", comp) and re.search(r"留出空间|留白|留空", comp)):
            bad[f"vert#{i}"] = (False, f"镜{i} 单人镜【构图】要写主体在上三分之一 + 视线方向留出空间（竖屏 9:16）")
    if shots and n_static / len(shots) > L2_STATIC_MAX:
        bad["static#0"] = (False, f"固定镜头 {n_static}/{len(shots)} = {n_static / len(shots):.0%} > {L2_STATIC_MAX:.0%}：每镜要有动机运镜（词表 enabled 的推近 / 按剧运镜），固定只留给有理由的镜")
    return bad


# ---- L3 焦段光圈表（L-192 ③，项目方 11-05“要 f/1.2 光学虚化、焦段不对、没电影感”；K-WRT-816–818）。只给 warn，级别跟 WRITER_LINT_LEVEL
#      （kind, mm 范围, T 范围）；每镜【光学】= 焦段(全画幅等效 mm)｜T 光圈｜高度=机位高度
L3_TABLE = {"establishing": ((24, 35), (2.8, 4.0), "全景 / 远景 / 中全景（建立镜头，一场最多一个）"),
            "medium": ((40, 50), (2.0, 2.0), "双人 / 中景（人物前后错落）"),
            "ots_mcu": ((65, 85), (1.4, 2.0), "过肩 / 单人近景 / 中近景"),
            "closeup": ((85, 135), (1.2, 1.4), "特写 / 大特写"),
            "insert": ((90, 105), (2.0, 2.0), "插入镜头（微距 100mm）")}
L3_LABELS = ("光学", "镜头", "机位与景别", "机位")
L3_MM = re.compile(r"(\d{2,3})\s*(?:mm|毫米)", re.I)
L3_T = re.compile(r"(?<![A-Za-z_])T\s*(\d+(?:\.\d+)?)", re.I)
L3_HEIGHT = re.compile(r"(?:机位)?高度\s*[=：:]?\s*[^｜；，。\s]{1,12}")
L3_PRACTICAL = re.compile(r"灯架|灯泡|灯串|灯光|灯|霓虹|反光板|监视器|摄影器材|器材|柔光箱|光源|烛|窗|电视|屏幕|路灯|车灯")
L3_SIDE = re.compile(r"并排|并肩|一字排开|横排|横向排开|平行站|正对镜头|面向镜头|对着镜头")
L3_OVERSHOULDER = re.compile(r"过肩|OTS", re.I)
L3_INSERT = re.compile(r"插入|微距|道具特写|物件特写|手部特写")


def _lens_spec(lid: str) -> str:
    """lenses.yaml id → “85mm T1.4”（【镜头】只写 id 时，QW-L9 从这里取焦段 / T 值，与 QW-L4 口径合一：L4 只管 id 合法 + 同场同景别同焦段，表内范围只由 L9 报一次）"""
    if "lens_full" not in _L2_CACHE:
        import yaml
        d = yaml.safe_load(L2_LENSES.read_text(encoding="utf-8")) if L2_LENSES.exists() else {}
        _L2_CACHE["lens_full"] = {str(x["id"]): x for x in (d.get("lenses") or [])}
    x = _L2_CACHE["lens_full"].get(lid.strip())
    if not x or not x.get("focal_mm"):
        return ""
    ap = re.search(r"\d+(?:\.\d+)?", str(x.get("aperture") or ""))
    return f"{int(x['focal_mm'])}mm" + (f" T{ap.group(0)}" if ap else "")


def l3_shot_type(s, b: str) -> str:
    img = _img(b)
    on = [c for c in (s.cast or []) if getattr(c, "presence", "") == "在画"]
    sz = _size(img) or ""
    if L3_INSERT.search(img[:80]) and not on:
        return "insert"
    if L3_OVERSHOULDER.search(img + _field(b, "构图")):
        return "ots_mcu"
    if sz in ("全景", "远景", "中全景"):
        return "establishing"
    if sz in ("特写", "大特写"):
        return "closeup"
    if sz in ("近景", "中近景"):
        return "ots_mcu"
    return "medium"


def l3_checks(shots: list, blocks: list[str]) -> dict:
    """→ {"<项>#<镜号|scene>": (ok, 说明)}，只返回失败项。
    optic#n  【光学】缺焦段 mm / T 光圈 / 机位高度；或 焦段 + T 不在该景别档的允许表里          K-WRT-816
    estab#s  同一场建立镜头（24–35mm）多于一个                                              K-WRT-816
    bokeh#n  【构图】背景层没写远处的实景光源 / 器材（焦外光斑的素材）                          K-WRT-817
    twoshot#n 两人以上在画：【构图】写并排 / 并肩 / 正对镜头，或 cast 景深层全相同             K-WRT-818"""
    bad: dict = {}
    estab: dict = {}
    for s, b in zip(shots, blocks):
        i = s.index
        txt = " ".join(_field(b, lb) for lb in L3_LABELS)
        if not L3_MM.search(_field(b, "光学")):      # 没写【光学】：用【镜头】id 对应的焦段 / T 值（lenses.yaml）
            txt += " " + _lens_spec(_field(b, "镜头").split("｜", 1)[0])
        typ = l3_shot_type(s, b)
        (mlo, mhi), (tlo, thi), name = L3_TABLE[typ]
        mm = L3_MM.search(txt)
        tt = L3_T.search(txt)
        hh = L3_HEIGHT.search(txt)
        miss = [n for n, v in (("焦段 mm", mm), ("T 光圈", tt), ("机位高度", hh)) if not v]
        if miss:
            bad[f"optic#{i}"] = (False, f"镜{i} 【光学】缺{'、'.join(miss)}：写“{mlo}–{mhi}mm｜T{tlo:g}–{thi:g}｜高度=…”（{name}）")
        else:
            m, t = int(mm.group(1)), float(tt.group(1))
            if not (mlo <= m <= mhi) or not (tlo - 1e-6 <= t <= thi + 1e-6):
                bad[f"optic#{i}"] = (False, f"镜{i} {name}：{m}mm T{t:g} 不在允许表（{mlo}–{mhi}mm、T{tlo:g}–{thi:g}）")
        if typ == "establishing":
            sc = getattr(s, "scene_id", None) or ""
            if sc in estab:
                bad[f"estab#{i}"] = (False, f"镜{i} 与镜{estab[sc]} 同场都是建立镜头（24–35mm）：一场最多一个，其余用 40mm 以上")
            else:
                estab[sc] = i
        comp = _field(b, "构图")
        bg = comp.split("背景", 1)[1] if "背景" in comp else ""
        if comp and not L3_PRACTICAL.search(bg):
            bad[f"bokeh#{i}"] = (False, f"镜{i} 【构图】背景层没写远处的实景光源 / 器材（灯架、灯泡、霓虹、监视器、窗…）：焦外要有东西才有光斑")
        on = [c for c in (s.cast or []) if getattr(c, "presence", "") == "在画"]
        if len(on) >= 2:
            depths = {getattr(c, "depth", None) for c in on} - {None, ""}
            if L3_SIDE.search(comp) or (depths and len(depths) == 1 and len(on) >= 2):
                bad[f"twoshot#{i}"] = (False, f"镜{i} {len(on)} 人在画：不要并排 / 并肩 / 正对镜头站（景深层全相同），要前后错落、身体斜 45°")
    return bad
