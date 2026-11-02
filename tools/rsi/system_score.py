"""线 5（系统代码）RSI 打分器（SYSARCH 11-02，总调度派；docs/master/RSI_PROGRAM.md 线 5；规则 K-OPS-Y01）。

项目方 03:5x 原话：“怎么让这个系统把规则全部体现下来，并且在不用 Claude 的情况下依然能跑得很棒？这个事情很关键。”

只读这些来源，算 0–100 分，追加一行到 data/rsi/scores.jsonl（line=system）：
  无 Claude   30  data/autopilot/coverage.json  deciders_now.claude（上线配置下 claude 判断点数）       分项 = max(0, 1 − n / CLAUDE_CAP)
  自运行      20  data/sentinel/state.json probes：Σviolated / Σn（探针自己报错的不算样本）→ SLO 达标率；
                  GPU = data/rsi/gpu_24h.json productive_pct / 80（SENTINEL 每小时刷新；缺时退回 S1 探针） 分项 = 两者平均
  发版        15  data/rsi/cut_seen.jsonl（system_version.record_cut 每次 cut 都追加；打分时也补记 last_cut）→ 每个 sv 首次尝试是否通过，
                  data/rsi/release_incidents.jsonl 里记了热修 / 回滚的 sv 一律算不通过；
                  index.json / deploy_*.json → 服务器版本落后几版                                 分项 = 0.5 × 一次通过率 + 0.5 × [落后 ≤ 1]
  结构健康    20  data/sysarch/scan_latest.json 生产代码 10 项总数之和，对比首扫锚点 STRUCT_ANCHOR    分项 = max(0, 1 − 现值 / 锚点)；另报“比上一轮降没降”
  规则覆盖    15  knowledge/generated/index.json：今天（date = 当天）新增的规则里带 check 的比例    分项 = 有 check / 全部
任何来源读不到 → 该分项记 null 并写进 missing（不当 0 也不当满分；总分按其余分项的权重重新归一，并标 partial=true）。

用法：python tools/rsi/system_score.py            # 量一次分，追加 scores.jsonl，打印
      python tools/rsi/system_score.py --dry      # 只打印不写
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2])
OUT = ROOT / "data/rsi"
WEIGHTS = {"no_claude": 30, "self_run": 20, "release": 15, "structure": 20, "rule_coverage": 15}
CLAUDE_CAP = 8   # 首次量分时上线配置 claude 判断点 7 个（coverage.json distill-r3），取 8 作 0 分线：今晚目标 ≤4 ≈ 50%，0 个 = 100%
# 结构健康锚点 = ARCH_ROADMAP §0 首扫基线（11-02 02:43，AST 口径定型后）；只比较这 10 项（后加的检查项不算进去，免得口径变化冒充退化 / 进步）
STRUCT_ANCHOR = {"no_timeout": 80, "direct_ssh": 35, "ssh_unlisted": 1, "def_ssh": 15, "hard_run": 157, "hard_path": 137,
                 "silent_read": 317, "nonatomic_json": 245, "untracked_code": 36, "unowned": 243}
SV_RE = re.compile(r"^sv-(\d{8})-(\d{2})$")


def _jl(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def s_no_claude(root: Path) -> tuple[float, dict]:
    c = _jl(root / "data/autopilot/coverage.json")
    src = "deciders_now_launch" if c.get("deciders_now_launch") else "deciders_now"   # DISTILL 11-02：上线配置口径（测试期写手 claude_testphase 不计）
    n = int((c.get(src) or {}).get("claude", 0))
    return max(0.0, 1 - n / CLAUDE_CAP), {"claude_points": n, "src": src, "claude_share_launch": c.get("claude_share_launch"), "decision_points": c.get("decision_points"), "coverage_at": c.get("at")}


def s_self_run(root: Path) -> tuple[float, dict]:
    pr = (_jl(root / "data/sentinel/state.json").get("probes") or {})
    ok = {k: v for k, v in pr.items() if not v.get("error") and v.get("n")}
    n = sum(int(v["n"]) for v in ok.values())
    vio = sum(int(v.get("violated") or 0) for v in ok.values())
    if not n:
        raise ValueError("SENTINEL 探针没有有效样本")
    slo = 1 - vio / n
    # GPU：SENTINEL data/rsi/gpu_24h.json for_rsi_line5.productive_pct（5 张生产卡 24 h 真正在跑占比，无数据时段留在分母）；
    # 目标 0.8（RSI_PROGRAM 线 5）→ 分 = min(1, pct / 80)。读不到才退回 S1 探针的 1 − violated/n
    gpu, gpu_src, pct = None, None, None
    try:
        pct = float((_jl(root / "data/rsi/gpu_24h.json").get("for_rsi_line5") or {})["productive_pct"])
        gpu, gpu_src = min(1.0, pct / 80.0), "gpu_24h.productive_pct"
    except (OSError, ValueError, KeyError, TypeError):
        s1 = ok.get("S1")
        if s1:
            gpu, gpu_src = 1 - int(s1.get("violated") or 0) / int(s1["n"]), "S1 探针"
    val = slo if gpu is None else (slo + gpu) / 2
    return val, {"slo_rate": round(slo, 3), "gpu_score": None if gpu is None else round(gpu, 3), "gpu_productive_pct": pct,
                 "gpu_src": gpu_src, "probes": len(ok),
                 "probe_errors": sorted(k for k, v in pr.items() if v.get("error"))}


def _sv_key(sv: str):
    m = SV_RE.match(sv or "")
    return (m.group(1), int(m.group(2))) if m else None


def s_release(root: Path, out: Path, write: bool) -> tuple[float, dict]:
    lc = _jl(root / "data/system_versions/last_cut.json")
    seen_p = out / "cut_seen.jsonl"
    seen = [json.loads(x) for x in seen_p.read_text(encoding="utf-8").splitlines() if x.strip()] if seen_p.exists() else []
    rec = {"id": lc.get("id"), "at": lc.get("at_iso") or lc.get("at"), "ok": bool(lc.get("ok"))}
    if rec["id"] and not any(s.get("id") == rec["id"] and s.get("at") == rec["at"] for s in seen):
        seen.append(rec)
        if write:
            out.mkdir(parents=True, exist_ok=True)
            with seen_p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    first: dict[str, bool] = {}
    for s in sorted(seen, key=lambda x: str(x.get("at"))):
        if s.get("id"):
            first.setdefault(s["id"], bool(s.get("ok")))
    # 部署后需要热修 / 回滚的版本不算一次通过（总调度 11-02 09:1x；账本 data/rsi/release_incidents.jsonl，FACTORY 热修 / 回滚时追加）
    inc_p = out / "release_incidents.jsonl"
    incidents = set()
    if inc_p.exists():
        for ln in inc_p.read_text(encoding="utf-8").splitlines():
            try:
                incidents.add(json.loads(ln)["sv"])
            except (ValueError, KeyError, TypeError):
                continue   # arch-ok: 坏行跳过，其余事件照算
    # 账本开始之后 cut 成功的版本（index.json 有）但账本漏记的 → 补一条“首次通过”（账本 09:1x 才改成 cut 时写入，之前靠采样会漏）；
    # 账本开始之前的版本不算（不知道它们失败过几次）
    t0 = min((str(s.get("at")) for s in seen if s.get("at")), default=None)
    if t0:
        for v in (_jl(root / "data/system_versions/index.json").get("versions") or []):
            if _sv_key(v.get("id")) and str(v.get("at", "")) >= t0[:19]:
                first.setdefault(v["id"], True)
    for sv in incidents & first.keys():
        first[sv] = False
    fp = sum(first.values()) / len(first) if first else None
    tags = sorted({v["id"] for v in (_jl(root / "data/system_versions/index.json").get("versions") or []) if _sv_key(v.get("id"))},
                  key=_sv_key)
    deployed = set()
    for f in glob.glob(str(root / "data/system_versions/deploy_*.json")):
        try:
            d = _jl(Path(f))
        except (OSError, ValueError):
            continue   # arch-ok: 写到一半的部署记录本轮不算（不会把版本算成已部署）
        hosts = d.get("hosts") or {}
        if hosts and all((h or {}).get("ok") for h in hosts.values()):
            deployed.add(d.get("id"))
    latest_dep = max((t for t in deployed if _sv_key(t)), key=_sv_key, default=None)
    lag = (len(tags) - 1 - tags.index(latest_dep)) if latest_dep in tags else None
    lag_ok = lag is not None and lag <= 1
    val = (0.5 * fp if fp is not None else 0.0) + (0.5 if lag_ok else 0.0)
    return val, {"first_pass_rate": None if fp is None else round(fp, 3), "svs_seen": len(first),
                 "hotfixed_or_rolled_back": sorted(incidents), "latest_tag": tags[-1] if tags else None,
                 "latest_deployed_all_hosts": latest_dep, "server_lag": lag}


def s_structure(root: Path, out: Path) -> tuple[float, dict]:
    cur = _jl(root / "data/sysarch/scan_latest.json")
    t = cur.get("totals") or {}
    now, first = sum(int(t.get(k, 0)) for k in STRUCT_ANCHOR), sum(STRUCT_ANCHOR.values())
    prev = None
    sp = out / "scores.jsonl"
    if sp.exists():
        for ln in reversed(sp.read_text(encoding="utf-8").splitlines()):
            try:
                r = json.loads(ln)
            except ValueError:
                continue   # arch-ok: 坏行跳过，只找上一条 system 记录
            if r.get("line") == "system":
                prev = ((r.get("detail") or {}).get("structure") or {}).get("total")
                break
    val = max(0.0, 1 - now / first) if first else 0.0
    return val, {"total": now, "first_total": first, "prev_total": prev, "dropped_vs_prev": None if prev is None else now < prev,
                 "scan_at": cur.get("at")}


def s_rule_coverage(root: Path, day: str) -> tuple[float, dict]:
    rules = _jl(root / "knowledge/generated/index.json").get("rules") or []
    today = [r for r in rules if str(r.get("date", ""))[:10] == day]
    if not today:
        raise ValueError(f"{day} 没有新增规则")
    withc = [r for r in today if r.get("check")]
    miss = sorted(r["id"] for r in today if not r.get("check"))
    return len(withc) / len(today), {"rules_today": len(today), "with_check": len(withc), "missing_check": miss[:20]}


def score(root: Path = ROOT, out: Path = OUT, write: bool = True, day: str | None = None) -> dict:
    day = day or time.strftime("%Y-%m-%d")
    parts, detail, missing = {}, {}, {}
    calls = {"no_claude": lambda: s_no_claude(root), "self_run": lambda: s_self_run(root),
             "release": lambda: s_release(root, out, write), "structure": lambda: s_structure(root, out),
             "rule_coverage": lambda: s_rule_coverage(root, day)}
    for k, fn in calls.items():
        try:
            v, d = fn()
            parts[k], detail[k] = round(v * 100, 1), d
        except Exception as e:   # noqa: BLE001 —— 来源缺失显式记 missing，不当 0 也不当满分
            parts[k] = None
            missing[k] = f"{type(e).__name__}: {str(e)[:160]}"
    wsum = sum(WEIGHTS[k] for k, v in parts.items() if v is not None)
    total = round(sum(WEIGHTS[k] * v for k, v in parts.items() if v is not None) / wsum, 1) if wsum else None
    sv = None
    try:
        raw = (root / "data/system_version.txt").read_text(encoding="utf-8").strip()
        sv = (json.loads(raw).get("id") if raw.startswith("{") else raw[:40]) or None   # 文件是 JSON（deploy 写），取 id
    except (OSError, ValueError, AttributeError):
        sv = None   # arch-ok: 笔记本可能没有这个文件，版本号只是标注
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "line": "system", "score": total, "parts": parts, "weights": WEIGHTS,
           "partial": bool(missing), "missing": missing, "detail": detail, "sv": sv}
    if write:
        out.mkdir(parents=True, exist_ok=True)
        with (out / "scores.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass   # arch-ok: 老终端不支持 reconfigure，只影响打印
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    r = score(write=not a.dry)
    print(f"线 5 系统代码 {r['score']}" + ("（部分来源缺失）" if r["partial"] else ""))
    for k, v in r["parts"].items():
        print(f"  {k:14s} {v}  (权重 {WEIGHTS[k]})  {json.dumps(r['detail'].get(k) or r['missing'].get(k), ensure_ascii=False)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
