"""HOLLYWOOD r5（总调度 fredw-2b 派，11-02）：冲 50 / 50。

项目方 00:4x 原话：“我要全部系统化，出一个 Hollywood level 的、画面非常漂亮的短剧……我起码要达到 50 分，就是你给的那个分数，50 over 50。”
AskUserQuestion：“允许，剧情和人物不变 (Recommended)”（台词可为潜台词重写；发生了什么、谁说的、人物关系和设定不变）；“$50”（写作 API 预算，
先集中 3–4 集冲满分）。决定记 D-SCR-09 / L-096 / L-097；方案 docs/master/HOLLYWOOD_PLAN.md §1B。

复用 hollywood.py（拼输入、gate、格式返修、机械修正、暂存）；r5 只换三处：
1. 不变量 I1：台词逐字 → 剧情事实不变 = 代码核对（说话人逐条顺序、人物、场景）+ 独立事实核对调用（config/prompts/hollywood_facts.md 任务 B）；
   其余 I2–I7 照旧，QW-W11 = 0 升为硬条件（r4 是只报告）。
2. 写作：每轮并行 3 稿（best-of-3），第 1 轮整集改写，之后专项精修（每遍只改一个维度：5 秒钩子 → 转折 → 潜台词 → 结尾钩子 → 其余未满分项）。
   写作模型 --writer flash-high（large-flash reasoning high）/ v2（large-v2 长推理）/ flash（关推理）。
3. 评审：可核对清单（hollywood_judge.md §三–§五；分数 = 满足条数），三个独立评审（A / B / 刁钻 C）逐项平均。

    .venv/Scripts/python.exe tools/script_rsi/hollywood_r5.py run --episode 4 --root data/review_pages/hollywood_r5 --writer flash-high
    .venv/Scripts/python.exe tools/script_rsi/hollywood_r5.py ab --episode 4 --root data/review_pages/hollywood_r5      # 写作模型对比（各 1 稿）
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("hollywood", ROOT / "tools" / "script_rsi" / "hollywood.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)
RL, FR, RC = H.RL, H.FR, H.RC

FACTS_MD = H.PROMPTS / "hollywood_facts.md"
RUBRIC_JSON = H.PROMPTS / "hollywood_rubric.json"
R4_ROOT = ROOT / "data" / "review_pages" / "hollywood_s10"      # r4 选中版（作为 r0 基线）
POLISH_ORDER = ["hook5s", "turns", "subtext", "endhook"]       # 总调度：钩子 → 转折 → 潜台词 → 结尾钩子
# L-098（项目方 11-02 01:08“50 美金，尽量少收一点，太贵了”，总调度定）：r5 总上限 $15（含已花约 $3.5 + 首批 4 集），每集 ≤ $3；
# 连续 1 轮不涨即停；best-of-3 → best-of-2；精修只针对最低的 2 个维度。⤴ 取代 L-097 的 $50 / best-of-3 / 连续 2 轮
TARGET_IMPORT, TARGET_FULL, MAX_ROUNDS, BEST_OF = 48, 50, 8, 2
COST_CAP_USD, EP_CAP_USD, NO_GAIN_STOP = 15.0, 3.0, 1


# ------------------------------------------------------------------ 客户端

MAX_OUT = 64000      # ab 实测（11-02）：flash-high / v2 在 32000 上限都 finish=length（推理吃掉输出），flash-high 正文被截断、v2 无正文


def make_writer(kind: str, temperature: float = 0.7):
    w = FR.Writer(temperature=temperature, max_tokens=MAX_OUT)
    if kind.startswith("flash-") and kind != "flash":
        w.off = {"reasoning_effort": kind.split("-", 1)[1]}       # flash-high / flash-medium / flash-low
    elif kind == "v2":
        w.model, w.off = "abliterated-model-large-v2", {}
    w.kind = kind
    return w


class Budget(H.Budget):
    """按各客户端实际模型计价（large-v2 单价不同）"""

    def usage(self) -> dict:
        from ns_api import llm_config
        try:
            prices = llm_config.model_pricing("abliteration")
        except Exception:  # noqa: BLE001
            prices = {}
        u = {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0}
        for c in self.clients:
            cu = getattr(c, "usage", {}) or {}
            pr = prices.get(getattr(c, "model", ""), self.price)
            for k in ("calls", "failed", "prompt_tokens", "completion_tokens"):
                u[k] += int(cu.get(k) or 0)
            u["usd"] += int(cu.get("prompt_tokens") or 0) * pr["prompt"] + int(cu.get("completion_tokens") or 0) * pr["completion"]
        u["usd"] = round(u["usd"], 4)
        return u


# ------------------------------------------------------------------ 剧情事实

def speaker_seq(ep_obj) -> list[str]:
    out = []
    for s in sorted(ep_obj.shots, key=lambda s: s.index):
        out += [str(d.speaker or d.speaker_note or "") for d in s.dialogue]
        if s.voiceover and s.voiceover.text:
            out.append(f"🎙{s.voiceover.speaker}")
    return out


def facts_system() -> str:
    return FACTS_MD.read_text(encoding="utf-8")


def make_fact_client():
    """事实核对用 large-flash + reasoning medium（11-02 实测：关推理时原稿对自己的事实表核对也报 4–11 条假偏差；
    开 medium 后 ep02 / ep04 原稿自检 0 偏差，r4 版各报 1 条真实偏差）"""
    c = FR.Writer(temperature=0.1, max_tokens=40000)
    c.off = {"reasoning_effort": "medium"}
    return c


def extract_facts(client, pre: str, chunk: str, ep: int) -> dict:
    """抽取后用原稿对自己的事实表自检，必须 0 偏差（最多抽 3 次），否则事实表不可信、不开跑"""
    user = f"【任务 A：抽取事实表】\n【ep{ep:02d} 原稿】\n{RL.block_text(chunk, 'head')}\n\n{H.shots_text(chunk)}"
    last = ""
    for _ in range(3):
        d, err = H._json_block(client(facts_system(), user))
        if not d or d.get("lines") is None:
            last = err or "缺 lines"
            continue
        ok, dev, err2 = check_facts(client, d, chunk, ep)
        if ok:
            return d
        last = f"原稿自检有偏差：{json.dumps(dev, ensure_ascii=False)[:300]}{err2}"
    raise RuntimeError(f"事实表抽取 3 次都不可信：{last}")


# K-WRT-H10（总调度 11-02 03:3x 定 A）：每集服装 / 造型不是剧情事实（第一季本来按集切换造型 A / B / C；项目方第二季原话“更加暴露点的版本”）。
# 是事实：身份、名字、年龄（≥22）、发色发型、脸（林晚 = L-086 身份脸）、水晶甲等标志性固定特征、人物关系、已发生的剧情。
# 同一集里没写换装却变了衣服仍是缺陷——由代码判定 consistency#4 / #5（rubric_code）查，不归事实核对。
WARDROBE = re.compile(r"造型|服装|穿着?|衣|裙|衫|裤|鞋|靴|高跟|外套|西装|束腰|风衣|毛衣|卫衣|内衣|围裙|手套|袜|配饰|首饰|项链|手链|耳环|乳贴")
FIXED_TRAIT = re.compile(r"发色|发型|头发|蓝发|脸|身份脸|水晶甲|指甲|疤|年龄|岁|身高|名字|身份")


CHANGE_WORD = re.compile(r"改|变|不是|换成|写成|缺|未出现|没有出现|消失|去掉")


def _fixed_trait_changed(found: str) -> bool:
    """改写稿描述里，同一分句同时出现固定特征词和“改 / 变 / 缺 / 未出现”→ 固定特征被动了"""
    return any(FIXED_TRAIT.search(c) and CHANGE_WORD.search(c) for c in re.split(r"[，,；;。、]", found or ""))


def drop_wardrobe(devs: list) -> list:
    """去掉“只是服装 / 造型不同”的偏差；固定特征（发色、脸、水晶甲、年龄、身份）被改的照旧算偏差"""
    out = []
    for d in devs or []:
        txt = f"{d.get('ref', '')} {d.get('found', '')}"
        if d.get("kind") in ("setting", "event", "invented") and WARDROBE.search(txt) and not _fixed_trait_changed(d.get("found", "")):
            continue
        out.append(d)
    return out


def check_facts(client, facts: dict, chunk: str, ep: int) -> tuple[bool, list, str]:
    user = (f"【任务 B：核对改写稿】\n【事实表】\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n"
            f"【ep{ep:02d} 改写稿】\n{H.shots_text(chunk)}")
    for _ in range(2):
        d, err = H._json_block(client(facts_system(), user))
        if d is not None and "deviations" in d:
            raw_dev = d.get("deviations") or []
            dev = drop_wardrobe(raw_dev)
            return (not dev) and (bool(d.get("ok")) or len(dev) < len(raw_dev) or not raw_dev), dev, ""
    return False, [], f"事实核对回复格式不对：{err}"


QUOTE_RE = re.compile(r"[“「『\"]([^”」』\"]{2,40})[”」』\"]")
TIME_RE = re.compile(r"(?:明晚|明早|明天|后天|今晚|下周[一二三四五六日]?|周[一二三四五六日]|[0-9一二三四五六七八九十两]+点(?:半|[0-9一二三四五六七八九十]+分)?)")
SPEECH_PREFIX = ("**对白**", "**🎙")


def fact_drift_lint(orig: str, cand: str) -> list[str]:
    """HW-F1（K-WRT-H06，bug→规则：r5 实测被事实核对拦下的写法里，最常见、能机检的两类）：
    镜头描述（img / 分拍 / motion / H3 / sound，不含台词行）里出现原稿全集没有的引号文字（手机屏幕 / 纸面新内容）或新的时间说法
    （例：镜8 屏幕“预约单·明晚八点”、镜10“明晚八点，别迟到”）→ 新信息，代码直接拦，不花事实核对的钱"""
    def desc(chunk):
        seg = RL.segment(chunk)
        start = seg["shots"][0][1] if seg["shots"] else len(seg["lines"])
        return "\n".join(ln for ln in seg["lines"][start:] if not ln.startswith(SPEECH_PREFIX))
    full_o = orig
    d_c = desc(cand)
    out = []
    for q in sorted(set(QUOTE_RE.findall(d_c))):
        if q not in full_o and not re.fullmatch(r"[A-Za-z ,.'-]+", q):
            out.append(f"新引号文字“{q}”")
    for t in sorted(set(TIME_RE.findall(d_c))):
        if t not in full_o:
            out.append(f"新时间说法“{t}”")
    return out


def gate5(pre, orig, cand, ep, base_lint, wd, facts=None, fact_client=None) -> dict:
    g = H.gate(pre, orig, cand, ep, base_lint, wd)
    A = H.episode_obj(pre, orig, ep, wd)
    B = H.episode_obj(pre, cand, ep, wd) if g["checks"] and g["checks"][0]["ok"] else None
    g["checks"] = [c for c in g["checks"] if c["id"] not in ("I1", "I8")]
    if B is not None:
        sa, sb = speaker_seq(A), speaker_seq(B)
        g["checks"].insert(1, {"id": "F1", "name": "说话人逐条顺序不变（代码）", "ok": sa == sb,
                               "detail": "一致" if sa == sb else f"原 {sa} → 新 {sb}"[:500]})
        zero = (g.get("lint") or {}).get("codes", {}).get("QW-W11", 0)
        g["checks"].append({"id": "W11", "name": "QW-W11 = 0", "ok": not zero, "detail": str(zero)})
        drift = fact_drift_lint(orig, cand)
        g["checks"].append({"id": "F0", "name": "HW-F1 新屏幕文字 / 新时间信息（代码预检，K-WRT-H06）", "ok": not drift,
                            "detail": "无" if not drift else "；".join(drift)[:500]})
    g["ok"] = all(c["ok"] for c in g["checks"])
    if g["ok"] and facts is not None and fact_client is not None:
        ok, dev, err = check_facts(fact_client, facts, cand, ep)
        g["checks"].insert(2, {"id": "F2", "name": "剧情事实不变（独立事实核对调用）", "ok": ok,
                               "detail": err or ("无偏差" if ok else json.dumps(dev, ensure_ascii=False)[:800])})
        g["ok"] = ok
        g["fact_deviations"] = dev
    return g


# ------------------------------------------------------------------ 清单评审

def judge_system(adversarial: bool) -> str:
    s = H.judge_system()
    return s + ("\n\n【本次你是第三个评审：按 §五 刁钻评审的要求打分，输出格式同 §四】" if adversarial else
                "\n\n【按 §三 清单逐条核对，输出格式按 §四（不写 score）】")


def parse_checklist(raw: str) -> tuple[dict | None, str]:
    d, err = H._json_block(raw)
    if err:
        return None, err
    ch = (d or {}).get("checks") or {}
    out = {}
    for k, _ in H.DIMS:
        v = ch.get(k)
        if not isinstance(v, dict):
            return None, f"缺少 {k}"
        met = sorted({int(x) for x in v.get("met") or [] if str(x).isdigit() and 1 <= int(x) <= 5})
        unmet = [u for u in v.get("unmet") or [] if isinstance(u, dict)]
        um_ids = {int(u.get("id")) for u in unmet if str(u.get("id", "")).isdigit()}
        met = [x for x in met if x not in um_ids]                    # 同一条既 met 又 unmet → 按不满足（不放宽）
        miss = [i for i in range(1, 6) if i not in met and i not in um_ids]
        unmet += [{"id": i, "shots": [], "why": "评审没有逐条给出，按不满足计"} for i in miss]
        out[k] = {"score": max(1, len(met)), "met": met, "unmet": unmet,
                  "shots": sorted({int(s) for u in unmet for s in (u.get("shots") or []) if str(s).isdigit()}),
                  "why": "；".join(f"#{u.get('id')} {u.get('why', '')}" for u in unmet)}
    return {"scores": out, "note": str(d.get("note") or "")}, ""


def score5(judges, chunk, plan, ep, pre, calls_dir: Path, uid: str) -> dict | None:
    user = H.judge_user(ep, pre, chunk, plan)

    def one(i):
        cl = judges[i]
        for t in range(2):
            raw = cl(judge_system(i == 2), user)
            (calls_dir / f"{uid}-judge{'ABC'[i]}{t}.reply.txt").write_text(raw, encoding="utf-8")
            sc, err = parse_checklist(raw)
            if sc:
                return sc
        return None
    (calls_dir / f"{uid}-judge.req.txt").write_text(user, encoding="utf-8")
    with cf.ThreadPoolExecutor(3) as ex:
        res = list(ex.map(one, range(3)))
    ok = [r for r in res if r]
    if len(ok) < 2:
        return None
    out = {}
    for k, _ in H.DIMS:
        vs = [r["scores"][k] for r in ok]
        unm = {}
        for v in vs:
            for u in v["unmet"]:
                unm.setdefault(int(u.get("id") or 0), u)
        out[k] = {"score": round(sum(v["score"] for v in vs) / len(vs), 2), "per_judge": [v["score"] for v in vs],
                  "unmet": [unm[i] for i in sorted(unm)], "shots": sorted({s for v in vs for s in v["shots"]}),
                  "why": "；".join(f"#{i} {unm[i].get('why', '')}" for i in sorted(unm))}
    sums = [H._sum(r) for r in ok]
    return {"scores": out, "judge_sums": sums, "unstable": max(sums) - min(sums) > 3, "judges_ok": len(ok)}


# ------------------------------------------------------------------ 写作请求

def r5_writer_system() -> str:
    j = H.JUDGE_MD.read_text(encoding="utf-8")
    rubric = j[j.find("## 三、可核对清单"):j.find("## 四、")] if "## 三、可核对清单" in j else ""
    return (H.writer_system() + "\n\n========\n\n"
            "## r5 口径（项目方 11-02 00:4x，覆盖上文“台词逐字保留”）\n"
            "- 台词与 🎙 的**措辞可以为了潜台词重写**；但发生了什么、谁说的、说话人逐条顺序、谁对谁说、每条台词 / 独白传达的信息、揭示时机、"
            "人物关系、设定都不变（系统用代码 + 独立事实核对调用双重检查，有任何偏差整稿作废）。台词条数与说话人顺序不变。\n"
            "- 目标：评审清单每项 5 条全部满足（50 / 50）。清单如下，逐条对照着写：\n\n" + rubric)


def constraints5(ep_obj, base_lint, facts) -> str:
    base = H.constraints_text(ep_obj, base_lint)
    # 把“台词逐字清单”换成“说话人顺序 + 事实表”
    cut = base.find("- 台词与 🎙（逐字")
    nxt = base.find("- 原稿 lint 计数")
    head, tail = (base[:cut], base[nxt:]) if cut >= 0 and nxt > cut else (base, "")
    seq = speaker_seq(ep_obj)
    return (head + "- 说话人逐条顺序（不变；措辞可改，信息不变）：" + " → ".join(seq) + "\n"
            "- 剧情事实表（不变，系统核对）：\n" + json.dumps(facts, ensure_ascii=False, indent=1) + "\n" + tail
            + "\n- QW-W11（对身上衣服的整理动作）必须为 0。")


def user_rewrite(ep, pre, cur_chunk, ep_obj, base_lint, facts, plan, scores, note="") -> str:
    parts = ["【输入：人物卡】", H.character_cards(pre, cur_chunk), "",
             f"【当前最好版本（ep{ep:02d}）】", RL.block_text(cur_chunk, "head"), "", H.shots_text(cur_chunk), "",
             "【当前好莱坞方案】", json.dumps(plan or {}, ensure_ascii=False, indent=1), "",
             constraints5(ep_obj, base_lint, facts), ""]
    if scores:
        parts += ["【评审清单：没满足的条件（三个评审合并）】"]
        parts += [f"- {n}（{scores[k]['score']} 分）：{scores[k]['why'] or '全部满足'}" for k, n in H.DIMS if scores[k]["score"] < 5]
    parts += ["", "【本轮任务：整集改写冲 50 / 50】按模板第二步的顺序重写全集（可以改台词措辞做潜台词，可以拆 / 合镜，每镜 6 秒），"
              "逐条满足评审清单；先输出 ```json 好莱坞方案，再输出从 **镜1｜img** 起的全部镜头块。"]
    if note:
        parts += ["", f"上一次的回复没有被采用（系统校验）：{note}"]
    return "\n".join(parts)


def user_polish(ep, pre, cur_chunk, ep_obj, base_lint, facts, plan, scores, dim, note="") -> str:
    name = dict(H.DIMS)[dim]
    v = scores[dim]
    rubric = json.loads(RUBRIC_JSON.read_text(encoding="utf-8")).get(dim, [])
    parts = ["【输入：人物卡】", H.character_cards(pre, cur_chunk), "",
             f"【当前最好版本（ep{ep:02d} 全部镜头）】", H.shots_text(cur_chunk), "",
             "【当前好莱坞方案】", json.dumps(plan or {}, ensure_ascii=False, indent=1), "",
             constraints5(ep_obj, base_lint, facts), "",
             f"【专项精修：只改“{name}”这一项】清单 5 条：", *[f"  {i}. {c}" for i, c in enumerate(rubric, 1)],
             f"当前 {v['score']} 分；没满足：{v['why'] or '无'}",
             "其它维度已达到的条件一条都不能丢（改动越少越好）。",
             "输出：先 ```json（只含被改镜的 shots 条目），再只输出被改的完整镜头块（镜号不变）；需要拆 / 合镜时输出全部镜头块（镜号 1..N 连续）。"]
    if note:
        parts += ["", f"上一次的回复没有被采用（系统校验）：{note}"]
    return "\n".join(parts)


def apply_reply(raw, orig, cur_chunk, n_cur, plan_base):
    """→ (chunk, plan, changed, err)：整集（1..N 连续且全给）或部分镜（镜号不变）"""
    nums = [int(RL.SHOT_RE.match(RL._norm(ln)).group(1)) for ln in H._after_json(raw).split("\n") if RL.SHOT_RE.match(RL._norm(ln))]
    # 整集 = 镜号 1..N 连续且 N ≥ max(6, 当前镜数 − 3)（合镜最多少 3 镜）；否则按部分镜处理
    if nums and nums == list(range(1, len(nums) + 1)) and len(nums) >= max(6, n_cur - 3):
        p, blocks, err = H.parse_full(raw)
        if not blocks:
            return None, None, None, err
        plan = p if (p and p.get("logline")) else H.merge_plan(plan_base or {}, p or {})
        return H.assemble_chunk(orig, blocks), plan, "全集", ""
    p, bmap, err = H.parse_partial(raw, n_cur)
    if not bmap:
        return None, None, None, err or "没有镜头块"
    c = cur_chunk
    for k in sorted(bmap):
        c = RL.splice(c, k - 1, bmap[k])
    return c, H.merge_plan(plan_base or {}, p or {}), sorted(bmap), ""


# ------------------------------------------------------------------ 主流程

def run_episode(a) -> int:
    ep = a.episode
    od = Path(a.root) / f"ep{ep:02d}"
    od.mkdir(parents=True, exist_ok=True)
    wd, calls = od / "work", od / "calls"
    wd.mkdir(exist_ok=True)
    calls.mkdir(exist_ok=True)

    def log(m):
        H._log(od, m)
    text, rec = RC.assemble(RL, [ep], RC.episode_sources())
    (od / "input.md").write_text(text, encoding="utf-8")
    pre, chunks = RL.split_doc(text)
    orig, head_exc = H.apply_head_exceptions(chunks[0], ep)
    H.ZERO_CODES[:] = ["QW-W11"]
    writers = [make_writer(a.writer) for _ in range(BEST_OF)]
    fact_cl = make_fact_client()
    judges = [FR.Writer(temperature=0.2, max_tokens=8000), FR.Writer(temperature=0.7, max_tokens=8000), FR.Writer(temperature=0.2, max_tokens=8000)]
    budget = Budget(a.budget, writers + [fact_cl] + judges)
    W_SYS = r5_writer_system()

    def guard():
        if budget.left() < 0.3:
            raise RuntimeError(f"本集预算将尽（${budget.usage()['usd']} / ${budget.cap}）")

    ep_obj = H.episode_obj(pre, orig, ep, wd)
    base_lint = H.lint(orig, ep)
    fpath = od / "facts.json"
    if getattr(a, "facts", "") and not fpath.exists():
        fpath.write_bytes(Path(a.facts).read_bytes())          # 续跑：沿用上一段已自检通过的事实表（不重抽、不花钱）
    facts = json.loads(fpath.read_text(encoding="utf-8")) if fpath.exists() else extract_facts(fact_cl, pre, orig, ep)
    fpath.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"ep{ep:02d} 事实表：{len(facts.get('events') or [])} 事件 / {len(facts.get('lines') or [])} 台词 / {len(facts.get('reveals') or [])} 揭示")

    # r0 = r4 选中版（台词逐字，事实自然不变）
    r4 = Path(a.base) if getattr(a, "base", "") else R4_ROOT / f"ep{ep:02d}" / "final.md"   # 续跑：--base 上一段最好稿
    base_chunk = RL.split_doc(r4.read_text(encoding="utf-8"))[1][0] if r4.exists() else orig
    r4rep = R4_ROOT / f"ep{ep:02d}" / "report.json"
    plan0 = None
    if r4rep.exists():
        rr = json.loads(r4rep.read_text(encoding="utf-8"))
        plan0 = next((x.get("plan") for x in rr["rounds"] if x["round"] == rr.get("selected_round")), None)
    g0 = gate5(pre, orig, base_chunk, ep, base_lint, wd, facts, fact_cl)
    s0 = score5(judges, base_chunk, plan0, ep, pre, calls, "r0")
    (od / "r0.md").write_text(pre + base_chunk, encoding="utf-8")
    rounds = [{"round": 0, "kind": "r4 选中版（基线）" if r4.exists() else "原稿", "chunk": "r0.md", "plan": plan0, "scores": s0, "gate": g0,
               "eligible": bool(g0["ok"] and s0)}]
    log(f"r0 {H._sum(s0)}（评审 {s0 and s0['judge_sums']}）；不变量 {'过' if g0['ok'] else H.gate_note(g0)[:300]}")
    best = 0 if rounds[0]["eligible"] else None
    no_gain, plan_i = 0, 0
    try:
        for r in range(1, MAX_ROUNDS + 1):
            guard()
            cur = rounds[best] if best is not None else rounds[0]
            cur_chunk = RL.split_doc((od / cur["chunk"]).read_text(encoding="utf-8"))[1][0]
            cur_obj = H.episode_obj(pre, cur_chunk, ep, wd)
            sc_cur = cur["scores"]["scores"] if cur.get("scores") else None
            if r == 1 or sc_cur is None:
                kind, dim = "整集改写", None
            else:
                # L-098：只精修最低的 2 个维度（同分按 POLISH_ORDER 优先）
                lows = sorted([k for k, _ in H.DIMS if sc_cur[k]["score"] < 5],
                              key=lambda k: (sc_cur[k]["score"], POLISH_ORDER.index(k) if k in POLISH_ORDER else 9))[:2]
                if not lows:
                    break
                dim = lows[plan_i % len(lows)]
                plan_i += 1
                kind = f"专项精修：{dict(H.DIMS)[dim]}"
            log(f"r{r} {kind}（best-of-{BEST_OF}，写作 {a.writer}）")

            base_note = ("当前版本与剧情事实表的偏差（必须改回，否则作废）：" + json.dumps(cur["gate"].get("fact_deviations") or [], ensure_ascii=False)[:1200]
                         if cur["round"] == 0 and not cur.get("eligible") and (cur.get("gate") or {}).get("fact_deviations") else "")

            def draft(i, note=base_note):
                u = (user_rewrite(ep, pre, cur_chunk, cur_obj, base_lint, facts, cur.get("plan"), sc_cur, note) if dim is None else
                     user_polish(ep, pre, cur_chunk, cur_obj, base_lint, facts, cur.get("plan"), sc_cur, dim, note))
                (calls / f"r{r}-d{i}.req.txt").write_text(u, encoding="utf-8")
                raw = writers[i](W_SYS, u)
                (calls / f"r{r}-d{i}.reply.txt").write_text(raw, encoding="utf-8")
                return raw
            with cf.ThreadPoolExecutor(BEST_OF) as ex:
                raws = list(ex.map(draft, range(BEST_OF)))
            cands = []
            for i, raw in enumerate(raws):
                c, p, chg, err = apply_reply(raw, orig, cur_chunk, len(cur_obj.shots), cur.get("plan"))
                if c is None:
                    log(f"  d{i} 解析失败：{err[:150]}")
                    continue
                c = H.mech_align_all(pre, c, ep, wd)
                g = gate5(pre, orig, c, ep, base_lint, wd)
                fix = sorted({x for x in (g.get("worse") or {}) if x.startswith(("QW-", "H3-"))} | ({"QW-W11"} if (g.get("lint") or {}).get("codes", {}).get("QW-W11") else set())
                             | {m.group(1) for s in (g.get("lint") or {}).get("shot_block", []) for m in [re.search(r"\[((?:QW|H3)-[A-Z0-9]+)\]", s)] if m})
                fix = [x for x in fix if x not in H.EPISODE_CODES]
                force = [f"ep{ep:02d}-S{m.group(1)}=QW-W5:{x.split('：', 1)[-1][:200]}" for x in (g.get("lint") or {}).get("shot_block", [])
                         for m in [re.search(r"\[QW-W5\] 镜(\d+)", x)] if m]
                hard = [x["id"] for x in g["checks"] if not x["ok"] and x["id"] not in ("I6", "I7", "W11")]
                if not g["ok"] and not hard and (fix or force):
                    guard()
                    c = H.format_repair(pre, c, ep, fix, writers[i], wd, f"r{r}d{i}", force)
                    c = H.mech_align_all(pre, c, ep, wd)
                    g = gate5(pre, orig, c, ep, base_lint, wd)
                if g["ok"]:
                    guard()
                    g = gate5(pre, orig, c, ep, base_lint, wd, facts, fact_cl)
                log(f"  d{i}：{H._gate_brief(g)}")
                if g["ok"]:
                    cands.append((i, c, p, chg, g))
                else:
                    (od / f"r{r}_d{i}_discarded.md").write_text(pre + c, encoding="utf-8")
            scored = []
            for i, c, p, chg, g in cands:
                guard()
                sc = score5(judges, c, p, ep, pre, calls, f"r{r}-d{i}")
                if sc:
                    scored.append((H._sum(sc), i, c, p, chg, g, sc))
                    log(f"  d{i} 分数 {H._sum(sc)}（评审 {sc['judge_sums']}）")
            rec_r = {"round": r, "kind": kind, "dim": dim, "drafts": len(raws), "valid": len(cands),
                     "scored": [{"draft": i, "sum": s, "judges": sc["judge_sums"]} for s, i, *_, sc in scored]}
            # DJ-29（DISTILL tools/autopilot/policy.noise_stop）：一轮里过半稿子评审极差 > 3 → 本轮不计涨没涨，停下先修尺子
            try:
                sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
                import policy as _POL
                ns = _POL.noise_stop([sc["judge_sums"] for *_, sc in scored])
            except Exception as e:  # noqa: BLE001
                ns = {"stop": False, "error": repr(e)[:200]}
            rec_r["noise_stop"] = ns
            if ns.get("stop"):
                rec_r.update({"eligible": False, "scores": None, "discarded": True})
                rounds.append(rec_r)
                log(f"r{r} 评审噪声过大（{ns}），本轮不计入，停下先修尺子（DJ-29）")
                break
            if not scored:
                rec_r.update({"discarded": True, "eligible": False, "scores": None})
                rounds.append(rec_r)
                no_gain += 1
                log(f"r{r} 三稿都没过不变量 / 打分")
            else:
                s, i, c, p, chg, g, sc = max(scored, key=lambda t: t[0])
                name = f"r{r}.md"
                (od / name).write_text(pre + c, encoding="utf-8")
                rec_r.update({"chunk": name, "pick": i, "plan": p, "scores": sc, "gate": g, "changed": chg, "eligible": True})
                rounds.append(rec_r)
                prev = H._sum(rounds[best]["scores"]) if best is not None else -1
                log(f"r{r} 选 d{i} {s}（此前最好 {prev}）")
                if s > prev:
                    best, no_gain = len(rounds) - 1, 0
                else:
                    no_gain += 1
                if s >= TARGET_FULL:
                    log("50 / 50，停")
                    break
            if no_gain >= NO_GAIN_STOP:
                log(f"连续 {NO_GAIN_STOP} 轮总分无提升，停（L-098）")
                break
    except RuntimeError as e:
        log(f"中止：{e}")
    sel = rounds[best] if best is not None else None
    rep = {"schema": "nsfs.hollywood_r5/1", "episode": ep, "at": time.strftime("%F %T"), "sources": rec, "writer": a.writer,
           "head_exceptions": head_exc, "base_lint": base_lint, "facts": "facts.json", "rounds": rounds,
           "selected_round": sel["round"] if sel else None, "selected_sum": H._sum(sel["scores"]) if sel else None,
           "usage": budget.usage(), "zero_codes": ["QW-W11"], "dur_window": H.DUR_WINDOW}
    if sel:
        fin = RL.split_doc((od / sel["chunk"]).read_text(encoding="utf-8"))[1][0]
        (od / "final.md").write_text(pre + fin, encoding="utf-8")
        rep["lint_after"] = H.lint(fin, ep)
        rep["gaps"] = {n: sel["scores"]["scores"][k]["why"] for k, n in H.DIMS if sel["scores"]["scores"][k]["score"] < 5}
    (od / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log(f"完成：选中 r{rep['selected_round']} {rep['selected_sum']}；费用 {rep['usage']}")
    return 0


def cmd_ab(a) -> int:
    """写作模型对比：同一集同一请求，flash-high 与 v2 各出 1 稿 → 不变量 + 清单打分 + 成本 / 时长"""
    ep = a.episode
    od = Path(a.root) / f"ab_ep{ep:02d}"
    od.mkdir(parents=True, exist_ok=True)
    (od / "work").mkdir(exist_ok=True)
    text, _ = RC.assemble(RL, [ep], RC.episode_sources())
    pre, chunks = RL.split_doc(text)
    orig, _ = H.apply_head_exceptions(chunks[0], ep)
    H.ZERO_CODES[:] = ["QW-W11"]
    wd = od / "work"
    ep_obj = H.episode_obj(pre, orig, ep, wd)
    base_lint = H.lint(orig, ep)
    fact_cl = make_fact_client()
    facts = extract_facts(fact_cl, pre, orig, ep)
    (od / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    r4 = R4_ROOT / f"ep{ep:02d}" / "final.md"
    cur = RL.split_doc(r4.read_text(encoding="utf-8"))[1][0] if r4.exists() else orig
    u = user_rewrite(ep, pre, cur, H.episode_obj(pre, cur, ep, wd), base_lint, facts, None, None)
    out = {}
    for kind in a.kinds.split(","):
        w = make_writer(kind)
        judges = [FR.Writer(temperature=0.2, max_tokens=8000), FR.Writer(temperature=0.7, max_tokens=8000), FR.Writer(temperature=0.2, max_tokens=8000)]
        t = time.time()
        raw = w(r5_writer_system(), u)
        dt = round(time.time() - t, 1)
        (od / f"{kind}.reply.txt").write_text(raw, encoding="utf-8")
        c, p, chg, err = apply_reply(raw, orig, cur, len(ep_obj.shots), None)
        rec = {"seconds": dt, "finish": getattr(w, "last_finish", None), "usage": Budget(99, [w]).usage(), "parse_error": err}
        if c is not None:
            c = H.mech_align_all(pre, c, ep, wd)
            g = gate5(pre, orig, c, ep, base_lint, wd, facts, fact_cl)
            sc = score5(judges, c, p, ep, pre, od, kind)
            (od / f"{kind}.md").write_text(pre + c, encoding="utf-8")
            rec.update({"gate": H._gate_brief(g), "score": H._sum(sc) if sc else None, "judges": sc and sc["judge_sums"],
                        "per_dim": {k: v["score"] for k, v in (sc or {}).get("scores", {}).items()}})
        out[kind] = rec
        print(kind, json.dumps(rec, ensure_ascii=False)[:600], flush=True)
    (od / "ab.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


# ------------------------------------------------------------------ 修尺子（总调度 11-02 01:4x G0）
# 评审噪声 ±5 > 补丁增益 +3 → 先修尺子：温度 0；逐条 met / unmet 附原文证据，证据在镜头块里逐字找不到 = 不满足；3 个评审逐条取多数；
# 同一稿重复 5 次，总分标准差 ≤ 1 才算合格（hollywood_judge.md §六）。

def _norm_txt(s: str) -> str:
    return re.sub(r"[\s*`｜|：:，,。.、；;“”\"'（）()]+", "", s or "")


LABEL_RE = re.compile(r"镜\d+(?:[/、]镜?\d+)*[｜|]?|\*\*[^*]{1,12}\*\*[：:]?|（[^）]{0,30}）|\([^)]{0,30}\)")


def evidence_found(ev: str, body_norm: str) -> bool:
    """证据按“……”“；”“/”切成片段，去掉镜号和字段标签；至少一段 ≥6 个有效字逐字出现在镜头块里才算有证据
    （第 1 次 ruler 实测：只比证据开头 20 字时，评审惯用的“镜1｜**img**：……原文”格式全被误判无证据，总分塌到 10–11）"""
    for part in re.split(r"……|\.\.\.|；|;|/|、镜|，镜", LABEL_RE.sub("|", ev)):
        for frag in part.split("|"):
            f = _norm_txt(frag)
            if len(f) >= 6 and f[:30] in body_norm:
                return True
    return False


def judge_system_evidence() -> str:
    return H.judge_system() + "\n\n【按 §三 清单逐条判定，输出格式按 §六（每条 met 必须附镜头块原文证据）】"


def parse_evidence(raw: str, chunk: str) -> tuple[dict | None, str]:
    """→ {dim: {id: bool}}；met=true 但证据为空 / 在镜头块里逐字找不到（“全文检索无”类除外）→ 按不满足"""
    d, err = H._json_block(raw)
    if err:
        return None, err
    items = (d or {}).get("items") or {}
    body = _norm_txt(H.shots_text(chunk))
    out = {}
    for k, _ in H.DIMS:
        got = {int(x.get("id")): x for x in items.get(k) or [] if isinstance(x, dict) and str(x.get("id", "")).isdigit()}
        res = {}
        for i in range(1, 6):
            x = got.get(i) or {}
            ev = str(x.get("evidence") or "")
            ok = bool(x.get("met")) and bool(ev.strip())
            if ok and not ev.startswith("全文检索"):
                ok = evidence_found(ev, body)
            res[i] = {"met": ok, "evidence": ev[:120], "why": str(x.get("why") or "")[:200]}
        out[k] = res
    return out, ""


def score_ruler(judges, chunk, ep, pre, calls_dir: Path, uid: str) -> dict | None:
    user = H.judge_user(ep, pre, chunk, None)

    def one(i):
        for t in range(2):
            raw = judges[i](judge_system_evidence(), user)
            (calls_dir / f"{uid}-ev{i}{t}.reply.txt").write_text(raw, encoding="utf-8")
            r, _ = parse_evidence(raw, chunk)
            if r:
                return r
        return None
    with cf.ThreadPoolExecutor(len(judges)) as ex:
        res = [r for r in ex.map(one, range(len(judges))) if r]
    if len(res) < 2:
        return None
    scores = {}
    for k, _ in H.DIMS:
        met = [i for i in range(1, 6) if sum(r[k][i]["met"] for r in res) * 2 > len(res)]     # 逐条多数
        unmet = [{"id": i, "why": next((r[k][i]["why"] for r in res if not r[k][i]["met"] and r[k][i]["why"]), "")} for i in range(1, 6) if i not in met]
        scores[k] = {"score": max(1, len(met)), "met": met, "unmet": unmet, "shots": [],
                     "why": "；".join(f"#{u['id']} {u['why']}" for u in unmet)}
    return {"scores": scores, "judges_ok": len(res), "per_judge": [sum(max(1, sum(r[k][i]["met"] for i in range(1, 6))) for k, _ in H.DIMS) for r in res]}


# ---- r6：机检条目改代码（tools/script_rsi/rubric_code.py），其余条目 7 个评审逐条取多数（温度 0、证据逐字）
_rc_spec = importlib.util.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
RC6 = importlib.util.module_from_spec(_rc_spec)
_rc_spec.loader.exec_module(RC6)


def judge_items_r6() -> list[tuple[str, int, str]]:
    rub = json.loads(RUBRIC_JSON.read_text(encoding="utf-8"))
    out = []
    for d in RC6.DIMS:
        for i in RC6.LLM_ITEMS[d]:
            out.append((d, i, rub[d][i - 1]))
        for i, note in RC6.MIXED_ITEMS.get(d, {}).items():
            out.append((d, i, f"{rub[d][i - 1]}【{note}】"))
    return out


def judge_system_r6() -> str:
    items = judge_items_r6()
    return (H.judge_system() + "\n\n【r6：本次只判下面这些条目（其余条目由代码判定，不用你判）。输出格式按 §六，items 里只列这些条目的 id】\n"
            + "\n".join(f"- {d}#{i}：{t}" for d, i, t in items))


def score_r6(judges, chunk, ep, pre, calls_dir: Path, uid: str, wd: Path) -> dict | None:
    obj = H.episode_obj(pre, chunk, ep, wd)
    shots = sorted(obj.shots, key=lambda s: s.index)
    blocks = [RL.block_text(chunk, k) for k in range(len(shots))]
    codes = H.lint(chunk, ep)["codes"]
    cc = RC6.code_checks(chunk, shots, blocks, RL.block_text(chunk, "head"), codes)
    user = H.judge_user(ep, pre, chunk, None)
    items = judge_items_r6()

    def one(i):
        for t in range(2):
            raw = judges[i](judge_system_r6(), user)
            (calls_dir / f"{uid}-j{i}{t}.reply.txt").write_text(raw, encoding="utf-8")
            r, _ = parse_evidence(raw, chunk)
            if r:
                return r
        return None
    with cf.ThreadPoolExecutor(len(judges)) as ex:
        res = [r for r in ex.map(one, range(len(judges))) if r]
    if len(res) * 2 <= len(judges):
        return None
    llm = {(d, i): sum(r[d][i]["met"] for r in res) * 2 > len(res) for d, i, _ in items}
    scores = {}
    for d in RC6.DIMS:
        met, unmet = [], []
        for i in range(1, 6):
            parts = []
            if (d, i) in llm:
                parts.append(llm[(d, i)])
            if i in cc[d]:
                parts.append(cc[d][i][0])
            (met if all(parts) else unmet).append(i)
        why = "；".join(f"#{i} {'代码：' + cc[d][i][1] if i in cc[d] and not cc[d][i][0] else '评审多数判不满足'}" for i in unmet)
        scores[d] = {"score": max(1, len(met)), "met": met, "unmet": [{"id": i} for i in unmet], "shots": [], "why": why}
    judge_sums = []      # 每个评审单独算的总分（代码条目共用）→ policy.noise_stop（DJ-29）
    for r in res:
        tot = 0
        for d in RC6.DIMS:
            m = sum(1 for i in range(1, 6) if (((d, i) not in llm) or r[d][i]["met"]) and ((i not in cc[d]) or cc[d][i][0]))
            tot += max(1, m)
        judge_sums.append(tot)
    return {"scores": scores, "judges_ok": len(res), "judge_sums": judge_sums, "code": {f"{d}#{i}": v for d in RC6.DIMS for i, v in cc[d].items()},
            "llm_majority": {f"{d}#{i}": v for (d, i), v in llm.items()}}


def cmd_ruler6(a) -> int:
    import statistics
    ep = a.episode
    od = Path(a.root) / f"ruler6_ep{ep:02d}"
    (od / "calls").mkdir(parents=True, exist_ok=True)
    (od / "work").mkdir(exist_ok=True)
    judges = [FR.Writer(temperature=0.0, max_tokens=8000) for _ in range(a.judges)]
    budget = Budget(a.budget, judges)
    out = {"share": RC6.share(), "files": {}}
    for f in a.files.split(","):
        pre, ch = RL.split_doc(Path(f).read_text(encoding="utf-8"))
        sums, code_sum = [], None
        for n in range(a.n):
            if budget.left() < 0.05:
                H._log(od, f"预算将尽 ${budget.usage()['usd']}，停")
                break
            sc = score_r6(judges, ch[0], ep, pre, od / "calls", f"{Path(f).parent.name}-{Path(f).stem}-rep{n}", od / "work")
            s = H._sum(sc) if sc else None
            sums.append(s)
            code_sum = sum(1 for v in (sc or {}).get("code", {}).values() if v[0])
            H._log(od, f"{f} 第 {n + 1} 次：{s}（代码满足 {code_sum}/{sum(len(v) for v in RC6.CODE_ITEMS.values()) + 3}）；"
                       f"{json.dumps({k: v['score'] for k, v in (sc or {}).get('scores', {}).items()})}")
            if sc and n == 0:
                (od / f"{Path(f).parent.name}-{Path(f).stem}.detail.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
        vals = [x for x in sums if x is not None]
        sd = statistics.pstdev(vals) if len(vals) > 1 else None
        out["files"][f] = {"sums": sums, "mean": (sum(vals) / len(vals)) if vals else None, "stdev": sd, "pass": sd is not None and sd <= 1.0}
        H._log(od, f"{f}：{sums} 均值 {out['files'][f]['mean']} 标准差 {sd} → {'合格' if sd is not None and sd <= 1 else '不合格'}")
    out["usage"] = budget.usage()
    (od / "ruler6.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    H._log(od, f"费用 {out['usage']}；机检占比 {out['share']}")
    return 0


def cmd_ruler(a) -> int:
    """同一稿重复打 N 次 → 标准差；≤ 1 合格"""
    import statistics
    ep = a.episode
    od = Path(a.root) / f"ruler_ep{ep:02d}_j{a.judges}"
    (od / "calls").mkdir(parents=True, exist_ok=True)
    pre, ch = RL.split_doc(Path(a.file).read_text(encoding="utf-8"))
    chunk = ch[0]
    judges = [FR.Writer(temperature=0.0, max_tokens=12000) for _ in range(a.judges)]
    budget = Budget(a.budget, judges)
    sums = []
    for n in range(a.n):
        if budget.left() < 0.1:
            break
        sc = score_ruler(judges, chunk, ep, pre, od / "calls", f"rep{n}")
        s = H._sum(sc) if sc else None
        sums.append(s)
        H._log(od, f"第 {n + 1} 次：{s}（各评审 {sc and sc['per_judge']}）；{json.dumps({k: v['score'] for k, v in (sc or {}).get('scores', {}).items()})}")
    vals = [x for x in sums if x is not None]
    sd = statistics.pstdev(vals) if len(vals) > 1 else None
    rep = {"file": a.file, "sums": sums, "stdev": sd, "pass": sd is not None and sd <= 1.0, "usage": budget.usage()}
    (od / "ruler.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    H._log(od, f"尺子：{sums} 标准差 {sd}；{'合格' if rep['pass'] else '不合格'}；费用 {rep['usage']}")
    return 0


# ------------------------------------------------------------------ 逐行补丁模式（总调度 11-02 01:2x G0）
# 原因（实测）：整稿重写过了事实核对后普遍 40–42；写作方往高分写就加新情节（invented）被拦，且整稿核对又贵又噪。
# 改法：事实表原样作硬约束，只允许改表达（台词措辞 / 潜台词 / 节奏 / 镜头描述）；写作方只回“行号 + 新文本”；
# 事实核对只核改动的行（hollywood_facts.md 任务 C）；每次只修清单里没满足的 1–2 条，修完立刻局部核对再整集打分。

PATCH_RULE = ("只允许改表达：台词措辞、潜台词、节奏、镜头描述（img / 分拍 / motion / H3 的写法）；"
              "不得新增冲突、决定、身体接触、信息、物件；不得改说话人、台词条数、镜数、时长、场景 id、人物行、衔接、集头。")


def numbered_lines(chunk: str) -> list[tuple[int, int, str]]:
    """镜头区每个非空行 → (行号, 在 chunk 里的下标, 原文)。集头不编号（集头不许改）"""
    seg = RL.segment(chunk)
    start = seg["shots"][0][1] if seg["shots"] else len(seg["lines"])
    out, n = [], 0
    for i in range(start, len(seg["lines"])):
        t = seg["lines"][i].rstrip("\n")
        if t.strip() and t.strip() != "---":
            n += 1
            out.append((n, i, t))
    return out


def apply_patches(chunk: str, patches: list, nl) -> tuple[str | None, list, str]:
    by = {n: (i, t) for n, i, t in nl}
    lines = RL.segment(chunk)["lines"]
    changed = []
    if not patches or len(patches) > 14:
        return None, [], f"补丁条数 {len(patches or [])}（应为 1–14）"
    for pch in patches:
        try:
            n, new = int(pch.get("line")), str(pch.get("new"))
        except (TypeError, ValueError):
            return None, [], f"补丁格式不对：{pch}"
        if n not in by:
            return None, [], f"行号 {n} 不存在"
        if "\n" in new or not new.strip():
            return None, [], f"行 {n} 的新文本不能为空或含换行"
        i, old = by[n]
        if old.startswith("**镜") and new.split("｜")[0] != old.split("｜")[0]:
            return None, [], f"行 {n} 是镜头标题行，镜号不能改"
        lines[i] = new + "\n"
        changed.append({"line": n, "old": old, "new": new})
    return "".join(lines), changed, ""


def shot_of_line(chunk: str, idx: int) -> int | None:
    for k, a_, b_, _ in [(s[0], s[1], s[2], s[3]) for s in RL.segment(chunk)["shots"]]:
        if a_ <= idx < b_ + 1:
            return k
    return None


def check_patch_facts(client, facts, chunk, changed) -> tuple[bool, list, str]:
    nl = {n: i for n, i, _ in numbered_lines(chunk)}
    items = [f"- 镜{shot_of_line(chunk, nl.get(c['line'], 0)) or '?'} 行{c['line']}：原文：{c['old']}\n  新文：{c['new']}" for c in changed]
    user = (f"【任务 C：核对补丁】\n【事实表】\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n【改动的行】\n" + "\n".join(items))
    for _ in range(2):
        d, err = H._json_block(client(facts_system(), user))
        if d is not None and "deviations" in d:
            raw_dev = d.get("deviations") or []
            dev = drop_wardrobe(raw_dev)
            return (not dev) and (bool(d.get("ok")) or len(dev) < len(raw_dev) or not raw_dev), dev, ""
    return False, [], f"补丁核对回复格式不对：{err}"


def pick_targets(scores: dict, used: set, k: int = 2) -> list[tuple[str, dict]]:
    """清单里还没满足的具体条目：按维度分数从低到高，取前 k 条没试过的（同维度多条先取编号小的）"""
    out = []
    for dim in sorted((d for d, _ in H.DIMS), key=lambda d: scores[d]["score"]):
        for u in scores[dim].get("unmet") or []:
            key = f"{dim}#{u.get('id')}"
            if key not in used and len(out) < k:
                out.append((dim, u))
    return out


def user_patch(ep, pre, chunk, facts, targets, note="") -> str:
    rubric = json.loads(RUBRIC_JSON.read_text(encoding="utf-8"))
    nl = numbered_lines(chunk)
    tg = [f"- {dict(H.DIMS)[d]} 第 {u.get('id')} 条：{rubric[d][int(u.get('id')) - 1] if str(u.get('id')).isdigit() and 1 <= int(u.get('id')) <= 5 else ''}\n"
          f"  评审说没满足：镜 {u.get('shots') or '未指出'}；{u.get('why', '')}" for d, u in targets]
    parts = ["【剧情事实表（硬约束，原样遵守）】", json.dumps(facts, ensure_ascii=False, indent=1), "",
             f"【改写边界】{PATCH_RULE}", "",
             f"【ep{ep:02d} 集头（只读，不许改）】", RL.block_text(chunk, "head"), "",
             "【镜头区，逐行编号（L 行号｜原文）】", *[f"L{n}｜{t}" for n, _, t in nl], "",
             "【本次只修这 1–2 条清单条目】", *tg, "",
             "只输出一个 ```json：{\"patches\": [{\"line\": 行号, \"new\": \"这一行的完整新文本\"}]}；只改为满足上面条目所必需的行（1–14 行），"
             "每行整行替换、保留原来的字段标签（如 **分拍**：、**对白**：、H3 里的 At 00:0X 时间码）；台词说话人和条数不变。"]
    if note:
        parts += ["", f"上一次的补丁没有被采用：{note}"]
    return "\n".join(parts)


def cmd_patch(a) -> int:
    ep = a.episode
    od = Path(a.root) / f"ep{ep:02d}_{a.tag}"
    od.mkdir(parents=True, exist_ok=True)
    wd, calls = od / "work", od / "calls"
    wd.mkdir(exist_ok=True)
    calls.mkdir(exist_ok=True)

    def log(m):
        H._log(od, m)
    text, rec = RC.assemble(RL, [ep], RC.episode_sources())
    pre, chunks = RL.split_doc(text)
    orig, _ = H.apply_head_exceptions(chunks[0], ep)
    H.ZERO_CODES[:] = ["QW-W11"]
    facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
    (od / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    base_lint = H.lint(orig, ep)
    writer = make_writer(a.writer, temperature=0.5)
    fact_cl = make_fact_client()
    judges = [FR.Writer(temperature=0.2, max_tokens=8000), FR.Writer(temperature=0.7, max_tokens=8000), FR.Writer(temperature=0.2, max_tokens=8000)]
    budget = Budget(a.budget, [writer, fact_cl] + judges)
    cur = RL.split_doc(Path(a.base).read_text(encoding="utf-8"))[1][0]
    g0 = gate5(pre, orig, cur, ep, base_lint, wd)
    sc = score5(judges, cur, None, ep, pre, calls, "p0")
    (od / "p0.md").write_text(pre + cur, encoding="utf-8")
    hist = [{"step": 0, "sum": H._sum(sc), "judges": sc and sc["judge_sums"], "gate": H._gate_brief(g0)}]
    log(f"p0 基线 {H._sum(sc)}（{sc and sc['judge_sums']}）；代码不变量 {H._gate_brief(g0)}；补丁模式，写作 {a.writer}，预算 ${a.budget}")
    best_sum, used, step, rnd_gain, attempts_in_round = H._sum(sc), set(), 0, False, 0
    try:
        while True:
            if budget.left() < 0.15:
                log(f"预算将尽 ${budget.usage()['usd']}，收尾")
                break
            targets = pick_targets(sc["scores"], used)
            if not targets:
                log("没有可修的清单条目了")
                break
            step += 1
            used |= {f"{d}#{u.get('id')}" for d, u in targets}
            note, ok_c = "", None
            for att in range(2):
                u_ = user_patch(ep, pre, cur, facts, targets, note)
                (calls / f"p{step}-a{att}.req.txt").write_text(u_, encoding="utf-8")
                raw = writer(r5_writer_system(), u_)
                (calls / f"p{step}-a{att}.reply.txt").write_text(raw, encoding="utf-8")
                d, err = H._json_block(raw)
                c, changed, err2 = apply_patches(cur, (d or {}).get("patches") or [], numbered_lines(cur)) if d else (None, [], err)
                if c is None:
                    note = err2 or err
                    continue
                c = H.mech_align_all(pre, c, ep, wd)
                g = gate5(pre, orig, c, ep, base_lint, wd)
                if not g["ok"]:
                    note = H.gate_note(g)
                    continue
                okf, dev, errf = check_patch_facts(fact_cl, facts, cur, changed)
                if not okf:
                    note = errf or ("改动触碰了剧情事实：" + json.dumps(dev, ensure_ascii=False)[:800])
                    continue
                ok_c = (c, changed)
                break
            tg_txt = "、".join(f"{d}#{u.get('id')}" for d, u in targets)
            if not ok_c:
                hist.append({"step": step, "targets": tg_txt, "rejected": note[:300]})
                log(f"p{step} 目标 {tg_txt}：补丁没过核对（{note[:160]}）")
            else:
                c, changed = ok_c
                sc2 = score5(judges, c, None, ep, pre, calls, f"p{step}")
                s2 = H._sum(sc2) if sc2 else -1
                hist.append({"step": step, "targets": tg_txt, "lines": len(changed), "sum": s2, "judges": sc2 and sc2["judge_sums"],
                             "accepted": s2 > best_sum})
                log(f"p{step} 目标 {tg_txt}：改 {len(changed)} 行 → {s2}（此前 {best_sum}）{'采用' if s2 > best_sum else '不采用'}")
                if s2 > best_sum:
                    cur, sc, best_sum, rnd_gain = c, sc2, s2, True
                    (od / f"p{step}.md").write_text(pre + cur, encoding="utf-8")
                    (od / "best.md").write_text(pre + cur, encoding="utf-8")
            attempts_in_round += 1
            if best_sum >= TARGET_FULL:
                break
            if attempts_in_round >= 3:          # 一“轮” = 3 次补丁尝试；L-098 连续 1 轮不涨即停
                if not rnd_gain:
                    log("本轮 3 次补丁都没涨分，停（L-098）")
                    break
                attempts_in_round, rnd_gain = 0, False
    except RuntimeError as e:
        log(f"中止：{e}")
    if not (od / "best.md").exists():
        (od / "best.md").write_text(pre + cur, encoding="utf-8")
    gf = gate5(pre, orig, cur, ep, base_lint, wd, facts, fact_cl)           # 收尾：选中稿再做一次整集事实核对
    rep = {"schema": "nsfs.hollywood_r5_patch/1", "episode": ep, "base": a.base, "writer": a.writer, "history": hist,
           "best_sum": best_sum, "final_gate": gf, "usage": budget.usage(),
           "gaps": {n: sc["scores"][k]["why"] for k, n in H.DIMS if sc["scores"][k]["score"] < 5}, "scores": sc}
    (od / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log(f"完成：最好 {best_sum}；整集核对 {H._gate_brief(gf)}；费用 {rep['usage']}")
    return 0


def cmd_jobs_dry(a) -> int:
    """导入前 dry 比对（总调度 01:4x 第 3 条）：候选稿 vs 现行导入稿（data/import/script_v2.json）这一集——镜头集合、
    每镜首帧作业提示词（image_jobs.frame_prompt，与 rebuild_first_frame_jobs 同一编译入口）、台词 / 🎙 是否变。
    只读，不写 first_frame_jobs.json。结论：jobs_unchanged = 镜号集合相同且每镜首帧提示词逐字相同"""
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import image_jobs as IJ
    from ns_agent.importer.script_md import import_script
    ep = a.episode
    si = IJ.load_import()
    cur = next(e for e in si.episodes if e.number == ep)
    cand = next(e for e in import_script(Path(a.file)).episodes if e.number == ep)
    g = si.globals
    proj = "series10_v1"
    cs, ns = {s.id: s for s in cur.shots}, {s.id: s for s in cand.shots}
    rows = []
    for sid in sorted(set(cs) | set(ns), key=lambda x: int(x.split("-S")[1])):
        a_, b_ = cs.get(sid), ns.get(sid)
        if not a_ or not b_:
            rows.append({"shot": sid, "status": "镜头新增" if b_ else "镜头删除"})
            continue
        pa, _ = IJ.frame_prompt(cur, a_, g, [], proj)
        pb, _ = IJ.frame_prompt(cand, b_, g, [], proj)
        da = [f"{d.speaker}|{d.text}" for d in a_.dialogue] + ([f"🎙|{a_.voiceover.text}"] if a_.voiceover and a_.voiceover.text else [])
        db = [f"{d.speaker}|{d.text}" for d in b_.dialogue] + ([f"🎙|{b_.voiceover.text}"] if b_.voiceover and b_.voiceover.text else [])
        rows.append({"shot": sid, "frame_prompt_same": pa == pb, "speech_changed": da != db, "duration": [a_.duration, b_.duration],
                     "h3_changed": (a_.h3_prompt or "") != (b_.h3_prompt or "")})
    unchanged = all(r.get("frame_prompt_same") for r in rows) and all("status" not in r for r in rows)
    rep = {"episode": ep, "file": a.file, "jobs_unchanged": unchanged, "shots_now": len(cs), "shots_cand": len(ns),
           "frame_changed": [r["shot"] for r in rows if r.get("frame_prompt_same") is False or "status" in r],
           "speech_changed": [r["shot"] for r in rows if r.get("speech_changed")], "rows": rows,
           "jobs_vs_import_now": IJ.jobs_vs_import()}
    out = Path(a.out) if a.out else Path(a.file).with_suffix(".jobs_dry.json")
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "rows"}, ensure_ascii=False, default=str)[:1500])
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--episode", type=int, required=True)
    r.add_argument("--root", required=True)
    r.add_argument("--writer", default="flash-high", choices=["flash-high", "flash-medium", "flash-low", "v2", "flash"])
    r.add_argument("--budget", type=float, default=EP_CAP_USD)
    r.add_argument("--base", default="", help="续跑：以这份稿为 r0（如上一段的 rN.md）")
    r.add_argument("--facts", default="", help="续跑：沿用这份 facts.json")
    b = sub.add_parser("ab")
    b.add_argument("--episode", type=int, required=True)
    b.add_argument("--root", required=True)
    b.add_argument("--kinds", default="flash-high,v2")
    pt = sub.add_parser("patch", help="逐行补丁模式（总调度 01:2x G0）：只修清单里没满足的 1–2 条，只核改动的行")
    pt.add_argument("--episode", type=int, required=True)
    pt.add_argument("--root", required=True)
    pt.add_argument("--base", required=True)
    pt.add_argument("--facts", required=True)
    pt.add_argument("--writer", default="flash-high", choices=["flash-high", "flash-medium", "flash-low", "flash"])
    pt.add_argument("--budget", type=float, default=1.0)
    pt.add_argument("--tag", default="patch")
    ru = sub.add_parser("ruler", help="修尺子：同一稿重复打 N 次看标准差（温度 0、逐条证据、3 评审多数）")
    ru.add_argument("--episode", type=int, required=True)
    ru.add_argument("--root", required=True)
    ru.add_argument("--file", required=True)
    ru.add_argument("--n", type=int, default=5)
    ru.add_argument("--budget", type=float, default=1.0)
    ru.add_argument("--judges", type=int, default=3, help="每次几个评审逐条取多数")
    r6 = sub.add_parser("ruler6", help="r6 尺子：机检条目代码判 + 7 评审逐条多数；同稿重复 N 次看标准差")
    r6.add_argument("--episode", type=int, required=True)
    r6.add_argument("--root", required=True)
    r6.add_argument("--files", required=True, help="逗号分隔，可同时打现行稿与候选稿")
    r6.add_argument("--n", type=int, default=5)
    r6.add_argument("--judges", type=int, default=7)
    r6.add_argument("--budget", type=float, default=1.0)
    jd = sub.add_parser("jobs-dry", help="导入前 dry 比对首帧作业（只读）")
    jd.add_argument("--episode", type=int, required=True)
    jd.add_argument("--file", required=True)
    jd.add_argument("--out", default="")
    a = ap.parse_args(argv)
    return {"run": run_episode, "ab": cmd_ab, "patch": cmd_patch, "ruler": cmd_ruler, "jobs-dry": cmd_jobs_dry, "ruler6": cmd_ruler6}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
