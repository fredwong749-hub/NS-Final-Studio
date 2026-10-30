"""
画布 API：分镜数据、人工修改、重渲染队列、版本切换、角色资产、导演加强。

    uv run uvicorn ns_api.app:app --port 8800
    浏览器打开 http://127.0.0.1:8800

渲染任务在单个后台线程里串行提交到 ComfyUI（NS_COMFY_URL，默认 127.0.0.1:8188）。
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
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ns_agent.compiler import compile_shot
from ns_agent.looks import default_store
from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient, ComfyError
from ns_schema.edits import ShotEdit, Take
from ns_api import assets as A
from ns_api import shotinfo as SI
from ns_api import readiness as RD  # 就绪闸门 + 一条链（docs/audit/shot_readiness_and_continuity.md §4）
from ns_api.looks import router as looks_router
from ns_api import projects as PJ  # T42 项目 / 新建剧向导 / 编排 / 看板
from ns_api import project_ctx as PJC
from ns_api import sop as SOP  # SOP 阶段 S1–S5 / 关口 G1–G5（只读）
from ns_api import h3view as H3V  # H3 提示词（SOP §9A）：来源选择 + 四块 + lint

COMFY_URL = os.environ.get("NS_COMFY_URL", "http://127.0.0.1:8188")
WEB_DIST = P.ROOT / "apps" / "web" / "dist"
BOOST_LLM_CONFIG = P.ROOT / "config" / "director_boost_llm.json"

# 运镜：motion 原文开头的英文镜头指令，到第一个中文逗号为止
CAMERA_RE = re.compile(r"^((?:extreme )?slow motion|camera [^，]+|static camera[^，]*|handheld[^，]*|"
                       r"orbit[^，]*|push in[^，]*|tracking[^，]*)", re.I)

app = FastAPI(title="NS-Final Studio 画布")
app.include_router(A.router)
app.include_router(looks_router)
app.include_router(PJ.router)
PJ.resume_on_startup()
_script = P.load_script()


def _watch_script():
    """script_v2.json 被重新导入后自动换上新剧本（之前要重启 API 才生效）"""
    global _script
    last = P.SCRIPT_JSON.stat().st_mtime if P.SCRIPT_JSON.exists() else 0
    while True:
        time.sleep(10)
        try:
            m = P.SCRIPT_JSON.stat().st_mtime
            if m != last:
                _script, last = P.load_script(), m
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
                     "video": ("h3_body", "soundscape")}   # SOP §9A：H3 只认正文与环境声的修改


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
        out[stage] = next((t for t in data["takes"] if t["stage"] == stage and t["n"] == n), None)
    return out


def _camera(motion: str) -> str:
    body = re.sub(r"^[a-z0-9_]+，", "", motion)
    m = CAMERA_RE.match(body)
    return m.group(1).strip() if m else ""


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
    music: str | None = None             # 本集背景音乐（后期混音；H3 的 non_diegetic_music 保持 N/A）


def _schema_fields(name: str) -> set[str]:
    from ns_schema import edits as E
    m = getattr(E, name, None)
    return set(getattr(m, "model_fields", {}) or {})


def audio_supported() -> dict:
    """E8 字段是否已上线（ns_schema.edits）；没上线时画布只读显示，不假装保存成功"""
    shot, ep = _schema_fields("ShotEdit"), _schema_fields("EpisodeEdit")
    return {"soundscape": "soundscape" in shot, "music": "music" in shot, "episode_music": "music" in ep}


def save_episode_edit(n: int, body: EpisodeEditBody) -> dict:
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
    if take.get("workflow") == "upload" or take.get("source") in ("upload", "next", "video"):
        target = ""                              # 上传 / 引用的版本没有提示词可比
    edited_after = bool(edit.updated_at and edit.updated_at > created)
    # 锁脸前缀（"图1是林晚的面部参考：…按以下描述。"）等由渲染器加在最前，比较时只看结尾
    if target and not prompt.endswith(target):
        raw = SI.strip_triggers(s.img_prompt if stage != "video" else s.motion_prompt)
        if edited_after and any(getattr(edit, f, None) for f in STAGE_EDIT_FIELDS.get(stage, EDIT_PROMPT_FIELDS)):
            local.append("提示词已改")
        elif stage != "last" and raw and raw[:12] not in prompt and SI.action_text(raw)[:12] not in prompt:
            local.append("剧本已改")
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
    img = act.get("image")
    if stage in ("video", "last") and img and img["created_at"] > created and take.get("source") != "next":
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


def _stale(shot_id: str, take: dict, compiled, act: dict) -> list[str]:
    """兼容旧调用：只返回本镜原因"""
    _, s = P.find_shot(_script, shot_id)
    edit = P.load_edit(shot_id)
    return _stale_split(shot_id, take, s, compiled, edit, act, None, _last_prompt(compiled, edit, s)[0])[0]


class Ctx:
    """一次请求共享：造型解析器、资产索引、本集加强（避免每镜重复读 JSON / 扫目录）"""

    def __init__(self):
        store = default_store()
        self.res = store.resolver()
        self.idx = A.AssetIndex(store)
        self.looks_by_id = {lk.id: lk for lk in store.lookbook().looks}
        self._ep: dict[int, dict] = {}
        self.slug = RD.current_slug()
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
        elif actual:
            src = "video"
    target = None
    if src == "next":
        target = next_first
    elif src == "upload":
        target = _url(edit.last_frame) if edit.last_frame and edit.last_frame != "next" else (
            _url(lt["file"]) if lt else None)
    elif src == "gen":
        target = _url(lt["file"]) if lt else None
    elif src == "video":
        target = actual
    return {"last_frame_source": src, "last_frame_target": target, "last_frame_actual": actual,
            "last_frame_take": lt["n"] if lt else None, "next_shot": nxt, "next_first_frame": next_first,
            "last_supported": last_supported()}


def episode_music(ep, ep_edit: dict) -> dict:
    """本集背景音乐（后期混音用，不进 H3：H3 的 non_diegetic_music 保持 N/A）。
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
    stale, stale_global = {}, {}
    for k, v in act.items():
        if v:
            stale[k], stale_global[k] = _stale_split(s.id, v, s, compiled, edit, act, look_hash, last_prompt, ep_edit)
    pending = [j for j in _jobs.values() if j.get("shot_id") == s.id and j["state"] in ("queued", "running")]
    lf = _last_frame_info(s.id, edit, act)
    count = {st: sum(1 for t in takes["takes"] if t["stage"] == st) for st in STAGES}
    boost = _boosts(edit, ep_edit)
    chain_info = _chain_fields(ep, s, c, edit, ep_edit, act, lf, ctx)
    h3v = H3V.view(s, compiled, edit, ctx.slug, c.adult)
    return {
        "review": _review(s.id, act),
        "stale": stale, "stale_global": stale_global,
        "id": s.id, "index": s.index, "adult": c.adult, "edited": bool(edit.updated_at),
        "camera": SI.camera_info(edit.camera, s.img_prompt, s.motion_prompt),
        "expression": SI.expression_info(edit.expression, s.img_prompt, s.motion_prompt),
        "img_summary": s.img_prompt[:60],
        "script_text": SI.script_text(s.img_note, s.motion_prompt),
        "duration": {"seconds": getattr(s, "duration", 10), "source": getattr(s, "duration_source", "default")},
        "image_prompt": compiled.image_prompt, "image_prompt_edited": bool(edit.image_prompt),
        # 视频提示词 = H3 官方四块提示词（gpu3 最终 > 剧本 **H3提示词** > 笔记本草稿）；旧版中文拼接只作历史
        "video_prompt": h3v["h3_prompt"],
        "video_prompt_edited": bool(edit.h3_body or edit.soundscape) and h3v["h3_prompt_source"] != "gpu3",
        "legacy_video_prompt": compiled.legacy_video_prompt,
        **h3v,
        "last_prompt": last_prompt, "last_prompt_source": last_prompt_src,
        # 卡片两行放不下全文：从本镜特有的部分开始显示（跳过角色锁 / 固定前缀），悬停看全文
        "image_prompt_focus": SI.focus(compiled.image_prompt, SI.strip_triggers(s.img_prompt)),
        "last_prompt_focus": SI.focus_last(last_prompt),
        "boost": boost, "has_boost": any(boost.values()),
        "audio": _audio(c, compiled, edit, s, ep, ep_edit),
        "first_frame": _url(act["image"]["file"]) if act["image"] else None,
        "first_frame_take": act["image"]["n"] if act["image"] else None,
        "video": _url(act["video"]["file"]) if act["video"] else None,
        "last_frame": lf["last_frame_actual"],       # 兼容 v1：= 视频实际尾帧
        **lf,
        "takes_count": count,
        # 每个阶段最新版本号：大于当前版本 = 有新版本待选（行内「新 vN 待选」，检查器自动放到对比位）
        "latest_take": {st: max((t["n"] for t in takes["takes"] if t["stage"] == st), default=None) for st in STAGES},
        "score": {k: (v.get("score") if v else None) for k, v in act.items() if k != "video"},
        "needs_review": takes.get("review") or {},
        "dialogue": [d.model_dump() for d in s.dialogue],
        "voiceover": s.voiceover.model_dump() if s.voiceover else None,
        "decor_state": s.decor_state,
        "look_hash": look_hash,
        "characters": [A.character_brief(r, ctx.idx, ctx.looks_by_id) for r in sl.characters] if sl else [],
        "job": pending[0]["state"] if pending else None,
        "job_stage": pending[0]["stage"] if pending else None,
        "queue_pos": _queue_pos(pending[0]["id"]) if pending else None,
        **chain_info,
    }


