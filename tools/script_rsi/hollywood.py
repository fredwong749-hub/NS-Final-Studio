"""HOLLYWOOD（项目方 11-01 ~20:00 模板，总调度 fredw-2b 派）：“好莱坞编剧 + 短剧提示词工程师”模板接进写作链路，单集试点。

模板原文：config/prompts/hollywood_writer.md（写作方）、hollywood_judge.md（独立评审，量表 10 项）；Pika 能力边界参考
config/prompts/hollywood_pika_reference.md（VIDEO-RCA 实测，评审与写作方都拿到）。规则 K-WRT-H01–H03（knowledge/rules/writer_hollywood.yaml）。

Claude 只写系统：拼输入、调网关、解析格式、核对不变量、出审片页。第二步（重写）和第三步（打分）全部由写作网关完成
（llm_config.resolve("script_write")，写作 / 评审两个独立调用）；系统不改写、不评价内容。

复用（G0）：拼输入 = repair_chain.assemble（现行来源 + sha 校验）；写作客户端 = full_repair.Writer（计调用 / token）；
对白不变量 = full_repair.dialogue_seq；格式返修 = qwen_repair_loop.main（--only-codes 变多的码）；H3 对齐句 = qwen_repair_loop.mech_align；
镜数上限 = script_md.shot_cap（D-SCR-06）；lint / P4 = pipeline/p4_adapter.check_p4（导入关口同款 + Spec）。

不变量（不满足 → 这一轮作废）：台词 / 🎙 逐字同序；集头（剧情、人物卡、造型）逐字；场景 id、出场人物不新增；镜数 6..上限；
集时长 ∈ 模板 60–120 ∩ 现行 QW-E3 50–75；lint 每个码不比原稿多；P4 阻断（人物卡行冻结项除外）= 0。

    .venv/Scripts/python.exe tools/script_rsi/hollywood.py run --episode 1 --out-dir data/review_pages/hollywood_ep01/run          # 真跑（花 API 费用）
    .venv/Scripts/python.exe tools/script_rsi/hollywood.py run --episode 1 --out-dir <dir> --stub                                 # 桩：只验链路
    .venv/Scripts/python.exe tools/script_rsi/hollywood.py page --out-dir data/review_pages/hollywood_ep01/run --html data/review_pages/hollywood_ep01/index.html
只出审片页，不导入（导入由项目方决定）。
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools" / "pipeline", ROOT / "packages" / "schema", ROOT / "services" / "agent", ROOT / "services" / "api",
           ROOT / "services" / "recipes"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PROMPTS = ROOT / "config" / "prompts"
WRITER_MD, JUDGE_MD, PIKA_MD = PROMPTS / "hollywood_writer.md", PROMPTS / "hollywood_judge.md", PROMPTS / "hollywood_pika_reference.md"
AUDIT_MD = ROOT / "data" / "review_pages" / "hollywood_ep01" / "config_audit.md"

DIMS = [("hook5s", "5 秒钩子"), ("conflict", "冲突是否成立"), ("turns", "转折密度"), ("gos", "人物目标 / 阻碍 / 赌注"),
        ("show", "show 而非 tell"), ("specificity", "画面 specificity"), ("pika", "运动符合 Pika / LoRA 能力"),
        ("consistency", "人物一致性"), ("subtext", "台词潜台词"), ("endhook", "结尾钩子")]
PASS_SCORE = 4                                    # 模板第三步：单项及格线（低于 4 分的项不允许出现在导入版里）
# r3（项目方 11-01 22:1x 原话“rsi HOLLYWOOD 达到95分,继续迭代”，总调度转）：取代模板“最多 3 轮”。
# 百分制 ≥95 = 满分 50 里 ≥47.5 → 整数总分 ≥48，且没有 <4 的项；最多 8 轮；连续 2 轮总分无提升即停；没到 95 的集不导入
TARGET_SUM, MAX_ROUNDS, FIX_BELOW = 47.5, 8, 5      # 两个评审逐项平均后比较        # 返修轮发给写作方的是 <5 分的项（要到 95 多数项须 5 分）
TEMPLATE_S = (60, 120)                            # 模板：每集 60–120 秒
# r2（总调度 11-01 21:4x）：项目方选“改成 60–120 秒”（D-SCR-08，RSI r7 同步 QW-E3）→ I5 = 60–120。
# ⤴ r1 用的是模板 ∩ 旧 QW-E3 50–75 = 60–75
DUR_WINDOW = TEMPLATE_S
SHOT_S = 6                                        # 一镜 6 秒（D-SCR-06 ⌈秒数 ÷ 6⌉ 同一常数）
MIN_SHOTS = DUR_WINDOW[0] // SHOT_S               # 60 秒 → 至少 10 镜
# 人物卡例外（项目方 11-01 21:4x 选“允许，改成铅笔裙 (Recommended)”）：集头造型行里逐字替换，系统照项目方原话改，写作方不碰集头
# 人物卡不变量（I2 集头逐字）的唯一例外：项目方 11-01 21:4x AskUserQuestion 选“允许，改成铅笔裙 (Recommended)”（L-092 / D-SCR-08b）——
# 只限 ep01 林晚造型行“深灰西装裙”→“深灰铅笔裙”这一处字面（EN 本来就是 dark grey pencil skirt），造型本身不变；新增例外须项目方原话（RSI r7 登记）
HEAD_EXCEPTIONS: dict[int, list[tuple[str, str, str]]] = {1: [("**造型｜林晚**", "深灰西装裙", "深灰铅笔裙")]}
ZERO_CODES: list[str] = []
# r4（项目方 11-02 AskUserQuestion 选“允许改台词，出审片页 (Recommended)”）：评审扣分项（钩子 / 转折 / 潜台词）多半要动台词，
# I1 冻结下 10 集卡在 36–42.5/50。--free-dialogue：I1 只记录不作废；说话人仍受 I3（不新增人物）约束；一律不导入，出审片页由项目方审
FREE_DIALOGUE = [False]                        # 要求降到 0 的新 lint（K-WRT-702 = QW-W11，RSI r7 定号；由 --zero-codes 传入）
COST_CAP_USD = 1.0                                # 试点预算（总调度：约 1 美元）
EPISODE_CODES = {"QW-E2", "QW-E3", "QW-E6b"}      # 集级 / 集头码：逐镜返修修不了
FROZEN_MARK = "造型｜"                             # 集头人物卡 / 造型行上的 P4 阻断：人物卡不变量冻结，单列给总调度


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


FR = _load("full_repair", "tools/script_rsi/full_repair.py")
RC = FR._load("repair_chain", "tools/pipeline/repair_chain.py")
RL = RC._load_rl()


def _log(od: Path, msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(od / "log.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------ 拼输入（只拼，不写内容）

def episode_obj(pre: str, chunk: str, ep: int, wd: Path):
    return RL.Checker(pre, wd, []).run(chunk, ep)["obj"]


def shots_text(chunk: str) -> str:
    seg = RL.segment(chunk)
    return "\n\n".join(RL.block_text(chunk, k) for k in range(len(seg["shots"])))


def character_cards(pre: str, chunk: str) -> str:
    """人物卡 = 前言角色锁里本集出场人物那几行 + 全剧人物表对应行 + 集头 造型｜ 行（全部原文照抄）"""
    head = RL.block_text(chunk, "head")
    names = []
    m = re.search(r"\*\*出场人物\*\*：(.+)", head)
    if m:
        names = [x.strip() for x in re.split(r"[、，,]", m.group(1)) if x.strip()]
    out = ["角色锁（全剧统一前缀，原文）："]
    out += [ln.strip() for ln in pre.splitlines() if any(ln.strip().startswith(f"【{n}】") for n in names)]
    out += ["", "全剧人物表（原文）："]
    out += [ln.strip() for ln in pre.splitlines() if ln.startswith("| ") and any(ln.startswith(f"| {n} |") for n in names)]
    out += ["", "本集造型（集头原文）："]
    out += [ln.strip() for ln in head.splitlines() if ln.startswith("**造型｜")]
    out += ["", "身高 / 关系：剧本里未提供"]
    return "\n".join(out)


def consistency_lock(pre: str, chunk: str, names: list[str]) -> str:
    """模板第二步 4：“图片提示词另附人物一致性描述，按人物卡逐字锁定外貌和服装”——系统逐字拷人物卡，不写内容"""
    head = RL.block_text(chunk, "head")
    out = []
    for n in names:
        lock = next((ln.strip() for ln in pre.splitlines() if ln.strip().startswith(f"【{n}】")), "")
        look = next((ln.strip() for ln in head.splitlines() if ln.startswith(f"**造型｜{n}**")), "")
        look = re.sub(r"^\*\*造型｜[^*]+\*\*：", "", look)
        out.append(f"{lock or '【' + n + '】未提供'}｜造型：{look or '未提供'}")
    return "\n".join(out)


def pika_reference() -> str:
    return PIKA_MD.read_text(encoding="utf-8") if PIKA_MD.exists() else "（Pika 能力边界参考：未提供）"


def audit_text() -> str:
    return AUDIT_MD.read_text(encoding="utf-8") if AUDIT_MD.exists() else "（config 盘点表：未提供）"


def writer_system() -> str:
    return (WRITER_MD.read_text(encoding="utf-8") + "\n\n========\n\n" + pika_reference()
            + "\n\n========\n\n" + FR._system_text())


def judge_system() -> str:
    return JUDGE_MD.read_text(encoding="utf-8") + "\n\n========\n\n" + pika_reference()


def duration_plan(ep_obj) -> dict:
    """纯算术（r2，总调度：6 秒一镜，镜数上限按 D-SCR-06）：N = max(⌈60÷6⌉, 原镜数, ⌈原总秒数÷6⌉, 说话轮次 + 独白)，
    封顶 ⌊120÷6⌋；每镜 6 秒，总 6N 秒 → shot_cap = max(8, 轮次 + 独白, N) ≥ N 恒成立。
    台词需要 >6 秒的（QW-T1 上限 > 6）单列：那条台词所在的镜用它的上限秒数，总秒数相应加上（仍 ≤120）。
    run1 实测（11-01 20:09）：只给区间时写作方 4 次都没凑出，所以系统直接给镜数和每镜秒数"""
    WL = RL.V.WL
    tot0 = sum(int(s.duration or 0) for s in ep_obj.shots)
    n = max(MIN_SHOTS, len(ep_obj.shots), -(-tot0 // SHOT_S), _turns_mono(ep_obj))
    n = min(n, DUR_WINDOW[1] // SHOT_S)
    long_ = [(s.index, FR.speech_limit(WL, s)) for s in ep_obj.shots if FR.speech_limit(WL, s) > SHOT_S]
    extra = sum(l - SHOT_S for _, l in long_)
    while n > MIN_SHOTS and n * SHOT_S + extra > DUR_WINDOW[1]:
        n -= 1
    return {"n": n, "total": n * SHOT_S + extra, "durs": [SHOT_S] * n,
            "long": [{"orig_shot": i, "seconds": l} for i, l in long_]}


def rule_text(code: str) -> str:
    r = RL.V.RULES.get(code)
    return f"{code}：{r[1]}" if r else code


def constraints_text(ep_obj, base_lint: dict) -> str:
    turns_mono = _turns_mono(ep_obj)
    seq = FR.dialogue_seq(ep_obj)
    lo, hi = DUR_WINDOW
    caps = "、".join(f"{s} 秒→{max(8, turns_mono, -(-s // 6))} 镜" for s in (lo, 90, hi))
    dp = duration_plan(ep_obj)
    lines = ["【系统硬校验的数字（不满足这一轮整轮作废）】",
             f"- **系统算好的镜数与时长（照这个写，最省事）**：恰好 {dp['n']} 镜，全集 {dp['total']} 秒，每镜 **时长** 依次 {dp['durs']} 秒"
             "（有台词 / 🎙 的镜放在哪一镜都行，但每镜秒数照这张表）"
             + (("；以下原稿镜的台词需要更长，放这些台词的镜改用括号里的秒数：" + "、".join(f"原镜{x['orig_shot']}（{x['seconds']} 秒）" for x in dp["long"]))
                if dp.get("long") else "") + "。",
             f"- 全集 **时长** 之和：{lo}–{hi} 秒（项目方 11-01 定：每集 60–120 秒，D-SCR-08）。原稿 {sum(int(s.duration or 0) for s in ep_obj.shots)} 秒。",
             f"- 镜数：6 ≤ 镜数 ≤ max(8, 说话轮次 + 独白段数 = {turns_mono}, ⌈全集秒数 ÷ 6⌉)（D-SCR-06）：{caps}。原稿 {len(ep_obj.shots)} 镜。",
             "- 单镜时长（QW-T1）：没有台词 / 独白的镜 ≤6 秒；有台词 / 🎙 的镜 ≤ max(6, 台词字数 ÷ 4.5 + 1.5) 秒；每镜 4–15 秒整数。",
             ("- 台词与 🎙：**本轮项目方已放开台词冻结**（接入说明第 1 条本轮不适用）——可以按评审意见改写、增删台词 / 🎙，"
              "说话人只能是本集已有人物；台词改了配音要重做，只在明显提分（钩子 / 转折 / 潜台词 / 目标赌注）时改。原稿台词（参考）："
              if FREE_DIALOGUE[0] else "- 台词与 🎙（逐字、同说话人、全集同顺序，一条不增不减；可以放进不同的镜，但顺序不变）：")]
    lines += [f"  {i + 1}. {x}" for i, x in enumerate(seq)]
    lines += ["- 原稿 lint 计数（每个码都不能变多；能少更好）：" + (json.dumps(base_lint["codes"], ensure_ascii=False) or "{}"),
              "  上次容易变多的码（规则原文）：" + "；".join(rule_text(c) for c in ("QW-A5", "QW-K3", "QW-LK2", "QW-W5", "H3-X1", "QW-CH4")),
              *(["- 必须降到 0 的新 lint（K-WRT-702，VIDEO-RCA 实测 Pika 外套消失的根因）：" + "；".join(rule_text(c) for c in ZERO_CODES)
                 + "；原稿命中：" + ("；".join(base_lint.get("zero_detail") or []) or "无")] if ZERO_CODES else []),
              "- 原稿 P4 阻断（镜头里的要改掉；集头人物卡行上的由系统单列，不用你改）："]
    lines += [f"  · {x}" for x in base_lint["shot_block"]] or ["  · 无"]
    return "\n".join(lines)


def _turns_mono(ep_obj) -> int:
    turns, last = 0, None
    for s in ep_obj.shots:
        for d in s.dialogue:
            sp = (d.speaker_note or "").strip()
            if sp != last:
                turns, last = turns + 1, sp
    return turns + sum(1 for s in ep_obj.shots if s.voiceover and s.voiceover.text)


def writer_user_full(ep: int, pre: str, chunk: str, ep_obj, base_lint: dict, note: str = "") -> str:
    parts = ["【输入 1：config 盘点表（第一步，系统产出）】", audit_text(), "",
             "【输入 2：本集分集大纲（集头原文）】", RL.block_text(chunk, "head"), "",
             "【输入 3：人物卡】", character_cards(pre, chunk), "",
             f"【输入 4：现有提示词（ep{ep:02d} 原稿全部镜头，生硬的版本）】", shots_text(chunk), "",
             constraints_text(ep_obj, base_lint), "",
             "【本轮任务：第二步，整集重写】按模板第二步的顺序（logline → 节拍 → 每场目标 / 阻碍 / 赌注 → 镜头提示词）重写全集；"
             "按“本系统接入说明”的第一轮输出格式输出：先 ```json 好莱坞方案，再从 **镜1｜img** 起的全部镜头块。"]
    if note:
        parts += ["", f"上一次的回复没有被采用（系统校验）：{note}"]
    return "\n".join(parts)


def writer_user_fix(ep: int, pre: str, chunk: str, ep_obj, base_lint: dict, plan: dict, scores: dict, note: str = "") -> str:
    fail = [(k, n, scores[k]) for k, n in DIMS if scores[k]["score"] < FIX_BELOW]
    keep = [f"{n}={scores[k]['score']}" for k, n in DIMS if scores[k]["score"] >= FIX_BELOW]
    shots = sorted({s for _, _, v in fail for s in v.get("shots") or []})
    parts = ["【输入：人物卡】", character_cards(pre, chunk), "",
             f"【当前版本（ep{ep:02d} 全部镜头，只作上下文）】", shots_text(chunk), "",
             "【当前好莱坞方案】", json.dumps(plan, ensure_ascii=False, indent=1), "",
             constraints_text(ep_obj, base_lint), "",
             f"【评审打分：低于 {FIX_BELOW} 分的项（只改这些；目标总分 ≥{TARGET_SUM}/50 且没有低于 4 分的项）】"]
    parts += [f"- {n}：{v['score']} 分；涉及镜 {v.get('shots') or '未指出'}；原因：{v.get('why') or '未提供'}" for _, n, v in fail]
    parts += [f"【{FIX_BELOW} 分的项，原样保留】{'、'.join(keep) or '无'}", "",
              f"【本轮任务：第三步，只改不及格项】建议改的镜：{shots or '评审未指出，自选最少的镜'}。"
              "两种输出任选其一：A）镜数不变：先 ```json（只含被改镜的 shots 条目），再只输出被改的完整镜头块（镜号不变）；"
              "B）评审要求拆镜 / 合镜（例如 Pika 能力项：一镜里有披衣、站起再走开等多个大动作）时：先 ```json（完整方案），"
              f"再输出全部镜头块（镜号 1..N 连续；每镜 {SHOT_S} 秒，总秒数 = {SHOT_S}×N，N ≤ {DUR_WINDOW[1] // SHOT_S}；"
              + ("台词按上面的放开说明；" if FREE_DIALOGUE[0] else "台词 / 🎙 逐字同序；") + "没被点名的镜内容照抄当前版本）。"]
    if note:
        parts += ["", f"上一次的回复没有被采用（系统校验）：{note}"]
    return "\n".join(parts)


def judge_user(ep: int, pre: str, chunk: str, plan: dict | None) -> str:
    return "\n".join(["【人物卡】", character_cards(pre, chunk), "",
                      "【好莱坞方案】", json.dumps(plan, ensure_ascii=False, indent=1) if plan else "未提供（原稿没有方案）", "",
                      f"【ep{ep:02d} 本集镜头】", RL.block_text(chunk, "head"), "", shots_text(chunk), "",
                      "按量表打分，只输出 ```json。"])


def compare_user(ep: int, orig: str, best: str, plan: dict) -> str:
    return "\n".join([f"【ep{ep:02d} 原稿镜头（生硬的版本）】", shots_text(orig), "",
                      f"【ep{ep:02d} 好莱坞改写后的镜头】", shots_text(best), "",
                      "【好莱坞方案】", json.dumps(plan, ensure_ascii=False, indent=1), "",
                      "【任务：模板输出第 4 项，三组前后对照】从上面挑 3 处，每处给：生硬原句（原稿里的原文，逐字摘）→ 好莱坞改法"
                      "（改写后的原文，逐字摘）→ 为什么这样改（一两句，说用了好莱坞方法的哪一条）。只输出 ```json："
                      '{"pairs": [{"shot_before": 1, "shot_after": 1, "before": "", "after": "", "why": ""}]}，恰好 3 组。'])


# ------------------------------------------------------------------ 解析回复（只看格式）

def _json_block(raw: str) -> tuple[dict | None, str]:
    t = RL.strip_think(raw)
    m = re.search(r"```json\s*\n(.*?)\n```", t, re.S)
    s = m.group(1) if m else None
    if s is None:
        a, b = t.find("{"), t.rfind("}")
        s = t[a:b + 1] if a >= 0 and b > a else None
    if s is None:
        return None, "回复里没有 ```json 代码块"
    try:
        return json.loads(s), ""
    except ValueError as e:
        return None, f"```json 解析失败：{e}"


def _after_json(raw: str) -> str:
    t = RL.strip_think(raw)
    m = re.search(r"```json\s*\n.*?\n```", t, re.S)
    return t[m.end():] if m else t


def parse_full(raw: str) -> tuple[dict | None, list[str] | None, str]:
    plan, err = _json_block(raw)
    if err:
        return None, None, err
    body = _after_json(raw)
    nums = [int(RL.SHOT_RE.match(RL._norm(ln)).group(1)) for ln in body.split("\n") if RL.SHOT_RE.match(RL._norm(ln))]
    if not nums:
        return plan, None, "回复里没有 **镜N｜img** 镜头块"
    if nums != list(range(1, len(nums) + 1)):
        return plan, None, f"镜号应从 1 连续递增，回复是 {nums}"
    blocks, err = FR.parse_blocks(RL, body, nums)
    return plan, blocks, err


def parse_partial(raw: str, n: int) -> tuple[dict | None, dict[int, str] | None, str]:
    plan, err = _json_block(raw)
    if err:
        return None, None, err
    body = _after_json(raw)
    nums = [int(RL.SHOT_RE.match(RL._norm(ln)).group(1)) for ln in body.split("\n") if RL.SHOT_RE.match(RL._norm(ln))]
    if not nums:
        return plan, None, "回复里没有被改的镜头块"
    if len(set(nums)) != len(nums) or any(not 1 <= k <= n for k in nums):
        return plan, None, f"镜号 {nums} 不合法（应为 1..{n} 内、不重复，镜数不变）"
    blocks, err = FR.parse_blocks(RL, body, nums)
    return plan, (dict(zip(nums, blocks)) if blocks else None), err


def parse_scores(raw: str) -> tuple[dict | None, str]:
    d, err = _json_block(raw)
    if err:
        return None, err
    sc = (d or {}).get("scores") or {}
    out = {}
    for k, _ in DIMS:
        v = sc.get(k)
        try:
            s = int((v or {}).get("score"))
        except (TypeError, ValueError):
            return None, f"缺少或非整数：{k}"
        if not 1 <= s <= 5:
            return None, f"{k} 分数 {s} 不在 1–5"
        out[k] = {"score": s, "shots": [int(x) for x in (v.get("shots") or []) if str(x).isdigit()], "why": str(v.get("why") or "")}
    return {"scores": out, "note": str(d.get("note") or "")}, ""


def assemble_chunk(orig_chunk: str, blocks: list[str]) -> str:
    head = RL.block_text(orig_chunk, "head")
    return head + "\n\n" + "\n\n".join(b.rstrip("\n") for b in blocks) + "\n\n---\n"


def mech_align_all(pre: str, chunk: str, ep: int, wd: Path) -> str:
    """H3 对齐句按各镜 **时长** 机械重算（qwen_repair_loop.mech_align；只改时间码，不改内容）"""
    obj = episode_obj(pre, chunk, ep, wd)
    if obj is None:
        return chunk
    for k, sh in enumerate(sorted(obj.shots, key=lambda s: s.index)):
        blk = RL.block_text(chunk, k)
        nb, rec = RL.mech_align(blk, int(sh.duration or 0))
        nb, rec2 = beats_to_duration(nb, int(sh.duration or 0))
        nb, rec3 = light_separators(nb)
        if rec or rec2 or rec3:
            chunk = RL.splice(chunk, k, nb)
    return chunk


BEAT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\s*秒")


LIGHT_KEYS = ("补光=", "轮廓光=", "修正=")


def light_separators(block: str) -> tuple[str, str]:
    """**光线** 行字段分隔符机械统一为“｜”（ep10 fixup 实测：写作方用“；”分隔，解析器读不到 修正=，SS-X2 不消）。只改分隔符"""
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("**光线**"):
            new = ln
            for k in LIGHT_KEYS:
                new = re.sub(r"[；;，,]\s*(?=" + re.escape(k) + ")", "｜", new)
            if new != ln:
                lines[i] = new
                return "\n".join(lines), "光线分隔符统一为｜"
    return block, ""


def beats_to_duration(block: str, seconds: int) -> tuple[str, str]:
    """SS-M2 机械修正（run r2 实测 4 集里 9 处“分拍只写到 5.0s，镜长 6.0s”）：**分拍** 行最后一段的结束秒数 < 时长时改成时长。
    只改时间码，不改动作文字；分拍段不单调就不动"""
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if not ln.startswith("**分拍**"):
            continue
        ms = list(BEAT_RE.finditer(ln))
        if not ms or not seconds:
            return block, ""
        ends = [float(m.group(2)) for m in ms]
        if any(b < a for a, b in zip(ends, ends[1:])) or ends[-1] >= seconds or float(ms[-1].group(1)) >= seconds:
            return block, ""
        m = ms[-1]
        lines[i] = ln[:m.start(2)] + str(seconds) + ln[m.end(2):]
        return "\n".join(lines), f"分拍末段 {m.group(2)}→{seconds} 秒"
    return block, ""


# ------------------------------------------------------------------ 不变量 / lint

def worse_detail(worse: dict, L: dict) -> str:
    """I6 的 detail：不只写“TL-10 0→1”，把变多那条码在候选稿里的 lint 原文一起带上（K211-F 11-03：a17 只因 H3 末拍一个 'settle' 撞 RL-T6 被拒，
    写手包里只看到“TL-10 0→1”，下一包没法改对）。原文从 shot_block（阻断）和 zero_detail 里找带 [码] 的那条"""
    if not worse:
        return "无变多"
    msgs = list(L.get("shot_block") or []) + list(L.get("zero_detail") or [])
    parts = []
    for c, (a, b) in worse.items():
        hit = next((m for m in msgs if f"[{c}]" in m), "")
        parts.append(f"{c} {a}→{b}" + (f"（{hit[:220]}）" if hit else ""))
    return "变多：" + "；".join(parts)


def lint(chunk: str, ep: int) -> dict:
    """p4_adapter.check_p4（导入关口同款，写作链路级别 + Spec）→ 每码计数、P4 阻断（人物卡冻结项单列）"""
    import p4_adapter as P4
    rep, *_ = P4.check_p4(chunk, ep)
    codes, frozen, shot_block, zero_detail = {}, [], [], []
    for i in rep.issues:
        m = re.match(r"\[([A-Za-z0-9-]+)\]", i.message or "")
        code = m.group(1) if m else i.rule
        codes[code] = codes.get(code, 0) + 1
        if code in ZERO_CODES:
            zero_detail.append(f"{i.field}：{i.message}"[:200])
        if i.level == "block":
            (frozen if (FROZEN_MARK in (i.message or "") and re.fullmatch(r"ep\d+", i.field or "")) else shot_block).append(
                f"{i.field}：{i.message}"[:300])
    return {"codes": dict(sorted(codes.items())), "frozen_block": frozen, "shot_block": shot_block, "zero_detail": zero_detail}


def gate(pre: str, orig: str, cand: str, ep: int, base_lint: dict, wd: Path) -> dict:
    res = {"ok": True, "checks": []}

    def add(cid, name, ok, detail):
        res["checks"].append({"id": cid, "name": name, "ok": bool(ok), "detail": detail})
        res["ok"] &= bool(ok)
    A = episode_obj(pre, orig, ep, wd)
    try:
        B = episode_obj(pre, cand, ep, wd)
    except Exception as e:  # noqa: BLE001
        B = None
        add("I0", "能导入", False, f"解析失败：{e!r}"[:300])
    if B is None:
        if not res["checks"]:
            add("I0", "能导入", False, "导入器解析不出本集")
        return res
    add("I0", "能导入", True, f"{len(B.shots)} 镜")
    sa, sb = FR.dialogue_seq(A), FR.dialogue_seq(B)
    if FREE_DIALOGUE[0]:
        res["checks"].append({"id": "I1", "name": "台词 / 🎙 改动（项目方 11-02 放开，只记录）", "ok": sa == sb, "report_only": True,
                              "detail": "一致" if sa == sb else f"原 {sa} → 新 {sb}"[:1500]})
    else:
        add("I1", "台词 / 🎙 逐字同序", sa == sb, "一致" if sa == sb else f"原 {sa} → 新 {sb}"[:500])
    add("I2", "集头逐字（剧情 / 人物卡 / 造型）", RL.block_text(orig, "head") == RL.block_text(cand, "head"), "系统保留原集头")
    sc_a, sc_b = {s.scene_id for s in A.shots}, {s.scene_id for s in B.shots}
    nm = lambda E: {c.name for s in E.shots for c in (s.cast or [])}   # noqa: E731
    add("I3", "场景 id / 出场人物不新增", sc_b <= sc_a and nm(B) <= nm(A),
        f"场景 {sorted(map(str, sc_b))}（原 {sorted(map(str, sc_a))}）；人物 {sorted(nm(B))}（原 {sorted(nm(A))}）")
    from ns_agent.importer.script_md import shot_cap
    cap = shot_cap(B)
    add("I4", "镜数 ≤ D-SCR-06 上限", 6 <= len(B.shots) <= cap, f"{len(B.shots)} 镜，上限 {cap}")
    tot = sum(int(s.duration or 0) for s in B.shots)
    add("I5", f"集时长 {DUR_WINDOW[0]}–{DUR_WINDOW[1]} 秒", DUR_WINDOW[0] <= tot <= DUR_WINDOW[1],
        f"{tot} 秒（项目方 11-01：60–120 秒，D-SCR-08）")
    L = lint(cand, ep)
    worse = {c: (base_lint["codes"].get(c, 0), n) for c, n in L["codes"].items() if n > base_lint["codes"].get(c, 0)}
    add("I6", "lint 每个码不比原稿多", not worse, worse_detail(worse, L))
    add("I7", "P4 阻断 = 0（人物卡冻结项除外）", not L["shot_block"], "0" if not L["shot_block"] else "；".join(L["shot_block"])[:600])
    zero = zero_hits(L)
    # I8 只报告、不作废：K-WRT-702 新 lint 要求降到 0，降不到的镜列给总调度（总调度 r2 第 2 条）
    res["checks"].append({"id": "I8", "name": "新 lint 降到 0（" + ("、".join(ZERO_CODES) or "未设") + "）", "ok": not zero,
                          "detail": "0" if not zero else "；".join(zero)[:600], "report_only": True})
    res["lint"], res["worse"], res["total_s"], res["shots"], res["cap"], res["zero_hits"] = L, worse, tot, len(B.shots), cap, zero
    return res


def zero_hits(L: dict) -> list[str]:
    return list(L.get("zero_detail") or [])


def apply_head_exceptions(chunk: str, ep: int) -> tuple[str, list[str]]:
    """项目方授权的人物卡例外：只在集头指定造型行里逐字替换（系统照原话改，不写内容）"""
    head = RL.block_text(chunk, "head")
    new, done = head, []
    for line_mark, old, rep_ in HEAD_EXCEPTIONS.get(ep, []):
        lines = new.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith(line_mark) and old in ln:
                lines[i] = ln.replace(old, rep_)
                done.append(f"{line_mark} {old} → {rep_}")
        new = "\n".join(lines)
    return (RL.splice(chunk, "head", new) if new != head else chunk), done


def gate_note(g: dict) -> str:
    s = "；".join(f"{c['id']} {c['name']} 不满足：{c['detail']}" for c in g["checks"]
                 if not c["ok"] and not (c["id"] == "I1" and c.get("report_only")))[:1500]
    if g.get("worse"):
        s += "\n变多的码的规则原文：" +"；".join(rule_text(c) for c in g["worse"])[:1500]
    return s


def format_repair(pre: str, chunk: str, ep: int, codes: list[str], ask, wd: Path, tag: str, force: list[str] | None = None) -> str:
    """复用 qwen_repair_loop（逐镜格式返修，台词 / 时长不变）修变多的 lint 码与镜头 P4 阻断"""
    src, out = wd / f"{tag}_in.md", wd / f"{tag}_out.md"
    src.write_text(pre + chunk, encoding="utf-8")
    RL.ONLY_CODES.clear()
    if force and "QW-W5" not in codes:
        codes = [*codes, "QW-W5"]
    RL.main([str(src), "--out", str(out), "--repair-dir", str(wd / f"{tag}_repair"), "--fix-warn", "--only-codes", ",".join(codes),
             "--no-export", "--max-rounds", "3", *[x for f in (force or []) for x in ("--force-shot", f)]], ask=ask)
    RL.ONLY_CODES.clear()
    RL.FORCE.clear()
    RL.ORIG.clear()
    if not out.exists():
        return chunk
    _, ch = RL.split_doc(out.read_text(encoding="utf-8"))
    return ch[0] if ch else chunk


# ------------------------------------------------------------------ 调用（计费、预算）

class Budget:
    def __init__(self, cap: float, clients: list):
        self.cap, self.clients = cap, clients
        try:
            from ns_api import llm_config
            rv = llm_config.resolve("script_write")
            self.price = llm_config.model_pricing(rv["id"]).get(rv["model"]) or {"prompt": 1e-6, "completion": 2e-6}
        except Exception:  # noqa: BLE001
            self.price = {"prompt": 1e-6, "completion": 2e-6}

    def usage(self) -> dict:
        u = {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0}
        for c in self.clients:
            for k in u:
                u[k] += int((getattr(c, "usage", {}) or {}).get(k) or 0)
        u["usd"] = round(u["prompt_tokens"] * self.price["prompt"] + u["completion_tokens"] * self.price["completion"], 4)
        u["price_per_m"] = {"prompt": self.price["prompt"] * 1e6, "completion": self.price["completion"] * 1e6}
        return u

    def left(self) -> float:
        return self.cap - self.usage()["usd"]


class Stub:
    """桩：写作方原样回原稿镜头（+ 空方案），评审回全 3 分。只验链路，不花钱"""

    def __init__(self, role: str, orig_chunk: str = ""):
        self.role, self.orig = role, orig_chunk
        self.usage = {"calls": 0, "stub": True}

    def __call__(self, system: str, user: str) -> str:
        self.usage["calls"] += 1
        if self.role == "judge":
            return "```json\n" + json.dumps({"scores": {k: {"score": 3, "shots": [1], "why": "stub"} for k, _ in DIMS}, "note": "stub"}) + "\n```"
        if "三组前后对照" in user:
            return '```json\n{"pairs": []}\n```'
        if "当前的完整 Markdown" in user:      # qwen_repair_loop 的逐镜请求
            return FR.stub_writer(system, user)
        return '```json\n{"logline": "stub", "beats": [], "scenes": [], "shots": []}\n```\n\n' + shots_text(self.orig)


# ------------------------------------------------------------------ 主流程

def cmd_run(a) -> int:
    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    wd = od / "work"
    wd.mkdir(exist_ok=True)
    text, rec = RC.assemble(RL, [a.episode], RC.episode_sources())
    (od / "input.md").write_text(text, encoding="utf-8")
    pre, chunks = RL.split_doc(text)
    orig, ep = chunks[0], a.episode
    ZERO_CODES[:] = [c.strip() for c in (a.zero_codes or "").split(",") if c.strip()]
    FREE_DIALOGUE[0] = bool(getattr(a, "free_dialogue", False))
    orig, head_exc = apply_head_exceptions(orig, ep)
    if a.stub:
        writer, judge = Stub("writer", orig), Stub("judge")
    else:
        writer = FR.Writer(temperature=0.7, max_tokens=30000)
        judge = FR.Writer(temperature=0.2, max_tokens=8000)
    judge_b = Stub("judge") if a.stub else FR.Writer(temperature=0.7, max_tokens=8000)
    budget = Budget(a.budget, [writer, judge, judge_b])
    W_SYS, J_SYS = writer_system(), judge_system()
    calls_dir = od / "calls"
    calls_dir.mkdir(exist_ok=True)

    def call(client, sysmsg, uid, user):
        if budget.left() < 0.08:
            raise RuntimeError(f"预算将尽（已花 ${budget.usage()['usd']}，上限 ${budget.cap}），停止调用")
        (calls_dir / f"{uid}.req.txt").write_text(user, encoding="utf-8")
        raw = client(sysmsg, user)
        (calls_dir / f"{uid}.reply.txt").write_text(raw, encoding="utf-8")
        fin = getattr(client, "last_finish", None)
        if fin and fin != "stop":
            _log(od, f"  {uid} finish_reason={fin}")
        return raw

    ep_obj = episode_obj(pre, orig, ep, wd)
    base_lint = lint(orig, ep)
    rounds = []
    _log(od, f"ep{ep:02d} 原稿 {len(ep_obj.shots)} 镜 / {sum(int(s.duration or 0) for s in ep_obj.shots)} 秒；lint {base_lint['codes']}；"
             f"P4 镜头阻断 {len(base_lint['shot_block'])}、人物卡冻结 {len(base_lint['frozen_block'])}")

    def score_one(client, uid):
        for t in range(2):
            raw = call(client, J_SYS, f"{uid}{t}", judge_user(ep, pre, cur_score_chunk[0], cur_score_chunk[1]))
            sc, err = parse_scores(raw)
            if sc:
                return sc
            _log(od, f"  {uid} 评审回复格式不对：{err}")
        return None

    cur_score_chunk = [None, None]

    def score(chunk, plan, uid):
        """两个独立评审调用（温度 0.2 / 0.7，互相看不到）逐项取平均（r3：run 实测同一稿两次打分差 2–7 分，单次评审噪声
        会让“连续两轮无提升即停”误停；项目方 22:1x 要求查评审稳定性）。两次总分差 >3 记 unstable"""
        cur_score_chunk[:] = [chunk, plan]
        a_ = score_one(judge, f"{uid}-judgeA")
        b_ = score_one(judge_b, f"{uid}-judgeB")
        if not a_ or not b_:
            return a_ or b_
        out = {}
        for k, _ in DIMS:
            x, y = a_["scores"][k], b_["scores"][k]
            out[k] = {"score": (x["score"] + y["score"]) / 2, "shots": sorted(set(x["shots"]) | set(y["shots"])),
                      "why": "；".join(w for w in (x["why"], y["why"]) if w), "a": x["score"], "b": y["score"]}
        d = _sum(a_) - _sum(b_)
        if abs(d) > 3:
            _log(od, f"  {uid} 两个评审总分差 {d}（A {_sum(a_)} / B {_sum(b_)}）>3，记 unstable")
        return {"scores": out, "note": f"A：{a_['note']} | B：{b_['note']}", "sum_a": _sum(a_), "sum_b": _sum(b_),
                "unstable": abs(d) > 3}

    # r0：原稿打分（基线）+ 不变量（原稿 vs 原稿 → 只看时长 / lint / P4 这几项）
    g0 = gate(pre, orig, orig, ep, base_lint, wd)
    s0 = score(orig, None, "r0")
    (od / "r0.md").write_text(pre + orig, encoding="utf-8")
    rounds.append({"round": 0, "kind": "原稿基线", "chunk": "r0.md", "plan": None, "scores": s0, "gate": g0,
                   "changed": [], "eligible": bool(g0["ok"] and s0)})
    _log(od, f"r0 分数 {_sum(s0)}；不变量 {'过' if g0['ok'] else '不过：' + gate_note(g0)[:300]}")

    best_idx = 0 if rounds[0]["eligible"] else None
    no_gain = discarded_run = 0
    for r in range(1, MAX_ROUNDS + 1):
        base = rounds[best_idx] if best_idx is not None else None
        full = base is None or base["round"] == 0
        cur_chunk = orig if full else RL.split_doc((od / base["chunk"]).read_text(encoding="utf-8"))[1][0]
        cand_failed = None
        rec_r = {"round": r, "kind": "整集重写" if full else "只改不及格项", "attempts": []}
        cand, plan, note, changed = None, None, "", []
        try:
            for att in range(1, 4):      # r3：每轮最多 3 次（台词 I1 / QW-W11 是主要作废原因，带校验说明重试）
                if full:
                    raw = call(writer, W_SYS, f"r{r}-write{att}", writer_user_full(ep, pre, orig, ep_obj, base_lint, note))
                    p, blocks, err = parse_full(raw)
                    c = assemble_chunk(orig, blocks) if blocks else None
                    chg = list(range(1, len(blocks) + 1)) if blocks else []
                else:
                    cur_obj = episode_obj(pre, cur_chunk, ep, wd)
                    raw = call(writer, W_SYS, f"r{r}-fix{att}",
                               writer_user_fix(ep, pre, cur_chunk, cur_obj, base_lint, base["plan"] or {}, base["scores"]["scores"], note))
                    nums_r = [int(RL.SHOT_RE.match(RL._norm(ln)).group(1)) for ln in _after_json(raw).split("\n")
                              if RL.SHOT_RE.match(RL._norm(ln))]
                    restructure = bool(nums_r) and nums_r == list(range(1, len(nums_r) + 1)) and len(nums_r) != len(cur_obj.shots) \
                        and len(nums_r) > 1
                    if restructure:
                        p, blocks, err = parse_full(raw)
                        bmap = None
                        c = assemble_chunk(orig, blocks) if blocks else None
                        chg = ["拆 / 合镜", len(cur_obj.shots), "→", len(blocks) if blocks else 0]
                        rec_r["kind"] = "只改不及格项（拆 / 合镜）"
                    else:
                        p, bmap, err = parse_partial(raw, len(cur_obj.shots))
                        c = cur_chunk
                    if restructure:
                        pass
                    elif bmap:
                        for k in sorted(bmap):
                            c = RL.splice(c, k - 1, bmap[k])
                    else:
                        c = None
                    if not restructure:
                        chg = sorted(bmap) if bmap else []
                    if p is not None and base["plan"] and not restructure:
                        p = merge_plan(base["plan"], p)
                if err or c is None:
                    note = err or "回复解析失败"
                    rec_r["attempts"].append({"attempt": att, "parse_error": note})
                    _log(od, f"r{r} 第 {att} 次：解析失败 {note[:200]}")
                    continue
                c = mech_align_all(pre, c, ep, wd)
                g = gate(pre, orig, c, ep, base_lint, wd)
                arec = {"attempt": att, "gate_first": _gate_brief(g)}
                fixable = sorted({x for x in list(g.get("worse") or {}) if x.startswith(("QW-", "H3-"))}
                                 | {m.group(1) for s in (g.get("lint") or {}).get("shot_block", [])
                                    for m in [re.search(r"\[((?:QW|H3)-[A-Z0-9]+)\]", s)] if m})
                fixable = sorted(set(fixable) | {c for c in ZERO_CODES if (g.get("lint") or {}).get("codes", {}).get(c)})
                fixable = [x for x in fixable if x not in EPISODE_CODES]
                only_lint = all(ch["ok"] or ch.get("report_only") for ch in g["checks"] if ch["id"] not in ("I6", "I7", "I8"))
                force = [f"ep{ep:02d}-S{m.group(1)}=QW-W5:{x.split('：', 1)[-1][:200]}" for x in (g.get("lint") or {}).get("shot_block", [])
                         for m in [re.search(r"\[QW-W5\] 镜(\d+)", x)] if m]
                if not g["ok"] and only_lint and (fixable or force):
                    _log(od, f"r{r} 第 {att} 次：只差 lint / P4，格式返修 {fixable} 强制镜 {len(force)}")
                    c = format_repair(pre, c, ep, fixable, writer, wd, f"r{r}a{att}", force)
                    c = mech_align_all(pre, c, ep, wd)
                    g = gate(pre, orig, c, ep, base_lint, wd)
                    arec["format_repair"] = fixable
                arec["gate"] = _gate_brief(g)
                rec_r["attempts"].append(arec)
                if g["ok"]:
                    cand, plan, changed = c, p, chg
                    rec_r["gate"] = g
                    break
                note = gate_note(g)
                _log(od, f"r{r} 第 {att} 次：不变量不过 {note[:300]}")
                cand_failed = (c, p, g)
        except RuntimeError as e:
            rec_r["error"] = str(e)
            _log(od, f"r{r} 中止：{e}")
        if cand is None:
            rec_r.update({"eligible": False, "discarded": True, "scores": None})
            if cand_failed:
                c, p, g = cand_failed
                (od / f"r{r}_discarded.md").write_text(pre + c, encoding="utf-8")
                rec_r.update({"chunk": f"r{r}_discarded.md", "plan": p, "gate": g})
            rounds.append(rec_r)
            # r3：作废轮没有分数，不算“总分没有提升”的轮（run 实测 7 集里 5 集因两轮作废在 r2 就停，没进入打分迭代）；
            # 仍受 8 轮上限和预算约束；连续 3 轮作废也停
            discarded_run += 1
            _log(od, f"r{r} 作废（不变量 / 解析不过）")
            if "error" in rec_r or discarded_run >= 3:
                break
            continue
        discarded_run = 0
        (od / f"r{r}.md").write_text(pre + cand, encoding="utf-8")
        try:
            sc = score(cand, plan, f"r{r}")
        except RuntimeError as e:
            sc, rec_r["error"] = None, str(e)
        rec_r.update({"chunk": f"r{r}.md", "plan": plan, "scores": sc, "changed": changed, "eligible": bool(sc)})
        rounds.append(rec_r)
        prev_best = _sum(rounds[best_idx]["scores"]) if best_idx is not None else -1
        _log(od, f"r{r} 分数 {_sum(sc)}（此前最好 {prev_best}）；改了镜 {changed}")
        if sc and _sum(sc) > prev_best:
            best_idx, no_gain = len(rounds) - 1, 0
        else:
            no_gain += 1
        if reached(sc):
            _log(od, f"r{r} 总分 {_sum(sc)} ≥{TARGET_SUM} 且无 <{PASS_SCORE} 项（百分制 ≥95），停")
            break
        if no_gain >= 2 or "error" in rec_r:
            _log(od, "连续两轮无提升或预算停，停")
            break

    best = rounds[best_idx] if best_idx is not None else None
    report = {"schema": "nsfs.hollywood/1", "episode": ep, "at": time.strftime("%F %T"), "sources": rec, "stub": a.stub,
              "dur_window": DUR_WINDOW, "base_lint": base_lint, "rounds": rounds, "head_exceptions": head_exc,
              "zero_codes": list(ZERO_CODES), "free_dialogue": FREE_DIALOGUE[0],
              "selected_round": best["round"] if best else None}
    if best and best["round"] > 0:
        _, bc = RL.split_doc((od / best["chunk"]).read_text(encoding="utf-8"))
        final = bc[0]
        (od / "final.md").write_text(pre + final, encoding="utf-8")
        try:
            raw = call(writer, W_SYS, "compare", compare_user(ep, orig, final, best["plan"] or {}))
            cmp_, err = _json_block(raw)
            report["pairs"] = (cmp_ or {}).get("pairs") or []
            report["pairs_error"] = err
        except RuntimeError as e:
            report["pairs"], report["pairs_error"] = [], str(e)
        report["lint_before"], report["lint_after"] = base_lint, lint(final, ep)
        report["validate_before"], report["validate_after"] = _validate_counts(od / "input.md", ep), _validate_counts(od / "final.md", ep)
    report["usage"] = budget.usage()
    (od / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _log(od, f"完成：选中 r{report['selected_round']}；费用 {report['usage']}")
    return 0


def merge_plan(old: dict, new: dict) -> dict:
    out = json.loads(json.dumps(old))
    for k in ("logline", "beats", "scenes"):
        if new.get(k):
            out[k] = new[k]
    by = {int(s.get("shot", 0)): s for s in out.get("shots") or []}
    for s in new.get("shots") or []:
        try:
            by[int(s.get("shot", 0))] = s
        except (TypeError, ValueError):
            pass
    out["shots"] = [by[k] for k in sorted(by)]
    return out


def reached(sc: dict | None) -> bool:
    return bool(sc) and _sum(sc) >= TARGET_SUM and all(v["score"] >= PASS_SCORE for v in sc["scores"].values())


def _sum(sc: dict | None) -> float:
    return round(sum(v["score"] for v in sc["scores"].values()), 1) if sc else -1


def _gate_brief(g: dict) -> dict:
    return {"ok": g["ok"], "failed": [f"{c['id']} {c['detail']}"[:300] for c in g["checks"] if not c["ok"]]}


def _validate_counts(path: Path, ep: int) -> dict:
    try:
        v = FR.validate_json(path)
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)[:200]}
    return {"blocking": v.get("blocking"), "warnings": v.get("warnings"), "counts": FR.counts(v).get(ep, {})}


# ------------------------------------------------------------------ 审片页

def _md_to_html(md: str) -> str:
    """极简 Markdown → HTML（标题 / 表格 / 列表 / 段落），给 config 盘点表用"""
    out, rows = [], []

    def flush():
        if rows:
            body = [r for r in rows if not re.fullmatch(r"\|?\s*:?-{2,}.*", r.strip())]
            cells = [[html.escape(c.strip()) for c in r.strip().strip("|").split("|")] for r in body]
            out.append("<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in cells[0]) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in cells[1:]) + "</tbody></table>")
            rows.clear()
    for ln in md.splitlines():
        if ln.strip().startswith("|"):
            rows.append(ln)
            continue
        flush()
        m = re.match(r"(#{1,4})\s+(.*)", ln)
        if m:
            n = len(m.group(1)) + 1
            out.append(f"<h{n}>{html.escape(m.group(2))}</h{n}>")
        elif re.match(r"\s*([-*]|\d+\.)\s+", ln):
            out.append(f"<div class=li>{html.escape(ln.strip())}</div>")
        elif ln.strip() and not ln.startswith("<!--"):
            out.append(f"<p>{html.escape(ln)}</p>")
    flush()
    return "\n".join(out)


def _h3_desc(h3: str | None) -> str:
    if not h3:
        return ""
    m = re.search(r"integrated_multimodal_description:\s*(.*?)(?:\n\s*\n|$)", h3, re.S)
    return (m.group(1) if m else h3).strip()


# ------------------------------------------------------------------ 合并 + 暂存 + 导入计划（r2：项目方“10 集都用，改完再出图”）

def cmd_merge(a) -> int:
    """各集 <root>/epNN/report.json：选中轮 > 0 且该轮不变量 I0–I7 全过 → 收 final.md 的那一集；没过的集不收、列出。
    来源 sha 复核（与 run 时 report.sources 一致，生产稿没被别人改过）→ 拼成一份 → staging_v3/merged → validate 阻断 = 0 → import_plan.json"""
    import hashlib
    root = Path(a.out_dir)
    eps = sorted(RL.parse_episodes(a.episodes))
    srcs = RC.episode_sources()
    pre, parts, ok_eps, bad = None, [], [], {}
    for e in eps:
        f = root / f"ep{e:02d}" / "report.json"
        if not f.exists():
            bad[e] = "没有 report.json"
            continue
        rp = json.loads(f.read_text(encoding="utf-8"))
        sel = rp.get("selected_round")
        g = next((r.get("gate") for r in rp["rounds"] if r["round"] == sel), None) if sel else None
        if not sel or not g or not g.get("ok"):
            bad[e] = "没有通过不变量的改写轮" if not sel else "选中轮不变量没过"
            continue
        sel_sc = next((r.get("scores") for r in rp["rounds"] if r["round"] == sel), None)
        if not reached(sel_sc) and not getattr(a, "stage_below_target", False):
            low = [f"{n}={sel_sc['scores'][k]['score']}（{sel_sc['scores'][k]['why'][:80]}）" for k, n in DIMS
                   if sel_sc and sel_sc["scores"][k]["score"] < FIX_BELOW]
            bad[e] = f"选中 r{sel} 总分 {_sum(sel_sc)}/50 < {TARGET_SUM}（百分制 95）：" + "；".join(low)
            continue
        s0 = rp["sources"][0]
        if not srcs.get(e, {}).get("sha_ok") or srcs[e]["sha256"] != s0["sha256"]:
            bad[e] = f"生产来源已变（run 时 {s0['sha256'][:12]}，现在 {str(srcs.get(e, {}).get('sha256'))[:12]}），须重跑"
            continue
        p0, ch = RL.split_doc((root / f"ep{e:02d}" / "final.md").read_text(encoding="utf-8"))
        pre = pre if pre is not None else p0
        parts.append(ch[0] if ch[0].endswith("\n") else ch[0] + "\n")
        ok_eps.append(e)
    summary = {"schema": "nsfs.hollywood_merge/1", "at": time.strftime("%F %T"), "ok_eps": ok_eps, "not_imported": bad}
    if ok_eps:
        tag = "_".join(f"ep{e:02d}" for e in ok_eps)
        out = root / f"merged_{tag}.md"
        out.write_text(pre + "".join(parts), encoding="utf-8")
        v = FR.validate_json(out)
        summary["validate"] = {"blocking": v.get("blocking"), "warnings": v.get("warnings")}
        # r7 导入闸门（总调度 11-02：新剧本导入前先跑 rubric_code，代码判定失败项 = 0 才能导入；K-WRT-H08）
        RA = _load("rubric_audit", "tools/script_rsi/rubric_audit.py")
        rg = RA.gate(out)
        summary["rubric_gate"] = {"ok": rg["ok"], "eps": {e: {"met": x["met"], "total": x["total"], "fails": x["fails"][:8]} for e, x in rg["eps"].items()}}
        if not rg["ok"] and not getattr(a, "skip_rubric_gate", False):
            bad.update({e: "rubric_code 代码判定失败项 ≠ 0（导入闸门）：" + "；".join(x["fails"][:3]) for e, x in rg["eps"].items() if x["fails"]})
            v = {**v, "blocking": (v.get("blocking") or 0) + sum(1 for x in rg["eps"].values() if x["fails"])}
        if not v.get("blocking"):
            staged = ROOT / "data/staging_v3/merged" / f"漆皮之下·十日_series10_v1_hwd_{'_'.join(f'ep{e:02d}' for e in ok_eps)}_v3.md"
            if staged.exists():
                staged = staged.with_name(staged.stem + time.strftime("_%H%M%S") + ".md")
            staged.write_bytes(out.read_bytes())
            sha = hashlib.sha256(staged.read_bytes()).hexdigest()
            summary["staged"], summary["sha256"] = RC._rel(staged), sha
            summary["import_cmd"] = [".venv/Scripts/python.exe", "tools/autopilot/producer.py", "import-staged", "--obj", RC._rel(staged),
                                     "--reason", sha, "--by", "PRODUCER", "--note", a.note]
    (root / f"merge_{'_'.join(f'ep{e:02d}' for e in eps)}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False)[:3000])
    a._summary = summary
    return 0 if ok_eps and summary.get("staged") else 1


def cmd_ship(a) -> int:
    """单集：run（I0–I7 全过才有选中轮）→ merge 只含本集 → PRODUCER import-staged（merge 只替换本集；核 sha + validate 阻断 = 0，
    导入接口自己备份；审计 note = 项目方原话 + 总调度决定）→ CHANGELOG 追加“HOLLYWOOD 导入 epNN”。导入串行（文件锁）"""
    import os
    import subprocess
    root = Path(a.out_dir)
    e = a.episode
    if getattr(a, "free_dialogue", False):
        a.no_import = True                        # 台词放开的版本只出审片页，导入由项目方审过再定
    rc = cmd_run(argparse.Namespace(episode=e, out_dir=str(root / f"ep{e:02d}"), stub=False, budget=a.budget, zero_codes=a.zero_codes,
                                    free_dialogue=getattr(a, "free_dialogue", False)))
    m = argparse.Namespace(out_dir=str(root), episodes=str(e), note=a.note)
    if cmd_merge(m) != 0 or a.no_import:
        return 1 if not a.no_import else rc
    sm = m._summary
    lock = ROOT / "data" / "autopilot" / "hollywood_import.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(600):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(2)
    else:
        print("导入锁等了 20 分钟，放弃")
        return 1
    try:
        r = subprocess.run([sys.executable, *sm["import_cmd"][1:]], cwd=ROOT, capture_output=True,
                           env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}, timeout=1800)
        out = r.stdout.decode("utf-8", "replace").strip().splitlines()
        res = {"exit": r.returncode, "stdout": out[-1] if out else "", "stderr": r.stderr.decode("utf-8", "replace")[-500:]}
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)
    rp = json.loads((root / f"ep{e:02d}" / "report.json").read_text(encoding="utf-8"))
    rp["import"] = {"staged": sm["staged"], "sha256": sm["sha256"], **res}
    (root / f"ep{e:02d}" / "report.json").write_text(json.dumps(rp, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if res["exit"] == 0:
        sel = rp["selected_round"]
        sc = _sum(next(x for x in rp["rounds"] if x["round"] == sel)["scores"])
        g = next(x for x in rp["rounds"] if x["round"] == sel)["gate"]
        line = (f"- {time.strftime('%Y-%m-%d %H:%M')} HOLLYWOOD 导入 ep{e:02d}（fredw-2b 派 r2，PRODUCER import-staged merge）：{sm['staged']} "
                f"sha {sm['sha256'][:12]}；选中 r{sel} {sc}/50；{g['shots']} 镜 / {g['total_s']} 秒；I0–I7 全过；"
                f"新 lint {'、'.join(ZERO_CODES) or '—'} 剩 {len(g.get('zero_hits') or [])}；本集 API ${rp['usage']['usd']}；{res['stdout'][:200]}\n")
        with open(ROOT / "docs" / "CHANGELOG_AGENTS.md", "a", encoding="utf-8") as f:
            f.write(line)
    print(json.dumps(rp["import"], ensure_ascii=False))
    return res["exit"]


# 只讲字段格式（ep10 fixup 实测：写作方把光线修正写进了 **场景** 行，SS-X2 不认）
FIX_HINTS = {"SS-X2": "——把修正写在本镜 **光线** 行最后的 修正= 里（例：修正=清晨日光替代暖黄顶灯），**光线** 行四段齐全（主光= / 补光= / 轮廓光= / 修正=），不要写进 **场景** 行",
             "QW-E7": "——集头换装行指向这一镜：本镜 img 备注或 motion 写明换装（换上什么），镜号不变"}


def _shot_of(field: str, msg: str) -> int | None:
    m = re.match(r"ep\d+-S(\d+)", field or "") or re.search(r"镜(\d+)", msg or "")
    return int(m.group(1)) if m else None


def cmd_fixup(a) -> int:
    """r4 专项返修（总调度：ep03 / ep10 每轮都因 SS-X2 / QW-CH6 / QW-E7 / QW-W5 变多作废）：从作废候选里挑违规最少的一版，
    把“比原稿多”的码逐镜交 qwen_repair_loop（校验器码用 --only-codes；Spec 码 SS-* 与集级码按镜号转 --force-shot，说明原文照抄 lint），
    最多 2 遍；不变量全过 → 双评审打分记录 → 写成 r<N>.md 并设为选中轮（只暂存，导入另走）"""
    od = Path(a.out_dir)
    rp = json.loads((od / "report.json").read_text(encoding="utf-8"))
    ep = rp["episode"]
    ZERO_CODES[:] = list(rp.get("zero_codes") or [])
    pre, ch = RL.split_doc((od / "input.md").read_text(encoding="utf-8"))
    orig, _ = apply_head_exceptions(ch[0], ep)
    wd = od / "work"
    base_lint = rp["base_lint"]
    writer = FR.Writer(temperature=0.3, max_tokens=12000)
    judge, judge_b = FR.Writer(temperature=0.2, max_tokens=8000), FR.Writer(temperature=0.7, max_tokens=8000)
    budget = Budget(a.budget, [writer, judge, judge_b])
    cands = []
    for r in rp["rounds"]:
        f = od / str(r.get("chunk") or "")
        if r["round"] > 0 and f.is_file():
            c = mech_align_all(pre, RL.split_doc(f.read_text(encoding="utf-8"))[1][0], ep, wd)   # 机械修正（时间码 / 分隔符）先做
            g = gate(pre, orig, c, ep, base_lint, wd)
            nfail = sum(not x["ok"] for x in g["checks"] if x["id"] != "I8")
            hard = [x["id"] for x in g["checks"] if not x["ok"] and x["id"] not in ("I6", "I7", "I8")]
            cands.append((bool(hard), nfail, sum(b - a_ for a_, b in (g.get("worse") or {}).values()), r["round"], c, g))
    cands.sort(key=lambda t: t[:3])
    if not cands or cands[0][0]:
        print("没有只差 lint 的候选，专项返修不适用")
        return 1
    _, _, _, src_round, c, g = cands[0]
    log = {"from_round": src_round, "passes": []}
    _log(od, f"fixup：从 r{src_round} 起，初始 {_gate_brief(g)}")
    import p4_adapter as P4
    for n in range(1, 3):
        if g["ok"] or budget.left() < 0.15:
            break
        rep_, *_ = P4.check_p4(c, ep)
        worse = set(g.get("worse") or {})
        force, codes = [], set()
        for i in rep_.issues:
            mm = re.match(r"\[([A-Za-z0-9-]+)\]\s*(.*)", i.message or "")
            code, detail = (mm.group(1), mm.group(2)) if mm else (i.rule, i.message)
            if code not in worse and not (i.level == "block" and code.startswith("QW-")):
                continue
            k = _shot_of(i.field, detail)
            if code.startswith("QW-") and k is None:
                continue
            if code.startswith(("SS-", "QW-E", "QW-W5")) or not re.match(r"ep\d+-S\d+$", i.field or ""):
                if k:
                    hint = FIX_HINTS.get(code, "")
                    force.append(f"ep{ep:02d}-S{k}={code}:{detail[:220]}{hint}")
            else:
                codes.add(code)
        codes |= {f.split("=")[1].split(":")[0] for f in force}
        _log(od, f"fixup 第 {n} 遍：codes {sorted(codes)}；强制镜 {len(force)}")
        c = format_repair(pre, c, ep, sorted(codes), writer, wd, f"fixup{n}", force)
        c = mech_align_all(pre, c, ep, wd)
        g = gate(pre, orig, c, ep, base_lint, wd)
        log["passes"].append({"pass": n, "codes": sorted(codes), "force": force, "gate": _gate_brief(g)})
        _log(od, f"fixup 第 {n} 遍后：{_gate_brief(g)}")
    rec = {"round": max(r["round"] for r in rp["rounds"]) + 1, "kind": f"专项返修（从 r{src_round}）", "fixup": log, "gate": g,
           "changed": "格式返修", "attempts": []}
    if g["ok"]:
        name = f"r{rec['round']}.md"
        (od / name).write_text(pre + c, encoding="utf-8")
        plan = next((r.get("plan") for r in rp["rounds"] if r["round"] == src_round), None)
        scs = []
        for cl, tag in ((judge, "A"), (judge_b, "B")):
            raw = cl(judge_system(), judge_user(ep, pre, c, plan))
            (od / "calls" / f"{name[:-3]}-fixup-judge{tag}.reply.txt").write_text(raw, encoding="utf-8")
            scs.append(parse_scores(raw)[0])
        sc = None
        if all(scs):
            sc = {"scores": {k: {"score": (scs[0]["scores"][k]["score"] + scs[1]["scores"][k]["score"]) / 2,
                                 "shots": sorted(set(scs[0]["scores"][k]["shots"]) | set(scs[1]["scores"][k]["shots"])),
                                 "why": "；".join(w for w in (scs[0]["scores"][k]["why"], scs[1]["scores"][k]["why"]) if w)} for k, _ in DIMS},
                  "note": "", "sum_a": _sum(scs[0]), "sum_b": _sum(scs[1])}
        rec.update({"chunk": name, "plan": plan, "scores": sc, "eligible": bool(sc)})
        rp["selected_round"] = rec["round"]
        (od / "final.md").write_text(pre + c, encoding="utf-8")
        rp["lint_after"] = lint(c, ep)
    else:
        name = f"r{rec['round']}_discarded.md"
        (od / name).write_text(pre + c, encoding="utf-8")
        rec.update({"chunk": name, "discarded": True, "eligible": False, "scores": None})
    rp["rounds"].append(rec)
    u = budget.usage()
    rp.setdefault("fixup_usage", []).append(u)
    rp["usage"]["usd"] = round(float(rp["usage"].get("usd") or 0) + u["usd"], 4)
    rp["usage"]["calls"] = int(rp["usage"].get("calls") or 0) + u["calls"]
    (od / "report.json").write_text(json.dumps(rp, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _log(od, f"fixup 完成：不变量 {'全过' if g['ok'] else '没过'}；分数 {_sum(rec.get('scores'))}；费用 {u}")
    return 0 if g["ok"] else 1


def cmd_rejudge(a) -> int:
    """第二个独立评审（项目方 22:1x 第 4 条：抽 2 集看分数是否稳定）：对选中版另起评审调用（默认换模型 large-v2，
    同一量表、同一输入，看不到第一评审的分数和写作方任何自评）；两次相差 >3 分标出来"""
    od = Path(a.out_dir)
    rp = json.loads((od / "report.json").read_text(encoding="utf-8"))
    sel = rp.get("selected_round")
    r_sel = next(r for r in rp["rounds"] if r["round"] == sel)
    pre, ch = RL.split_doc((od / r_sel["chunk"]).read_text(encoding="utf-8"))
    j2 = FR.Writer(temperature=0.7, max_tokens=4000)   # 第二评审：独立调用、不同温度
    if a.model:
        j2.model, j2.off = a.model, {}
    raw = j2(judge_system(), judge_user(rp["episode"], pre, ch[0], r_sel.get("plan")))
    (od / "calls" / f"rejudge-{j2.model}.reply.txt").write_text(raw, encoding="utf-8")
    sc, err = parse_scores(raw)
    s1 = _sum(r_sel["scores"])
    rec = {"model": j2.model, "scores": sc, "error": err, "sum1": s1, "sum2": _sum(sc) if sc else None, "usage": j2.usage}
    rec["diff"] = (rec["sum2"] - s1) if sc else None
    rec["unstable"] = bool(sc) and abs(rec["diff"]) > 3
    rp.setdefault("judge2", []).append(rec)
    (od / "report.json").write_text(json.dumps(rp, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in rec.items() if k != "scores"}, ensure_ascii=False),
          {k: v["score"] for k, v in (sc or {}).get("scores", {}).items()})
    return 0


def cmd_summary(a) -> int:
    """10 集汇总审片页：每集分数轨迹 / 不变量 / 镜数时长 / 新 lint 剩余 / 导入状态 / 费用；每集详情页 epNN.html（cmd_page）"""
    root = Path(a.out_dir)
    E = html.escape
    rows, tot_usd, tot_calls, left = [], 0.0, 0, []
    for e in range(1, 11):
        d = root / f"ep{e:02d}"
        f = d / "report.json"
        if not f.exists():
            rows.append(f"<tr><td>ep{e:02d}</td><td colspan=8>未跑 / 运行中</td></tr>")
            continue
        rp = json.loads(f.read_text(encoding="utf-8"))
        try:
            cmd_page(argparse.Namespace(out_dir=str(d), html=str(root / f"ep{e:02d}.html"), note=""))
        except Exception as ex:  # noqa: BLE001
            print(f"ep{e:02d} 详情页失败：{ex!r}")
        sel = rp.get("selected_round")
        traj = " → ".join(f"r{r['round']}:{_sum(r.get('scores')) if r.get('scores') else '作废'}" for r in rp["rounds"])
        g = next((r.get("gate") for r in rp["rounds"] if r["round"] == sel), None) if sel else None
        zh = (g or {}).get("zero_hits") or []
        if zh:
            left += [f"ep{e:02d} {x}" for x in zh]
        imp = rp.get("import") or {}
        u = rp.get("usage") or {}
        tot_usd += float(u.get("usd") or 0)
        tot_calls += int(u.get("calls") or 0)
        rows.append(f"<tr><td><a href='ep{e:02d}.html'>ep{e:02d}</a></td><td>{E(traj)}</td><td>{'r' + str(sel) if sel else '无'}</td>"
                    f"<td class={'ok' if g and g.get('ok') else 'bad'}>{'全过' if g and g.get('ok') else '没过'}</td>"
                    f"<td>{(g or {}).get('shots', '—')} 镜 / {(g or {}).get('total_s', '—')} 秒</td><td>{len(zh) if g else '—'}</td>"
                    f"<td class={'ok' if imp.get('exit') == 0 else 'bad'}>{'已导入' if imp.get('exit') == 0 else ('导入失败' if imp else '未导入')}</td>"
                    f"<td>{u.get('calls', 0)} 次 / ${u.get('usd', 0)}</td><td>{E(', '.join(rp.get('head_exceptions') or []))}</td></tr>")
    h = [f"<!doctype html><meta charset=utf-8><title>HOLLYWOOD series10 10 集汇总</title><style>body{{font-family:system-ui,'Microsoft YaHei';margin:24px}}"
         "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px}.ok{color:#080}.bad{color:#c00}</style>",
         "<h1>HOLLYWOOD 模板 · series10 10 集汇总（r2）</h1>",
         "<p>项目方 11-01 21:4x：“10 集都用，改完再出图”“改成 60–120 秒”，ep01 人物卡“允许，改成铅笔裙”；22:06“全部gpu跑起来”。"
         "重写与打分全部由写作网关完成；系统只核不变量（I0–I7 全过才导入，PRODUCER merge 单集导入）。I8 = K-WRT-702（QW-W11）要求降到 0，剩余的列在下面交总调度。</p>",
         f"<p>{E(time.strftime('%F %T'))} 生成；合计 {tot_calls} 次调用，约 ${round(tot_usd, 4)}。config 盘点表见 <a href='../hollywood_ep01/index.html'>ep01 试点页</a>。</p>",
         "<table><tr><th>集</th><th>分数轨迹（满分 50）</th><th>选中</th><th>不变量 I0–I7</th><th>镜数 / 时长</th><th>QW-W11 剩</th><th>导入</th><th>费用</th><th>人物卡例外</th></tr>",
         *rows, "</table>", "<h2>QW-W11（K-WRT-702）降不到 0 的镜</h2>",
         "<pre>" + E("\n".join(left) or "无") + "</pre>"]
    out = root / "index.html"
    out.write_text("\n".join(h), encoding="utf-8")
    print(out)
    return 0


def cmd_page(a) -> int:
    od = Path(a.out_dir)
    rp = json.loads((od / "report.json").read_text(encoding="utf-8"))
    ep = rp["episode"]
    pre, ch0 = RL.split_doc((od / "input.md").read_text(encoding="utf-8"))
    orig = ch0[0]
    wd = od / "work"
    wd.mkdir(exist_ok=True)
    A = episode_obj(pre, orig, ep, wd)
    final_p = od / "final.md"
    final = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0] if final_p.exists() else None
    B = episode_obj(pre, final, ep, wd) if final else None
    sel = rp.get("selected_round")
    plan = next((r.get("plan") for r in rp["rounds"] if r["round"] == sel), None) or {}
    E = html.escape
    css = ("body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:24px;max-width:1500px;color:#222}"
           "table{border-collapse:collapse;margin:8px 0;font-size:13px}td,th{border:1px solid #ccc;padding:4px 6px;vertical-align:top}"
           "th{background:#f3f3f3}.ok{color:#080}.bad{color:#c00}.shot{border:1px solid #ddd;border-radius:6px;padding:10px;margin:12px 0}"
           ".row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.lbl{font-weight:600;color:#555;margin-top:6px}"
           "pre{white-space:pre-wrap;background:#fafafa;padding:6px;font-size:12px;margin:2px 0}.li{margin:2px 0 2px 12px}"
           "details{margin:6px 0}.tag{display:inline-block;padding:1px 6px;border-radius:4px;background:#eee;margin-right:4px}")
    h = [f"<!doctype html><meta charset=utf-8><title>HOLLYWOOD ep{ep:02d} 试点</title><style>{css}</style>",
         f"<h1>HOLLYWOOD 模板试点 · ep{ep:02d}</h1>",
         "<p>项目方 11-01 ~20:00 模板（好莱坞编剧 + 短剧提示词工程师）。重写与打分全部由写作网关完成（写作 / 评审两个独立调用）；"
         "系统只拼输入、核对不变量。<b>未导入生产剧本</b>，是否推广 / 导入由项目方决定。</p>",
         f"<p>生成：{E(rp['at'])}；来源：{E(rp['sources'][0]['source'])}；选中版本：<b>{'r' + str(sel) if sel is not None else '无（没有一轮通过不变量）'}</b>；"
         f"费用：{rp['usage'].get('calls')} 次调用，prompt {rp['usage'].get('prompt_tokens')} / completion {rp['usage'].get('completion_tokens')} token，"
         f"约 ${rp['usage'].get('usd')}{'（桩）' if rp.get('stub') else ''}</p>",
         (f"<p><b>说明</b>：{E(a.note)}</p>" if getattr(a, "note", "") else ""),
         "<p><a href='#audit'>1 config 盘点</a> · <a href='#shots'>2 最终提示词</a> · <a href='#rsi'>3 RSI 日志</a> · "
         "<a href='#pairs'>4 三组前后对照</a> · <a href='#inv'>不变量与 lint</a></p>"]
    # 1 盘点
    h += ["<h2 id=audit>1 config 盘点表 + 参数建议（系统盘点，只列建议、未执行）</h2>",
          _md_to_html(AUDIT_MD.read_text(encoding="utf-8")) if AUDIT_MD.exists() else "<p>未提供</p>"]
    # 2 最终提示词
    h.append("<h2 id=shots>2 最终提示词（按镜头编号）</h2>")
    if plan:
        h.append(f"<p><b>logline</b>：{E(str(plan.get('logline', '')))}</p>")
        h.append("<table><tr><th>节拍</th><th>时间</th><th>镜</th></tr>" + "".join(
            f"<tr><td>{E(str(b.get('beat', '')))}</td><td>{E(str(b.get('at', '')))}</td><td>{E(str(b.get('shots', '')))}</td></tr>"
            for b in plan.get("beats") or []) + "</table>")
        h.append("<table><tr><th>镜</th><th>人物目标</th><th>阻碍</th><th>赌注</th></tr>" + "".join(
            f"<tr><td>{E(str(s.get('shots', '')))}</td><td>{E(str(s.get('goal', '')))}</td><td>{E(str(s.get('obstacle', '')))}</td>"
            f"<td>{E(str(s.get('stakes', '')))}</td></tr>" for s in plan.get("scenes") or []) + "</table>")
    lines_by = {int(s.get("shot", 0)): s.get("script_line_zh", "") for s in plan.get("shots") or [] if str(s.get("shot", "")).isdigit()}
    if B is None:
        h.append("<p class=bad>没有通过不变量的改写版本，下面只列原稿。</p>")
    for sh in sorted((B or A).shots, key=lambda s: s.index):
        names = [c.name for c in (sh.cast or []) if c.visible]
        speech = [f"（{d.speaker_note}）“{d.text}”" for d in sh.dialogue]
        if sh.voiceover and sh.voiceover.text:
            speech.append(f"🎙（{sh.voiceover.speaker}）{sh.voiceover.text}")
        o = next((x for x in A.shots if x.index == sh.index), None) if B else None
        h.append(f"<div class=shot><b>镜{sh.index}</b> <span class=tag>{sh.duration} 秒</span>"
                 + "".join(f"<span class=tag>{E(n)}</span>" for n in names)
                 + f"<div class=lbl>中文剧本行</div><div>{E(lines_by.get(sh.index, '') or '（写作方未给）')}</div>"
                 + (f"<div class=lbl>台词 / 🎙（逐字）</div><div>{E(' '.join(speech))}</div>" if speech else "")
                 + f"<div class=lbl>视频提示词（EN，H3提示词正文 → Pika）</div><pre>{E(_h3_desc(sh.h3_prompt))}</pre>"
                 + f"<div class=lbl>视频提示词（中文，motion）</div><pre>{E(sh.motion_prompt)}</pre>"
                 + f"<div class=lbl>图片提示词（img → Qwen-Image 2.1）</div><pre>{E(sh.img_prompt)}</pre>"
                 + f"<div class=lbl>人物一致性描述（系统按人物卡逐字附）</div><pre>{E(consistency_lock(pre, final or orig, names))}</pre>"
                 + (f"<details><summary>原稿镜{o.index}（{o.duration} 秒）</summary><div class=lbl>img</div><pre>{E(o.img_prompt)}</pre>"
                    f"<div class=lbl>motion</div><pre>{E(o.motion_prompt)}</pre><div class=lbl>H3</div><pre>{E(_h3_desc(o.h3_prompt))}</pre></details>"
                    if o else "")
                 + "</div>")
    if B is not None and len(B.shots) != len(A.shots):
        h.append(f"<p>原稿 {len(A.shots)} 镜 → 改写 {len(B.shots)} 镜；原稿未一一对应的镜见 input.md。</p>")
    # 3 RSI
    h.append("<h2 id=rsi>3 RSI 日志（每轮 10 项分数、改了什么、选中第几轮）</h2>")
    h.append("<table><tr><th>轮</th><th>类型</th>" + "".join(f"<th>{E(n)}</th>" for _, n in DIMS)
             + "<th>合计</th><th>不变量</th><th>改了哪些镜</th></tr>")
    for r in rp["rounds"]:
        sc = (r.get("scores") or {}).get("scores")
        g = r.get("gate") or {}
        h.append(f"<tr><td>r{r['round']}{' ★选中' if r['round'] == sel else ''}</td><td>{E(r.get('kind', ''))}{'（作废）' if r.get('discarded') else ''}</td>"
                 + "".join(f"<td class={'ok' if sc and sc[k]['score'] >= PASS_SCORE else 'bad'}>{sc[k]['score'] if sc else '—'}</td>" for k, _ in DIMS)
                 + f"<td>{_sum(r.get('scores')) if sc else '—'}</td>"
                 + f"<td class={'ok' if g.get('ok') else 'bad'}>{'过' if g.get('ok') else '不过'}</td><td>{E(str(r.get('changed') or '—'))}</td></tr>")
    h.append("</table>")
    for r in rp["rounds"]:
        sc = (r.get("scores") or {}).get("scores")
        det = []
        if sc:
            det += [f"<div class=li>{E(n)} {sc[k]['score']} 分：镜 {E(str(sc[k]['shots']))} {E(sc[k]['why'])}</div>"
                    for k, n in DIMS if sc[k]["score"] < PASS_SCORE]
            det.append(f"<div class=li>评审总评：{E((r.get('scores') or {}).get('note', ''))}</div>")
        for at in r.get("attempts") or []:
            det.append(f"<div class=li>第 {at.get('attempt')} 次：{E(json.dumps({k: v for k, v in at.items() if k != 'attempt'}, ensure_ascii=False))[:800]}</div>")
        if r.get("error"):
            det.append(f"<div class=li class=bad>{E(r['error'])}</div>")
        h.append(f"<details><summary>r{r['round']} 详情（评审意见 / 尝试记录）</summary>{''.join(det)}</details>")
    # 4 对照
    h.append("<h2 id=pairs>4 三组前后对照（写作方产出）</h2>")
    pairs = rp.get("pairs") or []
    if pairs:
        h.append("<table><tr><th>#</th><th>生硬原句</th><th>好莱坞改法</th><th>为什么这样改</th></tr>" + "".join(
            f"<tr><td>{i + 1}（镜{E(str(p.get('shot_before', '')))}→镜{E(str(p.get('shot_after', '')))}）</td><td>{E(str(p.get('before', '')))}</td>"
            f"<td>{E(str(p.get('after', '')))}</td><td>{E(str(p.get('why', '')))}</td></tr>" for i, p in enumerate(pairs)) + "</table>")
    else:
        h.append(f"<p>未产出：{E(str(rp.get('pairs_error') or '没有选中的改写版本'))}</p>")
    # 不变量 / lint
    h.append("<h2 id=inv>不变量与 lint 前后对比</h2>")
    gsel = next((r.get("gate") for r in rp["rounds"] if r["round"] == sel), None) or rp["rounds"][0].get("gate") or {}
    h.append("<table><tr><th>检查</th><th>结果</th><th>说明</th></tr>" + "".join(
        f"<tr><td>{E(c['id'] + ' ' + c['name'])}</td><td class={'ok' if c['ok'] else 'bad'}>{'过' if c['ok'] else '不过'}</td><td>{E(c['detail'])}</td></tr>"
        for c in gsel.get("checks") or []) + "</table>")
    lb, la = rp.get("base_lint") or {}, rp.get("lint_after") or {}
    codes = sorted(set(lb.get("codes") or {}) | set(la.get("codes") or {}))
    h.append("<table><tr><th>lint 码（p4_adapter，写作链路级别）</th><th>原稿</th><th>选中版</th></tr>" + "".join(
        f"<tr><td>{E(c)}</td><td>{(lb.get('codes') or {}).get(c, 0)}</td><td class={'bad' if (la.get('codes') or {}).get(c, 0) > (lb.get('codes') or {}).get(c, 0) else 'ok'}>"
        f"{(la.get('codes') or {}).get(c, 0) if la else '—'}</td></tr>" for c in codes) + "</table>")
    h.append(f"<p>P4 阻断：原稿 镜头 {len(lb.get('shot_block') or [])} / 人物卡冻结 {len(lb.get('frozen_block') or [])}；"
             f"选中版 镜头 {len(la.get('shot_block') or []) if la else '—'} / 人物卡冻结 {len(la.get('frozen_block') or []) if la else '—'}。"
             "人物卡冻结项（集头 造型｜ 行上的阻断）受“人物卡不变”约束，写作方不能改，单列给总调度。</p>")
    if la.get("frozen_block") or lb.get("frozen_block"):
        h.append("<pre>" + E("\n".join(lb.get("frozen_block") or [])) + "</pre>")
    vb, va = rp.get("validate_before") or {}, rp.get("validate_after") or {}
    if va:
        h.append(f"<p>导入关口 validate_qwen_script（warn 级）：阻断 {vb.get('blocking')} → {va.get('blocking')}；提示 {vb.get('warnings')} → {va.get('warnings')}</p>")
    h.append(f"<p>产物目录：{E(str(od))}（input.md 原稿 / r*.md 各轮 / final.md 选中版 / calls/ 每次请求与回复 / report.json）</p>")
    out = Path(a.html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(h), encoding="utf-8")
    print(out)
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
    r.add_argument("--out-dir", required=True)
    r.add_argument("--stub", action="store_true")
    r.add_argument("--budget", type=float, default=COST_CAP_USD)
    r.add_argument("--zero-codes", default="", help="要求降到 0 的新 lint 码（逗号分隔，如 K-WRT-702 的 QW 号）")
    r.add_argument("--free-dialogue", action="store_true", help="台词放开（项目方 11-02）：I1 只记录不作废")
    p = sub.add_parser("page")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--html", required=True)
    p.add_argument("--note", default="", help="页首说明（如此前作废的试跑及其费用）")
    mg = sub.add_parser("merge")
    mg.add_argument("--out-dir", required=True, help="各集 run 的上级目录（含 epNN/）")
    mg.add_argument("--episodes", required=True)
    mg.add_argument("--note", default="")
    mg.add_argument("--skip-rubric-gate", action="store_true", help="跳过 rubric_code 导入闸门（只用于复现 r7 之前的旧稿，须总调度批准）")
    mg.add_argument("--stage-below-target", action="store_true",
                    help="未达 95 的集也暂存 + 写导入命令（只暂存不导入，等总调度 / 项目方定降级导入口径）")
    sh = sub.add_parser("ship", help="单集流水线：run → 单集 merge → producer import-staged → CHANGELOG（总调度 22:06）")
    sh.add_argument("--episode", type=int, required=True)
    sh.add_argument("--out-dir", required=True, help="上级目录；本集产物在 <out-dir>/epNN")
    sh.add_argument("--budget", type=float, default=COST_CAP_USD)
    sh.add_argument("--zero-codes", default="")
    sh.add_argument("--note", default="")
    sh.add_argument("--no-import", action="store_true")
    sh.add_argument("--free-dialogue", action="store_true", help="台词放开（项目方 11-02）：I1 只记录；隐含 --no-import")
    fx = sub.add_parser("fixup", help="专项返修：作废候选里只差 lint 的那版逐镜返修变多的码")
    fx.add_argument("--out-dir", required=True)
    fx.add_argument("--budget", type=float, default=1.0)
    rj = sub.add_parser("rejudge", help="第二个独立评审（换模型）复打选中版")
    rj.add_argument("--out-dir", required=True)
    rj.add_argument("--model", default="", help="默认同网关同模型、独立调用（large-v2 不能关推理，11-01 实测 2 次 20000 token 全是推理、无正文）")
    sm_ = sub.add_parser("summary")
    sm_.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "page": cmd_page, "merge": cmd_merge, "ship": cmd_ship, "summary": cmd_summary, "rejudge": cmd_rejudge, "fixup": cmd_fixup}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
