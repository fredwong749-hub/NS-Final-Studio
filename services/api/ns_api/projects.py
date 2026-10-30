"""
项目 / 「新建剧」向导 / 「开始生产」编排 / 待办 / 进度看板 的 API（T42）。挂在 ns_api.app 上：

  GET  /api/projects                                 项目列表（默认项目 weita = 《为他而骚》）
  POST /api/projects {name, slug?}                   新建草稿项目（生成 projects/<slug>/ 目录骨架）
  GET  /api/projects/{slug}                          项目设置 + 建项目检查清单
  POST /api/projects/{slug}/script?kind=…            上传剧本三件套之一 → 实时导入校验报告
  GET  /api/projects/{slug}/script/report            最近一次校验报告
  GET/PUT /api/projects/{slug}/style                 风格 SOP 表单 → config/visual_bible.toml（返回 toml + 两镜示例提示词）
  POST /api/projects/{slug}/style/color-reference    上传色调参考图
  POST /api/projects/{slug}/style/confirm            G1 风格定稿
  GET  /api/projects/{slug}/characters               人物卡
  PUT  /api/projects/{slug}/characters/{cid}         写实强度 / 妆发甲衣 / 造型 A-B-C / 排期
  POST /api/projects/{slug}/characters/{cid}/references        上传参考图（会撤销已有确认）
  DELETE /api/projects/{slug}/characters/{cid}/references?path=
  POST /api/projects/{slug}/characters/{cid}/confirm {confirmed, by}   「此角色为 AI 生成的虚构成年人」
  PUT  /api/projects/{slug}/settings {lora_plan?, adult_content?}
  POST /api/projects/{slug}/create                   完成向导（检查清单全绿才行）
  GET  /api/projects/{slug}/file/{path}              项目内文件（参考图预览）

  POST /api/projects/{slug}/production/start {mode: real|dry_run}
  POST /api/projects/{slug}/production/pause | /tick
  GET  /api/projects/{slug}/production               进度看板
  POST /api/projects/{slug}/cards/{card_id} {decision, payload, by}
  POST /api/projects/{slug}/production/retry {episode, step}
  GET  /api/inbox                                    全部项目的待办卡片
  GET  /api/gpus                                     笔记本 ComfyUI 队列 + gpu3 GPU（桥）
"""
from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ns_api import project_ctx as PC
from ns_api import wizard as W

router = APIRouter(prefix="/api", tags=["projects"])
TICK_S = float(os.environ.get("NS_ORCH_TICK_S", "20"))
COMFY_URL = os.environ.get("NS_COMFY_URL", "http://127.0.0.1:8188")


def _ctx(slug: str, editable: bool = False) -> PC.ProjectContext:
    try:
        ctx = PC.get_project(slug)
    except KeyError:
        raise HTTPException(404, f"没有项目 {slug}")
    if editable and ctx.is_default:
        raise HTTPException(409, "《为他而骚》是现有项目，不能在向导里改")
    return ctx


def _bad(e: Exception):
    raise HTTPException(422, str(e))


def _summary(ctx: PC.ProjectContext) -> dict:
    s = ctx.settings()
    st = PC.read_json(ctx.orchestrator_dir / "state.json", {})
    return {"slug": ctx.slug, "name": ctx.name, "is_default": ctx.is_default,
            "status": "legacy" if ctx.is_default else s.get("status", "draft"),
            "root": str(ctx.root), "created_at": s.get("created_at"),
            "running": bool(st.get("running")), "mode": st.get("mode"),
            "episodes": len(PC.read_json(ctx.script_json, {}).get("episodes", []))}


# ================================================================== 项目 / 向导

class NewProject(BaseModel):
    name: str
    slug: str | None = None


@router.get("/projects")
def list_projects():
    return [_summary(c) for c in PC.list_projects()]


@router.post("/projects")
def new_project(body: NewProject):
    try:
        ctx = PC.create_project(body.name, body.slug)
    except ValueError as e:
        _bad(e)
    return _summary(ctx)


@router.get("/projects/{slug}")
def get_project(slug: str):
    ctx = _ctx(slug)
    out = _summary(ctx)
    if not ctx.is_default:
        s = ctx.settings()
        out.update(settings={k: v for k, v in s.items() if k not in ("style", "characters")},
                   readiness=W.readiness(ctx), lora_kinds=W.LORA_KINDS)
    return out


@router.post("/projects/{slug}/script")
async def upload_script(slug: str, kind: str = Query(...), file: UploadFile = File(...)):
    ctx = _ctx(slug, editable=True)
    try:
        W.save_script_file(ctx, kind, file.filename or "script.md", await file.read())
    except ValueError as e:
        _bad(e)
    return W.validate_script(ctx)


@router.get("/projects/{slug}/script/report")
def script_report(slug: str):
    ctx = _ctx(slug)
    return PC.read_json(ctx.import_dir / "validation.json", {"ok": False, "fatal": ["还没有上传剧本"], "warnings": []})