def _chain_fields(ep, s, c, edit: ShotEdit, ep_edit: dict, act: dict, lf: dict, ctx: Ctx) -> dict:
    """一条链（§4）：gpu3 负责 / 有 gpu3 链时，首帧·尾帧·视频全部取 gpu3 链，笔记本版本只作历史；
    返回的键会覆盖摘要里同名的笔记本字段。另附 readiness（就绪闸门）。"""
    chain = ctx.chain(s.id)
    owner, owner_why = RD.shot_owner(s.id, ctx.slug, chain)
    laptop = {"first": _url(act["image"]["file"]) if act["image"] else None,
              "first_take": act["image"]["n"] if act["image"] else None,
              "last": lf["last_frame_target"] or lf["last_frame_actual"], "last_from": lf["last_frame_source"],
              "video": _url(act["video"]["file"]) if act["video"] else None}
    use_gpu3 = owner == "gpu3" or chain["present"]
    has_laptop = bool(laptop["first"] or laptop["last"] or laptop["video"])
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
            "video": chain["video"], "last_frame": chain["last_frame"],
            "last_frame_target": chain["last_frame"], "last_frame_actual": chain["last_frame"],
            "last_frame_source": "gpu3" if chain["last_frame"] else None, "last_frame_take": None,
            "stale": {}, "stale_global": {}, "score": {},
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


