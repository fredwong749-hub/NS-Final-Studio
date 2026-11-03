"""集复盘门（HARNESS-O 11-03，项目方：每一集都是一次系统迭代）。

    .venv/Scripts/python.exe tools/master/episode_retro.py --run series10_v2 --episode 1          # 生成 / 刷新 docs/master/RETRO_ep01.md
    .venv/Scripts/python.exe tools/master/episode_retro.py done --run series10_v2 --episode 1     # 总调度勾完清单后标 done

内容（全部复用现有部件）：
  ① 本集指标 + 和上一集对比    ← tools/master/episode_metrics.collect / compare（本集 summary 同时落盘，和 episode_metrics calc 同一份）
  ② 本集卡点：怎么修、修完是否写进 SOP（report_issue close --sop-updated）和代码（仓库里 grep 得到卡点号）
  ③ 本集新增 / 改动的规则    ← git：本集开工以来 config/、knowledge/、docs/master/PIPELINE_SOP_V2.md 的提交 + 未提交改动
  ④ 记忆 / harness 更新清单（总调度勾选；- [x] 才算）
闸门：tools/master/sop_gate.py —— 第 N+1 集进“出图”要第 N 集复盘 done（文件里 `retro_status: done`）。
W24 RETRO-AUTO（11-03）：常驻 autoflow_resident.retro_tick 每 10 分钟调 tick()：整集预览已出的集 → 生成（事件指纹 retro_sig 没变不重写）
  + 已关没沉淀的卡点登记跟进（who=RETRO，不阻断，不重复）+ 第 5 节记忆候选 / 第 6 节 harness 建议 + 自动 done（done_by: retro_auto，
  开关 config/pipeline/sop_gate.json retro_auto_done，默认 true）。--dry 只打印不写盘。
刷新时保留已勾的项；已 done 的复盘不覆盖（要重开加 --force，状态回到 draft）。
文件名：主剧 docs/master/RETRO_epNN.md；别的剧 RETRO_<run>_epNN.md（sop_gate.retro_path）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULE_PATHS = ["config", "knowledge", "docs/master/PIPELINE_SOP_V2.md"]
CODE_PATHS = ["tools", "services", "packages", "tests", "config", "knowledge"]
STANDARD_ITEMS = [
    "MEMORY.md 现行骨架：本集新学到的事写进对应记忆文件（不新开重复文件）",
    "OWNER_CANON：本集项目方有没有新的重复要求 → 补定律或补“违反”计数",
    "PIPELINE_SOP_V2.md：本集每个卡点都写进对应步骤的“前置条件 / 卡过的地方”",
    "episode_ready / sop_gate：本集卡点里能自动查的，已做成检查（下一集开工前自动拦）",
    "master_check：本集新决策涉及的开关已进 SWITCH_EXPECT（带决策号）",
    "config/pipeline/sop_gate.json：observe_stages 是否可以收紧为 enforce",
    "下一集开工前跑 episode_ready + sop_gate status，缺的一次性补齐",
]


def _load(name: str, rel: str, root: Path = ROOT):
    sp = importlib.util.spec_from_file_location(name, root / rel if (root / rel).is_file() else ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _git(root: Path, *a: str) -> str:
    try:
        p = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):   # arch-ok: 不是 git 仓库（测试夹具）= 没有规则改动记录
        return ""


# ------------------------------------------------------------------ 各节
def metrics_section(root: Path, run: str, ep: int, collect=None, write: bool = True) -> tuple[list[str], dict | None]:
    EM = _load("episode_metrics_retro", "tools/master/episode_metrics.py", root)
    get = collect or (lambda e: EM.collect(root, run, e))
    try:
        cur = get(ep)
    except Exception as e:  # noqa: BLE001  指标算不出如实写，不挡复盘生成
        return [f"指标算不出：{e!r}"[:200]], None
    if collect is None and write:
        EM.write_summary(root, run, ep, cur, html=False)
    lines = ["```", EM.brief(cur), "```"]
    if ep > 1:
        prev = EM.jload(EM.Paths(root, run).summary(ep - 1)) if collect is None else None
        try:
            prev = prev or get(ep - 1)
        except Exception as e:  # noqa: BLE001
            prev = None
            lines.append(f"上一集指标算不出：{e!r}"[:200])
        if prev and "headline" not in prev and collect is None:
            prev["headline"] = EM.headline(root, run, ep - 1)       # 旧 summary（W24 之前算的）没有头条段：现场补算，不改盘上文件
        lines += ["", *headline_table(EM, prev, cur, ep)]
        if prev:
            rows = EM.compare(prev, cur)
            lines += ["", f"| 指标 | 第{ep - 1}集 | 第{ep}集 | 变化 |", "|---|---|---|---|"]
            mark = {"better": "✅ 变好", "worse": "❌ 变差", "same": "持平", "info": "—", "n/a": "—"}
            lines += [f"| {r['label']} | {EM._fmt(r['a']) if r['a'] is not None else '—'} | {EM._fmt(r['b']) if r['b'] is not None else '—'} | {mark.get(r['verdict'], r['verdict'])} |"
                      for r in rows]
    else:
        lines += ["", *headline_table(EM, None, cur, ep), "", "（第 1 集，没有上一集可比）"]
    return lines, cur


def headline_table(EM, prev: dict | None, cur: dict, ep: int) -> list[str]:
    """PLAN_V2_MASTER §1.3 两集对比（W24）：逐项本集 ≥ 上一集（越小越好的项是 ≤）才算过；另列 §1.3 绝对目标"""
    if not cur.get("headline"):
        return ["（本集 summary 没有 headline 段：episode_metrics 版本过旧）"]
    rows = EM.compare_headline(prev, cur)
    mark = {"better": "✅ 变好", "same": "✅ 持平", "worse": "❌ 退步", "n/a": "— 缺数"}
    out = [f"### PLAN §1.3 头条（第{ep}集 对 第{ep - 1}集，逐项不能退步）" if prev else f"### PLAN §1.3 头条（第{ep}集）", "",
           f"| 指标 | 第{ep - 1}集 | 第{ep}集 | 对比 | §1.3 目标 |", "|---|---|---|---|---|"]
    for r in rows:
        tgt = f"{r['target']} {'✅' if r['target_met'] else '❌'}" if r["target"] and r["target_met"] is not None else (r["target"] or "—")
        out.append(f"| {r['label']} | {'—' if r['a'] is None else r['a']} | {'—' if r['b'] is None else r['b']} | "
                   f"{mark[r['verdict']] if prev else '—'} | {tgt} |")
    if prev:
        worse = [r["label"] for r in rows if r["verdict"] == "worse"]
        out += ["", f"退步项：{'、'.join(worse)}（退步就修 pipeline，PLAN §1.3）" if worse else "退步项：无"]
    return out


def issue_rows(root: Path, run: str, ep: int) -> list[dict]:
    RI = _load("report_issue_retro", "tools/master/report_issue.py", root)
    rows = [i for i in RI.load(root / "data/pipeline/issues.jsonl") if i.get("run") == run and int(i.get("episode") or 0) == ep]
    for i in rows:
        hits = _git(root, "grep", "-l", "-F", i["id"], "--", *CODE_PATHS).split()
        i["code_refs"] = [h for h in hits if not h.endswith(".jsonl")][:4]
    return sorted(rows, key=lambda x: x.get("time") or "")


def issues_section(rows: list[dict]) -> list[str]:
    if not rows:
        return ["本集没有登记卡点。"]
    out = [f"共 {len(rows)} 条（未关 {sum(1 for r in rows if r['status'] == 'open')}，阻断 {sum(1 for r in rows if r.get('blocking'))}）。", "",
           "| 卡点 | 谁 | 步骤 | 什么事 | 怎么修（fix_hint） | 状态 | 写进 SOP | 写进代码 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        sop = "✅" if r.get("sop_updated") else ("❌" if r["status"] == "closed" else "—")
        code = "、".join(r["code_refs"]) if r["code_refs"] else "❌ 没找到"
        cell = lambda s, n=60: str(s or "").replace("|", "／").replace("\n", " ")[:n]  # noqa: E731
        out.append(f"| {r['id']} | {cell(r.get('who'), 16)} | {cell(r.get('step'), 8)} | {cell(r.get('what'))} | {cell(r.get('fix_hint'))} "
                   f"| {r['status']} | {sop} | {code} |")
    return out


def rules_section(root: Path, run: str, ep: int) -> list[str]:
    af = json.loads((root / f"data/pipeline/runs/{run}/autoflow_ep{ep:02d}.json").read_text(encoding="utf-8")) \
        if (root / f"data/pipeline/runs/{run}/autoflow_ep{ep:02d}.json").is_file() else {}
    since = str(af.get("started") or "")[:19] or "24 hours ago"
    committed = sorted({ln for ln in _git(root, "log", f"--since={since}", "--name-only", "--format=", "--", *RULE_PATHS).splitlines() if ln.strip()})
    pending = sorted({ln[3:] for ln in _git(root, "status", "--porcelain", "--", *RULE_PATHS).splitlines() if len(ln) > 3})
    out = [f"窗口：本集开工 {since} 起（git log --since + 未提交改动）。", ""]
    for title, files in (("已进版本", committed), ("未提交", pending)):
        out.append(f"- {title} {len(files)} 个：" + ("、".join(f"`{f}`" for f in files[:30]) + (" …" if len(files) > 30 else "") if files else "无"))
    return out


def checklist(rows: list[dict], old_checked: set[str]) -> list[str]:
    items = []
    for r in rows:
        if not r.get("sop_updated"):
            items.append(f"{r['id']}（{r.get('who')}）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes")
        if not r.get("code_refs"):
            items.append(f"{r['id']}：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由")
    items += STANDARD_ITEMS
    return [f"- [{'x' if it in old_checked else ' '}] {it}" for it in items]


def _old_checked(p: Path) -> set[str]:
    if not p.is_file():
        return set()
    return {m.group(1).strip() for m in re.finditer(r"^- \[[xX]\] (.+)$", p.read_text(encoding="utf-8"), re.M)}


def landed(r: dict) -> bool:
    """卡点的修法是否已进 SOP（sop_updated）或代码（仓库里 grep 得到卡点号）"""
    return bool(r.get("sop_updated") or r.get("code_refs"))


def followup_tag(iid: str) -> str:
    return f"[RETRO-FOLLOW {iid}]"


def followups(rows: list[dict], all_issues: list[dict]) -> list[dict]:
    """下一集前必做：修法没进 SOP / 代码的卡点（复盘自己登记的跟进项 who=RETRO 不再生跟进）。
    need_report = 已关但没沉淀、且还没登记过跟进项的（未关的卡点本身就在册，不重复登记）"""
    done_tags = {m.group(1) for i in all_issues if i.get("who") == "RETRO"
                 for m in [re.search(r"\[RETRO-FOLLOW (ISS-[\w-]+)\]", str(i.get("what") or ""))] if m}
    out = []
    for r in rows:
        if r.get("who") == "RETRO" or landed(r):
            continue
        out.append({**r, "need_report": r["status"] == "closed" and r["id"] not in done_tags, "followed": r["id"] in done_tags})
    return out


def followups_section(todo: list[dict], ep: int) -> list[str]:
    if not todo:
        return ["无：本集卡点的修法都已进 SOP 或代码。"]
    out = [f"共 {len(todo)} 条（未关 {sum(1 for t in todo if t['status'] == 'open')}，已关但没沉淀 {sum(1 for t in todo if t['status'] == 'closed')}）。"
           f"已关的各自登记一条跟进卡点（who=RETRO，不阻断，what 带 {followup_tag('<原卡点号>')}，同一条只登记一次）；未关的本身在册，不重复登记。", ""]
    for t in todo:
        st = "未关（在册）" if t["status"] == "open" else ("已登记跟进" if t["followed"] else "待登记跟进")
        out.append(f"- [第{ep + 1}集前] {t['id']}（{t.get('who')}，{st}）：{str(t.get('fix_hint') or t.get('what') or '')[:100]}")
    return out


def register_followups(root: Path, run: str, ep: int, todo: list[dict], reporter=None) -> list[str]:
    RI = None if reporter else _load("report_issue_retro", "tools/master/report_issue.py", root)
    live = root / "docs/master/V2_LIVE.md"
    rep = reporter or (lambda **kw: RI.report(issues=root / "data/pipeline/issues.jsonl", live=live if live.is_file() else None, **kw))
    ids = []
    for t in todo:
        if not t.get("need_report"):
            continue
        rec = rep(run=run, episode=ep, step=str(t.get("step") or "复盘"), who="RETRO", blocking=False,
                  what=f"{followup_tag(t['id'])} 第{ep}集卡点已关但修法没进 SOP / 代码：{str(t.get('what') or '')[:120]}",
                  fix_hint=f"第{ep + 1}集开工前：把“{str(t.get('fix_hint') or '')[:120]}”写进 PIPELINE_SOP_V2.md 对应步骤（report_issue close "
                           f"{t['id']} --sop-updated yes）或做成带卡点号的代码 / 检查")
        t["followed"], t["need_report"] = True, False
        ids.append(rec.get("id"))
    return ids


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def memory_candidates(cur: dict | None, prev: dict | None, rows: list[dict], todo: list[dict], ep: int) -> list[str]:
    """3–6 条一句话事实（给总调度写 memory；这里不写记忆文件）"""
    h = (cur or {}).get("headline") or {}
    out = []
    if h:
        out.append(f"第{ep}集 §1.3 头条：自动化率 {h.get('automation_ratio')}、人工介入 {h.get('interventions')} 次、GPU 占用 {h.get('gpu_util')}、"
                   f"好莱坞中位 {h.get('hollywood_median')}。")
    if prev and h:
        EM_rows = [r for r in _cmp_rows(prev, cur) if r["verdict"] == "worse"]
        out.append(f"第{ep}集对第{ep - 1}集退步：{'、'.join(r['label'] for r in EM_rows)}。" if EM_rows else f"第{ep}集对第{ep - 1}集头条无退步项。")
    if rows:
        by_step: dict[str, int] = {}
        for r in rows:
            by_step[str(r.get("step") or "?")] = by_step.get(str(r.get("step") or "?"), 0) + 1
        top = sorted(by_step.items(), key=lambda x: -x[1])[:2]
        out.append(f"第{ep}集卡点 {len(rows)} 条，最集中的步骤：" + "、".join(f"{k}（{v}）" for k, v in top) + "。")
    if todo:
        out.append(f"第{ep}集有 {len(todo)} 条卡点修法还没进 SOP / 代码，是第{ep + 1}集开工前的必做项。")
    det = h.get("interventions_detail") or {}
    if det.get("owner_decisions"):
        out.append(f"第{ep}集项目方 / 人工决策 {det['owner_decisions']} 条（owner_queue/decisions.jsonl），总调度 producer 手动事件 {det.get('producer_manual_events', 0)} 条。")
    if _num(h.get("one_pass_first")) is not None and h["one_pass_first"] < 0.6:
        out.append(f"第{ep}集首帧一次过率只有 {h['one_pass_first']}，返工主要在首帧。")
    while len(out) < 3:
        out.append(f"第{ep}集复盘由常驻 retro_tick 自动生成（W24），数据源缺的项见指标 nulls[]。")
    return out[:6]


def _cmp_rows(prev, cur):
    EM = _load("episode_metrics_retro", "tools/master/episode_metrics.py")
    return EM.compare_headline(prev, cur)


def harness_suggestions(cur: dict | None, todo: list[dict]) -> list[str]:
    """阈值 / 规则文件 + 建议值（只建议，不自动改规则）"""
    h = (cur or {}).get("headline") or {}
    out = []
    g = _num(h.get("gpu_util"))
    if g is not None and g < 0.4:
        out.append(f"`config/netfix/partition.json` lanes：GPU 占用 {g} < 0.4（§1.3）→ 建议本集出图分区多挂 1–2 条道，或 `config/pipeline/hollywood_score.json` "
                   "max_per_tick 1→2 把空闲道用上")
    a = _num(h.get("automation_ratio"))
    if a is not None and a < 0.6:
        out.append(f"`config/pipeline/sop_gate.json` promote.auto / lifecycle.apply：自动化率 {a} < 0.6 → 建议 lifecycle.apply=true（producer 起停不靠人）")
    n = _num(h.get("interventions"))
    if n is not None and n > 20:
        out.append(f"`config/policies/retry.yaml` hard_cap.value.per_stage_24h：人工介入 {n} > 20 → 看 uncap/approve 是否集中在少数镜，集中就把上限按镜放宽 2")
    f1 = _num(h.get("one_pass_first"))
    if f1 is not None and f1 < 0.6:
        out.append(f"`config/policies/gates.yaml`：首帧一次过率 {f1} < 0.6 → 看本集首帧不过的契约项，把最常挂的一项前移进 preflight（编译期拦）")
    if todo:
        out.append(f"`docs/master/PIPELINE_SOP_V2.md`：{len(todo)} 条卡点修法没进 SOP → 逐条写进对应步骤“卡过的地方”")
    if (h.get("hollywood_n") or 0) == 0:
        out.append("`config/pipeline/hollywood_score.json` require_idle：本集没有好莱坞分 → 建议给 hollywood_tick 每集预留至少一段空闲窗，或 require_idle=false 跑一轮补分")
    return out or ["本集头条都达标，暂不建议改阈值。"]


def event_sig(root: Path, run: str, ep: int, rows: list[dict]) -> str:
    """本集“事件”指纹：卡点状态 + producer 本集日志行 + 项目方决策 + 好莱坞分 + 整集预览片。不变 = 没有新事件，常驻不重写"""
    import hashlib
    tag = f"ep{ep:02d}"
    h = hashlib.sha1()
    for r in rows:
        h.update(f"{r['id']}|{r['status']}|{r.get('sop_updated')}\n".encode())
    for rel in (f"data/producer/runs/{run}/log.jsonl", "data/owner_queue/decisions.jsonl"):
        p = root / rel
        n = sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if tag in ln) if p.is_file() else 0
        h.update(f"{rel}:{n}\n".encode())
    hw = root / f"data/pipeline/runs/{run}/metrics/hollywood_{tag}.jsonl"
    h.update(f"hw:{len(hw.read_text(encoding='utf-8', errors='replace').splitlines()) if hw.is_file() else 0}\n".encode())
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    h.update(f"pv:{SG.check_preview(root, run, ep).get('why')}".encode())
    return h.hexdigest()[:16]


def _file_sig(p: Path) -> str | None:
    m = re.search(r"retro_sig:\s*(\w+)", p.read_text(encoding="utf-8")) if p.is_file() else None
    return m.group(1) if m else None


def generate(run: str, ep: int, root: Path = ROOT, force: bool = False, collect=None, dry: bool = False,
             only_if_changed: bool = False, register: bool = False, reporter=None, refresh_auto_done: bool = False) -> tuple[bool, str]:
    """dry = 不写任何文件（RETRO / summary / 卡点），返回 RETRO 正文；only_if_changed = 已有文件且事件指纹没变就不重写（常驻用）；
    register = 已关没沉淀的卡点登记跟进项；refresh_auto_done = 常驻自动 done 的（done_by: retro_auto）允许按新事件刷新"""
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    p = SG.retro_path(run, ep, root)
    state = SG.retro_state(run, ep, root)
    auto_done = state == "done" and p.is_file() and "done_by: retro_auto" in p.read_text(encoding="utf-8")
    if state == "done" and not force and not dry and not (refresh_auto_done and auto_done):
        return False, f"{p.name} 已 done，不覆盖（要重开加 --force）"
    rows = issue_rows(root, run, ep)
    sig = event_sig(root, run, ep, rows)
    if only_if_changed and not force and _file_sig(p) == sig:
        return False, f"{p.name} 没有新事件（retro_sig {sig}），不重写"
    old = _old_checked(p)
    mlines, cur = metrics_section(root, run, ep, collect, write=not dry)
    prev = None
    if ep > 1 and cur and collect is None:
        EM = _load("episode_metrics_retro", "tools/master/episode_metrics.py", root)
        prev = EM.jload(EM.Paths(root, run).summary(ep - 1))
        if prev is not None and "headline" not in prev:
            prev["headline"] = EM.headline(root, run, ep - 1)
    all_issues = _load("report_issue_retro", "tools/master/report_issue.py", root).load(root / "data/pipeline/issues.jsonl")
    todo = followups(rows, all_issues)
    new_ids = register_followups(root, run, ep, todo, reporter) if register and not dry else []
    stage = next((r for r in SG.status(run, root) if r["episode"] == ep), None)
    status_line = "<!-- retro_status: done --> <!-- done_by: retro_auto -->" if auto_done and refresh_auto_done else "<!-- retro_status: draft -->"
    body = [f"# 第 {ep} 集复盘（{run}）", "", status_line, f"<!-- retro_sig: {sig} -->",
            f"> 生成：{time.strftime('%Y-%m-%d %H:%M')}，tools/master/episode_retro.py。总调度勾完第 4 节后跑 "
            f"`episode_retro.py done --run {run} --episode {ep}`；没 done 之前第 {ep + 1} 集不能进“出图”（sop_gate）。",
            f"> 本集当前 SOP 阶段：{stage['stage'] + '（' + stage['why'][:120] + '）' if stage else '—'}", "",
            "## 1. 指标（和上一集对比）", "", *mlines, "",
            "## 2. 本集卡点：怎么修、是否写进 SOP 和代码", "", *issues_section(rows), "",
            "### 下一集前必做（修法没进 SOP / 代码的卡点）", "", *followups_section(todo, ep),
            *([f"", f"本次登记跟进：{'、'.join(new_ids)}"] if new_ids else []), "",
            "## 3. 本集新增 / 改动的规则（config、knowledge、SOP）", "", *rules_section(root, run, ep), "",
            "## 4. 记忆 / harness 更新清单（总调度勾选）", "", *checklist(rows, old), "",
            "## 5. 记忆候选（给总调度写 memory；这里不写记忆文件）", "", *[f"- {m}" for m in memory_candidates(cur, prev, rows, todo, ep)], "",
            "## 6. harness 变更建议（阈值 / 规则文件 + 建议值；不自动改）", "", *[f"- {x}" for x in harness_suggestions(cur, todo)], ""]
    text = "\n".join(body)
    if dry:
        return True, text
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return True, str(p)


def auto_done(run: str, ep: int, root: Path = ROOT) -> tuple[bool, str]:
    """常驻自动落 done（W24，config/pipeline/sop_gate.json retro_auto_done，默认 true）：整集预览已出 + 复盘已生成 + 指标算得出
    + 没沉淀的已关卡点都登记了跟进（下一集前必做在册）→ 写 `retro_status: done` + `done_by: retro_auto`（sop_gate.retro_state 同口径读）。
    第 4 节清单留给总调度异步勾；总调度手工 done（episode_retro.py done）的文件常驻不再碰"""
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    p = SG.retro_path(run, ep, root)
    if SG.retro_state(run, ep, root) == "done":
        return False, f"{p.name} 已 done"
    if not SG.check_preview(root, run, ep)["ok"]:
        return False, "整集预览还没出"
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    if not text or "指标算不出" in text or "待登记跟进" in text:
        return False, "复盘没生成 / 指标算不出 / 还有没登记的跟进项"
    text = text.replace("<!-- retro_status: draft -->", f"<!-- retro_status: done --> <!-- done_by: retro_auto --> <!-- done_at: {time.strftime('%Y-%m-%dT%H:%M')} -->", 1)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return True, f"{p.name} 自动 done：第 {ep + 1} 集可以进“出图”"


def auto(run: str, ep: int, root: Path = ROOT, reporter=None) -> dict:
    """一集的自动复盘：整集预览在 → 生成 / 刷新（没新事件不重写）+ 登记跟进 + 按配置自动 done"""
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    if not SG.check_preview(root, run, ep)["ok"]:
        return {"episode": ep, "skip": "整集预览还没出"}
    wrote, msg = generate(run, ep, root, only_if_changed=True, register=True, reporter=reporter, refresh_auto_done=True)
    out = {"episode": ep, "wrote": wrote, "msg": msg}
    if SG.config(root).get("retro_auto_done", True):
        out["done"] = auto_done(run, ep, root)[1]
    return out


def tick(runs: list[str] | None = None, root: Path = ROOT, reporter=None) -> dict:
    """常驻一拍（autoflow_resident.retro_tick 调）：每部剧每集走一遍 auto；只有整集预览已出的集会动"""
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    if runs is None:
        runs = [SG._registry(root).get("primary")]
    res = []
    for run in [r for r in runs if r]:
        if SG.is_legacy(run, root):
            continue
        for ep in SG.episodes_of(run, root):
            r = auto(run, ep, root, reporter)
            if "skip" not in r:
                res.append({"run": run, **r})
    return {"retro": res}


def mark_done(run: str, ep: int, root: Path = ROOT) -> tuple[bool, str]:
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    p = SG.retro_path(run, ep, root)
    if not p.is_file():
        return False, f"没有 {p.name}，先生成"
    text = p.read_text(encoding="utf-8")
    left = re.findall(r"^- \[ \] (.+)$", text, re.M)
    if left:
        return False, f"还有 {len(left)} 项没勾：\n  " + "\n  ".join(left[:10])
    text = re.sub(r"retro_status:\s*\w+", "retro_status: done", text, count=1)
    text = text.replace("<!-- retro_status: done -->", f"<!-- retro_status: done --> <!-- done_at: {time.strftime('%Y-%m-%dT%H:%M')} -->", 1)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return True, f"{p.name} 已标 done：第 {ep + 1} 集可以进“出图”"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="gen", choices=["gen", "done"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--force", action="store_true", help="重开已 done 的复盘（回到 draft）")
    ap.add_argument("--dry", action="store_true", help="只把复盘正文打到屏幕：不写 RETRO / summary / 卡点")
    ap.add_argument("--auto", action="store_true", help="走常驻同一条路：整集预览在才生成，没新事件不重写，登记跟进，按配置自动 done")
    a = ap.parse_args(argv)
    if a.cmd == "gen" and a.auto:
        print(json.dumps(auto(a.run, a.episode), ensure_ascii=False, indent=1))
        return 0
    ok, msg = (generate(a.run, a.episode, force=a.force, dry=a.dry) if a.cmd == "gen" else mark_done(a.run, a.episode))
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
