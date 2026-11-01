"""全仓结构退化扫描 + 棘轮闸门（SYSARCH 11-02，总调度 fredw-2b 派；docs/master/ARCH_ROADMAP.md §0；规则 K-OPS-A01）。

项目方 02:5x 原话：“我需要你整一个 master agent，更加全面地去看整个 system 的 code 怎么样去做。”
此前原话：“每次都是我指出来你才去修……这不是 RSI。”→ 结构问题必须由系统先发现：本脚本只读、可重复，
把 ARCH_MAP §7/§9 的 9 类结构退化变成计数，和基线比，只许减不许增（棘轮）。

度量（全部静态 AST / 文本，不起进程、不连服务器）：
  no_timeout      subprocess.run/call/check_call/check_output 不带 timeout=（Top15 #14）
  direct_ssh      代码里以 "ssh"/"scp" 为命令起进程（字面量），不经 tools/netfix/rssh（Top15 #13）
  ssh_unlisted    direct_ssh 中没登记在 config/netfix/ssh_callers.txt 的文件
  def_ssh         自写 def ssh()/_ssh()/run_ssh() 之类的平行实现（ARCH_MAP §8.2-2）
  hard_run        源码里写死 "series10_v1"（Top15 #11；唯一允许处 tools/autopilot/runs.py）
  hard_path       写死 /root/work/fredw、offline_20261101（ARCH_MAP §7）
  silent_read     try 里读文件 / 解析 JSON，except 里直接 return 常量 / pass（失败开放，Top15 #2）
  nonatomic_json  函数里 write_text(json.dumps(...)) 而同函数没有 os.replace（ARCH_MAP §6）
  untracked_code  代码目录里 git 未跟踪的 .py（Top15 #1：运行中的代码不在版本里）；imported=被已跟踪代码 import
  unowned         代码文件在 tools/qa/ownership.yaml 里匹配不到 owner（Top15 #15）

用法：
  python tools/qa/arch_scan.py                 # 扫描 → data/sysarch/scan_latest.json + history.jsonl，打印摘要
  python tools/qa/arch_scan.py --check         # 和 data/sysarch/baseline.json 比：任一度量的某个文件计数变大 / 新文件冒出 → 退出 1
  python tools/qa/arch_scan.py --write-baseline   # 只在 SYSARCH 关单后收紧基线时用（棘轮只往下）
  python tools/qa/arch_scan.py --files a.py b.py --check   # 只看给定文件（架构闸门审 diff 用）
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/sysarch"
CODE_DIRS = ("tools", "services", "packages", "ops", "apps/web/e2e")
SKIP_PARTS = {"__pycache__", "node_modules", ".venv", "_quarantine", "dist", "build", ".git"}
SUBPROC_FUNCS = {"run", "call", "check_call", "check_output"}
SSH_EXES = {"ssh", "ssh.exe", "scp", "scp.exe"}
SSH_GATE_FILES = {"tools/netfix/rssh.py", "tools/netfix/rsh.py", "tools/netfix/ssh_shim.py", "tools/netfix/tunnel_supervisor.py"}
DEF_SSH_RE = re.compile(r"^_?(ssh|run_ssh|ssh_run|ssh_cmd|remote_ssh|rsh)$")
HARD_RUN = "series10_v1"
HARD_RUN_ALLOW = {"tools/autopilot/runs.py", "tools/qa/arch_scan.py"}
HARD_PATHS = ("/root/work/fredw", "offline_20261101")
READ_ATTRS = {"read_text", "read_bytes", "load", "loads", "safe_load", "open"}
METRICS = ("no_timeout", "direct_ssh", "ssh_unlisted", "def_ssh", "hard_run", "hard_path", "silent_read",
           "nonatomic_json", "untracked_code", "unowned")


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def git_lines(*args: str) -> list[str]:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
        return [x for x in r.stdout.splitlines() if x.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def code_files(only: list[str] | None = None) -> list[Path]:
    if only:
        return [ROOT / f for f in only if f.endswith(".py") and (ROOT / f).is_file()]
    out = []
    for d in CODE_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if not SKIP_PARTS.intersection(p.relative_to(ROOT).parts):
                out.append(p)
    return sorted(out)


def _call_name(node: ast.Call) -> tuple[str | None, str | None]:
    f = node.func
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else None
        return base, f.attr
    if isinstance(f, ast.Name):
        return None, f.id
    return None, None


def _first_arg_exe(node: ast.Call) -> str | None:
    if not node.args:
        return None
    a = node.args[0]
    if isinstance(a, (ast.List, ast.Tuple)) and a.elts and isinstance(a.elts[0], ast.Constant) and isinstance(a.elts[0].value, str):
        return a.elts[0].value.strip()
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value.strip().split(" ", 1)[0]
    return None


def _is_trivial_handler(h: ast.ExceptHandler) -> bool:
    """except 体只有 pass / return 常量或空容器 / continue → 失败开放"""
    if len(h.body) != 1:
        return False
    s = h.body[0]
    if isinstance(s, (ast.Pass, ast.Continue)):
        return True
    if isinstance(s, ast.Return):
        v = s.value
        if v is None or isinstance(v, ast.Constant):
            return True
        if isinstance(v, ast.Dict):
            return not v.keys
        if isinstance(v, (ast.List, ast.Set, ast.Tuple)):
            return not v.elts
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in ("dict", "list", "set") and not v.args:
            return True
    return False


def _waived(lines: list[str], h: ast.ExceptHandler) -> bool:
    """except 行或其体内写了 “# arch-ok: <理由>” = 调用方显式处理了 None / 空值（审过的豁免，理由必须写）"""
    end = getattr(h, "end_lineno", h.lineno) or h.lineno
    return any("# arch-ok:" in lines[i - 1] for i in range(h.lineno, end + 1) if 0 < i <= len(lines))