@app.get("/api/episodes")
def episodes():
    ctx = Ctx()
    out = []
    for ep in _script.episodes:
        shots = [_shot_summary(ep, s, ctx) for s in ep.shots]
        out.append({"number": ep.number, "title": ep.title, "high_intensity": ep.high_intensity, "tag": ep.tag,
                    "synopsis": ep.synopsis, "edit": ctx.ep_edit(ep.number),
                    "music": episode_music(ep, ctx.ep_edit(ep.number)), "audio_supported": audio_supported(),
                    "readiness": _episode_readiness(ep, shots, ctx), "shots": shots})
    return out


@app.get("/api/readiness")
def readiness_report(ep: int | None = None):
    """给其它工具用：每镜 {id, owner, frames_source, readiness}；?ep=N 只看一集"""
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
        for s in e.shots:
            x = _shot_summary(e, s, ctx)
            rows.append({"id": s.id, "episode": e.number, "index": s.index, "readiness": x.get("readiness"),
                         "owner": x.get("owner"), "has_first": bool(x.get("first_frame")),
                         "has_last": bool(x.get("last_frame")), "has_video": bool(x.get("video")),
                         "gpu3_status": (x.get("gpu3") or {}).get("status"),
                         "h3_failed": x.get("h3_failed"), "h3_source": x.get("h3_prompt_source")})
    name = proj.name if proj is not None else ctx.slug
    return ctx.slug, name, inp, SOP.evaluate(inp, rows, project_owner=RD.project_owner(ctx.slug)[0])


@app.get("/api/sop/status")
def sop_status():
    """每个项目：当前阶段、G1–G5 通过/阻塞（原因 + 谁来做：owner|gpu3|laptop）、待项目方决定的事（附命令）。
    只读：没有任何替项目方接受关口的接口。当前画布项目全量计算；其它登记项目只看它自己的状态表 + gpu3 镜像。"""
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
            if a["gate"] in ("G3", "G4", "plate") or n in (a.get("episodes") or []) or a.get("episode") == n]
    acts = [{**a, "cli": SOP.cli_look(str(n), a["character"])} if a["gate"] == "look" else a
            for a in acts]                  # 本集视角：造型只确认本集（cli_all 仍是全部未确认的集）
    return {"project": slug, **e,
            "stages": [{"id": k, "label": v, "shots_here": e["counts"][k]} for k, v in SOP.STAGES],
            "gates": ev["gates"], "s1": ev["s1"], "owner_actions": acts,
            "shots": [s for s in ev["shots"] if s["episode"] == n]}



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

