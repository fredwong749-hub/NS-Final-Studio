"""
画布 API：分镜数据、人工修改、重渲染队列、版本切换、角色资产、导演加强。

    uv run uvicorn ns_api.app:app --port 8800
    浏览器打开 http://127.0.0.1:8800

渲染任务在单个后台线程里串行提交到 ComfyUI（NS_COMFY_URL，默认 gpu3 GPU0 = 127.0.0.1:18188，见 config/render_endpoints.json）；
精修循环 frame-jobs 走 ns_api.jobs 的按卡队列（W2）。
canvas-ui-spec-v2 §3.5：摘要里带齐卡片字段（两段提示词、剧本原文、运镜四要素、表情、人物行、尾帧三态），
卡片不必再逐镜请求 /api/shots/{id}。
"""
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ns_agent.compiler import compile_shot
from ns_agent.looks import default_store
from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient, ComfyError
from ns_schema.edits import AuditOverrideRequest, Delivery, H3PromptOverride, ShotEdit, Take
from ns_api import assets as A
from ns_api import shotinfo as SI
from ns_api import api_snapshot as API_SNAP  # DATAALIGN P2：/api/episodes、集摘要的磁盘快照（预热期间用）
from ns_api import unified_stale as UST  # DATAALIGN：unified 出图版本的过期基准
from ns_api import shot_cast as SCAST  # DATAALIGN：镜头卡人物 / 造型 / 脸与出图同源（docs/DATA_MAP.md）
from ns_api import readiness as RD  # 就绪闸门 + 一条链（docs/audit/shot_readiness_and_continuity.md §4）
from ns_api.looks import router as looks_router
from ns_api import projects as PJ  # T42 项目 / 新建剧向导 / 编排 / 看板
from ns_api import project_ctx as PJC
from ns_api import sop as SOP  # SOP 阶段 S1–S5 / 关口 G1–G5（只读）
from ns_api import h3view as H3V  # H3 提示词（SOP §9A）：来源选择 + 四块 + lint
from ns_api import explicit as EX  # 露骨红标：项目方自行处理，不做任何自动动作
from ns_api import owner_gates as OG  # fredw-92/UXF1：项目方在画布里拍板（同命令行记录逻辑）
from ns_api import gpu3_bridge as GB  # gpu3 桥：H3 修改 / 审计豁免 / 出视频闸门（docs/canvas.md §7.6）

from ns_render import endpoints as RENDER_EP  # noqa: E402  W2：出图地址按卡解析（config/render_endpoints.json + 环境变量）
COMFY_URL = RENDER_EP.image_url()   # W2：默认 gpu3 GPU0（隧道 127.0.0.1:18188）；NS_COMFY_URL 仍优先
WEB_DIST = P.ROOT / "apps" / "web" / "dist"
BOOST_LLM_CONFIG = P.ROOT / "config" / "director_boost_llm.json"

# 运镜：motion 原文开头的英文镜头指令，到第一个中文逗号为止
CAMERA_RE = re.compile(r"^((?:extreme )?slow motion|camera [^，]+|static camera[^，]*|handheld[^，]*|"
                       r"orbit[^，]*|push in[^，]*|tracking[^，]*)", re.I)

app = FastAPI(title="momoso Agentic Drama Studio API")
app.add_middleware(GZipMiddleware, minimum_size=1024)  # T60：集数据 JSON 压缩（SSE 流 Starlette 默认不压）
app.include_router(A.router)
app.include_router(looks_router)
app.include_router(PJ.router)
from ns_api import qwen_mailbox as QM  # noqa: E402  Qwen 信箱代理（内容原样转发，不读不改）
from ns_orch import comfy_lock as CL  # noqa: E402  T44：本机 ComfyUI 单一锁（画布队列 + 编排器子进程）
app.include_router(QM.router)
from ns_api import gpu3_requests as GR  # noqa: E402  「请 gpu3 重出」请求进度（桥 /queue，桥断读镜像）
app.include_router(GR.router)
from ns_api import script_inbox as SINBOX  # noqa: E402  剧本导入收件箱（项目方在画布确认导入；只做格式校验）
app.include_router(SINBOX.router)
from ns_api import script_input as SINPUT  # noqa: E402  剧本输入页：粘贴 / 上传草稿 → data/staging_input（成为导入候选）
app.include_router(SINPUT.router)
from ns_api import script_ab as SAB  # noqa: E402  剧本 A/B 对比：两版并排 + 项目方选择（只记录，不打分）
app.include_router(SAB.router)
from ns_api import gpu_monitor as GPUMON  # noqa: E402  GPU 实时面板（桥 + ssh + 信箱，5 s 缓存，只读）
app.include_router(GPUMON.router)
from ns_api import owner_run as OWNRUN  # noqa: E402  按集渲染（项目方本人）：透传桥 /episodes/{ep}/run；🔴 集拒绝
app.include_router(OWNRUN.router)
from ns_api import script_chat as SCHAT  # noqa: E402  T58 剧本创作对话框（外部写作模型，系统只收发 + 格式校验）
app.include_router(SCHAT.router)
from ns_api import llm_config as LLMC  # noqa: E402  §A 统一模型与 API 配置（W1）：/api/llm/*、/api/render/endpoints
app.include_router(LLMC.router)
from ns_api import manage as MG  # noqa: E402  剧本输入页 + 人物管理页
from ns_api import episodes_fast as EF  # noqa: E402  T60 集摘要缓存
app.include_router(MG.router)
from ns_api import jobs as JOBS  # noqa: E402  v1 共享任务队列（按 GPU 分道；GET /api/jobs/{id}、cancel）——W2/W3 共用，只挂一次
if not any(getattr(r, "path", "") == "/api/jobs/{job_id}" for r in app.routes):
    app.include_router(JOBS.router)
app.router.on_startup.append(JOBS.restore)   # 上次没跑完的任务标 failed（“API 重启中断”），不悄悄丢
from ns_api import frame_jobs as FJ  # noqa: E402  §C 出图与精修循环（W2）：frame-jobs / 定稿 lock·unlock
app.include_router(FJ.router)
from ns_render import frame_edit as FE  # noqa: E402
from ns_api import video_jobs as VJ  # noqa: E402  §D 视频任务（W3）：定稿首尾帧 → gpu3 GPU3 H3
from ns_render import h3_video as HV  # noqa: E402
app.include_router(VJ.router)
from ns_api import ref_switch as RSW  # noqa: E402  §E 本镜参考切换（W5）：/api/shots/{id}/refs[/preview|/apply]
app.include_router(RSW.router)
from ns_api import scene_assets as SCA  # noqa: E402  S2 场景资产库（/api/assets/scenes…）；必须挂在 asset_edit 的 /api/assets/{asset_id} 之前
app.include_router(SCA.router)
from ns_api import asset_edit as AED  # noqa: E402  §E 资产参考图组 / image2img / 版本（W5）；挂在 assets 路由之后
app.include_router(AED.router)
from ns_api import episode_produce as EPROD  # noqa: E402  fredw-92/EB 整集出片：按镜头铺到所有渲染道（/api/episodes/{n}/produce）
app.include_router(EPROD.router)
from ns_api import material_readiness as MRD  # noqa: E402  PREP 出片前资料闸门（/api/episodes/{ep}/readiness）
app.include_router(MRD.router)
from ns_api import post_settings as PST  # noqa: E402  UX4：成片对白来源只读（/api/post/dialogue-source）
app.include_router(PST.router)
from ns_api import revisions as REV  # noqa: E402  UX5-B P0 资产版本 / 依赖已更新 / 影响面（只读）
app.include_router(REV.router)
from ns_api import cuts as CUTS  # noqa: E402  UX5 成片页：成片列表 / 落后于定稿的镜头 / 合成新对照版（不覆盖）
app.include_router(CUTS.router)
from ns_api import revisions_p1 as REV1  # noqa: E402  UX6 资产二次修改 P1：set-current / 回滚 / 快照 / 保留旧版 / 成片过期 / LoRA 总表
app.include_router(REV1.router)
from ns_api import asset_center_p1 as ACP1  # noqa: E402  UX6 资产中心 B6–B10：版本链 / 另存 / 道具 / 音色提议 / 提示词模板
app.include_router(ACP1.router)
from ns_api import story_runs as STORY  # noqa: E402  UIRSI 新建剧本：提纲 → 写作链 P0→P4（异步、逐段可看可改、返修、送导入）
app.include_router(STORY.router)
from ns_api import script_autoflow as AUTOFLOW  # noqa: E402  HOLLYWOOD r8：新建剧本 → 可导入，全自动（tools/script_rsi/autoflow.py）
app.include_router(AUTOFLOW.router)
from ns_api import thumbs as THUMBS  # noqa: E402  UIRSI 缩略图（/api/thumb，缓存 data/_cache/thumbs）
app.include_router(THUMBS.router)
from ns_api import auth as AUTH  # noqa: E402  UIRSI 账户登录：项目方闸门从登录会话取身份（不再要原话）+ 写操作审计 data/audit/
AUTH.install(app)
from ns_api import voice_preview as VPREV  # noqa: E402  UIRSI 音色试听（本机 Kokoro）/ 一键换音色 / 旁白样本
app.include_router(VPREV.router)
from ns_api import shot_audio as SHAUD  # noqa: E402  UIRSI 对白逐句试听 / 配乐（B4）
app.include_router(SHAUD.router)
from ns_api import takes_ui as TAKESUI  # noqa: E402  UIRSI 画布候选版本（BE-5 配套）/ 撤销“用这张”
app.include_router(TAKESUI.router)
from ns_api import season as SEASON  # noqa: E402  UIRSI 全剧总览（集 × 镜结构 + 衔接）
app.include_router(SEASON.router)
from ns_api import project_settings as PSET  # noqa: E402  回退补回：项目设置页（旧项目向导 44 项）
app.include_router(PSET.router)
from ns_api import live as LIVE  # noqa: E402  UIRSI 实时推送 /api/events（SSE）+ 分段进度 /api/progress
app.include_router(LIVE.router)
from ns_api import gpu_live as GPULIVE  # noqa: E402  GPUVIEW 每张卡在做什么（comfy_tag）/ 进度 / 队列 / 温度功耗 /api/gpu/live
app.include_router(GPULIVE.router)
from ns_api import render_tasks as RTASKS  # noqa: E402  GPUVIEW 渲染任务中心 /api/render-tasks（顶栏 + 画布底栏同一份）
app.include_router(RTASKS.router)
from ns_api import edits as EDITS  # noqa: E402  EDITDEL 处处可编辑：反馈 → 逻辑模型修改计划 → 出图 / 视频 / 写作改写，进版本链
app.include_router(EDITS.router)
from ns_api import trash as TRASH  # noqa: E402  EDITDEL 删除 → 回收站 data/_trash（可还原；永久删除要 by=owner + 确认短语 + 名称）
app.include_router(TRASH.router)
from ns_api import character_hub as CHUB  # noqa: E402  ASSETUX 人物资产页：一人一页、点选即生效（身份脸 / 设定图 / 单品挂造型 / 上传单品）
app.include_router(CHUB.router)
from ns_api import producer as PRODUCER  # noqa: E402  PRODUCER 制作监督：/api/producer/status、pause / resume / gate（读 data/producer/registry.json）
app.include_router(PRODUCER.router)
from ns_api import infra_status as INFRA  # noqa: E402  UIRSI r38 实时连接状态：/api/infra/status（只读看门狗 / 常驻健康状态文件，不在请求里 ssh）
app.include_router(INFRA.router)
from ns_api import decision_locks as DLOCKS  # noqa: E402  UIRSI r40 项目方已定决策锁：/api/decision-locks（换掉已定的图前一键确认）
app.include_router(DLOCKS.router)
from ns_api import factory_health as FHEALTH  # noqa: E402  UIRSI r42 生产健康汇总：/api/factory/health（只读；总览上的展示等 UI-DESIGN 新设计再接）
app.include_router(FHEALTH.router)
app.router.on_startup.append(EPROD.resume_on_startup)   # 在 JOBS.restore 之后：被重启打断的任务按可恢复错误重试
VJ.get_script = lambda: _script


def _video_done(shot_id: str, take):
    _summary_cache.invalidate()
    _record_look_hash(shot_id, "video", take.n)


VJ.on_done = _video_done
VJ.on_qc_changed = lambda: _summary_cache.invalidate()
PJ.resume_on_startup()
_script = P.load_script()


def _on_script_changed():
    """剧本重新导入后：换上新剧本；集摘要立即重算（T60）；造型模块缓存的剧本也换掉
    （封板修复：否则换剧本后 /api/looks/episodes/N 报 unknown episode，直到重启 API）"""
    global _script
    _script = P.load_script()
    _summary_cache.invalidate()
    default_store()._script = None


def _watch_script():
    """script_v2.json 被重新导入后自动换上新剧本（之前要重启 API 才生效）"""
    last = P.SCRIPT_JSON.stat().st_mtime if P.SCRIPT_JSON.exists() else 0
    while True:
        time.sleep(10)
        try:
            m = P.SCRIPT_JSON.stat().st_mtime
            if m != last:
                _on_script_changed()
                last = m
        except (OSError, ValueError):
            pass   # 导入写到一半时读到半个文件，下一轮再试


threading.Thread(target=_watch_script, daemon=True).start()
_jobs: dict[str, dict] = {}
_queue: "queue.Queue[str]" = queue.Queue()

STAGES = ("image", "last", "video")
REVIEW_STATES = ("unreviewed", "passed", "rejected")
REVIEW_STAGES = ("image", "video")       # 审核只绑首帧 + 视频版本（尾帧加入前的 review.json 仍有效）
EDIT_PROMPT_FIELDS = ("image_prompt", "image_negative", "video_prompt", "camera", "expression", "last_prompt",
                      "boost_first", "boost_last", "soundscape", "h3_body")
# 各阶段受哪些人工字段影响（环境声只进视频；配乐 music 是后期用，不让任何版本过期）
STAGE_EDIT_FIELDS = {"image": ("image_prompt", "image_negative", "boost_first", "camera", "expression"),
                     "last": ("last_prompt", "boost_last", "camera", "expression"),
                     "video": ("h3_prompt_override",)}   # SOP §9A：H3 只认项目方覆盖


def _url(rel: str | None) -> str | None:
    if not rel:
        return None
    p = P.DATA / rel
    return f"/files/{rel}?v={int(p.stat().st_mtime)}" if p.exists() else None


