"""SENTINEL 常驻（规则 K-OPS-S02…S07；docs/master/SLO.md）：每 60 s 一拍，到期的探针跑一遍 → data/sentinel/issues.jsonl 工单。

  .venv/Scripts/python.exe tools/sentinel/sentinel.py serve          # 常驻（单实例，pid 锁 data/sentinel/sentinel.pid）
  .venv/Scripts/python.exe tools/sentinel/sentinel.py once [--only S2,S7] [--all]   # 跑一拍（--all 忽略周期，全部探针都跑）
  .venv/Scripts/python.exe tools/sentinel/sentinel.py status         # 打印未关闭工单
工单 decider=code；派单现行 = 总调度每拍读 data/sentinel/open.json 按 G0 派；下一步由编排器（tools/autopilot/flow.py）自动通知负责 loop（DISTILL 对齐）。
只读：不改生产代码 / 配置、不重启、不删文件。远程每台每拍 1 次合并只读调用（rssh 常驻主连接，timeout + nice + 限线程）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):   # K-OPS-V13：本机探针也限线程
    os.environ.setdefault(_k, "2")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.autopilot import policy  # noqa: E402
from tools.sentinel import judges as J  # noqa: E402
from tools.sentinel import probes as P  # noqa: E402
from tools.sentinel.store import IssueStore  # noqa: E402

D = ROOT / "data/sentinel"
PID = D / "sentinel.pid"
LOG = D / "sentinel.log"


def cfg() -> dict:
    return policy.load()["sentinel"]


def owners(c: dict) -> dict:
    return {"S0": "SENTINEL", **{s: c[k]["value"].get("owner_loop", "总调度") for s, k in P.CFG_OF.items() if k in c}}


def log(*a) -> None:
    D.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%F %T ") + " ".join(str(x) for x in a) + "\n")


def tick(only: set | None = None, force: bool = False, store: IssueStore | None = None) -> dict:
    c = cfg()
    store = store or IssueStore(D)
    mem = store.state.setdefault("mem", {})
    last = store.state.setdefault("probes", {})
    ctx = P.Ctx(c, mem)
    P.UNKNOWN.clear()
    findings, ran = [], {}
    for slo, fn in P.PROBES.items():
        if only and slo not in only:
            continue
        every = float(c[P.CFG_OF[slo]]["value"].get("every_s", 60))
        if not force and ctx.now - float((last.get(slo) or {}).get("t") or 0) < every - 5:
            continue
        t0 = time.time()
        try:
            fs = fn(ctx)
            err = None
        except Exception as e:  # noqa: BLE001
            fs, err = [], f"{type(e).__name__}: {e}"[:300]
            log("PROBE_ERR", slo, err, traceback.format_exc()[-600:].replace("\n", " | "))
        findings += fs
        # K-OPS-S06：探针自己坏了（抛异常）= 开“探针故障”工单，不当正常
        findings.append(J.F(slo, "probe_fault", err is not None, f"探针 {slo} 故障：{err}", error=err))
        last[slo] = {"t": ctx.now, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "secs": round(time.time() - t0, 1), "n": len(fs),
                     "violated": sum(f["violated"] for f in fs), "error": err}
        ran[slo] = last[slo]
    if store.state.get("state_err"):
        P.UNKNOWN["data/sentinel/state.json"] = store.state["state_err"]
    if ran:   # 本拍读不到的输入 / 远程采样失败 → S0 探针故障工单（恢复后自动关）
        findings.append(J.F("S0", "inputs", bool(P.UNKNOWN), f"探针输入读不到：{', '.join(sorted(P.UNKNOWN))[:160]}", inputs=dict(P.UNKNOWN)))
        for h in P.HOSTS:
            if any(s in ran for s in ("S2", "S3", "S5", "S6", "S7", "S13")):
                findings.append(J.F("S0", f"remote:{h}", h in ctx.errors, f"{h} 远程采样失败（{ctx.errors.get(h)}）——依赖它的探针本拍未测",
                                    error=ctx.errors.get(h)))
    store.state["remote_errors"] = ctx.errors
    store.state["probes"]["_unknown"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "inputs": dict(P.UNKNOWN), "remote": dict(ctx.errors)}
    res = store.apply(findings, ctx.now, owners(c))
    for r in res["opened"]:
        log("OPEN", r["id"], r["owner_loop"], r["title"])
    for r in res["resolved"]:
        log("RESOLVED", r["id"], r["duration_s"], "s", r["title"])
    return {"ran": ran, "opened": len(res["opened"]), "resolved": len(res["resolved"]), "open": len(store.open_issues()),
            "errors": ctx.errors}


def _alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
            return True
        except OSError:  # arch-ok: 进程探活，OSError 即不在（不是读文件）
            return False


def serve() -> int:
    D.mkdir(parents=True, exist_ok=True)
    old = int(PID.read_text().strip() or 0) if PID.exists() else 0
    if old and old != os.getpid() and _alive(old):
        print(f"已有实例 pid {old}")
        return 1
    PID.write_text(str(os.getpid()))
    log("START pid", os.getpid())
    while True:
        t0 = time.time()
        try:
            r = tick()
            log("TICK", json.dumps({k: v for k, v in r.items() if k != "ran"}, ensure_ascii=False), "ran", ",".join(r["ran"]))
        except Exception as e:  # noqa: BLE001
            log("TICK_ERR", repr(e)[:300])
        time.sleep(max(5.0, float(cfg()["tick_s"]["value"]) - (time.time() - t0)))


def status() -> int:
    snap = json.loads((D / "open.json").read_text(encoding="utf-8")) if (D / "open.json").exists() else {"issues": []}
    print(f"未关闭工单 {len(snap['issues'])}（{snap.get('at')}）")
    for r in snap["issues"]:
        print(f"  {r['id']}  {r['slo']}  {r.get('severity', '')}  {r['owner_loop']}  {r['duration_s'] // 60} 分钟  {r['title'][:110]}")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "once", "status", "retire"])
    ap.add_argument("--key")
    ap.add_argument("--why", default="")
    ap.add_argument("--only")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        return serve()
    if a.cmd == "status":
        return status()
    if a.cmd == "retire":
        r = IssueStore(D).retire(a.key, a.why, time.time())
        print(json.dumps(r, ensure_ascii=False) if r else "没有这张未关闭工单")
        return 0
    r = tick(set(a.only.split(",")) if a.only else None, force=a.all)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return status()


if __name__ == "__main__":
    sys.exit(main())
