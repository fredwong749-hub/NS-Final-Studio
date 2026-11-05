"""系统版本（发版 / 覆盖部署 / 回退）（CODE-RSI r3，2026-11-01；规则 K-OPS-V01，knowledge/rules/ops_code_rsi.yaml）。

项目方 11-01 22:5x：“记得每一次 iterate 完把东西记录下来.然后把规则系统的一些东西,全部代码都调一次,也就是说,每一次迭代都是用
override system,然后用 create a new version 那个 system versions”。
每次迭代收轮后由总调度 cut 一个系统版本：规则 + 代码 + 配置 + 文档一起成为可回退的 git 快照（tag），取代上一版，并留下本轮完整记录。
复用现有部件（G0）：git、knowledge kb 版本号、CHANGELOG、iter_gate 结果、syntax_guard、compile --check、decision_check /
decision_propagation、push_check / push_gate、resident_sync 的分级推送与 sha 核对。

  cut [--base REF] [--dry]     过闸门 → git add（.gitignore 口径：只跟踪代码 / 规则 / 配置 / 文档）→ commit（Co-Authored-By）→ tag sv-YYYYMMDD-NN
                               → docs/system_versions/<sv>.md + INDEX.md + data/system_versions/index.json（界面只读接口）
  cut … --on gpu33|local       W45：闸门在哪跑（默认 NS_CUT_ON > release.json gates_on）；gpu33 = tools/qa/remote_gates.py 把冻结树按 blob sha
                               增量推到服务器独立快照目录、在那里跑七门、结果与耗时拉回本报告；commit / tag / push 仍在笔记本
  deploy [SV] [--hosts gpu33,gpu36]
                               推到服务器：resident_sync 第一级推送（内含 push_gate）→ 代码按该版本的 git 快照逐个核 sha、不同就重推
                               → 服务器写 data/system_version.txt（= override system）→ 热重启常驻（resident_sync.restart 默认模式）
  （cut 末尾：推前密钥扫描 → git push origin <分支> --follow-tags；命中不推并报警，推送失败不影响发版——项目方 23:0x 授权，仅限发版流程）
  rollback SV                  只生成回退命令和差异预览（git checkout <tag> -- <跟踪文件> → deploy），不执行；执行要总调度确认
  status                       当前版本、HEAD 之后未入版的改动数
  release [--build-tree-only]  W17：按 data/system_versions/release_request.json 跑一次发版流水线（逻辑在 tools/autopilot/release_tick.py，
                               resident_sync loop 每拍自动跑）：复审全可入 → 按清单拼树（path@blob）→ cut --dry --tree → cut --tree → deploy --verify
  handover --dry|--apply       W17 / L-152 换代：笔记本 restart_producer.ps1 → 服务器 request_restart → 停 bench2 / bakeoff（只停不删）→ V2_LIVE
闸门任一不过就不发版并写明原因。不删文件。
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv/Scripts/python.exe") if (ROOT / ".venv/Scripts/python.exe").exists() else sys.executable
DOCS = ROOT / "docs/system_versions"
DATA = ROOT / "data/system_versions"
BASELINE = "0a91a20"                     # 第一个 git 检查点（总调度 11-01 夜）；还没有 sv 标签时以它为上一版
TAG_RE = re.compile(r"^sv-(\d{8})-(\d{2})$")
SMOKE = ["tests/test_syntax_guard.py", "tests/test_push_check.py", "tests/test_iter_gate.py",
         "tests/test_decision_propagation.py", "tests/test_system_version.py"]
CO_AUTHOR = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".wav", ".mp3", ".flac",
             ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".gguf", ".bin")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{24,}|\"(?:api_?key|secret|password|token)\"\s*:\s*\"[A-Za-z0-9_\-]{16,}\")", re.I)
# AUDIT-RULES 11-05：cut / 定向 pytest 一律按 JST（TZ=JST-9，与 ops/psmaster/cut_deploy_*.sh、release_tick 同口径）——笔记本时钟是美东，
# 测试按 JST 解析无时区串（debug_rsi e19/e21/e28）在本机时钟下会红；调用方已设 TZ 时不覆盖
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "TZ": os.environ.get("TZ") or "JST-9"}
LOCAL_VERSION_FILE = "data/system_version.txt"


# ---------------------------------------------------------------- 基础
def sh(cmd: list[str], timeout: int = 1800, cwd: Path = ROOT, env: dict | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env or ENV)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"超时 {timeout}s：{' '.join(cmd)[:120]}"


def git(*a, timeout: int = 600) -> str:
    code, out = sh(["git", *a], timeout)
    if code != 0:
        raise RuntimeError(f"git {' '.join(a)[:80]} 失败：{out[-400:]}")
    return out


def tail(s: str, n: int = 3) -> str:
    return " ⏎ ".join([x for x in s.strip().splitlines() if x.strip()][-n:])


def sv_tags() -> list[str]:
    tags = [t for t in git("tag", "--list", "sv-*").split() if TAG_RE.match(t)]
    return sorted(tags, key=lambda t: TAG_RE.match(t).groups())


def prev_ref(base: str | None = None) -> str:
    if base:
        return base
    t = sv_tags()
    return t[-1] if t else BASELINE


def next_id(today: str | None = None, tags: list[str] | None = None) -> str:
    today = today or dt.date.today().strftime("%Y%m%d")
    nums = [int(TAG_RE.match(t).group(2)) for t in (tags if tags is not None else sv_tags()) if TAG_RE.match(t).group(1) == today]
    return f"sv-{today}-{(max(nums) + 1 if nums else 1):02d}"


def ref_time(ref: str) -> float:
    try:
        return float(git("log", "-1", "--format=%ct", ref).strip())
    except RuntimeError:
        return 0.0


def pending_changes() -> list[tuple[str, str]]:
    """工作区里（按 .gitignore 口径）还没进版本的改动：[(状态, 路径)]"""
    out = git("status", "--porcelain=v1", "-uall", "-z")
    rows, parts = [], out.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        if len(e) > 3:
            st, path = e[:2], e[3:]
            rows.append((st.strip() or "?", path))
            if st[0] in "RC":
                i += 1
        i += 1
    return rows


# ---------------------------------------------------------------- 闸门
def pick_tests(changed: list[str], root: Path | None = None) -> list[str]:
    root = root or ROOT
    tests = set()
    for f in changed:
        if f.startswith("tests/") and f.endswith(".py") and Path(f).name.startswith("test_") and (root / f).exists():
            tests.add(f)
        elif f.endswith(".py") and f.startswith(("services/", "tools/", "packages/")):
            stem = Path(f).stem
            if stem in ("__init__", "run", "report", "page", "build_jobs", "server", "utils", "common"):
                continue
            tests |= {p.relative_to(root).as_posix() for p in sorted((root / "tests").glob(f"test_*{stem}*.py"))}
    return sorted(tests | {t for t in SMOKE if (root / t).exists()})


def collection_problems(out: str) -> list[str]:
    """pytest 收集阶段的问题（K-OPS-F08）：ERROR collecting <文件> / xdist 各 worker 收集不一致 → 具体文件 / 提示"""
    probs = sorted(set(re.findall(r"ERROR collecting (\S+)", out)))
    if "Different tests were collected between" in out:
        m = re.findall(r"^(?:\+|-)\s*(tests/\S+?)::", out, re.M)
        probs.append("xdist 各 worker 收集不一致" + (("：" + "、".join(sorted(set(m))[:10])) if m else "（收集期间测试或其参数在变）"))
    return probs


# ---------------------------------------------------------------- W22（ISS-1103-145040）：pytest 闸门的输出口径
SUMMARY_RE = re.compile(r"^=*\s*(?:\d+ (?:failed|passed|skipped|errors?|xfailed|xpassed|deselected|warnings?)[, ]*)+.*?in [\d.]+s.*$", re.M)


def norm_nl(s: str) -> str:
    """Windows 子进程写文件是 \\r\\n：re.M 的 $ 不认 \\r → 没有“ - 原因”的 FAILED 行匹配不到（dry #9 没判 flaky 的根因）"""
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def failed_lines(out: str) -> list[str]:
    """全部 `FAILED ...` / `ERROR ...` 简报行（去重、保序）"""
    seen, res = set(), []
    for ln in norm_nl(out).splitlines():
        ln = ln.strip()
        if re.match(r"^(FAILED|ERROR) \S", ln) and ln not in seen:
            seen.add(ln)
            res.append(ln)
    return res


def failed_ids(out: str) -> list[str]:
    """失败用例的 nodeid（FAILED 行，可能带也可能不带“ - 原因”）"""
    return sorted({m.group(1) for m in re.finditer(r"^FAILED (\S+?)(?: - .*)?\s*$", norm_nl(out), re.M)})


def summary_line(out: str) -> str:
    ms = SUMMARY_RE.findall(norm_nl(out))
    return ms[-1].strip("= ").strip() if ms else tail(out, 1)


def pytest_detail(summary: str, failed: list[str], flaky: list[str], rerun: dict | None, log_rel: str | None) -> str:
    """gates[].detail：首跑的全部 FAILED 行 + 首跑合计行 + flaky 名单 + 串行重跑结果 + 完整输出文件"""
    parts = list(failed) + [summary]
    if rerun and not flaky:
        parts.append(f"串行重跑仍不过（code {rerun['code']}）：{rerun.get('still_failed') or rerun['ids']}")
    if flaky:
        parts.append(f"并行偶发、串行通过（flaky）：{flaky}")
    if log_rel:
        parts.append(f"完整输出：{log_rel}")
    return " ⏎ ".join(p for p in parts if p)


def write_pytest_log(out: str, sv: str, log_dir: Path | None = None) -> str | None:
    """完整 pytest 输出落盘 data/system_versions/<sv>_pytest_<n>.txt（n 从 1 递增：同一 sv 的 dry / 正式 cut 各留一份）"""
    d = Path(log_dir or DATA)
    try:
        d.mkdir(parents=True, exist_ok=True)
        k = 1
        while (d / f"{sv}_pytest_{k}.txt").exists():
            k += 1
        f = d / f"{sv}_pytest_{k}.txt"
        f.write_text(out, encoding="utf-8")
    except OSError:  # arch-ok: 落盘失败不拦闸门（detail 里仍有 FAILED 行）
        return None
    try:
        return f.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:  # arch-ok: 测试里 log_dir 在临时目录
        return str(f)