def last_supported() -> bool:
    """尾帧生成由 render_router 提供（pipeline.render_last_frame）；没上线前 stage=last 返回 501"""
    return hasattr(P, "render_last_frame")


def _active(shot_id: str, data: dict | None = None) -> dict:
    data = data or P.load_takes(shot_id)
    out = {}
    for stage in STAGES:
        n = data["active"].get(stage)
        t = next((t for t in data["takes"] if t["stage"] == stage and t["n"] == n), None)
        # UIRSI r41（项目方 11-02 00:5x：“旧版本的东西就隔离开吧”）：当前版本已隔离（旧剧本版本，文件已移走）= 这一阶段没有当前版本，
        # 集摘要 / 详情都不再把它算作“有”（CONSENT DATAALIGN → UIRSI）
        # r42：标记被服务器并回冲掉、但文件已在隔离区的，也算已隔离（ns_api.takes_ui.is_quarantined 同口径）
        from ns_api.takes_ui import is_quarantined  # noqa: PLC0415
        out[stage] = None if (t and is_quarantined(t)) else t
    return out


def _camera(motion: str) -> str:
    body = re.sub(r"^[a-z0-9_]+，", "", motion)
    m = CAMERA_RE.match(body)
    return m.group(1).strip() if m else ""


def _auto_locked(takes: dict, act: dict) -> dict:
    """takes.json locked_by[stage] = {by:"auto", n}（episode_produce 自动测试定稿）且 n 仍是定稿版 / 当前视频 → {stage: n}"""
    out = {}
    lk = takes.get("locked") or {}
    for st, rec in (takes.get("locked_by") or {}).items():
        if not isinstance(rec, dict) or rec.get("by") != "auto" or rec.get("n") is None:
            continue
        cur = (act.get(st) or {}).get("n") if st == "video" else lk.get(st)
        if cur == rec["n"]:
            out[st] = rec["n"]
    return out


def _review(shot_id: str, act: dict) -> dict:
    """审核只对当前版本有效：当前版本换了就回到未审"""
    r = P._read_json(P.shot_dir(shot_id) / "review.json", {})
    current = {k: (act[k]["n"] if act.get(k) else None) for k in REVIEW_STAGES}
    if not r or {k: (r.get("takes") or {}).get(k) for k in REVIEW_STAGES} != current:
        return {"state": "unreviewed", "reason": "", "at": None}
    return {"state": r["state"], "reason": r.get("reason", ""), "at": r.get("at")}


# ---------------------------------------------------------------- 导演加强（本集）

def episode_edit_path(n: int) -> Path:
    return P.RENDERS / f"ep{n:02d}" / "episode_edit.json"


def load_episode_edit(n: int) -> dict:
    """优先用 pipeline.load_episode_edit（渲染器会读同一份）；没上线前直接读 JSON"""
    if hasattr(P, "load_episode_edit"):
        e = P.load_episode_edit(n)
        return e.model_dump() if hasattr(e, "model_dump") else dict(e)
    d = P._read_json(episode_edit_path(n), {})
    return {"boost_first": d.get("boost_first"), "boost_last": d.get("boost_last"), "music": d.get("music"),
            "updated_at": d.get("updated_at")}


class EpisodeEditBody(BaseModel):
    """只改请求里出现的字段（保存导演加强不会清掉本集背景音乐，反之亦然）"""
    boost_first: str | None = None
    boost_last: str | None = None
    music: str | None = None             # 本集配乐（英文 → 各镜 H3 non_diegetic_music 的默认值；中文 → 只作后期提示）


def _schema_fields(name: str) -> set[str]:
    from ns_schema import edits as E
    m = getattr(E, name, None)
    return set(getattr(m, "model_fields", {}) or {})


def audio_supported() -> dict:
    """E8 字段是否已上线（ns_schema.edits）；没上线时画布只读显示，不假装保存成功"""
    shot, ep = _schema_fields("ShotEdit"), _schema_fields("EpisodeEdit")
    return {"soundscape": "soundscape" in shot, "music": "music" in shot, "episode_music": "music" in ep}


def save_episode_edit(n: int, body: EpisodeEditBody) -> dict:
    with P.episode_lock(n):   # fredw-92/B-fix：读-改-写 episode_edit.json 与 refs/apply scope=scene 同一把每集锁
        return _save_episode_edit(n, body)


def _save_episode_edit(n: int, body: EpisodeEditBody) -> dict:
    given = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in body.model_dump(exclude_unset=True).items()}
    if given.get("music") and not audio_supported()["episode_music"]:
        raise HTTPException(501, "本集背景音乐字段（EpisodeEdit.music）后端还没上线，暂不能保存")
    clean = {**{k: v for k, v in load_episode_edit(n).items() if k != "updated_at"}, **given}
    if hasattr(P, "save_episode_edit"):
        from ns_schema import edits as E
        if hasattr(E, "EpisodeEdit"):
            fields = _schema_fields("EpisodeEdit")
            e = P.save_episode_edit(n, E.EpisodeEdit(**{k: v for k, v in clean.items() if k in fields}))
            return e.model_dump() if hasattr(e, "model_dump") else dict(e)
    rec = {**clean, "updated_at": P.now()}
    P._write_json(episode_edit_path(n), rec)
    return rec


def _boosts(edit: ShotEdit, ep_edit: dict) -> dict:
    return {"first": getattr(edit, "boost_first", None), "last": getattr(edit, "boost_last", None),
            "episode_first": ep_edit.get("boost_first"), "episode_last": ep_edit.get("boost_last")}


# ---------------------------------------------------------------- 尾帧提示词 / 过期

def _last_prompt(compiled, edit: ShotEdit, s) -> tuple[str, str]:
    """尾帧提示词 → (文本, 来源 edit|compiler|fallback)。编译器输出 last_prompt 后自动改用编译器的。"""
    if edit.last_prompt:
        return edit.last_prompt, "edit"
    lp = getattr(compiled, "last_prompt", None)
    if lp:
        return lp, "compiler"
    return SI.fallback_last_prompt(s.motion_prompt, _script.globals.image_suffix or ""), "fallback"


_PLATE_RE = re.compile(re.escape(getattr(P, "LAST_ROLE_PLATE", "") or "\0")
                       .replace(r"\{i\}", r"\d+").replace(r"\{name\}", r"[^。；，]+?"))


def _strip_plate(prompt: str) -> str:
    """尾帧提示词：去掉 render_last_frame 插在第一句后的身份底板说明（图2只提供…的面部身份与发型…）"""
    return _PLATE_RE.sub("", prompt, count=1) if prompt else prompt


def _inputs_changed(shot_id: str, take: dict, look_hash: str | None) -> str | None:
    """提示词对不上时，区分本镜输入变化（local）与编译器升级（global）：
    "look" = 造型哈希变了；"inputs" = 出图时的 inputs_sha（剧本 / 造型 / 参考覆盖 / 底板）≠ 当前；None = 没变或无从判断"""
    if look_hash and take.get("look_hash") and take["look_hash"] != look_hash:
        return "look"
    sha = take.get("inputs_sha")
    if not sha:
        return None
    try:
        from ns_agent.state_timeline import shot_inputs_sha
        cur = shot_inputs_sha(shot_id, P.ROOT)
    except Exception:  # noqa: BLE001
        return None
    return "inputs" if cur and cur != sha else None


def _stale_split(shot_id: str, take: dict, s, compiled, edit: ShotEdit, act: dict, look_hash: str | None,
                 last_prompt: str, ep_edit: dict | None = None) -> tuple[list[str], list[str]]:
    """过期原因拆成两类（规范 §3.5.7）：
    local  = 本镜输入变化：本镜修改 / 导演加强、剧本原文、造型、首帧、下一镜首帧 → 卡片显示「过期」角标
    global = 全局编译器升级（剧本原文还在、本镜没改，只是拼装规则变了）→ 只在检查器 / 版本里显示"""
    local, glob = [], []
    stage = take["stage"]
    created = take["created_at"]
    target = {"image": compiled.image_prompt, "video": compiled.video_prompt, "last": last_prompt}.get(stage, "")
    prompt = take.get("prompt") or ""
    # F4：指令改图 / 换参考的 prompt 是项目方原话、画布一次性整段替换不是编译提示词 → 和出图时的编译提示词基准比
    # （改图版本沿修改链继承父版本的基准；旧版本没记基准时现场沿链找）
    if take.get("basis_prompt") is not None or take.get("mode") in FE.EDIT_MODES:
        prompt = take["basis_prompt"] if take.get("basis_prompt") is not None else \
            FE.chain_basis(P.load_takes(shot_id), take)
        if not prompt:
            target = ""                          # 父版本是上传 / 引用：无可比
    if stage == "last":
        prompt = _strip_plate(prompt)            # 尾帧渲染时在第一句后插了身份底板说明（不是编译器输出）
    if take.get("workflow") in FE.NO_PROMPT_WORKFLOWS or take.get("source") in FE.NO_PROMPT_SOURCES:
        target = ""                              # 上传 / 引用的版本没有提示词可比
    # DATAALIGN（UIPIXEL P1）：唯一出图路径（unified_frame）的版本和“同一条路径现在拼出的正文”比，不和旧编译器比
    # （旧比较对 unified 版本必然失败 → 一出来就“剧本已改”）；见 ns_api/unified_stale.py
    unified = UST.is_unified(take) and stage in ("image", "last") and take.get("basis_prompt") is None         and take.get("mode") not in FE.EDIT_MODES
    if unified and target:
        try:
            ub = UST.unified_bodies(_script, P.find_shot(_script, shot_id)[0], s)
        except Exception:  # noqa: BLE001
            ub = None
        if ub and ub.get(stage):
            target = UST.match_target(prompt, ub[stage]) if stage == "image" else ub[stage]
    if UST.is_video10(take):
        target = ""                              # VIDEO10 片子：不和画布 H3 视图比提示词，只按 from_first 判首帧已换
    v1_video = stage == "video" and bool((take.get("params") or {}).get("first"))   # §D 视频任务出的版本（W3）
    if v1_video:
        vp = take["params"]
        # 项目方给的提示词（请求覆盖 / 画布覆盖）不和剧本比；剧本版按本版帧数重算对齐句后再比
        target = "" if vp.get("prompt_source") in ("request", "owner_edit") else \
            HV.realign(target, vp.get("frames") or take.get("frames") or 0) if target else target
        if target and vp.get("last_frame_used") is False:   # RR：只给首帧时系统对齐句是 I2VA 句，基准同样换
            old_style = HV.align_first_only(target)      # FIX P0 ③ 之前出的版本：正文仍带 Picture 2 句
            target = old_style if prompt.endswith(old_style) else HV.i2v_prompt(target)[0]
    edited_after = bool(edit.updated_at and edit.updated_at > created)
    # 锁脸前缀（"图1是林晚的面部参考：…按以下描述。"）等由渲染器加在最前，比较时只看结尾
    if target and not prompt.endswith(target):
        raw = SI.strip_triggers(s.img_prompt if stage != "video" else s.motion_prompt)
        if edited_after and any(getattr(edit, f, None) for f in STAGE_EDIT_FIELDS.get(stage, EDIT_PROMPT_FIELDS)):
            local.append("提示词已改")
        elif not unified and stage != "last" and raw and raw[:12] not in prompt and SI.action_text(raw)[:12] not in prompt:
            local.append("剧本已改")                 # 旧路径的猜法；unified 版本按 inputs_sha 判（下一分支）
        elif why := _inputs_changed(shot_id, take, look_hash):
            if why == "inputs":                  # F4：造型 / 参考覆盖 / 时间线变了（不是编译器升级）
                local.append("本镜输入已改")      # why == "look" → 下面记「造型已改」
        else:
            glob.append("编译器升级")
    # 导演加强：保存晚于版本 → 本镜输入变化（渲染器把加强写进提示词后，上面的提示词比较也会命中）
    boost_field = {"image": "boost_first", "last": "boost_last"}.get(stage)
    if boost_field and "提示词已改" not in local:
        if edited_after and getattr(edit, boost_field, None) and getattr(edit, boost_field) not in prompt:
            local.append("导演加强已改")
        elif ep_edit and ep_edit.get("updated_at") and ep_edit["updated_at"] > created \
                and ep_edit.get(boost_field) and ep_edit[boost_field] not in prompt:
            local.append("本集加强已改")
    if look_hash and take.get("look_hash") and take["look_hash"] != look_hash:
        local.append("造型已改")
    if stage == "image" and take.get("scene_plate"):   # S3（fredw-92/S-back）：带过的场景底图换了定稿版本
        from ns_render import scene_plate as SPL
        local += [r for r in SPL.stale_reasons(take, P.ROOT) if r not in local]
    if v1_video:   # 首尾帧来自定稿版本：定稿换了（版本号或文件）才过期
        local += HV.stale_reasons(take, P.load_takes(shot_id))
        return local, glob
    img = act.get("image")
    if stage in ("video", "last") and take.get("source") != "next":
        ff = take.get("from_first")
        if ff is not None:   # F4：记了由哪版首帧得到 → 只和定稿（没定稿时当前）首帧版本比，不按时间比
            tk = P.load_takes(shot_id)
            cur = (tk.get("locked") or {}).get("image")
            cur = cur if cur is not None else (img["n"] if img else None)
            from ns_render import frame_edit as _FE   # fredw-92/Q1：尾帧对“预览版 → 其定稿档”不算首帧已换
            same = _FE.first_equivalents(tk, cur) if stage == "last" else {cur}
            if cur is not None and ff not in same:
                local.append("首帧已换")
        elif img and img["created_at"] > created:
            local.append("首帧已换")
    if stage == "video":
        if edit.last_frame == "next":
            nxt = P.next_shot_id(_script, shot_id)
            nimg = _active(nxt)["image"] if nxt else None
            if nimg and nimg["created_at"] > created:
                local.append("下一镜首帧已换")
        lst = act.get("last")
        if lst and lst["created_at"] > created and edit.last_source in (None, "gen"):
            local.append("尾帧已换")
    return local, glob


