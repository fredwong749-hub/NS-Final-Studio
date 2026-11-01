"""P3-P4 系统预拼句子片段（SERIES 2026-10-31，总调度定：逐字锚点 / 说话人 / 画外类改为系统预拼、写作模型照抄）。

为什么：series10_v1 两次全集实跑，P4 剩余 block 里 H3-X1 / H3-X3 / H3-X4 占 22/35，返修 2 轮也修不好，原因有规律：
  - H3-X1：登记 EN 外貌短语以冠词 a 开头，写作模型改成 one / the → 逐字比对失败；
  - H3-X3：VOICE 被意译（a warm bright voice → a warm bright tone）；
  - H3-X4：画外说话人要满足 H3-D8（年龄 / 性别 / 画内外 / 音色 / 语速），写作模型就把整句外貌短语写了进去。
所以系统按人物表 + 登记造型把这三处的句子片段拼好，写作模型逐字照抄；返修时按镜点名要插入 / 删除的片段。
只拼格式片段（人物表 / 造型登记原文 + 固定连接词），不写剧情。规则：knowledge K-WRT-206。

    block_for(chars, looks)                 -> 写进 P3-P4 用户消息的【系统预拼片段】段
    repair_lines(gate_raw, md, chars, looks) -> 逐镜返修句（H3-X1 / X3 / X4 / SS-M2）
"""
from __future__ import annotations

import re

GENDER_EN = {"女": "woman", "男": "man"}


def _c(c, k):
    return c.get(k) if isinstance(c, dict) else getattr(c, k)


def speaker_on(c, n: int = 1) -> str:
    """在画说话人：满足 H3-X3（VOICE 逐字）+ H3-D8（年龄 / 性别 / on-screen / 音色 / 语速），不含外貌短语"""
    return f"the on-screen {_c(c, 'age')}-year-old {GENDER_EN.get(_c(c, 'gender'), 'person')} with {_c(c, 'voice_phrase')} (S{n}) says"


def speaker_off(c, n: int = 1) -> str:
    """画外说话人：同上，但不出现外貌短语（H3-X4）"""
    return (f"an off-screen {_c(c, 'age')}-year-old {GENDER_EN.get(_c(c, 'gender'), 'person')} with {_c(c, 'voice_phrase')} "
            f"(S{n}) says in an off-screen voiceover:")


def anchors(c, look_en: str | None) -> str:
    """锚点句（H3-X1）：EN 外貌短语 + in + 造型 EN，两段都逐字（开头的 a 不改成 one / the）"""
    return f"{_c(c, 'en_phrase')} in {look_en}" if look_en else _c(c, "en_phrase")


def block_for(chars: list, looks: list[dict] | None = None) -> str:
    """P3-P4 用户消息附加段。chars = storyline 人物卡（本集），looks = P1 造型登记（可空）"""
    lk = {l["name"]: l for l in looks or []}
    rows = []
    for c in chars:
        name = _c(c, "name")
        ls = (lk.get(name) or {}).get("looks") or []
        anc = "；".join(f"造型{x['id']}：「{anchors(c, x['en'])}」" for x in ls) or f"「{anchors(c, None)}」"
        rows.append(f"- {name}\n  · 在画时锚点句片段（按本镜造型选一条）：{anc}\n"
                    f"  · 在画说话时：「{speaker_on(c)}」\n  · 画外说话时：「{speaker_off(c)}」")
    return ("【系统预拼片段（逐字照抄，规则 K-WRT-206 / H3-X1 / H3-X3 / H3-X4 / H3-D8）】\n"
            "- H3 正文第一句（锚点句）里，每个在画角色写一次他的锚点句片段，逐字（含开头的 a，不改成 one / the；造型 EN 与本集造型行 EN 一致）。\n"
            "- 说话人第一次开口的那一句，用对应的“在画说话时 / 画外说话时”片段，逐字；(S1) 按本镜开口顺序编号（普通对话镜只有 S1）。\n"
            "- **人物** 行写了画外 / 局部的角色，H3 正文里不写他的 EN 外貌短语；要介绍他说话，只用“画外说话时”片段。\n"
            + "\n".join(rows))


