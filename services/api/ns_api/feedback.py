"""人类反馈后台（FEEDBACK，总调度 fredw-2b 11-02 12:5x 派）。

项目方原话：“在这个 overview 页面里面，如果有一些错误的按钮，我可以往上点一下，然后输入文字告诉你这里有什么错误。
然后需要有一个统一的人类反馈后台，对反馈的错误进行处理：1. 进行修复；2. 检查整个系统的参数，看看有没有大的系统性架构问题。”

这是 RSI 的人类输入通道：每条反馈都要走完 分类 → 取证 → 路由修复 → 漏检分析（至少一项系统改进）→ 同类批量扫描 → 复核 → 回归集 → 关单。

存储（不删，只追加 / 覆盖本条）：
  data/feedback/items/<id>.json     一条一个文件（当前状态 + 全部历史）
  data/feedback/events.jsonl        所有变更流水
  data/feedback/shots/<id>.png      前端截图（可选）
  data/feedback/evidence/<id>/**    取证文件（抽帧、裁图等，处理方写）

接口（前端格式见 docs/feedback/API.md）：
  POST /api/feedback                     新建一条（登录即本人：提交人取登录会话，不用打字）
  GET  /api/feedback?status=&ep=&shot=&route=&run=&open=1   列表 + 计数（每条带 dot：red / yellow / green）
  GET  /api/feedback/{id}                单条（含历史）
  GET  /api/feedback/{id}/screenshot     截图
  POST /api/feedback/{id}/status         改状态 / 补处理字段（状态流见 FLOW）；项目方可 reopen
  GET  /api/feedback/meta                分类表、负责方路由表、状态流（前端下拉用）
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ns_api import auth as AUTH

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["feedback"])
_lock = threading.Lock()

STATUSES = ["new", "triaged", "fixing", "fixed", "verified", "closed"]
# 允许的流转（reopen 单独处理：fixed / verified / closed → new，只有登录的项目方能做）
FLOW = {
    "new": ["triaged"],
    "triaged": ["fixing", "new"],
    "fixing": ["fixed", "triaged"],
    "fixed": ["verified", "fixing"],      # 复核不过 → 退回 fixing
    "verified": ["closed", "fixing"],
    "closed": [],
}
REOPENABLE = {"triaged", "fixing", "fixed", "verified", "closed"}
# 状态色只用三种圆点：红 = 待处理（新 / 被打回），黄 = 处理中，绿 = 已复核 / 关单
DOT = {"new": "red", "triaged": "yellow", "fixing": "yellow", "fixed": "yellow", "verified": "green", "closed": "green"}
STATUS_ZH = {"new": "新反馈", "triaged": "已分派", "fixing": "修复中", "fixed": "已修待复核", "verified": "复核通过", "closed": "已关单"}

# 分类 → 默认负责方（tools/qa/ownership.yaml 的 loop 名；界面类另有 FILMUI / UIRSI2 派单名）
CATEGORIES = {
    "image.face": ("出图 · 脸", "IMGLAB"), "image.hand": ("出图 · 手", "IMGLAB"), "image.hair": ("出图 · 发", "IMGFIX"),
    "image.outfit": ("出图 · 服装", "IMGFIX"), "image.composition": ("出图 · 构图", "IMGLAB"),
    "image.fusion": ("出图 · 融合", "IMGLAB"), "image.gaze": ("出图 · 看镜头", "VQAGATE"),
    "video.hand": ("视频 · 手", "VIDLAB"), "video.camera": ("视频 · 运镜", "VIDLAB"), "video.expression": ("视频 · 表情", "VIDLAB"),
    "video.lipsync": ("视频 · 口型", "VIDLAB"), "video.drift": ("视频 · 漂移", "VIDLAB"), "video.audio": ("视频 · 声音", "VIDLAB"),
    "script": ("剧本", "HOLLYWOOD"), "ui": ("界面", "UIRSI"), "ops": ("系统 / 运维", "DEBUG_RSI"),
    "test": ("测试单", "FEEDBACK"),   # 链路实测：可直接关单，默认不进列表 / 计数（?tests=1 才显示）
}
TARGET_KINDS = ["first", "last", "video", "field", "ui", "shot", "episode", "other"]


def _dir(*sub: str) -> Path:
    d = REPO / "data" / "feedback" / Path(*sub) if sub else REPO / "data" / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _path(fid: str) -> Path:
    if not re.fullmatch(r"fb-\d{4,}", fid):
        raise HTTPException(404, "反馈编号格式是 fb-0001")
    return _dir("items") / f"{fid}.json"


def _load(fid: str) -> dict:
    p = _path(fid)
    if not p.exists():
        raise HTTPException(404, f"没有这条反馈：{fid}")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(item: dict, event: dict) -> None:
    p = _path(item["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    with (_dir() / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": item["id"], "at": _now(), **event}, ensure_ascii=False) + "\n")


def _next_id() -> str:
    ns = [int(m.group(1)) for f in _dir("items").glob("fb-*.json") if (m := re.fullmatch(r"fb-(\d+)\.json", f.name))]
    return f"fb-{(max(ns) + 1) if ns else 1:04d}"


def _who(request: Request, actor: str | None) -> dict:
    u = AUTH.user_of(request)
    if u and u.get("role") == "owner":
        return {"name": u["name"], "role": "owner"}
    if u:
        return {"name": u["name"], "role": u.get("role") or "viewer"}
    return {"name": (actor or "agent").strip()[:40] or "agent", "role": "agent"}


def _view(item: dict, full: bool = True) -> dict:
    out = {**item, "dot": DOT.get(item["status"], "red"), "status_zh": STATUS_ZH.get(item["status"], item["status"]),
           "next": FLOW.get(item["status"], []), "has_screenshot": bool(item.get("screenshot"))}
    if not full:
        out.pop("history", None)
    return out


class Target(BaseModel):
    kind: str = "other"                  # first / last / video / field / ui / shot / episode / other
    field: str | None = None             # kind=field：字段名（如 action、camera、prompt_h3）
    selector: str | None = None          # kind=ui：元素选择器 / data-testid
    label: str | None = None             # 界面上看到的文字（按钮名、标签）
    file: str | None = None              # 对应素材相对路径（前端知道就带上，如 renders/ep02/S3/video.mp4）


class FeedbackIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    route: str = ""                      # 页面路由（location.pathname + hash）
    run: str | None = None               # 如 series10_v1
    ep: int | str | None = None          # 集号
    shot: str | None = None              # 镜号，如 S3
    target: Target = Target()
    take: str | int | None = None        # 当前 take 版本（take 号 / 文件名）
    timecode: float | None = None        # 视频时间码（秒），点视频时取 video.currentTime
    screenshot: str | None = None        # data:image/png;base64,... 或纯 base64（可选，≤ 6 MB）
    viewport: dict | None = None         # {w, h, dpr}
    context: dict | None = None          # 其它前端上下文（自由字段，原样存）
    actor: str | None = None             # 非登录调用方（agent）自报名字；登录用户忽略此项


class StatusIn(BaseModel):
    status: str | None = None            # 目标状态；不填 = 只补字段 / 加备注
    note: str | None = None
    actor: str | None = None
    category: str | None = None          # CATEGORIES 的 key
    owner: str | None = None             # 负责方（loop 名）
    owner_agent: str | None = None       # 负责方 agent id
    evidence: list[str] | None = None    # 取证文件路径（追加）
    root_cause: str | None = None
    fix_note: str | None = None
    fix_evidence: list[str] | None = None
    miss_analysis: str | None = None     # 漏检分析：哪道闸门漏了、为什么
    improvements: list[dict] | None = None   # 系统改进 [{kind: rule|check|gate|regression|prompt|config, ref, note, status}]
    same_class: dict | None = None       # 同类扫描 {check, scanned, hits, list_file}
    verify: dict | None = None           # 复核 {check, result: pass|fail, evidence}
    regression: str | None = None        # 回归集登记（文件 / 用例 id）
    systemic: bool | None = None         # 是否写进 docs/feedback/SYSTEMIC.md
    resolution: str | None = None        # 关单方式：不填 = 修复复核；"frozen" = 项目方决定不处理（note 写依据）


def _save_screenshot(fid: str, b64: str) -> str | None:
    raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
    try:
        data = base64.b64decode(raw, validate=False)
    except (ValueError, TypeError):
        return None
    if not data or len(data) > 6 * 1024 * 1024:
        return None
    ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png"
    p = _dir("shots") / f"{fid}{ext}"
    p.write_bytes(data)
    return str(p.relative_to(REPO)).replace("\\", "/")


@router.get("/api/feedback/meta")
def meta():
    return {"statuses": [{"key": s, "zh": STATUS_ZH[s], "dot": DOT[s], "next": FLOW[s]} for s in STATUSES],
            "categories": [{"key": k, "zh": v[0], "owner": v[1]} for k, v in CATEGORIES.items()],
            "target_kinds": TARGET_KINDS, "reopen_from": sorted(REOPENABLE)}


@router.post("/api/feedback")
def create(body: FeedbackIn, request: Request):
    who = _who(request, body.actor)
    if body.target.kind not in TARGET_KINDS:
        raise HTTPException(422, f"target.kind 只能是 {TARGET_KINDS}")
    with _lock:
        fid = _next_id()
        ep = body.ep
        if isinstance(ep, str) and re.fullmatch(r"(?:ep)?0*(\d+)", ep, re.I):
            ep = int(re.fullmatch(r"(?:ep)?0*(\d+)", ep, re.I).group(1))
        item = {
            "id": fid, "created_at": _now(), "by": who, "text": body.text.strip(),
            "route": body.route, "run": body.run, "ep": ep, "shot": body.shot, "target": body.target.model_dump(),
            "take": body.take, "timecode": body.timecode, "viewport": body.viewport, "context": body.context or {},
            "screenshot": _save_screenshot(fid, body.screenshot) if body.screenshot else None,
            "status": "new", "category": None, "owner": None, "owner_agent": None,
            "evidence": [], "root_cause": None, "fix_note": None, "fix_evidence": [], "miss_analysis": None,
            "improvements": [], "same_class": None, "verify": None, "regression": None, "systemic": False,
            "reopened": 0, "updated_at": _now(),
            "history": [{"at": _now(), "by": who, "status": "new", "note": "提交"}],
        }
        _save(item, {"by": who, "action": "create", "status": "new"})
    return _view(item)


@router.get("/api/feedback")
def list_items(status: str | None = None, ep: str | None = None, shot: str | None = None, route: str | None = None,
               run: str | None = None, open: int = 0, limit: int = 500, tests: int = 0):
    items, unreadable = [], []
    for f in sorted(_dir("items").glob("fb-*.json"), reverse=True):
        try:
            it = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:   # arch-ok: 坏文件不静默丢，记进 unreadable 随响应返回（总调度 11-02 14:0x）
            unreadable.append({"file": f.name, "error": str(e)[:120]})
            continue
        if it.get("category") == "test" and not tests:
            continue
        items.append(it)
    counts = {s: 0 for s in STATUSES}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    def keep(it):
        if status and it["status"] not in status.split(","):
            return False
        if open and it["status"] == "closed":
            return False
        if ep is not None and str(it.get("ep")).lstrip("0") != str(ep).lower().replace("ep", "").lstrip("0"):
            return False
        if shot and str(it.get("shot") or "").upper() != shot.upper():
            return False
        if route and not str(it.get("route") or "").startswith(route):
            return False
        if run and it.get("run") != run:
            return False
        return True
    sel = [_view(it, full=False) for it in items if keep(it)][:limit]
    dots = {"red": 0, "yellow": 0, "green": 0}
    for it in items:
        dots[DOT[it["status"]]] += 1
    return {"items": sel, "counts": counts, "dots": dots, "total": len(items), "unreadable": unreadable}


@router.get("/api/feedback/{fid}")
def get_item(fid: str):
    return _view(_load(fid))


@router.get("/api/feedback/{fid}/screenshot")
def screenshot(fid: str):
    it = _load(fid)
    if not it.get("screenshot"):
        raise HTTPException(404, "这条没有截图")
    return FileResponse(REPO / it["screenshot"])


@router.post("/api/feedback/{fid}/status")
def set_status(fid: str, body: StatusIn, request: Request):
    who = _who(request, body.actor)
    with _lock:
        it = _load(fid)
        cur, to = it["status"], body.status
        # 先合并处理字段（后面的闸门按合并后的值判）
        for k in ("category", "owner", "owner_agent", "root_cause", "fix_note", "miss_analysis", "same_class",
                  "verify", "regression", "systemic"):
            v = getattr(body, k)
            if v is not None:
                if k == "category" and v not in CATEGORIES:
                    raise HTTPException(422, f"分类只能是 {list(CATEGORIES)}")
                it[k] = v
        for k in ("evidence", "fix_evidence"):
            for v in getattr(body, k) or []:
                if v not in it[k]:
                    it[k].append(v)
        for imp in body.improvements or []:
            it["improvements"].append({"at": _now(), **imp})
        if it.get("category") and not it.get("owner"):
            it["owner"] = CATEGORIES[it["category"]][1]
        action = "update"
        if to and to != cur:
            if to == "new" and cur in REOPENABLE:
                if who["role"] != "owner":
                    raise HTTPException(403, "只有登录的项目方能打回（reopen）")
                it["reopened"] = int(it.get("reopened") or 0) + 1
                it["verify"] = None
                action = "reopen"
            elif to == "closed" and it.get("category") == "test":
                pass   # 测试单（链路实测）：直接关，不走修复闸门，也不进计数（见 list_items）
            elif to == "closed" and body.resolution == "frozen" and cur in ("triaged", "fixing", "fixed", "verified"):
                # 项目方决定不处理（如 L-125 V1 冻结）：不走 fixed / verified，但漏检分析、系统改进、回归登记照样必填，
                # 还要写明依据（note 里写决定编号）——根因修复必须已经进了规则，不能只是“算了”
                if not (body.note or "").strip():
                    raise HTTPException(422, "冻结关单要在 note 写明依据（项目方决定编号）")
                it["resolution"] = "frozen"
            elif to not in FLOW.get(cur, []):
                raise HTTPException(409, f"{STATUS_ZH.get(cur, cur)} 不能直接改成 {STATUS_ZH.get(to, to)}；可改：{FLOW.get(cur)}")
            # 每一步的必填项（G1：每个判断落成字段，不靠口头）
            need = []
            if it.get("category") == "test":
                if to != "closed":
                    raise HTTPException(409, "测试单只能直接关单")
                it["status"] = "closed"
                it["updated_at"] = _now()
                it["history"].append({"at": _now(), "by": who, "status": "closed", "from": cur, "note": body.note or "测试单"})
                _save(it, {"by": who, "action": "close_test", "from": cur, "status": "closed", "note": body.note})
                return _view(it)
            if to == "triaged" and not (it.get("category") and it.get("owner")):
                need.append("category + owner")
            if to == "fixed" and not (it.get("fix_note") and it.get("fix_evidence")):
                need.append("fix_note + fix_evidence")
            if to == "verified" and not ((it.get("verify") or {}).get("check") and (it.get("verify") or {}).get("result") == "pass"):
                need.append("verify{check, result: pass}")
            if to == "closed":
                if not it.get("regression"):
                    need.append("regression（回归集登记）")
                if not it.get("improvements"):
                    need.append("improvements（至少一项系统改进）")
                if not it.get("miss_analysis"):
                    need.append("miss_analysis（漏检分析）")
            if need:
                raise HTTPException(422, "改成 " + STATUS_ZH[to] + " 还缺：" + "、".join(need))
            it["status"] = to
            action = action if action == "reopen" else "status"
        it["updated_at"] = _now()
        it["history"].append({"at": _now(), "by": who, "status": it["status"], "from": cur, "note": body.note or action})
        _save(it, {"by": who, "action": action, "from": cur, "status": it["status"], "note": body.note})
    return _view(it)