def _dep_stale(shot_id: str, take: dict, local: list[str] | None = None, ledger: dict | None = None) -> list[dict]:
    """UX5-B P0：“依赖已更新”（docs/ux_round5/B_revision.md §2.4）。只标记：不并入 stale（整集出片 EB 按 stale 判断要不要重出），
    卡片显示单独的角标。来源：take.deps 里的资产版本 ≠ 当前；G1：首帧 / 尾帧 inputs_sha ≠ 当前（与提示词是否变无关，
    已报「本镜输入已改」「造型已改」的不重复）；旧视频：基底配方原样字段 ≠ 当前配置"""
    try:
        from ns_agent import asset_revs as AR
        out = AR.stale_deps(take, P.ROOT, ledger)
        stage = take.get("stage")
        if stage in ("image", "last") and not ({"本镜输入已改", "造型已改"} & set(local or [])):
            from ns_agent.state_timeline import shot_inputs_sha
            d = AR.inputs_dep(take, shot_inputs_sha(shot_id, P.ROOT))
            if d:
                out.append(d)
        if stage == "video":
            d = AR.vbase_drift(take, P.ROOT)
            if d and not any(x["key"] == d["key"] for x in out):
                out.append(d)
        return out
    except Exception:  # noqa: BLE001 — 算不出不影响画布
        return []


def _stale(shot_id: str, take: dict, compiled, act: dict) -> list[str]:
    """兼容旧调用：只返回本镜原因"""
    _, s = P.find_shot(_script, shot_id)
    edit = P.load_edit(shot_id)
    return _stale_split(shot_id, take, s, compiled, edit, act, None, _last_prompt(compiled, edit, s)[0])[0]


_IDX: dict = {"at": 0.0, "key": None, "idx": None}
_IDX_TTL_S = 10.0


def _asset_index(store) -> "A.AssetIndex":
    """T60：资产索引（扫 7 个角色目录约 0.2 s）跨请求复用 10 s；衣橱文件一改立即重扫"""
    try:
        key = store._path("wardrobe").stat().st_mtime_ns
    except OSError:
        key = None
    now = time.time()
    if _IDX["idx"] is None or _IDX["key"] != key or now - _IDX["at"] > _IDX_TTL_S:
        _IDX.update(at=now, key=key, idx=A.AssetIndex(store))
    return _IDX["idx"]


class Ctx:
    """一次请求共享：造型解析器、资产索引、本集加强（避免每镜重复读 JSON / 扫目录）"""

    def __init__(self):
        store = default_store()
        self.res = store.resolver()
        self.idx = _asset_index(store)
        self.looks_by_id = {lk.id: lk for lk in store.lookbook().looks}
        self._ep: dict[int, dict] = {}
        self.slug = RD.current_slug()
        self.cast = SCAST.CastCtx(_script)   # DATAALIGN：剧本 **人物** 行 + shot_looks 登记（与 asset_refs.resolve_shot 同口径）
        self._chains: dict[str, dict] = {}

    def chain(self, shot_id: str) -> dict:
        if shot_id not in self._chains:
            self._chains[shot_id] = RD.gpu3_chain(shot_id, self.slug)
        return self._chains[shot_id]

    def shot_looks(self, s):
        try:
            return self.res.shot_looks(s)
        except Exception:                       # 造型数据坏了不影响卡片其它字段
            return None

    def ep_edit(self, n: int) -> dict:
        if n not in self._ep:
            self._ep[n] = load_episode_edit(n)
        return self._ep[n]

    def rev_ledger(self) -> dict:
        """UX5-B：资产版本账本（vN 文案用），一次请求读一次"""
        if not hasattr(self, "_ledger"):
            try:
                from ns_agent.asset_revs import read_ledger
                self._ledger = read_ledger(P.ROOT)
            except Exception:  # noqa: BLE001
                self._ledger = {}
        return self._ledger


def _last_frame_info(shot_id: str, edit: ShotEdit, act: dict) -> dict:
    """尾帧：目标（独立资产）/ 实际（视频抽帧）/ 来源 gen|next|upload|video"""
    actual = _url(act["video"]["last_frame"]) if act.get("video") and act["video"].get("last_frame") else None
    lt = act.get("last")
    nxt = P.next_shot_id(_script, shot_id)
    next_first = None
    if nxt:
        nimg = _active(nxt)["image"]
        next_first = _url(nimg["file"]) if nimg else None
    src = edit.last_source
    if not src:
        if edit.last_frame == "next":
            src = "next"
        elif edit.last_frame:
            src = "upload"
        elif lt:
            src = lt.get("source") or "gen"
            if src not in ("gen", "upload", "next", "video"):
                src = "gen"   # DATAALIGN（PW-011）：出图线登记的版本（source=pipeline）就是生成的独立尾帧，前端只认这四种
        elif actual:
            src = "video"
    target = None
    if src == "next":
        target = next_first
    elif src == "upload":
        target = _url(edit.last_frame) if edit.last_frame and edit.last_frame != "next" else (
            _url(lt["file"]) if lt else None)
    elif src == "video":
        target = actual
    else:
        # gen，以及登记进来的出图线版本（source=pipeline 等）：当前尾帧就是这一版。
        # DATAALIGN（PW-011）：以前只认 "gen"，pipeline 版本的 last_frame_target 恒为 null，监督面板 / 进度都当“没有尾帧”
        target = _url(lt["file"]) if lt else None
    return {"last_frame_source": src, "last_frame_target": target, "last_frame_actual": actual,
            "last_frame_take": lt["n"] if lt else None, "next_shot": nxt, "next_first_frame": next_first,
            "last_supported": last_supported()}


def episode_music(ep, ep_edit: dict) -> dict:
    """本集配乐（项目方 2026-10-30 E8：进 H3）。英文作为各镜 H3 non_diegetic_music 的默认值——取值顺序见
    h3_prompt.resolve_music：本镜修改 > 剧本 H3 字段 > 【配乐】静默提示（N/A）> 本集【BGM】英文；中文只作后期提示。
    后期对 H3 已带配乐的镜头不再叠 BGM（ns_post.music.h3_music_shots）。
    人工（EpisodeEdit.music）优先；默认取剧本 **配乐** 行的【BGM】英文提示，没有就用整行原文。"""
    bgm, raw = getattr(ep, "music_bgm", "") or "", getattr(ep, "music", "") or ""
    default = bgm or raw
    edit = ep_edit.get("music")
    return {"text": edit or default, "source": "edit" if edit else ("script" if default else "none"),
            "default": default, "default_source": "script" if default else "none", "raw": raw}


def _audio(c, compiled, edit: ShotEdit, s, ep, ep_edit: dict) -> dict:
    """E8：环境声 overall_soundscape（进 H3，指南 §4.6）+ 本镜配乐提示（后期，ShotEdit.music / 剧本 music_cue）。
    编译器上线后用它的 video_soundscape(+_source) 与 post_music；之前按 人工 → 剧本 兜底。
    default* = 不算本镜人工修改时的值（「恢复默认」用）。"""
    sc_def = getattr(c, "video_soundscape", None)
    sc_def_src = getattr(c, "video_soundscape_source", None) or ("script" if sc_def else None)
    if sc_def is None:
        sc_def, sc_def_src = (s.sound or ""), ("script" if s.sound else "none")
    pm = getattr(c, "post_music", None) or {}
    cue_def = (pm.get("shot_cue") if isinstance(pm, dict) else None) or getattr(s, "music_cue", "") or ""
    sc_edit, mu_edit = getattr(edit, "soundscape", None), getattr(edit, "music", None)
    return {
        "soundscape": {"text": sc_edit or getattr(compiled, "video_soundscape", None) or sc_def,
                       "source": "edit" if sc_edit else sc_def_src, "default": sc_def, "default_source": sc_def_src},
        "music": {"text": mu_edit or cue_def, "source": "edit" if mu_edit else ("script" if cue_def else "none"),
                  "default": cue_def, "default_source": "script" if cue_def else "none"},
        "episode_music": episode_music(ep, ep_edit),
        "supported": audio_supported(),
    }


def _storyboard(s) -> dict:
    """fredw-92/U4：本镜分镜字段原文（画布“分镜详情 / 分镜表”只读显示，逐字，不改写）。
    end_state：剧本写了 **结束状态**（R3）就用原文；否则取 motion 最后一个“——”之后的原文（S1-W1），没有“——”= None。"""
    motion = s.motion_prompt or ""
    end = getattr(s, "end_state", None) or None
    end_src = "script" if end else None
    if not end and "——" in motion:
        end = motion.rsplit("——", 1)[1].strip() or None
        end_src = "motion" if end else None
    cast = getattr(s, "cast", None)
    return {
        "scene_id": getattr(s, "scene_id", None), "scene_detail": getattr(s, "scene_detail", None),
        "img_note": s.img_note, "img_prompt": s.img_prompt, "motion_prompt": motion,
        "end_state": end, "end_state_source": end_src,
        "cast_raw": getattr(s, "cast_raw", None), "cast": [c.model_dump() for c in cast] if cast is not None else None,
        "link": getattr(s, "link", None), "link_carry": getattr(s, "link_carry", None),
        "sound": s.sound or "", "sound_h3": getattr(s, "sound_h3", "") or "",
        "sound_intimate": getattr(s, "sound_intimate", "") or "", "music_cue": getattr(s, "music_cue", "") or "",
        "h3_prompt": getattr(s, "h3_prompt", None), "h3_check": getattr(s, "h3_check", None),
        "dialogue_raw": s.dialogue_raw, "dialogue_stage": list(getattr(s, "dialogue_stage", []) or []),
        "duration": getattr(s, "duration", None), "duration_source": getattr(s, "duration_source", "default"),
    }


def _queue_pos(job_id: str) -> int | None:
    q = sorted((j for j in _jobs.values() if j["state"] == "queued"), key=lambda j: j["created_at"])
    return next((i + 1 for i, j in enumerate(q) if j["id"] == job_id), None)


def _shot_summary(ep, s, ctx: Ctx | None = None) -> dict:
    ctx = ctx or Ctx()
    takes = P.load_takes(s.id)
    act = _active(s.id, takes)
    edit = P.load_edit(s.id)
    ep_edit = ctx.ep_edit(ep.number)
    c = compile_shot(ep, s, _script.globals, set())
    compiled = _compile_for_display(ep, s, edit)
    last_prompt, last_prompt_src = _last_prompt(compiled, edit, s)
    sl = ctx.shot_looks(s)
    look_hash = sl.look_hash if sl else None
    stale, stale_global, stale_deps = {}, {}, {}
    for k, v in act.items():
        if v:
            stale[k], stale_global[k] = _stale_split(s.id, v, s, compiled, edit, act, look_hash, last_prompt, ep_edit)
            if deps := _dep_stale(s.id, v, stale[k], ctx.rev_ledger()):
                stale_deps[k] = deps
    pending = [j for j in _jobs.values() if j.get("shot_id") == s.id and j["state"] in ("queued", "running")]
    lf = _last_frame_info(s.id, edit, act)
    # UIAUDIT P1-1（UIRSI r43）：已隔离的旧剧本版本不计数（否则画布写“视频 1 版待选”却没有可挑的）
    from ns_api.takes_ui import is_quarantined  # noqa: PLC0415
    count = {st: sum(1 for t in takes["takes"] if t["stage"] == st and not is_quarantined(t)) for st in STAGES}
    boost = _boosts(edit, ep_edit)
    chain_info = _chain_fields(ep, s, c, edit, ep_edit, act, lf, ctx)
    h3v = H3V.view(s, compiled, edit, ctx.slug, c.adult)
    hold = EX.hold(s, ctx.slug)
    return {
        "review": _review(s.id, act),
        "stale": stale, "stale_global": stale_global, "stale_deps": stale_deps,
        "id": s.id, "index": s.index, "adult": c.adult, "edited": bool(edit.updated_at),
        "camera": SI.camera_info(edit.camera, s.img_prompt, s.motion_prompt),
        "expression": SI.expression_info(edit.expression, s.img_prompt, s.motion_prompt),
        "img_summary": s.img_prompt[:60],
        "script_text": SI.script_text(s.img_note, s.motion_prompt),
        # DATAALIGN：剧本没写时长（None / 缺）= 10 秒兜底、标 default；/api/season 同一规则（两页总秒数一致）
        "duration": {"seconds": getattr(s, "duration", None) if getattr(s, "duration", None) is not None else 10,
                     "source": getattr(s, "duration_source", None) or ("script" if getattr(s, "duration", None) is not None else "default")},
        "image_prompt": compiled.image_prompt, "image_prompt_edited": bool(edit.image_prompt),
        # 视频提示词 = H3 官方四块提示词（gpu3 最终 > 剧本 **H3提示词** > 笔记本草稿）；旧版中文拼接只作历史
        "video_prompt": h3v["h3_prompt"],
        "video_prompt_edited": bool(edit.h3_prompt_override),
        "legacy_video_prompt": compiled.legacy_video_prompt,
        **h3v,
        # 兼容字段：2026-10-30 取消成人过滤器后恒为 None
        "explicit_hold": hold,
        "last_prompt": last_prompt, "last_prompt_source": last_prompt_src,
        # 卡片两行放不下全文：从本镜特有的部分开始显示（跳过角色锁 / 固定前缀），悬停看全文
        "image_prompt_focus": SI.focus(compiled.image_prompt, SI.strip_triggers(s.img_prompt)),
        "last_prompt_focus": SI.focus_last(last_prompt),
        "boost": boost, "has_boost": any(boost.values()),
        "audio": _audio(c, compiled, edit, s, ep, ep_edit),
        "storyboard": _storyboard(s),   # fredw-92/U4：剧本分镜字段原文（摘要缓存的 light_shot 不带）
        "first_frame": _url(act["image"]["file"]) if act["image"] else None,
        "first_frame_take": act["image"]["n"] if act["image"] else None,
        # fredw-92/UXF1：当前首帧 / 尾帧是不是坏图（ns_render.image_check）；定稿版本号（与当前不同 = 当前是草稿）
        "bad": {st: (P.bad_reason(act[st]) if act[st] else None) for st in ("image", "last")},
        "locked_take": {st: (takes.get("locked") or {}).get(st) for st in ("image", "last")},
        # fredw-92/UXF4（审查 N1）：整集出片“自动测试定稿”的阶段 → 版本号（仍是那一版定稿 / 当前视频才算）；
        # 画布上标“自动定稿·待复审”，不算项目方定稿 / 通过
        "auto_locked": _auto_locked(takes, act),
        "video": _url(act["video"]["file"]) if act["video"] else None,
        # fredw-92/QCV：当前视频的运动量质检（ns_render.motion_qc；画布视频格角标“静止·不合格”/“结尾定住 Ns”）
        "video_qc": _video_qc(act["video"]),
        "last_frame": lf["last_frame_actual"],       # 兼容 v1：= 视频实际尾帧
        **lf,
        "takes_count": count,
        # 每个阶段最新版本号：大于当前版本 = 有新版本待选（行内「新 vN 待选」，检查器自动放到对比位）
        "latest_take": {st: max((t["n"] for t in takes["takes"] if t["stage"] == st and not is_quarantined(t)), default=None) for st in STAGES},
        "score": {k: (v.get("score") if v else None) for k, v in act.items() if k != "video"},
        "needs_review": takes.get("review") or {},
        "dialogue": [d.model_dump() for d in s.dialogue],
        "voiceover": s.voiceover.model_dump() if s.voiceover else None,
        "decor_state": s.decor_state,
        "look_hash": look_hash,
        # DATAALIGN K-DATA-001：人选 = 剧本本镜 **人物** 行（在画 / 局部），造型字母 = 出图登记（A/B/C），脸 = 出图身份脸；
        # 旧造型库只补插槽 / 冲突 / 本镜覆盖。剧本不属于登记了资产的项目 → 旧库原样
        "characters": SCAST.merge(SCAST.shot_cast(ctx.cast, ep, s),
                                  [A.character_brief(r, ctx.idx, ctx.looks_by_id) for r in sl.characters] if sl else []),
        "job": pending[0]["state"] if pending else None,
        "job_stage": pending[0]["stage"] if pending else None,
        "queue_pos": _queue_pos(pending[0]["id"]) if pending else None,
        **chain_info,
    }