_SHOT_RE = re.compile(r"ep\d+-S(\d+)")


def _cast_of(md: str) -> dict[int, dict[str, str]]:
    """{镜号: {角色: 在画 / 画外 / 局部}}，取自 P4 **人物** 行"""
    out = {}
    for b in re.split(r"(?m)^(?=\*\*镜\d+｜img)", md)[1:]:
        n = int(re.match(r"\*\*镜(\d+)", b).group(1))
        m = re.search(r"^\*\*人物\*\*[：:](.*)$", b, re.M)
        out[n] = {x.group(1).strip(): x.group(2) for x in re.finditer(r"([^、（]+)（(在画|画外|局部)", m.group(1))} if m else {}
    return out


def _has_both(md: str, n: int) -> bool:
    for b in re.split(r"(?m)^(?=\*\*镜\d+｜img)", md)[1:]:
        if int(re.match(r"\*\*镜(\d+)", b).group(1)) == n:
            return bool(re.search(r"^\*\*对白\*\*", b, re.M)) and bool(re.search(r"^\*\*🎙", b, re.M))
    return False


def repair_lines(gate_raw: dict, md: str, chars: list, looks: list[dict] | None = None) -> list[str]:
    """把导入关口的 H3-X1 / X3 / X4 issue 换成“镜N 逐字插入 / 删除哪个片段”（确定性），SS-M2 等其余照原文点名"""
    byname = {_c(c, "name"): c for c in chars}
    cast = _cast_of(md)
    out = []
    for e in gate_raw.get("episodes") or []:
        for sh in e.get("shots") or []:
            m = _SHOT_RE.search(sh.get("id", ""))
            if not m:
                continue
            n = int(m.group(1))
            for i in sh.get("issues") or []:
                if i.get("level") != "block":
                    continue
                rid, det = i.get("rule_id"), i.get("detail", "")
                if rid == "H3-X1":
                    phr = [p.split("：", 1)[1] for p in det.split("缺少：", 1)[-1].split("；") if "：" in p]
                    out.append(f"镜{n}（H3-X1）：H3 正文第一句必须逐字包含 " + "、".join(f"「{p}」" for p in phr)
                               + "（开头的 a 不改成 one / the；可写成“<外貌短语> in <造型 EN>”）。")
                elif rid == "H3-X3":
                    for mm in re.finditer(r"\(S(\d+)\) ([^：]+)：", det):
                        sn, who = int(mm.group(1)), mm.group(2).strip()
                        c = byname.get(who)
                        if c is None:
                            continue
                        frag = speaker_off(c, sn) if cast.get(n, {}).get(who) in ("画外", "局部") else speaker_on(c, sn)
                        out.append(f"镜{n}（H3-X3）：{who} 第一次开口的那一句改成以「{frag}」引出台词，VOICE 逐字，不意译。")
                elif rid == "QW-M1" and ("对白避让" in det or "独白避让" in det):
                    # 规则原文“避让只用 对白避让/独白避让/无需避让”被读成三选一；同镜既有台词又有 🎙 时两个都要写（校验按包含判）
                    if ("台词" in det and "🎙" in det) or _has_both(md, n):
                        want = "对白避让，独白避让」——这一镜既有台词又有 🎙，两个都写"
                    else:
                        want = "对白避让」" if "台词" in det else "独白避让」"
                    out.append(f"镜{n}（QW-M1）：【配乐】的避让写成「{want}（只改这一处）。")
                elif rid == "H3-X4":
                    mm = re.search(r"不在画的角色 (\S+) 的外貌出现在正文里.*?：(.*)$", det)
                    if mm:
                        who, ph = mm.group(1), mm.group(2).strip()
                        c = byname.get(who)
                        alt = f"；他要说话就用「{speaker_off(c)}」" if c is not None else ""
                        out.append(f"镜{n}（H3-X4）：{who} 本镜不在画，删掉 H3 正文里的「{ph}」{alt}。")
    return list(dict.fromkeys(out))


