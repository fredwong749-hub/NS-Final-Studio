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
  hard_import_path 写死某部剧的导入稿 / 造型目录 / 渲染根目录（script_v2.json、data/looks、data/renders、data/renders/epNN…）——
                  按剧取路径一律调 runs.script_path / looks_path / renders_dir（K-OPS-F24，AUDIT-M I-14 / I-15，总调度 18:5x）；现有处进基线，只拦新增
  bypass_script   服务器上被生产调用的脚本不是来自仓库部署目录（K-OPS-F18，总调度 11-02 16:5x：同一个东西两个入口，今天第四次）：
                  [PY, "x.py"] / cd {DIR} && {PY} x.py 这类按 cwd 相对跑脚本，或写死仓库外的 /root/work/fredw/<目录>/x.py

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
TEST_DIRS = ("tests",)
# 测试代码单独口径（总调度 11-02 03:4x，UIAUDIT 报 A1）：只有 no_timeout 进棘轮（子进程无上限会让 cut 的 pytest 卡死），其余只记录不阻断
TEST_GATED = {"no_timeout"}


def is_test(path: str) -> bool:
    return path.startswith("tests/") or "/tests/" in path or path.rsplit("/", 1)[-1].startswith("test_")
SKIP_PARTS = {"__pycache__", "node_modules", ".venv", "_quarantine", "dist", "build", ".git"}
SUBPROC_FUNCS = {"run", "call", "check_call", "check_output"}
SSH_EXES = {n + ext for n in ("ssh", "scp") for ext in ("", ".exe")}   # 拼出来：不让 test_netfix 的文本正则把本文件误判成 ssh 调用方
SSH_GATE_FILES = {"tools/netfix/rssh.py", "tools/netfix/rsh.py", "tools/netfix/ssh_shim.py", "tools/netfix/tunnel_supervisor.py"}
DEF_SSH_RE = re.compile(r"^_?(ssh|run_ssh|ssh_run|ssh_cmd|remote_ssh|rsh)$")
HARD_RUN = "series10_v1"
HARD_RUN_ALLOW = {"tools/autopilot/runs.py", "tools/qa/arch_scan.py"}
HARD_PATHS = ("/root/work/fredw", "offline_20261101")
READ_ATTRS = {"read_text", "read_bytes", "load", "loads", "safe_load", "open"}
METRICS = ("no_timeout", "direct_ssh", "ssh_unlisted", "def_ssh", "hard_run", "hard_path", "silent_read",
           "nonatomic_json", "untracked_code", "unowned", "pipe_gate", "mtime_run_guess", "mtime_latest", "prompt_bypass", "bypass_script",
           "hard_import_path", "naive_time")
# L-118 四道关之四（总调度 11-02 13:3x 定）：编译模块以外的代码往提示词字段里拼接句子 = 规则又散落了。
# 只许经 config/compile/plugins.yaml 登记的插件改本段（IMGMASTER 合入）。现有散落处进基线，只许减。
PROMPT_FIELDS = {"prompt", "img_prompt", "positive", "positive_prompt", "text_prompt", "prompt_text", "pos", "full_prompt"}
COMPILE_OWNERS = {"services/agent/ns_agent/frame_job.py", "services/agent/ns_agent/asset_refs.py",
                  "services/render_router/ns_render/unified_frame.py"}
# K-OPS-W20（WORKFLOW 11-02，UIAUDIT N1 林晚人物页 404 根因）：按修改时间猜“当前剧”——同一行 iterdir() + st_mtime / getmtime，
# 或 runs / run_dir 目录按 mtime 排序，或 def mt(p: str)；当前剧只许读 runs.py / ns_api.current_run。口径同 tests/test_current_run.py
MTIME_RUN_GUESS_RE = re.compile(r"(?:runs?|RUNS|run_dir|root)\b.{0,120}key=lambda [a-z_]+: -?\(?[a-z_]+(?: / \"[a-z_]+\")?\)?\.stat\(\)\.st_mtime"
                                r"|def mt\(p: str\) -> float")