def _video_qc(take: dict | None) -> dict | None:
    """take.qc.motion 的精简版 {verdict, labels, reasons, metrics}；没质检过 → None"""
    mo = ((take or {}).get("qc") or {}).get("motion")
    if not mo:
        return None
    return {"verdict": mo.get("verdict"), "labels": mo.get("labels") or [], "reasons": mo.get("reasons") or [],
            "metrics": mo.get("metrics") or {}, "take": (take or {}).get("n")}


def _chain_fields(ep, s, c, edit: ShotEdit, ep_edit: dict, act: dict, lf: dict, ctx: Ctx) -> dict:
    """一条链（§4）：gpu3 负责 / 有 gpu3 链时，首帧·尾帧·视频全部取 gpu3 链，笔记本版本只作历史；
    返回的键会覆盖摘要里同名的笔记本字段。另附 readiness（就绪闸门）。"""
    chain = ctx.chain(s.id)
    owner, owner_why = RD.shot_owner(s.id, ctx.slug, chain)
    laptop = {"first": _url(act["image"]["file"]) if act["image"] else None,
              "first_take": act["image"]["n"] if act["image"] else None,
              "last": lf["last_frame_target"] or lf["last_frame_actual"], "last_from": lf["last_frame_source"],
              "video": _url(act["video"]["file"]) if act["video"] else None}
    has_laptop = bool(laptop["first"] or laptop["last"] or laptop["video"])
    # owner=canvas（W2）：画布有版本就显示画布的；还没有时才显示 gpu3 链（历史）
    use_gpu3 = owner == "gpu3" or (chain["present"] and not (owner == "canvas" and has_laptop))
    if use_gpu3:
        frames_source = "gpu3" if (chain["first_frame"] or chain["last_frame"] or chain["video"]) else "none"
    else:
        frames_source = "laptop" if has_laptop else "none"
    i = next((k for k, x in enumerate(ep.shots) if x.id == s.id), 0)
    prev_id = ep.shots[i - 1].id if i > 0 else None
    out = {
        "owner": owner, "owner_reason": owner_why, "frames_source": frames_source,
        "gpu3": chain,
        "laptop_history": ({**laptop, "note": RD.HISTORY_NOTE} if use_gpu3 and has_laptop else None),
        "readiness": RD.readiness(s=s, ep=ep, adult=c.adult, edit=edit, ep_edit=ep_edit, owner=owner,
                                  frames_source=frames_source, chain=chain, laptop=laptop, prev_id=prev_id),
        "prev_shot": prev_id,
    }
    if use_gpu3:   # 行内显示 = 出视频实际用的那一对；笔记本的版本号 / 过期 / 新版本提示都不属于这条链
        out.update({
            "first_frame": chain["first_frame"], "first_frame_take": chain["image_take"],
            "video": chain["video"], "video_qc": None, "last_frame": chain["last_frame"],
            "last_frame_target": chain["last_frame"], "last_frame_actual": chain["last_frame"],
            "last_frame_source": "gpu3" if chain["last_frame"] else None, "last_frame_take": None,
            "stale": {}, "stale_global": {}, "stale_deps": {}, "score": {}, "bad": {}, "locked_take": {}, "auto_locked": {},
            "latest_take": {st: None for st in STAGES},
        })
        if lf.get("next_shot"):
            out["next_first_frame"] = ctx.chain(lf["next_shot"])["first_frame"]
    return out


def _find(shot_id: str):
    try:
        return P.find_shot(_script, shot_id)
    except KeyError:
        raise HTTPException(404, "没有这个镜头")


# ---------------------------------------------------------------- 读

def _episode_readiness(ep, shots: list[dict], ctx: Ctx) -> dict:
    """本集顶部：就绪 N / M 镜 + 衔接表（renders_gpu3/epXX/continuity_sheet.jpg）"""
    return {"ready": sum(1 for x in shots if x["readiness"]["ready"]), "total": len(shots),
            "owner": RD.project_owner(ctx.slug)[0], **RD.episode_extras(ep.number, ctx.slug)}


from ns_api import shot_cache as SCACHE  # noqa: E402  DATAALIGN（P1）：镜头卡摘要按镜输入签名缓存，返回内容不变

_shot_cache = SCACHE.ShotCache()


def _cache_global_sig(ctx) -> tuple:
    """全局输入签名（见 shot_cache 文档）：剧本对象 + 造型 / 配置 / 本剧资产登记 / 版本账本 / 顶层状态文件"""
    root = Path(P.ROOT)
    dirs = [root / "data" / "looks", root / "config", root / "config" / "recipes"]
    pj = ctx.cast.project
    files = [root / "data" / "scenes.json", root / "data" / "state_timeline.json", root / SOP.OWNER_GATES]
    if pj:   # 本剧资产登记只看镜头卡真正读的两份（出图作业表等频繁写的文件不进签名）
        files += [root / "data" / "pipeline" / "runs" / pj / "assets" / f for f in ("shot_looks.json", "sheets_chosen.json")]
    try:
        from ns_agent.asset_revs import ledger_path
        files.append(ledger_path(P.ROOT))
    except Exception:  # noqa: BLE001
        pass
    # 剧本用文件 (mtime, 大小) 而不是 id(_script)：签名要能跨进程（按镜缓存的磁盘快照，重启后复用）
    return SCACHE.ShotCache.global_sig(dirs, files, (tuple(API_SNAP.script_key(P.SCRIPT_JSON) or ()), ctx.slug, str(P.DATA),
                                                      _CODE_KEY))


def _cached_shots(ep, ctx) -> list[dict]:
    """每镜 _shot_summary 走按镜缓存（签名含本镜 + 前后镜 + 本集加强 + 全局）；任务字段每次现算"""
    g = _cache_global_sig(ctx)
    ep_sig = SCACHE._mt(episode_edit_path(ep.number))
    ids = [s.id for s in ep.shots]
    own = {sid: SCACHE.ShotCache.shot_sig(P.shot_dir(sid), RD.shot_gpu3_dir(sid, ctx.slug)) for sid in ids}

    def near(sid: str):
        try:
            nx = P.next_shot_id(_script, sid)
        except Exception:  # noqa: BLE001
            nx = None
        out = [own.get(nx) if nx in own else (SCACHE.ShotCache.shot_sig(P.shot_dir(nx), RD.shot_gpu3_dir(nx, ctx.slug)) if nx else None)]
        i = ids.index(sid)
        out.append(own[ids[i - 1]] if i > 0 else None)
        return tuple(out)

    shots = []
    for s in ep.shots:
        sig = (g, ep_sig, own[s.id], near(s.id))
        ctx.__dict__.setdefault("_sigs", {})[s.id] = sig
        v = _shot_cache.get(s.id, sig, lambda s=s: _shot_summary(ep, s, ctx), lambda s=s: _shot_summary(ep, s, Ctx()))
        ctx.__dict__.setdefault("_base_objs", []).append(v)   # HTTP 出口按“同一批缓存对象”复用已编码的字节
        pending = [j for j in _jobs.values() if j.get("shot_id") == s.id and j["state"] in ("queued", "running")]
        shots.append({**v, "job": pending[0]["state"] if pending else None,
                      "job_stage": pending[0]["stage"] if pending else None,
                      "queue_pos": _queue_pos(pending[0]["id"]) if pending else None})
    _shot_cache.kick()
    return shots


def _episode_payload(ep, ctx) -> dict:
    """一集的完整数据（旧 /api/episodes 每一项；/api/episodes/{n} 也用它，逐字相同）"""
    shots = _cached_shots(ep, ctx)
    return {"number": ep.number, "title": ep.title, "high_intensity": ep.high_intensity, "tag": ep.tag,
            "synopsis": ep.synopsis, "edit": ctx.ep_edit(ep.number),
            "music": episode_music(ep, ctx.ep_edit(ep.number)), "audio_supported": audio_supported(),
            "music_raw": getattr(ep, "music", "") or "", "music_bgm": getattr(ep, "music_bgm", "") or "",  # U4
            "readiness": _episode_readiness(ep, shots, ctx),
            "explicit_hold_count": sum(1 for x in shots if x.get("explicit_hold")), "shots": shots}


@app.get("/api/episodes")
def episodes_http():
    """HTTP 出口：内容 = episodes()（集摘要后台重算也直接调 episodes()）。
    DATAALIGN（P1）：每镜都命中同一批缓存对象、集层字段和任务字段都没变 → 直接复用上次编码好的字节（2.5 MB 编码约 0.1–0.4 s）。
    单飞：并发请求排队，前一个算完 / 编码完，后面的直接拿缓存字节（重启后并发冷请求曾 10 / 18 / 6 s）"""
    if not _WARM["done"] and not _EPISODES_BYTES.get("v"):
        # P2：启动预热还没完成 → 上次完好结果的磁盘快照（剧本没变才用；响应头标快照时间），不排队等现算
        snap = API_SNAP.load(P.DATA, "episodes", P.SCRIPT_JSON)
        if snap:
            return Response(content=snap[0], media_type="application/json", headers={"x-ns-snapshot": str(int(snap[1]))})
    with _EPISODES_LOCK:
        return _episodes_http()


_EPISODES_LOCK = threading.Lock()
_WARM = {"done": False}


def _episodes_http():
    ctx = Ctx()
    data = [_episode_payload(ep, ctx) for ep in _script.episodes]
    objs = ctx.__dict__.get("_base_objs", [])
    key = (json.dumps([{k: v for k, v in e.items() if k != "shots"} for e in data], ensure_ascii=False, default=str),
           tuple((x.get("job"), x.get("job_stage"), x.get("queue_pos")) for e in data for x in e["shots"]))
    hit = _EPISODES_BYTES.get("v")       # (objs, key, bytes)：objs 持有引用，按 is 比较（不用 id，防止地址复用）
    if hit and hit[1] == key and len(hit[0]) == len(objs) and all(a is b for a, b in zip(hit[0], objs)):
        return Response(content=hit[2], media_type="application/json")
    r = _fast_json(data)
    _EPISODES_BYTES["v"] = (objs, key, r.body)
    API_SNAP.save(P.DATA, "episodes", r.body, P.SCRIPT_JSON)     # 下次重启预热期间用
    _dump_shot_cache()
    return r


def _code_key() -> tuple:
    """本进程加载的代码版本：services/ 与 packages/ 下 .py 的 (文件数, 最大 mtime)。换了代码重启 → 磁盘快照里的按镜摘要全部作废重算"""
    root = Path(P.ROOT)
    n, mx = 0, 0
    for base in ("services", "packages"):
        for dp, _dn, fn in os.walk(root / base):
            if "__pycache__" in dp:
                continue
            for f in fn:
                if f.endswith(".py"):
                    n += 1
                    try:
                        mx = max(mx, os.stat(os.path.join(dp, f)).st_mtime_ns)
                    except OSError:
                        pass
    return (n, mx)


_CODE_KEY = _code_key()
_SHOT_DUMP = {"at": 0.0}
def shot_cache_file() -> Path:
    """按镜缓存快照路径：跟着 P.DATA 走（测试把 P.DATA 换成临时目录时也跟着换；ITERAUDIT 真实数据写保护 11-01）"""
    return P.DATA / "cache" / "api_snapshots" / "shot_cache.pkl"


def _dump_shot_cache():
    """按镜缓存写磁盘（60 s 内最多一次，后台线程）：重启后预热只核签名、不重算（总调度 11-01 P1）。
    测试里（PYTEST_CURRENT_TEST）不写：后台线程会活过测试结束，写到真实 data/"""
    if API_SNAP.in_tests():
        return
    now = time.time()
    if now - _SHOT_DUMP["at"] < 60:
        return
    _SHOT_DUMP["at"] = now
    path = shot_cache_file()
    dpath = path.with_name("shot_detail.pkl")

    def run():
        _shot_cache.dump(path)
        _shot_detail_cache.dump(dpath)        # 镜头详情也写盘：重启后画布一次拉全部详情不再整轮现算
    threading.Thread(target=run, name="shot-cache-dump", daemon=True).start()


_EPISODES_BYTES: dict = {}


def episodes():
    """全部集完整数据（旧接口，保留兼容；画布首屏改用 /api/episodes/summary + /api/episodes/{n}）"""
    ctx = Ctx()
    return [_episode_payload(ep, ctx) for ep in _script.episodes]


def _fast_json(data) -> Response:
    """DATAALIGN（P1）：跳过 jsonable_encoder（2.5 MB 约 0.7 s）；数据本身全是 JSON 原生类型，
    输出与 FastAPI JSONResponse 逐字节相同（ensure_ascii=False、紧凑分隔符，已核对）"""
    return Response(content=json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                    media_type="application/json")


def _summary_build():
    """集摘要重算：先记下这一代的逐镜输入签名（请求时签名变了 → 同步重算，见 episodes_summary）"""
    sig = _summary_inputs_sig()
    data = episodes()
    _SUMMARY_SIG["built"] = sig
    return data


_summary_cache = EF.SummaryCache(_summary_build, ttl_s=60.0)  # 60 s：后台全量重算约 2.6 s CPU，过频会和当前集详情抢 CPU；换剧本时立即失效


_SUMMARY_SIG: dict = {}


