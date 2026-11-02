"""真删除前的反查（SYSARCH，总调度 11-02 14:xx 定；规则 K-OPS-Y06）。

背景：11-02 13:2x 项目方本人下令删除隔离区（L-058，-Delete），删完 knowledge 规则证据指向的文件没了，compile --check 失败挡住发版。
quarantine_refcheck 只管“移进隔离区之前”，“从隔离区（或任何地方）真删除之前”没有检查。本脚本补这一步，只读、不删任何东西：

  - 反查 knowledge/rules/*.yaml 的 evidence.src、knowledge/RSI_LEDGER.md、knowledge/archive/**、config/owner_decisions.yaml 里
    指向要删路径（文件本身，或目录下任意文件）的引用；
  - 有引用 → 列出每处（文件:行、规则 id、原 src）并给改指方案，退出码 1；没有 → 退出码 0；
  - --emit-ps1 OUT：只在没有引用时生成删除脚本，脚本开头先重跑本反查，不过就中止（删除脚本生成时自带这一步）。

改指方案（不自动改）：把被删文件里支撑这条规则的要点（一两句 + 原路径 + sha256 + 删除日期）追加到 knowledge/archive/deleted_evidence.md，
再把 evidence.src 改成 "knowledge/archive/deleted_evidence.md §<原路径>"——compile 要求 src 指向存在的文件，存档文件长期保留。

    .venv/Scripts/python.exe -X utf8 tools/qa/purge_precheck.py data/_quarantine_20261101 [更多路径]
    .venv/Scripts/python.exe -X utf8 tools/qa/purge_precheck.py data/_quarantine_20261101 --emit-ps1 ops/cleanup/delete_x.ps1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ("knowledge/rules", "knowledge/RSI_LEDGER.md", "knowledge/archive", "config/owner_decisions.yaml")
ARCHIVE = "knowledge/archive/deleted_evidence.md"
ID_RE = re.compile(r"^\s*-\s*id:\s*(\S+)")


def norm(p: str | Path) -> str:
    s = str(p).replace("\\", "/").strip().strip("'\"")
    try:
        pp = Path(s)
        if pp.is_absolute():
            s = pp.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        pass
    return s.lstrip("./")


def _files() -> list[Path]:
    out = []
    for d in SCAN:
        p = ROOT / d
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [q for q in p.rglob("*") if q.is_file() and q.suffix in (".yaml", ".yml", ".md", ".json", ".txt")]
    return sorted(out)


def _hits_target(text: str, targets: list[str]) -> list[str]:
    """一行里提到的、落在某个要删路径之下（或就是它）的路径片段"""
    found = []
    for t in targets:
        tt = t.rstrip("/")
        for m in re.finditer(re.escape(tt) + r"(/[^\s'\"）),|]*)?", text):
            found.append(m.group(0))
    return found


def check(paths: list[str]) -> list[dict]:
    targets = [norm(p) for p in paths]
    hits = []
    for f in _files():
        rel = f.relative_to(ROOT).as_posix()
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            hits.append({"file": rel, "line": 0, "rule": None, "ref": None, "error": f"读不到：{e}"})   # 读不到也要报，不当成没引用
            continue
        rule = None
        for i, ln in enumerate(lines, 1):
            m = ID_RE.match(ln)
            if m:
                rule = m.group(1)
            for ref in _hits_target(ln, targets):
                hits.append({"file": rel, "line": i, "rule": rule if rel.startswith("knowledge/rules/") else None, "ref": ref,
                             "fix": plan_fix(ref)})
    return hits


def plan_fix(ref: str) -> str:
    p = ROOT / ref
    sha = ""
    if p.is_file():
        try:
            sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        except OSError:
            sha = "读不到"   # arch-ok: 只用于改指方案里的标注，不影响判定
    return (f"把 {ref} 支撑这条的要点（一两句 + 原路径 + sha256 {sha or '目录'} + 删除日期 {time.strftime('%Y-%m-%d')}）追加到 {ARCHIVE}，"
            f"再把这里的 src 改成 \"{ARCHIVE} §{ref}\"")


PS1 = r"""# 生成：tools/qa/purge_precheck.py（K-OPS-Y06）。删除前先重跑反查：有规则证据 / 决策检查引用就中止。
$ErrorActionPreference = 'Stop'
Set-Location '{root}'
& .\.venv\Scripts\python.exe -X utf8 tools\qa\purge_precheck.py {args}
if ($LASTEXITCODE -ne 0) {{ Write-Host '反查不过：仍有引用，删除中止' ; exit 1 }}
{removes}
Write-Host '删除完成'
"""


def emit_ps1(paths: list[str], out: str) -> Path:
    targets = [norm(p) for p in paths]
    removes = "\n".join(f"Remove-Item -LiteralPath '{(ROOT / t)}' -Recurse -Force" for t in targets)
    args = " ".join(f"'{t}'" for t in targets)
    p = ROOT / out if not Path(out).is_absolute() else Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(PS1.format(root=ROOT, args=args, removes=removes), encoding="utf-8-sig")
    return p


def main(argv: list[str] | None = None) -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass   # arch-ok: 老终端不支持 reconfigure，只影响打印
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit-ps1")
    a = ap.parse_args(argv)
    hits = check(a.paths)
    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
    else:
        for h in hits:
            print(f"引用  {h['file']}:{h['line']}  {h.get('rule') or ''}  → {h.get('ref') or h.get('error')}")
            if h.get("fix"):
                print(f"      改指：{h['fix']}")
        print("PURGE_PRECHECK", "FAIL" if hits else "PASS", f"（{len(hits)} 处引用）")
    if hits:
        if a.emit_ps1:
            print("有引用，不生成删除脚本", file=sys.stderr)
        return 1
    if a.emit_ps1:
        print("删除脚本：", emit_ps1(a.paths, a.emit_ps1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