# 同一部剧里“按修改时间取最新文件”（最新成片 / 合并稿 / 场景图）：不一定错，但应走登记表或 active 指针；只记账、只许减不增
MTIME_LATEST_RE = re.compile(r"(?:glob|iterdir|listdir)\(.*(?:st_mtime|getmtime)|(?:st_mtime|getmtime).*(?:glob|iterdir|listdir)\(")
# K-OPS-E14（DEBUG-RSI 提议，总调度 11-02 批）：闸门命令接管道再用 && 判成败 → 退出码被 head/tail/grep 吃掉
PIPE_GATE_RE = re.compile(r"(lock-status|pytest|system_version|iter_gate|decision_check)[^|\n]*\|\s*(head|tail|grep)[^&\n]*&&")
# K-OPS-F18：脚本只许从仓库部署目录跑（imggen/score_remote.py 旁路拷贝让 sv-13 的修复没生效）
BYPASS_RES = (re.compile(r"\[\s*[A-Za-z_][\w.]*\s*,\s*[\"'][\w-]+\.py[\"']"),                  # [PY, "x.py", ...]：按 cwd 相对跑
              re.compile(r"cd \{?\$?[A-Za-z_]\w*\}?\s*&&\s*\S+\s+[\w-]+\.py\b"),               # cd {R} && {PY} x.py
              re.compile(r"/root/work/fredw/(?!offline_20261101/repo/)[\w./-]+?\.py\b"))      # 仓库外绝对路径的 .py
# L-212 #10（W-FIX-UI 11-07）：笔记本系统时钟是美东，ns_api 里用本机时区取 / 格式化时间 = 页面差 14 小时。
# 页面时间一律走 ns_api/clock.py（epoch_jst / jst_now_str / local_naive_to_jst）。存量（写进文件的记录 / 文件名戳 / 比较键）进基线，只许减；
# 确实不是给人看的（文件名戳、和同文件旧记录比较）在行尾写 # arch-ok: 原因
NAIVE_TIME_SCOPE = "services/api/ns_api/"
NAIVE_TIME_ALLOW = {"services/api/ns_api/clock.py"}
NAIVE_TIME_RE = re.compile(r"\btime\.(?:localtime|ctime|asctime)\(|\bdatetime\.now\(\s*\)|\bdatetime\.today\(\)"
                           r"|\bdatetime\.fromtimestamp\([^,()]*(?:\([^()]*\))?[^,()]*\)|\btime\.strftime\((?!.*\bgmtime\()")


def naive_time_count(path: str, lines: list[str]) -> int:
    if not path.startswith(NAIVE_TIME_SCOPE) or path in NAIVE_TIME_ALLOW or is_test(path):
        return 0
    return sum(1 for ln in lines if NAIVE_TIME_RE.search(ln) and "# arch-ok:" not in ln and not ln.lstrip().startswith("#"))


HARD_IMPORT_ALLOW = {"tools/autopilot/runs.py", "services/api/ns_api/run_paths.py", "tools/qa/arch_scan.py"}
HARD_IMPORT_RE = re.compile(r"script_v2\.json|(?:^|/)data/looks(?:/|$)|^data/renders/?$|(?:^|/)data/renders/ep\d")


def hard_import_count(strs: list[str]) -> int:
    return sum(1 for x in strs if HARD_IMPORT_RE.search(x))


SHELL_DIRS = CODE_DIRS + ("docs", "knowledge", "config")
SHELL_EXTS = {".sh", ".ps1", ".md"}


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
    for d in CODE_DIRS + TEST_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if not SKIP_PARTS.intersection(p.relative_to(ROOT).parts):
                out.append(p)
    return sorted(out)


def shell_files(only: list[str] | None = None) -> list[Path]:
    if only:
        return [ROOT / f for f in only if Path(f).suffix in SHELL_EXTS and (ROOT / f).is_file()]
    out = []
    for d in SHELL_DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix in SHELL_EXTS and p.is_file() and not SKIP_PARTS.intersection(p.relative_to(ROOT).parts):
                out.append(p)
    return sorted(set(out))


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