def _summary_inputs_sig() -> tuple:
    """集摘要的逐镜输入签名（与按镜缓存同一套：渲染目录 + takes / edits / review + gpu3 镜像 + 本集加强），约 80×9 次 stat"""
    slug = RD.current_slug()
    out = [id(_script)]
    for ep in _script.episodes:
        out.append(SCACHE._mt(episode_edit_path(ep.number)))
        out += [SCACHE.ShotCache.shot_sig(P.shot_dir(s.id), RD.shot_gpu3_dir(s.id, slug)) for s in ep.shots]
    return tuple(out)


@app.get("/api/episodes/summary")
def episodes_summary():
    """T60：集列表 + 每集摘要 + 每镜轻字段（后台缓存，超过 15 s 后台重算；as_of = 这份数据算完的时间）
    DATAALIGN：每镜渲染目录 / gpu3 镜像 / 本集加强的签名变了（出了新版本、设了当前、审过）→ 同步重算再返回，计数不再滞后 60 s"""
    if _SUMMARY_SIG.get("built") is not None and _SUMMARY_SIG["built"] != _summary_inputs_sig():
        _summary_cache.refresh_now()
    data, at = _summary_cache.get()
    if at > 0:   # 现算的一代才写快照（快照装进来的 as_of=0）
        API_SNAP.save(P.DATA, "summary", json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), P.SCRIPT_JSON)
    return {"as_of": at, "build_s": _summary_cache.last_build_s, "episodes": data}


@app.get("/api/episodes/{n}")
def episode_detail_http(n: int):
    """HTTP 出口：内容 = episode_detail(n)，跳过 jsonable_encoder（逐字节相同）"""
    return _fast_json(episode_detail(n))


def episode_detail(n: int):
    """T60：单集完整数据（现算，只算这一集；与 /api/episodes 里这一集逐字相同）"""
    ep = next((e for e in _script.episodes if e.number == n), None)
    if ep is None:
        raise HTTPException(404, f"没有第 {n} 集")
    return _episode_payload(ep, Ctx())


@app.get("/api/explicit-holds")
def explicit_holds():
    """「仅看红标」：全部露骨红标镜头（只列镜号、集、来源；不含镜头文字）"""
    slug = RD.current_slug()
    out = []
    for ep in _script.episodes:
        for s in ep.shots:
            h = EX.hold(s, slug)
            if h:
                out.append({"id": s.id, "episode": ep.number, "index": s.index, **h})
    return {"count": len(out), "label": EX.LABEL, "shots": out}


def _refuse_explicit(s):
    """露骨红标镜头：服务端拒绝一切自动动作（出图 / 重出 / gpu3 重出 / 模型生成建议）"""
    if EX.hold(s, RD.current_slug()):
        raise HTTPException(409, EX.refuse_detail(s.id))


# 封板修复 A-2：/api/readiness、/api/sop/status 全量算 1–5 s → 按输入签名缓存（返回内容不变）。
# 剧本 / 状态表 / 场景表 / 关口记录 / 造型计划 mtime 变了立即重算；其余输入（gpu3 镜像、帧）最多旧 10 s。
_slow_cache = EF.KeyedCache(ttl_s=10.0)


def _inputs_sig(root: Path | None = None) -> tuple:
    root = Path(root or P.ROOT)
    files = (P.DATA / "import" / "script_v2.json", root / "data" / "state_timeline.json", root / "data" / "scenes.json",
             root / SOP.OWNER_GATES, root / "data" / "looks" / "schedule.json")

    def mt(f: Path):
        try:
            return f.stat().st_mtime_ns
        except OSError:
            return None
    return (Ctx().slug, str(root), str(P.DATA), id(_script), tuple(mt(f) for f in files))


@app.get("/api/readiness")
def readiness_report(ep: int | None = None):
    """给其它工具用：每镜 {id, owner, frames_source, readiness}；?ep=N 只看一集"""
    if ep is not None and not any(e.number == ep for e in _script.episodes):
        raise HTTPException(404, "没有这一集")   # 封板修复：与 /api/episodes/{n}、/api/sop/episode/{n} 一致，不返回 200 空表
    return _slow_cache.get(("readiness", ep), _inputs_sig(), lambda: _readiness_report(ep))


def _readiness_report(ep: int | None):
    ctx = Ctx()
    eps = [e for e in _script.episodes if ep is None or e.number == ep]
    res = []
    for e in eps:
        shots = [_shot_summary(e, s, ctx) for s in e.shots]
        res.append({"ep": e.number, "title": e.title, **_episode_readiness(e, shots, ctx),
                    "shots": [{"id": x["id"], "owner": x["owner"], "frames_source": x["frames_source"],
                               "readiness": x["readiness"]} for x in shots]})
    return res


# ---------------------------------------------------------------- SOP 阶段 S1–S5 / 关口 G1–G5（只读，从不替项目方接受）

SOP_ROOT: Path | None = None   # 测试用：覆盖读状态表 / 关口记录的项目根


def _sop_project(slug: str):
    try:
        return PJC.get_project(slug)
    except Exception:
        return None


def _sop_eval(ep_filter: int | None = None):
    """当前画布项目：每镜用画布的就绪闸门（剧本要素 + 首尾帧同链 + 衔接）。ep_filter：只算该集 + 首集（G4 要看首集）"""
    ctx = Ctx()
    proj = _sop_project(ctx.slug)
    if SOP_ROOT is not None:              # 测试：临时项目根
        inp = SOP.Inputs(SOP_ROOT, RD.gpu3_root(ctx.slug))
    else:
        inp = SOP.Inputs(proj.root if proj is not None else P.ROOT, RD.gpu3_root(ctx.slug),
                         proj.orchestrator_dir if proj is not None else None)
    first = _script.episodes[0].number if _script.episodes else None
    rows = []
    for e in _script.episodes:
        if ep_filter is not None and e.number not in (ep_filter, first):
            continue
        # DATAALIGN（UM-0276 / UM-0326 首屏慢）：走按镜缓存（与 /api/episodes 同一份，签名变了才重算），不再每次现算本集 + 首集
        cached = _cached_shots(e, ctx) if SOP_ROOT is None else [_shot_summary(e, s_, ctx) for s_ in e.shots]
        for s, x in zip(e.shots, cached):
            rows.append({"id": s.id, "episode": e.number, "index": s.index, "readiness": x.get("readiness"),
                         "owner": x.get("owner"), "has_first": bool(x.get("first_frame")),
                         "has_last": bool(x.get("last_frame_target")), "has_video": bool(x.get("video")),   # DATAALIGN：当前尾帧 = last_frame_target（last_frame 是视频抽帧）
                         "gpu3_status": (x.get("gpu3") or {}).get("status"),
                         "h3_failed": x.get("h3_failed"), "h3_source": x.get("h3_prompt_source"),
                         "h3_override_stale": x.get("h3_override_stale")})
    name = proj.name if proj is not None else ctx.slug
    return ctx.slug, name, inp, SOP.evaluate(inp, rows, project_owner=RD.project_owner(ctx.slug)[0])


@app.get("/api/sop/status")
def sop_status():
    """每个项目：当前阶段、G1–G5 通过/阻塞（原因 + 谁来做：owner|gpu3|laptop）、待项目方决定的事（附命令）。
    只读：没有任何替项目方接受关口的接口。当前画布项目全量计算；其它登记项目只看它自己的状态表 + gpu3 镜像。"""
    if SOP_ROOT is not None:              # 测试临时根：不缓存
        return _sop_status()
    proj = _sop_project(Ctx().slug)
    return _slow_cache.get(("sop_status",), _inputs_sig(proj.root if proj is not None else None), _sop_status)


def _sop_status():
    slug, name, inp, ev = _sop_eval()
    projects = [SOP.project_summary(slug, name, ev, inp)]
    try:
        others = [c for c in PJC.list_projects() if c.slug != slug]
    except Exception:
        others = []
    for c in others:
        oi = SOP.Inputs(c.root, RD.gpu3_root(c.slug), c.orchestrator_dir)
        rows = []
        for s in (oi.timeline or {}).get("shots") or []:
            if not s.get("shot_id"):
                continue
            ch = RD.gpu3_chain(s["shot_id"], c.slug)
            rows.append({"id": s["shot_id"], "episode": int(s.get("episode") or 0), "index": int(s.get("index") or 0),
                         "has_first": bool(ch["first_frame"]), "has_last": bool(ch["last_frame"]),
                         "has_video": bool(ch["video"]), "gpu3_status": ch.get("status")})
        ev2 = SOP.evaluate(oi, rows, project_owner=RD.project_owner(c.slug)[0])
        projects.append({**SOP.project_summary(c.slug, c.name, ev2, oi),
                         "partial": "未在画布打开：只按状态表和 gpu3 镜像判断，剧本要素未检查"})
    return {"current": slug, "projects": projects, "stages": [{"id": k, "label": v} for k, v in SOP.STAGES],
            "actors": SOP.ACTOR_LABEL}


@app.get("/api/sop/episode/{n}")
def sop_episode(n: int):
    """本集每镜：所处阶段（第一个没过的出口闸门）+ 阻塞项（谁来做、项目方的命令）；本集阶段与汇总"""
    if not any(e.number == n for e in _script.episodes):
        raise HTTPException(404, "没有这一集")
    slug, _, inp, ev = _sop_eval(n)
    e = ev["episodes"][n]
    acts = [a for a in ev["owner_actions"]
            if a["gate"] in ("G3", "G4", "plate", "source_drift") or n in (a.get("episodes") or []) or a.get("episode") == n]
    acts = [{**a, "cli": SOP.cli_look(str(n), a["character"])} if a["gate"] == "look" else a
            for a in acts]                  # 本集视角：造型只确认本集（cli_all 仍是全部未确认的集）
    return {"project": slug, **e,
            "stages": [{"id": k, "label": v, "shots_here": e["counts"][k]} for k, v in SOP.STAGES],
            "gates": ev["gates"], "s1": ev["s1"], "owner_actions": acts,
            "shots": [s for s in ev["shots"] if s["episode"] == n]}



@app.post("/api/sop/owner-decision")
def sop_owner_decision(body: OG.OwnerDecision):
    """fredw-92/UXF1：项目方在画布「待你决定」确认框里亲自拍板（造型确认 / G3 / G4 / G5 / 底板）。
    必须 by="owner" + 非空原话；记录逻辑与命令行同一份（ns_api.owner_gates）。agent 不得调用。"""
    _require_owner(body.by, body.quote, "项目方决定")
    if body.gate not in OG.GATES:
        raise HTTPException(400, f"gate 只能是 {'、'.join(OG.GATES)}")
    proj = _sop_project(Ctx().slug)
    root = SOP_ROOT if SOP_ROOT is not None else (proj.root if proj is not None else P.ROOT)
    from ns_api.looks import get_store as _look_store
    out = OG.decide(body, root=Path(root), gpu3_root=RD.gpu3_root(Ctx().slug), look_store=_look_store())
    OG.log(Path(root), body, out)
    _summary_cache.invalidate()
    return {"ok": True, **out}


def _compile_for_display(ep, s, edit):
    """画布显示用的编译结果：与渲染路径（pipeline.compile_with_edits）一致地带上导演加强、环境声、配乐，
    但不写 compiled.json、不需要 LoRA 列表。"""
    from ns_agent.compiler import boost_text
    ee = P.load_episode_edit(ep.number)
    c = compile_shot(ep, s, _script.globals, set(),
                     boost_first=boost_text(ee.boost_first, edit.boost_first),
                     boost_last=boost_text(ee.boost_last, edit.boost_last),
                     soundscape=edit.soundscape, music=edit.music, episode_music=ee.music)
    return P.apply_edit(c, edit)

_shot_detail_cache = SCACHE.ShotCache()
_DETAIL_FILES = ("errors.json", "compiled.json", "visual_spec.json")


@app.get("/api/shots/{shot_id}")
def shot(shot_id: str):
    """DATAALIGN（总调度 P1：整体卡 15–17 s）：镜头详情按镜缓存。复现：80 个 /api/shots 并发 → 18.9 s 才全回来，
    期间最轻的 /api/comfy-lock 也排到 6.8 s（同步线程池 40 个名额全被详情占住、GIL 串行）。
    签名 = 与 /api/episodes 同一套按镜签名 + 本镜 errors / compiled / visual_spec 文件；摘要（含任务字段）每次取最新"""
    ep, s = _find(shot_id)
    ctx = Ctx()
    summary = next((x for x in _cached_shots(ep, ctx) if x["id"] == s.id), None)
    sig = (ctx.__dict__.get("_sigs") or {}).get(s.id)
    if summary is None or sig is None:
        return _shot_detail(shot_id)
    sig = (sig, tuple(SCACHE._mt(P.shot_dir(shot_id) / f) for f in _DETAIL_FILES))
    v = _shot_detail_cache.get(shot_id, sig, lambda: _shot_detail(shot_id, summary), lambda: _shot_detail(shot_id))
    _shot_detail_cache.kick()
    return {**v, "summary": summary}


