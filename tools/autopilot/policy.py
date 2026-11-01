"""策略层（DISTILL 11-02，L-102 / ITERATION_PROTOCOL §G1，规则 K-OPS-X01）：config/policies/*.yaml 是阈值和判断的单一来源。

  load(root)                    → {policy: {item: {...}}}
  get("resources.pause_max_s")  → value
  drift_check(root)             → 代码里另有常量的项（status=drift_checked）逐项比对；不一致 = 失败（policy_check 退出码 1）
  ref_check(root)               → enforced_by / 决策清单里写的文件必须存在
  判定函数（编排器 / guard 用，纯函数、可测）：
    pause_overdue(ctrl, now)    暂停超过 resources.pause_max_s 且不是项目方本人暂停
    handback_ok(rec)            服务器交还条件（handback.yaml）
    score_backlog_max(lanes, vlm_instances)
    noise_stop(judge_sums_list) 评审噪声先修尺子（budget.judge_noise_*）
    pick_import(cands)          预算 / 轮数用完时选最高分且不变量全过的版本（budget.import_best_when_capped）
    post_better(base, post)     后期版成片分 ≥ 原版才用（gates.post_layer_enabled）

CLI：python tools/autopilot/policy.py check     （drift + ref；run.py policy-check 同）
"""
from __future__ import annotations

import ast
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POL_DIR = "config/policies"
DECISIONS = "config/policies/decisions.yaml"
_PATH_RE = re.compile(r"(?:tools|config|services|docs|ops|packages|apps|tests|knowledge)/[\w./\-]+\.(?:py|json|yaml|yml|md|ps1|sh|mjs|tsx|ts)")
_cache: dict = {}


def load(root: Path = ROOT) -> dict:
    key = str(root)
    d = root / POL_DIR
    sig = tuple(sorted((p.name, p.stat().st_mtime_ns) for p in d.glob("*.yaml"))) if d.exists() else ()
    if key in _cache and _cache[key][0] == sig:
        return _cache[key][1]
    out = {}
    for p in sorted(d.glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if doc.get("schema") != "nsfs.policy/1":
            continue
        out[doc["policy"]] = doc.get("items") or {}
    _cache[key] = (sig, out)
    return out


def item(path: str, root: Path = ROOT) -> dict:
    pol, name = path.split(".", 1)
    return load(root)[pol][name]


def get(path: str, default=None, root: Path = ROOT):
    try:
        return item(path, root)["value"]
    except KeyError:
        return default


# ---------------------------------------------------------------------------------------------- 漂移检查
_OPS = {ast.Mult: lambda a, b: a * b, ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b}


def _lit(node):
    """literal_eval + 简单算术（45 * 60 这类常量写法）"""
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_lit(node.left), _lit(node.right))
    return ast.literal_eval(node)


