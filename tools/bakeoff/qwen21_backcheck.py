"""BAKEOFF（R11-12）：Qwen Image 2.1 提示词回查——当前 series10 首帧提示词（frame_job 统一路径编译结果）+ 真实坏例。

  bad     收集坏例：画布 takes 里被总调度驳回（master_reject）或契约 postflight 不过的首帧 / 尾帧版本
          → data/ab/qwen21/bad_takes.json
  lint    用 qwen21_lint.py 的规则扫当前作业（data/pipeline/runs/series10_v1/assets/first_frame_jobs.json）和坏例的提示词
          → data/ab/qwen21/lint_report.json + docs/qwen21/BACKCHECK.md
只读：不改作业、不改 takes、不改剧本。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/ab/qwen21"
JOBS = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"


def bad():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted((ROOT / "data/renders").glob("ep*/S*/takes.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        takes = d.get("takes") if isinstance(d, dict) else d
        shot = f"{f.parent.parent.name}-{f.parent.name}"
        for t in takes or []:
            if t.get("stage") not in ("image", "last_frame", "last"):
                continue
            pf = t.get("postflight") or {}
            mr = t.get("master_reject")
            fails = [{"id": x["id"], "detail": x.get("detail", "")} for x in pf.get("items", []) if x.get("status") == "fail"]
            if not (mr or (pf.get("ok") is False and fails)) or not t.get("prompt"):
                continue
            rows.append({"shot": shot, "n": t["n"], "stage": t["stage"], "file": t.get("file"), "prompt": t["prompt"],
                         "master_reject": (mr or {}).get("reason"), "fails": fails,
                         "workflow": t.get("workflow"), "created_at": t.get("created_at")})
    (OUT / "bad_takes.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    c = Counter(x["id"] for r in rows for x in r["fails"])
    print(len(rows), "坏例；总调度驳回", sum(1 for r in rows if r["master_reject"]), "；契约不过项", dict(c))


def lint():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import qwen21_lint as QL
    jobs = json.loads(JOBS.read_text(encoding="utf-8"))["jobs"]
    badp = OUT / "bad_takes.json"
    bads = json.loads(badp.read_text(encoding="utf-8")) if badp.exists() else []
    rep = {"jobs": {}, "bad": {}}
    hit_jobs, hit_bad = Counter(), Counter()
    for j in jobs:
        r = QL.lint(j["prompt"], size=j.get("size"), on_screen=j.get("on_screen"))
        rep["jobs"][j["shot"]] = r
        hit_jobs.update({x["id"] for x in r})
    for b in bads:
        r = QL.lint(b["prompt"])
        rep["bad"][f"{b['shot']}#{b['n']}"] = r
        hit_bad.update({x["id"] for x in r})
    (OUT / "lint_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    # 坏例里每条规则的命中率 vs 当前作业里的命中率
    lines = ["# 回查：series10 首帧提示词 × Qwen 2.1 写法规则（tools/bakeoff/qwen21_backcheck.py 生成）", "",
             f"当前作业 {len(jobs)} 条（{JOBS.relative_to(ROOT).as_posix()}）；坏例 {len(bads)} 条（data/ab/qwen21/bad_takes.json）。", "",
             "| 规则 | 说明 | 当前作业命中 | 坏例命中 |", "|---|---|---|---|"]
    for rid, desc in QL.RULES.items():
        lines.append(f"| {rid} | {desc} | {hit_jobs.get(rid, 0)}/{len(jobs)} | {hit_bad.get(rid, 0)}/{len(bads)} |")
    by_rule = defaultdict(list)
    for sid, r in rep["jobs"].items():
        for x in r:
            by_rule[x["id"]].append(f"{sid}：{x['evidence']}")
    lines += ["", "## 当前作业命中明细（每条规则最多 6 例）", ""]
    for rid, ex in by_rule.items():
        lines.append(f"- **{rid}**：" + "；".join(ex[:6]))
    (ROOT / "docs/qwen21/BACKCHECK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("jobs", dict(hit_jobs)); print("bad", dict(hit_bad))


# 规则 → 它预计会导致的契约不过项（用来看“命中这条的版本是不是更容易在这一项不过”）
LINK = {"QL01": ["Q3", "Q2"], "QL02": ["Q3", "Q1"], "QL03": ["Q2"], "QL04": ["Q4"], "QL05": ["Q6"], "QL06": ["Q1"],
        "QL08": ["Q7"], "QL09": ["Q7"], "QL10": ["Q4"]}


def assoc():
    """全部有契约结果的首帧 / 尾帧版本：命中某规则 vs 没命中时，对应契约项的不过率（相关，不是因果；因果要 GPU A/B）"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import qwen21_lint as QL
    rows = []
    for f in sorted((ROOT / "data/renders").glob("ep*/S*/takes.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for t in (d.get("takes") if isinstance(d, dict) else d) or []:
            pf = t.get("postflight") or {}
            if t.get("stage") not in ("image", "last_frame", "last") or not t.get("prompt") or pf.get("ok") is None:
                continue
            st = {x["id"]: x.get("status") for x in pf.get("items", [])}
            rows.append(({x["id"] for x in QL.lint(t["prompt"])}, st, bool(t.get("master_reject"))))
    out = {"n": len(rows), "rules": {}}
    lines = ["", "## 命中规则 vs 契约不过率（全部有契约结果的版本；相关不是因果，因果靠 GPU A/B）", "",
             f"样本：{len(rows)} 个版本（data/renders/ep*/S*/takes.json）。", "",
             "| 规则 | 对应契约项 | 命中：不过 / 测过 | 未命中：不过 / 测过 |", "|---|---|---|---|"]
    for rid, qs in LINK.items():
        for q in qs:
            a = [st.get(q) for hit, st, _ in rows if rid in hit and st.get(q) in ("pass", "fail")]
            b = [st.get(q) for hit, st, _ in rows if rid not in hit and st.get(q) in ("pass", "fail")]
            fa, fb = sum(x == "fail" for x in a), sum(x == "fail" for x in b)
            out["rules"][f"{rid}:{q}"] = {"hit": [fa, len(a)], "miss": [fb, len(b)]}
            pa = f"{fa}/{len(a)}（{fa / len(a):.0%}）" if a else "—"
            pb = f"{fb}/{len(b)}（{fb / len(b):.0%}）" if b else "—"
            lines.append(f"| {rid} | {q} | {pa} | {pb} |")
    (OUT / "assoc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    bc = ROOT / "docs/qwen21/BACKCHECK.md"
    txt = bc.read_text(encoding="utf-8") if bc.exists() else ""
    txt = txt.split("\n## 命中规则 vs 契约不过率")[0].rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    bc.write_text(txt, encoding="utf-8")
    print("\n".join(lines))


PATTERNS = [  # 坏例分类：(标题, 规则, 选择条件)
    ("景别被撑大：特写 / 近景里要求裙、裤、鞋入画", "QL01", lambda b, h: "QL01" in h and any(f["id"] == "Q3" for f in b["fails"])),
    ("局部特写出成带脸的中近景", "QL02", lambda b, h: "QL02" in h or "局部" in (b["master_reject"] or "") or "大特写" in (b["master_reject"] or "")),
    ("两人同框又写一人前景虚化 / 背影：多出一张认不出的脸", "QL06", lambda b, h: "QL06" in h and any(f["id"] == "Q1" for f in b["fails"])),
    ("否定句把被否定的东西带进画面（“不是长裤”出长裤）", "QL03", lambda b, h: "QL03" in h and ("长裤" in (b["master_reject"] or "") or any("没穿" in f["detail"] or "下装" in f["detail"] for f in b["fails"]))),
    ("塑料脸 / 娃娃脸特写（总调度亲审）", "QL10", lambda b, h: "塑料" in (b["master_reject"] or "")),
    ("服装漏件：短款西装外套没穿", "—", lambda b, h: "外套" in (b["master_reject"] or "") or any("外套" in f["detail"] for f in b["fails"])),
]


def gallery():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import qwen21_lint as QL
    bads = json.loads((OUT / "bad_takes.json").read_text(encoding="utf-8"))
    lines = ["# Qwen Image 2.1 出图坏例库（R11-12；tools/bakeoff/qwen21_backcheck.py gallery 生成）", "",
             "每类坏例：现象 → 提示词里的结构问题（lint 规则 QL*，tools/bakeoff/qwen21_lint.py）→ 归谁改 → 真实版本（图、契约不过项 / 总调度驳回原因）。",
             "规则与证据见 knowledge/rules/render_qwen21.yaml；命中率与不过率的对照见 docs/qwen21/BACKCHECK.md。", ""]
    for title, rid, cond in PATTERNS:
        sel = []
        for b in bads:
            h = {x["id"] for x in QL.lint(b["prompt"])}
            if cond(b, h):
                sel.append((b, h))
        lines += [f"## {title}（{rid}，{len(sel)} 例）", ""]
        for b, h in sel[:4]:
            why = b["master_reject"] or "；".join(f"{f['id']} {f['detail'][:60]}" for f in b["fails"][:2])
            ev = next((x["evidence"] for x in QL.lint(b["prompt"]) if x["id"] == rid), "")
            img = "../../data/" + (b["file"] or "").replace(chr(92), "/")
            lines += [f"- **{b['shot']} #{b['n']}（{b['stage']}）**：{why}",
                      f"  - 图：[{b['file']}]({img})；命中：{', '.join(sorted(h))}" + (f"；证据：{ev}" if ev else ""),
                      f"  - 提示词节选：{b['prompt'][:160]}…"]
        lines.append("")
    (ROOT / "docs/qwen21/BAD_CASES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("gallery ok")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    {"bad": bad, "lint": lint, "assoc": assoc, "gallery": gallery}[sys.argv[1]]()
