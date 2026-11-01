"""SENTINEL 工单库（规则 K-OPS-S03）：data/sentinel/issues.jsonl 只追加；同一 key 只开一张；恢复自动 resolved。

记录（每次状态变化追加一行，同 id 以最后一行为准）：
  id, key, slo, slo_title, title, evidence, first_seen, last_seen, owner_loop, decider="code", status=open|resolved,
  resolved_at, duration_s, dispatch={mode, next}
data/sentinel/state.json：当前未关闭工单（key → 记录，含最新证据 / last_seen），给看板与下一拍用。
data/sentinel/open.json：看板快照（未关闭工单 + 负责方 + 持续时长）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from tools.sentinel.judges import SLO_TITLE, iso

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = {"mode": "总调度每拍读工单按 G0 派单（现行）", "next": "编排器 tools/autopilot/flow.py 读 open.json 自动通知负责 loop（与 DISTILL 对齐，待接）"}


class IssueStore:
    def __init__(self, d: Path | None = None):
        self.d = Path(d or ROOT / "data/sentinel")
        self.d.mkdir(parents=True, exist_ok=True)
        self.log = self.d / "issues.jsonl"
        self.state_p = self.d / "state.json"
        self.open_p = self.d / "open.json"
        try:
            self.state = json.loads(self.state_p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # arch-ok: 首次运行 / 状态坏 → 空状态起步，并记 state_err（tick 开 S0 工单）
            self.state = {"state_err": f"{type(e).__name__}" if self.state_p.exists() else None}
        self.state.setdefault("open", {})

    def _append(self, rec: dict) -> None:
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    @staticmethod
    def new_id(key: str, t: float) -> str:
        slo = key.split(":", 1)[0]
        return f"SN-{slo}-{time.strftime('%m%d%H%M', time.localtime(t))}-{hashlib.sha1(key.encode()).hexdigest()[:6]}"

    def apply(self, findings: list[dict], now: float, owners: dict[str, str]) -> dict:
        """findings 来自 judges.j_*；owners：SLO → 负责 loop。返回 {opened:[...], resolved:[...]}"""
        opened, resolved = [], []
        op = self.state["open"]
        seen = {}
        for f in findings:                     # 同一拍同 key 多条：违约优先
            k = f["key"]
            if k not in seen or (f["violated"] and not seen[k]["violated"]):
                seen[k] = f
        for k, f in seen.items():
            if f["violated"]:
                if k in op:
                    op[k].update(last_seen=iso(now), title=f["title"], evidence=f["evidence"])
                    op[k]["duration_s"] = round(now - op[k]["_t0"])
                else:
                    rec = {"id": self.new_id(k, now), "key": k, "slo": f["slo"], "slo_title": SLO_TITLE.get(f["slo"], ""),
                           "title": f["title"], "evidence": f["evidence"], "first_seen": iso(now), "last_seen": iso(now),
                           "owner_loop": f.get("owner_loop") or owners.get(f["slo"], "总调度"), "severity": f.get("severity", "P1"),
                           "decider": "code", "status": "open",
                           "resolved_at": None, "duration_s": 0, "dispatch": DISPATCH}
                    self._append(rec)
                    op[k] = dict(rec, _t0=now)
                    opened.append(rec)
            elif k in op:
                rec = {kk: v for kk, v in op.pop(k).items() if kk != "_t0"}
                rec.update(status="resolved", resolved_at=iso(now), last_seen=iso(now),
                           duration_s=round(now - ts0(rec, now)), recovered_evidence=f["evidence"])
                self._append(rec)
                resolved.append(rec)
        self.state["at"] = iso(now)
        self.save(now)
        return {"opened": opened, "resolved": resolved}

    def save(self, now: float) -> None:
        tmp = self.state_p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_p)
        rows = sorted(({kk: v for kk, v in r.items() if kk != "_t0"} | {"duration_s": round(now - r["_t0"])}
                       for r in self.state["open"].values()), key=lambda r: (r["slo"], r["first_seen"]))
        snap = {"schema": "nsfs.sentinel.open/1", "at": iso(now), "n_open": len(rows), "issues": rows,
                "probes": self.state.get("probes", {})}
        tmp = self.open_p.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.open_p)

    def retire(self, key: str, why: str, now: float) -> dict | None:
        """探针口径变了、这个 key 以后不再测（例：清单删掉某文件）→ 关单并写明原因（status=retired，不算恢复）"""
        if key not in self.state["open"]:
            return None
        rec = {kk: v for kk, v in self.state["open"].pop(key).items() if kk != "_t0"}
        rec.update(status="retired", resolved_at=iso(now), retire_why=why, duration_s=round(now - ts0(rec, now)))
        self._append(rec)
        self.save(now)
        return rec

    def open_issues(self) -> list[dict]:
        return list(self.state["open"].values())


def ts0(rec: dict, now: float) -> float:
    from tools.sentinel.judges import ts
    return ts(rec.get("first_seen")) or now