def _py_const(file: Path, name: str):
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return _lit(node.value)
                if isinstance(tgt, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    for t, v in zip(tgt.elts, node.value.elts):
                        if isinstance(t, ast.Name) and t.id == name:
                            return _lit(v)
    raise KeyError(f"{file.name} 里没有常量 {name}")


def _norm(v, view: str | None):
    if view == "keys":
        return sorted(v.keys())
    if view == "sorted":
        return sorted(v)
    if isinstance(v, (list, tuple)):
        return list(v)
    return v


def drift_one(name: str, it: dict, root: Path = ROOT) -> dict:
    dr = it.get("drift") or {}
    kind = dr.get("kind")
    want = it.get("value")
    if dr.get("field"):
        want = want[dr["field"]]
    f = root / dr.get("file", "")
    res = {"item": name, "kind": kind, "file": dr.get("file"), "want": want}
    try:
        if kind == "py_const":
            got = _norm(_py_const(f, dr["name"]), dr.get("view"))
            want = _norm(want, dr.get("view") if dr.get("view") == "sorted" else None)
            if dr.get("view") == "keys":
                want = sorted(want)
        elif kind == "json":
            got = json.loads(f.read_text(encoding="utf-8"))
            for k in dr["path"]:
                got = got[k]
            got = _norm(got, dr.get("view"))
            if dr.get("view") == "sorted":
                want = sorted(want)
        elif kind == "json_blocking":
            d = json.loads(f.read_text(encoding="utf-8"))
            got = sorted(k for k, v in (d.get("checks") or {}).items() if v.get("blocking"))
            want = sorted(want)
        elif kind == "grep":
            got = bool(re.search(dr["pattern"], f.read_text(encoding="utf-8")))
            want = True
        else:
            return res | {"ok": False, "error": f"未知 drift.kind {kind}"}
    except Exception as e:  # noqa: BLE001
        return res | {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return res | {"got": got, "want": want, "ok": got == want}


def drift_check(root: Path = ROOT) -> list[dict]:
    out = []
    for pol, items in load(root).items():
        for name, it in items.items():
            if it.get("status") == "drift_checked":
                out.append(drift_one(f"{pol}.{name}", it, root))
    return out


def ref_check(root: Path = ROOT) -> list[dict]:
    """enforced_by / 决策清单 where 里写到的仓库路径必须存在（防止清单指向不存在的代码）"""
    bad = []
    texts = []
    for pol, items in load(root).items():
        for name, it in items.items():
            texts.append((f"{pol}.{name}", str(it.get("enforced_by") or "")))
            for need in ("value", "source", "status", "owner"):
                if need not in it:
                    bad.append({"where": f"{pol}.{name}", "missing_field": need})
            if it.get("status") == "pending" and not it.get("plan"):
                bad.append({"where": f"{pol}.{name}", "missing_field": "plan（pending 必须写方案）"})
    dp = root / DECISIONS
    if dp.exists():
        for d in (yaml.safe_load(dp.read_text(encoding="utf-8")) or {}).get("decisions") or []:
            texts.append((d.get("id"), str(d.get("where") or "")))
            if d.get("coded") in ("no", "partial") and not d.get("plan"):
                bad.append({"where": d.get("id"), "missing_field": "plan"})
    for where, t in texts:
        for m in _PATH_RE.findall(t):
            if not (root / m).exists():
                bad.append({"where": where, "missing_path": m})
    return bad


# ---------------------------------------------------------------------------------------------- 判定函数
def _ts(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return None


def pause_decision(ctrl: dict, now: float | None = None, root: Path = ROOT) -> dict | None:
    """暂停判定（唯一实现，总调度 D5 口径；producer 每拍与 run.py guard 共用）→ None（没暂停 / 未到点）或
    {action: resume|alert, kind, by, since, paused_s, limit_s, why}
      运维暂停（reason_kind ∈ ops_kinds）：到 expires_at（最多 paused_at + 180 s）→ resume
      显式暂停（reason_kind ∈ explicit_kinds，或 paused_by 是项目方）：超过 180 s → alert（不自动恢复）
      缺 reason_kind / expires_at：超过 180 s → alert（记违规）"""
    if not ctrl or not ctrl.get("paused"):
        return None
    it = item("resources.pause_max_s", root)
    lim = float(it["value"])
    now = now or time.time()
    by = str(ctrl.get("paused_by") or "")
    kind = ctrl.get("reason_kind")
    t0 = _ts(ctrl.get("paused_at"))
    dt = (now - t0) if t0 is not None else None
    base = {"kind": kind, "by": by, "since": ctrl.get("paused_at"), "paused_s": round(dt) if dt is not None else None, "limit_s": lim}
    if kind in set(it.get("explicit_kinds") or []) or by in set(it.get("exempt_paused_by") or []):
        return dict(base, action="alert", why="显式暂停超过 180 s（不自动恢复）") if dt is None or dt > lim else None
    missing = [f for f in it.get("require_fields") or [] if not ctrl.get(f)]
    if kind in set(it.get("ops_kinds") or []) and not missing:
        exp = _ts(ctrl.get("expires_at"))
        cands = [x for x in (exp, (t0 + lim) if t0 is not None else None) if x is not None]
        if cands and now >= min(cands):
            return dict(base, action="resume", why=f"运维暂停到点（expires_at / 最多 {int(lim)} s）")
        return None
    if dt is None or dt > lim:
        return dict(base, action="alert", why=f"暂停缺 {missing or ['合法 reason_kind']}，超过 {int(lim)} s（违规，只告警）")
    return None


def pause_overdue(ctrl: dict, now: float | None = None, root: Path = ROOT) -> dict | None:
    """兼容旧名：= pause_decision"""
    return pause_decision(ctrl, now, root)


def handback_ok(rec: dict | None, server_sv: str | None = None, root: Path = ROOT) -> tuple[bool, list[str]]:
    """assets_ready.<host> 记录 → (可交还, 不满足的条件)"""
    rec = rec or {}
    P = load(root)["handback"]
    why = []
    if rec.get("preflight_dryrun_ok") is not P["preflight_dryrun_ok"]["value"]:
        why.append("服务器 preflight dryrun 未 0 挡（K-OPS-F02）")
    if int(rec.get("preflight_dryrun_shots") or 0) < int(P["preflight_min_shots"]["value"]):
        why.append("preflight dryrun 镜数为 0")
    if P["refs_match"]["value"] and (rec.get("refs_match") is not True or int(rec.get("refs_mismatch") or 0) > 0):
        why.append("refs sha 与笔记本不一致")
    writers = P["ready_writer"]["value"]
    if rec.get("ready") and not any(w in str(rec.get("preflight_dryrun_by") or "") for w in writers):
        why.append(f"ready=true 不是 {writers} 写的")
    want = P["min_code_sv"]["value"]
    if server_sv is not None and want and str(server_sv) < str(want):
        why.append(f"服务器代码 {server_sv} 低于 min_code_sv {want}")
    return (not why, why)


def score_backlog_max(lanes: int, vlm_instances: int = 1) -> int:
    return 2 * max(1, int(lanes)) * max(1, int(vlm_instances))


def noise_stop(judge_sums: list[list[float]], root: Path = ROOT) -> dict:
    """judge_sums：一轮里每份稿的各评审总分 → {stop, unstable, total, ratio}"""
    spread = float(get("budget.judge_noise_max_spread", 3, root))
    ratio_max = float(get("budget.judge_noise_stop_ratio", 0.5, root))
    rows = [s for s in judge_sums if s]
    uns = sum(1 for s in rows if max(s) - min(s) > spread)
    r = uns / len(rows) if rows else 0.0
    return {"stop": bool(rows) and r >= ratio_max, "unstable": uns, "total": len(rows), "ratio": round(r, 3)}


def pick_import(cands: list[dict], spent_usd: float = 0.0, rounds_left: int = 0, root: Path = ROOT) -> dict:
    """cands：[{name, score, invariants_pass, p4_block_zero, fact_check_zero}] → {pick, why, decider}"""
    smin = float(get("budget.import_score_min", 48, root))
    cap = float(get("budget.writing_total_cap_usd", 15, root))
    rule = get("budget.import_best_when_capped", {}, root) or {}
    ok = [c for c in cands if all(c.get(k) for k in rule.get("requires", []))]
    if not ok:
        return {"pick": None, "why": "没有不变量全过的候选 → 写作方返修", "decider": "code"}
    best = max(ok, key=lambda c: float(c.get("score") or 0))
    if float(best.get("score") or 0) >= smin:
        return {"pick": best["name"], "why": f"达到导入线 {smin}", "decider": "code"}
    capped = spent_usd >= cap or rounds_left <= 0
    if capped and rule.get("enabled"):
        return {"pick": best["name"], "why": f"预算 / 轮数已用完，导入最高分 {best.get('score')}（未达 {smin}）", "decider": "code"}
    return {"pick": None, "why": f"最高 {best.get('score')} 未达 {smin}，预算未用完 → 继续迭代", "decider": "code"}


def delivery_check(fs: dict | None, best: float | None, lip_redo_pending: int, root: Path = ROOT) -> dict:
    """预览交付闸门（gates.delivery_gate 棘轮）：fs = 成片分 JSON → {ok, min_line, why}"""
    g = get("gates.delivery_gate", {}, root) or {}
    floor = float(g.get("film_score_floor", 30))
    line = max(floor, (float(best) - float(g.get("ratchet_minus", 1))) if best is not None else floor)
    why = []
    tot = (fs or {}).get("total_50")
    if tot is None:
        why.append("没有成片分（未测 ≠ 通过）")
    elif float(tot) < line:
        why.append(f"成片分 {tot} < 最低线 {line:g}（max({floor:g}, 历史最好 {best} − 1)）")
    hard = g.get("hard") or []
    if "lip_redo_zero" in hard and lip_redo_pending:
        why.append(f"口型重出单 {lip_redo_pending} 条未处理")
    if "a1_no_zero_shot" in hard:
        a1 = ((fs or {}).get("items") or {}).get("A1") or {}
        if a1.get("measured") and a1.get("score") == 0:
            why.append("视线 A1 为 0 分")
        if any(c.get("id") == "A1.3" and c.get("pass") is False for c in a1.get("conds") or []):
            why.append("A1.3：有镜头疑似看镜头")
    return {"ok": not why, "min_line": line, "why": why}


def update_best(path: Path, ep: int, fs: dict | None) -> float | None:
    """棘轮：本集出了更好的成片分就抬高历史最好分（代码自动），返回更新后的最好分"""
    d = {}
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    k = f"ep{ep:02d}"
    cur = (d.get(k) or {}).get("best")
    tot = (fs or {}).get("total_50")
    if tot is not None and (cur is None or float(tot) > float(cur)):
        d[k] = {"best": float(tot), "name": fs.get("name"), "at": fs.get("at"), "coverage": fs.get("coverage")}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return float(tot)
    return cur


def run_writing_cap(run_id: str, root: Path = ROOT) -> float:
    """某部剧的整部写作上限：budget.writing_per_run.overrides[run_id] 优先，否则 run_cap_usd"""
    v = get("budget.writing_per_run", {}, root) or {}
    return float((v.get("overrides") or {}).get(run_id, v.get("run_cap_usd", 15.0)))


def post_better(base: dict | None, post: dict | None) -> bool | None:
    """成片分 JSON（total_50）→ 后期版是否 ≥ 原版；任一缺 = None（未测）"""
    if not base or not post or base.get("total_50") is None or post.get("total_50") is None:
        return None
    return float(post["total_50"]) >= float(base["total_50"])


# ---------------------------------------------------------------------------------------------- CLI
def check(root: Path = ROOT, out=print) -> int:
    dr = drift_check(root)
    rf = ref_check(root)
    n_items = sum(len(v) for v in load(root).values())
    bad = [d for d in dr if not d["ok"]]
    out(f"策略 {len(load(root))} 份 / {n_items} 项；drift_checked {len(dr)} 项，不一致 {len(bad)}；引用缺失 {len(rf)}")
    for d in bad:
        out(f"  ❌ 漂移 {d['item']}：策略 {d.get('want')!r} ≠ 代码 {d.get('got', d.get('error'))!r}（{d.get('file')}）")
    for b in rf:
        out(f"  ❌ 引用 {b}")
    return 1 if bad or rf else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        sys.exit(check())
    print(__doc__)