def _try_reads(t: ast.Try) -> bool:
    for n in ast.walk(ast.Module(body=t.body, type_ignores=[])):
        if isinstance(n, ast.Call):
            _b, name = _call_name(n)
            if name in READ_ATTRS:
                return True
    return False


def scan_source(path: str, src: str) -> dict[str, int]:
    """单文件计数（纯函数，测试直接调）"""
    c = {m: 0 for m in METRICS}
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return {"parse_error": 1}   # 写到一半 / 语法错：本次不计（Y1 syntax_guard 管），比较和收紧基线时沿用旧值
    lines = src.splitlines()
    # 写死计数只看代码里的字符串常量（注释、docstring 不算）
    docs = {id(b[0].value) for b in (getattr(n, "body", None) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)}
    strs = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    if path not in HARD_RUN_ALLOW:
        c["hard_run"] = sum(x.count(HARD_RUN) for x in strs)
        c["hard_path"] = sum(x.count(h) for x in strs for h in HARD_PATHS)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            base, name = _call_name(n)
            if base == "subprocess" and name in SUBPROC_FUNCS:
                kws = {k.arg for k in n.keywords}
                if "timeout" not in kws and None not in kws:   # None = **kwargs，可能带 timeout，不算
                    c["no_timeout"] += 1
            if base == "subprocess" and name in SUBPROC_FUNCS | {"Popen"} and path not in SSH_GATE_FILES:
                exe = _first_arg_exe(n)
                if exe and exe.rsplit("/", 1)[-1].lower() in SSH_EXES:
                    c["direct_ssh"] += 1
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if DEF_SSH_RE.match(n.name) and path not in SSH_GATE_FILES:
                c["def_ssh"] += 1
            has_dump_write = has_replace = False
            for m in ast.walk(n):
                if isinstance(m, ast.Call):
                    b, nm = _call_name(m)
                    if nm == "write_text" and m.args and isinstance(m.args[0], ast.Call) and _call_name(m.args[0])[1] == "dumps":
                        has_dump_write = True
                    if (b == "os" and nm in ("replace", "rename")) or (nm == "replace" and len(m.args) == 1):
                        has_replace = True   # os.replace(t, p) / tmp.replace(p)（Path.replace 一个参数；str.replace 两个参数不算）
            if has_dump_write and not has_replace:
                c["nonatomic_json"] += 1
        elif isinstance(n, ast.Try):
            if _try_reads(n) and any(_is_trivial_handler(h) and not _waived(lines, h) for h in n.handlers):
                c["silent_read"] += 1
    return c


def import_names(src: str) -> set[str]:
    """文件里 import 到的所有名字分量（from a.b import c → {a, b, c}）"""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.update(a.name.split("."))
        elif isinstance(n, ast.ImportFrom):
            out.update((n.module or "").split("."))
            out.update(a.name for a in n.names)
    return out


