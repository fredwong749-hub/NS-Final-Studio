"""当前版本审计（K-OPS-Q23，RSI r5；起因：ep01-S5 当前首帧被设回总调度驳回过的 v3，current_changes.jsonl 没有记录）。

扫 data/renders/epNN/SN/takes.json 的 active，逐镜逐阶段查两件事：
  1. 当前版本指向“不能当当前”的版本：总调度驳回（master_reject）/ 标了不要（params.rejected）/ 坏图（bad）
  2. 当前版本和审计日志对不上：data/producer/current_changes.jsonl 里这一镜这一阶段最后一条的 to ≠ 现在的 active
     （= 有代码路径绕过了 pipeline.set_active，或者离线并回整份覆盖了 takes.json）

    .venv/Scripts/python.exe tools/qa/active_audit.py          # 报告 → data/qa/active_audit/report.md / .json
只读 takes.json / 审计日志，不改当前版本（修复走 pipeline.set_active / deactivate，由 owner 决定）。
"""
from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "qa" / "active_audit"
AUDIT = ROOT / "data" / "producer" / "current_changes.jsonl"


def why_ineligible(t: dict) -> str | None:
    if t.get("master_reject"):
        return f"总调度驳回过（{str((t['master_reject'] or {}).get('reason', ''))[:40]}）"
    prm = t.get("params") if isinstance(t.get("params"), dict) else {}
    if prm.get("rejected"):
        return f"标了不要（{str(prm['rejected'].get('reason', ''))[:40]}）"
    if t.get("bad"):
        return f"坏图（{str(t['bad'])[:40]}）"
    return None


def last_audit(audit_file: Path = AUDIT) -> dict:
    out = {}
    try:
        for ln in audit_file.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            out[(r.get("shot"), r.get("stage"))] = r
    except OSError:
        pass
    return out


def scan(renders: Path | None = None, audit_file: Path = AUDIT) -> dict:
    renders = renders or ROOT / "data" / "renders"
    la = last_audit(audit_file)
    bad, unaudited, n = [], [], 0
    for f in sorted(glob.glob(str(renders / "ep[0-9]*" / "S*" / "takes.json"))):
        p = Path(f)
        shot = f"{p.parent.parent.name}-{p.parent.name}"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n += 1
        for stage, cur in (d.get("active") or {}).items():
            t = next((x for x in d.get("takes") or [] if x.get("stage") == stage and x.get("n") == cur), None)
            w = why_ineligible(t) if t else "当前指向不存在的版本"
            if w:
                bad.append({"shot": shot, "stage": stage, "active": cur, "why": w})
            a = la.get((shot, stage))
            if a is not None and a.get("to") != cur:
                unaudited.append({"shot": shot, "stage": stage, "active": cur, "last_audit_to": a.get("to"),
                                  "last_audit_at": a.get("ts"), "takes_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))})
    return {"shots": n, "ineligible_active": bad, "unaudited": unaudited, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    r = scan()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 当前版本审计（K-OPS-Q23）· {r['at']}", "", f"扫了 {r['shots']} 镜（data/renders/epNN/SN/takes.json）。", "",
          f"## 当前版本指向不能当当前的版本：{len(r['ineligible_active'])} 处", "", "| 镜 | 阶段 | 当前 | 原因 |", "|---|---|---|---|"]
    md += [f"| {x['shot']} | {x['stage']} | v{x['active']} | {x['why']} |" for x in r["ineligible_active"]]
    md += ["", f"## 当前版本和审计日志对不上：{len(r['unaudited'])} 处（data/producer/current_changes.jsonl）", "",
           "| 镜 | 阶段 | 当前 | 审计最后记到 | 审计时间 | takes.json 修改时间 |", "|---|---|---|---|---|---|"]
    md += [f"| {x['shot']} | {x['stage']} | {x['active']} | {x['last_audit_to']} | {x['last_audit_at']} | {x['takes_mtime']} |" for x in r["unaudited"]]
    (OUT / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 1 if r["ineligible_active"] else 0


if __name__ == "__main__":
    sys.exit(main())