def _shot_detail(shot_id: str, summary: dict | None = None):
    ep, s = _find(shot_id)
    edit = P.load_edit(shot_id)
    compiled = _compile_for_display(ep, s, edit)
    takes = P.load_takes(shot_id)
    act = _active(shot_id, takes)
    ctx = Ctx()
    ep_edit = ctx.ep_edit(ep.number)
    # DATAALIGN（UIAUDIT r14g 首屏慢）：摘要走按镜缓存（与 /api/episodes 同一份、同一签名），不再每次现算全部版本的过期判定
    if summary is None:
        summary = next((x for x in _cached_shots(ep, ctx) if x["id"] == s.id), None) or _shot_summary(ep, s, ctx)
    last_prompt = summary["last_prompt"]
    for t in takes["takes"]:
        t["url"] = _url(t["file"])
        t["last_url"] = _url(t.get("last_frame"))
        t["raw_url"] = _url(t.get("raw_file"))
        t["bad"] = P.bad_reason(t)   # fredw-92/UXF1：坏图角标
        t["stale"], t["stale_global"] = _stale_split(shot_id, t, s, compiled, edit, act, summary["look_hash"],
                                                     last_prompt, ep_edit)
        t["stale_deps"] = _dep_stale(shot_id, t, t["stale"], ctx.rev_ledger())
    boost = summary["boost"]

    def landed(text: str | None, prompt: str):
        return None if not text else text in prompt

    return {
        "summary": summary,
        # DATAALIGN（PW-011）：当前帧一处说清——与集摘要 / /api/progress 同一口径（summary.first_frame / last_frame_target / video）
        "frames": {"first": summary.get("first_frame"), "first_take": summary.get("first_frame_take"),
                   "last": summary.get("last_frame_target"), "last_take": summary.get("last_frame_take"),
                   "last_source": summary.get("last_frame_source"), "video": summary.get("video"),
                   "video_tail": summary.get("last_frame_actual")},
        "episode": {"number": ep.number, "title": ep.title, "synopsis": ep.synopsis, "edit": ep_edit},
        "script": s.model_dump(),
        # video_negative 不再显示（H3 cfg 1 没有负向分支；数据里仍保留）；video_prompt = 画布显示的 H3 提示词
        "compiled": {**{k: getattr(compiled, k) for k in (
            "image_prompt", "image_negative", "adult", "adult_reasons", "dropped_triggers", "legacy_video_prompt",
            "h3_prompt_source", "h3_frames", "h3_missing")},
            "video_prompt": summary["h3_prompt"], "laptop_h3_prompt": compiled.video_prompt},
        "compiled_last": {"last_prompt": last_prompt, "source": summary["last_prompt_source"],
                          "compiler_has_last_prompt": hasattr(compiled, "last_prompt")},
        # 渲染器最近一次写的 compiled.json（含 image_body / end_state / boost_* / visual_spec）与 visual_spec.json
        "compiled_file": P._read_json(P.shot_dir(shot_id) / "compiled.json", None),
        "visual_spec": P._read_json(P.shot_dir(shot_id) / "visual_spec.json", None)
        or (P._read_json(P.shot_dir(shot_id) / "compiled.json", {}) or {}).get("visual_spec"),
        # 导演加强最终落点：assembled_* 是渲染器拼好的提示词（apply_edit 之后）；*_landed=False 表示
        # 渲染器还没把这段加强写进提示词（等 render_router 接入）
        "assembled": {
            "first": compiled.image_prompt, "last": last_prompt,
            "first_landed": landed(boost["first"], compiled.image_prompt),
            "first_episode_landed": landed(boost["episode_first"], compiled.image_prompt),
            "last_landed": landed(boost["last"], last_prompt),
            "last_episode_landed": landed(boost["episode_last"], last_prompt),
        },
        "edit": edit.model_dump(),
        "last_frame_target": _url(edit.last_frame) if edit.last_frame and edit.last_frame != "next" else edit.last_frame,
        "takes": takes,
        # T21：gpu3 负责 / 有 gpu3 链的镜头（与摘要的 frames 取链规则一致），全屏查看器用 gpu3 的版本链（只读）
        "gpu3_takes": (RD.gpu3_takes(shot_id, ctx.slug)
                       if summary.get("owner") == "gpu3" or (summary.get("gpu3") or {}).get("present") else None),
        "next_shot": P.next_shot_id(_script, shot_id),
        "error": P._read_json(P.shot_dir(shot_id) / "errors.json", None),
    }


# ---------------------------------------------------------------- 写：镜头 / 本集

@app.put("/api/shots/{shot_id}/edit")
def put_edit(shot_id: str, edit: ShotEdit):
    _find(shot_id)
    clean = ShotEdit.model_validate({k: (v.strip() or None) if isinstance(v, str) and k != "note" else v
                                     for k, v in edit.model_dump().items()})
    with P.shot_lock(shot_id):   # 封板修复：读-改-写 edits.json 期间不让同镜其它写入插进来
        # H3 项目方覆盖只能经 /h3-override 写：这里一律沿用已存的值（普通保存既不能改、也不会清掉）
        old = P.load_edit(shot_id)
        for k in P.H3_OVERRIDE_FIELDS:
            setattr(clean, k, getattr(old, k))
        clean.ref_overrides = old.ref_overrides   # W5：参考覆盖只经 /refs/apply 写（同时更新 ref_overrides.json 索引）
        clean.h3_body = None                      # 已停用字段
        saved = P.save_edit(shot_id, clean)
    _summary_cache.invalidate()   # 封板修复：写入后集摘要立即重算
    return saved.model_dump()


class H3OverrideBody(BaseModel):
    body: str | None = None          # 新的 integrated_multimodal_description（不含也可，“[Shot 1] ”自动补）
    soundscape: str | None = None    # 新的 overall_soundscape
    note: str = ""                   # 项目方确认原话（必填；只留在笔记本这份，桥的请求体没有 note）
    by: str = ""                     # 必须是 "owner"
    base_sha: str | None = None      # 画布当时显示的提示词 sha256（= gpu3 effective_sha256）；gpu3 用它判过期（409）
    clear: bool = False              # True = 撤销覆盖（只在笔记本；gpu3 桥暂无撤销接口）


def _require_owner(by: str, quote: str, what: str):
    if by != "owner":
        raise HTTPException(403, f"{what}只接受项目方本人（by=owner）；agent 不得调用")
    if not (quote or "").strip():
        raise HTTPException(400, f"{what}必须填写项目方原话")


def _h3_compose(ep, s, edit: ShotEdit, body: str | None, soundscape: str | None):
    """项目方修改：起点 = 未过期的已有覆盖 > 剧本 / 笔记本草稿；→ (文本, 起点编译结果)"""
    compiled = _compile_for_display(ep, s, ShotEdit())          # 不含旧覆盖
    oi = H3V.override_info(s, edit)
    base = edit.h3_prompt_override.text if oi and not oi["stale"] else compiled.video_prompt
    try:
        return H3V.compose_override(base, body, soundscape), compiled
    except ValueError as e:
        raise HTTPException(409, str(e))


def _delivery(fn) -> Delivery:
    try:
        return Delivery(ok=True, at=P.now(), code=200, response=fn())
    except GB.BridgeError as e:
        return Delivery(ok=False, at=P.now(), code=e.code, error=str(e),
                        response=e.body if isinstance(e.body, dict) else None)


class H3LintBody(BaseModel):
    body: str | None = None
    soundscape: str | None = None


@app.post("/api/shots/{shot_id}/h3-lint")
def h3_lint_preview(shot_id: str, req: H3LintBody):
    """只读：项目方在 H3 面板里边写边检（不保存、不送 gpu3）"""
    from ns_schema.h3_lint import failed_rules, lint_ok
    ep, s = _find(shot_id)
    text, compiled = _h3_compose(ep, s, P.load_edit(shot_id), req.body, req.soundscape)
    res = H3V.lint(text, s, compiled.h3_frames, compiled.adult)
    return {"text": text, "sha256": H3V.sha256_text(text), "lint": res, "ok": lint_ok(res), "failed": failed_rules(res)}


@app.put("/api/shots/{shot_id}/h3-override")
def put_h3_override(shot_id: str, req: H3OverrideBody):
    """项目方修改 H3 提示词（SOP §9A；只能改正文与环境声，对齐句与 non_diegetic_music: N/A 固定）。

    仅供项目方在画布「H3 提示词」面板里亲自操作：必须 by="owner" 且带非空确认原话 note。
    **Agent / 自动化脚本一律不得调用本接口**（包括代项目方填写 note）。
    存进本地 edits.json h3_prompt_override {text, by, at, base_sha, note, …}，并经 gpu3 桥 POST …/h3_edit
    （{text, by:"owner", base_sha}）写到 gpu3；gpu3 自行记 S1-W9 豁免并重新审计。桥不可达 / 拒绝 → delivery.ok=False，
    画布显示「未送达 gpu3」+ 重试（POST /api/shots/{id}/gpu3-resend）；409 = gpu3 侧提示词已变（stale），刷新后重改。
    笔记本 lint_h3 不通过 → status=draft（S4 继续阻塞）。剧本 **H3提示词** 之后变了 → stale，SOP「待你决定」提示重新确认。"""
    from ns_schema.h3_lint import failed_rules
    _require_owner(req.by, req.note, "H3 提示词修改")
    try:
        with P.shot_lock(shot_id):   # 封板修复：读-改-写 edits.json 期间不让同镜其它写入插进来
            ep, s = _find(shot_id)
            edit = P.load_edit(shot_id)
            if req.clear:
                edit.h3_prompt_override = None
                edit.note = (edit.note + f"\n[H3 覆盖撤销 {P.now()}] {req.note.strip()}").strip()
                return {"edit": P.save_edit(shot_id, edit).model_dump(), "lint": None, "delivered": None,
                        "warning": "只在笔记本撤销：gpu3 桥还没有撤销接口，gpu3 侧 edits.json 仍保留上次的修改"}
            if not (req.body or "").strip() and not (req.soundscape or "").strip():
                raise HTTPException(400, "没有要修改的正文或环境声")
            text, compiled = _h3_compose(ep, s, edit, req.body, req.soundscape)
            res = H3V.lint(text, s, compiled.h3_frames, compiled.adult)
            failed = failed_rules(res)
            ov = H3PromptOverride(text=text, by="owner", at=P.now(), base_sha=req.base_sha, script_sha=H3V.script_sha(s),
                                  note=req.note.strip(), status="draft" if failed else "renderable", failed=failed)
            ov.delivery = _delivery(lambda: GB.post_h3_edit(RD.current_slug(), shot_id, text, req.base_sha))
            edit.h3_prompt_override = ov
            saved = P.save_edit(shot_id, edit)
            return {"edit": saved.model_dump(), "lint": res, "status": ov.status, "failed": failed,
                    "delivered": ov.delivery.ok, "delivery": ov.delivery.model_dump()}
    finally:
        _summary_cache.invalidate()   # 封板修复：写入后集摘要立即重算


class AuditOverrideBody(BaseModel):
    rule_id: str
    owner_quote: str = ""
    by: str = ""


@app.put("/api/shots/{shot_id}/audit-override")
def put_audit_override(shot_id: str, req: AuditOverrideBody):
    """项目方对 gpu3 审计某条规则的豁免请求（须原话）。**仅项目方在画布上操作；agent 不得调用。**
    存进本地 edits.json audit_override_requests[]，并经桥 POST …/override（{rule_id, owner_quote, by:"owner"}）；
    gpu3 把有效的并入 status.json audit.overrides、无效的进 audit.invalid_overrides。我们从不写 gpu3 的 status.json。"""
    _require_owner(req.by, req.owner_quote, "审计豁免")
    _find(shot_id)
    rid = req.rule_id.strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9]*-[A-Z]+\d+", rid):
        raise HTTPException(422, f"rule_id 格式不对：{rid}")
    edit = P.load_edit(shot_id)
    r = AuditOverrideRequest(rule_id=rid, owner_quote=req.owner_quote.strip(), by="owner", at=P.now())
    r.delivery = _delivery(lambda: GB.post_override(RD.current_slug(), shot_id, rid, r.owner_quote))
    edit.audit_override_requests = [x for x in edit.audit_override_requests if x.rule_id != rid] + [r]
    P.save_edit(shot_id, edit)
    return {"request": r.model_dump(), "delivered": r.delivery.ok}


class ResendBody(BaseModel):
    what: str                        # h3_edit | override
    rule_id: str | None = None       # what=override 时：重发哪一条
    by: str = ""


@app.post("/api/shots/{shot_id}/gpu3-resend")
def gpu3_resend(shot_id: str, req: ResendBody):
    """「未送达 gpu3」的重试：原样重发已由项目方确认、存在本地 edits.json 的内容（不改内容）。仅项目方点按钮触发。"""
    if req.by != "owner":
        raise HTTPException(403, "重发只接受项目方本人（by=owner）")
    _find(shot_id)
    edit = P.load_edit(shot_id)
    slug = RD.current_slug()
    if req.what == "h3_edit":
        ov = edit.h3_prompt_override
        if not ov:
            raise HTTPException(404, "本镜没有 H3 修改")
        ov.delivery = _delivery(lambda: GB.post_h3_edit(slug, shot_id, ov.text, ov.base_sha))
        d = ov.delivery
    elif req.what == "override":
        r = next((x for x in edit.audit_override_requests if x.rule_id == req.rule_id), None)
        if not r:
            raise HTTPException(404, "没有这条豁免请求")
        r.delivery = _delivery(lambda: GB.post_override(slug, shot_id, r.rule_id, r.owner_quote))
        d = r.delivery
    else:
        raise HTTPException(400, "what 只能是 h3_edit 或 override")
    P.save_edit(shot_id, edit)
    return {"delivered": d.ok, "delivery": d.model_dump()}


@app.get("/api/shots/{shot_id}/gpu3-state")
def gpu3_state(shot_id: str):
    """只读：经桥取 gpu3 实时 ShotRenders（audit / h3 / shot_state / video_gate）；video_gate.video_ok 是「出视频」的权威"""
    _find(shot_id)
    try:
        return {"reachable": True, "shot": GB.get_shot(RD.current_slug(), shot_id)}
    except GB.BridgeError as e:
        return {"reachable": False, "error": str(e), "code": e.code}


def _video_ok(shot_id: str) -> tuple[bool, str, bool]:
    """出视频闸门：以 gpu3 桥 video_gate.video_ok 为准；桥不可达则拒绝（不静默放行）。→ (通过, 原因, 桥可达)"""
    try:
        g = (GB.get_shot(RD.current_slug(), shot_id) or {}).get("video_gate") or {}
    except GB.BridgeError as e:
        return False, f"无法确认 gpu3 出视频闸门：{e}", e.code is not None
    if g.get("video_ok") is True:
        return True, "", True
    return False, (f"gpu3 出视频闸门未通过：verdict={g.get('verdict')!r}，prompt_sha={g.get('prompt_sha')}，"
                   f"effective_sha256={g.get('effective_sha256')}" + ("，blocked" if g.get("blocked") else "")), True


@app.get("/api/rules/{rule_id}/explain")
def rule_explain(rule_id: str):
    """规则说明（画布规则号弹窗）：先问 gpu3 桥 GET /api/gpu3/rules/{id}（shot_audit.py --explain，原样）；
    桥不可达 / 5xx 时用本地 docs/audit/rule_ids.md + SOP_production.md 拼（source=local）。只读，不在本机起子进程。"""
    from ns_api import docs as DOCS
    if not re.fullmatch(r"[A-Z][A-Z0-9]*-[A-Z]+\d+", rule_id):
        raise HTTPException(404, "不是合法的 rule_id")
    links = {"rule_href": H3V.rule_href(rule_id)}
    try:
        out = GB.get_rule(rule_id)
        return {**out, **links, "sop_href": H3V.sop_href(out.get("sop_ref")), "source": "gpu3"}
    except GB.BridgeError as e:
        if e.code == 404:
            raise HTTPException(404, f"规则表里没有 {rule_id}")
        bridge_err = str(e)
    out = DOCS.explain_local(P.ROOT, rule_id)
    if out is None:
        raise HTTPException(404, f"规则表里没有 {rule_id}")
    return {**out, **links, "sop_href": H3V.sop_href(out.get("sop_ref")), "source": "local", "bridge_error": bridge_err}