def _field_name(t) -> str | None:
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
        return t.slice.value   # job["prompt"] += ...
    return None


def _prompt_bypass(tree, lines) -> int:
    """x.prompt += "..." / prompt = prompt + "..." / prompt_parts.append(...)（字段名在 PROMPT_FIELDS）"""
    n_hit = 0
    for n in ast.walk(tree):
        hit = False
        if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) and (_field_name(n.target) or "").lower() in PROMPT_FIELDS:
            hit = True
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Add):
            tgt = (_field_name(n.targets[0]) or "").lower()
            left = (_field_name(n.value.left) or "").lower()
            hit = tgt in PROMPT_FIELDS and left == tgt
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("append", "extend", "insert"):
            hit = (_field_name(n.func.value) or "").lower() in PROMPT_FIELDS
        if hit and not _line_waived(lines, n):
            n_hit += 1
    return n_hit


def _delegates_to_rssh(fn: ast.AST) -> bool:
    """函数体里有 rssh.run / rssh.run_retry 之类的调用，且没有自己起 ssh/scp 子进程 = 薄包装"""
    uses_rssh = own_ssh = False
    for m in ast.walk(fn):
        if isinstance(m, ast.Call):
            b, nm = _call_name(m)
            if b == "rssh" or nm == "run_retry":   # rssh.run(...) / _rssh().run_retry(...)
                uses_rssh = True
            if b == "subprocess" and nm in SUBPROC_FUNCS | {"Popen"}:
                exe = _first_arg_exe(m)
                if exe and exe.rsplit("/", 1)[-1].lower() in SSH_EXES:
                    own_ssh = True
    return uses_rssh and not own_ssh


def _line_waived(lines: list[str], n: ast.AST) -> bool:
    """调用所在行（含续行）写了 “# arch-ok: <理由>” = 审过的豁免"""
    end = getattr(n, "end_lineno", n.lineno) or n.lineno
    return any("# arch-ok:" in lines[i - 1] for i in range(n.lineno, end + 1) if 0 < i <= len(lines))


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
    c["pipe_gate"] = sum(len(PIPE_GATE_RE.findall(x)) for x in strs)
    if path != "tools/qa/arch_scan.py" and not is_test(path):
        c["bypass_script"] = sum(len(rx.findall(x)) for x in strs for rx in BYPASS_RES)
    if path not in HARD_IMPORT_ALLOW and not is_test(path):
        c["hard_import_path"] = hard_import_count(strs)
    c["naive_time"] = naive_time_count(path, lines)
    for ln in (lines if path != "tools/qa/arch_scan.py" else []):   # 本文件的正则自己会命中
        if "# arch-ok:" in ln or ln.lstrip().startswith("#"):
            continue
        if ("iterdir()" in ln and ("st_mtime" in ln or "getmtime" in ln)) or MTIME_RUN_GUESS_RE.search(ln):
            c["mtime_run_guess"] += 1
        elif MTIME_LATEST_RE.search(ln):
            c["mtime_latest"] += 1
    if path not in HARD_RUN_ALLOW:
        c["hard_run"] = sum(x.count(HARD_RUN) for x in strs)
        c["hard_path"] = sum(x.count(h) for x in strs for h in HARD_PATHS)
    if path not in COMPILE_OWNERS and not path.startswith("config/compile/") and not is_test(path):
        c["prompt_bypass"] = _prompt_bypass(tree, lines)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            base, name = _call_name(n)
            if base == "subprocess" and name in SUBPROC_FUNCS:
                kws = {k.arg for k in n.keywords}
                if "timeout" not in kws and None not in kws and not _line_waived(lines, n):   # None = **kwargs，可能带 timeout
                    c["no_timeout"] += 1
            if base == "subprocess" and name in SUBPROC_FUNCS | {"Popen"} and n.args and isinstance(n.args[0], ast.List)                     and "cwd" in {k.arg for k in n.keywords} and path != "tools/qa/arch_scan.py" and not is_test(path)                     and any(isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.endswith(".py") and "/" not in e.value
                            for e in n.args[0].elts):
                c["bypass_script"] += 1      # K-OPS-F18：subprocess.run([PY, "x.py"], cwd=别的目录) = 跑的是那个目录里的拷贝
            if base == "subprocess" and name in SUBPROC_FUNCS | {"Popen"} and path not in SSH_GATE_FILES:
                exe = _first_arg_exe(n)
                if exe and exe.rsplit("/", 1)[-1].lower() in SSH_EXES:
                    c["direct_ssh"] += 1
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if DEF_SSH_RE.match(n.name) and path not in SSH_GATE_FILES and not _delegates_to_rssh(n):
                c["def_ssh"] += 1   # 只算平行实现：函数体里调了 rssh.* 的薄包装不算（4-1 的收口方式）
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