def speech_lines(md: str, dialogue: list[tuple[str, str]], voiceover: list[tuple[str, str]]) -> list[str]:
    """LK34-01 / LK34-03 的具体原因（series10_v1：只说“拼接后不相等”时写作模型两轮都修不对）：
    同一镜写了两条 🎙（导入器一镜只认一条）、同一段独白在两镜重复、剧本台词 / 独白整句没进任何镜。dialogue / voiceover = [(说话人, 原文)]"""
    out = []
    shots = re.split(r"(?m)^(?=\*\*镜\d+｜img)", md)[1:]
    seen: dict[str, int] = {}
    vo_by = {int(re.match(r"\*\*镜(\d+)", b).group(1)): re.findall(r"^\*\*🎙（[^）]*）\*\*[：:](.*)$", b, re.M) for b in shots}
    free = [k for k, v in sorted(vo_by.items()) if not v]
    for b in shots:
        n = int(re.match(r"\*\*镜(\d+)", b).group(1))
        vos = vo_by[n]
        if len(vos) > 1:
            # 保持独白顺序：本镜留最后一条，前面几条依次挪到本镜之前最近的空镜（没有就挪到之后的空镜）
            before = [k for k in free if k < n][::-1]
            after = [k for k in free if k > n]
            for v in vos[:-1][::-1]:
                tgt = before.pop(0) if before else (after.pop(0) if after else None)
                if tgt is not None:
                    free.remove(tgt)
                    out.append(f"镜{n}（LK34-03）：这一镜有 {len(vos)} 条 🎙，一镜只能一条——把「{v.strip()[:30]}」整条移到镜{tgt} 的 🎙 行（镜{tgt} 现在没有 🎙），原文不改，镜{n} 只留「{vos[-1].strip()[:20]}」。")
                else:
                    out.append(f"镜{n}（LK34-03）：这一镜有 {len(vos)} 条 🎙，一镜只能一条；别的镜都有 🎙 了——新增一镜放「{v.strip()[:30]}」（镜数仍在上限内）。")
        for v in vos:
            v = v.strip()
            if v in seen:
                out.append(f"镜{n}（LK34-03）：🎙「{v[:30]}」和镜{seen[v]} 重复，剧本里只有一次——删掉其中一镜的这条 🎙。")
            seen.setdefault(v, n)
    flat = re.sub(r"\s+", "", md)
    for who, t in dialogue:
        if re.sub(r"\s+", "", t) not in flat:
            out.append(f"（LK34-01）剧本台词（{who}）「{t}」没出现在任何镜：放进对应镜的 **对白** 行，并在该镜 H3 正文写同一句 <d>，原文逐字。")
    for who, t in voiceover:
        if re.sub(r"\s+", "", t) not in flat:
            out.append(f"（LK34-03）剧本独白（{who}）「{t}」没出现在任何镜：放进一镜的 🎙 行（该镜没有别的 🎙），原文逐字。")
    return list(dict.fromkeys(out))


def spec_lines(issues: list[dict]) -> list[str]:
    """Shot Spec 层（P4-SPEC：SS-M2 等）的 issue → “镜N：…”（field 形如 ep02-S4.motion.beats）"""
    out = []
    for i in issues:
        if i.get("level") != "block" or i.get("rule") != "P4-SPEC":
            continue
        m = _SHOT_RE.search(i.get("field", ""))
        if not m:
            continue
        msg = i.get("message", "")
        tip = "——**分拍** 续写到镜长（最后一拍的止 = 镜长），H3 分拍时间同步" if "SS-M2" in msg else ""
        out.append(f"镜{m.group(1)}：{msg}{tip}。")
    return list(dict.fromkeys(out))


