"""每镜一个“重做”按钮（L-215 / PLAN_5H 块 J，W-KICKOFF 11-07）：项目方点一下 = 这一镜这一格重出，不确认、不来回。

POST /api/owner/redo {run?, shot: "ep02-S5", kind: first|last|video}
  · 只认登录的项目方本人（role=owner）；没登录 / 查看令牌 / agent → 403，什么都不写。
  · 首帧 / 尾帧：走现成的驳回重出通道 producer.py reject（master_rejects，n=0 = 插队重出、不先撤下当前版；替换版过契约 + 看图闸门后换上），
    by = "项目方（重做按钮）"。
  · 视频：在同一份 master_rejects.json 记 video:<镜号>（by 同上，owner_redo=true）；服务器 vidgen.check_lip_redo 读到后
    作废现有片子、回到待出（与口型重出同一条路，项目方本人的要求不受重出次数上限）。
  · master_rejects 已在 resident_sync control_files 里（按对象合并推两台）；这里另起后台线程立刻推一次。
  · 成人镜：只回文字（不回图 / 提示词）；是否能出由触发清单决定（L-216 开项目常设授权自动入清单）。
L-123：这不是“接受 / 驳回”——是项目方自己明确要求重出一格。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-redo"])
BY = "项目方（重做按钮）"
SID = re.compile(r"^ep(\d{2})-S(\d+)$")
KIND_WORD = {"first": "首帧", "last": "尾帧", "video": "视频"}
_lock = threading.Lock()


def _jst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M:%S")


def _at():
    from ns_api import adult_trigger as AT  # noqa: PLC0415
    return AT


def _producer_reject(run: str, oid: str, reason: str, root: Path = REPO) -> dict:
    r = subprocess.run([sys.executable, str(root / "tools/autopilot/producer.py"), "reject", "--obj", oid, "--n", "0", "--reason", reason,
                        "--plan", "frame_v9,frame_v9", "--by", BY, "--run", run], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, cwd=str(root), env={**os.environ, "PYTHONUTF8": "1"})
    return {"ok": r.returncode == 0, "err": (r.stderr or "")[-300:] if r.returncode else ""}


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def video_redo(run: str, sid: str, reason: str, root: Path = REPO) -> dict:
    """master_rejects.json[video:<sid>]：每次点都换新 at（vidgen 按 at 认“新请求”，一条只用一次）"""
    p = _at().producer_dir(run, root) / "master_rejects.json"
    with _lock:
        try:
            cur = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except ValueError as e:      # 坏文件不覆盖（覆盖会丢别的驳回）
            return {"ok": False, "err": f"master_rejects.json 读不出：{e}"[:200]}
        cur = cur if isinstance(cur, dict) else {}
        cur[f"video:{sid}"] = {"kind": "video", "reject_n": 0, "reason": reason, "by": BY, "at": _jst(), "label": "项目方重做",
                               "owner_redo": True, "plan": [], "cleared": True,
                               "_note": "视频重做由 vidgen.check_lip_redo 按 at 消费（一条只用一次）；producer 驳回账不管 video:*，所以记 cleared"}
        _atomic_json(p, cur)
    return {"ok": True, "err": ""}


def redo(run: str, sid: str, kind: str, root: Path = REPO, reject_fn=None, video_fn=None) -> dict:
    if not SID.match(sid or ""):
        raise ValueError(f"镜号不对：{sid}")
    if kind not in KIND_WORD:
        raise ValueError(f"只能重做首帧 / 尾帧 / 视频：{kind}")
    reason = f"项目方点了“重做{KIND_WORD[kind]}”"
    oid = f"{kind}:{sid}"
    res = (video_fn or video_redo)(run, sid, reason, root) if kind == "video" else (reject_fn or _producer_reject)(run, oid, reason, root)
    try:
        AT = _at()
        adult = sid in AT.adult_shots(run, root)
        waiting = adult and oid not in AT.triggered(run, root)
    except Exception:  # noqa: BLE001  # arch-ok: 认不出是不是成人镜 = 按成人镜、未进清单处理（只回文字）
        adult, waiting = True, True
    if not res.get("ok"):
        say = f"{sid} {KIND_WORD[kind]}没交出去：{res.get('err') or '原因不明'}"[:200]
    elif waiting:          # 复审 nit：成人镜还没进触发清单 → 不说“出好后自动换上”
        say = f"{sid} {KIND_WORD[kind]}的重做已记下；这一镜还在等进触发清单，进了清单就会重出"
    else:
        say = f"{sid} {KIND_WORD[kind]}已交给系统重做，出好后自动换上"
    return {"ok": bool(res.get("ok")), "obj": oid, "run": run, "adult": adult, "waiting_trigger": waiting, "err": res.get("err") or "", "say": say}


class RedoBody(BaseModel):
    run: str | None = None
    shot: str
    kind: str


@router.post("/api/owner/redo")
def post_redo(body: RedoBody, request: Request):
    from ns_api import auth  # noqa: PLC0415
    u = auth.user_of(request)
    if not u or u.get("role") != "owner":
        raise HTTPException(403, "只有登录的项目方本人能点重做")
    AT = _at()
    run = AT._run_of(body.run)
    try:
        out = redo(run, body.shot.strip(), body.kind.strip())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not out["ok"]:
        raise HTTPException(502, out["say"])
    AT.push_now()            # master_rejects 在 control_files 里：立刻推两台（常驻每拍也会推）
    return {**out, "queued": True}
