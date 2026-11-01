"""自动迭代 Loop 的持久化：与 API 进程解耦（chain_audit E6：API 重启丢作业 / schema 失败丢结果）。

目录 data/iterate_loop/<run_id>/：
  state.json        当前状态（原子写：先写 .tmp 再 replace）
  events.jsonl      追加写的事件日志（每个动作一行，带时间）
  plans/<hash>.json 每次编译出的 RenderPlan（内容寻址，不覆盖）
  results/<镜>/a<N>.json  每次出片的结果副本（作业返回、take、文件、审片指标、规则判定）——先写原件，再改 state 索引
  PAUSE             存在即暂停（loop.py pause / resume）
  director/verdicts.json  剪辑导演 agent 的主观审片结论（接口：loop 每个 tick 读）
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "iterate_loop"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Store:
    def __init__(self, run_id: str, base: Path | None = None):
        self.run_id = run_id
        self.dir = (base or BASE) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- state ----
    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def load(self) -> dict | None:
        return read_json(self.state_path)

    def save(self, state: dict) -> None:
        state["updated_at"] = now()
        write_json(self.state_path, state)

    # ---- 事件 ----
    def event(self, kind: str, **kw) -> dict:
        ev = {"t": now(), "kind": kind, **kw}
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def events(self) -> list[dict]:
        p = self.dir / "events.jsonl"
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    # ---- 产物 ----
    def save_plan(self, plan: dict) -> Path:
        p = self.dir / "plans" / f"{plan['plan_hash'][:16]}.json"
        if not p.exists():
            write_json(p, plan)
        return p

    def save_result(self, shot: str, attempt: int, version: int, result: dict) -> Path:
        p = self.dir / "results" / shot / f"v{version}_a{attempt}.json"
        write_json(p, result)
        return p

    # ---- 暂停 ----
    @property
    def pause_flag(self) -> Path:
        return self.dir / "PAUSE"

    def paused(self) -> bool:
        return self.pause_flag.exists()

    def pause(self, why: str = "") -> None:
        self.pause_flag.write_text(why or now(), encoding="utf-8")
        self.event("paused", why=why)

    def resume(self) -> None:
        if self.pause_flag.exists():
            self.pause_flag.unlink()
        self.event("resumed")

    # ---- 主观审片接口 ----
    @property
    def verdicts_path(self) -> Path:
        return self.dir / "director" / "verdicts.json"

    def verdicts(self) -> dict:
        return read_json(self.verdicts_path, {}) or {}