@app.get("/api/docs/{name}")
def docs_page(name: str):
    """只读文档（规则号 / SOP 出处链接的目标）：rule_ids、SOP_production、SOP_parameters；锚点 #<rule_id>、#sec-<小节号>"""
    from fastapi.responses import HTMLResponse
    from ns_api import docs as DOCS
    out = DOCS.page(P.ROOT, name)
    if out is None:
        raise HTTPException(404, f"只提供 {sorted(DOCS.DOCS)}")
    return HTMLResponse(out)


@app.get("/api/episodes/{n}/edit")
def get_episode_edit(n: int):
    if not any(ep.number == n for ep in _script.episodes):
        raise HTTPException(404, "没有这一集")
    return load_episode_edit(n)


@app.put("/api/episodes/{n}/edit")
def put_episode_edit(n: int, body: EpisodeEditBody):
    """本集导演加强：作用于本集全部镜头。保存后，晚于它的首帧 / 尾帧版本不变，早于它的标「本集加强已改」"""
    if not any(ep.number == n for ep in _script.episodes):
        raise HTTPException(404, "没有这一集")
    return save_episode_edit(n, body)


@app.post("/api/shots/{shot_id}/last-frame")
async def upload_last_frame(shot_id: str, file: UploadFile = File(...)):
    _find(shot_id)
    suffix = Path(file.filename or "x.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):   # 封板修复 P1：曾可上传 .html，经 /files 同源执行
        raise HTTPException(422, "只接受 png / jpg / webp")
    rel = f"uploads/{shot_id}/last_{int(time.time())}{suffix}"
    (P.DATA / rel).parent.mkdir(parents=True, exist_ok=True)
    (P.DATA / rel).write_bytes(await file.read())
    with P.shot_lock(shot_id):   # 封板修复：读-改-写 edits.json 加每镜锁
        edit = P.load_edit(shot_id)
        edit.last_frame = rel
        edit.last_source = "upload"
        P.save_edit(shot_id, edit)
    _summary_cache.invalidate()   # 封板修复：写入后集摘要立即重算
    return {"last_frame": rel, "url": _url(rel)}


@app.post("/api/shots/{shot_id}/first-frame")
async def upload_first_frame(shot_id: str, file: UploadFile = File(...)):
    """上传首帧：记为一个 image 版本（workflow=upload）并设为当前"""
    _find(shot_id)
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(422, "只接受 png / jpg / webp")
    raw = await file.read()
    # 封板修复：取号 + 写文件 + 记版本在同一把每镜锁里，并发上传 / 渲染线程不会拿到同一个 n
    with P.shot_lock(shot_id):
        n = P._next_n(shot_id, "image")
        rel = f"renders/{P.shot_dir(shot_id).relative_to(P.RENDERS).as_posix()}/takes/image_{n:03d}_upload{suffix}"
        (P.DATA / rel).parent.mkdir(parents=True, exist_ok=True)
        (P.DATA / rel).write_bytes(raw)
        take = Take(n=n, stage="image", file=rel, seed=0, prompt="", created_at=P.now(), workflow="upload",
                    source="upload")
        P._add_take(shot_id, take)
    _summary_cache.invalidate()   # 封板修复：写入后集摘要立即重算
    return {"n": n, "url": _url(rel)}


# ---------------------------------------------------------------- 导演加强：用项目方自己的模型给建议

class BoostSuggest(BaseModel):
    which: str = "first"            # first | last
    llm: dict | None = None         # 每处 ⚙ 覆盖 {provider?, model?, params?}（契约 §A）


DEFAULT_RULES_FILE = "config/director_boost_rules.md"
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _local_config_path() -> Path:
    return BOOST_LLM_CONFIG.with_name(BOOST_LLM_CONFIG.stem + ".local.json")


def _legacy_boost_config() -> dict:
    cfg: dict = {}
    for path in (BOOST_LLM_CONFIG, _local_config_path()):
        if path.exists():
            try:
                cfg.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError as e:
                raise HTTPException(400, f"{path.name} 不是合法 JSON：{e.msg}")
    return cfg


def load_boost_config(override: dict | None = None) -> dict:
    """2026-10-30 夜 W1：模型来自统一配置 config/llm_providers.json 的用途 director_boost（+ 本次 llm 覆盖）；
    config/director_boost_llm.json 只管 instruction_file。迁移期读兼容：旧文件（含 .local.json）里写了 base_url 的，
    整组 base_url / model / api_key 覆盖统一配置（本次有 llm 覆盖时不用旧文件）；api_key 缺时可来自环境变量
    NS_BOOST_API_KEY。密钥只用于请求头，从不返回、不记日志。"""
    legacy = _legacy_boost_config()
    cfg: dict = {"instruction_file": legacy.get("instruction_file")}
    try:
        rv = LLMC.resolve("director_boost", override)
        cfg.update(provider=rv["id"], base_url=rv["base_url"], model=rv["model"], api_key=rv["api_key"],
                   timeout_s=rv["timeout_s"])
    except LLMC.LLMConfigError as e:
        cfg["config_error"] = str(e)
    if not override and str(legacy.get("base_url") or "").strip():
        cfg.update(provider="legacy", base_url=legacy["base_url"], model=legacy.get("model") or "",
                   api_key=legacy.get("api_key"), timeout_s=legacy.get("timeout_s") or cfg.get("timeout_s"))
    if not cfg.get("api_key") and os.environ.get("NS_BOOST_API_KEY"):
        cfg["api_key"] = os.environ["NS_BOOST_API_KEY"]
    return cfg


def _rules_path(cfg: dict) -> Path:
    ins = Path(str(cfg.get("instruction_file") or DEFAULT_RULES_FILE))
    return ins if ins.is_absolute() else P.ROOT / ins


def rules_text(cfg: dict) -> str:
    """指令文件去掉 <!-- 注释 --> 后的内容；空 = 项目方还没写规则"""
    p = _rules_path(cfg)
    return COMMENT_RE.sub("", p.read_text(encoding="utf-8")).strip() if p.is_file() else ""


def _boost_llm_config(override: dict | None = None) -> tuple[dict, str]:
    hint = ("在「模型与 API」页给用途“导演加强”选服务商和模型（config/llm_providers.json 的 purposes.director_boost），"
            "密钥在同页填写（只存 config/llm_providers.local.json）")
    cfg = load_boost_config(override)
    if cfg.get("config_error") and not cfg.get("base_url"):
        raise HTTPException(400, f"导演加强模型配置有误：{cfg['config_error']}。{hint}")
    missing = [k for k in ("base_url", "model") if not str(cfg.get(k) or "").strip()]
    if missing:
        raise HTTPException(400, f"配置缺少 {'、'.join(missing)}。{hint}")
    text = rules_text(cfg)
    if not text:
        name = cfg.get("instruction_file") or DEFAULT_RULES_FILE
        raise HTTPException(400, f"指令文件 {name} 不存在或没有正文（注释不算）。请项目方先写好导演加强规则再用")
    return cfg, text


@app.get("/api/boost/config")
def boost_config_status():
    """设置页用：只报告是否就绪，密钥只显示「已配置 / 未配置」"""
    cfg = load_boost_config()
    return {"provider": cfg.get("provider") or "", "base_url": cfg.get("base_url") or "", "model": cfg.get("model") or "",
            "instruction_file": cfg.get("instruction_file") or DEFAULT_RULES_FILE,
            "api_key": "已配置" if cfg.get("api_key") else "未配置",
            "rules_ready": bool(rules_text(cfg)),
            "ready": bool(cfg.get("base_url") and cfg.get("model") and rules_text(cfg))}


def _shot_material(ep, s, which: str) -> str:
    """只把剧本数据交给模型（不附加任何我们自己的指令文字）"""
    lines = [f"镜头：{s.id}", f"目标：{'首帧' if which == 'first' else '尾帧'}",
             f"集：{ep.number} {ep.title}", f"梗概：{ep.synopsis}"]
    if s.img_note:
        lines.append(f"画面备注：{s.img_note}")
    lines += [f"画面 img：{s.img_prompt}", f"动作 motion：{s.motion_prompt}"]
    if s.sound:
        lines.append(f"音效：{s.sound}")
    for d in s.dialogue:
        lines.append(f"对白：{(d.speaker_note + '：') if d.speaker_note else ''}{d.text}")
    if s.voiceover:
        lines.append(f"旁白：{s.voiceover.text}")
    return "\n".join(lines)


def call_llm(cfg: dict, system: str, user: str) -> str:
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    body = json.dumps({"model": cfg["model"], "messages": [{"role": "system", "content": system},
                                                           {"role": "user", "content": user}]}).encode()
    headers = {"Content-Type": "application/json"}
    key = cfg.get("api_key")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_s") or 120)) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


@app.post("/api/shots/{shot_id}/boost/suggest")
def boost_suggest(shot_id: str, req: BoostSuggest):
    """返回建议文本，只填进输入框，不保存"""
    ep, s = _find(shot_id)
    _refuse_explicit(s)
    if req.which not in ("first", "last"):
        raise HTTPException(422, "which 只能是 first 或 last")
    cfg, instruction = _boost_llm_config(req.llm)
    try:
        text = call_llm(cfg, instruction, _shot_material(ep, s, req.which))
    except (urllib.error.URLError, OSError, KeyError, ValueError, IndexError) as e:
        msg = str(e)
        if cfg.get("api_key"):
            msg = msg.replace(cfg["api_key"], "***")
        raise HTTPException(502, f"调用模型失败：{msg[:300]}")
    return {"which": req.which, "suggestion": text.strip(), "model": cfg["model"]}


# ---------------------------------------------------------------- gpu3 重出 / 媒体代理

class Gpu3RerenderBody(BaseModel):
    stage: str = "both"          # image=首帧（尾帧随首帧重编）/ last=只重出尾帧 / video / both
    note: str = ""
    priority: int = 5            # 2026-10-30 夜：成人内容一律不拦，不再有 by / 项目方确认（旧客户端带 by 会被忽略）


def _adult_shot(ep, s) -> bool:
    """成人镜 / 🔴 集：只用于展示与日志，不再限制任何调用方。"""
    if getattr(ep, "high_intensity", False) or getattr(s, "adult", False):
        return True
    from ns_agent.compiler import classify_adult
    try:
        return bool(classify_adult(ep, s))
    except Exception:            # noqa: BLE001
        return True


@app.post("/api/shots/{shot_id}/gpu3-rerender")
def gpu3_rerender(shot_id: str, body: Gpu3RerenderBody):
    """「请 gpu3 重出」：按 docs/canvas.md §2 发一条 nsfs_canvas.rerender/v1 到桥（桥写 gpu3 上的 rerender_queue.jsonl）。
    契约的 stage 只有 image|video|both：「只重出尾帧」发 image + overrides.last_only=true（保留首帧，由首帧重编尾帧）。"""
    ep, s = _find(shot_id)
    _refuse_explicit(s)
    if body.stage not in RD.GPU3_RERENDER_STAGES:
        raise HTTPException(400, f"stage 只能是 {RD.GPU3_RERENDER_STAGES}")
    if body.stage in ("video", "both"):          # 出视频：gpu3 审计 pass 且审计的就是当前提示词（video_gate.video_ok）
        ok, why, reachable = _video_ok(shot_id)
        if not ok:
            raise HTTPException(409 if reachable else 502,
                                why + ("" if reachable else "。请先开隧道 ssh -N -L 15180:127.0.0.1:5180 gpu33"))
    edit = P.load_edit(shot_id)
    stage = "image" if body.stage == "last" else body.stage
    req = {"schema": "nsfs_canvas.rerender/v1", "op": "render", "project": RD.current_slug(), "shot": shot_id,
           "stage": stage, "keep_seed": False, "edit": edit.model_dump(),
           "overrides": {"last_only": True} if body.stage == "last" else {},
           "priority": body.priority, "requested_by": "owner",
           "note": (body.note or {"image": "重出首帧（尾帧随之重编）", "last": "只重出尾帧（保留首帧）",
                                  "video": "重出视频（保留首尾帧）", "both": "重出首尾帧和视频"}[body.stage])}
    try:
        res = RD.post_rerender(req)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HTTPException(502, f"gpu3 桥不可达（{RD.BRIDGE_URL}）：{e}。请先开隧道 ssh -N -L 15180:127.0.0.1:5180 gpu33")
    errs = res.get("errors") if isinstance(res, dict) else None
    if errs:
        raise HTTPException(422, f"桥拒绝：{errs}")
    reqs = (res.get("requests") if isinstance(res, dict) else None) or []
    rid = (reqs[0] or {}).get("id") if reqs and isinstance(reqs[0], dict) else None
    # request_id = 桥分配的请求 id（画布用它在 GET /api/gpu3/requests 里追踪进度）
    return {"ok": True, "request_id": rid, "request": {**req, "id": rid} if rid else req, "bridge": res}


GPU3_MEDIA_CACHE: Path | None = None   # 测试用：覆盖 data/cache/gpu3_media


@app.get("/api/gpu3-media/{rel:path}")
def gpu3_media(rel: str, request: Request):
    """镜像还没同步的 gpu3 文件：同源代理到桥 /api/gpu3/media/<rel>（Range 透传，视频可拖动）。只读。"""
    # 封板修复：Windows 上反斜杠也是分隔符（renders_gpu3/..\..\config\x 曾能读出仓库任意文件）；冒号挡盘符 / ADS
    if (not rel.startswith("renders_gpu3/") or "\\" in rel or ":" in rel
            or any(p in ("..", ".") for p in rel.split("/"))):
        raise HTTPException(400, "只代理 renders_gpu3/ 下的文件")
    local = P.DATA / rel
    if local.exists():
        return FileResponse(local)
    # takes/ 下是带版本号的文件（不再改写）→ 取过一次就存本地缓存；桥慢（几 MB 要 10–20 s）时不再每次 502
    cacheable = "/takes/" in rel
    cached = (GPU3_MEDIA_CACHE or P.DATA / "cache" / "gpu3_media") / rel
    if cacheable and cached.is_file():
        return FileResponse(cached, headers={"Cache-Control": "max-age=300"})
    try:
        r = RD.fetch_media(rel, request.headers.get("range"))
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, f"gpu3 桥：{e.reason}")
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(502, f"gpu3 桥不可达：{e}")
    keep = ("content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag")
    headers = {k: v for k, v in r.headers.items() if k.lower() in keep}
    headers["Cache-Control"] = "max-age=300"

    save = cacheable and r.status == 200 and not request.headers.get("range")
    want = int(headers.get("content-length") or headers.get("Content-Length") or -1)

    def body():
        fh = tmp = None
        if save:
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                tmp = cached.with_name(f"{cached.name}.{uuid.uuid4().hex[:8]}.part")
                fh = tmp.open("wb")
            except OSError:
                fh = None
        n, done = 0, False
        try:
            with r:
                while chunk := r.read(1 << 16):
                    n += len(chunk)
                    if fh:
                        fh.write(chunk)
                    yield chunk
            done = True
        finally:
            if fh:
                fh.close()
                try:
                    if done and n > 0 and want in (-1, n):
                        os.replace(tmp, cached)
                    else:
                        tmp.unlink(missing_ok=True)
                except OSError:
                    pass
    return StreamingResponse(body(), status_code=r.status, headers=headers)


