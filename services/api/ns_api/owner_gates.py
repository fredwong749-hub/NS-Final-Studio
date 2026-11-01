"""fredw-92/UXF1：「待你决定」在画布里直接拍板（UX 审查 #8）。

以前画布只显示命令行（tools/s1_gate.py、python -m ns_agent.looks confirm、tools/sop_owner.py），项目方要自己跑。
这里给同一套记录逻辑加一个接口，**只给项目方本人在画布确认框里点**：

    POST /api/sop/owner-decision
      {gate: "look" | "G3" | "G4" | "G5" | "plate", by: "owner", quote: "项目方原话",
       character?, episodes?（look，如 "2" 或 "1-3"）, episode?（G4 / G5）, rework?（G5 返工）, scene_id?（plate）}

- by 必须是 "owner"、quote 必须非空（与 H3 覆盖 / 审计豁免同一个 _require_owner 口径）；agent 不得调用。
- 记录与命令行逐字同一份逻辑：look → LookStore.confirm_episodes；G3 → tools/s1_gate.py main(--accept)；
  G4 / G5 / plate → tools/sop_owner.py 的 g4 / g5 / plate。命令行的校验（G4 要 qa.json 全 pass、G5 要有成片、
  底板要 scenes.json 非临时）原样生效，不满足 → 409 + 原因。
- 另记一行 data/sop/owner_ui_log.jsonl（谁、哪个关口、原话、时间、来源 = 画布），方便事后核对。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import time
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from ns_render import pipeline as P

GATES = ("look", "G3", "G4", "G5", "plate")
UI_LOG = Path("data") / "sop" / "owner_ui_log.jsonl"


class OwnerDecision(BaseModel):
    gate: str
    by: str = ""
    quote: str = ""
    character: str | None = None
    episodes: str | None = None
    episode: int | None = None
    rework: bool = False
    scene_id: str | None = None


def _tool(name: str):
    """tools/<name>.py（命令行同一份代码）按文件加载"""
    f = P.ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ns_tools_{name}", f)
    if spec is None or spec.loader is None:
        raise HTTPException(500, f"找不到 tools/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cli_error(e: SystemExit) -> HTTPException:
    msg = e.code if isinstance(e.code, str) else f"命令返回 {e.code}"
    return HTTPException(409, msg)


def decide(body: OwnerDecision, *, root: Path, gpu3_root: Path, look_store=None) -> dict:
    """执行一条项目方决定（调用方已核过 by=owner + 原话）。→ {gate, record}"""
    q = body.quote.strip()
    g = body.gate
    if g == "look":
        if not body.character or not (body.episodes or "").strip():
            raise HTTPException(400, "确认造型要给 character 和 episodes")
        from ns_agent.looks import default_store
        store = look_store or default_store()
        try:
            eps = store.confirm_episodes(body.episodes.strip(), body.character, q)
        except KeyError as e:
            raise HTTPException(404, f"没有这个角色：{body.character}") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"gate": g, "record": {"character": body.character, "episodes": eps}}
    if g == "G3":
        mod = _tool("s1_gate")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = mod.main(["--accept", q, "--root", str(root)])
            except SystemExit as e:
                raise _cli_error(e) from e
        if code:
            raise HTTPException(409, err.getvalue().strip() or f"s1_gate 返回 {code}")
        try:
            rec = json.loads(out.getvalue())
        except ValueError:
            rec = {"output": out.getvalue()[-2000:]}
        return {"gate": g, "record": rec}
    mod = _tool("sop_owner")
    try:
        if g == "G4":
            rec = mod.g4(root, gpu3_root, int(body.episode or 1), q, False)
        elif g == "G5":
            if body.episode is None:
                raise HTTPException(400, "验收成片要给 episode")
            rec = mod.g5(root, gpu3_root, int(body.episode), q, bool(body.rework))
        elif g == "plate":
            if not body.scene_id:
                raise HTTPException(400, "确认底板要给 scene_id")
            rec = mod.plate(root, body.scene_id, q, False, True)
        else:
            raise HTTPException(400, f"gate 只能是 {'、'.join(GATES)}")
    except SystemExit as e:
        raise _cli_error(e) from e
    return {"gate": g, "record": rec}


def log(root: Path, body: OwnerDecision, result: dict) -> None:
    try:
        f = Path(root) / UI_LOG
        f.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "via": "canvas", "by": "owner", "gate": body.gate,
               "quote": body.quote.strip(), "character": body.character, "episodes": body.episodes,
               "episode": body.episode, "rework": body.rework, "scene_id": body.scene_id}
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
