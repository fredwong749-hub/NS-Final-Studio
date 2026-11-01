"""迭代收轮闸门（ITERAUDIT 2026-11-01；协议见 docs/ITERATION_PROTOCOL.md）。

任何 loop（UIMASTER / UIRSI / UIPIXEL / UIAUDIT / ASSETUX / EDITDEL / ASSETMASTER / REFLOCK / IMGGEN / VIDEO10 /
BAKEOFF / AUTOPILOT）在宣布“本轮完成”之前必须跑它；退出码 0 才算完成。

    .venv/Scripts/python.exe tools/qa/iter_gate.py --loop UIRSI --round r29 --task OT1,OT4 \
        --changed apps/web/src/v3/ReviewRow.tsx,apps/web/src/v3/pages/ScriptPage.tsx \
        --verifier UIAUDIT --verify-evidence apps/web/e2e/uiaudit/r6g_detect.json \
        --report docs/uirsi/rounds/r29.md --rules K-UI-033

    # 生成类 loop：
    .venv/Scripts/python.exe tools/qa/iter_gate.py --loop IMGGEN --round g7 --task OT9 \
        --changed tools/series10_imggen/imggen.py --contract data/pipeline/runs/series10_v1/images/contract.json \
        --verifier REFLOCK --verify-evidence data/review_pages/series10_images/verify.md --report ... --no-lesson "只换 seed"

聚合的检查（id → 内容）：
  S0 项目方任务     --task 必须是 tools/qa/ownership.yaml owner_tasks 里的 OTn
  K1 知识库         tools/knowledge/compile.py --check
  K2 链条契约       tools/pipeline/check_chain.py
  O1 所有权         --changed 的每个文件属于本 loop，或 owner 在 LOCKS.md 写了 CONSENT 授权行，或属于 shared；否则 = fail
  O2 撞车提示       最近 --window 分钟内被改过、且 owner 不是本 loop 的文件（只提示）
  U1 前端构建       apps/web/e2e/uimaster/gate.sh（tsc + vite build + dev 模块可取）
  R1 功能不回退 G10 最新 apps/web/e2e/uiaudit/rNg_detect.json（按修改时间，再按轮号） 必须比本轮改动新 → regress_check.mjs 退出 0
  D1 数据一致       tools/qa/data_parity.py（DATAALIGN）；不存在 = 未测（≠ 通过）
  C1 生成契约       --contract 里的 ContractResult：fail / untested / “ok 但有阻断项”（冒充通过）
  C2 总调度亲审     --for-owner 时 --review-dir 下必须有 master_review.md（GEN_CONTRACT §0.3）
  V1 独立复核       --verifier ≠ --loop，且 --verify-evidence 存在、比本轮最新改动新
  L1 账本 / 报告    --report 存在；7 步关键词齐；引用的路径都存在；带数字的结论行同一行要有出处
  RL 规则有检查     --rules 每条在 knowledge 里且有 check 字段（指向存在的文件 / 测试）；或 --no-lesson "<理由>"
  H1 内容缺陷猎捕   生成类 loop：tools/qa/defect_hunt.py 的 state 必须比最新首帧 / 视频评分 / 成片新（K-OPS-Q13）
  A1 结构棘轮       tools/qa/arch_scan.py --files <本轮 .py> --check：任一文件结构退化计数比 data/sysarch/baseline.json 多 = fail（K-OPS-S01，SYSARCH）
  V2 系统版本       本轮 --changed 是否已进系统版本（git tag sv-*，tools/qa/system_version.py cut）；没进只提示（K-OPS-V01）
  Y1 语法守卫       tools/qa/syntax_guard.py 全仓：写断的字符串 / 语法错误 / 非法转义 / 未定义名 / 项目内导入失效（K-OPS-C01，CODE-RSI）
  T1 测试           --tests 给的 pytest 路径；带真实数据写保护（tests/conftest.py + tools/qa/real_data_guard.py），写真实 data/ / 遗留线程 / 哨兵文件被改 = fail
结果：pass / fail / untested / na / warn。任何 fail → 退出 1（FAIL）；必需项 untested → 退出 2（INCOMPLETE，不得宣布完成）。
产物：data/qa/iter_gate/<loop>_<round>.json 与 .md。只读检查，不改别人的文件，不起停服务。
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv/Scripts/python.exe") if (ROOT / ".venv/Scripts/python.exe").exists() else sys.executable
OUT = ROOT / "data/qa/iter_gate"
LOCKS = ROOT / "docs/uimaster/LOCKS.md"
UIAUDIT_DIR = ROOT / "apps/web/e2e/uiaudit"
# 授权行（docs/uimaster/LOCKS.md “## 授权” 一节；docs/ITERATION_PROTOCOL.md §4）：
#   CONSENT: <文件 owner> -> <被授权 agent> : <路径或 glob> | <原话 / 日期>
CONSENT_RE = re.compile(r"^\s*(?:[-*]\s*)?`?CONSENT:\s*([A-Z][A-Z0-9_]*)\s*(?:->|→)\s*([A-Z][A-Z0-9_]*)\s*:\s*([^\s|`]+)")
REGRESS_RE = re.compile(r"^r(\d+)g_detect\.json$")
UI_LOOPS = {"UIMASTER", "UIRSI", "UIPIXEL", "UIAUDIT", "ASSETUX", "EDITDEL"}
GEN_LOOPS = {"ASSETMASTER", "REFLOCK", "IMGGEN", "VIDEO10", "BAKEOFF", "AUTOPILOT"}
RULE_LOOPS = {"ITERAUDIT"}   # 规则系统 loop（RSI 别名映射到这里）：C1 生成契约判“不适用”（总调度 11-01 晚）
STEP_WORDS = {  # 报告里 7 步的关键词（任一即可）
    "1 场景": ("项目方任务", "OT"), "2 度量": ("度量", "正确性"), "3 改动": ("改动", "改了"),
    "4 独立复核": ("独立复核", "复核"), "5 回归": ("回归",), "6 证据": ("证据",), "7 规则": ("规则", "K-"),
}
PATH_RE = re.compile(r"(?<![\w/.-])((?:apps|docs|tools|services|data|config|knowledge|tests|packages)/[\w./\-\u4e00-\u9fff]+)")
NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|分|/\s*\d+|→|×|个|条|张|镜|秒|s\b)")
SRC_RE = re.compile(r"(?:apps|docs|tools|services|data|config|knowledge|tests)/|\.(?:md|json|png|jpg|py|mjs|js|tsx?|ya?ml|txt|log|html|mp4|wav)\b|§")


def rel(p: str | Path) -> str:
    p = Path(p)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def sh(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"超时 {timeout}s"
    except FileNotFoundError as e:
        return 127, str(e)


def tail(s: str, n: int = 4) -> str:
    return " ⏎ ".join([x for x in s.splitlines() if x.strip()][-n:])[:600]


def glob_match(path: str, pat: str) -> bool:
    if pat.endswith("/**"):
        return path == pat[:-3] or path.startswith(pat[:-2])
    if "**/" in pat:  # apps/web/src/**/*.css
        head, rest = pat.split("**/", 1)
        return path.startswith(head) and fnmatch.fnmatch(path.rsplit("/", 1)[-1], rest)
    return fnmatch.fnmatch(path, pat)


def load_own() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "tools/qa/ownership.yaml").read_text(encoding="utf-8"))


def parse_consents(text: str) -> list[dict]:
    """LOCKS.md 文本 → [{owner, agent, glob}]；格式见 CONSENT_RE"""
    out = []
    for ln in text.splitlines():
        m = CONSENT_RE.match(ln)
        if m:
            # CODE-RSI 11-01（K-OPS-C06）：路径后紧跟的中文 / 英文括号说明（“xx.py（只改 …）”）不属于路径，原来整段被当成 glob → 授权永远对不上
            g = re.split(r"[（(]", m.group(3), 1)[0].rstrip("，,、")
            out.append({"owner": m.group(1), "agent": m.group(2), "glob": g})
    return out


def load_consents(path: Path | None = None) -> list[dict]:
    p = path or LOCKS
    return parse_consents(p.read_text(encoding="utf-8")) if p.exists() else []


def consented(path: str, owner: str, agent: str, consents: list[dict]) -> dict | None:
    return next((c for c in consents if c["owner"] == owner and c["agent"] == agent and glob_match(path, c["glob"])), None)


def newest_regress_detect(d: Path | None = None) -> Path | None:
    """UIAUDIT 最新一份功能回退 detect（rNg_detect.json）：先比修改时间，同时间再比轮号（不写死某一轮）"""
    d = d or UIAUDIT_DIR
    c = [(p.stat().st_mtime, int(m.group(1)), p) for p in d.glob("r*g_detect.json") if (m := REGRESS_RE.match(p.name))]
    return max(c, key=lambda x: (x[0], x[1]))[2] if c else None


def as_list(x) -> list:
    return [] if x in (None, "", []) else (x if isinstance(x, list) else [x])


def has_check(r: dict) -> bool:
    return bool(r.get("check") or r.get("targets") or r.get("loop"))


def load_rules() -> tuple[dict, dict]:
    """→ ({id: 条目}, {id: 文件相对路径})"""
    import yaml
    rules, files = {}, {}
    for f in sorted((ROOT / "knowledge/rules").glob("*.yaml")):
        for r in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("rules") or []:
            rules[r.get("id")] = r
            files[r.get("id")] = rel(f)
    return rules, files


WRITER_LINKS = {"P0-P1", "P1-P2", "P2-P3", "P3-P4"}
LINT_SOURCES = ("tools/validate_qwen_script.py", "tools/qa/writer_lints.py", "packages/schema/ns_schema",
                "services/recipes/ns_recipes", "tools/pipeline",
                # RSI 11-01：validate_qwen_script 动态加载的两套 lint（规则号字面量在它们自己的文件里）
                "tools/qa/acting_lints.py", "tools/vqa/script_lint.py")
# 派单名 → ownership.yaml 里的 loop 名（总调度派 “RSI loop（含 ITERAUDIT 职责）”，文件归 ITERAUDIT）
LOOP_ALIASES = {"RSI": "ITERAUDIT", "WORKFLOW": "AUTOPILOT", "VIDEO-RCA": "VIDEO_RCA", "CODE-RSI": "CODERSI", "CODE_RSI": "CODERSI", "SCRIPT-RSI": "SCRIPT_RSI"}
# 一个派单名对应多个 ownership 条目（总调度 11-01 晚：PROD = VIDEO10 + PRODUCER）
LOOP_GROUPS = {"PROD": {"VIDEO10", "PRODUCER"}}


def writer_relevant(r: dict) -> bool:
    return r.get("domain") == "writer" or bool(set(as_list(r.get("link"))) & WRITER_LINKS)


def lint_defined(lid: str) -> bool:
    for src in LINT_SOURCES:
        p = ROOT / src
        for f in ([p] if p.is_file() else p.glob("*.py")):
            try:
                if f'"{lid}"' in f.read_text(encoding="utf-8"):
                    return True
            except OSError:
                continue
    return False


def writer_gaps(r: dict) -> str:
    """写作相关规则缺什么（空 = 齐）：writer_prompt 目标 + writer_text + lint（规则号在 P4 校验器里有定义）"""
    if not writer_relevant(r):
        return ""
    miss = []
    if not any(t.get("kind") == "writer_prompt" for t in as_list(r.get("targets"))) and not r.get("covered_by"):
        miss.append("缺 writer_prompt 目标")
    if not r.get("writer_text") and not r.get("covered_by"):
        miss.append("缺 writer_text")
    lints = as_list(r.get("lint"))
    if not lints:
        miss.append("缺 lint（P4 校验规则号）")
    miss += [f"lint {x} 在校验器里找不到" for x in lints if not lint_defined(str(x))]
    return "、".join(miss)


def rule_owner(rid: str, file: str, own: dict) -> str:
    ro = own.get("rule_owners", {})
    for pat, o in (ro.get("by_id") or {}).items():
        if re.fullmatch(pat, rid):
            return o
    return (ro.get("by_file") or {}).get(file.rsplit("/", 1)[-1], "未指派")


def unchecked_report(out: Path) -> str:
    """docs/master/unchecked_rules.md：无检查规则按 owner 列（总调度 11-01：进 MASTER_PICTURE 缺口清单）"""
    own = load_own()
    rules, files = load_rules()
    by: dict[str, list[str]] = {}
    for i, r in rules.items():
        if not has_check(r):
            by.setdefault(rule_owner(i, files[i], own), []).append(i)
    total = sum(len(v) for v in by.values())
    md = ["# 无强制检查的规则（按 owner）", "",
          f"生成：`.venv/Scripts/python.exe tools/qa/iter_gate.py --list-unchecked`（{time.strftime('%Y-%m-%d %H:%M')}）。"
          f"共 {total} / {len(rules)} 条（来源 knowledge/rules/*.yaml；“有检查” = check 字段或 targets / loop 块）。",
          "", "总调度 11-01 决定：这些规则标 `enforced: false`，继续作为指引生效、不降级为草案；各 owner 在 sweep 里逐条补 `check:`"
          "（测试 / 校验器 / gate 路径）后删掉 `enforced: false`。iter_gate 的 RL 项只对**新**规则缺检查判不通过。", "",
          "| owner | 条数 | 规则 id（文件） |", "|---|---|---|"]
    for o, ids in sorted(by.items(), key=lambda kv: -len(kv[1])):
        grp: dict[str, list[str]] = {}
        for i in ids:
            grp.setdefault(files[i], []).append(i)
        md.append(f"| {o} | {len(ids)} | " + "；".join(f"{', '.join(v)}（{k}）" for k, v in grp.items()) + " |")
    text = "\n".join(md) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


def owner_of(path: str, own: dict) -> tuple[str | None, str | None]:
    """→ (owner, shared_via)；override 先匹配（总调度 11-01：全部 CSS 归 UIPIXEL），其余最具体的匹配优先"""
    for ov in own.get("override") or []:
        if glob_match(path, ov["glob"]):
            return ov["owner"], None
    best = (None, -1)
    for o, pats in own["owners"].items():
        for pt in pats:
            if glob_match(path, pt) and len(pt) > best[1]:
                best = (o, len(pt))
    hit = next((s for s in own.get("shared", []) if glob_match(path, s["glob"])), None)
    shared = hit["via"] if hit else None
    # 共享条目比 owner 的通配更具体（例：docs/uimaster/LOCKS.md 是写 CONSENT 的共享入口，而 docs/uimaster/** 归 UIMASTER）→ 按共享算
    if hit and best[0] and len(hit["glob"]) > best[1]:
        return None, shared
    return best[0], shared


def uncompiled_rule_files() -> list[tuple[str, str]]:
    """比 knowledge/generated/index.json 新的规则文件 + 它的 owner（总调度 11-01：改了规则不编译，记到它名下）"""
    gen = ROOT / "knowledge/generated/index.json"
    t = gen.stat().st_mtime if gen.exists() else 0
    own = load_own()
    out = []
    for f in sorted((ROOT / "knowledge/rules").glob("*.yaml")):
        if f.stat().st_mtime > t:
            out.append((rel(f), rule_owner("", rel(f), own)))
    return out


def propagation_results() -> list[dict]:
    """tools/qa/decision_propagation.run()（按路径加载，避免同名脚本撞车 K-OPS-Q11）"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("ns_decision_propagation_gate", ROOT / "tools/qa/decision_propagation.py")
    dp = ilu.module_from_spec(spec)
    spec.loader.exec_module(dp)
    return dp.run()


