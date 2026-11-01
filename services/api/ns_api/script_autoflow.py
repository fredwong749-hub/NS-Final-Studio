"""HOLLYWOOD r8（总调度 fredw-2b 派，11-02）：新建剧本页的“全自动写到可导入”接口。执行者 = tools/script_rsi/autoflow.py（子进程），
本模块只启动 / 读状态，不写剧本、不判内容。运行目录与 /api/story-runs 同一个（data/pipeline/runs/<id>，P0_brief.json 由新建页写入）。

  POST /api/script-autoflow/{run_id}/start    {episode, budget_usd?, import_mode: dry|live}   一键：P1→P4 + 代码判定补丁 + 新尺子 + 导入闸门
  POST /api/script-autoflow/{run_id}/repair   同 start（已通过的段复用，从卡住处续跑）                             一键返修
  POST /api/script-autoflow/{run_id}/import   项目方一次点选导入（L-098 闸门范围）：live + --owner-ok
  GET  /api/script-autoflow/{run_id}          状态 autoflow.json（每段 status / decider / 花费 / 失败项 / 分数轨迹）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
RUNS = REPO / "data" / "pipeline" / "runs"
router = APIRouter(tags=["script-autoflow"])
_procs: dict[str, subprocess.Popen] = {}


class StartBody(BaseModel):
    episode: int = 1
    budget_usd: float | None = None
    import_mode: str = "dry"


def _dir(run_id: str) -> Path:
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "运行编号不合法")
    d = RUNS / run_id
    if not (d / "P0_brief.json").exists():
        raise HTTPException(404, "这个运行还没有提纲（P0_brief.json）")
    return d


def _spawn(run_id: str, body: StartBody, owner_ok: bool = False) -> dict:
    p = _procs.get(run_id)
    if p is not None and p.poll() is None:
        raise HTTPException(409, "这个剧本正在自动写，等它停下再点")
    d = _dir(run_id)
    if body.import_mode not in ("dry", "live"):
        raise HTTPException(400, "import_mode 只能是 dry 或 live")
    cmd = [sys.executable, str(REPO / "tools/script_rsi/autoflow.py"), "run", "--run-dir", str(d), "--episode", str(body.episode),
           "--import", body.import_mode]
    if body.budget_usd is not None:
        cmd += ["--budget", str(body.budget_usd)]
    if owner_ok:
        cmd.append("--owner-ok")
    log = open(d / "autoflow.log", "a", encoding="utf-8")
    _procs[run_id] = subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                                      env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return {"started": True, "run": run_id, "cmd": " ".join(cmd[1:])}


@router.post("/api/script-autoflow/{run_id}/start")
def start(run_id: str, body: StartBody):
    return _spawn(run_id, body)


@router.post("/api/script-autoflow/{run_id}/repair")
def repair(run_id: str, body: StartBody):
    return _spawn(run_id, body)


@router.post("/api/script-autoflow/{run_id}/import")
def owner_import(run_id: str, body: StartBody):
    st = status(run_id)
    if st.get("verdict") != "importable":
        raise HTTPException(409, f"还不能导入：{st.get('verdict')}（{st.get('next_action') or ''}）")
    return _spawn(run_id, StartBody(episode=body.episode, budget_usd=body.budget_usd, import_mode="live"), owner_ok=True)


@router.get("/api/script-autoflow/{run_id}")
def status(run_id: str):
    d = _dir(run_id)
    p = d / "autoflow.json"
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"verdict": "not_started"}
    proc = _procs.get(run_id)
    st["running"] = bool(proc is not None and proc.poll() is None)
    return st
