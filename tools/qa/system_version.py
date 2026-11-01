"""系统版本（发版 / 覆盖部署 / 回退）（CODE-RSI r3，2026-11-01；规则 K-OPS-V01，knowledge/rules/ops_code_rsi.yaml）。

项目方 11-01 22:5x：“记得每一次 iterate 完把东西记录下来.然后把规则系统的一些东西,全部代码都调一次,也就是说,每一次迭代都是用
override system,然后用 create a new version 那个 system versions”。
每次迭代收轮后由总调度 cut 一个系统版本：规则 + 代码 + 配置 + 文档一起成为可回退的 git 快照（tag），取代上一版，并留下本轮完整记录。
复用现有部件（G0）：git、knowledge kb 版本号、CHANGELOG、iter_gate 结果、syntax_guard、compile --check、decision_check /
decision_propagation、push_check / push_gate、resident_sync 的分级推送与 sha 核对。

  cut [--base REF] [--dry]     过闸门 → git add（.gitignore 口径：只跟踪代码 / 规则 / 配置 / 文档）→ commit（Co-Authored-By）→ tag sv-YYYYMMDD-NN
                               → docs/system_versions/<sv>.md + INDEX.md + data/system_versions/index.json（界面只读接口）
  deploy [SV] [--hosts gpu33,gpu36]
                               推到服务器：resident_sync 第一级推送（内含 push_gate）→ 代码按该版本的 git 快照逐个核 sha、不同就重推
                               → 服务器写 data/system_version.txt（= override system）→ 热重启常驻（resident_sync.restart 默认模式）
  （cut 末尾：推前密钥扫描 → git push origin <分支> --follow-tags；命中不推并报警，推送失败不影响发版——项目方 23:0x 授权，仅限发版流程）
  rollback SV                  只生成回退命令和差异预览（git checkout <tag> -- <跟踪文件> → deploy），不执行；执行要总调度确认
  status                       当前版本、HEAD 之后未入版的改动数
闸门任一不过就不发版并写明原因。不删文件。
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
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
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


# ---------------------------------------------------------------- 基础
def sh(cmd: list[str], timeout: int = 1800, cwd: Path = ROOT) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=ENV)
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
def pick_tests(changed: list[str]) -> list[str]:
    tests = set()
    for f in changed:
        if f.startswith("tests/") and f.endswith(".py") and Path(f).name.startswith("test_") and (ROOT / f).exists():
            tests.add(f)
        elif f.endswith(".py") and f.startswith(("services/", "tools/", "packages/")):
            stem = Path(f).stem
            if stem in ("__init__", "run", "report", "page", "build_jobs", "server", "utils", "common"):
                continue
            tests |= {p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob(f"test_*{stem}*.py")}
    return sorted(tests | {t for t in SMOKE if (ROOT / t).exists()})


def gates(changed: list[str], run_tests: bool = True) -> list[dict]:
    rows = []

    def add(gid, name, ok, detail):
        rows.append({"id": gid, "name": name, "ok": bool(ok), "detail": detail})

    code, out = sh([PY, "tools/qa/syntax_guard.py", "--dry"], 600)
    add("syntax", "全仓语法守卫（K-OPS-C01）", code == 0, tail(out, 2))
    code, out = sh([PY, "tools/knowledge/compile.py", "--check"], 600)
    add("kb", "知识库 compile --check", code == 0, tail(out, 2))
    code, out = sh([PY, "tools/qa/decision_check.py"], 900)
    m = re.search(r"合计 (\d+)：✅ (\d+)\s+❌ (\d+)\s+⏳ (\d+)", out)
    bad = int(m.group(3)) if m else -1
    add("decision", "decision_check（0 ❌，⏳ 可以）", m is not None and bad == 0,
        m.group(0) if m else "没读到合计行：" + tail(out, 2))
    code, out = sh([PY, "tools/qa/decision_propagation.py", "--dry"], 900)
    add("propagation", "decision_propagation（K-OPS-D02）", code == 0, tail(out, 1)[:300])
    if run_tests:
        tests = pick_tests(changed)
        code, out = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", str(min(12, os.cpu_count() or 4)), *tests], 2400)
        flaky = []
        if code != 0:   # 并行下的偶发（story_runs 等）：失败的用例串行重跑一次，仍红才算不过
            failed = sorted(set(re.findall(r"^FAILED (\S+?)(?: - |$)", out, re.M)))
            if failed:
                c2, o2 = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *failed], 1200)
                if c2 == 0:
                    flaky, code, out = failed, 0, out + "\n串行重跑通过：" + "，".join(failed)
        m = re.search(r"(\d+) passed", out)
        add("pytest", f"定向 pytest（{len(tests)} 个文件：改动涉及 + smoke）", code == 0,
            tail(out, 2) + (f" ⏎ 并行偶发、串行通过：{flaky}" if flaky else ""))
        rows[-1]["passed"] = int(m.group(1)) if m else 0
        rows[-1]["files"] = tests
    return rows


def staged_problems() -> list[str]:
    bad = []
    names = [x for x in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0") if x]
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


def metrics(gate_rows: list[dict]) -> dict:
    m = {}
    try:
        idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
        m["kb_version"], m["rules"] = idx.get("kb_version"), idx.get("n")
    except (OSError, ValueError):
        pass
    for r in gate_rows:
        if r["id"] == "decision":
            m["decision_check"] = r["detail"]
        if r["id"] == "pytest":
            m["tests_passed"] = r.get("passed")
    code, out = sh([PY, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], 600)
    c = re.search(r"(\d+) tests? collected", out)
    m["tests_collected"] = int(c.group(1)) if c else None
    code, out = sh([PY, "tools/qa/data_parity.py"], 900)
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
def cut(base: str | None = None, dry: bool = False, sv: str | None = None, run_tests: bool = True) -> dict:
    prev = prev_ref(base)
    changed = pending_changes()
    files = [p for _s, p in changed]
    if not changed and not git("diff", "--name-only", prev, "HEAD").strip():
        return {"ok": False, "reason": "相对上一版没有任何改动，不发版"}
    g = gates(files, run_tests)
    fails = [x for x in g if not x["ok"]]
    sv = sv or next_id()
    rep = {"id": sv, "prev": prev, "gates": g}
    if fails:
        rep.update(ok=False, reason="闸门不过：" + "；".join(f"{x['name']}：{x['detail'][:200]}" for x in fails))
        return rep
    since = ref_time(prev)
    gr = gate_results(since)
    loops_line = loops_since(gr)
    if dry:
        rep.update(ok=True, dry=True, changed=len(changed), loops=loops_line)
        return rep
    git("add", "-A")
    probs = staged_problems()
    if probs:
        git("reset", "-q")
        rep.update(ok=False, reason="暂存区有不该进 git 的文件：" + "；".join(probs[:10]))
        return rep
    # 先按暂存区算差异写文档，文档一起进这次提交
    tree = git("write-tree").strip()
    rd, cd, cs = rule_diff(prev, tree), config_diff(prev, tree), code_stats(prev, tree)
    dec = owner_decisions(prev, tree)
    mt = metrics(g)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / f"{sv}.md").write_text(version_md(sv, prev, g, rd, cd, cs, gr, dec, mt, changed, loops_line), encoding="utf-8")
    entry = {"id": sv, "prev": prev, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files_changed": len(changed),
             "rules": rd, "config_files": sorted(cd), "code": cs, "gates": [{k: x[k] for k in ("id", "ok", "detail")} for x in g],
             "iter_gate": gr, "decisions": dec, "metrics": mt, "doc": f"docs/system_versions/{sv}.md", "deployed": {}}
    idx = write_index(entry)
    git("add", "-A", "docs/system_versions")
    msg = [f"{sv}：系统版本（K-OPS-V01）", "",
           "项目方 11-01 22:5x：“每一次迭代都是用 override system,然后用 create a new version 那个 system versions”",
           f"上一版：{prev}；改动文件 {len(changed)}；规则 +{len(rd['added'])} ~{len(rd['modified'])} 归档 {len(rd['archived'])}；kb {mt.get('kb_version')}",
           f"本版包含的 loop 轮次：{loops_line or '—'}", f"项目方 / 总调度决定：{'、'.join(dec) or '—'}",
           f"闸门：{'；'.join(x['name'] + ' 通过' for x in g)}", f"记录：docs/system_versions/{sv}.md", "", CO_AUTHOR]
    fd, mfn = tempfile.mkstemp(suffix=".txt")
    os.close(fd)                     # Windows：不关 fd，之后 unlink 报 WinError 32（sv-20261101-01 首跑踩到，commit 已成、tag 手补）
    mf = Path(mfn)
    mf.write_text("\n".join(msg) + "\n", encoding="utf-8")
    try:
        git("commit", "-q", "-F", str(mf))
    finally:
        mf.unlink(missing_ok=True)
    commit = git("rev-parse", "HEAD").strip()
    git("tag", "-a", sv, "-m", f"{sv} 系统版本（上一版 {prev}）")
    entry["commit"] = commit
    entry["remote_push"] = push_remote(prev, sv)          # 总调度 23:0x：发版后推 GitHub（失败不影响发版，记下来）
    write_index(entry)
    rep.update(ok=True, commit=commit, doc=entry["doc"], rules=rd, files=len(changed), current=idx.get("current"),
               remote_push=entry["remote_push"])
    return rep


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
    # git archive 出来是仓库里的 LF；工作区是 CRLF（autocrlf）。内容与该版本一致（git 认为没改）的文件用工作区原字节，
    # 免得只因换行符不同就整批重推、和日常 push 来回覆盖（sv-20261101-01 首次 deploy：gpu36 重推 292 个只差换行的文件）
    changed = set(x for x in git("diff", "--name-only", sv, "--", *dirs).splitlines() if x)
    for n in names:
        src = ROOT / n
        if n not in changed and src.is_file():
            (dest / n).write_bytes(src.read_bytes())
    return names


def deploy(sv: str | None = None, hosts: list[str] | None = None, restart: bool = True) -> dict:
    sv = sv or (sv_tags() or [None])[-1]
    if not sv:
        raise SystemExit("还没有任何系统版本，先 cut")
    rs = load_rs()
    hosts = hosts or list(rs.HOSTS)
    commit = git("rev-list", "-n", "1", sv).strip()
    tracked_code = [x for x in git("ls-tree", "-r", "--name-only", sv, "--", *rs.CODE_DIRS).split("\n") if x]
    drift = [p for _s, p in pending_changes() if p.startswith(tuple(d + "/" for d in rs.CODE_DIRS))]
    res = {"id": sv, "commit": commit, "hosts": {}, "drift_local": len(drift)}
    with tempfile.TemporaryDirectory(prefix="nsfs_sv_") as td:
        names = export_tag(sv, rs.CODE_DIRS, Path(td))
        for h in hosts:
            r = {"at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            try:
                rs.push(h, tier=1, yes=True)                         # 第一级推送（内含 push_gate，不过抛 PushGateFailed）
                live_root = rs.ROOT
                rs.ROOT = Path(td)                                    # 代码按该版本快照逐个核 sha，不同就重推（= 覆盖成这一版）
                try:
                    v = rs.verify_sha(h, [n for n in names if n in tracked_code], fix=True)
                finally:
                    rs.ROOT = live_root
                r["sha_checked"], r["sha_mismatch"], r["sha_fixed"] = v["checked"], len(v["mismatch"]), len(v["fixed"])
                if v["mismatch"]:
                    raise RuntimeError(f"{len(v['mismatch'])} 个代码文件与 {sv} 不一致：{v['mismatch'][:5]}")
                stamp = json.dumps({"id": sv, "commit": commit, "at": r["at"], "by": "tools/qa/system_version.py deploy"}, ensure_ascii=False)
                rs.ssh(h, f"cd {rs.R} && mkdir -p data && cat > data/system_version.txt && cat data/system_version.txt",
                       data=(stamp + "\n").encode(), tries=3)
                r["version_file"] = "data/system_version.txt"
                if restart:
                    r["restart"] = rs.restart(h).strip().replace("\n", "；")[-300:]
                    r["alive"] = rs.alive(h).replace("\n", "；")
                r["ok"] = True
            except Exception as e:  # noqa: BLE001
                r.update(ok=False, error=f"{type(e).__name__}: {e}"[:400])
            res["hosts"][h] = r
    idx = write_index()
    for v in idx["versions"]:
        if v["id"] == sv:
            v.setdefault("deployed", {}).update({h: r for h, r in res["hosts"].items() if r.get("ok")})
            write_index(v)
    (DATA / f"deploy_{sv}_{time.strftime('%H%M%S')}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def rollback(sv: str) -> dict:
    if sv not in sv_tags() and sv != BASELINE:
        raise SystemExit(f"没有版本 {sv}（现有：{sv_tags()}）")
    stat = git("diff", "--stat", "HEAD", sv)
    pend = pending_changes()
    cmds = [f"git stash push -u -m 'before rollback to {sv}'   # 仅当工作区有未入版改动（现在 {len(pend)} 个）",
            f"git checkout {sv} -- .", f".venv/Scripts/python.exe tools/qa/system_version.py cut --base {sv}   # 回退本身也记一版",
            ".venv/Scripts/python.exe tools/qa/system_version.py deploy"]
    return {"target": sv, "preview_stat": tail(stat, 40), "pending_local": len(pend), "commands": cmds,
            "note": "只生成命令与差异预览，未执行；执行要总调度确认（K-OPS-V01）"}


def status() -> dict:
    t = sv_tags()
    return {"current": t[-1] if t else None, "versions": t, "pending": len(pending_changes()),
            "head": git("rev-parse", "--short", "HEAD").strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="系统版本：cut / deploy / rollback / status（K-OPS-V01）")
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("cut")
    c.add_argument("--base")
    c.add_argument("--dry", action="store_true")
    c.add_argument("--id")
    d = sp.add_parser("deploy")
    d.add_argument("sv", nargs="?")
    d.add_argument("--hosts")
    d.add_argument("--no-restart", action="store_true")
    r = sp.add_parser("rollback")
    r.add_argument("sv")
    sp.add_parser("status")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if a.cmd == "cut":
        out = cut(a.base, a.dry, a.id)
        print(json.dumps({k: v for k, v in out.items() if k != "gates"}, ensure_ascii=False, indent=1)[:4000])
        for gg in out.get("gates", []):
            print(f"  {'✅' if gg['ok'] else '❌'} {gg['name']}：{gg['detail'][:200]}")
        return 0 if out.get("ok") else 1
    if a.cmd == "deploy":
        out = deploy(a.sv, a.hosts.split(",") if a.hosts else None, not a.no_restart)
        print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
        return 0 if out["hosts"] and all(x.get("ok") for x in out["hosts"].values()) else 1
    if a.cmd == "rollback":
        print(json.dumps(rollback(a.sv), ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(status(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
