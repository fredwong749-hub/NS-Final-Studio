"""总调度巡检（HARNESS-O 11-03）：一个命令出一页结论（≤ 40 行），总调度每 30 分钟跑这一个。只读，不改任何状态。

    .venv/Scripts/python.exe tools/master/master_check.py            # 一页文字
    .venv/Scripts/python.exe tools/master/master_check.py --json     # 给脚本 / 看板用

内容（全部复用现有部件，不另算）：
  ① 每集 SOP 阶段 + 复盘状态     ← tools/master/sop_gate.status、data/pipeline/sop_gate/violations.jsonl（近 30 分钟）
  ② 未关卡点和负责人              ← tools/master/report_issue.load
  ③ 未复审交付                    ← tools/master/deliver.py（未上线时如实写“未上线”）
  ④ 开关是否和决策一致            ← 开关文件实际值 vs 本文件 SWITCH_EXPECT（每条带决策号；switch.py 上线后改读它的登记表）
  ⑤ 待处理请求                    ← tools/master/pending_requests.list_requests（data/master/inbox/requests）
  ⑥ resident / asset_worker / :8800 / producer 心跳 ← data/factory/autoflow_resident.json、data/pipeline/asset_jobs/worker.json、GET /api/progress、
     各剧 producer 目录 heartbeat.json（带 run 身份：为哪部剧在跑；归档剧还在跑 → ⚠）
  ⑦ GPU 道占用                    ← data/sentinel/gpu_samples.jsonl（SENTINEL nvidia-smi 采样）+ data/state/netfix/partition.json（挂道 / 借道 / 退役）
  ⑧ 看门狗最近一轮                ← data/master/watchdog_last.json（tools/master/watchdog.py，W19；resident 每 30 分钟跑一轮）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = os.environ.get("NS_API", "http://127.0.0.1:8800")
MAX_LINES = 40
ACTIVE = ("preparing", "active", "producing")

# 开关 → 决策要求（switch.py 上线前的种子表；每条必须有决策号）。op: eq / le / info（只显示）
SWITCH_EXPECT = [
    ("agent_dispatcher.enabled", "config/pipeline/agent_dispatcher.json", ["enabled"], "eq", True, "L-138 做完测过就开"),
    ("agent_dispatcher.max_concurrent", "config/pipeline/agent_dispatcher.json", ["max_concurrent"], "le", 2, "L-138 限 2 并发"),
    ("asset_worker.max_parallel", "config/pipeline/asset_worker.json", ["max_parallel"], "le", 6, "11-05 项目方“全部显卡给他”取代 L-140 的 asset_worker 部分：≤ 6（除坏卡 gpu33:2 外全部道）"),
    ("asset_worker.render", "config/pipeline/asset_worker.json", ["render"], "info", None, "总调度 01:1x 开"),
    ("asset_worker.voice", "config/pipeline/asset_worker.json", ["voice"], "info", None, "总调度：未批"),
    ("asset_worker.golden", "config/pipeline/asset_worker.json", ["golden"], "info", None, "阶段 B 待开"),
    ("asset_worker.apply_meta", "config/pipeline/asset_worker.json", ["apply_meta"], "info", None, "总调度 01:1x 开"),
    ("owner_delegate.enabled", "config/pipeline/owner_delegate.json", ["enabled"], "info", None, "L-136 代选（项目方下次操作即到期）"),
    ("hollywood_score.enabled", "config/pipeline/hollywood_score.json", ["enabled"], "info", None, "总调度 02:4x（1c46 ①）"),
    ("api_guard_auto.enabled", "data/ops/api_guard_auto.json", ["enabled"], "info", None, "总调度 22:0x 止血：缺文件 = 关"),
    ("sop_gate.enabled", "config/pipeline/sop_gate.json", ["enabled"], "eq", True,
     "C-16 资料齐全才出；false = require 直接放行且不记违规（A-G1 第 22 轮 P1：关总开关必须在巡检里红）"),
    ("sop_gate.observe_stages", "config/pipeline/sop_gate.json", ["observe_stages"], "info", None, "HARNESS-O：第1集过导入闸门后清空"),
]


def _load(name: str, rel: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 巡检只读，缺文件如实显示
        return default


def _age(at, now: float) -> str:
    if at is None:
        return "无"
    try:
        t = float(at) if isinstance(at, (int, float)) else datetime.fromisoformat(str(at)[:19]).timestamp()
    except ValueError:
        return str(at)
    s = int(now - t)
    return f"{s}s 前" if s < 120 else f"{s // 60}min 前"


def active_runs(root: Path) -> list[str]:
    reg = _j(root / "config/pipeline/runs.json", {}) or {}
    return sorted(r for r, v in (reg.get("runs") or {}).items() if (v or {}).get("status") in ACTIVE)


def sec_episodes(root: Path, now: float) -> list[str]:
    SG = _load("sop_gate_mc", "tools/master/sop_gate.py")
    out = []
    for run in active_runs(root):
        for r in SG.status(run, root):
            out.append(f"  {run} ep{r['episode']:02d}：{r['stage']}｜复盘 {r['retro']}｜{r['why'][:110]}")
    vp = root / "data/pipeline/sop_gate/violations.jsonl"
    rec = []
    if vp.is_file():
        for ln in vp.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                v = json.loads(ln)
            except ValueError:   # arch-ok: 坏行跳过
                continue
            if now - datetime.fromisoformat(v["at"]).timestamp() <= 1800:
                rec.append(v)
    if rec:
        enf = sum(1 for v in rec if v.get("mode") == "enforce")
        last = rec[-1]
        out.append(f"  闸门违规（近 30min）{len(rec)} 次（挡下 {enf}）；最近：{last['by']} → ep{last['episode']:02d} {last['stage']}")
    return out or ["  没有在做的剧"]


def sec_issues(root: Path) -> list[str]:
    RI = _load("report_issue_mc", "tools/master/report_issue.py")
    rows = [i for i in RI.load(root / "data/pipeline/issues.jsonl") if i.get("status") == "open"]
    blk = [i for i in rows if i.get("blocking")]
    head = f"  未关 {len(rows)} 条（阻断 {len(blk)}）"
    by: dict[str, int] = {}
    for i in rows:
        by[i.get("who") or "?"] = by.get(i.get("who") or "?", 0) + 1
    out = [head + "；负责人：" + "、".join(f"{k}×{v}" for k, v in sorted(by.items(), key=lambda x: -x[1])[:6])]
    for i in sorted(blk, key=lambda x: x.get("time") or "", reverse=True)[:4]:
        out.append(f"  🔴 {i['id']} {i.get('who')} 第{i.get('episode')}集 步骤{i.get('step')}：{str(i.get('what'))[:70]}")
    return out


def sec_deliveries(root: Path) -> list[str]:
    p = root / "tools/master/deliver.py"
    if not p.is_file():
        return ["  deliver.py 未上线（总调度 03:5x 收窄范围：先做 sop_gate / master_check / episode_retro），未复审数：无从统计"]
    D = _load("deliver_mc", "tools/master/deliver.py")
    pend = D.pending_review(root) if hasattr(D, "pending_review") else []
    return [f"  等复审 {len(pend)} 条" + ("：" + "、".join(str(x.get('id')) for x in pend[:6]) if pend else "")]


def switch_rows(root: Path) -> list[dict]:
    rows = []
    for name, f, path, op, want, why in SWITCH_EXPECT:
        d = _j(root / f, None)
        v = d
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        ok = True
        if op == "eq":
            ok = v == want
        elif op == "le":
            ok = isinstance(v, (int, float)) and v <= want
        rows.append({"name": name, "value": v, "ok": ok, "op": op, "want": want, "why": why, "missing": d is None})
    return rows


def sec_switches(root: Path) -> list[str]:
    rows = switch_rows(root)
    bad = [r for r in rows if not r["ok"]]
    vals = "；".join(f"{r['name'].split('.', 1)[0] if r['name'].endswith('.enabled') else r['name']}={r['value']}" for r in rows)
    out = [f"  {'❌ ' + str(len(bad)) + ' 条和决策对不上' if bad else '✅ 有决策约束的开关都对得上'}（{sum(1 for r in rows if r['op'] != 'info')} 条有约束）"]
    for r in bad:
        out.append(f"  ❌ {r['name']}={r['value']}，要求 {r['op']} {r['want']}（{r['why']}）")
    out.append("  " + vals[:300])
    return out


def sec_requests(root: Path) -> list[str]:
    PR = _load("pending_requests_mc", "tools/master/pending_requests.py")
    rows = PR.list_requests(root / "data/master/inbox", root=root)
    out = [f"  待处理 {len(rows)} 条"]
    for r in rows[:4]:
        out.append(f"  {r.get('run')} ep{int(r.get('episode') or 0):02d} {r.get('kind')} {r.get('step')} 第{r.get('attempt')}次")
    return out


def _api_ok() -> str:
    try:
        with urllib.request.urlopen(API + "/api/progress", timeout=3) as r:
            return f"HTTP {r.status}"
    except Exception as e:  # noqa: BLE001  巡检：探不到如实写
        return f"不通（{type(e).__name__}）"


PRODUCER_STALE_S = 600          # producer 每 20 s 一拍；10 分钟没心跳 = 不在跑
STOPPED_RUNS = ("archived", "frozen")


def sec_producers(root: Path, now: float) -> list[str]:
    """ISS-1103-033310-5833：为哪部剧在跑。要跑的剧 = primary + runs.json 里 producing 的剧，各看自己的 producer 目录心跳
    （legacy 剧 = data/producer，其它 = data/producer/runs/<run>，同 runs.producer_dir）；心跳里的 run 和目录不符、
    或已归档 / 冻结的剧心跳还在更新（旧进程按启动时缓存的 RUN_ID 在跑）→ ⚠"""
    reg = _j(root / "config/pipeline/runs.json", {}) or {}
    runs = reg.get("runs") or {}
    legacy = reg.get("legacy_unprefixed_run")
    primary = (_j(root / "config/pipeline/run.json", {}) or {}).get("run_id") or reg.get("primary")
    want = [r for r in [primary] + sorted(r for r, v in runs.items() if (v or {}).get("status") == "producing") if r]
    want = list(dict.fromkeys(want))

    def hb_of(r):
        pd = root / "data/producer" if r == legacy else root / "data/producer/runs" / r
        return _j(pd / "heartbeat.json", {}) or {}

    def fresh(hb):
        try:
            return bool(hb) and not hb.get("exited") and now - float(hb.get("t") or 0) <= PRODUCER_STALE_S
        except (TypeError, ValueError):
            return False

    out = []
    for r in want:
        hb, st = hb_of(r), (runs.get(r) or {}).get("status")
        if not hb:
            out.append(f"  ⚠ producer[{r}]（{st}）没有心跳：没有进程在为这部剧出图")
            continue
        if hb.get("exited"):
            state = f"已退出（{str(hb.get('exit_reason'))[:50]}）"
        elif not fresh(hb):
            state = "心跳停了"
        else:
            state = "在跑" + ("·暂停" if hb.get("paused") else "") + f" 在途{hb.get('inflight')}"
        bad = "" if hb.get("run") == r else (f" ⚠ 心跳 run={hb.get('run')} 和本剧不符" if hb.get("run") else " ⚠ 心跳没有 run 身份（旧代码）")
        flag = "" if fresh(hb) and not bad else "⚠ "
        out.append(f"  {flag}producer[{r}]（{st}）pid {hb.get('pid')} {state}，心跳 {_age(hb.get('t'), now)}{bad}")
    for r, v in sorted(runs.items()):
        if r in want or (v or {}).get("status") not in STOPPED_RUNS:
            continue
        hb = hb_of(r)
        if fresh(hb):
            old = "心跳没有 run 身份 = 旧代码，" if not hb.get("run") else ""
            out.append(f"  ⚠ producer[{r}] 剧已 {(v or {}).get('status')}，pid {hb.get('pid')} 仍在跑（{old}按启动时的 run 缓存）"
                       f"→ 受控重启一次 producer，新代码会自己交接到 {primary}")
    return out


def sec_heartbeats(root: Path, now: float, api=None) -> list[str]:
    rh = _j(root / "data/factory/autoflow_resident.json", {}) or {}
    wh = _j(root / "data/pipeline/asset_jobs/worker.json", {}) or {}
    cfg = wh.get("config") or {}
    return [f"  resident pid {rh.get('pid')} 第{rh.get('tick')}拍 {_age(rh.get('t') or rh.get('at'), now)}"
            f"{'（错误：' + str(rh.get('error'))[:60] + '）' if rh.get('error') else ''}；"
            f"asset_worker {_age(wh.get('at'), now)}（render={cfg.get('render')} golden={cfg.get('golden')}）；"
            f":8800 {(api or _api_ok)()}"] + sec_resident_assets(rh) + sec_producers(root, now)


def sec_resident_assets(rh: dict) -> list[str]:
    """W12 RESIDENT-RELOAD：resident 心跳里的资产线状态。连续出错 ≥3 拍 resident 写 state=reload_failed / asset_failed + 卡点 id；
    以前 ⑥ 只显示“心跳 N 分钟前”，资产 tick 每拍 AttributeError 也看不出来"""
    st, n = rh.get("state"), rh.get("asset_error_streak") or 0
    if st in ("reload_failed", "asset_failed"):
        why = "新旧代码对不上 / 依赖重载失败" if st == "reload_failed" else "资产 tick 出错"
        return [f"  ⚠ resident 资产线停了（state={st}：{why}，连续 {n} 拍，卡点 {rh.get('asset_issue') or '?'}）："
                f"{str(rh.get('asset_error') or '')[:100]} → 修代码后下一拍自动恢复；不恢复 → 受控重启 ops/restart_autoflow.ps1"]
    if rh.get("asset_error"):
        return [f"  resident 资产 tick 本拍出错（连续 {n} 拍，未到登记线）：{str(rh['asset_error'])[:100]}"]
    return []


def sec_gpu(root: Path, now: float) -> list[str]:
    last: dict[str, dict] = {}
    p = root / "data/sentinel/gpu_samples.jsonl"
    if p.is_file():
        with open(p, "rb") as f:
            f.seek(max(0, p.stat().st_size - 8000))
            for ln in f.read().decode("utf-8", "replace").splitlines()[1:]:
                try:
                    r = json.loads(ln)
                    last[r["host"]] = r
                except (ValueError, KeyError):   # arch-ok: 尾部截断的半行跳过
                    continue
    part = _j(root / "data/state/netfix/partition.json", {}) or {}
    held = set(part.get("retired_lanes") or []) | set(part.get("_lent_lanes") or {}) | set(part.get("_temp_holds") or {})
    cells = []
    for h in sorted(last):
        r = last[h]
        busy = [f"{h}:{g}" + ("⛔" if f"{h}:{g}" in held else "") + f" {u}%/{m // 1024}G" for g, u, m in r.get("smi") or []]
        cells.append(" ".join(busy) + f"（{_age(r.get('t'), now)}）")
    out = ["  " + "；".join(cells) if cells else "  没有 GPU 采样"]
    out.append(f"  退役 {sorted(part.get('retired_lanes') or [])} 借出 {sorted(part.get('_lent_lanes') or {})} 挂道 {sorted(part.get('_temp_holds') or {})}")
    hc = {"healed": 0, "reported": 0}                 # ASSIGN D（11-03）：tools/autopilot/lane_heal.py 的日志，近 24 小时
    lp = root / "data/producer/lane_heal.jsonl"
    if lp.is_file():
        for ln in lp.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
            try:
                r = json.loads(ln)
                t = time.mktime(time.strptime(r["at"], "%Y-%m-%d %H:%M:%S"))
            except (ValueError, KeyError):   # arch-ok: 坏行跳过
                continue
            if now - t <= 86400:
                hc["healed" if r.get("event") == "healed" else "reported"] += 1
    out.append(f"  卡死已自愈 {hc['healed']} 次 · 登记未自动处理 {hc['reported']} 次（近 24 小时，lane_heal）")
    return out


WATCHDOG_STALE_S = 3600           # 看门狗每 30 分钟一轮；超过 1 小时没跑 = resident 没挂上 / 跑挂了


def sec_watchdog(root: Path, now: float) -> list[str]:
    """W19：看门狗最近一轮的结论（命中按规则计数、新登记、⏫ 升级、规则自身出错）；1 小时没跑 → ⚠"""
    d = _j(root / "data/master/watchdog_last.json", None)
    if not d:
        return ["  ⚠ 看门狗还没跑过（tools/master/watchdog.py run；resident 每 30 分钟调一次）"]
    t = d.get("t")
    flag = "⚠ " if not isinstance(t, (int, float)) or now - t > WATCHDOG_STALE_S else ""
    by = "、".join(f"规则{k}×{v}" for k, v in sorted((d.get("by_rule") or {}).items())) or "0 命中"
    out = [f"  {flag}{_age(t, now)}：{by}；新登记 {len(d.get('registered') or [])} 条"
           + (f"（{'、'.join((d.get('registered') or [])[:4])}）" if d.get("registered") else "")
           + f"；⏫ {len(d.get('escalate') or [])} 条；不重登 {d.get('held') or 0} 条"]
    for e in (d.get("errors") or [])[:2]:
        out.append(f"  ⚠ 看门狗规则出错：{str(e)[:110]}")
    return out


SECTIONS = [("① 每集 SOP 阶段 / 复盘", "eps"), ("② 未关卡点", "issues"), ("③ 未复审交付", "deliv"), ("④ 开关 vs 决策", "sw"),
            ("⑤ 待处理请求", "req"), ("⑥ 心跳", "hb"), ("⑦ GPU 道", "gpu"),
            ("⑧ 看门狗最近一轮", "wd")]


def build(root: Path = ROOT, now: float | None = None, api=None) -> dict:
    now = now or time.time()
    fns = {"eps": lambda: sec_episodes(root, now), "issues": lambda: sec_issues(root), "deliv": lambda: sec_deliveries(root),
           "sw": lambda: sec_switches(root), "req": lambda: sec_requests(root), "hb": lambda: sec_heartbeats(root, now, api),
           "gpu": lambda: sec_gpu(root, now), "wd": lambda: sec_watchdog(root, now)}
    out = {}
    for title, k in SECTIONS:
        try:
            out[title] = fns[k]()
        except Exception as e:  # noqa: BLE001  一节坏了不拖垮整页，如实写
            out[title] = [f"  ⚠ 这一节读不出：{e!r}"[:160]]
    return out


def render(sections: dict, now: float | None = None) -> str:
    lines = [f"总调度巡检 {time.strftime('%m-%d %H:%M', time.localtime(now or time.time()))}（tools/master/master_check.py）"]
    budget = MAX_LINES - 1 - len(sections)
    per = {t: v for t, v in sections.items()}
    while sum(len(v) for v in per.values()) > budget:      # 超 40 行：从最长的一节尾部砍，留一行“…”
        t = max(per, key=lambda k: len(per[k]))
        per[t] = per[t][:-2] + ["  …"] if len(per[t]) > 2 else per[t][:1]
    for t, v in per.items():
        lines.append(t)
        lines.extend(v)
    return "\n".join(lines[:MAX_LINES])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    now = time.time()
    s = build(ROOT, now)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        print(render(s, now))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