# ---------------------------------------------------------------- 渲染队列

class RenderRequest(BaseModel):
    stage: str
    seed: int | None = None


def _gpu3_owner_reason(shot_id: str) -> str | None:
    slug = RD.current_slug()
    owner, why = RD.shot_owner(shot_id, slug, RD.gpu3_chain(shot_id, slug))
    return why if owner == "gpu3" else None


@app.post("/api/shots/{shot_id}/render")
def render(shot_id: str, req: RenderRequest):
    _refuse_explicit(_find(shot_id)[1])
    why = _gpu3_owner_reason(shot_id)
    if why:   # 一镜一条链：gpu3 负责的镜头本机不出新版本（避免首帧 / 尾帧 / 视频来自两条链）
        raise HTTPException(409, f"gpu3 负责此镜（避免两条链）：{why}。请用「请 gpu3 重出」")
    if req.stage not in STAGES:
        raise HTTPException(400, f"stage 只能是 {STAGES}")
    if req.stage == "video":
        ok, why, _ = _video_ok(shot_id)
        if not ok:
            raise HTTPException(409, why)
    if req.stage == "last" and not last_supported():
        raise HTTPException(501, "尾帧生成尚未上线（等待 render_router 提供 pipeline.render_last_frame）")
    if req.stage == "last" and not (P.shot_dir(shot_id) / "frame.png").exists():
        raise HTTPException(409, "尾帧以首帧为底图，先出首帧")
    job = {"id": uuid.uuid4().hex[:8], "shot_id": shot_id, "stage": req.stage, "seed": req.seed,
           "state": "queued", "created_at": P.now(), "error": None}
    _jobs[job["id"]] = job
    _queue.put(job["id"])
    return job


@app.post("/api/shots/{shot_id}/takes/{stage}/{n}/activate")
def activate(shot_id: str, stage: str, n: int):
    if stage not in STAGES:
        raise HTTPException(400, f"stage 只能是 {STAGES}")
    try:
        P.set_active(shot_id, stage, n)          # set_active 内部持每镜锁（封板修复）
    except StopIteration:
        raise HTTPException(404, "没有这个版本")
    except ValueError as e:                     # QCRejected
        raise HTTPException(409, str(e))
    _summary_cache.invalidate()   # 封板修复：写入后集摘要立即重算
    return P.load_takes(shot_id)


class ReviewRequest(BaseModel):
    state: str
    reason: str = ""


@app.put("/api/shots/{shot_id}/review")
def put_review(shot_id: str, req: ReviewRequest):
    _find(shot_id)
    if req.state not in REVIEW_STATES:
        raise HTTPException(400, f"state 只能是 {REVIEW_STATES}")
    act = _active(shot_id)
    rec = {"state": req.state, "reason": req.reason, "at": P.now(),
           "takes": {k: (act[k]["n"] if act.get(k) else None) for k in REVIEW_STAGES}}
    P._write_json(P.shot_dir(shot_id) / "review.json", rec)
    _summary_cache.invalidate()   # 封板修复：写入后集摘要立即重算
    return _review(shot_id, act)


class BatchRenderRequest(BaseModel):
    shot_ids: list[str]
    stage: str
    only_missing: bool = False       # 只跑当前没有该阶段版本的镜头


@app.post("/api/render-batch")
def render_batch(req: BatchRenderRequest):
    """逐个入队；某个镜头不存在不影响其它，结果逐条返回"""
    results = []
    for sid in req.shot_ids:
        try:
            if req.only_missing and P.load_takes(sid)["active"].get(req.stage) is not None:
                results.append({"shot_id": sid, "ok": False, "skipped": True, "error": "已有版本（只跑缺失的）"})
                continue
            results.append({"shot_id": sid, "ok": True, "job": render(sid, RenderRequest(stage=req.stage))})
        except (HTTPException, KeyError, ValueError) as e:
            results.append({"shot_id": sid, "ok": False, "error": getattr(e, "detail", str(e))})
    return results


@app.get("/api/jobs")
def jobs():
    # fredw-92/D1：并入 v1 任务队列（frame-jobs / video-jobs / asset gen-jobs）——以前这里只有旧渲染队列，
    # v1 视频在跑时 /api/jobs 仍是 []，按“/api/jobs 空了才重启 API”的运维规则会把正在跑的视频打断。
    # v1 任务另带 v1:true；stage 映射到旧词表（first→image，视频任务无 stage → video）。
    v1 = []
    for j in JOBS.all_jobs():
        st = j.get("stage")
        v1.append({**j, "v1": True, "stage": {"first": "image"}.get(st, st) or (
            "video" if j.get("kind") == "video" else j.get("kind"))})
    allj = list(_jobs.values()) + v1
    return sorted(allj, key=lambda j: str(j.get("created_at") or ""), reverse=True)[:50]


@app.post("/api/assets/characters/{character}/generate")
def generate_asset(character: str, req: A.GenerateRequest):
    """资产出图（E6）：入队到同一个 GPU 串行队列；Qwen Image 2.1 多参考编辑。不会自动登记进衣橱。"""
    cid = A._char(character)
    req = A.validate_generate(cid, req, default_store())
    job = {"id": uuid.uuid4().hex[:8], "shot_id": f"asset:{cid}", "stage": "asset", "seed": req.seed,
           "state": "queued", "created_at": P.now(), "error": None, "character": cid, "request": req.model_dump()}
    _jobs[job["id"]] = job
    _queue.put(job["id"])
    return job


def _record_look_hash(shot_id: str, stage: str, n: int):
    """渲染完成后把本镜造型哈希写进 take（用于「造型已改」过期判定）"""
    try:
        h = default_store().shot_looks(shot_id).look_hash
        with P.shot_lock(shot_id):   # F4：与 frame_edit / 定稿同一把每镜锁（读-改-写 takes.json）
            data = P.load_takes(shot_id)
            for t in data["takes"]:
                if t["stage"] == stage and t["n"] == n:
                    t["look_hash"] = h
            P._write_json(P.shot_dir(shot_id) / "takes.json", data)
    except Exception:
        pass


RENDERERS = {"image": lambda: P.render_image, "video": lambda: P.render_video,
             "last": lambda: getattr(P, "render_last_frame")}


OFFLINE_RETRY_S = 10


def _wait_comfy_online(job: dict):
    """本机 ComfyUI 没开时不让任务直接失败：挂起等待（comfy_wait.who = offline），启动后自动继续。"""
    from ns_orch.executors import comfy_status
    while not (st := comfy_status(COMFY_URL))["reachable"]:
        job["comfy_wait"] = {"who": "offline", "what": f"本机 ComfyUI 未启动（{COMFY_URL}）", "since": job.get(
            "comfy_wait", {}).get("since") or P.now(), "error": st.get("error")}
        time.sleep(OFFLINE_RETRY_S)
    job.pop("comfy_wait", None)


@app.get("/api/render-backend")
def render_backend():
    """出图后端是否可用（画布顶栏用）：ComfyUI 可达性、队列、显存。
    F4：与 /api/render/endpoints 同一个探测、同一个地址（「模型与 API」页的 image 端点 = 出图任务实际用的），
    8 s 超时 + 15 s 缓存（经 SSH 隧道 1.5 s 常超时，两边曾经一个说通一个说不通）"""
    try:
        url = LLMC.render_endpoints()["image"]["url"]
    except Exception:  # noqa: BLE001 — 配置文件坏了按默认出图地址
        url = COMFY_URL
    # GPUVIEW 11-01（PAGEWATCH PW-013：每秒探 9 分钟有 10 次 2–10 s）：经隧道现探 /system_stats 1–5 s，
    # 缓存一过期就卡住请求。展示接口改成“先给上次结果、后台刷新”；从没探过才同步探一次
    hit = RENDER_EP.peek(url)
    if hit is None:
        return RENDER_EP.probe(url)
    age = time.monotonic() - hit[0]
    if age >= RENDER_EP.PROBE_TTL_S:
        with _rb_guard:
            t = _rb_thread.get(url)
            if t is None or not t.is_alive():
                t = _rb_thread[url] = threading.Thread(target=RENDER_EP.probe, args=(url,), daemon=True, name="ns-render-backend-probe")
                t.start()
    return {**hit[1], "cached": True, "age_s": round(age, 1)}


_rb_guard = threading.Lock()
_rb_thread: dict = {}


def _worker():
    client = ComfyClient(COMFY_URL)
    while True:
        job = _jobs[_queue.get()]
        job["state"] = "running"
        job["started_at"] = P.now()
        _wait_comfy_online(job)
        try:
            # T44：等本机 ComfyUI 锁（编排器子进程占用时任务上显示 comfy_wait = 占用者，不换状态以免影响画布）
            lock = CL.acquire("canvas", f"{job['shot_id']} {job['stage']}",
                              on_wait=lambda info, j=job: j.__setitem__("comfy_wait", info or {"who": "unknown"}))
        except Exception as e:  # noqa: BLE001
            job.update(state="failed", error=f"ComfyUI 锁：{e}"[:1000])
            continue
        job.pop("comfy_wait", None)
        try:
            _run_job(client, job)
        except Exception as e:  # noqa: BLE001  不让线程退出
            job.update(state="failed", error=str(e)[:1000])
        finally:
            CL.release(lock)


def _run_job(client, job: dict):
    try:
        if job["stage"] == "asset":
            rec = A.generate_asset(client, job["character"], job["request"])
            job.update(state="done", file=rec["file"])
            return
        if job["stage"] == "image":     # W2：画布出图只出 1 张，不评分 / 不看图判定 / 不否决
            take = FE.regen(client, _script, job["shot_id"], "image", seed=job["seed"])
        elif job["stage"] == "last":
            take = P.render_last_frame(client, _script, job["shot_id"], seed=job["seed"], candidates=1, rounds=1,
                                       score_fn=None, qc_fn=FE.no_qc)
        else:
            take = RENDERERS[job["stage"]]()(client, _script, job["shot_id"], seed=job["seed"])
        take = take if not isinstance(take, dict) else Take.model_validate(take)
        job.update(state="done", take=take.n)
        _record_look_hash(job["shot_id"], job["stage"], take.n)
    except (ComfyError, Exception) as e:  # 任何错误都记到任务上
        job.update(state="failed", error=str(e)[:1000])
        if job["stage"] != "asset":
            P._write_json(P.shot_dir(job["shot_id"]) / "errors.json", {"last": str(e), "at": P.now()})


@app.get("/api/comfy-lock")
def comfy_lock():
    """T44：本机 ComfyUI 锁状态 {free, holder:{who:canvas|orchestrator, what, pid, since}|null}（只读）"""
    h = CL.holder()
    return {"free": h is None, "holder": h, "lock": str(CL.LOCK_PATH)}


threading.Thread(target=_worker, daemon=True).start()
_shot_cache.load(shot_cache_file())
_shot_detail_cache.load(shot_cache_file().with_name("shot_detail.pkl"))   # DATAALIGN（P1）：上次进程的按镜摘要，签名一致的直接复用，预热只需核签名
_snap = API_SNAP.load(P.DATA, "summary", P.SCRIPT_JSON)   # DATAALIGN P2：预热期间先给上次的摘要（as_of=0 → 立即后台重算）
if _snap:
    try:
        _summary_cache._data, _summary_cache._at = json.loads(_snap[0]), 0.0
    except ValueError:
        pass
_summary_cache.warm()  # T60：模块定义完后再预热集摘要，首个画布请求直接命中缓存


def _warm_episodes_bytes():
    """DATAALIGN（P1 重启后冷请求）：集摘要预热把每镜摘要算进按镜缓存后，再把 /api/episodes 整份编码好；
    启动后第一个请求直接拿字节。失败不影响服务"""
    try:
        _summary_cache.get()
        episodes_summary()          # 顺带写摘要快照
        with _EPISODES_LOCK:
            _episodes_http()
    except Exception:  # noqa: BLE001
        pass
    finally:
        _WARM["done"] = True


threading.Thread(target=_warm_episodes_bytes, name="episodes-warm", daemon=True).start()


async def _start_loop_watchdog():
    """DATAALIGN（总调度 P1：整体卡 15–17 s）：事件循环延迟 / 线程池占满看门狗 → data/qa/loop_lag.jsonl（含卡住时各线程调用栈）"""
    from ns_api import loop_watchdog as LW
    # 同步接口线程池 40 → 100：按镜缓存单飞时，等别人算完的请求也占着线程池名额；几个慢请求叠在一起就会把 40 个占满，
    # 连最轻的接口也排队（疑似 15–17 s 整体卡顿的放大器，看门狗的 threadpool 字段会证实 / 否定）。NS_THREADPOOL 可调
    try:
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = int(os.environ.get("NS_THREADPOOL") or 100)
    except Exception:  # noqa: BLE001
        pass
    LW.start(P.ROOT / "data" / "qa" / "loop_lag.jsonl")


app.router.on_startup.append(_start_loop_watchdog)

app.mount("/files", StaticFiles(directory=P.DATA), name="files")
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):   # QA-09：未知接口返回 404，而不是页面
            raise HTTPException(404, "没有这个接口")
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and f.is_relative_to(WEB_DIST.resolve()):   # T60：dist 根下的静态文件（favicon.svg 等）
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
