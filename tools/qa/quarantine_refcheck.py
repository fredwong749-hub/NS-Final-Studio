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
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    a = ap.parse_args(argv)
    paths = list(a.paths)
    if a.plan:
        paths += [it["src"] for it in json.loads(Path(a.plan).read_text(encoding="utf-8"))]
    res = [check(x) for x in paths]
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