class Gate:
    def __init__(self, a):
        self.a, self.rows = a, []
        self.loop = LOOP_ALIASES.get(a.loop.upper(), a.loop.upper())
        self.loops = LOOP_GROUPS.get(self.loop, set()) | {self.loop}     # 本 loop 名下的全部 ownership 条目
        self.changed = [rel(x.strip()) for x in ",".join(a.changed or []).split(",") if x.strip()]
        mts = [(ROOT / c).stat().st_mtime for c in self.changed if (ROOT / c).exists()]
        self.newest_change = max(mts) if mts else 0.0
        self.ui = self.loop in UI_LOOPS or any(c.startswith("apps/web/") for c in self.changed) or a.ui
        self.api = any(c.startswith("services/api/") for c in self.changed)
        self.gen = bool(self.loops & GEN_LOOPS)

    def add(self, cid, name, status, detail="", required=True):
        self.rows.append({"id": cid, "name": name, "status": status, "detail": detail, "required": required})

    # ---------- 各项 ----------
    def s0_task(self, own):
        tasks = [t.strip() for t in (self.a.task or "").split(",") if t.strip()]
        bad = [t for t in tasks if t not in own.get("owner_tasks", {})]
        if not tasks:
            self.add("S0", "项目方任务场景", "fail", "没有 --task：每轮必须从项目方任务 OT1–OT9 出发")
        elif bad:
            self.add("S0", "项目方任务场景", "fail", f"未知任务 {bad}")
        else:
            self.add("S0", "项目方任务场景", "pass", "；".join(f"{t} {own['owner_tasks'][t]['name']}" for t in tasks))

    def k1_knowledge(self):
        code, out = sh([PY, "tools/knowledge/compile.py", "--check"], 300)
        det = tail(out, 3)
        if code != 0 and "过期" in out:
            det += " ⏎ 改了规则没编译：" + "；".join(f"{f}（{o}）" for f, o in uncompiled_rule_files())
        self.add("K1", "知识库 compile --check", "pass" if code == 0 else "fail", det)

    def k2_chain(self):
        if not (ROOT / "tools/pipeline/check_chain.py").exists():
            return self.add("K2", "链条契约 check_chain", "na", "没有 check_chain.py", False)
        code, out = sh([PY, "tools/pipeline/check_chain.py"], 300)
        self.add("K2", "链条契约 check_chain", "pass" if code == 0 else "fail", tail(out, 3))

    def o1_ownership(self, own):
        if not self.changed:
            return self.add("O1", "所有权（改动文件归属）", "untested", "没有 --changed：本轮改了哪些文件必须声明")
        if not self.loops & set(own.get("owners") or {}):     # K-OPS-Q22：新派 loop 开工前先在 ownership.yaml 登记
            return self.add("O1", "所有权（改动文件归属）", "fail",
                            f"loop {self.loop} 在 tools/qa/ownership.yaml 里没有条目：开工前先由总调度登记它的文件（K-OPS-Q22）")
        mine, shared, foreign, orphan, ok_by = [], [], [], [], []
        cons = load_consents()
        for c in self.changed:
            o, via = owner_of(c, own)
            if o in self.loops:
                mine.append(c)
            elif o and any(consented(c, o, lp, cons) for lp in self.loops):
                ok_by.append(f"{c}（{o} 已在 LOCKS.md 授权）")
            elif via and (o is None or o in self.loops):
                shared.append(f"{c}（只能经：{via}）")
            elif o:
                foreign.append(f"{c} → 属于 {o}")
            else:
                orphan.append(c)
        st = "fail" if foreign else ("warn" if orphan or shared else "pass")
        det = f"本 loop {len(mine)}；owner 授权 {len(ok_by)}；共享 {len(shared)}；越界 {len(foreign)}；无主 {len(orphan)}"
        det += "".join(f" ⏎ 授权 {x}" for x in ok_by[:6])
        det += "".join(f" ⏎ 越界 {x}" for x in foreign[:8]) + "".join(f" ⏎ 共享 {x}" for x in shared[:6])
        det += "".join(f" ⏎ 无主（请总调度登记 ownership.yaml）{x}" for x in orphan[:6])
        self.add("O1", "所有权（改动文件归属）", st, det)

    def o2_collision(self, own):
        win = self.a.window * 60
        now, hits = time.time(), []
        for top in ("apps/web/src", "services", "tools", "config", "knowledge/rules"):
            for dp, dn, fn in os.walk(ROOT / top):
                dn[:] = [d for d in dn if d not in ("node_modules", "__pycache__", "dist", ".git")]
                for f in fn:
                    p = Path(dp) / f
                    try:
                        if now - p.stat().st_mtime > win:
                            continue
                    except OSError:
                        continue
                    r = rel(p)
                    o, via = owner_of(r, own)
                    if o not in self.loops and r not in self.changed:
                        hits.append(f"{r}（{o or ('共享' if via else '无主')}）")
        overlap = [h for h in hits if any(h.startswith(c) for c in self.changed)]
        self.add("O2", f"撞车提示（近 {self.a.window} 分钟别人改的文件）", "warn" if hits else "pass",
                 f"{len(hits)} 个" + "".join(f" ⏎ {h}" for h in (overlap + hits)[:10]), False)

    def u1_frontend(self):
        if not self.ui:
            return self.add("U1", "前端构建 gate.sh", "na", "本轮没改前端", False)
        bash = shutil.which("bash") if os.name != "nt" else r"C:\Program Files\Git\bin\bash.exe"
        if not bash or not Path(bash).exists():
            return self.add("U1", "前端构建 gate.sh", "untested", "找不到 Git Bash")
        if self.a.skip_build:
            return self.add("U1", "前端构建 gate.sh", "untested", "--skip-build（本次未跑，不算通过）")
        code, out = sh([bash, "apps/web/e2e/uimaster/gate.sh"], 900)
        self.add("U1", "前端构建 gate.sh", "pass" if code == 0 and "GATE OK" in out else "fail", tail(out, 3))

    def r1_regress(self):
        if not self.ui:
            return self.add("R1", "功能不回退 G10", "na", "本轮没改前端", False)
        f = newest_regress_detect()
        if not f:
            return self.add("R1", "功能不回退 G10", "untested", "没有 rNg_detect.json：先跑 detect.mjs flows_regress.json rN")
        age_ok = f.stat().st_mtime >= self.newest_change
        code, out = sh(["node", "apps/web/e2e/uiaudit/regress_check.mjs", rel(f)], 120)
        m = re.search(r"P0 回退 (\d+) 条 / 基线 (\d+) 条", out)
        det = f"{rel(f)}：" + (m.group(0) if m else tail(out, 2))
        if "本轮作废" in out:
            return self.add("R1", "功能不回退 G10", "fail", det + "；G0 白屏 / 报错层，结果作废")
        if code != 0:
            return self.add("R1", "功能不回退 G10", "fail", det)
        if not age_ok:
            return self.add("R1", "功能不回退 G10", "untested", det + "；但这份 detect 比本轮改动旧 → 改完要重跑 detect（pwsh run_round.ps1 rN）")
        self.add("R1", "功能不回退 G10", "pass", det)

    def d1_parity(self):
        need = self.ui or self.api or any(t in (self.a.task or "") for t in ("OT1", "OT2", "OT3", "OT4", "OT5", "OT6", "OT7"))
        p = ROOT / "tools/qa/data_parity.py"
        if not p.exists():
            return self.add("D1", "数据一致（前端 = 后端）", "untested" if need else "na",
                            "tools/qa/data_parity.py 还没交付（DATAALIGN）——未测 ≠ 通过", need)
        code, out = sh([PY, "tools/qa/data_parity.py", *self.a.parity_args.split()], 900)
        self.add("D1", "数据一致（前端 = 后端）", "pass" if code == 0 else "fail", tail(out, 4), need)

    def c1_contract(self):
        files = [x for x in ",".join(self.a.contract or []).split(",") if x.strip()]
        need = (self.gen or "OT9" in (self.a.task or "")) and self.loop not in RULE_LOOPS   # 规则系统 loop 不产出契约 JSON（总调度 11-01）
        if not files:
            return self.add("C1", "生成契约逐项", "untested" if need else "na", "没有 --contract（契约逐项结果 JSON）", need)
        n = ok = 0
        bad, forged, untested = [], [], []

        def walk(o, where):
            nonlocal n, ok
            if isinstance(o, dict):
                if "items" in o and isinstance(o["items"], list) and ("stage" in o or "contract_version" in o):
                    n += 1
                    blk = [i.get("id") for i in o["items"] if isinstance(i, dict) and i.get("status") not in ("pass", "na")]
                    unt = [i.get("id") for i in o["items"] if isinstance(i, dict) and i.get("status") == "untested"]
                    subj = o.get("subject", where)
                    if o.get("ok") and blk:
                        forged.append(f"{subj} ok=true 但 {blk}")
                    elif blk:
                        (untested if set(blk) <= set(unt) else bad).append(f"{subj} {blk}")
                    else:
                        ok += 1
                    return
                for k, v in o.items():
                    walk(v, f"{where}.{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{where}[{i}]")
        for f in files:
            p = ROOT / f.strip()
            if not p.exists():
                return self.add("C1", "生成契约逐项", "fail", f"契约文件不存在 {f}")
            walk(json.loads(p.read_text(encoding="utf-8")), rel(p))
        if n == 0:
            return self.add("C1", "生成契约逐项", "fail", "文件里没有 ContractResult（stage/items）")
        det = f"{n} 条：通过 {ok}，不通过 {len(bad)}，只差未测 {len(untested)}，冒充通过 {len(forged)}"
        det += "".join(f" ⏎ 冒充 {x}" for x in forged[:5]) + "".join(f" ⏎ 不过 {x}" for x in bad[:5])
        st = "fail" if forged else ("warn" if bad or untested else "pass")  # 不通过的可以存在，但只能标“不合格”，不得进下游
        self.add("C1", "生成契约逐项", st, det + ("；不通过 / 未测的条目只能标“不合格 / 尽力”，不得进下游或给项目方" if bad or untested else ""), need)

    def c2_master(self):
        if not self.a.for_owner:
            return self.add("C2", "总调度亲审签字", "na", "本轮不给项目方看", False)
        d = ROOT / (self.a.review_dir or "__none__")
        sig = sorted(d.glob("master_review*.md"), key=os.path.getmtime) if d.is_dir() else []
        if not sig:
            return self.add("C2", "总调度亲审签字", "fail", f"{rel(d)} 下没有 master_review*.md（GEN_CONTRACT §0.3：签字后才能给项目方）")
        newest = max((p.stat().st_mtime for p in d.rglob("*") if p.is_file() and not p.name.startswith("master_review")), default=0)
        if sig[-1].stat().st_mtime < newest:
            return self.add("C2", "总调度亲审签字", "fail", f"{rel(sig[-1])} 比页面内容旧：签字后页面又改过，要重签")
        self.add("C2", "总调度亲审签字", "pass", rel(sig[-1]))

    def v1_verify(self):
        v = (self.a.verifier or "").upper()
        ev = ROOT / (self.a.verify_evidence or "__none__")
        if not v:
            return self.add("V1", "独立复核", "untested", "没有 --verifier：改的人不能自己判通过")
        if LOOP_ALIASES.get(v, v) in self.loops:
            return self.add("V1", "独立复核", "fail", "复核方 = 改动方（自评）")
        if not ev.exists():
            return self.add("V1", "独立复核", "untested", f"复核证据不存在：{self.a.verify_evidence or '没给 --verify-evidence'}")
        if ev.stat().st_mtime < self.newest_change:
            return self.add("V1", "独立复核", "untested", f"{rel(ev)} 比本轮最新改动旧，复核的不是这一版")
        self.add("V1", "独立复核", "pass", f"{v}：{rel(ev)}")

    def l1_report(self):
        if not self.a.report:
            return self.add("L1", "账本 / 报告（带证据）", "untested", "没有 --report")
        p = ROOT / self.a.report
        if not p.exists():
            return self.add("L1", "账本 / 报告（带证据）", "fail", f"不存在 {self.a.report}")
        txt = p.read_text(encoding="utf-8", errors="replace")
        miss_step = [k for k, ws in STEP_WORDS.items() if not any(w in txt for w in ws)]
        miss_path, unsourced, in_code = [], [], False
        for ln in txt.splitlines():
            if ln.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            pending = re.search(r"待交付|还没交付|未生成|尚未生成|交付前|结果写在|产物：", ln)
            for m in ([] if pending else PATH_RE.findall(ln)):
                q = m.rstrip("。，；、）)」.:：,")
                if "*" in q or "<" in q or "{" in q:
                    continue
                if not (ROOT / q).exists() and not glob.glob(str(ROOT / q) + "*"):
                    miss_path.append(q)
            if NUM_RE.search(ln) and not SRC_RE.search(ln) and not ln.lstrip().startswith("#"):
                unsourced.append(ln.strip()[:90])
        st = "fail" if (miss_path or miss_step or unsourced) else "pass"
        det = f"{rel(p)}：缺步骤 {miss_step or '无'}；引用不存在 {len(miss_path)}；无出处数字行 {len(unsourced)}"
        det += "".join(f" ⏎ 不存在 {x}" for x in sorted(set(miss_path))[:5]) + "".join(f" ⏎ 无出处 {x}" for x in unsourced[:5])
        self.add("L1", "账本 / 报告（带证据）", st, det)

    def rl_rules(self):
        """总调度 11-01：旧的无检查规则标 enforced: false（保留为指引，不打回）；只有“新”规则（没标 enforced: false）
        缺检查才 fail。有检查 = check 字段，或 targets / loop 块（compile.py 生成 / 校验下游）。"""
        rules, files = load_rules()
        legacy, new_bad, bad_path = [], [], []
        changed_files = {c for c in self.changed if c.startswith("knowledge/rules/")}
        for i, r in rules.items():
            for c in as_list(r.get("check")):
                path = re.split(r"\s|::|§|#", str(c), 1)[0]
                if not (ROOT / path).exists():
                    bad_path.append(f"{i} check 指向不存在 {path}")
            if has_check(r):
                continue
            (legacy if r.get("enforced") is False else new_bad).append(i)
        ids = [x.strip() for x in (self.a.rules or "").split(",") if x.strip()]
        mine_new = [i for i in new_bad if i in ids or files.get(i) in changed_files]
        others_new = [i for i in new_bad if i not in mine_new]
        miss = [i for i in ids if i not in rules]
        mine_legacy = [i for i in ids if i in legacy]
        # 项目方 11-01：“发现 bug、找到 solution 后把规则写到系统 code，剧本 LLM 好自动改进”——写作相关的新规则
        # 必须同时有 writer_prompt 目标 + writer_text（进 writer_knowledge.md）和 lint（P4 校验规则号，返修环能拦）
        writer_gap = [f"{i}：{g}" for i in sorted(set(ids) | set(mine_new)) if i in rules
                      for g in [writer_gaps(rules[i])] if g]
        det = (f"无检查的旧规则 {len(legacy)} 条（enforced: false，只作指引，见 docs/master/unchecked_rules.md）；"
               f"本轮新规则缺检查 {len(mine_new)}；别的 loop 新规则缺检查 {len(others_new)}")
        det += "".join(f" ⏎ 缺检查（新）{i}（{files[i]}）" for i in mine_new[:8])
        det += "".join(f" ⏎ 别人的新规则缺检查 {i}（{files[i]}）" for i in others_new[:5])
        det += "".join(f" ⏎ 不在知识库 {i}" for i in miss) + "".join(f" ⏎ {x}" for x in bad_path[:5])
        det += "".join(f" ⏎ 本轮改的是旧规则 {i}：顺手补 check 并删 enforced: false" for i in mine_legacy[:5])
        det += "".join(f" ⏎ 写作规则不完整 {x}" for x in writer_gap[:6])
        if mine_new or miss or bad_path or writer_gap:
            return self.add("RL", "规则 + 强制检查", "fail", det)
        if not ids and not self.a.no_lesson:
            return self.add("RL", "规则 + 强制检查", "untested", "没有 --rules 也没有 --no-lesson ⏎ " + det)
        st = "warn" if others_new or mine_legacy else ("na" if self.a.no_lesson else "pass")
        self.add("RL", "规则 + 强制检查", st, (f"本轮无新教训：{self.a.no_lesson} ⏎ " if self.a.no_lesson else "") + det,
                 not self.a.no_lesson)

    def h1_hunt(self):
        """内容缺陷猎捕（K-OPS-Q13，项目方 R11-11）：生成类 loop 收轮前，data/qa/defect_hunt/state.json 要比最新产出新"""
        need = self.gen
        st = ROOT / "data/qa/defect_hunt/state.json"
        outs = [*glob.glob(str(ROOT / "data/renders/ep[0-9]*/S*/takes.json")),
                *glob.glob(str(ROOT / "data/pipeline/runs/series10_v1/video/scores/*.json")),
                *glob.glob(str(ROOT / "data/episodes/series10/*.timeline.json"))]
        newest = max((os.path.getmtime(f) for f in outs), default=0)
        if not st.exists():
            return self.add("H1", "内容缺陷猎捕", "untested" if need else "na", "没有 data/qa/defect_hunt/state.json：跑 tools/qa/defect_hunt.py", need)
        try:
            d = json.loads(st.read_text(encoding="utf-8"))
        except ValueError:
            return self.add("H1", "内容缺陷猎捕", "fail", "state.json 坏了", need)
        last = max((time.mktime(time.strptime(c["at"], "%Y-%m-%dT%H:%M:%S")) for c in d.get("classes", {}).values() if c.get("at")), default=0)
        hits = sum(c.get("hits") or 0 for c in d.get("classes", {}).values())
        err = [k for k, c in d.get("classes", {}).items() if c.get("status") == "error"]
        det = f"{len(d.get('classes', {}))} 类，命中 {hits} 处；最近一次 {time.strftime('%m-%d %H:%M', time.localtime(last))}"
        if err:
            return self.add("H1", "内容缺陷猎捕", "fail", det + f"；检测器出错 {err[:5]}", need)
        if last < newest:
            return self.add("H1", "内容缺陷猎捕", "untested" if need else "warn",
                            det + f"；之后又有新产出（{time.strftime('%m-%d %H:%M', time.localtime(newest))}）→ 重跑 tools/qa/defect_hunt.py --force", need)
        self.add("H1", "内容缺陷猎捕", "pass", det + "（命中按 docs/rsi/DEFECT_HUNT.md 分派）", need)

    def g0_propagation(self):
        """K-OPS-D02（§G0）：决策全量同步。归本 loop 的文件（或本轮改过的文件）里还有未标 ⤴ 的过期口径 / 没跟上新口径 = 不通过；
        别的 loop 的残留只提示（总调度 11-01：残留只算归该 loop 的文件）"""
        try:
            res = propagation_results()
        except Exception as e:  # noqa: BLE001
            return self.add("G0", "决策全量同步（K-OPS-D02）", "untested", f"decision_propagation 跑不了：{e!r}"[:200], False)
        stale = [s for r in res for s in r["stale"]]
        unsynced = [u for r in res for u in r["unsynced"]]
        own = load_own()

        def owned(f: str) -> bool:      # 归本 loop：ownership 的 owner，或规则文件按 rule_owners.by_file；本轮改过的也算
            o = owner_of(f, own)[0] or (own.get("rule_owners", {}).get("by_file") or {}).get(f.rsplit("/", 1)[-1], "")
            return f in self.changed or str(o).split("（")[0] in self.loops
        mine = [s for s in stale if owned(s["file"])] + [u for u in unsynced if owned(u["file"])]
        det = f"决定 {len(res)} 条；过期口径残留 {len(stale)} 处、必须同步未跟上 {len(unsynced)} 个文件（data/qa/decision_propagation/report.md）"
        if mine:
            return self.add("G0", "决策全量同步（K-OPS-D02）", "fail",
                            det + "；归本 loop（或本轮改过）的文件里还有：" + "；".join(f"{x['file']}:{x.get('line', '')}" for x in mine[:5]), True)
        self.add("G0", "决策全量同步（K-OPS-D02）", "warn" if (stale or unsynced) else "pass", det, False)

    def y1_syntax(self):
        # K-OPS-C01（CODE-RSI 11-01）：任何 loop 收轮前全仓 Python 必须能编译、无未定义名、项目内导入都解析得到
        if not (ROOT / "tools/qa/syntax_guard.py").exists():
            return self.add("Y1", "全仓语法守卫", "untested", "没有 tools/qa/syntax_guard.py")
        code, out = sh([PY, "tools/qa/syntax_guard.py"], 300)
        st = {0: "pass", 1: "fail"}.get(code, "untested")
        self.add("Y1", "全仓语法守卫（K-OPS-C01）", st, tail(out, 4))

    def a1_arch(self):
        # K-OPS-S01（SYSARCH 11-02，总调度批准、CONSENT 代录 docs/uimaster/LOCKS.md）：本轮改动不许新增结构退化
        #（没 timeout 的子进程、直接 ssh、自写 def ssh、写死 run_id / 服务器路径、静默读取、非原子写 JSON、未入版、无主）
        if not (ROOT / "tools/qa/arch_scan.py").exists():
            return self.add("A1", "结构退化棘轮（K-OPS-S01）", "untested", "没有 tools/qa/arch_scan.py")
        py = [c for c in self.changed if c.endswith(".py")]
        if not py:
            return self.add("A1", "结构退化棘轮（K-OPS-S01）", "na", "本轮没有改 .py", False)
        code, out = sh([PY, "tools/qa/arch_scan.py", "--files", *py, "--check"], 300)
        st = {0: "pass", 1: "fail"}.get(code, "untested")
        bad = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("退化")]
        self.add("A1", "结构退化棘轮（K-OPS-S01）", st, (" ⏎ ".join(bad[:6]) if bad else tail(out, 2)))

    def v2_version(self):
        # K-OPS-V01（CODE-RSI r3，项目方 11-01 22:5x“每一次迭代都是用 override system,然后用 create a new version”）：
        # 本轮改动是否已进某个系统版本（git tag sv-*）；没进只提示，由总调度巡检时 tools/qa/system_version.py cut
        if not self.changed:
            return self.add("V2", "已进系统版本（K-OPS-V01）", "na", "没有 --changed", False)
        code, out = sh(["git", "status", "--porcelain=v1", "--", *self.changed], 120)
        left = [ln[3:] for ln in out.splitlines() if len(ln) > 3]
        if code != 0:
            return self.add("V2", "已进系统版本（K-OPS-V01）", "warn", tail(out, 2), False)
        self.add("V2", "已进系统版本（K-OPS-V01）", "warn" if left else "pass",
                 (f"{len(left)} 个改动还没进系统版本（等总调度 cut）：" + "、".join(left[:8])) if left else "本轮改动都已在版本里", False)

    def t1_tests(self):
        if not self.a.tests:
            return self.add("T1", "pytest", "na", "未指定", False)
        # 写保护（K-OPS-Q03）：tests/conftest.py 装 tools/qa/real_data_guard.py，跑完写 data/qa/test_guard_last.json
        rep_f = ROOT / "data/qa/test_guard_last.json"
        t0 = time.time()
        code, out = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *self.a.tests.split(",")], 1800)
        try:
            rep = json.loads(rep_f.read_text(encoding="utf-8")) if rep_f.stat().st_mtime >= t0 - 1 else None
        except (OSError, ValueError):
            rep = None
        if rep is None:
            return self.add("T1", "pytest（真实数据写保护）", "fail",
                            "没有本次的 data/qa/test_guard_last.json：tests/conftest.py 的写保护没生效 ⏎ " + tail(out, 2))
        g = (f"写真实数据 {len(rep['violations'])}；遗留线程 {len(rep['leftover_threads'])}；哨兵被改 {len(rep['sentinels_changed'])}"
             + "".join(f" ⏎ {v['op']} {v['path']} ← {v['test']}" for v in rep["violations"][:5]))
        self.add("T1", "pytest（真实数据写保护）", "pass" if code == 0 and rep["ok"] else "fail", tail(out, 2) + " ⏎ " + g)

    # ---------- 汇总 ----------
    def run(self) -> int:
        own = load_own()
        self.s0_task(own)
        self.k1_knowledge()
        self.k2_chain()
        self.o1_ownership(own)
        self.o2_collision(own)
        self.u1_frontend()
        self.r1_regress()
        self.d1_parity()
        self.c1_contract()
        self.c2_master()
        self.v1_verify()
        self.l1_report()
        self.rl_rules()
        self.h1_hunt()
        self.g0_propagation()
        self.y1_syntax()
        self.a1_arch()
        self.v2_version()
        self.t1_tests()
        fail = [r for r in self.rows if r["status"] == "fail"]
        unt = [r for r in self.rows if r["status"] == "untested" and r["required"]]
        verdict, code = ("FAIL", 1) if fail else (("INCOMPLETE", 2) if unt else ("PASS", 0))
        mark = {"pass": "通过", "fail": "**不通过**", "untested": "**未测**", "na": "不适用", "warn": "提示"}
        md = [f"# iter_gate {self.loop} {self.a.round}：**{verdict}**", "",
              f"时间 {time.strftime('%Y-%m-%d %H:%M:%S')}；改动 {len(self.changed)} 个文件；协议 docs/ITERATION_PROTOCOL.md", "",
              "| 项 | 内容 | 结果 | 必需 | 说明 |", "|---|---|---|---|---|"]
        for r in self.rows:
            md.append(f"| {r['id']} | {r['name']} | {mark[r['status']]} | {'是' if r['required'] else '否'} | "
                      f"{r['detail'].replace('|', '／').replace(' ⏎ ', '<br>')} |")
        md += ["", {"PASS": "可以宣布本轮完成。", "FAIL": "不得宣布完成：先修不通过项（或回滚本轮改动）。",
                    "INCOMPLETE": "不得宣布完成：未测 ≠ 通过，补测后重跑。"}[verdict]]
        text = "\n".join(md)
        if not self.a.dry:
            OUT.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^\w.-]", "_", self.a.round)
            stem = f"{self.loop}_{safe}"
            (OUT / f"{stem}.md").write_text(text + "\n", encoding="utf-8")
            (OUT / f"{stem}.json").write_text(json.dumps({"loop": self.loop, "round": self.a.round, "verdict": verdict,
                                                          "changed": self.changed, "rows": self.rows,
                                                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                                         ensure_ascii=False, indent=1), encoding="utf-8")
            text += f"\n\n结果已写 data/qa/iter_gate/{stem}.md / .json"
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
        return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="迭代收轮闸门（docs/ITERATION_PROTOCOL.md）")
    ap.add_argument("--loop")
    ap.add_argument("--round")
    ap.add_argument("--list-unchecked", action="store_true", help="只生成 docs/master/unchecked_rules.md（无检查规则按 owner）")
    ap.add_argument("--task", help="项目方任务 OTn，逗号分隔（tools/qa/ownership.yaml owner_tasks）")
    ap.add_argument("--changed", action="append", help="本轮改动的文件（逗号分隔，可多次）")
    ap.add_argument("--window", type=int, default=60, help="撞车提示看最近多少分钟")
    ap.add_argument("--ui", action="store_true", help="强制当作前端改动")
    ap.add_argument("--skip-build", action="store_true", help="不跑 gate.sh（U1 记未测）")
    ap.add_argument("--parity-args", default="", help="传给 data_parity.py 的参数")
    ap.add_argument("--contract", action="append", help="契约逐项结果 JSON（ContractResult），逗号分隔")
    ap.add_argument("--for-owner", action="store_true", help="本轮产物要给项目方看")
    ap.add_argument("--review-dir", help="审片 / 挑选页目录（要有 master_review.md）")
    ap.add_argument("--verifier", help="独立复核方（不能是本 loop）")
    ap.add_argument("--verify-evidence", help="复核方产出的证据文件")
    ap.add_argument("--report", help="本轮报告 / 账本文件")
    ap.add_argument("--rules", help="本轮新增 / 修改的规则 id，逗号分隔")
    ap.add_argument("--no-lesson", help="本轮没有新教训时写理由")
    ap.add_argument("--tests", help="pytest 路径，逗号分隔")
    ap.add_argument("--dry", action="store_true", help="不写 data/qa/iter_gate")
    a = ap.parse_args(argv)
    if a.list_unchecked:
        sys.stdout.reconfigure(encoding="utf-8")
        print(unchecked_report(ROOT / "docs/master/unchecked_rules.md"))
        return 0
    if not a.loop or not a.round:
        ap.error("需要 --loop 和 --round")
    return Gate(a).run()


if __name__ == "__main__":
    sys.exit(main())