@app.get("/api/shots/{shot_id}")
def shot(shot_id: str):
    ep, s = _find(shot_id)
    edit = P.load_edit(shot_id)
    compiled = _compile_for_display(ep, s, edit)
    takes = P.load_takes(shot_id)
    act = _active(shot_id, takes)
    ctx = Ctx()
    ep_edit = ctx.ep_edit(ep.number)
    summary = _shot_summary(ep, s, ctx)
    last_prompt = summary["last_prompt"]
    for t in takes["takes"]:
        t["url"] = _url(t["file"])
        t["last_url"] = _url(t.get("last_frame"))
        t["raw_url"] = _url(t.get("raw_file"))
        t["stale"], t["stale_global"] = _stale_split(shot_id, t, s, compiled, edit, act, summary["look_hash"],
                                                     last_prompt, ep_edit)
    boost = summary["boost"]

    def landed(text: str | None, prompt: str):
        return None if not text else text in prompt

    return {
        "summary": summary,
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
        "next_shot": P.next_shot_id(_script, shot_id),
        "error": P._read_json(P.shot_dir(shot_id) / "errors.json", None),
    }


# ---------------------------------------------------------------- 写：镜头 / 本集

@app.put("/api/shots/{shot_id}/edit")
def put_edit(shot_id: str, edit: ShotEdit):
    _find(shot_id)
    clean = ShotEdit.model_validate({k: (v.strip() or None) if isinstance(v, str) and k != "note" else v
                                     for k, v in edit.model_dump().items()})
    return P.save_edit(shot_id, clean).model_dump()


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
    rel = f"uploads/{shot_id}/last_{int(time.time())}{suffix}"
    (P.DATA / rel).parent.mkdir(parents=True, exist_ok=True)
    (P.DATA / rel).write_bytes(await file.read())
    edit = P.load_edit(shot_id)
    edit.last_frame = rel
    edit.last_source = "upload"
    P.save_edit(shot_id, edit)
    return {"last_frame": rel, "url": _url(rel)}


@app.post("/api/shots/{shot_id}/first-frame")
async def upload_first_frame(shot_id: str, file: UploadFile = File(...)):
    """上传首帧：记为一个 image 版本（workflow=upload）并设为当前"""
    _find(shot_id)
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(422, "只接受 png / jpg / webp")
    n = P._next_n(shot_id, "image")
    rel = f"renders/{P.shot_dir(shot_id).relative_to(P.RENDERS).as_posix()}/takes/image_{n:03d}_upload{suffix}"
    (P.DATA / rel).parent.mkdir(parents=True, exist_ok=True)
    (P.DATA / rel).write_bytes(await file.read())
    take = Take(n=n, stage="image", file=rel, seed=0, prompt="", created_at=P.now(), workflow="upload",
                source="upload")
    P._add_take(shot_id, take)
    return {"n": n, "url": _url(rel)}


# ---------------------------------------------------------------- 导演加强：用项目方自己的模型给建议

class BoostSuggest(BaseModel):
    which: str = "first"            # first | last


DEFAULT_RULES_FILE = "config/director_boost_rules.md"
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _local_config_path() -> Path:
    return BOOST_LLM_CONFIG.with_name(BOOST_LLM_CONFIG.stem + ".local.json")


def load_boost_config() -> dict:
    """config/director_boost_llm.json，再用 .local.json（gitignore，放密钥）同名键覆盖；
    api_key 也可以来自环境变量 NS_BOOST_API_KEY。密钥只用于请求头，从不返回、不记日志。"""
    cfg: dict = {}
    for path in (BOOST_LLM_CONFIG, _local_config_path()):
        if path.exists():
            try:
                cfg.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError as e:
                raise HTTPException(400, f"{path.name} 不是合法 JSON：{e.msg}")
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