def gates(changed: list[str], run_tests: bool = True, root: Path | None = None, env: dict | None = None,
          sv: str | None = None, log_dir: Path | None = None) -> list[dict]:
    """全部闸门；root / env = 冻结快照目录与快照的 PYTHONPATH（K-OPS-F08：闸门只对快照跑，不对活的工作树跑）；
    sv 给了 = 完整 pytest 输出落盘 log_dir（默认 data/system_versions）/<sv>_pytest_<n>.txt（W22）"""
    rows = []
    root = root or ROOT
    _sh0 = globals()["sh"]

    def sh(cmd, timeout=1800):          # noqa: F811  闸门里的命令一律在快照目录、用快照环境跑
        if env is None and root == ROOT:
            return _sh0(cmd, timeout)
        return _sh0(cmd, timeout, cwd=root, env=env)

    def add(gid, name, ok, detail):
        rows.append({"id": gid, "name": name, "ok": bool(ok), "detail": detail})

    code, out = sh([PY, "tools/qa/syntax_guard.py", "--dry"], 600)
    add("syntax", "全仓语法守卫（K-OPS-C01）", code == 0, tail(out, 2))
    code, out = sh([PY, "tools/knowledge/compile.py", "--check"], 600)
    add("kb", "知识库 compile --check", code == 0, tail(out, 2))
    if (root / "tools/qa/arch_scan.py").exists():      # K-OPS-S01（SYSARCH，总调度 03:0x 批准）：结构问题只许减、不许增
        code, out = sh([PY, "tools/qa/arch_scan.py", "--check"], 600)
        add("arch", "arch_scan --check（K-OPS-S01 棘轮）", code == 0, tail(out, 2))
    if (root / "tools/vqa/regression_check.py").exists():   # VQA 回归集（VQAGATE K-REV-V19，总调度批准接进 cut 闸门）：确定性用例，本机约 1 分钟
        code, out = sh([PY, "tools/vqa/regression_check.py"], 900)
        add("vqa_regress", "VQA 回归集（K-REV-V19）", code == 0, tail(out, 2))
    code, out = sh([PY, "tools/qa/decision_check.py"], 900)
    m = re.search(r"合计 (\d+)：✅ (\d+)\s+❌ (\d+)\s+⏳ (\d+)", out)
    bad = int(m.group(3)) if m else -1
    add("decision", "decision_check（0 ❌，⏳ 可以）", m is not None and bad == 0,
        m.group(0) if m else "没读到合计行：" + tail(out, 2))
    code, out = sh([PY, "tools/qa/decision_propagation.py", "--dry"], 900)
    add("propagation", "decision_propagation（K-OPS-D02）", code == 0, tail(out, 1)[:300])
    if run_tests:
        tests = pick_tests(changed, root)
        n = pytest_n()      # L-162 总调度 11-03：xdist 12 worker 在本机僵死两次，允许用 NS_CUT_PYTEST_N 降并行
        stall_s = xdist_stall_s()

        def _pyt(nn: int) -> list[str]:     # nn <= 0 → 完全不传 -n（进程内串行，不起 xdist worker）
            # W22：-rf = 每个失败用例一行 FAILED（闸门 detail 全部记下，不再只留尾 2 行）
            return [PY, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider", *(["-n", str(nn)] if nn > 0 else []), *tests]

        def _tmo(nn: int) -> int:           # 串行按文件数放大超时（≥ 3600 s，每个文件 30 s）
            return 2400 if nn > 0 else max(3600, 30 * len(tests))

        def _stall(nn: int) -> float | None:  # W22（ISS-1103-145040）：串行一律不判僵死，只认超时（dry #8 被误杀）
            return stall_s if nn > 0 else None
        # W17：xdist 僵死自愈——stall_s 内整棵进程树 CPU 合计 < 1 s 且没有新输出（像 cut B dry #2/#3）→ 杀掉，退到 -n 0 串行重跑一次
        code, out, wst = run_watched(_pyt(n), _tmo(n), cwd=root, env=env or ENV, stall_s=_stall(n))
        out = norm_nl(out)
        heal = None
        if wst.get("stalled") and n > 0:
            n2 = 0
            heal = {"n": n, "stalled_after_s": wst.get("elapsed_s"), "cpu_s": wst.get("cpu_delta"), "window_s": stall_s, "retry_n": n2}
            code, out, w2 = run_watched(_pyt(n2), _tmo(n2), cwd=root, env=env or ENV, stall_s=_stall(n2))
            out = norm_nl(out)
            heal.update(retry_stalled=bool(w2.get("stalled")), retry_code=code)
            out = (f"xdist 僵死自愈：-n {n} 在 {heal['window_s']} s 内进程树 CPU {heal['cpu_s']} s 且无新输出，已杀掉，以 -n {n2} 重试"
                   + ("（重试仍僵死）" if w2.get("stalled") else "") + "\n" + out)
        first_failed, first_sum = failed_lines(out), summary_line(out)
        flaky, rerun = [], None
        if code != 0:   # 并行下的偶发（story_runs 等）：失败的用例串行重跑一次，仍红才算不过
            failed = failed_ids(out)
            coll = collection_problems(out)
            if failed:
                c2, o2 = sh([PY, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider", *failed], 1200)
                o2 = norm_nl(o2)
                rerun = {"ids": failed, "code": c2, "still_failed": failed_ids(o2) if c2 != 0 else [], "summary": summary_line(o2)}
                out = out + "\n---- 失败用例串行重跑（code " + str(c2) + "）----\n" + o2
                if c2 == 0:
                    flaky, code = failed, 0
                    out += "\n串行重跑通过：" + "，".join(failed)
            elif coll:      # K-OPS-F08：收集阶段出错（没有 FAILED 行）——报出具体文件，整组串行重跑一次
                c2, o2 = sh([PY, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider", *tests], 2400)
                out = out + "\n收集问题：" + "；".join(coll) + ("\n串行重跑通过" if c2 == 0 else "\n串行重跑仍不过：" + tail(o2, 3))
                code = c2
        m = re.search(r"(\d+) passed", out)
        log_rel = write_pytest_log(out, sv, log_dir) if sv else None
        add("pytest", f"定向 pytest（{len(tests)} 个文件：改动涉及 + smoke）", code == 0,
            pytest_detail(first_sum, first_failed, flaky, rerun, log_rel))
        rows[-1]["passed"] = int(m.group(1)) if m else 0
        rows[-1]["files"] = tests
        rows[-1]["n"] = n
        rows[-1]["failed"] = first_failed
        rows[-1]["flaky"] = flaky
        if rerun:
            rows[-1]["rerun"] = rerun
        if log_rel:
            rows[-1]["log"] = log_rel
        if heal:
            rows[-1]["xdist_heal"] = heal
    return rows


# ---------------------------------------------------------------- W17 发版配置 / xdist 僵死自愈 / 按清单拼树
RELEASE_CFG_REL = "config/pipeline/release.json"
RELEASE_DEFAULTS = {"enabled": True, "pytest_n": 4, "xdist_stall_min": 10, "hosts": ["gpu33", "gpu36"], "every_s": 60}


def release_cfg(root: Path | None = None) -> dict:
    """config/pipeline/release.json（W17 RELEASE-AUTO）；读不到 = 默认值"""
    try:
        d = json.loads(((root or ROOT) / RELEASE_CFG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 没有配置 = 默认值（enabled=true、pytest_n=4）
        d = {}
    return {**RELEASE_DEFAULTS, **d}


def pytest_n() -> int:
    """cut 定向 pytest 的 xdist 并行数：NS_CUT_PYTEST_N（release_tick 按 release.json pytest_n 设）> min(12, CPU 数)；
    ≤ 0 = 不传 -n（进程内串行）"""
    v = os.environ.get("NS_CUT_PYTEST_N")
    return max(0, int(v)) if v not in (None, "") else min(12, os.cpu_count() or 4)


def xdist_stall_s() -> float:
    v = os.environ.get("NS_CUT_XDIST_STALL_S")
    return float(v) if v else float(release_cfg().get("xdist_stall_min") or 10) * 60


def _proc_table() -> list[tuple[int, int, float]] | None:
    """[(pid, ppid, CPU 秒)]：Windows 一次 CIM 查询；Linux 读 /proc；取不到 = None（不判僵死）"""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,KernelModeTime,UserModeTime | ConvertTo-Json -Compress")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            d = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
        except (OSError, subprocess.TimeoutExpired, ValueError):  # arch-ok: 拿不到进程表 = 本次不判僵死
            return None
        d = [d] if isinstance(d, dict) else d or []
        return [(int(x.get("ProcessId") or 0), int(x.get("ParentProcessId") or 0),
                 (float(x.get("KernelModeTime") or 0) + float(x.get("UserModeTime") or 0)) / 1e7) for x in d]
    out = []
    tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    for p in Path("/proc").glob("[0-9]*"):
        try:
            st = (p / "stat").read_text().rsplit(")", 1)[1].split()
            out.append((int(p.name), int(st[1]), (int(st[11]) + int(st[12])) / tck))
        except (OSError, IndexError, ValueError):  # arch-ok: 进程已退出 / 读不到，跳过
            continue
    return out


def proc_tree_cpu(pid: int, table=None) -> float | None:
    """pid 的所有子孙进程（xdist worker 等）CPU 秒合计；进程表取不到 = None"""
    rows = table if table is not None else _proc_table()
    if rows is None:
        return None
    kids = defaultdict(list)
    for p, pp, c in rows:
        kids[pp].append((p, c))
    tot, stack, seen = 0.0, [pid], {pid}
    while stack:
        for p, c in kids.get(stack.pop(), []):
            if p not in seen:
                seen.add(p)
                tot += c
                stack.append(p)
    return round(tot, 3)


# W37（cut C 前置 P0）：_kill_tree 身份核对。旧实现 `taskkill /PID <pid> /T /F` 按 ParentProcessId 连带杀子孙；Windows pid 会复用，
# 某个更早出生的别人进程（其父 pid 恰好被复用到我们树里）会被 /T “领养”后一起杀掉——11-03 :8800 api_watchdog / autoflow_resident
# 两次被外部 /F 杀的机制（ISS-1103-172328 / 172950；CUTC_PRECHECK ⑦-1）。
KILL_TREE_RULE = (
    "杀前核对：根进程 (pid, 创建时间, 命令行) 必须与 run_watched 启动时记录一致——创建时间落在 [Popen 前 - 2s, Popen 后 + 2s]，"
    "命令行含启动 argv[0] 的文件名；不一致 = 不杀根、记日志。子孙只按自己算的树杀（不用 /T）：某进程算作子进程当且仅当 "
    "ParentProcessId == 父 pid 且 创建时间 ≥ 父的创建时间 且 ≥ 启动时刻 - 2s；比父早出生的 = pid 复用领养的别人进程，不杀、记日志。"
    "进程表取不到 = 只杀我们持有句柄的根进程（Popen.kill），不碰任何别的 pid。最后逐个 taskkill /PID n /F（无 /T）。"
)
_TICKS_EPOCH = 621355968000000000  # .NET DateTime ticks 的 1970-01-01（UTC）
_BORN_SLACK_S = 2.0


def _kill_log(msg: str) -> None:
    print(f"[_kill_tree] {msg}", file=sys.stderr, flush=True)


def _ident_table() -> dict[int, dict] | None:
    """{pid: {ppid, born(unix 秒), cmd}}；取不到 = None"""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine,ExecutablePath,"
              "@{n='Born';e={if($_.CreationDate){$_.CreationDate.ToUniversalTime().Ticks}else{0}}} | ConvertTo-Json -Compress")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # strict=False：别人的进程命令行里带控制字符（tab / 换行）时 ConvertTo-Json 原样输出，默认 json.loads 整表报错
            # → 进程表取不到 → 只杀 .venv 转发器根进程、真正干活的 Python312 子进程活着（AUDIT-RULES 11-05 根因，test_run_watched_kills_stalled_tree）
            d = json.loads(r.stdout.decode("utf-8", "replace") or "[]", strict=False)
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            _kill_log(f"进程表取不到（{e!r}）→ 只杀持有句柄的根进程")
            return None
        d = [d] if isinstance(d, dict) else d or []
        out = {}
        for x in d:
            b = int(x.get("Born") or 0)
            out[int(x.get("ProcessId") or 0)] = {
                "ppid": int(x.get("ParentProcessId") or 0),
                "born": (b - _TICKS_EPOCH) / 1e7 if b else 0.0,
                "cmd": str(x.get("CommandLine") or x.get("ExecutablePath") or "")}
        return out
    try:
        boot = float(next(ln.split()[1] for ln in Path("/proc/stat").read_text().splitlines() if ln.startswith("btime")))
        tck = os.sysconf("SC_CLK_TCK")
    except (OSError, StopIteration, ValueError, IndexError) as e:
        _kill_log(f"/proc/stat 读不到（{e!r}）→ 只杀持有句柄的根进程")
        return None
    out = {}
    for p in Path("/proc").glob("[0-9]*"):
        try:
            st = (p / "stat").read_text().rsplit(")", 1)[1].split()
            cl = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            out[int(p.name)] = {"ppid": int(st[1]), "born": boot + int(st[19]) / tck, "cmd": cl}
        except (OSError, IndexError, ValueError):  # arch-ok: 进程已退出 / 读不到，跳过
            continue
    return out


def _cmd_mark(argv: list[str]) -> str:
    return os.path.basename(str(argv[0])).lower() if argv else ""


def kill_plan(ident: dict, table: dict[int, dict]) -> tuple[list[int], list[str]]:
    """纯函数：按 KILL_TREE_RULE 算出可杀的 pid（子孙在前、根在后）和拒杀日志。
    ident = run_watched 启动时记录 {pid, t0, t1, argv}；table = _ident_table() 的结果"""
    root, refused = int(ident["pid"]), []
    t0 = float(ident["t0"]) - _BORN_SLACK_S
    t1 = float(ident["t1"]) + _BORN_SLACK_S
    mark = _cmd_mark(ident.get("argv") or [])
    r = table.get(root)
    root_ok = False
    if r is None:
        refused.append(f"根 pid {root} 已不在进程表")
    elif not (t0 <= r["born"] <= t1):
        refused.append(f"根 pid {root} 创建时间 {r['born']:.1f} 不在启动窗口 [{t0:.1f}, {t1:.1f}]（pid 复用）：{r['cmd'][:120]}")
    elif mark and mark not in r["cmd"].lower():
        refused.append(f"根 pid {root} 命令行不含启动程序 {mark}：{r['cmd'][:120]}")
    else:
        root_ok = True
    kids: dict[int, list[int]] = defaultdict(list)
    for pid, x in table.items():
        kids[x["ppid"]].append(pid)
    # 根身份不符时它的“子进程”也不认（那是别人的树）；根已退出时，孤儿子孙仍按 ppid + 启动后出生认领
    parent_born = {root: (r["born"] if root_ok else t0)} if (root_ok or r is None) else {}
    order, stack, seen = [], list(parent_born), {root}
    while stack:
        par = stack.pop()
        for k in kids.get(par, []):
            if k in seen:
                continue
            seen.add(k)
            kb = table[k]["born"]
            if kb < parent_born[par] or kb < t0:
                refused.append(f"pid {k} 比父 {par} 早出生（{kb:.1f} < {parent_born[par]:.1f}）= pid 复用领养的别人进程，不杀：{table[k]['cmd'][:120]}")
                continue
            parent_born[k] = kb
            order.append(k)
            stack.append(k)
    pids = list(reversed(order)) + ([root] if root_ok else [])
    return pids, refused


def _kill_tree(pr: subprocess.Popen, ident: dict | None = None, table_fn=None, killer=None) -> dict:
    """按 KILL_TREE_RULE 杀 pr 的进程树；返回 {killed, refused}。ident 缺省 = 只认 pr 本身（我们持有句柄，pid 不会被复用）"""
    ident = ident or {"pid": pr.pid, "t0": 0.0, "t1": time.time(), "argv": []}
    if os.name != "nt" and killer is None and table_fn is None:
        # POSIX：start_new_session=True 时根即进程组长；未 wait 的子进程 pid 不会被复用，进程组只含本次启动的子孙
        try:
            os.killpg(pr.pid, 9)
            return {"killed": [pr.pid], "refused": [], "how": "killpg"}
        except OSError:  # arch-ok: 进程组已不在，退回只杀本进程
            pr.kill()
            return {"killed": [pr.pid], "refused": [], "how": "kill"}
    table = (table_fn or _ident_table)()
    if table is None:
        pr.kill()
        return {"killed": [pr.pid], "refused": ["进程表取不到：只杀根（句柄）"], "how": "handle"}
    pids, refused = kill_plan(ident, table)
    for m in refused:
        _kill_log(m)
    if killer is not None:
        killer(pids)
    elif pids:
        args = ["taskkill", "/F"]
        for p in pids:
            args += ["/PID", str(p)]
        subprocess.run(args, capture_output=True, timeout=60)
    if pr.pid not in pids and pr.poll() is None:
        pr.kill()  # 句柄还在 = 一定是我们的根；身份核对没过也只用句柄杀它自己
    return {"killed": pids, "refused": refused, "how": "plan"}


def run_watched(cmd: list[str], timeout: int, cwd: Path | None = None, env: dict | None = None, stall_s: float | None = 600,
                poll_s: float = 30, cpu_fn=proc_tree_cpu, clock=time.time, sleep=time.sleep) -> tuple[int, str, dict]:
    """跑命令并看着它：stall_s 窗口内进程树 CPU 增量 < 1 s 且输出没有变长 = 僵死 → 杀整棵树，返回 stalled=True；超时 → 124。
    stall_s=None = 不判僵死、只认超时（W22：串行 pytest 等网络 10 分钟 CPU 不动是“慢”，不是僵死）"""
    fd, fn = tempfile.mkstemp(prefix="nsfs_watch_", suffix=".out")
    os.close(fd)
    t0, samples, info = clock(), [], {"stalled": False}
    try:
        with open(fn, "wb") as fo:
            kw = {"start_new_session": True} if os.name != "nt" else {}
            t_spawn = time.time()
            pr = subprocess.Popen(cmd, cwd=cwd or ROOT, env=env or ENV, stdin=subprocess.DEVNULL, stdout=fo, stderr=subprocess.STDOUT, **kw)
            ident = {"pid": pr.pid, "t0": t_spawn, "t1": time.time(), "argv": list(cmd)}
            while True:
                try:
                    code = pr.wait(timeout=poll_s)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = clock()
                if now - t0 > timeout:
                    info["kill"] = _kill_tree(pr, ident)
                    pr.wait(timeout=60)
                    code = 124
                    info["timeout"] = True
                    break
                if stall_s is None:
                    continue
                c = cpu_fn(pr.pid)
                if c is None:
                    continue
                try:
                    osz = os.path.getsize(fn)
                except OSError:  # arch-ok: 读不到输出大小 = 按没变
                    osz = -1
                samples.append((now, c, osz))
                old = [s for s in samples if s[0] <= now - stall_s]
                if old and c - old[-1][1] < 1.0 and osz == old[-1][2]:
                    info["kill"] = _kill_tree(pr, ident)
                    pr.wait(timeout=60)
                    info.update(stalled=True, elapsed_s=round(now - t0, 1), cpu_delta=round(c - old[-1][1], 3))
                    code = 125
                    break
                samples = [s for s in samples if s[0] > now - stall_s - 3 * poll_s] or samples[-1:]
        out = Path(fn).read_bytes().decode("utf-8", "replace")
        if info.get("timeout"):
            out += f"\n超时 {timeout}s：{' '.join(cmd)[:120]}"
        return code, out, info
    finally:
        _unlink_tolerant(Path(fn), info)


def _unlink_tolerant(p: Path, info: dict | None = None, tries: int = 6, wait_s: float = 0.5, sleep=time.sleep) -> bool:
    """删 run_watched 的输出临时文件：Windows 上被杀进程树的残留子进程（.venv 转发器的 Python312 子进程）还握着 stdout 句柄时
    unlink 抛 PermissionError（WinError 32）——清理失败不能把“已判僵死 / 已超时”的结果变成异常；重试几次后留在 %TEMP%，记 info"""
    for _ in range(tries):
        try:
            p.unlink(missing_ok=True)
            return True
        except PermissionError:  # arch-ok: 临时文件被残留子进程占用，稍后重试 / 放弃
            sleep(wait_s)
    if info is not None:
        info["tmp_left"] = str(p)
    return False


def _git_at(repo: Path, env: dict, *a, input_text: str | None = None) -> str:
    r = subprocess.run(["git", *a], cwd=repo, env=env, input=input_text, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)[:80]} 失败：{(r.stdout + r.stderr)[-400:]}")
    return r.stdout


BLOB_ITEM = re.compile(r"^(?P<path>.+)@(?P<blob>[0-9a-f]{7,40})$")


def read_list(list_path: Path) -> list[str]:
    """清单：一行一项，# 开头 / 空行跳过；`path@blob` = 用这个 blob（例：决策表复审通过时的版本），不用工作树此刻的内容"""
    return [ln.strip() for ln in list_path.read_text(encoding="utf-8-sig").splitlines() if ln.strip() and not ln.strip().startswith("#")]


def build_tree_from_list(list_path: Path, base: str = "HEAD", repo: Path | None = None) -> dict:
    """CUT_PLAN_sv17 §1：临时 GIT_INDEX_FILE ← read-tree base → 清单逐项 add（path@blob 走 update-index --cacheinfo；
    工作树没有、base 里有 = 删除）→ write-tree。不碰仓库的 index / HEAD；任何一项不成立就抛错（不跳过、不 -f）"""
    repo = repo or ROOT
    items = read_list(Path(list_path))
    if not items:
        raise RuntimeError(f"清单为空：{list_path}")
    fd, idx = tempfile.mkstemp(prefix="nsfs_release_index_")
    os.close(fd)
    Path(idx).unlink(missing_ok=True)
    env = {**ENV, "GIT_INDEX_FILE": idx}
    try:
        _git_at(repo, env, "read-tree", base)
        add, rm, blobs = [], [], []
        for it in items:
            m = BLOB_ITEM.match(it)
            if m:
                path, blob = m.group("path"), m.group("blob")
                if _git_at(repo, env, "cat-file", "-t", blob).strip() != "blob":
                    raise RuntimeError(f"清单项 {it}：{blob} 不是 blob")
                full = _git_at(repo, env, "rev-parse", blob).strip()
                ls = _git_at(repo, env, "ls-tree", base, "--", path).split()
                mode = ls[0] if ls else "100644"
                _git_at(repo, env, "update-index", "--add", "--cacheinfo", f"{mode},{full},{path}")
                blobs.append({"path": path, "blob": full})
            elif (repo / it).exists():
                add.append(it)
            elif _git_at(repo, env, "ls-files", "--", it).strip():
                rm.append(it)
            else:
                raise RuntimeError(f"清单项 {it}：工作树没有、{base} 里也没有")
        for i in range(0, len(add), 200):
            _git_at(repo, env, "add", "--", *add[i:i + 200])
        for i in range(0, len(rm), 200):
            _git_at(repo, env, "rm", "--cached", "-q", "--", *rm[i:i + 200])
        tree = _git_at(repo, env, "write-tree").strip()
        return {"tree": tree, "base": base, "items": len(items), "added": len(add), "removed": rm, "blobs": blobs}
    finally:
        Path(idx).unlink(missing_ok=True)


def load_manifest_mod():
    """tools/release/manifest.py（交付清单 + 租约；不 import 本模块）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("nsfs_release_manifest", ROOT / "tools/release/manifest.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("nsfs_release_manifest", m)
    spec.loader.exec_module(m)
    return m


def build_tree_from_manifests(ids: list[str], base: str = "HEAD", repo: Path | None = None) -> dict:
    """按交付清单拼树：HEAD + 各清单文件在 manifest-check 时钉住的 blob（复用 build_tree_from_list）"""
    return load_manifest_mod().build_tree_from_manifests(ids, build_tree_from_list, base, repo or ROOT)


def staged_problems(env: dict | None = None) -> list[str]:
    bad = []
    out = gitx(env, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z") if env else git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    names = [x for x in out.split("\0") if x]
    for f in names:
        p = ROOT / f
        low = f.lower()
        if low.startswith("data/") or low.endswith(".local.json") or "/node_modules/" in low:
            bad.append(f"{f}：不该进 git（data / 本地密钥 / node_modules）")
        elif low.endswith(MEDIA_EXT):
            bad.append(f"{f}：媒体 / 模型文件")
        elif p.is_file() and p.stat().st_size > 5 * 1024 * 1024:
            bad.append(f"{f}：{p.stat().st_size / 1e6:.1f} MB（> 5 MB）")
        elif p.is_file() and p.suffix in (".json", ".yaml", ".yml", ".toml", ".py", ".md", ".txt", ".env") and p.stat().st_size < 2_000_000:
            try:
                if SECRET_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
                    bad.append(f"{f}：疑似密钥")
            except OSError:
                pass
    return bad


# ---------------------------------------------------------------- 差异（相对上一版）
def _load_text(text: str, suffix: str):
    if suffix == ".json":
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    if suffix == ".toml":
        import tomllib
        return tomllib.loads(text)
    return None


def _at(ref: str, path: str) -> str | None:
    code, out = sh(["git", "show", f"{ref}:{path}"], 120)
    return out if code == 0 else None


def rules_of(texts: dict[str, str]) -> dict[str, dict]:
    import yaml
    out = {}
    for f, t in texts.items():
        try:
            d = yaml.safe_load(t) or {}
        except Exception:  # noqa: BLE001
            continue
        for r in (d.get("rules") or []) if isinstance(d, dict) else []:
            if isinstance(r, dict) and r.get("id"):
                out[str(r["id"])] = r
    return out


def rule_diff(ref: str, head: str = "HEAD") -> dict:
    def texts(r):
        names = [x for x in git("ls-tree", "-r", "--name-only", r, "--", "knowledge/rules").split() if x.endswith((".yaml", ".yml"))]
        return {n: (_at(r, n) or "") for n in names}
    a, b = rules_of(texts(ref)), rules_of(texts(head))
    arch = lambda r: str(r.get("status", "")) in ("归档", "废弃", "archived", "deprecated") or "⤴" in str(r.get("status", ""))  # noqa: E731
    return {"added": sorted(set(b) - set(a)),
            "modified": sorted(k for k in set(a) & set(b) if a[k] != b[k] and not (arch(b[k]) and not arch(a[k]))),
            "archived": sorted([k for k in set(a) - set(b)] + [k for k in set(a) & set(b) if arch(b[k]) and not arch(a[k])]),
            "total": len(b)}


def _flat(o, p="") -> dict:
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            out.update(_flat(v, f"{p}.{k}" if p else str(k)))
        return out or {p: {}}
    return {p: o}


def config_diff(ref: str, head: str = "HEAD", files: list[str] | None = None, limit: int = 40) -> dict:
    files = files if files is not None else [x for x in git("diff", "--name-only", ref, head, "--", "config").split()
                                             if x.endswith((".json", ".yaml", ".yml", ".toml"))]
    out = {}
    for f in files:
        sa, sb = _at(ref, f), _at(head, f)
        try:
            a = _flat(_load_text(sa, Path(f).suffix)) if sa else {}
            b = _flat(_load_text(sb, Path(f).suffix)) if sb else {}
        except Exception as e:  # noqa: BLE001
            out[f] = {"error": f"{type(e).__name__}: {e}"[:120]}
            continue
        ch = {"added": sorted(set(b) - set(a))[:limit], "removed": sorted(set(a) - set(b))[:limit],
              "changed": [{"key": k, "from": str(a[k])[:80], "to": str(b[k])[:80]} for k in sorted(set(a) & set(b)) if a[k] != b[k]][:limit]}
        if sa is None:
            ch["file"] = "新文件"
        elif sb is None:
            ch["file"] = "删除"
        out[f] = ch
    return out


def code_stats(ref: str, head: str = "HEAD") -> dict:
    mods: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for ln in git("diff", "--numstat", ref, head).splitlines():
        a, d, f = (ln.split("\t") + ["", "", ""])[:3]
        parts = f.split("/")
        key = "/".join(parts[:2]) if parts[0] in ("services", "tools", "packages", "apps", "knowledge", "config", "docs", "tests") else parts[0]
        m = mods[key]
        m[0] += 1
        m[1] += int(a) if a.isdigit() else 0
        m[2] += int(d) if d.isdigit() else 0
    return {k: {"files": v[0], "add": v[1], "del": v[2]} for k, v in sorted(mods.items(), key=lambda kv: -(kv[1][1] + kv[1][2]))}


def owner_decisions(ref: str, head: str = "HEAD") -> list[str]:
    diff = git("diff", "-U0", ref, head, "--", "docs/master/MASTER_PICTURE.md", "config/owner_decisions.yaml")
    ids = []
    for ln in diff.splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            ids += re.findall(r"\b(L-\d{3}[a-z]?|D-[A-Z]+-\d+[a-z]?)\b", ln)
    return sorted(set(ids))


def gate_results(since: float) -> list[dict]:
    out = []
    for f in sorted((ROOT / "data/qa/iter_gate").glob("*.json")):
        if f.stat().st_mtime < since:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"loop": d.get("loop"), "round": d.get("round"), "verdict": d.get("verdict"),
                    "path": f.relative_to(ROOT).as_posix().replace(".json", ".md"), "at": d.get("at")})
    return out


def kb_meta() -> dict:
    m = {}
    try:
        idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
        m["kb_version"], m["rules"] = idx.get("kb_version"), idx.get("n")
    except (OSError, ValueError):
        pass
    return m


def metrics(gate_rows: list[dict], root: Path | None = None, env: dict | None = None) -> dict:
    root = root or ROOT
    m = kb_meta()
    for r in gate_rows:
        if r["id"] == "decision":
            m["decision_check"] = r["detail"]
        if r["id"] == "pytest":
            m["tests_passed"] = r.get("passed")
    code, out = sh([PY, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], 600, cwd=root, env=env)
    c = re.search(r"(\d+) tests? collected", out)
    m["tests_collected"] = int(c.group(1)) if c else None
    code, out = sh([PY, "tools/qa/data_parity.py"], 900, cwd=root, env=env)
    m["data_parity"] = tail(out, 1)[:200]
    return m


# ---------------------------------------------------------------- 记录
def write_index(entry: dict | None = None) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    f = DATA / "index.json"
    try:
        idx = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = {"schema": "nsfs.system_versions/1", "versions": []}
    if entry:
        idx["versions"] = [v for v in idx["versions"] if v["id"] != entry["id"]] + [entry]
    idx["versions"].sort(key=lambda v: v["id"])
    idx["current"] = idx["versions"][-1]["id"] if idx["versions"] else None
    idx["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    DOCS.mkdir(parents=True, exist_ok=True)
    md = ["# 系统版本索引（tools/qa/system_version.py；规则 K-OPS-V01）", "",
          "界面只读接口：`data/system_versions/index.json`（schema nsfs.system_versions/1）。每一版 = git tag，回退见各版文档末尾。", "",
          "| 版本 | 时间 | 提交 | 上一版 | 规则（新增 / 修改 / 归档） | 代码文件 | 测试 | 部署 |", "|---|---|---|---|---|---|---|---|"]
    for v in reversed(idx["versions"]):
        r = v.get("rules", {})
        dep = "、".join(f"{h} {d.get('at', '')[11:16]}" for h, d in (v.get("deployed") or {}).items()) or "—"
        md.append(f"| [{v['id']}]({v['id']}.md) | {v.get('at', '')[:16]} | {v.get('commit', '')[:7]} | {v.get('prev', '')} | "
                  f"{len(r.get('added', []))} / {len(r.get('modified', []))} / {len(r.get('archived', []))} | {v.get('files_changed', '')} | "
                  f"{v.get('metrics', {}).get('tests_passed', '')} | {dep} |")
    (DOCS / "INDEX.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return idx


def version_md(sv: str, prev: str, gates_rows: list[dict], rd: dict, cd: dict, cs: dict, gr: list[dict],
               dec: list[str], mt: dict, changed: list[tuple[str, str]], loops_line: str) -> str:
    L = [f"# 系统版本 {sv}", "", f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}；上一版：{prev}；git tag `{sv}`",
         f"- 由来：项目方 11-01 22:5x“每一次迭代都是用 override system,然后用 create a new version 那个 system versions”（K-OPS-V01）",
         f"- 本版包含：{loops_line or '—'}", f"- 改动文件 {len(changed)} 个（按 .gitignore 口径）", "",
         "## 闸门", "", "| 项 | 结果 | 说明 |", "|---|---|---|"]
    L += [f"| {g['name']} | {'通过' if g['ok'] else '**不通过**'} | {g['detail'].replace('|', '／')[:300]} |" for g in gates_rows]
    L += ["", "## 规则（相对上一版）", "", f"- 新增 {len(rd['added'])}：{'、'.join(rd['added']) or '—'}",
          f"- 修改 {len(rd['modified'])}：{'、'.join(rd['modified']) or '—'}", f"- 归档 {len(rd['archived'])}：{'、'.join(rd['archived']) or '—'}",
          f"- 规则总数 {rd['total']}；kb 版本 {mt.get('kb_version')}", "", "## 配置（键级）", ""]
    if not cd:
        L.append("- 无")
    for f, c in cd.items():
        if "error" in c:
            L.append(f"- `{f}`：解析失败 {c['error']}")
            continue
        L.append(f"- `{f}`{('（' + c['file'] + '）') if c.get('file') else ''}：新增 {len(c['added'])}、删除 {len(c['removed'])}、改值 {len(c['changed'])}")
        for k in c["added"][:12]:
            L.append(f"  - + `{k}`")
        for k in c["removed"][:12]:
            L.append(f"  - − `{k}`")
        for x in c["changed"][:12]:
            L.append(f"  - ~ `{x['key']}`：{x['from']} → {x['to']}")
    L += ["", "## 代码（按模块）", "", "| 模块 | 文件 | +行 | −行 |", "|---|---|---|---|"]
    L += [f"| {k} | {v['files']} | {v['add']} | {v['del']} |" for k, v in list(cs.items())[:40]]
    L += ["", "## 本轮各 loop 的 iter_gate 结果", ""]
    L += [f"- {g['loop']} {g['round']}：{g['verdict']}（{g['path']}）" for g in gr] or ["- 无"]
    L += ["", "## 项目方 / 总调度决定（本版新入账）", "", f"- {'、'.join(dec) or '—'}", "", "## 关键指标", ""]
    L += [f"- {k}：{v}" for k, v in mt.items()]
    L += ["", "## 回退", "", "只预览（不执行）：`.venv/Scripts/python.exe tools/qa/system_version.py rollback " + prev + "`", "",
          "```", f"git diff --stat {sv} {prev}", f"git checkout {prev} -- .        # 跟踪文件回到上一版（未跟踪 / 忽略的数据不动）",
          f".venv/Scripts/python.exe tools/qa/system_version.py deploy {prev}", "```", ""]
    return "\n".join(L)


def loops_since(gr: list[dict]) -> str:
    by = defaultdict(list)
    for g in gr:
        by[g["loop"]].append(f"{g['round']}({g['verdict']})")
    return "；".join(f"{k} {'、'.join(v)}" for k, v in sorted(by.items()))


# ---------------------------------------------------------------- 命令
# ---------------------------------------------------------------- 冻结窗口 + 快照（K-OPS-F08，总调度 02:1x）
CUT_LOCK = DATA / "cut_lock.json"
SNAP_BASE = Path(os.environ.get("NS_CUT_SNAPSHOTS") or (Path(ROOT.anchor) / "nsfs_cut_snapshots"))
CUT_LOCK_TTL_S = 45 * 60
PY_PATHS = ("packages/schema", "services/agent", "services/api", "services/orchestrator", "services/render_router",
            "services/recipes", "services/post")


LOCK_HISTORY = DATA / "lock_history.jsonl"
FREEZE_DRIFT = ROOT / "data/rsi/freeze_drift.jsonl"
FROZEN_TOP = ("tools/", "services/", "packages/", "config/", "knowledge/", "ops/", "tests/", "apps/")


def quiet_since(seconds: float = 60, max_wait: float = 600, sleep=time.sleep, clock=time.time) -> dict:
    """预冻结（SYSARCH §9 / K-OPS-F08 修订）：冻结目录里改动过的文件，最近一次 mtime 距今 ≥ seconds 才返回（最多等 max_wait）。
    写到一半的文件要么在这之前写完，要么被冻结锁拦下，不会再被拍进冻结树（11-02 sv-09 owner_queue.py 事故）"""
    t0 = clock()
    last = None
    while True:
        latest, who = 0.0, None
        for _st, path in pending_changes():
            if not path.startswith(FROZEN_TOP):
                continue
            try:
                m = (ROOT / path).stat().st_mtime
            except OSError:
                continue
            if m > latest:
                latest, who = m, path
        age = clock() - latest if latest else 1e9
        last = {"quiet_s": round(min(age, 1e6), 1), "last_file": who, "waited_s": round(clock() - t0, 1)}
        if age >= seconds or clock() - t0 >= max_wait:
            last["ok"] = age >= seconds
            return last
        sleep(min(10, seconds - age + 1))


LOCKS_MD = ROOT / "docs/uimaster/LOCKS.md"
LOCKS_MD_REL = "docs/uimaster/LOCKS.md"
LOCK_BEGIN, LOCK_END = "<!-- SV-CUT-LOCK:BEGIN（system_version cut 自动维护，勿手改） -->", "<!-- SV-CUT-LOCK:END -->"
LOCK_DIRS_MAIN = ("services/", "tools/", "tests/")


def locks_md_block(rec: dict | None) -> str:
    """LOCKS.md 里的发版冻结锁区块（总调度 11-03：cut 期间写入锁和 LOCKS.md 打通，别的 agent 改文件前看 LOCKS.md 就能看到、主动让路）。
    未冻结时是固定文字（不带时间戳），这样提交进版本的内容和 cut 结束后的工作树一致，不会每次都多出一个改动"""
    head = "## 发版冻结锁（system_version cut）"
    how = ("查询：`.venv/Scripts/python.exe tools/qa/system_version.py lock-status`（退出码 3 = 冻结中）；"
           "锁文件 data/system_versions/cut_lock.json；规则 K-OPS-F08")
    if rec and rec.get("active"):
        exp = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(rec.get("expires_t") or 0)))
        others = " ".join(x for x in FROZEN_TOP if x not in LOCK_DIRS_MAIN)
        lines = ["| 状态 | 版本 | 持锁进程 | 最晚到期 |", "|---|---|---|---|",
                 f"| 🔒 冻结中 | {rec.get('sv') or '-'} | pid {rec.get('pid')} | {exp} |", "",
                 f"**{' '.join(LOCK_DIRS_MAIN)}（以及 {others}）现在不要改。**改了也不会进这一版，还可能让发版闸门失败；"
                 "等这里变回“未冻结”再动手。" + how]
    else:
        lines = ["| 状态 |", "|---|", "| 未冻结（cut 开始时这里会自动改成冻结状态） |", "",
                 "改 " + " ".join(LOCK_DIRS_MAIN) + " 前先看这一块。" + how]
    return "\n".join([LOCK_BEGIN, head, "", *lines, LOCK_END])


def locks_md_text(text: str, rec: dict | None) -> str:
    """把冻结锁区块写进 LOCKS.md 文本：已有区块就整块替换；没有就插在“## 临时锁”前（找不到就接在文件末尾）。其余内容一字不动"""
    nl = "\r\n" if "\r\n" in text else "\n"
    blk = locks_md_block(rec).replace("\n", nl)
    i, j = text.find(LOCK_BEGIN), text.find(LOCK_END)
    if i >= 0 and j > i:
        return text[:i] + blk + text[j + len(LOCK_END):]
    k = text.find("## 临时锁")
    if k >= 0:
        return text[:k] + blk + nl + nl + text[k:]
    return text.rstrip() + nl + nl + blk + nl


def sync_locks_md(rec: dict | None, path: Path | None = None) -> str:
    """cut_lock 每次变化都同步到 LOCKS.md（原子替换）。失败不拦 cut（锁文件仍是权威），返回 ok / 错误原因写进锁记录"""
    path = path or LOCKS_MD
    try:
        raw = path.read_bytes().decode("utf-8") if path.exists() else "# 文件锁（UIMASTER 维护）\n"
        new = locks_md_text(raw, rec)
        if new != raw:
            tmp = path.with_name(path.name + ".svlock.tmp")
            tmp.write_bytes(new.encode("utf-8"))
            os.replace(tmp, path)
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:200]


def index_locks_md_inactive(env: dict, root: Path | None = None, rel: str = LOCKS_MD_REL) -> str | None:
    """冻结树里的 LOCKS.md 一律是“未冻结”版本（cut 期间工作树里是 🔒，不能把冻结状态提交进版本）。返回写入的 blob sha"""
    root = root or ROOT
    f = root / rel
    if not f.exists():
        return None
    fd, tn = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    try:
        Path(tn).write_bytes(locks_md_text(f.read_bytes().decode("utf-8"), None).encode("utf-8"))
        code, out = sh(["git", "hash-object", "-w", "--path", rel, tn], 120, cwd=root, env=env)
        if code != 0:
            raise RuntimeError(f"git hash-object 失败：{out[-300:]}")
        sha = out.strip().splitlines()[-1]
        code, out = sh(["git", "update-index", "--add", "--cacheinfo", f"100644,{sha},{rel}"], 120, cwd=root, env=env)
        if code != 0:
            raise RuntimeError(f"git update-index 失败：{out[-300:]}")
        return sha
    finally:
        Path(tn).unlink(missing_ok=True)


def cut_lock(active: bool, sv: str | None = None, note: str = "") -> dict:
    """data/system_versions/cut_lock.json：cut 进行中 = active=true（到期自动失效）。各 agent 写代码 / 规则 / 配置前先看它
    （tools/qa/system_version.py lock-status；规则 K-OPS-F08）。结束时改回 active=false（不删文件）"""
    DATA.mkdir(parents=True, exist_ok=True)
    rec = {"active": bool(active), "sv": sv, "pid": os.getpid(), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "expires_t": time.time() + CUT_LOCK_TTL_S if active else None, "note": note,
           "rule": "K-OPS-F08：active 期间不要改 tools/ services/ packages/ config/ knowledge/ ops/ tests/（改了也不会进这一版，进下一版）"}
    tmp = CUT_LOCK.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, CUT_LOCK)
    rec["locks_md"] = sync_locks_md(rec)            # 总调度 11-03：和 docs/uimaster/LOCKS.md 打通（锁文件写完再同步，锁文件是权威）
    with open(CUT_LOCK.parent / "lock_history.jsonl", "a", encoding="utf-8") as f:     # SYSARCH iter_gate F1：冻结窗口内的写入判 fail
        f.write(json.dumps({"sv": sv, "event": "start" if active else "end", "at": rec["at"], "t": time.time(), "pid": os.getpid(),
                            "note": note}, ensure_ascii=False) + "\n")
    return rec


CUT_LOCK_RENEW_S = 5 * 60


def cut_lock_renew(sv: str | None, pid: int | None = None) -> bool:
    """W17b P1-4（A17 第 28 轮）：cut 进行中续期 cut_lock（expires_t = 现在 + TTL）。只续自己的锁（active、同 sv、同 pid）；
    别人的锁 / 已结束的锁不动。不写 lock_history（start / end 事件不变）"""
    try:
        d = json.loads(CUT_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 锁文件读不到 = 不续（cut 结束时 cut_lock(False) 会重写）
        return False
    if not d.get("active") or d.get("sv") != sv or int(d.get("pid") or 0) != int(pid or os.getpid()):
        return False
    d["expires_t"] = time.time() + CUT_LOCK_TTL_S
    d["renewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tmp = CUT_LOCK.with_suffix(".renew.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, CUT_LOCK)
    return True


def start_cut_lock_renewer(sv: str | None, every_s: float = CUT_LOCK_RENEW_S):
    """后台线程每 every_s 续期一次；返回 stop()。stop() 与续期互斥：stop() 返回后不会再有续期写入
    （否则续期可能盖掉随后 cut_lock(False) 写的 active=false）"""
    import threading
    ev, mu, pid = threading.Event(), threading.Lock(), os.getpid()

    def _loop():
        while not ev.wait(every_s):
            with mu:
                if ev.is_set():
                    return
                try:
                    cut_lock_renew(sv, pid)
                except OSError:  # arch-ok: 续期失败下一轮再试（最坏 = 退回 45 分钟 TTL 的旧行为）
                    pass

    def stop() -> None:
        with mu:
            ev.set()
    threading.Thread(target=_loop, name=f"cut_lock_renew:{sv}", daemon=True).start()
    return stop


def cut_locked(now: float | None = None) -> dict | None:
    try:
        d = json.loads(CUT_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if d.get("active") and float(d.get("expires_t") or 0) > (now or time.time()) else None


def gitx(env: dict, *a, timeout: int = 600) -> str:
    code, out = sh(["git", *a], timeout, env=env)
    if code != 0:
        raise RuntimeError(f"git {' '.join(a)[:80]} 失败：{out[-400:]}")
    return out


def freeze_tree(idx_file: Path) -> tuple[str, dict]:
    """用独立的 index 文件把此刻的工作树（.gitignore 口径）写成一棵 git 树——之后别人再改文件，这一版的内容也不变"""
    env = {**ENV, "GIT_INDEX_FILE": str(idx_file)}
    gitx(env, "read-tree", "HEAD")
    gitx(env, "add", "-A")
    index_locks_md_inactive(env)                    # LOCKS.md 此刻是 🔒 冻结中，进版本的要是“未冻结”版本
    return gitx(env, "write-tree").strip(), env


def ignored_paths() -> list[str]:
    out = git("status", "--ignored", "--porcelain=v1", "-z")
    return [e[3:].rstrip("/") for e in out.split("\0") if e.startswith("!! ")]


def _link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.is_dir():
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], capture_output=True, check=True)
        else:
            os.symlink(src, dst, target_is_directory=True)
    else:
        try:
            os.link(src, dst)
        except OSError:
            import shutil
            shutil.copy2(src, dst)


HARDLINK_TOP = ("data", "assets", "golden")
JUNCTION_OK = ("node_modules", "models_cache", "apps/web/dist")


# W22 P0：快照不带 pid / 锁 / 常驻心跳文件——快照里的测试读到它们就会拿到生产进程的 pid（15:30 autoflow_resident 被杀）
LIVE_PID_RE = re.compile(r"(\.pid|\.pid\.json|\.lock|_pid\.json)$|^autoflow_resident\.json$|^api_restart\.json$", re.I)


def _hardlink_tree(src: Path, dst: Path) -> int:
    n = 0
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d not in ("__pycache__", "node_modules")]
        rel = Path(dp).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in fns:
            if LIVE_PID_RE.search(f):
                continue
            try:
                os.link(Path(dp) / f, dst / rel / f)
                n += 1
            except OSError:
                pass
    return n


def _hardlink_tree_missing(src: Path, dst: Path) -> int:
    n = 0
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d not in ("__pycache__", "node_modules")]
        rel = Path(dp).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in fns:
            t = dst / rel / f
            if LIVE_PID_RE.search(f) or t.exists():
                continue
            try:
                os.link(Path(dp) / f, t)
                n += 1
            except OSError:
                pass
    return n


CODE_TOP = ("tools/", "services/", "packages/", "config/", "knowledge/", "ops/", "tests/")
CODE_EXT = (".py", ".sh", ".ps1", ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".cube", ".service", ".timer", ".mjs", ".ts", ".tsx")


def ignored_code_files() -> list[str]:
    """ARCH_MAP #1（总调度 03:0x）：代码目录里被 .gitignore 挡住、永远进不了版本的代码类文件（缓存 / 日志 / *.local.json 除外）。
    非空 → cut 阻断并列出（要么改 .gitignore 收进来，要么挪出代码目录）"""
    out = git("status", "--ignored", "--porcelain=v1", "-uall", "-z")
    files = [e[3:] for e in out.split("\0") if e.startswith("!! ")]
    return sorted(f for f in files if f.startswith(CODE_TOP) and f.endswith(CODE_EXT)
                  and "__pycache__" not in f and ".pytest_cache" not in f and not f.startswith("ops/logs/")
                  and not f.endswith(".local.json"))


def untracked_code_after(tree: str) -> list[str]:
    """提交后仍未跟踪的代码文件 = 冻结之后才出现的（进下一版）；冻结时就在的未跟踪文件已由 git add -A 收进冻结树"""
    left = [x for x in git("ls-files", "--others", "--exclude-standard", "-z").split("\0") if x]
    return sorted(f for f in left if f.startswith(CODE_TOP))


def build_snapshot(tree: str, dest: Path) -> dict:
    """快照目录 = 冻结树的完整导出（代码 / 测试 / 配置 / 规则 / 文档）+ 被忽略的数据（data/、assets 图片、模型缓存……）以
    目录联接 / 硬链接接到工作树（闸门要读真实数据；数据不进版本）"""
    import shutil
    if dest.exists():
        shutil.move(str(dest), str(dest) + f".old{int(time.time())}")
    dest.mkdir(parents=True)
    raw = subprocess.run(["git", "archive", "--format=tar", tree], cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dest, filter="fully_trusted") if hasattr(tarfile, "fully_trusted_filter") else tf.extractall(dest)
        n = sum(1 for m in tf.getmembers() if m.isfile())
    linked = 0
    for rel in ignored_paths():
        if rel.startswith((".git", ".venv", ".pytest_cache", "nsfs_cut_snapshots")) or "__pycache__" in rel or rel.endswith(".pyc")                 or rel.endswith("_selftest_take"):
            continue
        src = ROOT / rel
        if not src.exists():
            continue
        if (dest / rel).exists():
            if src.is_dir() and (dest / rel).is_dir() and not (dest / rel).is_symlink():
                linked += _hardlink_tree_missing(src, dest / rel)     # 树里带了该目录的少量文件：补链其余（原先整目录被跳过）
            continue
        if src.is_dir() and not rel.endswith(JUNCTION_OK):    # 默认逐文件硬链接（resolve 不跳出快照）；只有超大且没人 resolve 的目录用联接
            linked += _hardlink_tree(src, dest / rel)       # 数据目录逐文件硬链接：路径 resolve 仍落在快照里（目录联接会跳回工作树）
        else:
            _link(src, dest / rel)
            linked += 1
    env = {**ENV, "PYTHONPATH": os.pathsep.join(str(dest / x) for x in PY_PATHS)}
    return {"dir": str(dest), "files": n, "linked": linked, "env": env}


def load_remote_gates():
    """W45：tools/qa/remote_gates.py（cut 七门在 gpu33 上跑）"""
    return sys.modules.get("ns_remote_gates_sv") or _load_mod(ROOT / "tools/qa/remote_gates.py", "ns_remote_gates_sv")


def _load_mod(path: Path, name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def gates_on(on: str | None = None) -> str | None:
    """W45：闸门在哪跑。--on（"local" = 本机）> 环境变量 NS_CUT_ON > release.json gates_on > 本机。→ 主机名或 None（本机）"""
    v = on if on not in (None, "") else (os.environ.get("NS_CUT_ON") or release_cfg().get("gates_on") or "local")
    return None if str(v).lower() in ("local", "laptop", "none", "off") else str(v)


def run_on_server(tree: str, sv: str, changed: list[str], run_tests: bool, dry: bool, on: str | None) -> tuple[tuple | None, dict]:
    """W45：on = 主机 → remote_gates（服务器快照 + 七门 + 耗时）→ ((快照信息, 闸门行), 附加报告字段)；on = None → (None, {})。
    服务器基础设施失败 → release.json gates_on_fallback："local"（默认：返回 None，cut 退回本机并记 gates_on_fallback）/ "fail"（失败关闭）"""
    if not on:
        return None, {}
    r = load_remote_gates().remote_cut_gates(tree, sv, changed, run_tests, want_metrics=not dry, host=on, sv=sys.modules[__name__])
    if not r.get("error"):
        return (r["snapshot"], r["gates"]), {"gates_on": on, "gate_timings": r.get("timings"), "gates_s": r.get("gates_s"),
                                             "gates_wall_s": r.get("wall_s"), "remote_metrics": r.get("metrics"), "remote_job": r.get("job")}
    extra = {"gates_on_fallback": f"{on} 不可用 → 本机：{r['error'][:400]}"}
    if str(release_cfg().get("gates_on_fallback") or "local") == "fail":
        return ({}, [{"id": "remote", "name": f"闸门在 {on} 上跑（W45）", "ok": False, "detail": r["error"][:600]}]), extra
    return None, extra


CUT_MUTEX = DATA / "cut.mutex"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":       # Windows 的 os.kill(pid, 0) 会真的发信号，只能用 tasklist
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
            return str(pid) in (r.stdout or "")
        except (OSError, subprocess.TimeoutExpired):  # arch-ok: 查不到当作还活着（宁可拒绝，不抢锁）
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cut_mutex_acquire(mutex: Path | None = None) -> tuple[bool, str]:
    """全局 cut 互斥（REVIEW-C 🔴）：O_CREAT|O_EXCL 建锁文件记 pid；已有锁且持有者还活着 = 拒绝；持有者已死 = 清掉重建"""
    mutex = mutex or CUT_MUTEX
    mutex.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(mutex), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                owner = int((mutex.read_text(encoding="utf-8").strip() or "0").split()[0])
            except (OSError, ValueError, IndexError):  # arch-ok: 锁文件读不出 pid = 当作有人持有，拒绝
                return False, "cut.mutex 存在但读不出持有者 pid"
            if owner != os.getpid() and _pid_alive(owner):
                return False, f"另一个 cut 正在进行（pid {owner}，{mutex}）"
            mutex.unlink(missing_ok=True)       # 持有者已死 = 陈旧锁
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
        return True, ""
    return False, "cut.mutex 抢不到"


def cut(base: str | None = None, dry: bool = False, sv: str | None = None, run_tests: bool = True, tree: str | None = None,
        on: str | None = None) -> dict:
    """发版入口：全局互斥（cut_lock 有别的活进程在冻结 → 拒绝；再抢 cut.mutex）→ 指定 --id 时核对 tag 不存在 → _cut_impl。
    拒绝时 rc 3（main 里 out['rc']）"""
    lk = cut_locked()
    if lk and int(lk.get("pid") or 0) != os.getpid() and _pid_alive(int(lk.get("pid") or 0)):
        return {"ok": False, "rc": 3, "reason": f"别的 cut 正在冻结中（pid {lk.get('pid')}，sv {lk.get('sv')}）"}
    ok, why = cut_mutex_acquire()
    if not ok:
        return {"ok": False, "rc": 3, "reason": why}
    try:
        if sv and sv in sv_tags():
            return {"ok": False, "rc": 3, "id": sv, "reason": f"tag {sv} 已存在，不覆盖"}
        return _cut_impl(base, dry, sv, run_tests, tree, on)
    finally:
        CUT_MUTEX.unlink(missing_ok=True)


def _cut_impl(base: str | None = None, dry: bool = False, sv: str | None = None, run_tests: bool = True, tree: str | None = None,
        on: str | None = None) -> dict:
    """发版（K-OPS-V01 / K-OPS-F08）：冻结窗口 → 冻结树 → 快照 → 闸门全部对快照跑 → 提交冻结树（不是此刻的工作树）→ tag。
    cut 期间别的 agent 改的文件不进这一版、也不会让闸门失败（留给下一版）"""
    prev = prev_ref(base)
    sv = sv or next_id()
    changed = pending_changes()
    files = [p for _s, p in changed]
    if not changed and not git("diff", "--name-only", prev, "HEAD").strip():
        return {"ok": False, "reason": "相对上一版没有任何改动，不发版"}
    os.environ["NS_FREEZE_EXEMPT"] = "1"              # SYSARCH 冻结锁第 2 层：cut 自己和它起的子进程（git / pytest / compile）豁免
    cut_lock(True, sv, "预冻结：等冻结目录 60 s 无改动")
    renew_stop = start_cut_lock_renewer(sv)           # W17b P1-4：cut 可能超过 45 分钟 TTL（xdist 自愈 ≈ 78 分钟），跑多久续多久
    if not tree:
        q = quiet_since(60)
        if not q.get("ok"):
            renew_stop()
            cut_lock(False, sv, "预冻结超时：冻结目录一直有人在改")
            return {"ok": False, "id": sv, "prev": prev, "reason": f"预冻结 10 分钟内冻结目录没安静下来（最后改动 {q.get('last_file')}）"}
    idx_fd, idx_name = tempfile.mkstemp(prefix="nsfs_cut_index_")
    os.close(idx_fd)
    idx_file = Path(idx_name)
    idx_file.unlink(missing_ok=True)
    rep = {"id": sv, "prev": prev}
    try:
        ign = ignored_code_files()
        if ign:
            rep.update(ok=False, reason="代码目录里有被 .gitignore 挡住、进不了版本的代码文件（ARCH_MAP #1）：" + "、".join(ign[:20]))
            return rep
        if tree:     # 指定冻结树（例：在上一次冻结树上做总调度批准的最小改动，不从工作树重拍，避免带入冻结期间的未审改动）
            ienv = {**ENV, "GIT_INDEX_FILE": str(idx_file)}
            gitx(ienv, "read-tree", tree)
            rep["tree_given"] = True
        else:
            tree, ienv = freeze_tree(idx_file)
        frozen = [x for x in gitx(ienv, "diff", "--cached", "--name-only", "HEAD").split("\n") if x]
        srv, extra = run_on_server(tree, sv, frozen or files, run_tests, dry, gates_on(on))   # W45：默认在 gpu33 上跑
        if srv:
            snap, g = srv
        else:
            snap = build_snapshot(tree, SNAP_BASE / sv)
            t_g = time.time()
            g = gates(frozen or files, run_tests, root=Path(snap["dir"]), env=snap["env"], sv=sv)
            extra.update(gates_on="local", gates_s=round(time.time() - t_g, 1))
        rep.update(tree=tree, snapshot={k: v for k, v in snap.items() if k != "env"}, frozen_files=len(frozen), **extra)
        rep["gates"] = g
        plog = next((x["log"] for x in g if x.get("log")), None)
        if plog:                                         # W22：cut_lock note 引用完整 pytest 输出
            rep["pytest_log"] = plog
        heal = next((x["xdist_heal"] for x in g if x.get("xdist_heal")), None)
        if heal:                                         # W17：xdist 僵死自愈记进 cut 报告
            rep["xdist_heal"] = heal
        fails = [x for x in g if not x["ok"]]
        if fails:
            rep.update(ok=False, reason="闸门不过：" + "；".join(f"{x['name']}：{x['detail'][:200]}" for x in fails))
            return rep
        since = ref_time(prev)
        gr = gate_results(since)
        loops_line = loops_since(gr)
        if dry:
            rep.update(ok=True, dry=True, changed=len(frozen), loops=loops_line)
            return rep
        probs = staged_problems(ienv)
        if probs:
            rep.update(ok=False, reason="冻结树里有不该进 git 的文件：" + "；".join(probs[:10]))
            return rep
        rd, cd, cs = rule_diff(prev, tree), config_diff(prev, tree), code_stats(prev, tree)
        dec = owner_decisions(prev, tree)
        mt = ({**(extra.get("remote_metrics") or {}), **kb_meta()} if extra.get("gates_on") not in (None, "local")
              else metrics(g, Path(snap["dir"]), snap["env"]))
        DOCS.mkdir(parents=True, exist_ok=True)
        chg = [("M", f) for f in frozen]
        (DOCS / f"{sv}.md").write_text(version_md(sv, prev, g, rd, cd, cs, gr, dec, mt, chg, loops_line), encoding="utf-8")
        entry = {"id": sv, "prev": prev, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files_changed": len(frozen),
                 "rules": rd, "config_files": sorted(cd), "code": cs, "gates": [{k: x[k] for k in ("id", "ok", "detail")} for x in g],
                 "iter_gate": gr, "decisions": dec, "metrics": mt, "doc": f"docs/system_versions/{sv}.md", "deployed": {},
                 "tree": tree, "drift_during_cut": None}
        idx = write_index(entry)
        gitx(ienv, "add", "-A", "docs/system_versions")          # 文档进冻结树（只加文档，别的文件仍是冻结时刻的内容）
        tree2 = gitx(ienv, "write-tree").strip()
        msg = [f"{sv}：系统版本（K-OPS-V01）", "",
               "项目方 11-01 22:5x：“每一次迭代都是用 override system,然后用 create a new version 那个 system versions”",
               f"上一版：{prev}；改动文件 {len(frozen)}；规则 +{len(rd['added'])} ~{len(rd['modified'])} 归档 {len(rd['archived'])}；kb {mt.get('kb_version')}",
               f"本版包含的 loop 轮次：{loops_line or '—'}", f"项目方 / 总调度决定：{'、'.join(dec) or '—'}",
               f"闸门（冻结快照上跑，K-OPS-F08）：{'；'.join(x['name'] + ' 通过' for x in g)}", f"记录：docs/system_versions/{sv}.md", "", CO_AUTHOR]
        fd, mfn = tempfile.mkstemp(suffix=".txt")
        os.close(fd)                 # Windows：不关 fd，之后 unlink 报 WinError 32（sv-20261101-01 首跑踩到）
        mf = Path(mfn)
        mf.write_text("\n".join(msg) + "\n", encoding="utf-8")
        try:
            old_head = git("rev-parse", "HEAD").strip()
            commit = git("commit-tree", tree2, "-p", old_head, "-F", str(mf)).strip()
        finally:
            mf.unlink(missing_ok=True)
        branch = git("symbolic-ref", "HEAD").strip()
        git("update-ref", branch, commit, old_head)              # 比较并交换：期间有人另行提交就失败，不覆盖
        git("reset", "-q")                                        # 只同步 index 到新 HEAD；工作树不动（cut 期间别人的改动留作下一版）
        git("tag", "-a", sv, "-m", f"{sv} 系统版本（上一版 {prev}）", commit)
        drift = [p for _s, p in pending_changes() if not p.startswith("docs/system_versions/")]
        late = untracked_code_after(tree)
        if drift:     # SYSARCH §9 第 4 层：冻结期间有改动的文件进 cut 报告 + 账本（SENTINEL 探针按它开工单，负责方 = 文件负责方）
            FREEZE_DRIFT.parent.mkdir(parents=True, exist_ok=True)
            with open(FREEZE_DRIFT, "a", encoding="utf-8") as f:
                f.write(json.dumps({"sv": sv, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": drift[:200]}, ensure_ascii=False) + "\n")
            rep["drift_files"] = drift[:50]
        entry.update(commit=commit, drift_during_cut=len(drift), untracked_code_after_cut=late[:50])
        entry["state_snapshot"] = take_state_snapshot(sv)    # K-OPS-X06（DISTILL）：决策 / 配置 / 运行状态快照，回退时可还原
        entry["remote_push"] = push_remote(prev, sv)          # 总调度 23:0x：发版后推 GitHub（失败不影响发版，记下来）
        write_index(entry)
        rep.update(ok=True, commit=commit, doc=entry["doc"], rules=rd, files=len(frozen), current=idx.get("current"),
                   remote_push=entry["remote_push"], state_snapshot=entry["state_snapshot"], drift_during_cut=len(drift),
                   untracked_code_after_cut=late[:50])
        return rep
    finally:
        renew_stop()
        idx_file.unlink(missing_ok=True)
        cut_lock(False, sv, "cut 结束：" + ("成功" if rep.get("ok") else str(rep.get("reason") or "失败")[:200])
                 + (f"；pytest 完整输出 {rep['pytest_log']}" if rep.get("pytest_log") else ""))


PUSH_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{24,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|"
                            r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|xox[bp]-[A-Za-z0-9-]{20,}|"
                            r"\"(?:api_?key|secret|password|token)\"\s*:\s*\"[A-Za-z0-9_\-]{16,}\")", re.I)


def secret_hits(prev: str, head: str = "HEAD") -> list[str]:
    """推远端前的密钥扫描：本次提交新增的行（git diff prev..head 的 + 行）"""
    hits, cur = [], None
    for ln in git("diff", "-U0", "--no-color", prev, head).splitlines():
        if ln.startswith("+++ "):
            cur = ln[6:] if ln.startswith("+++ b/") else ln[4:]
        elif ln.startswith("+") and PUSH_SECRET_RE.search(ln):
            hits.append(f"{cur}: {PUSH_SECRET_RE.search(ln).group(0)[:12]}…")
    return hits


def push_remote(prev: str, sv: str) -> dict:
    """项目方 23:0x 授权（仅限发版流程）：commit + tag 后 git push origin <分支> --follow-tags。推前密钥扫描，命中不推、报警
    （data/qa/alerts.jsonl）；推送失败不影响发版，结果记进 index.json"""
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    code, out = sh(["git", "remote", "get-url", "origin"], 60)
    if code != 0:
        return {"at": at, "ok": False, "skipped": "没有 origin 远端"}
    hits = secret_hits(prev)
    if hits:
        alert = {"at": at, "code": "A-SECRET", "src": "tools/qa/system_version.py", "msg": f"{sv} 推 GitHub 前密钥扫描命中，未推", "hits": hits[:20]}
        f = ROOT / "data/qa/alerts.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(alert, ensure_ascii=False) + chr(10))
        return {"at": at, "ok": False, "blocked": "密钥扫描命中", "hits": hits[:20]}
    branch = git("branch", "--show-current").strip() or "master"
    code, out = sh(["git", "push", "origin", branch, "--follow-tags"], 3600)
    return {"at": at, "ok": code == 0, "remote": "origin", "branch": branch, "detail": tail(out, 3)[:400]}


def load_rs():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_resident_sync_sv", ROOT / "tools/autopilot/resident_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def export_tag(sv: str, dirs: list[str], dest: Path) -> list[str]:
    raw = subprocess.run(["git", "archive", "--format=tar", sv, "--", *dirs], cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        names = [m.name for m in tf.getmembers() if m.isfile()]
        tf.extractall(dest, filter="data")
    # 总调度 11-02 20:1x：服务器上的文件 = 版本库里的原字节（LF，.gitattributes eol=lf）。以前“内容没改就用工作区原字节”把 Windows
    # 工作区的 CRLF 推上了服务器，服务器文件的 sha 和 git show 永远对不上（实测 remote_score.py 041b… ≠ 8601…）。日常代码推送已停用
    # （部署是唯一入口），不再有来回覆盖的问题；第一次切换会按 sha 补推一批只差换行的文件
    return names


def load_state_snapshot():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_state_snapshot_sv", ROOT / "tools/autopilot/state_snapshot.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def take_state_snapshot(sv: str, ss=None) -> dict:
    """cut 打完 tag 后做状态快照（data/system_versions/<sv>/state_snapshot.tar + manifest.json）；失败只记录，不影响发版"""
    try:
        ss = ss or load_state_snapshot()
        r = ss.snapshot(sv) or {}
        f = r.get("files")
        return {"ok": True, "dir": f"data/system_versions/{sv}/", "files": len(f) if isinstance(f, dict) else f,
                "tar_sha256": r.get("tar_sha256"), "at": r.get("at")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def load_restart_queue():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_restart_queue_sv", ROOT / "tools/autopilot/restart_queue.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_push_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_push_check_sv", ROOT / "tools/qa/push_check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_MISSING = object()


class _Patched:
    """临时改 resident_sync 模块的全局（ROOT / CODE_DIRS），退出时还原"""

    def __init__(self, rs, **kw):
        self.rs, self.kw, self.old = rs, kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(self.rs, k, _MISSING)
            setattr(self.rs, k, v)
        return self.rs

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is _MISSING:
                delattr(self.rs, k)
            else:
                setattr(self.rs, k, v)


def drift_files(sv: str, code_dirs: list[str]) -> list[str]:
    """工作树相对该版本多出 / 改动的代码文件（tag 之后的提交 + 未提交 + 未跟踪）——只报，不拦部署（K-OPS-F06）"""
    after = [x for x in git("diff", "--name-only", sv, "HEAD", "--", *code_dirs).split("\n") if x]
    pend = [p for _s, p in pending_changes()]
    return sorted({p for p in after + pend if p.startswith(tuple(d + "/" for d in code_dirs))})


def _verified_install(dest: str, data: bytes) -> str:
    """与 tools/factory/sync.verified_install 同口径：临时文件 sha 对上才替换（stdin 传丢不会留下 0 字节表）"""
    h = hashlib.sha256(data).hexdigest()
    return (f"cat > {dest}.tmp && echo '{h}  {dest}.tmp' | sha256sum -c --quiet - && mv {dest}.tmp {dest} && sha256sum {dest}"
            f" || {{ echo 'sha 不符，未替换 {dest}（收到 '$(stat -c %s {dest}.tmp 2>/dev/null)' 字节，应为 {len(data)}）' >&2; false; }}")


HOT_S = 120     # 最近 120 s 内还在改的数据文件算“正在变”


def hot_files(rs, now: float | None = None, hot_s: float = HOT_S) -> list[str]:
    """第一级数据文件里最近 hot_s 秒内还在被改的（笔记本上其他 loop 正在写）：部署时不推，免得推送复核每轮都不同、一推再推"""
    now = now or time.time()
    try:
        with _Patched(rs, CODE_DIRS=[]):
            dirs, _ = rs.push_dirs(False, 1)
        loc = rs.local_manifest(dirs)
    except Exception:  # noqa: BLE001  # arch-ok: 量不了就当没有热文件，照旧推
        return []
    return sorted(f for f, (sz, mt) in loc.items() if rs.tier_of(f, sz) == 1 and f.startswith("data/") and now - mt < hot_s)


def deploy_host(rs, h: str, snap: Path, names: list[str], tracked_code: list[str], sv: str, commit: str,
                restart: bool = True, pc=None, rq=None, urgent: bool = False, expected: bytes | None = None,
                hold_data: list[str] | None = None, restart_mode: str | None = None) -> dict:
    """一台机器的部署（FACTORY D9 / K-OPS-F06，总调度 01:3x 批准）：
    ① 代码只发该版本的 git 快照（export_tag 解出的目录）：推送前检查也对快照做（P1–P4），工作树里 tag 之外的新文件 / 改动根本不参与，
       不会再因“cut 之后又新建了代码文件”判“没推到”而整台失败（11-02 01:23 gpu36 sv-02 事故）；
    ② 第一级数据（作业表 / 身份脸等）照旧从工作树推，推送前检查只看数据（CODE_DIRS 置空）；
    ③ 代码按快照逐个核 sha、不同就重推；④ 写 data/system_version.txt；⑤ 热重启（按道排空由 restart 负责）"""
    pc = pc or load_push_check()
    r = {"at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    paused = False
    try:
        with _Patched(rs, ROOT=snap, required_data=lambda: set()):   # 快照里没有 data/：代码推送不需要数据清单
            g = pc.run(code_only=True, tier=1, rs=rs, skip_guard=True)          # 快照在 cut 时已过 syntax_guard
            if g.get("verdict") != "PASS":
                raise RuntimeError("快照推送前检查不通过：" + "；".join(f"[{x['kind']}] {x['file']}" for x in g["problems"][:5]))
            # 代码不再按“大小 + 修改时间”整批推（快照导出的修改时间每次都不同 → 每次全量 792 个文件、约 10 分钟，sv-11 实测）；
            # 改由下面 verify_sha 按 sha 只补不一致的文件（K-OPS-F13 修订）
        hot = sorted(set(hot_files(rs)) | set(hold_data or []))   # --hold-data：本次部署明确不推的数据（总调度 17:4x：first_frame_jobs.json 要等新代码上线、重编、测试绿后才推）
        # 总调度 11-02 15:4x：推送期间一直在变的数据文件不进第一级（每轮复核都不同 → 一推再推），交给常驻同步循环之后补
        if hot:
            r["hot_skipped"] = hot[:50]
        orig_wanted = getattr(rs, "wanted", lambda *a, **k: True)
        with _Patched(rs, CODE_DIRS=[], wanted=lambda f, *a, **k: f not in hot and orig_wanted(f, *a, **k)):
            g2 = pc.run(code_only=False, tier=1, rs=rs, skip_guard=True)
            if g2.get("verdict") != "PASS":
                raise RuntimeError("数据推送前检查不通过：" + "；".join(f"[{x['kind']}] {x['file']}" for x in g2["problems"][:5]))
            rs.push(h, tier=1, yes=True, gate=False)
        with _Patched(rs, ROOT=snap):                                         # 代码按该版本快照逐个核 sha，不同就重推
            v = rs.verify_sha(h, [n for n in names if n in tracked_code], fix=True)
        r["sha_checked"], r["sha_mismatch"], r["sha_fixed"] = v["checked"], len(v["mismatch"]), len(v["fixed"])
        if v["mismatch"]:
            raise RuntimeError(f"{len(v['mismatch'])} 个代码文件与 {sv} 不一致：{v['mismatch'][:5]}")
        stamp = json.dumps({"id": sv, "commit": commit, "at": r["at"], "by": "tools/qa/system_version.py deploy"}, ensure_ascii=False)
        rs.ssh(h, f"cd {rs.R} && mkdir -p data && cat > data/system_version.txt && cat data/system_version.txt",
               data=(stamp + "\n").encode(), tries=3)
        r["version_file"] = "data/system_version.txt"
        if expected:     # K-OPS-F03 修订：期望 refs 表按本版（cut 冻结快照）建，部署时一起推，重启后的 refs_guard 对的就是这一版
            rel = "data/factory/inbox/expected_refs.json"
            rs.ssh(h, f"cd {rs.R} && mkdir -p data/factory/inbox && " + _verified_install(rel, expected), data=expected, tries=3)
            r["expected_refs"] = "pushed"
        # 服务器运行依赖（config/deploy/server_deps.yaml：venv 能 import 的包 / 版本、模型文件 sha）——缺了不排重启（总调度 04:0x）
        sd = rs.ssh(h, f"cd {rs.R} && OFFLINE_SELF={h} {rs.OFF}/venv/bin/python tools/factory/server_deps.py; echo rc=$?", tries=3).decode("utf-8", "replace")
        r["server_deps"] = sd.strip()[-400:]
        if "rc=0" not in sd:
            raise RuntimeError("服务器运行依赖不齐（config/deploy/server_deps.yaml），不排重启，老进程继续：" + sd.strip()[-300:])
        # K-OPS-F09：新代码会对缺失 / 损坏的决策文件拒派——重启前先在服务器上用新代码查一遍，不过就不排重启（老进程继续生产）
        dg = rs.ssh(h, f"cd {rs.R} && OFFLINE_SELF={h} NS_FACTORY_HOST={h} {rs.OFF}/venv/bin/python tools/factory/decisions_guard.py; echo rc=$?",
                    tries=3).decode("utf-8", "replace")
        r["decisions_guard"] = dg.strip()[-400:]
        if "rc=0" not in dg:
            raise RuntimeError("服务器决策文件不齐（K-OPS-F09），不排重启，老进程继续：" + dg.strip()[-300:])
        pre = server_pause_owner(rs, h) if restart and urgent else None
        r["pre_paused"] = pre
        r["post_verify"] = post_verify(rs, h)    # 总调度 20:3x：部署后核对（当前剧资产包里每个角色的 face_of + sha）做进自动流程
        if restart and urgent and not pre:   # K-OPS-F13 修订：推完、核对都过了才暂停派单，紧接着当场排空重启——暂停窗口 = 排空 + 重启（≤ 3 分钟）
            rs.ssh(h, f"cd {rs.R} && {rs.OFF}/venv/bin/python tools/autopilot/producer.py pause --by DEPLOY_ATOMIC "   # 不再覆盖整个推送过程（sv-11 停派 26 分钟）
                      f"--note '部署 {sv}：重启前暂停派单，重启后恢复'", tries=3)
            paused = True
            r["paused_at"] = time.strftime("%H:%M:%S")
        if restart:      # K-OPS-W16（DJ-20）：不直接重启，写重启队列（resident_sync loop 排空后合并执行，同台 30 分钟最多一次）
            rq = rq or load_restart_queue()
            mode_kw = {"mode": restart_mode} if restart_mode else {}     # K-OPS-I11：只改派单配置 → producer-only；不传 = 队列默认 all
            q = rq.request(h, f"system_version deploy {sv}", by="system_version deploy", urgent=urgent, **mode_kw)
            r["restart"] = f"queued {q['id']}（tools/autopilot/restart_queue.py，执行记录 data/autopilot/restart_done.jsonl）"
            if restart_mode:
                r["restart_mode"] = restart_mode
            if urgent and hasattr(rq, "process"):     # K-OPS-F13：urgent 不等 loop 下一拍，当场按队列规则（排空 ≤90 s）执行，重启后 resume
                done = rq.process(h, rs) or {}
                r["restart"] += (f"；当场执行 ok={done.get('ok')} drain={done.get('drain_mode') or done.get('drained')} {done.get('secs')} s"
                                 + (f" error={str(done.get('error'))[:200]}" if done.get("error") else ""))
                if paused and done.get("ok"):
                    # A-09 ③（总调度 18:3x）：重启队列看到“已暂停”不会 resume（不清别人的暂停）——部署自己设的暂停由部署自己解；
                    # 部署前就被别人（项目方 owner / 运维 / runs.json）暂停的，部署不碰（pre 有值时上面根本没 pause）
                    rs.ssh(h, f"cd {rs.R} && {rs.OFF}/venv/bin/python tools/autopilot/producer.py resume --by DEPLOY_ATOMIC "
                              f"--note '部署 {sv} 重启完成，解除部署自己的暂停'", tries=3)
                    r["resumed_own_pause"] = True
                    paused = False
                else:
                    paused = paused and not done.get("ok")
        r["ok"] = True
    except Exception as e:  # noqa: BLE001
        r.update(ok=False, error=f"{type(e).__name__}: {e}"[:400])
    if paused and not r.get("ok", False) or (paused and "当场执行 ok=False" in str(r.get("restart"))):
        try:     # 部署没成：老进程继续生产（解除暂停）
            rs.ssh(h, f"cd {rs.R} && {rs.OFF}/venv/bin/python tools/autopilot/producer.py resume --by DEPLOY_ATOMIC --note '部署未完成，恢复派单'", tries=3)
            r["resumed_after_fail"] = True
        except Exception as e2:  # noqa: BLE001
            r["resume_error"] = repr(e2)[:200]
    return r


def post_verify(rs, h: str) -> dict:
    """部署后在服务器上跑 tools/factory/post_verify.py（经 stdin 送部署版脚本）：当前剧 face_of + sha 对清单；跑不了 = ok False 记原因"""
    try:
        raw = rs.ssh(h, f"cd {rs.R} && {rs.OFF}/venv/bin/python tools/factory/post_verify.py {rs.R}", tries=2)
        txt = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        return json.loads([x for x in txt.strip().splitlines() if x.startswith("{")][-1])
    except Exception as e:  # noqa: BLE001  # arch-ok: 核对跑不了 = 记下来（不当作通过）
        return {"ok": False, "error": repr(e)[:200]}


def server_pause_owner(rs, h: str) -> str | None:
    """部署前服务器上本机主剧是否已被别人暂停（OVERSIGHT-F P1-3：按剧取 control 路径 + runs.json status，tools/factory/pause_state.py）"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("factory_pause_state", ROOT / "tools/factory/pause_state.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.remote_pause_owner(rs, h, tries=2)


LAST_CUT = DATA / "last_cut.json"


def record_cut(out: dict, dry: bool) -> None:
    """每次 cut（非 dry）都记结果；deploy 据此判断“最近一次 cut 失败”就不部署（K-OPS-F07）"""
    if dry:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    LAST_CUT.write_text(json.dumps({"ok": bool(out.get("ok")), "id": out.get("id"), "at": time.time(),
                                    "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": str(out.get("reason") or "")[:300]},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    # 线 5 发版分项的账本（SYSARCH，总调度 11-02 09:1x 定）：每次 cut 尝试都追加一行，打分器按“每个 sv 第一次尝试是否通过”算
    ledger = ROOT / "data/rsi/cut_seen.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": out.get("id"), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": bool(out.get("ok")),
                             "src": "system_version.record_cut", "reason": str(out.get("reason") or "")[:160]},
                            ensure_ascii=False) + "\n")


def deploy_guard(sv: str | None, allow_old: bool = False, last_cut: dict | None = None, tags: list[str] | None = None,
                 tag_time=None) -> str | None:
    """→ None = 可以部署；否则返回拒绝原因（K-OPS-F07，总调度 02:0x：sv-04 cut 失败后另一流程把 sv-03 重新部署，
    服务器 config/vqa.json 被还原成 instances=1、积压闸卡死 GPU）。
    ① 最近一次 cut 失败（时间晚于最新 tag）→ 拒绝；② 只许部署最新版本，旧版本要 --allow-old（回退流程）"""
    tags = tags if tags is not None else sv_tags()
    if not tags:
        return "还没有任何系统版本，先 cut"
    newest = tags[-1]
    lc = last_cut if last_cut is not None else (json.loads(LAST_CUT.read_text(encoding="utf-8")) if LAST_CUT.exists() else {})
    tt = tag_time or (lambda t: float(git("log", "-1", "--format=%ct", t).strip() or 0))
    if lc and lc.get("ok") is False and float(lc.get("at") or 0) > tt(newest):
        return f"最近一次 cut 失败（{lc.get('at_iso')}：{lc.get('reason') or '闸门不过'}），不部署；修好后重新 cut 再 deploy"
    target = sv or newest
    if target != newest and not allow_old:
        return f"{target} 不是最新版本（最新 {newest}）；回退请走 rollback 流程并加 --allow-old"
    return None


def build_expected(sv: str) -> tuple[bytes | None, dict]:
    """期望 refs 表：优先用 cut 冻结快照（D:/nsfs_cut_snapshots/<sv>，代码 = 本版 tag）建，含全部有导入稿的剧（第二季等）；
    快照不在 → 退回本仓库工作树建并注明。建不出来 → 不推（服务器沿用旧表；decisions_guard 仍要求表存在）"""
    import importlib.util
    snap = SNAP_BASE / sv
    root = snap if (snap / "tools/factory/inbox.py").exists() else ROOT
    try:
        spec = importlib.util.spec_from_file_location("ns_inbox_sv", root / "tools/factory/inbox.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        out = DATA / f"expected_refs_{sv}.json"
        t = m.build(root=root, out_path=out)
        b = out.read_bytes()
        (ROOT / "data/factory/inbox").mkdir(parents=True, exist_ok=True)
        (ROOT / "data/factory/inbox/expected_refs.json").write_bytes(b)
        return b, {"built_from": "cut 快照" if root == snap else "工作树（快照不在）", "counts": t.get("counts"),
                   "blocked": len(t.get("laptop_blocked") or {})}
    except Exception as e:  # noqa: BLE001
        return None, {"error": f"{type(e).__name__}: {e}"[:300]}


INCIDENTS = ROOT / "data/rsi/release_incidents.jsonl"


def record_incident(sv: str, kind: str, fixed_by: str | None, note: str = "") -> dict:
    """发版事故账本（总调度 11-02 定：部署后需要热修 / 回滚的版本不算一次通过；SYSARCH 记分读这里）"""
    rec = {"sv": sv, "kind": kind, "fixed_by": fixed_by, "by": "tools/qa/system_version.py", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "note": note}
    INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
    with open(INCIDENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def write_local_version(sv: str, commit: str, at: str | None = None, root: Path | None = None) -> str:
    """AUDIT-RULES 11-05：deploy 只在服务器写 data/system_version.txt，笔记本那份停在 sv-20261102-04 → 本机工具
    （policy.min_code_sv / film_score / sentinel probes / vidlab score / post_verify）读到旧版本。部署成功（任一台 ok）后本机同格式写一份；
    原子写（临时文件 + replace），内容与服务器 stamp 同 schema（id / commit / at / by）"""
    root = root or ROOT
    p = root / LOCAL_VERSION_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = json.dumps({"id": sv, "commit": commit, "at": at or time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "by": "tools/qa/system_version.py deploy"}, ensure_ascii=False)
    tmp = p.with_suffix(".txt.tmp")
    tmp.write_text(stamp + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return LOCAL_VERSION_FILE


DISPATCH_CONFIG = ("config/factory/hosts.json", "config/pipeline/lane_relay.json", "config/pipeline/sop_gate.json",
                   "config/gen_contract.json", "config/pipeline/producer.json", "config/render_quality.json",
                   "config/compile/run_style.json", "config/pipeline/video_shard.json")
DISPATCH_RESTART_MODE = "producer-only"


def local_deployed_sv(root: Path | None = None) -> str | None:
    """上一次部署成功的版本 id（deploy 成功后 write_local_version 写的本机 data/system_version.txt）；读不到 = None"""
    p = (root or ROOT) / LOCAL_VERSION_FILE
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("id") or "") or None
    except Exception:  # noqa: BLE001  # arch-ok: 本机版本文件缺 / 坏 = 无上次版本 → 调用方按“改了派单配置”处理（失败偏安全：紧急重启）
        return None


def previous_deployed_sv(sv: str, tags: list[str] | None = None) -> str | None:
    """上一次部署的版本：本机 data/system_version.txt 记的 id；没有就取 sv 前一个 tag；都没有 / 与 sv 相同 = None"""
    prev = local_deployed_sv()
    if not prev:
        tags = tags if tags is not None else sv_tags()
        prev = next((tags[i - 1] for i in range(1, len(tags)) if tags[i] == sv), None)
    return prev if prev and prev != sv else None


def changed_between(prev: str, sv: str, paths, git_fn=None) -> list[str] | None:
    """prev..sv 之间 paths 里改动的文件（git diff --name-only）；git 失败（旧 tag 不在等）= None（判不了）"""
    git_fn = git_fn or git
    try:
        out = git_fn("diff", "--name-only", prev, sv, "--", *paths)
    except Exception:  # noqa: BLE001  # arch-ok: git 判不了 = None → dispatch_config_changed 当“改了”（失败偏安全）
        return None
    return sorted({x.strip().replace("\\", "/") for x in out.split("\n") if x.strip()})


def dispatch_config_changed(sv: str, prev: str | None = None, files: tuple[str, ...] = DISPATCH_CONFIG,
                            git_fn=None, tags: list[str] | None = None) -> list[str]:
    """K-OPS-I11（RULES-1105，项目方 11-05 20:1x “显卡没有用起来”）：本版相对上一次部署的版本改了哪些**派单相关配置**
    （hosts / lane_relay / sop_gate / gen_contract / producer / render_quality / run_style / video_shard）。
    改了 = producer 必须立刻读到：deploy 自动把重启请求升为 urgent（cut O 之后 gpu33 producer 卡在 30 分钟重启间隔外，
    gpu36:1/2 借道与 L-195 都没加载，20:00–20:15 道空着、ep01 S11/S12/S14 ready 没人派）。
    prev 默认 = previous_deployed_sv；判不了（git 失败）= 按全部改了处理（宁可多重启一次，不让 producer 读旧配置）"""
    prev = prev or previous_deployed_sv(sv, tags)
    if not prev or prev == sv:
        return []
    out = changed_between(prev, sv, files, git_fn)
    return list(files) if out is None else out


def dispatch_restart_plan(sv: str, prev: str | None = None, code_dirs=None, git_fn=None, tags: list[str] | None = None,
                          urgent: bool = False) -> dict:
    """K-OPS-I11 的重启计划：{changed: 派单配置改动, others: 同版其它代码改动数, urgent, mode, why}。
    派单配置改了 → urgent；只改了派单配置（没别的代码）→ mode=producer-only（night 不动，视频不被打断）；
    还改了别的代码 → mode 留空（= all，与原部署行为一致：全部进程读新版）"""
    prev = prev or previous_deployed_sv(sv, tags)
    changed = dispatch_config_changed(sv, prev, git_fn=git_fn, tags=tags) if prev else []
    plan = {"prev": prev, "changed": changed, "others": 0, "urgent": bool(urgent), "mode": None, "why": None}
    if not changed:
        return plan
    code_dirs = list(code_dirs or [])
    allc = changed_between(prev, sv, code_dirs, git_fn) if code_dirs else None
    others = [x for x in (allc or []) if x not in set(changed)] if allc is not None else None
    plan["others"] = len(others) if others is not None else -1
    plan["urgent"] = True
    plan["mode"] = DISPATCH_RESTART_MODE if others == [] else None
    plan["why"] = (f"K-OPS-I11：派单配置变更 {changed} → 重启请求升为 urgent"
                   + (f" + {DISPATCH_RESTART_MODE}" if plan["mode"] else f"（同版另有 {plan['others']} 个代码改动 → 全部重启）"))
    return plan


def deploy(sv: str | None = None, hosts: list[str] | None = None, restart: bool = True, allow_old: bool = False,
           urgent: bool = False, hotfix_of: str | None = None, hold_data: list[str] | None = None,
           verify_shot: int | None = None, verify_run: str | None = None, manifest_prefix: str | None = None,
           run_verify: bool = True) -> dict:
    why = deploy_guard(sv, allow_old)
    if why:
        raise SystemExit("deploy 拒绝：" + why)
    sv = sv or sv_tags()[-1]
    rs = load_rs()
    hosts = hosts or list(rs.HOSTS)
    commit = git("rev-list", "-n", "1", sv).strip()
    tracked_code = [x for x in git("ls-tree", "-r", "--name-only", sv, "--", *rs.CODE_DIRS).split("\n") if x]
    drift = drift_files(sv, rs.CODE_DIRS)
    res = {"id": sv, "commit": commit, "hosts": {}, "drift_local": len(drift), "drift_files": drift[:50],
           "drift_note": "工作树里 tag 之外的代码改动只报不推（K-OPS-F06），留给下一版" if drift else None}
    restart_mode = None
    if restart:      # K-OPS-I11：派单相关配置变了 → 紧急重启（不等 30 分钟间隔；只改配置时 producer-only），审计记原因
        plan = dispatch_restart_plan(sv, code_dirs=rs.CODE_DIRS, urgent=urgent)
        res["dispatch_config_changed"] = plan["changed"]
        if plan["changed"]:
            restart_mode = plan["mode"]
            if plan["urgent"] and not urgent:
                res["urgent_auto"] = plan["why"]
            urgent = urgent or plan["urgent"]
    with tempfile.TemporaryDirectory(prefix="nsfs_sv_") as td:
        names = export_tag(sv, rs.CODE_DIRS, Path(td))
        pc = load_push_check()
        expected, res["expected_refs"] = build_expected(sv)
        for h in hosts:
            res["hosts"][h] = deploy_host(rs, h, Path(td), names, tracked_code, sv, commit, restart=restart, pc=pc, urgent=urgent,
                                          expected=expected, hold_data=hold_data, restart_mode=restart_mode)
    idx = write_index()
    for v in idx["versions"]:
        if v["id"] == sv:
            v.setdefault("deployed", {}).update({h: r for h, r in res["hosts"].items() if r.get("ok")})
            write_index(v)
    if any(r.get("ok") for r in res["hosts"].values()):
        res["local_version_file"] = write_local_version(sv, commit, res.get("at") or time.strftime("%Y-%m-%dT%H:%M:%S"))
    if hotfix_of and res["hosts"] and all(x.get("ok") for x in res["hosts"].values()):
        res["incident"] = record_incident(hotfix_of, "hotfix", sv, f"{sv} 热修 {hotfix_of}")
    ok_hosts = [h for h, r in res["hosts"].items() if r.get("ok")]
    if run_verify and ok_hosts:      # 总调度 11-03：deploy 完自动 verify（核部署成功的机器；verify 不过 = 本次部署不算完成，退出码 1）
        try:
            res["verify"] = verify(sv, ok_hosts, verify_shot, verify_run, manifest_prefix, rs=rs)
        except Exception as e:  # noqa: BLE001
            res["verify"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    (DATA / f"deploy_{sv}_{time.strftime('%H%M%S')}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def rollback(sv: str) -> dict:
    if sv not in sv_tags() and sv != BASELINE:
        raise SystemExit(f"没有版本 {sv}（现有：{sv_tags()}）")
    stat = git("diff", "--stat", "HEAD", sv)
    pend = pending_changes()
    cmds = [f"git stash push -u -m 'before rollback to {sv}'   # 仅当工作区有未入版改动（现在 {len(pend)} 个）",
            f"git checkout {sv} -- .",
            f".venv/Scripts/python.exe tools/autopilot/state_snapshot.py restore {sv}   # 先预览；确认后加 --apply（校验 sha、先备份现状到 data/system_versions/{sv}/pre_restore_*，不删）", f".venv/Scripts/python.exe tools/qa/system_version.py cut --base {sv}   # 回退本身也记一版",
            ".venv/Scripts/python.exe tools/qa/system_version.py deploy"]
    return {"target": sv, "preview_stat": tail(stat, 40), "pending_local": len(pend), "commands": cmds,
            "note": "只生成命令与差异预览，未执行；执行要总调度确认（K-OPS-V01）",
            "incident_cmd": f".venv/Scripts/python.exe -c \"import importlib.util as u;s=u.spec_from_file_location('sv','tools/qa/system_version.py');m=u.module_from_spec(s);s.loader.exec_module(m);m.record_incident('<被回滚的版本>','rollback','{sv}')\"   # 执行回滚后记事故账本"}


# ---------------------------------------------------------------- 部署后核对（总调度 11-03：verify 子命令，deploy 完自动调）
VERIFY_MANIFEST = "assets_v2/manifest.json"
VERIFY_CODE = ("services/agent/ns_agent/compiler.py", "services/agent/ns_agent/frame_job.py", "services/agent/ns_agent/asset_refs.py",
               "services/agent/ns_agent/gen_contract/preflight.py", "services/agent/ns_agent/gen_contract/style.py",
               "tools/promptfix/golden_v2.py")
VERIFY_MARK = "@@NSV@@"
VERIFY_NEED_SHOT = ("verify 必须指定镜号（--shot N；deploy 用 --verify-shot N）：golden dry-run 只认当前剧导入稿里的指定镜，"
                    "没有默认金样，不退回任何夹具（ISS-1103-005000-2af2）")


def tag_blob_sha(sv: str, rel: str) -> str | None:
    """该版本 git 快照里文件的 sha256（按字节，和服务器 sha256sum 同口径）；版本里没有这个文件 = None"""
    r = subprocess.run(["git", "show", f"{sv}:{rel}"], cwd=ROOT, capture_output=True, timeout=120)
    return hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 else None


def verify_probe_cmd(R: str, OFF: str, host: str, run: str | None, shot: int | None) -> str:
    """一台机器一条只读命令：版本戳 / 清单 sha / 编译相关代码 sha / golden_v2 只编译 dry-run（--summary，不出图）"""
    import shlex
    env = (f"NS_RUN={shlex.quote(run)} " if run else "") + f"OFFLINE_SELF={shlex.quote(host)} PYTHONIOENCODING=utf-8"
    if not shot:
        raise ValueError(VERIFY_NEED_SHOT)
    gold = f"tools/promptfix/golden_v2.py --summary --shot {int(shot)}"
    m = VERIFY_MARK
    return (f"cd {R} && echo '{m} version'; cat data/system_version.txt 2>/dev/null; "
            f"echo '{m} manifest'; sha256sum {VERIFY_MANIFEST} 2>/dev/null; "
            f"echo '{m} code'; sha256sum {' '.join(VERIFY_CODE)} 2>/dev/null; "
            f"echo '{m} golden'; {env} timeout 600 {OFF}/venv/bin/python {gold} 2>&1 | tail -n 30; true")


def parse_probe(raw: str) -> dict:
    sec: dict[str, list[str]] = {}
    cur = None
    for ln in raw.splitlines():
        if ln.startswith(VERIFY_MARK + " "):
            cur = ln[len(VERIFY_MARK) + 1:].strip()
            sec[cur] = []
        elif cur:
            sec[cur].append(ln)
    out: dict = {"stamp": None, "manifest_sha": None, "code": {}, "golden": None, "golden_err": None}
    vtxt = "\n".join(sec.get("version") or []).strip()
    try:
        out["stamp"] = json.loads(vtxt) if vtxt else None
    except ValueError:
        out["stamp"] = {"raw": vtxt[:200]}
    for ln in sec.get("manifest") or []:
        if ln.strip():
            out["manifest_sha"] = ln.split()[0]
    for ln in sec.get("code") or []:
        parts = ln.split(None, 1)
        if len(parts) == 2:
            out["code"][parts[1].strip().lstrip("*")] = parts[0]
    g = [ln for ln in sec.get("golden") or [] if ln.startswith("GOLDEN_SUMMARY ")]
    if g:
        try:
            out["golden"] = json.loads(g[-1][len("GOLDEN_SUMMARY "):])
        except ValueError as e:
            out["golden_err"] = f"GOLDEN_SUMMARY 解析失败：{e}"
    else:
        out["golden_err"] = ("没有 GOLDEN_SUMMARY 输出：" + " ⏎ ".join((sec.get("golden") or [])[-4:]))[:400]
    return out


def judge_verify(sv: str, probes: dict, want_code: dict, manifest_prefix: str | None = None,
                 local_golden: dict | None = None) -> dict:
    """三项（总调度 11-03）：① 编译版本 = 本版（版本戳 id + 编译相关代码逐个 sha 对本版快照）；② 清单 sha（给了前缀就对前缀，
    并且各台一致）；③ 同一镜 golden dry-run 结果各台一致（给了本地结果也要一致）。任何一项缺数据 = 不通过，不猜"""
    rows, gold_set, man_set = {}, set(), set()
    for h, p in probes.items():
        if p.get("error"):
            rows[h] = {"ok": False, "error": p["error"]}
            continue
        st = p.get("stamp")
        sid = st.get("id") if isinstance(st, dict) else None
        bad_code = sorted(f for f, w in want_code.items() if w is None or p.get("code", {}).get(f) != w)
        man = p.get("manifest_sha")
        g = p.get("golden")
        rows[h] = {"version": sid, "version_ok": sid == sv, "code_mismatch": bad_code, "code_ok": not bad_code,
                   "manifest_sha": man, "manifest_ok": bool(man) and (not manifest_prefix or man.startswith(manifest_prefix)),
                   "golden": {k: g.get(k) for k in ("shot", "prompt_sha", "refs_sha", "route", "adult", "preflight_ok", "preflight_fail")} if g else None,
                   "golden_err": p.get("golden_err"), "golden_ok": bool(g)}
        man_set.add(man)
        if g:
            gold_set.add(json.dumps(g, ensure_ascii=False, sort_keys=True))
    if local_golden:
        gold_set.add(json.dumps(local_golden, ensure_ascii=False, sort_keys=True))
    good = [r for r in rows.values() if "error" not in r]
    man_same = len(man_set) == 1 and None not in man_set
    gold_same = len(gold_set) == 1 and bool(good) and all(r["golden_ok"] for r in good)
    for r in good:
        r["ok"] = r["version_ok"] and r["code_ok"] and r["manifest_ok"] and r["golden_ok"]
    ok = bool(rows) and len(good) == len(rows) and all(r["ok"] for r in good) and man_same and gold_same
    return {"id": sv, "ok": ok, "hosts": rows, "manifest_same": man_same, "golden_same": gold_same,
            "manifest_prefix": manifest_prefix, "local_golden": local_golden}


def local_golden_summary(run: str | None, shot: int | None) -> dict | None:
    if not shot:
        raise ValueError(VERIFY_NEED_SHOT)
    env = {**ENV, **({"NS_RUN": run} if run else {})}
    _code, out = sh([PY, "tools/promptfix/golden_v2.py", "--summary", "--shot", str(int(shot))], 600, env=env)
    g = [ln for ln in out.splitlines() if ln.startswith("GOLDEN_SUMMARY ")]
    return json.loads(g[-1][len("GOLDEN_SUMMARY "):]) if g else None


def _write_verify(sv: str, res: dict) -> Path:
    """verify 结果落盘 data/system_versions/verify_<sv>_HHMMSS.json：tmp + os.replace（同 write_index，ARCH_MAP §6）"""
    DATA.mkdir(parents=True, exist_ok=True)
    f = DATA / f"verify_{sv}_{time.strftime('%H%M%S')}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    return f


def verify(sv: str | None = None, hosts: list[str] | None = None, shot: int | None = None, run: str | None = None,
           manifest_prefix: str | None = None, with_local: bool = False, rs=None) -> dict:
    """部署后核对：每台一条只读探针（rs.ssh → tools/netfix/rssh），golden 只编译不出图；结果写 data/system_versions/verify_<sv>_*.json"""
    sv = sv or sv_tags()[-1]
    if not shot:     # 失败关闭：不碰服务器，直接记一条不通过
        res = {"id": sv, "ok": False, "reason": VERIFY_NEED_SHOT, "hosts": {}, "shot": None, "run": run,
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _write_verify(sv, res)
        return res
    rs = rs or load_rs()
    hosts = hosts or list(rs.HOSTS)
    want = {f: tag_blob_sha(sv, f) for f in VERIFY_CODE}
    probes = {}
    for h in hosts:
        try:
            raw = rs.ssh(h, verify_probe_cmd(rs.R, rs.OFF, h, run, shot), timeout=900, tries=3).decode("utf-8", "replace")
            probes[h] = parse_probe(raw)
        except Exception as e:  # noqa: BLE001
            probes[h] = {"error": f"{type(e).__name__}: {e}"[:300]}
    lg = local_golden_summary(run, shot) if with_local else None
    res = judge_verify(sv, probes, want, manifest_prefix, lg)
    res.update(at=time.strftime("%Y-%m-%dT%H:%M:%S"), shot=shot, run=run)
    _write_verify(sv, res)
    return res


def _write_report(path: str, out: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def load_release_tick():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_release_tick", ROOT / "tools/autopilot/release_tick.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def status() -> dict:
    t = sv_tags()
    return {"current": t[-1] if t else None, "versions": t, "pending": len(pending_changes()),
            "head": git("rev-parse", "--short", "HEAD").strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="系统版本：cut / deploy / verify / rollback / status（K-OPS-V01）")
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("cut")
    c.add_argument("--base")
    c.add_argument("--manifests", nargs="+", default=None, metavar="ID", help="按交付清单拼树（HEAD + 钉住的 blob），与 --tree 互斥")
    c.add_argument("--dry", action="store_true")
    c.add_argument("--id")
    c.add_argument("--tree", default=None, help="用指定的 git 树代替冻结工作树（总调度批准的快照修补）")
    c.add_argument("--report-json", default=None, help="完整 cut 报告另写到这个文件（release_tick 读）")
    c.add_argument("--on", default=None, help="W45：闸门在哪跑（gpu33 / local）；不给 = NS_CUT_ON > release.json gates_on > local")
    d = sp.add_parser("deploy")
    d.add_argument("sv", nargs="?")
    d.add_argument("--hosts")
    d.add_argument("--no-restart", action="store_true")
    d.add_argument("--allow-old", action="store_true", help="部署非最新版本（只给回退流程用）")
    d.add_argument("--urgent", action="store_true", help="重启请求插队（K-OPS-W16 urgent，审计记 urgent_jump）")
    d.add_argument("--hold-data", default="", help="本次部署不推的数据文件（逗号分隔，仓库相对路径），例：data/pipeline/runs/<run>/assets/first_frame_jobs.json")
    d.add_argument("--hotfix-of", default=None, help="本版是热修哪一版：部署成功后自动记发版事故账本 data/rsi/release_incidents.jsonl")
    d.add_argument("--verify-shot", type=int, default=None, help="部署后 verify 用的镜号（golden_v2 --shot）；不给 = verify 失败关闭、deploy 退出码 1（没有默认金样）")
    d.add_argument("--verify-run", default=None, help="verify 时 golden 用的剧（NS_RUN；不给 = 服务器当前剧）")
    d.add_argument("--manifest-prefix", default=None, help="verify：assets_v2/manifest.json 的 sha 必须以此开头")
    d.add_argument("--no-verify", action="store_true", help="跳过部署后 verify（只给回退流程用）")
    d.add_argument("--report-json", default=None, help="完整 deploy 报告另写到这个文件（release_tick 读）")
    v = sp.add_parser("verify")
    v.add_argument("sv", nargs="?")
    v.add_argument("--hosts")
    v.add_argument("--shot", type=int, default=None, help="必填：golden dry-run 的镜号（不给 = 失败关闭）")
    v.add_argument("--run", default=None)
    v.add_argument("--manifest-prefix", default=None)
    v.add_argument("--local", action="store_true", help="同时跑本地 golden dry-run，要求与服务器一致（根因模式 #2）")
    r = sp.add_parser("rollback")
    r.add_argument("sv")
    mc = sp.add_parser("manifest-check", help="核对交付清单：文件在 / 钉 blob / 伴随缺口 / 重叠 / 别人的租约；有 error 退出码 1")
    mc.add_argument("ids", nargs="+")
    mc.add_argument("--no-pin", action="store_true", help="不写 blob / 不落 pins 文件（只看）")
    mc.add_argument("--repin", nargs="*", default=None, metavar="ID", help="作者显式重钉已有 pin（默认已有 pin 只校验不改）；不带 id = 全部，带 id = 只重钉这些")
    mc.add_argument("--by", default=None, help="pin 文件记 pinned_by（默认清单 worker）")
    ls_ = sp.add_parser("lease", help="建议性文件租约：take / release / list（glob 可用）")
    ls_.add_argument("action", choices=["take", "release", "list"])
    ls_.add_argument("--worker")
    ls_.add_argument("--paths", nargs="*", default=[])
    ls_.add_argument("--ttl-h", type=float, default=6.0)
    sp.add_parser("status")
    sp.add_parser("lock-status")
    ho = sp.add_parser("handover", help="L-152 换代（W17）：--dry 只列将做的步骤；--apply 执行（条件不满足不动）")
    hg = ho.add_mutually_exclusive_group(required=True)
    hg.add_argument("--dry", action="store_true")
    hg.add_argument("--apply", action="store_true")
    ho.add_argument("--force", action="store_true", help="--apply 时不看“已换代过”记录（条件仍要满足）")
    rl = sp.add_parser("release", help="W17：按 data/system_versions/release_request.json 跑一次发版流水线（= release_tick 一拍）")
    rl.add_argument("--build-tree-only", action="store_true", help="只按清单拼树、打印 tree，不跑 cut")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if a.cmd == "manifest-check":
        rep = load_manifest_mod().manifest_check(a.ids, ROOT, pin=not a.no_pin, repin=(True if a.repin == [] else (a.repin or False)), by=a.by)
        print(json.dumps(rep, ensure_ascii=False, indent=1)[:6000])
        return 0 if rep["ok"] else 1
    if a.cmd == "lease":
        M = load_manifest_mod()
        if a.action == "list":
            print(json.dumps(M.leases_active(ROOT), ensure_ascii=False, indent=1))
            return 0
        if not a.worker:
            print("lease take|release 需要 --worker")
            return 2
        if a.action == "take":
            if not a.paths:
                print("lease take 需要 --paths")
                return 2
            out = M.lease_take(a.worker, a.paths, ROOT, a.ttl_h)
        else:
            out = M.lease_release(a.worker, a.paths or None, ROOT)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 3 if out.get("conflicts") else 0      # 3 = 租到了但和别人重叠（建议性）
    if a.cmd == "cut":
        if a.manifests:
            if a.tree:
                print("--manifests 与 --tree 互斥")
                return 2
            a.tree = build_tree_from_manifests(a.manifests, a.base or "HEAD")["tree"]
        out = cut(a.base, a.dry, a.id, tree=a.tree, on=a.on)
        if out.get("rc") != 3:                        # 互斥拒绝不算一次 cut 尝试（不覆盖别人正在跑的 last_cut）
            record_cut(out, a.dry)
        if a.report_json and out.get("rc") != 3:
            _write_report(a.report_json, out)
        print(json.dumps({k: v for k, v in out.items() if k != "gates"}, ensure_ascii=False, indent=1)[:4000])
        for gg in out.get("gates", []):
            print(f"  {'✅' if gg['ok'] else '❌'} {gg['name']}" + (f"（{gg['elapsed_s']} s）" if gg.get("elapsed_s") is not None else "")
                  + f"：{gg['detail'][:200]}")
        return 0 if out.get("ok") else int(out.get("rc") or 1)
    if a.cmd == "deploy":
        out = deploy(a.sv, a.hosts.split(",") if a.hosts else None, not a.no_restart, a.allow_old, a.urgent, a.hotfix_of,
                     hold_data=[x for x in (a.hold_data or "").split(",") if x], verify_shot=a.verify_shot,
                     verify_run=a.verify_run, manifest_prefix=a.manifest_prefix, run_verify=not a.no_verify)
        if a.report_json:
            _write_report(a.report_json, out)
        print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
        ok = bool(out["hosts"]) and all(x.get("ok") for x in out["hosts"].values())
        return 0 if ok and (a.no_verify or (out.get("verify") or {}).get("ok")) else 1
    if a.cmd == "verify":
        out = verify(a.sv, a.hosts.split(",") if a.hosts else None, a.shot, a.run, a.manifest_prefix, a.local)
        print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
        return 0 if out.get("ok") else 1
    if a.cmd == "lock-status":       # K-OPS-F08：别的 agent 写代码前先查；退出码 3 = cut 进行中
        lk = cut_locked()
        print(json.dumps(lk or {"active": False}, ensure_ascii=False, indent=1))
        return 3 if lk else 0
    if a.cmd == "rollback":
        print(json.dumps(rollback(a.sv), ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("handover", "release"):      # W17：逻辑在 tools/autopilot/release_tick.py（调用本模块，不复制）
        RT = load_release_tick()
        if a.cmd == "handover":
            out = RT.handover_once(apply=bool(a.apply), sv=sys.modules[__name__], force=a.force)
            print(RT.format_handover(out))
            return 0 if out.get("ok", True) else 1
        if a.build_tree_only:
            req = RT.read_request()
            if not req:
                out = {"error": "没有 release_request.json"}
            elif req.get("manifests"):
                out = build_tree_from_manifests(list(req["manifests"]), req.get("base") or "HEAD")
            else:
                out = build_tree_from_list(ROOT / req["list"], req.get("base") or "HEAD")
        else:
            out = RT.release_once(sv=sys.modules[__name__])
        print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
        return 0 if not out.get("error") and out.get("status") != "failed" else 1
    print(json.dumps(status(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