PKG_ROOTS = ("", "services/agent", "services/api", "services/render_router", "services/post", "services/orchestrator",
             "services/recipes", "services/canvas_api", "packages/schema", "packages/qc")


def imported_untracked(importer: str, src: str, untracked: set[str]) -> set[str]:
    """importer 可能 import 到的未跟踪 .py（按真实解析路径，不按文件名撞名）：
    相对导入按 importer 目录解析；绝对导入按仓库根 + 各包根解析；裸名导入（sys.path 插目录后 import x）
    只在 importer 和目标同目录、或 importer 源码里写了目标目录路径时才算"""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return set()
    here = importer.rsplit("/", 1)[0] if "/" in importer else ""
    by_stem: dict[str, list[str]] = {}
    for u in untracked:
        by_stem.setdefault(u.rsplit("/", 1)[-1][:-3], []).append(u)
    cands: set[str] = set()

    def mod_files(base: str, parts: list[str]) -> list[str]:
        b = "/".join(x for x in [base, *parts] if x)
        return [b + ".py", b + "/__init__.py"]

    def bare(name: str) -> None:
        for u in by_stem.get(name, []):
            d = u.rsplit("/", 1)[0]
            if d == here or d in src:
                cands.add(u)

    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            parts = (n.module or "").split(".") if n.module else []
            if n.level:
                base = here
                for _ in range(n.level - 1):
                    base = base.rsplit("/", 1)[0] if "/" in base else ""
                bases = [base]
            else:
                bases = list(PKG_ROOTS)
                if len(parts) == 1:
                    bare(parts[0])
            for b in bases:
                cands.update(mod_files(b, parts))
                for a in n.names:
                    cands.update(mod_files(b, parts + [a.name]))
        elif isinstance(n, ast.Import):
            for a in n.names:
                parts = a.name.split(".")
                for b in PKG_ROOTS:
                    cands.update(mod_files(b, parts))
                if len(parts) == 1:
                    bare(parts[0])
    return cands & untracked


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
    # K-OPS-E14：.sh / .ps1 / .md 里的闸门命令行（全量扫描时才扫；--files 只扫给定的这类文件）
    for p in shell_files(only):
        r = rel(p)
        try:
            n = len(PIPE_GATE_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue   # arch-ok: 扫描期间被移走的文件，下一轮再看
        if n:
            per.setdefault(r, {})["pipe_gate"] = n
    # 未跟踪模块是否被已跟踪代码 import（=sv tag 回滚即坏）
    imported: dict[str, list[str]] = {}
    unt_py = {u for u in untracked if u.endswith(".py")}
    if unt_py:
        for r, src in texts.items():
            if r in untracked:
                continue
            for u in imported_untracked(r, src, unt_py):
                imported.setdefault(u, []).append(r)
    totals = {m: sum(v.get(m, 0) for f, v in per.items() if not is_test(f)) for m in METRICS}
    totals_tests = {m: sum(v.get(m, 0) for f, v in per.items() if is_test(f)) for m in METRICS}
    totals["parse_error"] = sum(v.get("parse_error", 0) for v in per.values())
    return {"schema": "nsfs.arch_scan/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files_scanned": len(files),
            "partial": bool(only), "totals": totals, "totals_tests": totals_tests, "per_file": per,
            "untracked_imported": {k: sorted(set(v))[:10] for k, v in sorted(imported.items())},
            "ownership_findings": ownership_findings(), "knowledge_dup_ids": knowledge_dup_ids()}


RULE_ID_RE = re.compile(r"^\s*-\s*id:\s*([A-Z][A-Z0-9]*-[A-Z0-9-]+)\s*$", re.M)


def knowledge_dup_ids(rules_dir: Path | None = None) -> list[str]:
    """knowledge/rules/*.yaml 里同一个规则 id 出现两次（总调度 11-02 05:5x：写入时就拦，不等 cut）。纯文本扫，毫秒级"""
    seen: dict[str, str] = {}
    out = []
    for f in sorted((rules_dir or ROOT / "knowledge/rules").glob("*.yaml")):
        try:
            txt = f.read_text(encoding="utf-8")
        except OSError as e:
            out.append(f"读不到 {f.name}：{e}")
            continue
        for rid in RULE_ID_RE.findall(txt):
            if rid in seen:
                out.append(f"规则 id 重复：{rid}（{seen[rid]} 和 {f.name}）")
            else:
                seen[rid] = f.name
    return out


def ownership_findings(own: dict | None = None) -> list[str]:
    """一个负责方只用一个 key（总调度 11-02 03:15）：
    ① owners 的 key 是另一个 key 加后缀（AUTOPILOT_API ⊂ AUTOPILOT）= 别名 key；
    ② ownership.yaml 有 loops: 登记表时，owners / override / rule_owners / test_owners 里出现表外的负责方 = 未知 key。
    只读 ownership.yaml，不写。"""
    if own is None:
        try:
            import yaml
            own = yaml.safe_load((ROOT / "tools/qa/ownership.yaml").read_text(encoding="utf-8"))
        except Exception as e:   # noqa: BLE001 —— 表坏了本身就是问题，显式报
            return [f"ownership.yaml 读不到 / 解析失败：{e}"]
    out = []
    keys = sorted((own.get("owners") or {}).keys())
    for k in keys:
        base = next((b for b in keys if b != k and k.startswith(b + "_")), None)
        if base:
            out.append(f"别名 key：{k}（应合进 {base}）")
    # 已知 loop = loops: 登记表（有的话）；没有登记表时 = owners 的 key（rule_owners / test_owners / override 只能指向真有文件的负责方）
    reg = own.get("loops") or {}
    loops = set(reg) or set(keys)
    if reg and isinstance(reg, dict):   # loops: {NAME: {status: active|inactive, custodian: 在岗代管方}}
        for k, v in sorted(reg.items()):
            v = v or {}
            if v.get("status") not in ("active", "inactive"):
                out.append(f"loops 登记表：{k} 的 status 不是 active / inactive")
            elif v.get("status") == "inactive":
                c = v.get("custodian")
                if not c:
                    out.append(f"loops 登记表：{k} 是 inactive 但没写 custodian")
                elif (reg.get(c) or {}).get("status") != "active":
                    out.append(f"loops 登记表：{k} 的代管方 {c} 不在岗")
        for k in keys:
            if k not in reg:
                out.append(f"未知负责方 key：{k}（owners 里有、loops: 登记表里没有）")
    if loops:
        used = set(keys) | {o.get("owner") for o in own.get("override") or [] if isinstance(o, dict)}
        ro = own.get("rule_owners") or {}
        for sect in ("by_file", "by_id"):
            used |= {v for v in (ro.get(sect) or {}).values() if isinstance(v, str)}
        used |= {v for v in (own.get("test_owners") or {}).values() if isinstance(v, str)}
        norm = {re.split(r"[（(\s]", x, 1)[0] for x in used if x}   # “AUTOPILOT（ARCH）”这类带注解的值取主名
        for k in sorted(x for x in norm if x and x not in loops):
            out.append(f"未知负责方 key：{k}（不在已知 loop 里：ownership.yaml loops: 或 owners）")
    return out


def new_files(owner: str | None = None) -> list[str]:
    """git 未跟踪的代码 / 测试 .py；owner 给了就只留归它的（ownership.yaml 最具体匹配）"""
    fs = [f for f in git_lines("ls-files", "--others", "--exclude-standard", "--", *CODE_DIRS, *TEST_DIRS)
          if f.endswith(".py") and not SKIP_PARTS.intersection(f.split("/"))]
    if owner:
        own_fn = load_owner_fn()
        fs = [f for f in fs if own_fn(f) == owner]
    return sorted(fs)


def compare(cur: dict, base: dict) -> list[str]:
    """棘轮：只报变坏的（文件级计数变大，或新文件冒出非 0）"""
    bad = []
    bp = base.get("per_file", {})
    for f, c in cur.get("per_file", {}).items():
        if c.get("parse_error"):
            continue   # 本次没法解析，不判（不当作变好也不当作变坏）
        for m, v in c.items():
            if is_test(f) and m not in TEST_GATED:
                continue   # 测试代码：只有 no_timeout 判，其余只记录
            if cur.get("partial") and m == "untracked_code":
                continue   # 审一轮改动时新文件还没 cut 是正常的（入版由 iter_gate V2 / cut 管）；全量巡检才判
            old = bp.get(f, {}).get(m, 0)
            if v > old:
                bad.append(f"{m}: {f} {old}→{v}")
    bad += [f"knowledge: {x}" for x in cur.get("knowledge_dup_ids") or []]   # 不进基线，一条都不许有（部分扫描也判）
    known = set(base.get("ownership_findings") or [])
    bad += [f"ownership: {x}" for x in cur.get("ownership_findings") or [] if x not in known]   # 只许减不增
    if not cur.get("partial"):
        for k, v in (cur.get("untracked_imported") or {}).items():
            if k not in (base.get("untracked_imported") or {}):
                bad.append(f"untracked_imported: {k} 被 {', '.join(v[:3])} import，但没入版")
    return bad


def tighten(base: dict, cur: dict) -> dict:
    """棘轮收紧：文件级每项取 min；当前没出现的文件 / 项 = 已清零；当前新出现的不吸收；解析失败的沿用旧值"""
    per = {}
    for f, bc in base.get("per_file", {}).items():
        cc = cur.get("per_file", {}).get(f, {})
        if cc.get("parse_error"):
            per[f] = bc
            continue
        nc = {m: min(v, cc.get(m, 0)) for m, v in bc.items() if min(v, cc.get(m, 0))}
        if nc:
            per[f] = nc
    ui = {k: v for k, v in (base.get("untracked_imported") or {}).items() if k in (cur.get("untracked_imported") or {})}
    totals = {m: sum(v.get(m, 0) for f, v in per.items() if not is_test(f)) for m in METRICS}
    of = [x for x in base.get("ownership_findings") or [] if x in (cur.get("ownership_findings") or [])]
    return {**base, "at": cur.get("at"), "per_file": per, "untracked_imported": ui, "totals": totals, "ownership_findings": of}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--tighten", action="store_true", help="只收紧：每个文件每项取 min(基线, 现值)，新退化不吸收")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--new", action="store_true",
                    help="只查未入版的新代码文件（git 未跟踪的 .py）：新文件不许带任何退化入版（总调度 11-02 05:4x）")
    ap.add_argument("--owner", help="配合 --new：只查 ownership.yaml 里归这个负责方的新文件（iter_gate A2 用）")
    a = ap.parse_args()
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if a.new:
        a.files = new_files(a.owner)
        if not a.files:
            print("ARCH_SCAN PASS（没有未入版的新代码文件）")
            return 0
        print("新文件：", " ".join(a.files))
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
    if a.tighten and not a.files:
        bp = OUT / "baseline.json"
        old = json.loads(bp.read_text(encoding="utf-8"))
        new = tighten(old, cur)
        tmp = bp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, bp)
        print("基线已收紧（只降不升）", {m: new["totals"].get(m) for m in METRICS})
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
