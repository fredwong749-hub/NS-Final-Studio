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
        it = COUNT.sub("", ACC_PREFIX.sub("", re.sub(r"（.*", "", it.strip()))).strip()
        it = re.sub(r"(在颈间|在手上|在颈前)$", "", it)
        if len(it) >= 2 and not re.match(r"^(挂|在|戴|系|别)", it):
            out.append(it[-3:] if len(it) > 3 else it)
    return out


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
    cam_bad = []
    for s, b in zip(shots, blocks):
        cam = _field(b, "镜头运动")
        mv = cam.split("｜")[0]
        if not _size(_img(b)) or re.search(r"[+＋、/]|和|并", mv) or ("Arc" in mv and "幅度=小" not in cam):
            cam_bad.append(s.index)
    put("pika", 3, not cam_bad, f"景别缺失 / 多种运镜 / Arc 幅度不是小的镜：{cam_bad or '无'}")
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