def fix_cue_avoid(md: str, shots: set[int] | None = None) -> tuple[str, list[str]]:
    """系统确定性修正（总调度 2026-10-31：返修后仍剩的结构 / 枚举问题由系统处理，不再找写作模型）：
    只改 **sound** 行【配乐】里的避让枚举词，使之与本镜是否有台词 / 🎙 一致（QW-M1）。不碰台词、画面、H3。
    shots = 只改这些镜（导入关口点名 QW-M1 的镜）；None = 全部。→ (新稿, 改动记录)"""
    parts = re.split(r"(?m)^(?=\*\*镜\d+｜img)", md)
    log = []
    for k, b in enumerate(parts[1:], 1):
        n = int(re.match(r"\*\*镜(\d+)", b).group(1))
        if shots is not None and n not in shots:
            continue
        has_d = bool(re.search(r"^\*\*对白\*\*[：:]\s*\S", b, re.M))
        has_v = bool(re.search(r"^\*\*🎙", b, re.M))
        want = "，".join(x for x, ok in (("对白避让", has_d), ("独白避让", has_v)) if ok) or "无需避让"

        def sub(m):
            cue = m.group(1)
            segs = [s for s in re.split(r"[，,]", cue) if s.strip() and s.strip() not in ("对白避让", "独白避让", "无需避让")]
            new = "，".join(segs + [want])
            if new != cue:
                log.append(f"镜{n}：【配乐】{cue} → {new}")
            return f"【配乐】{new}"
        parts[k] = re.sub(r"【配乐】([^；;\n]*)", sub, b, count=1)
    return parts[0] + "".join(parts[1:]), log


# ---------------------------------------------------------------- 结构类剩余问题：系统算候选，写作模型只在候选里选（总调度 2026-10-31）
def shot_table(md: str) -> list[dict]:
    """[{n, dur, scene, cast{名: 在画/画外/局部}, dlg[(说话人, 原文)], vo}]"""
    out = []
    for b in re.split(r"(?m)^(?=\*\*镜\d+｜img)", md)[1:]:
        n = int(re.match(r"\*\*镜(\d+)", b).group(1))
        g = lambda f: (re.search(rf"^\*\*{f}\*\*[：:](.*)$", b, re.M) or [None, ""])[1]   # noqa: E731
        dur = int((re.search(r"\d+", g("时长")) or [0])[0]) if re.search(r"\d+", g("时长")) else 0
        cast = {x.group(1).strip(): x.group(2) for x in re.finditer(r"([^、（]+)（(在画|画外|局部)", g("人物"))}
        dlg = [(m.group(1).split("，")[0].strip(), m.group(2)) for m in re.finditer(r"（([^）]*)）“([^”]*)”", g("对白"))]
        out.append({"n": n, "dur": dur, "scene": g("场景").split("｜")[0].strip(), "cast": cast, "dlg": dlg,
                    "vo": bool(re.search(r"^\*\*🎙", b, re.M))})
    return out


def _fits(sh: dict, text: str, extra_speech: int = 0) -> bool:
    used = sum(len(t) for _, t in sh["dlg"]) + extra_speech
    return (used + len(text)) / 3.5 <= sh["dur"] - 0.3


def missing_line_options(md: str, speech: list[tuple[str, str]], idx: int, k: int = 2) -> list[dict]:
    """剧本第 idx 句台词（speech = P3 全部对白，按序）没进分镜 → 候选镜（≤k 个）：
    位于前一句已落镜与后一句已落镜之间；不与别的说话人同镜（H3-D7）；时长放得下（3.5 字 / 秒）；
    无台词的镜优先（时长长的先），其次是同一说话人已有台词的镜（接在后面）。"""
    who, text = speech[idx]
    tab = shot_table(md)
    where = {}
    for sh in tab:
        for d in sh["dlg"]:
            where.setdefault(d, sh["n"])
    prev = max([where[s] for s in speech[:idx] if s in where] or [tab[0]["n"]])
    nxt = min([where[s] for s in speech[idx + 1:] if s in where] or [tab[-1]["n"]])
    cands = []
    for sh in tab:
        if not prev <= sh["n"] <= nxt:
            continue
        others = {s for s, _ in sh["dlg"]} - {who}
        if others or not _fits(sh, text):
            continue
        pres = sh["cast"].get(who) or "画外"
        rank = (0 if not sh["dlg"] else 1, -sh["dur"], abs(sh["n"] - prev))
        cands.append((rank, {"shot": sh["n"], "speaker": who, "text": text, "presence": pres,
                             "how": ("本镜目前没有台词，加这一句" if not sh["dlg"] else "接在本镜同一说话人的台词后面"),
                             "add_cast": who not in sh["cast"]}))
    return [c for _, c in sorted(cands, key=lambda x: x[0])][:k]


