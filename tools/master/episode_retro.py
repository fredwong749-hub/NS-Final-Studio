"""集复盘门（HARNESS-O 11-03，项目方：每一集都是一次系统迭代）。

    .venv/Scripts/python.exe tools/master/episode_retro.py --run series10_v2 --episode 1          # 生成 / 刷新 docs/master/RETRO_ep01.md
    .venv/Scripts/python.exe tools/master/episode_retro.py done --run series10_v2 --episode 1     # 总调度勾完清单后标 done

内容（全部复用现有部件）：
  ① 本集指标 + 和上一集对比    ← tools/master/episode_metrics.collect / compare（本集 summary 同时落盘，和 episode_metrics calc 同一份）
  ② 本集卡点：怎么修、修完是否写进 SOP（report_issue close --sop-updated）和代码（仓库里 grep 得到卡点号）
  ③ 本集新增 / 改动的规则    ← git：本集开工以来 config/、knowledge/、docs/master/PIPELINE_SOP_V2.md 的提交 + 未提交改动
  ④ 记忆 / harness 更新清单（总调度勾选；- [x] 才算）
闸门：tools/master/sop_gate.py —— 第 N+1 集进“出图”要第 N 集复盘 done（文件里 `retro_status: done`）。
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
def metrics_section(root: Path, run: str, ep: int, collect=None) -> tuple[list[str], dict | None]:
    EM = _load("episode_metrics_retro", "tools/master/episode_metrics.py", root)
    get = collect or (lambda e: EM.collect(root, run, e))
    try:
        cur = get(ep)
    except Exception as e:  # noqa: BLE001  指标算不出如实写，不挡复盘生成
        return [f"指标算不出：{e!r}"[:200]], None
    if collect is None:
        EM.write_summary(root, run, ep, cur, html=False)
    lines = ["```", EM.brief(cur), "```"]
    if ep > 1:
        prev = EM.jload(EM.Paths(root, run).summary(ep - 1)) if collect is None else None
        try:
            prev = prev or get(ep - 1)
        except Exception as e:  # noqa: BLE001
            prev = None
            lines.append(f"上一集指标算不出：{e!r}"[:200])
        if prev:
            rows = EM.compare(prev, cur)
            lines += ["", f"| 指标 | 第{ep - 1}集 | 第{ep}集 | 变化 |", "|---|---|---|---|"]
            mark = {"better": "✅ 变好", "worse": "❌ 变差", "same": "持平", "info": "—", "n/a": "—"}
            lines += [f"| {r['label']} | {EM._fmt(r['a']) if r['a'] is not None else '—'} | {EM._fmt(r['b']) if r['b'] is not None else '—'} | {mark.get(r['verdict'], r['verdict'])} |"
                      for r in rows]
    else:
        lines.append("（第 1 集，没有上一集可比）")
    return lines, cur


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


def generate(run: str, ep: int, root: Path = ROOT, force: bool = False, collect=None) -> tuple[bool, str]:
    SG = _load("sop_gate_retro", "tools/master/sop_gate.py", root)
    p = SG.retro_path(run, ep, root)
    if SG.retro_state(run, ep, root) == "done" and not force:
        return False, f"{p.name} 已 done，不覆盖（要重开加 --force）"
    old = _old_checked(p)
    mlines, _cur = metrics_section(root, run, ep, collect)
    rows = issue_rows(root, run, ep)
    stage = next((r for r in SG.status(run, root) if r["episode"] == ep), None)
    body = [f"# 第 {ep} 集复盘（{run}）", "", "<!-- retro_status: draft -->",
            f"> 生成：{time.strftime('%Y-%m-%d %H:%M')}，tools/master/episode_retro.py。总调度勾完第 4 节后跑 "
            f"`episode_retro.py done --run {run} --episode {ep}`；没 done 之前第 {ep + 1} 集不能进“出图”（sop_gate）。",
            f"> 本集当前 SOP 阶段：{stage['stage'] + '（' + stage['why'][:120] + '）' if stage else '—'}", "",
            "## 1. 指标（和上一集对比）", "", *mlines, "",
            "## 2. 本集卡点：怎么修、是否写进 SOP 和代码", "", *issues_section(rows), "",
            "## 3. 本集新增 / 改动的规则（config、knowledge、SOP）", "", *rules_section(root, run, ep), "",
            "## 4. 记忆 / harness 更新清单（总调度勾选）", "", *checklist(rows, old), ""]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(body), encoding="utf-8")
    tmp.replace(p)
    return True, str(p)


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
    a = ap.parse_args(argv)
    ok, msg = (generate(a.run, a.episode, force=a.force) if a.cmd == "gen" else mark_done(a.run, a.episode))
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