def load_owner_fn():
    spec = importlib.util.spec_from_file_location("_iter_gate_for_arch", ROOT / "tools/qa/iter_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # 只有标准库顶层 import
    own = mod.load_own()
    return lambda p: mod.owner_of(p, own)[0]


def scan(only: list[str] | None = None) -> dict:
    files = code_files(only)
    untracked = set(git_lines("ls-files", "--others", "--exclude-standard", "--", *CODE_DIRS))
    listed = {x.strip() for x in (ROOT / "config/netfix/ssh_callers.txt").read_text(encoding="utf-8").splitlines()
              if x.strip() and not x.startswith("#")} if (ROOT / "config/netfix/ssh_callers.txt").exists() else set()
    try:
        owner = load_owner_fn()
    except Exception as e:   # noqa: BLE001 —— 所有权表读不到要显式报，不静默
        print(f"[arch_scan] 警告：ownership.yaml 读取失败，unowned 不计：{e}", file=sys.stderr)
        owner = None
    per: dict[str, dict[str, int]] = {}
    stems: dict[str, str] = {}
    texts: dict[str, str] = {}
    for p in files:
        r = rel(p)
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[arch_scan] 读不到 {r}：{e}", file=sys.stderr)
            continue
        texts[r] = src
        c = scan_source(r, src)
        if c.get("parse_error"):
            per[r] = c
            continue
        if c["direct_ssh"] and r not in listed:
            c["ssh_unlisted"] = c["direct_ssh"]
        if r in untracked:
            c["untracked_code"] = 1
            stems[p.stem] = r
        if owner is not None and owner(r) is None:
            c["unowned"] = 1
        if any(c.values()):
            per[r] = {k: v for k, v in c.items() if v}
    # 未跟踪模块是否被已跟踪代码 import（=sv tag 回滚即坏）
    imported: dict[str, list[str]] = {}
    if stems:
        for r, src in texts.items():
            if r in untracked:
                continue
            for s in import_names(src) & stems.keys():
                if stems[s] != r:
                    imported.setdefault(stems[s], []).append(r)
    totals = {m: sum(v.get(m, 0) for v in per.values()) for m in METRICS}
    totals["parse_error"] = sum(v.get("parse_error", 0) for v in per.values())
    return {"schema": "nsfs.arch_scan/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files_scanned": len(files),
            "partial": bool(only), "totals": totals, "per_file": per,
            "untracked_imported": {k: sorted(set(v))[:10] for k, v in sorted(imported.items())}}


def compare(cur: dict, base: dict) -> list[str]:
    """棘轮：只报变坏的（文件级计数变大，或新文件冒出非 0）"""
    bad = []
    bp = base.get("per_file", {})
    for f, c in cur.get("per_file", {}).items():
        if c.get("parse_error"):
            continue   # 本次没法解析，不判（不当作变好也不当作变坏）
        for m, v in c.items():
            if cur.get("partial") and m == "untracked_code":
                continue   # 审一轮改动时新文件还没 cut 是正常的（入版由 iter_gate V2 / cut 管）；全量巡检才判
            old = bp.get(f, {}).get(m, 0)
            if v > old:
                bad.append(f"{m}: {f} {old}→{v}")
    if not cur.get("partial"):
        for k, v in (cur.get("untracked_imported") or {}).items():
            if k not in (base.get("untracked_imported") or {}):
                bad.append(f"untracked_imported: {k} 被 {', '.join(v[:3])} import，但没入版")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--files", nargs="*")
    a = ap.parse_args()
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    cur = scan(a.files)
    OUT.mkdir(parents=True, exist_ok=True)
    if not a.files:
        (OUT / "scan_latest.json").write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        with (OUT / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": cur["at"], "totals": cur["totals"], "untracked_imported": len(cur["untracked_imported"])},
                                ensure_ascii=False) + "\n")
    print("arch_scan", cur["at"], "扫描", cur["files_scanned"], "个文件")
    for m in METRICS:
        print(f"  {m:15s} {cur['totals'][m]}")
    print(f"  untracked_imported {len(cur['untracked_imported'])}")
    if a.write_baseline:
        if a.files:
            print("--write-baseline 不能和 --files 一起用", file=sys.stderr)
            return 2
        bp = OUT / "baseline.json"
        old = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {"per_file": {}}
        for f, c in list(cur["per_file"].items()):
            if c.get("parse_error"):   # 解析失败的文件沿用旧基线，避免把“写到一半”收成 0
                cur["per_file"][f] = old["per_file"].get(f, c)
                print(f"  {f} 本次解析失败，沿用旧基线", file=sys.stderr)
        tmp = bp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, bp)
        print("基线已写 data/sysarch/baseline.json")
    if a.check:
        bp = OUT / "baseline.json"
        if not bp.exists():
            print("没有基线 data/sysarch/baseline.json → 不能判（先 --write-baseline）", file=sys.stderr)
            return 2
        bad = compare(cur, json.loads(bp.read_text(encoding="utf-8")))
        for b in bad:
            print("  退化", b)
        print("ARCH_SCAN", "FAIL" if bad else "PASS", f"（{len(bad)} 处退化）")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