def split_two_speaker_plan(md: str, shot_n: int, cap: int) -> dict | None:
    """H3-D7（普通对话镜一镜一人）：把 shot_n 的两人对白拆成相邻两镜（各一人，画外者写画外）；
    拆后镜数超上限 cap 时，把同场景相邻两个无台词过渡镜合并为一镜（时长相加，≤15 秒）。只给拆法，画面由写作模型填。"""
    tab = shot_table(md)
    sh = next((x for x in tab if x["n"] == shot_n), None)
    if sh is None or len({s for s, _ in sh["dlg"]}) < 2:
        return None
    first, second = sh["dlg"][0], sh["dlg"][1]
    half = max(4, (sh["dur"] + 1) // 2)
    plan = {"shot": shot_n, "split": [
        {"part": "a", "dur": half, "line": first, "cast": {first[0]: sh["cast"].get(first[0], "画外"), second[0]: sh["cast"].get(second[0], "在画")}},
        {"part": "b", "dur": half, "line": second, "cast": {second[0]: "在画"}}], "merge": None}
    if len(tab) + 1 > cap:
        pairs = []
        for a, b in zip(tab, tab[1:]):
            if a["dlg"] or b["dlg"] or a["vo"] and b["vo"] or a["scene"] != b["scene"] or a["dur"] + b["dur"] > 15 or shot_n in (a["n"], b["n"]):
                continue
            pairs.append((a["dur"] + b["dur"], a["n"], b["n"]))
        if not pairs:
            return None
        tot, a, b = min(pairs)
        plan["merge"] = {"shots": [a, b], "dur": tot}
    return plan


# ---------------------------------------------------------------- 自动修复（总调度 2026-10-31：预拼片段缺失时由系统补全，不再需要人点头）
_DESC_RE = re.compile(r"(integrated_multimodal_description:\s*)(.*)")


def _first_sentence_end(desc: str) -> int:
    m = re.search(r"[.!?](?=\s|$)", desc)
    return m.start() if m else len(desc)



def fix_anchors(md: str, gate_raw: dict, chars: list | None = None, looks: list[dict] | None = None) -> tuple[str, list[str]]:
    """H3-X1：锚点句（H3 正文第一句）缺系统预拼片段 → 逐字补进第一句（只改这一个格式片段）。
    缺造型 EN：句中若写了同一角色的另一套登记造型 EN → 换成本镜造型；否则紧跟该角色登记外貌短语插入 “ in <造型 EN>”。
    缺外貌短语：在第一句句号前补 “, with <外貌短语>[ in <造型 EN>]”。→ (新稿, 改动记录)"""
    need: dict[int, list[tuple[str, str, str]]] = {}
    for e in gate_raw.get("episodes") or []:
        for sh in e.get("shots") or []:
            m = _SHOT_RE.search(sh.get("id", ""))
            for i in sh.get("issues") or []:
                if m and i.get("rule_id") == "H3-X1" and i.get("level") == "block":
                    for p in i.get("detail", "").split("缺少：", 1)[-1].split("；"):
                        mm = re.match(r"(\S+) (EN外貌短语|造型 EN)：(.+)$", p.strip())
                        if mm:
                            need.setdefault(int(m.group(1)), []).append((mm.group(1), mm.group(2), mm.group(3).strip()))
    if not need:
        return md, []
    en_of = {_c(c, "name"): _c(c, "en_phrase") for c in chars or []}
    other_looks = {l["name"]: [k["en"] for k in l.get("looks") or []] for l in looks or []}
    parts = re.split(r"(?m)^(?=\*\*镜\d+｜img)", md)
    log = []
    for k, b in enumerate(parts[1:], 1):
        n = int(re.match(r"\*\*镜(\d+)", b).group(1))
        m = _DESC_RE.search(b) if n in need else None
        if not m:
            continue
        desc = m.group(2)
        items = need[n]
        for who in dict.fromkeys(w for w, _, _ in items):
            en = next((p for w, lab, p in items if w == who and lab == "EN外貌短语"), None)
            look = next((p for w, lab, p in items if w == who and lab == "造型 EN"), None)
            end = _first_sentence_end(desc)
            first = desc[:end]
            if en is None and look:
                wrong = next((x for x in other_looks.get(who, []) if x != look and x in first), None)
                base = en_of.get(who)
                # 镜号顺延（合并 / 拆镜）后造型切换行还写旧镜号：本镜 img 写了“镜n起…换装”，且锚点句用的正是某条
                # “造型｜<角色>｜镜M起”（M≠n）的造型 → 改那一行的镜号为 n（以本镜画面为准），不动锚点句
                hdr = re.search(rf"^\*\*造型｜{re.escape(who)}｜镜(\d+)起\*\*[：:][^\n]*EN={re.escape(wrong[:30])}", parts[0], re.M) if wrong else None
                if hdr and int(hdr.group(1)) != n and re.search(rf"镜{n}起", b.splitlines()[0]):
                    parts[0] = parts[0][:hdr.start(1)] + str(n) + parts[0][hdr.end(1):]
                    log.append(f"镜{n}：造型切换行“{who}｜镜{hdr.group(1)}起”改为“镜{n}起”（镜号顺延后没跟着改；本镜 img 写明镜{n}起换装，H3-X1）")
                elif wrong:
                    desc = first.replace(wrong, look, 1) + desc[end:]
                    log.append(f"镜{n}：锚点句里 {who} 的造型 EN 换成本镜造型（“{wrong[:24]}…” → “{look[:24]}…”，H3-X1）")
                elif base and base in first:
                    i = first.index(base) + len(base)
                    desc = desc[:i] + f" in {look}" + desc[i:]
                    log.append(f"镜{n}：锚点句在 {who} 外貌短语后补“in {look[:30]}…”（H3-X1）")
                else:
                    desc = first + f", in {look}" + desc[end:]
                    log.append(f"镜{n}：锚点句句末补“in {look[:30]}…”（{who}，H3-X1）")
            elif en:
                add = f", with {en}" + (f" in {look}" if look else "")
                desc = first + add + desc[end:]
                log.append(f"镜{n}：锚点句补“{add[2:42]}…”（{who}，H3-X1）")
        parts[k] = b[:m.start(2)] + desc + b[m.end(2):]
    return parts[0] + "".join(parts[1:]), log


def auto_fix(md: str, episode: int, chars: list | None = None, looks: list[dict] | None = None) -> tuple[str, list[str]]:
    """写作模型返修用完后仍剩的“系统自有片段 / 枚举槽位”问题，由系统确定性补全（总调度 2026-10-31 授权，不需要人点头）：
    H3-X1 预拼锚点片段缺失 / 造型 EN 与本镜造型行不符 → fix_anchors；QW-M1 配乐避让枚举 → fix_cue_avoid（只改被点名的镜）。
    台词、画面描述不动；改动记录写进报告 system_fix。"""
    from p4_adapter import check_p4
    _, _, _, gate_raw = check_p4(md, episode)
    new, log = fix_anchors(md, gate_raw, chars, looks)
    m1 = set()
    for e in gate_raw.get("episodes") or []:
        for sh in e.get("shots") or []:
            mm = _SHOT_RE.search(sh.get("id", ""))
            if mm and any(i.get("rule_id") == "QW-M1" and i.get("level") == "block" for i in sh.get("issues") or []):
                m1.add(int(mm.group(1)))
    if m1:
        new, log2 = fix_cue_avoid(new, m1)
        log += log2
    return new, log
