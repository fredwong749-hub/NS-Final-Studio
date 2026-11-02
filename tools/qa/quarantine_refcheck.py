"""隔离前引用检查（K-OPS-Q30 的 check；CLEANUP 2026-11-01，项目方 18:3x：“把旧的东西全部移出”）。

规则：任何文件 / 目录移进隔离区之前，先查生产代码、测试、API、前端、配置、运维脚本有没有读它。
有引用 = 不移（写进报告交总调度），没有引用才移。本脚本只读，不移动任何东西。

    .venv/Scripts/python.exe -X utf8 tools/qa/quarantine_refcheck.py PATH [PATH ...]
    .venv/Scripts/python.exe -X utf8 tools/qa/quarantine_refcheck.py --plan PLAN.json   # [{"src": ...}, ...]
退出码：0 = 全部无引用；1 = 至少一项有引用。

检索词：相对项目根的路径（/ 和 \\ 两种写法）、“父目录/名字”、以及足够独特的名字本身（≥6 个字符、不在通用词表里）。
检索范围 CODE_DIRS（生产代码 + 测试 + 前端 + 配置 + 运维）+ EVIDENCE_DIRS（知识库规则证据链 / RSI 账本，compile 校验证据存在）；
其余 docs/ 的命中只作提示（文档引用不算生产读取）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = ("services", "packages", "tools", "tests", "apps/web/src", "apps/web/e2e", "apps/web/scripts", "config", "ops", "infra",
             "comfy", "templates", "pyproject.toml")
DOC_DIRS = ("docs", "knowledge/inbox", "knowledge/prompts")
# 知识库规则的证据链和 RSI 账本不是“旧”：它们引用的文件算读取者（compile.py --check 校验证据文件存在）
EVIDENCE_DIRS = ("knowledge/rules", "knowledge/RSI_LEDGER.md", "knowledge/archive")
# 隔离工具自己、删除脚本、生成物不算“读取”
SELF_GLOBS = ("!tools/qa/quarantine_*", "!ops/cleanup/**", "!**/__pycache__/**", "!**/node_modules/**", "!**/*.pyc", "!**/dist/**",
              "!knowledge/generated/**", "!**/*.orig_*",
              # 日志和 e2e 扫描输出是“记录”，不是读取者
              "!**/*.log", "!ops/logs/**", "!apps/web/e2e/**/*.json", "!apps/web/e2e/**/*.html", "!apps/web/e2e/**/*.md")
GENERIC = {"data", "assets", "config", "tests", "tools", "archive", "_archive", "backup", "_backup", "backups", "review", "report",
           "README", "STATE", "index", "manifest", "MANIFEST", "images", "frames", "videos", "audio", "output", "outputs", "series10",
           "render", "renders", "scenes", "voice", "voices", "music", "episodes", "pipeline", "staging", "merged", "repair", "replies",
           "gpu33", "gpu36", "report.json", "manifest.json", "_work.md", "STATE.md", "README.md"}


# ISS-1103-033325-9b07（SYSAUDIT-F 11-03）：阶段 B 执行器 tools/pipeline/golden_worker.py 和 tests/test_golden_pipeline.py 被当“内容”
# 移进 data/_quarantine_20261103_golden_o/（无 MANIFEST、从未进 git）。系统代码不属于内容隔离：退役代码走 git（删除 / 回退可追溯），
# 不进 data/ 隔离区。这条守卫 ref_override 也绕不过。
CODE_ROOTS = ("tools", "tests")
CODE_SUFFIXES = (".py",)


def protected_code(path: str | Path, root: Path | None = None) -> list[str]:
    """path（文件或目录）里属于 tools/ tests/ 的 .py（相对项目根）；非空 = 不许移进隔离区"""
    root = root or ROOT
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        rel = p.resolve().relative_to(root.resolve())
    except ValueError:
        return []
    if not rel.parts:                     # 项目根本身
        return [x for c in CODE_ROOTS for x in protected_code(root / c, root)]
    if rel.parts[0] not in CODE_ROOTS:
        return []
    if p.is_file() or not p.exists():
        return [rel.as_posix()] if rel.suffix in CODE_SUFFIXES else []
    return sorted(x.relative_to(root.resolve()).as_posix() for x in p.resolve().rglob("*")
                  if x.is_file() and x.suffix in CODE_SUFFIXES and "__pycache__" not in x.parts)


RETIRED_FILE = "RETIRED.json"     # <qdir>/RETIRED.json：有意退役的系统代码清单（总调度 11-03：例外只认显式清单）


def retired_list(q: Path) -> dict[str, dict]:
    """<qdir>/RETIRED.json → {原相对路径: {reason, by, decision, at}}。格式：{"retired": [{"src": "tools/...py", "reason": ..., "by": ..., "decision": ...}]}"""
    try:
        d = json.loads((q / RETIRED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有清单 = 没有例外
        return {}
    return {str(r.get("src")): r for r in (d.get("retired") or []) if r.get("src") and r.get("reason") and r.get("by")}


def record_retired(q: Path, src_rel: str, reason: str, by: str, decision: str = "") -> dict:
    """把一个代码文件登记为有意退役（追加进 <qdir>/RETIRED.json；同一路径覆盖）。reason / by 必填"""
    if not (reason and by):
        raise ValueError("退役登记必须写 reason 和 by（谁定的）")
    q.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads((q / RETIRED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 新建清单
        d = {}
    rows = [r for r in (d.get("retired") or []) if r.get("src") != src_rel]
    rec = {"src": src_rel, "reason": reason, "by": by, "decision": decision, "at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S")}
    d = {"_doc": "有意退役的系统代码（tools/ tests/ .py）。只有列在这里的，quarantine 守卫才不判为误隔离（ISS-1103-033325-9b07）",
         "retired": rows + [rec]}
    (q / RETIRED_FILE).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rec


def quarantined_code(root: Path | None = None) -> list[str]:
    """已经躺在 data/_quarantine*/ 里、又没有登记在该隔离目录 RETIRED.json 里的系统代码
    （隔离区路径 = <qdir>/<原相对路径>，所以看 <qdir>/tools|tests/**.py）。手工 mv 进去的也查得出来；非空 = 误隔离，该还原或补退役登记"""
    root = root or ROOT
    out = []
    for q in sorted((root / "data").glob("_quarantine*")):
        ok = retired_list(q)
        for c in CODE_ROOTS:
            if (q / c).is_dir():
                out += [x.relative_to(root).as_posix() for x in (q / c).rglob("*")
                        if x.is_file() and x.suffix in CODE_SUFFIXES and "__pycache__" not in x.parts
                        and x.relative_to(q).as_posix() not in ok]
    return sorted(out)


def terms_for(p: Path) -> list[str]:
    try:
        rel = p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        rel = p.as_posix()
    out = {rel, rel.replace("/", "\\"), rel.replace("/", "\\\\")}
    parts = rel.split("/")
    if len(parts) >= 2:
        out.add("/".join(parts[-2:]))
    name = parts[-1]
    stem = Path(name).stem
    if name not in GENERIC and stem not in GENERIC and len(stem) >= 6 and not re.fullmatch(r"[\d_\-.]+", stem):
        out.add(name)
    return sorted(t for t in out if t)


def rg(terms: list[str], dirs: tuple[str, ...]) -> list[str]:
    existing = [d for d in dirs if (ROOT / d).exists()]
    if not existing or not terms:
        return []
    cmd = ["rg", "-n", "-F", "--no-heading", "-S", "--max-columns", "220"]
    for g in SELF_GLOBS:
        cmd += ["-g", g]
    for t in terms:
        cmd += ["-e", t]
    cmd += existing
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)   # K-OPS-S01
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def check(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    t = terms_for(p)
    code = rg(t, CODE_DIRS) + rg(t, EVIDENCE_DIRS)
    docs = rg(t, DOC_DIRS)
    return {"src": str(p), "terms": t, "code_refs": code, "doc_refs": docs[:20], "doc_ref_count": len(docs),
            "referenced": bool(code)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--plan")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scan-quarantine", action="store_true", help="列出 data/_quarantine*/ 里没登记 RETIRED.json 的 tools/ tests/ .py（误隔离）")
    a = ap.parse_args(argv)
    if a.scan_quarantine:
        bad = quarantined_code()
        for x in bad:
            print("[CODE-IN-QUARANTINE]", x)
        print(f"隔离区里的系统代码 {len(bad)} 个")
        return 1 if bad else 0
    paths = list(a.paths)
    if a.plan:
        paths += [it["src"] for it in json.loads(Path(a.plan).read_text(encoding="utf-8"))]
    res = [check(x) for x in paths]
    for r in res:                         # 系统代码一律算“有引用”（不许隔离）
        code = protected_code(r["src"])
        if code:
            r.update(referenced=True, protected_code=code, code_refs=[f"系统代码（tools/ tests/ .py 不属于内容隔离）：{x}" for x in code[:5]] + r["code_refs"])
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for r in res:
            flag = "REFERENCED" if r["referenced"] else "clean"
            print(f"[{flag}] {r['src']}  code={len(r['code_refs'])} docs={r['doc_ref_count']}")
            for ln in r["code_refs"][:8]:
                print("    ", ln[:200])
    return 1 if any(r["referenced"] for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