def _boost_llm_config() -> tuple[dict, str]:
    hint = (f"请先创建 config/{BOOST_LLM_CONFIG.name}（参考 config/director_boost_llm.example.json，"
            "填 base_url、model；密钥放 config/director_boost_llm.local.json 的 api_key 或环境变量 NS_BOOST_API_KEY）")
    if not BOOST_LLM_CONFIG.exists() and not _local_config_path().exists():
        raise HTTPException(400, f"没有找到导演加强模型配置。{hint}")
    cfg = load_boost_config()
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
    return {"base_url": cfg.get("base_url") or "", "model": cfg.get("model") or "",
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
    if req.which not in ("first", "last"):
        raise HTTPException(422, "which 只能是 first 或 last")
    cfg, instruction = _boost_llm_config()
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
    priority: int = 5


@app.post("/api/shots/{shot_id}/gpu3-rerender")
def gpu3_rerender(shot_id: str, body: Gpu3RerenderBody):
    """「请 gpu3 重出」：按 docs/canvas.md §2 发一条 nsfs_canvas.rerender/v1 到桥（桥写 gpu3 上的 rerender_queue.jsonl）。
    契约的 stage 只有 image|video|both：「只重出尾帧」发 image + overrides.last_only=true（保留首帧，由首帧重编尾帧）。"""
    _find(shot_id)
    if body.stage not in RD.GPU3_RERENDER_STAGES:
        raise HTTPException(400, f"stage 只能是 {RD.GPU3_RERENDER_STAGES}")
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
    return {"ok": True, "request": req, "bridge": res}


@app.get("/api/gpu3-media/{rel:path}")
def gpu3_media(rel: str, request: Request):
    """镜像还没同步的 gpu3 文件：同源代理到桥 /api/gpu3/media/<rel>（Range 透传，视频可拖动）。只读。"""
    if not rel.startswith("renders_gpu3/") or ".." in rel.split("/"):
        raise HTTPException(400, "只代理 renders_gpu3/ 下的文件")
    local = P.DATA / rel
    if local.exists():
        return FileResponse(local)
    try:
        r = RD.fetch_media(rel, request.headers.get("range"))
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, f"gpu3 桥：{e.reason}")
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(502, f"gpu3 桥不可达：{e}")
    keep = ("content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag")
    headers = {k: v for k, v in r.headers.items() if k.lower() in keep}
    headers["Cache-Control"] = "max-age=300"

    def body():
        with r:
            while chunk := r.read(1 << 16):
                yield chunk
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
    _find(shot_id)
    why = _gpu3_owner_reason(shot_id)
    if why:   # 一镜一条链：gpu3 负责的镜头本机不出新版本（避免首帧 / 尾帧 / 视频来自两条链）
        raise HTTPException(409, f"gpu3 负责此镜（避免两条链）：{why}。请用「请 gpu3 重出」")
    if req.stage not in STAGES:
        raise HTTPException(400, f"stage 只能是 {STAGES}")
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
        P.set_active(shot_id, stage, n)
    except StopIteration:
        raise HTTPException(404, "没有这个版本")
    except ValueError as e:                     # QCRejected
        raise HTTPException(409, str(e))
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
    return sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)[:50]


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
        data = P.load_takes(shot_id)
        for t in data["takes"]:
            if t["stage"] == stage and t["n"] == n:
                t["look_hash"] = h
        P._write_json(P.shot_dir(shot_id) / "takes.json", data)
    except Exception:
        pass


RENDERERS = {"image": lambda: P.render_image, "video": lambda: P.render_video,
             "last": lambda: getattr(P, "render_last_frame")}


def _worker():
    client = ComfyClient(COMFY_URL)
    while True:
        job = _jobs[_queue.get()]
        job["state"] = "running"
        job["started_at"] = P.now()
        try:
            if job["stage"] == "asset":
                rec = A.generate_asset(client, job["character"], job["request"])
                job.update(state="done", file=rec["file"])
                continue
            take = RENDERERS[job["stage"]]()(client, _script, job["shot_id"], seed=job["seed"])
            job.update(state="done", take=take.n)
            _record_look_hash(job["shot_id"], job["stage"], take.n)
        except (ComfyError, Exception) as e:  # 任何错误都记到任务上，不让线程退出
            job.update(state="failed", error=str(e)[:1000])
            if job["stage"] != "asset":
                P._write_json(P.shot_dir(job["shot_id"]) / "errors.json", {"last": str(e), "at": P.now()})


threading.Thread(target=_worker, daemon=True).start()

app.mount("/files", StaticFiles(directory=P.DATA), name="files")
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):   # QA-09：未知接口返回 404，而不是页面
            raise HTTPException(404, "没有这个接口")
        return FileResponse(WEB_DIST / "index.html")
