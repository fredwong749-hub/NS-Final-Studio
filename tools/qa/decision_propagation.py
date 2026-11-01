"""决策全量同步检查（K-OPS-D02 的 check；项目方 11-01 §G0：“一旦决定了,其它sub-tasks related都要改一下”）。

config/owner_decisions.yaml 的 checks 条目上可加三个字段（decision_check.py 不读它们，互不影响）：
  stale_terms: [正则…]   过期口径。扫描 docs/ knowledge/ config/（含各 STATE.md）里还在用、又没标 ⤴ 的行
  new_terms:   [正则…]   新口径。propagate 里的文件必须至少出现一次
  propagate:   [文件…]   必须同步到新决定的文件（缺新口径 = 没同步；有未标 ⤴ 的过期口径 = 没同步）
  stale_allow: [glob…]   这条决定额外放过的文件（例：记录这条决定本身的规则）

“已标 ⤴”= 该行含 ⤴，或该行所在的 Markdown 小节标题含 ⤴，或 YAML / JSON 里该行的键名以 _ 开头且同行写了“取代 / 已撤 / ⤴”。
历史记录不扫：research/、_archive、archive、CHANGELOG、RSI_LEDGER、rounds/、overnight/、patches/、*_log.md、文件名带 8 位日期、
knowledge/generated（compile 生成物）、docs/master/owner_messages_extracted.md、config/owner_decisions.yaml 本身。

    .venv/Scripts/python.exe tools/qa/decision_propagation.py            # 报告 → data/qa/decision_propagation/report.md / .json
    .venv/Scripts/python.exe tools/qa/decision_propagation.py --only D-VID-01
退出码：有未同步 = 1，全同步 = 0。每条命中带文件 owner（tools/qa/ownership.yaml），用来分派“谁去改”。只读，不改被扫描的文件。
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DECISIONS = ROOT / "config" / "owner_decisions.yaml"
OUT = ROOT / "data" / "qa" / "decision_propagation"
SCAN_DIRS = ("docs", "knowledge", "config")
EXTS = {".md", ".yaml", ".yml", ".json", ".txt"}
EXCLUDE = re.compile(r"(^|/)(research|_archive|archive|rounds|overnight|patches|generated|_quarantine[^/]*)(/|$)|CHANGELOG|RSI_LEDGER|"
                     r"_log\.md$|\d{8}|owner_messages_extracted|owner_decisions\.yaml$", re.I)
MARK = "⤴"
MAX_BYTES = 2_000_000


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def scan_files(root: Path = ROOT) -> list[Path]:
    out = []
    for d in SCAN_DIRS:
        for p in (root / d).rglob("*"):
            if p.is_file() and p.suffix.lower() in EXTS and p.stat().st_size <= MAX_BYTES:
                r = p.relative_to(root).as_posix()
                if not EXCLUDE.search(r):
                    out.append(p)
    return sorted(out)


def marked_lines(text: str, suffix: str) -> set[int]:
    """已标 ⤴ 的行号（1 起）：本行含 ⤴；Markdown 小节标题含 ⤴ 时整节；YAML / JSON 的 _ 开头注释键写了取代"""
    ok, in_marked, level = set(), False, 0
    for n, line in enumerate(text.splitlines(), 1):
        if suffix == ".md":
            m = re.match(r"^(#{1,6})\s", line)
            if m:
                lv = len(m.group(1))
                if MARK in line:
                    in_marked, level = True, lv
                elif in_marked and lv <= level:
                    in_marked = False
        if MARK in line or in_marked:
            ok.add(n)
        elif suffix in (".yaml", ".yml", ".json") and re.match(r'^\s*"?_\w*"?\s*:', line) and re.search(r"取代|已撤|⤴", line):
            ok.add(n)
    return ok


def find_stale(text: str, suffix: str, terms: list[re.Pattern]) -> list[tuple[int, str]]:
    ok = marked_lines(text, suffix)
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if n in ok:
            continue
        for t in terms:
            m = t.search(line)
            if m:
                hits.append((n, line.strip()[:160]))
                break
    return hits


_OWN: dict = {}


def _owner(path: str) -> str:
    try:
        sys.path.insert(0, str(ROOT / "tools" / "qa"))
        import iter_gate as G  # noqa: PLC0415
        if "own" not in _OWN:
            _OWN["own"] = G.load_own()
        o, via = G.owner_of(path, _OWN["own"])
        return o or (f"共享（{via[:20]}）" if via else "未指派")
    except Exception:  # noqa: BLE001
        return "未知"


GENERATED_RE = re.compile(r"自动写|自动生成|勿手改|auto-?generated|do not edit", re.I)


def is_generated(p: Path) -> bool:
    """K-OPS-D04：文件头 3 行写着“自动写 / 自动生成 / 勿手改 / auto-generated”= 程序生成物，不能当同步对象（同步它的生成程序）"""
    try:
        head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:3])
    except OSError:
        return False
    return bool(GENERATED_RE.search(head))


def check_decision(c: dict, files: list[Path], root: Path = ROOT) -> dict:
    terms = [re.compile(t, re.I) for t in c.get("stale_terms") or []]
    new = [re.compile(t, re.I) for t in c.get("new_terms") or []]
    allow = c.get("stale_allow") or []
    stale, unsynced = [], []
    for p in files:
        r = p.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(r, g) for g in allow):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in find_stale(text, p.suffix.lower(), terms) if terms else []:
            stale.append({"file": r, "line": n, "text": line})
    for f in c.get("propagate") or []:
        p = root / f
        if not p.exists():
            unsynced.append({"file": f, "why": "文件不存在"})
            continue
        if is_generated(p):
            unsynced.append({"file": f, "why": "配置错误：这是程序自动生成的文件，改同步它的生成程序（K-OPS-D04）"})
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if new and not any(t.search(text) for t in new):
            unsynced.append({"file": f, "why": "没有新口径（" + " / ".join(t.pattern for t in new)[:60] + "）"})
    files_hit = sorted({x["file"] for x in stale} | {x["file"] for x in unsynced})
    unowned = [f for f in files_hit if _owner(f) in ("未指派", "未知")] if root == ROOT else []
    return {"id": c["id"], "title": c.get("title", ""), "decision": c.get("decision", ""), "stale": stale, "unsynced": unsynced,
            "unowned": unowned}


def run(only: set[str] | None = None, root: Path = ROOT, decisions: Path = DECISIONS) -> list[dict]:
    cfg = yaml.safe_load(decisions.read_text(encoding="utf-8")) or {}
    cs = [c for c in cfg.get("checks") or [] if (c.get("stale_terms") or c.get("propagate")) and (not only or c["id"] in only)]
    files = scan_files(root)
    return [check_decision(c, files, root) for c in cs]


def report(res: list[dict], owners: bool = True) -> str:
    md = [f"# 决策全量同步检查（K-OPS-D02）· {time.strftime('%Y-%m-%d %H:%M')}", "",
          "`tools/qa/decision_propagation.py`；过期口径 = config/owner_decisions.yaml 的 stale_terms；已标 ⤴ 的行不算。", ""]
    for r in res:
        bad = len(r["stale"]) + len(r["unsynced"])
        md += [f"## {r['id']} {'✅ 已全量同步' if not bad else f'❌ {bad} 处没同步'}：{r['title']}", "", f"决定：{r['decision']}", ""]
        if r.get("unowned"):
            md += ["**没有 owner 的文件（K-OPS-D03：没人负责就永远同步不完，请总调度在 tools/qa/ownership.yaml 指派）**：", ""]
            md += [f"- `{f}`" for f in r["unowned"]] + [""]
        if r["unsynced"]:
            md += ["必须同步的文件还没跟上：", ""] + [f"- `{u['file']}`（{_owner(u['file']) if owners else ''}）：{u['why']}" for u in r["unsynced"]] + [""]
        if r["stale"]:
            md += ["| 文件 | 行 | owner | 内容 |", "|---|---|---|---|"]
            md += [f"| `{s['file']}` | {s['line']} | {_owner(s['file']) if owners else ''} | {s['text'].replace('|', '／')} |" for s in r["stale"]]
            md.append("")
    return "\n".join(md)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="K-OPS-D02 决策全量同步检查")
    ap.add_argument("--only")
    ap.add_argument("--dry", action="store_true", help="不写 data/qa/decision_propagation")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    res = run(set(a.only.split(",")) if a.only else None)
    text = report(res)
    if not a.dry:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "report.md").write_text(text, encoding="utf-8")
        (OUT / "report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    return 1 if any(r["stale"] or r["unsynced"] or r.get("unowned") for r in res) else 0


def summary(res: list[dict]) -> str:
    """一行汇总（decision_check 末尾打印）"""
    parts = [f"{r['id']} {'✅' if not (r['stale'] or r['unsynced']) else '❌ ' + str(len(r['stale']) + len(r['unsynced']))}"
             + (f"（无 owner {len(r['unowned'])}）" if r.get("unowned") else "") for r in res]
    return "决策全量同步（K-OPS-D02，tools/qa/decision_propagation.py）：" + ("；".join(parts) or "没有登记 stale_terms / propagate 的决定")


if __name__ == "__main__":
    sys.exit(main())