@router.get("/projects/{slug}/style")
def get_style(slug: str):
    ctx = _ctx(slug, editable=True)
    return {"form": W.style_form(ctx).model_dump(), "defaults": W.template_defaults().model_dump(),
            "confirmed": ctx.settings().get("gates", {}).get("G1"), "saved": "style" in ctx.settings(),
            "toml": ctx.visual_bible.read_text(encoding="utf-8") if ctx.visual_bible.exists() else None,
            "preview": W.style_preview(ctx)}


@router.put("/projects/{slug}/style")
def put_style(slug: str, form: W.StyleForm):
    ctx = _ctx(slug, editable=True)
    try:
        return W.save_style(ctx, form)
    except ValueError as e:
        _bad(e)


@router.post("/projects/{slug}/style/color-reference")
async def upload_color_ref(slug: str, file: UploadFile = File(...)):
    ctx = _ctx(slug, editable=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in W.IMG_EXT:
        raise HTTPException(422, "色调参考图只接受 png / jpg / webp")
    p = ctx.assets_dir / "style" / f"color_reference_01{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    for old in p.parent.glob("color_reference_01.*"):
        old.unlink()
    p.write_bytes(await file.read())
    form = W.style_form(ctx)
    form.color_reference = ctx.rel(p)
    out = W.save_style(ctx, form)
    return {"color_reference": form.color_reference, **out}


class ByBody(BaseModel):
    by: str = ""          # 封板修复 P0：不给默认值；本人闸门由 _owner() 校验


OWNER_BY = ("owner", "项目方")


def _owner(by: str) -> str:
    """封板修复 P0：项目方本人闸门（风格确认 / 角色确认 / 开工 / 卡片决定）必须显式写 by=owner（或“项目方”），agent 不得代点"""
    if (by or "").strip() not in OWNER_BY:
        raise HTTPException(403, "只有项目方本人能做这个决定（by=owner）；agent 不得代点")
    return by.strip()


@router.post("/projects/{slug}/style/confirm")
def confirm_style(slug: str, body: ByBody):
    ctx = _ctx(slug, editable=True)
    try:
        return W.confirm_style(ctx, _owner(body.by))
    except ValueError as e:
        _bad(e)


@router.get("/projects/{slug}/characters")
def characters(slug: str):
    ctx = _ctx(slug, editable=True)
    return {"characters": W.characters_list(ctx), "realism_levels": W.REALISM_LEVELS,
            "face_reference": PC.read_json(ctx.face_reference, None)}


@router.put("/projects/{slug}/characters/{cid}")
def put_character(slug: str, cid: str, form: W.CharacterForm):
    ctx = _ctx(slug, editable=True)
    try:
        return W.update_character(ctx, cid, form)
    except KeyError:
        raise HTTPException(404, "没有这个角色")
    except ValueError as e:
        _bad(e)


@router.post("/projects/{slug}/characters/{cid}/references")
async def add_reference(slug: str, cid: str, file: UploadFile = File(...)):
    ctx = _ctx(slug, editable=True)
    try:
        return W.add_reference(ctx, cid, file.filename or "ref.png", await file.read())
    except KeyError:
        raise HTTPException(404, "没有这个角色")
    except ValueError as e:
        _bad(e)


@router.delete("/projects/{slug}/characters/{cid}/references")
def remove_reference(slug: str, cid: str, path: str):
    ctx = _ctx(slug, editable=True)
    try:
        return W.remove_reference(ctx, cid, path)
    except KeyError:
        raise HTTPException(404, "没有这个角色")


class ConfirmBody(BaseModel):
    confirmed: bool
    by: str = ""


@router.post("/projects/{slug}/characters/{cid}/confirm")
def confirm_character(slug: str, cid: str, body: ConfirmBody):
    ctx = _ctx(slug, editable=True)
    try:
        return W.confirm_character(ctx, cid, body.confirmed, _owner(body.by))
    except KeyError:
        raise HTTPException(404, "没有这个角色")
    except ValueError as e:
        _bad(e)


@router.put("/projects/{slug}/settings")
def put_settings(slug: str, form: W.SettingsForm):
    ctx = _ctx(slug, editable=True)
    try:
        return W.update_settings(ctx, form)
    except ValueError as e:
        _bad(e)


@router.post("/projects/{slug}/create")
def finalize(slug: str):
    ctx = _ctx(slug, editable=True)
    try:
        W.finalize(ctx)
    except ValueError as e:
        _bad(e)
    return get_project(slug)


@router.get("/projects/{slug}/file/{path:path}")
def project_file(slug: str, path: str):
    ctx = _ctx(slug)
    try:
        p = ctx.resolve_inside(path)
    except ValueError:
        raise HTTPException(403, "路径越界")
    # 封板修复 P0：默认项目的 root 是仓库根，config/ 里有密钥（*.local.json）——一律拒绝 config/、.env、*.local.*、secrets
    rel = p.relative_to(ctx.root.resolve()).as_posix().lower()
    if (rel.startswith(("config/", ".", "ops/", "services/", "tools/")) or ".local." in p.name.lower()
            or "secret" in rel or p.name.lower().endswith(".env")):
        raise HTTPException(404, "没有这个文件")
    if not p.is_file() or p.suffix.lower() not in (*W.IMG_EXT, ".md", ".toml", ".json", ".mp4"):
        raise HTTPException(404, "没有这个文件")
    return FileResponse(p)


# ================================================================== 编排 / 看板 / 待办

def make_engine(ctx: PC.ProjectContext, mode: str | None = None):
    """测试可替换（monkeypatch）。mode 缺省时读状态文件里的模式"""
    from ns_orch.engine import Engine, mode_executor
    from ns_orch.gpu3 import Gpu3Bridge
    mode = mode or PC.read_json(ctx.orchestrator_dir / "state.json", {}).get("mode") or "real"
    return Engine(ctx, mode_executor(mode), Gpu3Bridge(), sync=os.environ.get("NS_ORCH_SYNC") == "1")


class StartBody(BaseModel):
    mode: str = "real"           # real | dry_run
    by: str = ""


@router.post("/projects/{slug}/production/start")
def production_start(slug: str, body: StartBody):
    ctx = _ctx(slug)
    if body.mode not in ("real", "dry_run"):
        raise HTTPException(422, "mode 只能是 real 或 dry_run")
    try:
        make_engine(ctx, body.mode).start(body.mode, _owner(body.by))
    except ValueError as e:
        raise HTTPException(409, str(e))
    _ensure_ticker()
    return make_engine(ctx).board()


@router.post("/projects/{slug}/production/pause")
def production_pause(slug: str, body: ByBody):
    ctx = _ctx(slug)
    make_engine(ctx).pause(body.by or "项目方")      # 暂停是安全操作，谁都可以停
    return make_engine(ctx).board()


@router.post("/projects/{slug}/production/tick")
def production_tick(slug: str):
    ctx = _ctx(slug)
    make_engine(ctx).tick()
    return make_engine(ctx).board()


@router.get("/projects/{slug}/production")
def production_board(slug: str):
    return make_engine(_ctx(slug)).board()


class Decision(BaseModel):
    decision: str
    payload: dict = {}
    by: str = ""


@router.post("/projects/{slug}/cards/{card_id}")
def decide(slug: str, card_id: str, body: Decision):
    ctx = _ctx(slug)
    try:
        make_engine(ctx).decide(card_id, body.decision, body.payload, _owner(body.by))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return make_engine(ctx).board()


class RetryBody(BaseModel):
    episode: int | None = None
    step: str


@router.post("/projects/{slug}/production/retry")
def retry(slug: str, body: RetryBody):
    ctx = _ctx(slug)
    try:
        make_engine(ctx).retry(body.episode, body.step)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return make_engine(ctx).board()


@router.get("/inbox")
def inbox():
    cards = []
    for ctx in PC.list_projects():
        if ctx.is_default or not (ctx.orchestrator_dir / "state.json").exists():
            continue
        cards += make_engine(ctx).cards()
    return sorted(cards, key=lambda c: c.get("opened_at") or "")


@router.get("/gpus")
def gpus(project: str | None = None):
    from ns_orch.executors import comfy_status
    from ns_orch.gpu3 import Gpu3Bridge, SimulatedGpu3
    mode = None
    if project:
        mode = PC.read_json(_ctx(project).orchestrator_dir / "state.json", {}).get("mode")
    gpu3 = SimulatedGpu3({}).gpus() if mode == "dry_run" else Gpu3Bridge().gpus()
    return {"laptop": comfy_status(COMFY_URL), "gpu3": gpu3}


# ================================================================== 后台推进

_ticker: threading.Thread | None = None


def _tick_all():
    while True:
        time.sleep(TICK_S)
        for ctx in PC.list_projects():
            if ctx.is_default:
                continue
            try:
                if PC.read_json(ctx.orchestrator_dir / "state.json", {}).get("running"):
                    make_engine(ctx).tick()
            except Exception:                   # 一个项目出错不影响其他项目
                pass


def _ensure_ticker():
    global _ticker
    if os.environ.get("NS_ORCH_BACKGROUND", "1") == "0":
        return
    if _ticker is None or not _ticker.is_alive():
        _ticker = threading.Thread(target=_tick_all, daemon=True)
        _ticker.start()


def resume_on_startup():
    """API 启动时：有项目在跑就恢复后台推进"""
    if any(not c.is_default and PC.read_json(c.orchestrator_dir / "state.json", {}).get("running")
           for c in PC.list_projects()):
        _ensure_ticker()
