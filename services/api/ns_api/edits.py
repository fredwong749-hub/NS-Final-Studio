"""
处处可编辑：“指出问题 → 系统修”闭环（EDITDEL 2026-10-31，项目方原话：“我对图片不满意，会进行 edit，指出我认为错误的地方。
然后系统返回去对图片进行 edit，调度 image 的图文对应模型；此时，仍然需要调用 API 模型来进行逻辑上的处理。”）

三层：
  1. 对象层：把对象（图片 / 视频 / 剧本段 / 提示词 / 资产字段）的当前内容、提示词、Shot Spec、身份参考读出来。
  2. 逻辑层：写作 / 逻辑 API 模型（config/llm_providers.json 用途 edit_plan，默认 abliteration large-flash，关推理）
     按 config/pipeline/prompts/edit_planner.md（从 knowledge 规则自动组装）把项目方反馈翻译成结构化修改计划（JSON）；
     系统再按锁定规则机检计划（HC-07 外貌锚点、HC-02 成年人约束、剧本台词不由逻辑层改）。
  3. 执行层：
       图片 → 可插拔编辑模型（config/edit_engines.json：default 现为 Qwen-Image 2.1 Edit；BAKEOFF 对比 2511 / Klein / FireRed /
              Krea2 后切换），每次提交前后过 GEN_CONTRACT preflight / postflight（ns_agent.gen_contract，REFLOCK）；
              原图作 图1 + 修改指令 + 身份参考，LoRA / 负面词 / 身份锚点一律取自系统出图编译器
              （ns_agent.compiler，K-REN-103）；有框选 = 局部重绘（整图编辑后只把框内羽化贴回原图，框外像素不变）。
              画布镜头版本（take）进 takes.json 的修改链（parent）；其它图片（流水线首帧、设定图、场景图）进
              data/edits/versions/<key>/ 的版本链。都不覆盖原版本，可对比、可回滚。
       视频 → 按计划改参数（换 seed / 时长 / 步数 / 基底）经现有 video-jobs 重出（新 take，parent = 原版本）。
       文本 → 写作模型（用途 script_write）按计划改写，标“待确认”；剧本段跑链条校验（tools/pipeline/run_chain.validate）。
              采用（adopt）时才写回：提示词写进本镜 edits.json；剧本段走 PUT /api/story-runs/.../artifact（by=owner）。
  4. 记账：data/edits/ledger.jsonl（反馈、计划、结果、是否采用）；被采用的改法按关键词聚类，同类 ≥2 次自动写
     knowledge/inbox/<日期>_edit_<类>.yaml 规则草案（status 待确认），并在 knowledge/RSI_LEDGER.md 记一行。

系统只做编排与格式 / 规则机检，不写、不评价剧本内容；修改指令与改写文字都由模型给出。

接口：
  POST /api/edits                          {type, id, version?, feedback, annotations?, gpu?, engine?, llm?, dry_run?}
                                           （操作人从登录会话取，项目方 2026-10-31：登录即本人）
  GET  /api/edits/engines                  可选编辑模型
  GET  /api/edits?type=&id=&limit=         编辑记录（新 → 旧）
  GET  /api/edits/{edit_id}                单条（含任务进度 job）
  POST /api/edits/{edit_id}/adopt          {by?, note?} 采用：设为当前 / 写回（剧本段要 by=owner）
  POST /api/edits/{edit_id}/reject         {reason?} 不采用（版本保留在链上）
  POST /api/edits/{edit_id}/rollback       回到编辑前的版本（当前版本指回原版本）
  GET  /api/edits/versions?type=&id=       版本链（对比用）
  GET  /api/edits/planner-prompt           逻辑模型系统提示词（组装结果）
  POST /api/edits/planner-prompt/rebuild   从 knowledge 规则重新组装
  GET  /api/edits/learned                  采用过的改法聚类（规则草案候选）

对象 id：
  image  take:<shot>/<image|last>/<n> | file:<相对项目根的图片路径>（可带 #<shot> 指定镜头，不带时按文件名 epNN-SN 推断）
         asset 图片用 file:assets/...；不给 n（take:<shot>/image）= 当前版本
  video  take:<shot>/video/<n>
  script run:<run_id>/<P1..P4>[@<ep>]                 写作链产物
  prompt shot:<shot>/<image_prompt|last_prompt|boost_first|boost_last|expression|camera>
  asset  asset:<asset_id>/<字段>                         （text 字段：采用后返回文字，由资产页按原接口保存）
标注 annotations：{box:[x,y,w,h]（0–1 相对坐标）| boxes:[[..]], time_s?: 视频时间点, note?}
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：按当前剧取路径（V1 已归档，不在网页显示）
import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ns_api import jobs as J
from ns_api import llm_config as LLMC
from ns_render import pipeline as P
from ns_render import render_paths as RP   # W33

router = APIRouter(tags=["edits"])
REPO = Path(__file__).resolve().parents[3]
PLANNER_PROMPT = REPO / "config" / "pipeline" / "prompts" / "edit_planner.md"
KNOWLEDGE = REPO / "knowledge"
TYPES = ("image", "video", "script", "prompt", "asset")
IMAGE_ACTIONS = ("inpaint", "edit", "regen", "refs", "seed", "prompt_only")
VIDEO_ACTIONS = ("video_rerun", "prompt_only")
TEXT_ACTIONS = ("text_rewrite",)
ALL_ACTIONS = IMAGE_ACTIONS + VIDEO_ACTIONS + TEXT_ACTIONS + ("reject",)
PROMPT_FIELDS = ("image_prompt", "last_prompt", "boost_first", "boost_last", "expression", "camera")
STRENGTHS = ("small", "medium", "large")
PLAN_MAX_TOKENS = 1500
REWRITE_MAX_TOKENS = 6000
LEARN_MIN = 2                          # 同一类改法被采用 ≥2 次 → 写规则草案
FEATHER = 0.04                         # 局部重绘羽化半径（相对短边）
_lock = threading.RLock()

# 反馈关键词 → 改法类别（只用于记账聚类，不评价内容）
LEARN_KEYS = {
    "oily_skin": ("油", "油光", "油腻", "反光", "oily", "shiny"),
    "identity": ("不像", "脸不对", "换脸", "像别人", "身份"),
    "plastic_skin": ("塑料", "磨皮", "假脸", "蜡像", "太光滑"),
    "hands": ("手指", "手", "指甲"),
    "framing": ("构图", "景别", "裁切", "太远", "太近", "出画"),
    "lighting": ("太暗", "太亮", "过曝", "曝光", "光线", "打光"),
    "color": ("偏色", "太黄", "太红", "太蓝", "发色", "色调"),
    "motion": ("不动", "卡顿", "僵", "抖"),
}


def data_dir() -> Path:
    return P.DATA / "edits"


def ledger_path() -> Path:
    return data_dir() / "ledger.jsonl"


# ============================================================ 存储
def _items_dir() -> Path:
    d = data_dir() / "items"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_item(it: dict) -> dict:
    p = _items_dir() / f"{it['edit_id']}.json"
    tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in range(40):   # Windows：别的线程正在读这个文件时 replace 会 Access denied → 稍等重试
        try:
            tmp.replace(p)
            break
        except PermissionError:
            if k == 39:
                raise
            time.sleep(0.05)
    return it


def _load_item(edit_id: str) -> dict:
    if not re.fullmatch(r"ed-[0-9a-f]{10}", edit_id or ""):
        raise HTTPException(404, f"没有这条编辑：{edit_id}")
    p = _items_dir() / f"{edit_id}.json"
    if not p.is_file():
        raise HTTPException(404, f"没有这条编辑：{edit_id}")
    for k in range(40):   # 正在被替换（Windows 读写冲突）→ 稍等重试
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (PermissionError, ValueError):
            if k == 39:
                raise
            time.sleep(0.05)
    raise HTTPException(500, "读不到编辑记录")


def ledger(event: str, it: dict, **extra) -> None:
    rec = {"at": P.now(), "event": event, "edit_id": it.get("edit_id"), "type": it.get("type"), "id": it.get("id"),
           "feedback": it.get("feedback"), "annotations": it.get("annotations"), "plan": it.get("plan"),
           "result": it.get("result"), "status": it.get("status"), "adopted": it.get("adopted"),
           "learn_key": it.get("learn_key"), **extra}
    data_dir().mkdir(parents=True, exist_ok=True)
    with _lock, ledger_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_ledger() -> list[dict]:
    """账本不存在 = 还没有记录（空表）；存在但读不了 = 抛错（不当成空账本）。单行坏 = 跳过并记数（追加式账本写一半的尾行）"""
    p = ledger_path()
    if not p.is_file():
        return []
    out, bad = [], 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:  # arch-ok: 追加式账本的单个坏行（写到一半）跳过并计数，其它行照用
            bad += 1
    if bad:
        _log_bad_lines(p, bad)
    return out


def _log_bad_lines(p: Path, n: int) -> None:
    import logging
    logging.getLogger("ns_api.edits").warning("%s 有 %d 行不是 JSON，已跳过", p, n)


# ============================================================ 版本链（非 take 的图片）
def _key(obj_id: str) -> str:
    return hashlib.sha1(obj_id.encode("utf-8")).hexdigest()[:16]


def chain_path(obj_id: str) -> Path:
    return data_dir() / "versions" / _key(obj_id) / "chain.json"


def load_chain(obj_id: str, original: str | None = None) -> dict:
    p = chain_path(obj_id)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"id": obj_id, "original": original, "current": 0,
            "versions": [{"v": 0, "file": original, "edit_id": None, "parent": None, "created_at": None,
                          "label": "原版"}]}


def _atomic_json(p: Path, obj) -> None:
    """JSON 原子写：临时文件 + os.replace（arch_scan nonatomic_json）"""
    import os
    import tempfile
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def save_chain(ch: dict) -> dict:
    _atomic_json(chain_path(ch["id"]), ch)
    return ch


def _url(rel_repo: str | None) -> str | None:
    """相对项目根的路径 → 浏览器能打开的地址（data/ 下走 /files，assets/ 下走 /api/assets/file）"""
    if not rel_repo:
        return None
    r = rel_repo.replace("\\", "/")
    if r.startswith("data/"):
        return "/files/" + r[5:]
    if r.startswith("assets/"):
        return f"/api/assets/file?path={r}"
    return None


def _repo_rel(p: Path) -> str:
    """data/ 下的文件一律写成 data/…（P.DATA 可能不在项目根下，如测试）；其余相对项目根"""
    try:
        return "data/" + p.resolve().relative_to(P.DATA.resolve()).as_posix()
    except ValueError:
        return p.resolve().relative_to(REPO.resolve()).as_posix()


def _abs(rel_repo: str) -> Path:
    r = rel_repo.replace("\\", "/")
    if r.startswith("data/"):
        return P.DATA / r[5:]
    return REPO / r


def _safe_rel(raw: str) -> str:
    raw = (raw or "").replace("\\", "/").strip()
    if (not raw or ":" in raw or raw.startswith("/") or ".." in raw.split("/")):
        raise HTTPException(422, f"路径不合法：{raw!r}")
    return raw


# ============================================================ 对象解析
_SHOT_RE = re.compile(r"(ep\d{2,3}-S\d+)")


def _app():
    from ns_api import app as A
    return A


def _compiled(shot_id: str | None, loras: set[str] | None = None):
    if not shot_id:
        return None
    try:
        return P.compile_with_edits(_app()._script, shot_id, loras if loras is not None else set())
    except Exception:  # noqa: BLE001  没有这个镜头 / 剧本不含 → 只是没有上下文
        return None


def _find_take(shot_id: str, stage: str, n: int | None) -> dict:
    data = P.load_takes(shot_id)
    if n is None:
        n = (data.get("active") or {}).get(stage)
    t = next((x for x in data.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
    if not t:
        raise HTTPException(404, f"{shot_id} 没有 {stage} v{n}")
    return t


def identity_refs(text: str) -> list[dict]:
    """身份参考：提示词里出现的角色 → data/assets/asset_refs.json 里 role=identity 的第一张（未作废）；
    林晚兜底 config/face_reference.json"""
    from ns_schema.looks import CHARACTERS
    try:
        refs = json.loads((P.DATA / "assets" / "asset_refs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        refs = {}
    out = []
    for cid, name in CHARACTERS.items():
        if name not in (text or ""):
            continue
        pick = next((r for r in refs.get(cid) or [] if r.get("role") == "identity" and not r.get("void")
                     and (REPO / str(r.get("file") or "")).is_file()), None)
        if pick:
            out.append({"character": name, "asset_id": cid, "path": pick["file"], "role": "identity",
                        "ref_id": pick.get("ref_id")})
        elif cid == "lin_wan" and not _RP.manifest():          # V1 旧兜底；资产包模式（V2）身份脸只认清单，不读 V1 face_reference
            frp = REPO / "config" / "face_reference.json"
            fr = json.loads(frp.read_text(encoding="utf-8")) if frp.is_file() else {}
            if fr.get("reference") and (REPO / fr["reference"]).is_file():
                out.append({"character": name, "asset_id": cid, "path": fr["reference"], "role": "identity"})
    return out


def identity_anchor(prompt: str) -> str:
    """编译器提示词里的角色锁段（【姓名】…）：改图指令后面原样带上，免得编辑把锁定外貌改掉"""
    i = (prompt or "").find("【")
    if i < 0:
        return ""
    seg = prompt[i:i + 200]
    cut = seg.rfind("，")
    return seg[:cut] if cut > 20 else seg


def describe(obj_type: str, obj_id: str, version: int | None = None) -> dict:
    """对象上下文（给逻辑模型和执行层）"""
    if obj_type not in TYPES:
        raise HTTPException(422, f"type 只能是 {' | '.join(TYPES)}")
    kind, _, rest = obj_id.partition(":")
    ctx: dict = {"type": obj_type, "id": obj_id, "kind": kind}
    if kind == "take":
        parts = rest.split("/")
        if len(parts) not in (2, 3):
            raise HTTPException(422, "take id 写法：take:<镜头>/<image|last|video>/<n>")
        shot, stage = parts[0], {"first": "image"}.get(parts[1], parts[1])
        if stage not in ("image", "last", "video"):
            raise HTTPException(422, "stage 只能是 image | last | video")
        if (obj_type == "video") != (stage == "video"):
            raise HTTPException(422, "type=video 只对应视频版本；图片用 image / last")
        n = version if version is not None else (int(parts[2]) if len(parts) == 3 else None)
        t = _find_take(shot, stage, n)
        c = _compiled(shot)
        prompt = (c.image_prompt if stage == "image" else c.last_prompt if stage == "last" else c.video_prompt) if c else ""
        ctx.update(shot_id=shot, stage=stage, n=t["n"], file=f"data/{t['file']}", take=t,
                   locked=(P.load_takes(shot).get("locked") or {}).get(stage) == t["n"],
                   prompt=t.get("prompt") or prompt, compiled_prompt=prompt,
                   spec=(c.visual_spec if c else None), script_text=_script_text(shot))
    elif kind == "file":
        raw, _, shot = rest.partition("#")
        rel = _safe_rel(raw)
        if not _abs(rel).is_file():
            raise HTTPException(404, f"找不到图片：{rel}")
        if obj_type != "image":
            raise HTTPException(422, "file: 只用于图片")
        m = _SHOT_RE.search(rel)
        shot = shot or (m.group(1) if m else None)
        ch = load_chain(obj_id, rel)
        cur = next((v for v in ch["versions"] if v["v"] == (version if version is not None else ch["current"])), None)
        if cur is None:
            raise HTTPException(404, f"没有版本 v{version}")
        c = _compiled(shot)
        ctx.update(shot_id=shot, stage="image", file=cur["file"], chain_v=cur["v"], original=rel,
                   prompt=(c.image_prompt if c else ""), compiled_prompt=(c.image_prompt if c else ""),
                   spec=(c.visual_spec if c else None), script_text=_script_text(shot) if shot else "",
                   locked=False)
    elif kind == "run":
        from ns_api import story_runs as SR
        m = re.fullmatch(r"([A-Za-z0-9_.\-]{1,80})/(P[1-4])(?:@(\d{1,3}))?", rest)
        if not m:
            raise HTTPException(422, "剧本段 id 写法：run:<运行>/<P1..P4>[@集]")
        d = SR._run_dir(m.group(1))
        p = SR._artifact_path(d, m.group(2), int(m.group(3)) if m.group(3) else None)
        if not p.is_file():
            raise HTTPException(404, f"这一段还没有产物：{m.group(2)}")
        ctx.update(run_id=m.group(1), node=m.group(2), ep=int(m.group(3)) if m.group(3) else None,
                   file=_repo_rel(p), text=p.read_text(encoding="utf-8"), series=bool(SR.series_eps(d)),
                   running=SR._alive(m.group(1)))
    elif kind == "shot":
        shot, _, field = rest.partition("/")
        if field not in PROMPT_FIELDS:
            raise HTTPException(422, f"提示词字段只能是 {' | '.join(PROMPT_FIELDS)}")
        c = _compiled(shot)
        if c is None:
            raise HTTPException(404, f"没有镜头 {shot}")
        ed = P.load_edit(shot)
        cur = getattr(ed, field, None)
        comp = {"image_prompt": c.image_prompt, "last_prompt": c.last_prompt, "boost_first": c.boost_first,
                "boost_last": c.boost_last}.get(field, "")
        ctx.update(shot_id=shot, field=field, text=cur if cur is not None else comp, compiled_prompt=c.image_prompt,
                   overridden=cur is not None, script_text=_script_text(shot))
    elif kind == "asset":
        aid, _, field = rest.partition("/")
        if not aid or not field:
            raise HTTPException(422, "资产字段 id 写法：asset:<asset_id>/<字段>")
        ctx.update(asset_id=aid, field=field, text=_asset_field(aid, field))
    else:
        raise HTTPException(422, "id 前缀只能是 take: / file: / run: / shot: / asset:")
    if obj_type == "image" and kind not in ("take", "file"):
        raise HTTPException(422, "图片对象用 take: 或 file:")
    if obj_type in ("script",) and kind != "run":
        raise HTTPException(422, "剧本对象用 run:")
    if obj_type == "prompt" and kind != "shot":
        raise HTTPException(422, "提示词对象用 shot:")
    if obj_type == "asset" and kind not in ("asset", "file"):
        raise HTTPException(422, "资产对象用 asset:（资产图片用 type=image + file:）")
    if ctx.get("prompt") or ctx.get("compiled_prompt"):
        ctx["identity_refs"] = identity_refs((ctx.get("compiled_prompt") or "") + (ctx.get("prompt") or ""))
    return ctx


def _script_text(shot: str | None) -> str:
    if not shot:
        return ""
    try:
        s = P.find_shot(_app()._script, shot)
        s = s[1] if isinstance(s, tuple) else s
        return str(getattr(s, "img", "") or getattr(s, "text", "") or "")[:1500]
    except Exception:  # noqa: BLE001
        return ""


def _asset_field(aid: str, field: str) -> str:
    try:
        from ns_api import asset_edit as AE
        a = AE.asset_detail(aid) if hasattr(AE, "asset_detail") else None
    except Exception:  # noqa: BLE001
        a = None
    if isinstance(a, dict):
        v = a.get(field)
        if v is None and isinstance(a.get("asset"), dict):
            v = a["asset"].get(field)
        if v is not None:
            return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return ""


# ============================================================ 逻辑层：系统提示词（从 knowledge 组装）
PLANNER_RULE_IDS = ("K-REN-103", "K-REN-101", "K-AST-202", "K-WRT-205", "K-AST-203")
PLANNER_HEAD = """# 编辑计划器（系统提示词，自动组装，勿手改）

本文件由 ns_api.edits.build_planner_prompt() 从 knowledge/rules/*.yaml 与 knowledge/inbox/*.yaml（已采用的改法草案）组装；
改规则请改 knowledge，再调 POST /api/edits/planner-prompt/rebuild。

你是短剧生产系统的“修改计划器”。项目方会对一个对象（图片 / 视频 / 剧本段 / 提示词 / 资产字段）给出中文反馈，
可能带框选区域（0–1 相对坐标 [x, y, w, h]）或视频时间点。你要把反馈翻译成**一个**结构化修改计划，只输出 JSON，不要任何别的文字。

## 输出格式（JSON 对象）
{
  "understanding": "一句中文：你理解的问题",
  "action": "inpaint | edit | regen | refs | seed | prompt_only | video_rerun | text_rewrite | reject",
  "instruction": "给图像编辑模型（Qwen-Image 2.1 Edit）的修改指令：只写要改的地方和要保持不变的地方",
  "region": [x, y, w, h] 或 null,
  "strength": "small | medium | large",
  "use_identity_ref": true 或 false,
  "seed_change": true 或 false,
  "prompt_patch": {"find": "原提示词里的一段", "replace": "换成的文字"} 或 null,
  "video": {"seconds": 数字或 null, "steps": 数字或 null, "base": null 或基底 id, "last_frame_mode": null | "use" | "none" | "auto"} 或 null,
  "rewrite_brief": "给写作模型的改写要点（只在 text_rewrite 时）",
  "lock_conflicts": [{"rule": "HC-07 | HC-02 | SCRIPT", "message": "中文"}],
  "notes": "中文补充"
}

## 选 action 的规则
- 图片：有框选且问题在框内 → inpaint（region 用项目方的框，strength 一般 medium）；整体质感 / 光线 / 皮肤问题 → edit；
  构图 / 景别 / 人物动作错 → regen（整图重出，提示词不变，换 seed）；脸不像某角色 → edit 或 inpaint 且 use_identity_ref=true；
  只是提示词写错 → prompt_only + prompt_patch。
- 视频：动作 / 卡顿 / 不动 → video_rerun（seed_change=true，可调 seconds / steps）；提示词问题 → prompt_only。
- 剧本段 / 资产文字：text_rewrite，rewrite_brief 写改什么；你不写剧本正文，正文由写作模型改写，改完一律“待确认”。
- 提示词：prompt_only + prompt_patch（find 必须是原文里真实存在的一段）。
- 反馈要求违反下面的锁定规则 → action=reject，并在 lock_conflicts 里写明。

## 锁定规则（违反 = reject 或写进 lock_conflicts）
- HC-07：已锁定角色的外貌锚点（发色、发型、标志物）不得改变；林晚标志物 = 钻石水晶甲。修图只能让画面更接近锁定外貌，不能改锁定外貌。
- HC-01 / HC-02：所有角色都是 22 岁以上成年人；指令里不得出现任何未成年化词语。
- SCRIPT：剧情、台词不由计划器改；剧本文字只能由写作模型改写并标“待确认”，项目方确认后才写回。
- K-REN-103：出图提示词一律经系统编译器；你的 instruction 只是修改指令，系统会自动附上编译器的 LoRA、负面词和角色锁段。
"""


def _prel(p: Path) -> str:
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def _yaml_rules() -> list[dict]:
    import yaml
    out = []
    for p in sorted((KNOWLEDGE / "rules").glob("*.yaml")) + sorted((KNOWLEDGE / "inbox").glob("*edit_*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}      # 规则文件读坏 = 抛错（knowledge compile --check 也会拦）
        for r in d.get("rules") or []:
            if isinstance(r, dict):
                out.append({**r, "_src": _prel(p)})
    return out


def build_planner_prompt(write: bool = True) -> str:
    rules = _yaml_rules()
    pick = [r for r in rules if r.get("id") in PLANNER_RULE_IDS]
    learned = [r for r in rules if str(r.get("id", "")).startswith("K-EDT-E")]
    lines = [PLANNER_HEAD, "\n## 相关知识条目（knowledge/rules）"]
    for r in pick:
        lines.append(f"- {r['id']}（{r.get('status', '')}）{r.get('title', '')}：{r.get('then', '')}")
    if learned:
        lines.append("\n## 已沉淀的改法（knowledge/inbox，项目方采用过 ≥2 次；待确认）")
        for r in learned:
            lines.append(f"- {r['id']} {r.get('title', '')}：{r.get('then', '')}")
    txt = "\n".join(lines) + "\n"
    if write:
        PLANNER_PROMPT.parent.mkdir(parents=True, exist_ok=True)
        PLANNER_PROMPT.write_text(txt, encoding="utf-8")
    return txt


def planner_prompt() -> str:
    try:
        return PLANNER_PROMPT.read_text(encoding="utf-8")
    except OSError:
        return build_planner_prompt()


# ============================================================ 逻辑层：调用模型
def call_llm(purpose: str, system: str, user: str, max_tokens: int, override: dict | None = None) -> dict:
    """真调用（测试里 monkeypatch 掉）。默认关推理"""
    ov = dict(override or {})
    ov["params"] = {"reasoning": False, "temperature": 0.2 if purpose == "edit_plan" else None,
                    **(ov.get("params") or {})}
    rv = LLMC.resolve(purpose, ov)
    t0 = time.time()
    out = LLMC.complete_text(rv, system, user, max_tokens=max_tokens)
    usage = out.get("usage") or {}
    cost = None
    try:
        pr = LLMC.model_pricing(rv["id"]).get(rv["model"])
        if pr and usage:
            cost = round(usage.get("prompt_tokens", 0) * pr["prompt"] + usage.get("completion_tokens", 0) * pr["completion"], 5)
    except Exception:  # noqa: BLE001
        cost = None
    return {"content": out.get("content") or "", "usage": usage, "model": f"{rv['id']}/{rv['model']}",
            "seconds": round(time.time() - t0, 1), "cost_usd": cost}


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("模型没有返回 JSON")
    return json.loads(t[i:j + 1])


def _planner_user(ctx: dict, feedback: str, ann: dict | None) -> str:
    keep = {k: ctx.get(k) for k in ("type", "id", "shot_id", "stage", "n", "field", "node", "locked", "overridden")
            if ctx.get(k) is not None}
    parts = [f"对象：{json.dumps(keep, ensure_ascii=False)}", f"项目方反馈（原话）：{feedback}"]
    if ann:
        parts.append(f"标注：{json.dumps(ann, ensure_ascii=False)}")
    if ctx.get("compiled_prompt"):
        parts.append(f"当前出图提示词（编译器输出）：\n{ctx['compiled_prompt'][:2500]}")
    if ctx.get("prompt") and ctx.get("prompt") != ctx.get("compiled_prompt"):
        parts.append(f"这一版实际用的提示词 / 指令：\n{str(ctx['prompt'])[:1500]}")
    if ctx.get("spec"):
        parts.append(f"Shot Spec：{json.dumps(ctx['spec'], ensure_ascii=False)[:1500]}")
    if ctx.get("script_text"):
        parts.append(f"剧本该镜原文（只读，不改）：\n{ctx['script_text']}")
    if ctx.get("identity_refs"):
        parts.append("身份参考：" + "、".join(f"{r['character']}（{r['path']}）" for r in ctx["identity_refs"]))
    if ctx.get("text") is not None and ctx["type"] in ("script", "prompt", "asset"):
        parts.append(f"当前文字：\n{str(ctx['text'])[:6000]}")
    parts.append("只输出 JSON 修改计划。")
    return "\n\n".join(parts)


def _lock_checks(texts: list[str]) -> list[dict]:
    import sys
    p = str(REPO / "tools" / "pipeline")
    if p not in sys.path:
        sys.path.insert(0, p)
    import hard_constraints as HC  # noqa: PLC0415
    out = []
    for t in texts:
        if not t:
            continue
        out += HC.check_look_lock(t, ["痣", "mole"])
        out += [x for x in HC.check_text(t) if x["level"] == "block"]
    return out


def normalize_plan(raw: dict, ctx: dict, ann: dict | None) -> dict:
    """模型计划 → 系统可执行的计划；不合法的字段改成默认并在 fixes 里说明；锁定规则机检"""
    plan = {k: raw.get(k) for k in ("understanding", "action", "instruction", "region", "strength", "use_identity_ref",
                                    "seed_change", "prompt_patch", "video", "rewrite_brief", "lock_conflicts", "notes")}
    fixes = []
    t = ctx["type"]
    allowed = {"image": IMAGE_ACTIONS, "video": VIDEO_ACTIONS, "script": TEXT_ACTIONS, "prompt": ("prompt_only",),
               "asset": TEXT_ACTIONS}[t] + ("reject",)
    if plan["action"] not in allowed:
        fixes.append(f"action {plan['action']!r} 不适用于 {t}，改成 {allowed[0]}")
        plan["action"] = {"image": "edit", "video": "video_rerun", "prompt": "prompt_only"}.get(t, "text_rewrite")
    box = (ann or {}).get("box") or ((ann or {}).get("boxes") or [None])[0]
    if t == "image":
        if box and plan["action"] in ("edit", "inpaint"):
            if plan["action"] != "inpaint":
                fixes.append("项目方框选了区域 → 局部重绘（inpaint）")
            plan["action"], plan["region"] = "inpaint", box
        if plan["action"] == "inpaint" and not _valid_box(plan.get("region")):
            plan["region"] = box if _valid_box(box) else None
            if plan["region"] is None:
                fixes.append("没有有效的区域 → 改成整图编辑（edit）")
                plan["action"] = "edit"
        if plan["action"] in ("edit", "inpaint", "refs") and not (plan.get("instruction") or "").strip():
            plan["instruction"] = ctx.get("feedback") or ""
            fixes.append("计划没给修改指令 → 用项目方原话")
        if plan.get("strength") not in STRENGTHS:
            plan["strength"] = "medium"
        if plan["action"] == "refs" and not ctx.get("identity_refs"):
            fixes.append("没有可用的身份参考 → 改成整图编辑")
            plan["action"] = "edit"
    plan["use_identity_ref"] = bool(plan.get("use_identity_ref")) and bool(ctx.get("identity_refs"))
    if plan["action"] == "prompt_only":
        pp = plan.get("prompt_patch") or {}
        if not isinstance(pp, dict) or not pp.get("find") or pp["find"] not in str(ctx.get("text") or ctx.get("prompt") or ""):
            fixes.append("prompt_patch.find 不在原文里 → 作废这处替换（需要重新描述）")
            plan["prompt_patch"] = None
    conflicts = [c for c in (plan.get("lock_conflicts") or []) if isinstance(c, dict)]
    conflicts += _lock_checks([plan.get("instruction") or "", ((plan.get("prompt_patch") or {}).get("replace") or "")])
    plan["lock_conflicts"] = conflicts
    if any(c.get("level") == "block" for c in conflicts) and plan["action"] != "reject":
        fixes.append("计划触发锁定规则（block）→ 不执行")
        plan["action"] = "reject"
    plan["fixes"] = fixes
    return plan


def _valid_box(b) -> bool:
    try:
        x, y, w, h = (float(v) for v in b)
    except (TypeError, ValueError):
        return False
    return 0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1


def make_plan(ctx: dict, feedback: str, ann: dict | None, llm: dict | None) -> tuple[dict, dict]:
    ctx = {**ctx, "feedback": feedback}
    res = call_llm("edit_plan", planner_prompt(), _planner_user(ctx, feedback, ann), PLAN_MAX_TOKENS, llm)
    try:
        raw = _extract_json(res["content"])
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(502, f"逻辑模型返回的不是合法 JSON：{e}；原文前 300 字：{res['content'][:300]}")
    return normalize_plan(raw, ctx, ann), {k: v for k, v in res.items() if k != "content"} | {"raw": res["content"][:4000]}


# ============================================================ 执行层：图片
def _contract_cfg() -> dict:
    """config/gen_contract.json（REFLOCK：LoRA 白名单 / 禁用、后缀禁用词）"""
    return json.loads((REPO / "config" / "gen_contract.json").read_text(encoding="utf-8"))   # 契约配置缺 / 坏 = 抛错（失败关闭，不当成没有禁用词）


def clean_instruction(text: str) -> tuple[str, list[str]]:
    """生成契约 I7：提示词里不得出现旧后缀禁用词（含否定句里的“去掉油光”）→ 去掉含禁用词的分句，记下来"""
    banned = [w for w in (_contract_cfg().get("suffix_banned") or []) if w]
    if not banned:
        return text, []
    parts = re.split(r"(?<=[，,；;。\n])", text)
    keep, drop = [], []
    for seg in parts:
        (drop if any(w.lower() in seg.lower() for w in banned) else keep).append(seg)
    return "".join(keep).strip("，,；; "), [d.strip() for d in drop if d.strip()]


def compose_instruction(plan: dict, ctx: dict) -> str:
    """改图指令 = 计划指令（去掉契约禁用词分句）+ 编译器角色锁段 + 局部重绘说明。参考图的“图N是…”标注由
    ns_agent.asset_refs 槽位规划的 prompt_prefix 给（见 contract_inputs），这里不再写图号"""
    ins, dropped = clean_instruction((plan.get("instruction") or "").strip())
    if dropped:
        plan.setdefault("fixes", []).append(f"去掉了含契约禁用词的分句（I7）：{dropped}")
    anchor = identity_anchor(ctx.get("compiled_prompt") or "")
    if anchor:
        # 11-02 17:0x 项目方：写“男主角穿了女孩子的衣服”→ 提交被“没过”拒收。根因：编译稿的角色锁段（取 200 字）里夹着旧出图后缀
        # （“奶油般柔焦虚化”…），原样拼进指令 → I7 禁用词。锁段也要去掉含禁用词的分句，不能让系统自己拼出的内容挡住项目方的修改
        anchor, dropped_a = clean_instruction(anchor)
        if dropped_a:
            plan.setdefault("fixes", []).append(f"角色锁段里去掉了含契约禁用词的分句（I7）：{dropped_a}")
    if anchor:
        ins += f"\n保持角色锁定外貌（编译器角色锁段，不得改变）：{anchor}"
    if plan["action"] == "inpaint":
        ins += "\n只改需要修改的区域，其余画面保持不变。"
    return ins


def edit_project(run: str | None = None) -> str:
    """改图 / 导演加强的槽位规划项目 = 镜头所在的剧（NS_RUN 或 runs.json primary，ns_agent.run_paths.current_run）；
    该剧在 config/recipes/asset_refs.json 没有项目配置 → 抛错，不退回 series10_v1（config/edit_engines.json 的 project 字段已废）"""
    from ns_agent import asset_refs as AR
    r = run or _RP.current_run()
    if not r or not AR.project_cfg(r):
        raise ValueError(f"改图槽位规划：当前剧 {r!r} 没有资产项目配置（不退回 V1，失败关闭）")
    return r


def contract_inputs(ctx: dict, instruction: str, engine: dict) -> dict:
    """生成契约 preflight 请求（REFLOCK：参考图 = ns_agent.asset_refs 槽位规划 plan.files，提示词 = plan.prompt_prefix +
    改图指令 + 默认出图预设后缀 I7；LoRA 过白名单 I8）。原图作底图（init_image），不占参考槽"""
    shot = ctx.get("shot_id")
    model = engine.get("contract_model") or "qwen_image_2.1"
    project = edit_project()                       # OVERSIGHT-F P1-5a：按当前剧取（V2 不按 V1 规划参考图）；取不到 = ValueError（失败关闭）
    cc = _contract_cfg()
    allow, banned = set(cc.get("lora_allow") or {}), set(cc.get("lora_banned") or {})
    comp = _compiled(shot)
    loras = [[f, float(w)] for f, w in (comp.image_loras if comp else []) if f not in banned and (not allow or f in allow)]
    try:
        from ns_agent.gen_contract import style as ST
        suffix = ST.image_suffix()
    except Exception:  # noqa: BLE001
        suffix = ""
    req = {"kind": "image", "model": model, "project": project, "shot_id": shot, "loras": loras,
           "compiled_by": "ns_api.edits ← ns_agent.compiler（角色锁段 / 负面词）+ ns_agent.asset_refs（参考槽位）"}
    images, prefix, err = [], "", None
    try:
        from ns_agent import asset_refs as AR
        ep, sh = P.find_shot(_app()._script, shot)
        sr, plan = AR.plan_for(project, ep, sh, model)
        images, prefix = list(plan.files), plan.prompt_prefix
        req.update(asset_refs=AR.record(sr, plan),
                   cast=[{"name": c.name, "presence": c.presence, "x": getattr(c, "x", None), "depth": getattr(c, "depth", None)}
                         for c in (getattr(sh, "cast", None) or [])])
    except Exception as e:  # noqa: BLE001  没有镜头 / 项目参考配置 → 请求不完整，preflight 会列出缺什么
        err = f"{type(e).__name__}: {e}"[:300]
    prompt = "\n".join(x for x in (prefix, instruction, suffix) if x)
    req.update(prompt=prompt, refs=images)
    return {"req": req, "images": images, "prompt": prompt, "loras": loras, "error": err}


def composite_region(original: Path, edited: Path, box, out: Path) -> None:
    """局部重绘：编辑结果只在框内（羽化）贴回原图；框外像素 = 原图"""
    from PIL import Image, ImageDraw, ImageFilter
    ed = Image.open(edited).convert("RGB")
    org = Image.open(original).convert("RGB")
    if org.size != ed.size:
        org = org.resize(ed.size, Image.LANCZOS)
    W_, H_ = ed.size
    x, y, w, h = (float(v) for v in box)
    mask = Image.new("L", ed.size, 0)
    ImageDraw.Draw(mask).rectangle([x * W_, y * H_, (x + w) * W_, (y + h) * H_], fill=255)
    r = max(2, int(min(W_, H_) * FEATHER))
    mask = mask.filter(ImageFilter.GaussianBlur(r))
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.composite(ed, org, mask).save(out)


ENGINES_FILE = REPO / "config" / "edit_engines.json"
ENGINE_DEFAULTS = {
    "default": "qwen_image_2_1_edit",
    "gen_contract": "if_available",
    "engines": {"qwen_image_2_1_edit": {"label": "Qwen-Image 2.1 Edit（现状）", "builder": "qwen_edit", "max_refs": 3,
                                        "enabled": True}},
}


def engines_cfg() -> dict:
    try:
        cfg = json.loads(ENGINES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    out = {**ENGINE_DEFAULTS, **{k: v for k, v in cfg.items() if k != "engines"}}
    out["engines"] = {**ENGINE_DEFAULTS["engines"], **(cfg.get("engines") or {})}
    return out


def pick_engine(name: str | None) -> tuple[str, dict]:
    cfg = engines_cfg()
    eid = name or cfg["default"]
    e = cfg["engines"].get(eid)
    if not e:
        raise HTTPException(422, f"没有这个编辑模型：{eid}（config/edit_engines.json）")
    if not e.get("enabled", True):
        raise HTTPException(409, f"编辑模型 {e.get('label') or eid} 还没启用（config/edit_engines.json enabled=false）")
    if e.get("builder") == "template" and not (REPO / str(e.get("graph") or "")).is_file():
        raise HTTPException(409, f"编辑模型 {e.get('label') or eid} 的工作流模板不存在：{e.get('graph')}")
    return eid, e


def _fill(node, vals: dict):
    """模板占位：整串等于 {{k}} → 原类型值；串里含 {{k}} → 文本替换"""
    if isinstance(node, dict):
        return {k: _fill(v, vals) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, vals) for v in node]
    if isinstance(node, str):
        m = re.fullmatch(r"\{\{(\w+)\}\}", node)
        if m and m.group(1) in vals:
            return vals[m.group(1)]
        return re.sub(r"\{\{(\w+)\}\}", lambda mm: str(vals.get(mm.group(1), mm.group(0))), node)
    return node


def build_edit_workflow(engine: dict, *, prompt: str, negative: str, images: list[str], size, seed: int, prefix: str,
                        loras, init: str | None, denoise: float) -> dict:
    """可插拔编辑模型（项目方：Image 2.1 的 edit 不行，BAKEOFF 对比 Qwen-Image-Edit 2511 / Klein / FireRed / Krea2 后切换）：
    builder = qwen_edit（现有 Image 2.1 编辑图）| template（ComfyUI API 格式模板 + {{prompt}} {{negative}} {{image1}}… 占位）"""
    from ns_render import workflows as W
    if engine.get("builder", "qwen_edit") == "qwen_edit":
        return W.qwen_edit(prompt, negative, images[: 1 + int(engine.get("max_refs", 3))], *size, seed, prefix,
                           m=P.QWEN_TURBO, loras=loras, ref_resolution=0, crop=False, init_image=init, denoise=denoise)
    graph = json.loads((REPO / engine["graph"]).read_text(encoding="utf-8"))
    vals = {"prompt": prompt, "negative": negative, "seed": seed, "width": size[0], "height": size[1],
            "prefix": prefix, "denoise": denoise, "init_image": init or images[0]}
    for i, name in enumerate(images[: 1 + int(engine.get("max_refs", 3))], 1):
        vals[f"image{i}"] = name
    return _fill(graph, vals)


def gen_contract(stage: str, payload: dict) -> dict:
    """GEN_CONTRACT（docs/GEN_CONTRACT.md）preflight / postflight：ns_agent.gen_contract（REFLOCK 实现中）。
    模块在 → 调它，不通过就拦；模块不在 → config gen_contract=required 时拦，if_available 时记“未接入”放行"""
    try:
        from ns_agent import gen_contract as GC  # noqa: PLC0415
    except ImportError:
        if engines_cfg().get("gen_contract") == "required":
            raise HTTPException(409, "GEN_CONTRACT 校验器还没接入（ns_agent.gen_contract），按配置 required 不提交")
        return {"status": "unavailable", "note": "ns_agent.gen_contract 未接入（REFLOCK 实现中）"}
    fn = getattr(GC, stage, None)
    if fn is None:
        return {"status": "unavailable", "note": f"ns_agent.gen_contract 没有 {stage}()"}
    rep = fn("image", payload)
    rep = rep if isinstance(rep, dict) else getattr(rep, "__dict__", {"ok": bool(rep)})
    return {"status": "pass" if rep.get("ok") else "fail", **rep}


def _front(client) -> None:
    """插队（BAKEOFF 分的道：ComfyUI /prompt 带 front=true，只占 1 个任务）"""
    from ns_render.comfy_client import ComfyError, ComfyUnavailable
    raw = getattr(client, "_json", None)
    if raw is None:
        return

    def post(wf):
        try:
            body = {"prompt": wf, "client_id": getattr(client, "client_id", "ns_edit"), "front": True}
            tag = getattr(client, "ns_tag", None)     # GPU 任务归属标签（jobs 工作线程设的，K-OPS-G01）
            if isinstance(tag, dict) and tag:
                body["extra_data"] = {"ns_tag": dict(tag)}
            return raw("/prompt", body)
        except ComfyUnavailable:
            raise
        except ComfyError as e:
            if getattr(e, "status", None) == 400:
                try:
                    return {"_http400": json.loads(e.body), "_msg": str(e)}
                except (TypeError, ValueError):  # arch-ok: 400 的正文不是 JSON → 按原错误抛出（下一行 raise），不吞
                    pass
            raise
    client._post_prompt = post


def remote_scores(image: Path, lane) -> dict:
    """出图机器上的人脸 / 手打分（REFLOCK tools/gen_contract/remote_score.py，CPU，约 10–20 s，先 scp 上去、打完删）。
    config/edit_engines.json remote_score=false 或道不在 gpu33 / gpu36 → 不打（Q1/Q3/Q5/Q6 记 untested）"""
    if not engines_cfg().get("remote_score", True):
        return {}
    host = str(lane or "").split(":")[0]
    if host not in ("gpu33", "gpu36"):
        return {}
    import sys
    p = str(REPO / "tools" / "gen_contract")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        import remote_score as RS  # noqa: PLC0415
        m = RS.score_local_files(host, {"img": str(image)})
        return {"remote": (m.get("items") or {}).get("img"), "cross": m.get("cross"), "hands": (m.get("hands") or {}).get("img")}
    except Exception as e:  # noqa: BLE001  打分失败 → 只记原因，相关项 untested
        return {"remote_error": f"{type(e).__name__}: {e}"[:300]}


def _postflight(image: Path, req: dict, lane=None) -> dict:
    """出图后契约质检（Q1–Q7；没测到的 = untested，不算通过）。失败不影响版本入链，结果记在版本上并在界面标出"""
    rs = remote_scores(image, lane) if lane is not None else {}
    try:
        out = gen_contract("postflight", {"image": str(image), "request": req, "remote": rs.get("remote"),
                                          "cross": rs.get("cross"), "hands": rs.get("hands")})
        if rs.get("remote_error"):
            out["remote_error"] = rs["remote_error"]
        return out
    except HTTPException as e:
        return {"status": "error", "detail": str(e.detail)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"[:300]}


def base_quality(path: Path) -> dict | None:
    """底图质感（契约 Q4，REFLOCK K-REV-232 第二轮口径：整图 Laplacian（宽 768）/ 平均饱和度 / 油光）。
    → {"ok", "reasons", "metrics"}；算不了 → None（不拦）"""
    try:
        from PIL import Image
        from ns_agent.gen_contract import postflight as PF
        t4 = (_contract_cfg().get("image_thresholds") or {}).get("Q4_texture") or {}
        q = PF.texture(Image.open(path).convert("RGB"))
    except Exception as e:  # noqa: BLE001  # arch-ok: 底图质感只作参考（调用方把 None 当“未测”，不当通过），原因写日志
        import logging
        logging.getLogger("ns_api.edits").warning("底图质感算不了（未测）：%s：%r", path, e)
        return None
    bad = []
    if "lap_full" in q and t4.get("lap_full_min") is not None and q["lap_full"] < t4["lap_full_min"]:
        bad.append(f"清晰度（整图 Laplacian，宽 768）{q['lap_full']} < {t4['lap_full_min']}（塑料 / 糊）")
    if "sat_mean" in q and t4.get("sat_mean_max") is not None and q["sat_mean"] > t4["sat_mean_max"]:
        bad.append(f"平均饱和度 {q['sat_mean']} > {t4['sat_mean_max']}")
    if "specular" in q and t4.get("specular_max") is not None and q["specular"] > t4["specular_max"]:
        bad.append(f"油光 {q['specular']} > {t4['specular_max']}")
    return {"ok": not bad, "reasons": bad, "metrics": q, "thresholds": t4}


def _image_job(it: dict, ctx: dict, plan: dict, gpu, engine_name: str | None = None, front: bool = False) -> dict:
    from ns_api import frame_jobs as FJ
    from ns_render import frame_edit as FE
    action = plan["action"]
    shot = ctx.get("shot_id")
    instruction = compose_instruction(plan, ctx)
    refs = ([{"path": r["path"], "role": "identity", "asset_id": r.get("asset_id")} for r in ctx.get("identity_refs") or []][:1]
            if plan.get("use_identity_ref") else [])
    regen = action in ("regen", "seed")
    if ctx["kind"] == "take" and regen:   # 整图重出：原出图流水线（编译器提示词）
        body = FJ.FrameJobBody(stage="first" if ctx["stage"] == "image" else "last", mode="regen",
                               parent=ctx["n"], seed=int(time.time()) % 2_000_000_000, gpu=gpu)
        job = FJ.create_frame_job(shot, body)
        it["result"] = {"job_id": job["job_id"], "kind": "take", "shot_id": shot, "stage": ctx["stage"],
                        "parent": ctx["n"], "engine": "frame-jobs regen"}
        return job
    eid, engine = pick_engine(engine_name)
    src = _abs(ctx["file"])
    ci = contract_inputs(ctx, instruction, engine)
    images = ci["images"] or [r["path"] for r in refs]
    prompt_full = ci["prompt"] if ci["images"] else instruction
    pre = gen_contract("preflight", {**ci["req"], "edit": {"object": ctx["id"], "action": action, "source": ctx["file"],
                                                           "engine": eid, "feedback": it.get("feedback")}})
    if ci["error"]:
        pre["build_error"] = ci["error"]
    if pre["status"] == "fail":
        raise HTTPException(422, {"message": "GEN_CONTRACT preflight 没过，不提交", "preflight": pre})
    lane = FJ._lane(gpu)
    seed = int(time.time()) % 2_000_000_000
    obj_id = ctx["id"]

    def run(client, job):
        if front:
            _front(client)
        c_ = FJ._Cancellable(client, job, None)
        attempts: list[dict] = []
        adir = data_dir() / "attempts" / it["edit_id"]
        cur = {"engine_id": eid, "engine": engine, "ci": ci, "seed": seed, "region": plan.get("region"), "pre": pre,
               "prompt": prompt_full, "images": images}
        post: dict = {}
        for k in range(MAX_RETRY + 1):
            change = "首次"
            if k:
                nxt, change = next_attempt(cur, k, plan, ctx, instruction, it)
                if nxt is None:
                    attempts.append({"k": k, "skipped": change})
                    break
                cur = nxt
            res = _generate(c_, job, cur, ctx, plan, src, shot, regen, obj_id, adir / f"a{k}.png")
            post = _postflight(res["final"], cur["ci"]["req"], job.get("gpu"))
            ok = post.get("status") == "pass"
            attempts.append({"k": k, "change": change, "engine": cur["engine_id"], "seed": cur["seed"],
                             "region": cur["region"], "file": _repo_rel(res["final"]), "ok": ok,
                             "failed": [i.get("id") for i in post.get("items") or [] if i.get("status") in ("fail", "untested")],
                             "reasons": (post.get("reasons") or [])[:8]})
            _finish(it["edit_id"], {"attempts": attempts}, keep_status=True)
            if ok:
                res["meta"].update(postflight=post, attempts=attempts)
                if ctx["kind"] == "take":
                    return _save_take_result(it, ctx, c_, res, plan, job)
                return _save_chain_result(it, ctx, res, plan)
            if J.cancelled(job):
                raise J.Cancelled()
        out = {"contract_failed": True, "attempts": attempts, "postflight": post,
               "message": f"按生成契约自动重出 {sum(1 for a in attempts if 'file' in a) - 1} 次仍未通过：不作为候选给项目方"
                          "（文件留在 data/edits/attempts/ 备查）"}
        _finish(it["edit_id"], out)
        return {"take": None, **out}

    job = J.submit("frame", shot, lane, run, params={"edit_id": it["edit_id"], "object": obj_id, "action": action,
                                                      "engine": eid},
                   eta_s=J.estimate("frame", lane), stage="edit", mode=action)
    it["result"] = {"job_id": job["job_id"], "kind": "take" if ctx["kind"] == "take" else "chain",
                    "shot_id": shot, "stage": ctx.get("stage"), "parent": ctx.get("n"),
                    "parent_v": ctx.get("chain_v", 0), "instruction": prompt_full, "refs": images, "engine": eid,
                    "preflight": pre}
    return job


# ------------------------------------------------------------------ 契约自动重出（GEN_CONTRACT §0：≤3 次，每次只改一个维度）
MAX_RETRY = 3
RETRY_DIMS = ("seed", "region", "engine")


def _grow_box(box, k: float = 0.25):
    x, y, w, h = (float(v) for v in box)
    nw, nh = min(1.0, w * (1 + k)), min(1.0, h * (1 + k))
    nx, ny = min(max(0.0, x - (nw - w) / 2), 1 - nw), min(max(0.0, y - (nh - h) / 2), 1 - nh)
    return [round(nx, 4), round(ny, 4), round(nw, 4), round(nh, 4)]


def _other_engine(current: str) -> tuple[str, dict] | None:
    cfg = engines_cfg()
    for k, e in cfg["engines"].items():
        if k == current or not e.get("enabled", True):
            continue
        if e.get("builder") == "template" and not (REPO / str(e.get("graph") or "")).is_file():
            continue
        return k, e
    return None


def next_attempt(cur: dict, k: int, plan: dict, ctx: dict, instruction: str, it: dict) -> tuple[dict | None, str]:
    """第 k 次重出（1..3）：按 换 seed → 调局部重绘区域 → 换编辑模型 的顺序取第 k 个维度；
    该维度不适用（不是局部重绘 / 没有别的已启用模型 / 新模型 preflight 不过）→ 换 seed。每次只改一个维度"""
    dim = RETRY_DIMS[(k - 1) % len(RETRY_DIMS)]
    nxt = dict(cur)
    if dim == "region" and plan["action"] == "inpaint" and cur.get("region"):
        nxt["region"] = _grow_box(cur["region"])
        return nxt, f"调局部重绘区域：{cur['region']} → {nxt['region']}（外扩 25%）"
    if dim == "engine":
        alt = _other_engine(cur["engine_id"])
        if alt:
            ci2 = contract_inputs(ctx, instruction, alt[1])
            pre2 = gen_contract("preflight", {**ci2["req"], "edit": {"object": ctx["id"], "action": plan["action"],
                                                                     "engine": alt[0], "retry": k}})
            if pre2["status"] != "fail":
                nxt.update(engine_id=alt[0], engine=alt[1], ci=ci2, pre=pre2,
                           prompt=ci2["prompt"] if ci2["images"] else instruction,
                           images=ci2["images"] or cur["images"])
                return nxt, f"换编辑模型：{cur['engine_id']} → {alt[0]}"
    nxt["seed"] = (int(cur["seed"]) + 7919 * k) % 2_000_000_000
    return nxt, f"换 seed：{cur['seed']} → {nxt['seed']}" + ("" if dim == "seed" else f"（{dim} 不适用）")


def _generate(c_, job: dict, cur: dict, ctx: dict, plan: dict, src: Path, shot: str | None, regen: bool, obj_id: str,
              out: Path) -> dict:
    """出 1 张 → out（局部重绘时 out = 贴回原图后的结果，另存 *_raw.png）"""
    from ns_render import frame_edit as FE
    try:
        comp = P.compile_with_edits(_app()._script, shot, P.available_loras(c_)) if shot else None
    except Exception:  # noqa: BLE001
        comp = None
    negative = P.image_negative(comp, P.QWEN_TURBO) if comp else ""
    loras = [tuple(x) for x in cur["ci"]["loras"]]      # 编译器 LoRA 过契约白名单（I8：lin_wan_qi 已禁）
    from PIL import Image
    with Image.open(src) as im:
        size = FE._fit_size(im.size, 1920)
    # 参考槽 = 契约槽位规划（身份脸 > 造型设定图 > 单品 > 场景）；原图作底图。没有槽位规划时原图兼作 图1
    names = [FE._input(c_, REPO / f, None, FE.REF_MAX_SIDE) for f in cur["images"]]   # 槽位文件相对项目根
    if not names:
        names = [FE._input(c_, src, None, 1344)]
    st = None if regen else (plan.get("strength") or "medium")
    init = FE._input(c_, src, tuple(size)) if st else None
    prompt = comp.image_prompt if (regen and comp) else cur["prompt"]
    wf = build_edit_workflow(cur["engine"], prompt=prompt, negative=negative, images=names, size=size, seed=cur["seed"],
                             prefix=f"ns_final/edits_{_key(obj_id)}", loras=loras, init=init,
                             denoise=FE.EDIT_DENOISE[st] if st else 1.0)
    entry, secs = c_.run(wf, timeout_s=900)
    item = next(f for f in c_.output_files(entry) if f["filename"].endswith(".png"))
    out.parent.mkdir(parents=True, exist_ok=True)
    region = cur.get("region") if plan["action"] == "inpaint" else None
    raw = out.with_name(out.stem + "_raw.png") if region else out
    c_.download(item, raw)
    if region:
        composite_region(src, raw, region, out)
    meta = {"seed": cur["seed"], "seconds": round(secs, 1), "workflow": f"edit_{cur['engine_id']}_{plan['action']}",
            "engine": cur["engine_id"], "instruction": prompt, "negative": negative, "loras": [list(x) for x in loras],
            "refs": [{"path": f} for f in cur["images"]], "size": list(size), "gpu": job.get("gpu"),
            "compiler": "ns_agent.compiler" if comp else None, "region": region, "preflight": cur["pre"]}
    return {"final": out, "raw": raw if region else None, "meta": meta, "remote": c_}


def _save_chain_result(it: dict, ctx: dict, res: dict, plan: dict) -> dict:
    """通过契约的那一张 → 版本链新版本（未通过的尝试不进版本链）"""
    obj_id = ctx["id"]
    with _lock:
        ch = load_chain(obj_id, ctx["original"])
        v = max(x["v"] for x in ch["versions"]) + 1
        vdir = chain_path(obj_id).parent
        vdir.mkdir(parents=True, exist_ok=True)
        final = vdir / (f"v{v:03d}.png" if res["raw"] else f"v{v:03d}_raw.png")
        shutil.copyfile(res["final"], final)
        raw = None
        if res["raw"]:
            raw = vdir / f"v{v:03d}_raw.png"
            shutil.copyfile(res["raw"], raw)
        rec = {"v": v, "file": _repo_rel(final), "raw_file": _repo_rel(raw) if raw else None, "edit_id": it["edit_id"],
               "parent": ctx.get("chain_v", 0), "created_at": P.now(), **res["meta"], "label": f"编辑 v{v}"}
        ch["versions"].append(rec)
        save_chain(ch)       # 不改 current：项目方采用后才设为当前
    out = {"version": v, "file": rec["file"], "url": _url(rec["file"]), "postflight": rec["postflight"],
           "attempts": rec["attempts"]}
    _finish(it["edit_id"], out)
    return {"take": None, **out}


def _save_take_result(it: dict, ctx: dict, c_, res: dict, plan: dict, job: dict) -> dict:
    """画布 take：通过契约的那一张挂在父版本下（修改链 parent），不设为当前（采用时才设）；未通过的尝试不进 takes"""
    from ns_render import frame_edit as FE
    from ns_render.comfy_client import remote_info
    meta = res["meta"]
    shot, stage = ctx["shot_id"], ctx["stage"]
    src_take = ctx["take"]
    with P.shot_lock(shot):
        n = P._next_n(shot, stage)
    rel_dir = RP.take_rel_dir(P.shot_dir(shot), P.DATA, P.RENDERS)   # W33
    rel = f"{rel_dir}/{stage}_{n:03d}_{FE.unique_tag(job)}.png"
    dest = P.DATA / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(res["final"], dest)
    unmasked = None
    if res["raw"]:
        un = dest.with_name(dest.stem + "_unmasked.png")
        shutil.copyfile(res["raw"], un)
        unmasked = un.relative_to(P.DATA).as_posix()
    basis = FE.chain_basis(P.load_takes(shot), src_take)
    take = P.Take(n=n, stage=stage, file=rel, seed=meta["seed"], prompt=meta["instruction"], negative=meta["negative"],
                  seconds=meta["seconds"], created_at=P.now(), workflow=meta["workflow"],
                  reference=f"data/{src_take['file']}",
                  references=[f"data/{src_take['file']} ({stage} v{src_take['n']})", *(r["path"] for r in meta["refs"])],
                  parent=src_take["n"], mode="refs" if meta["refs"] else "instruct", instruction=meta["instruction"],
                  strength=plan.get("strength"), refs=meta["refs"] or None,
                  from_first=src_take.get("from_first") if stage == "last" else None,
                  gpu=job.get("gpu"), job_id=job.get("id"), source="gen" if stage == "last" else None,
                  remote=remote_info(c_, dest), basis_prompt=basis, look_hash=src_take.get("look_hash"),
                  inputs_sha=src_take.get("inputs_sha"), bible_version=src_take.get("bible_version"),
                  deps={k: v for k, v in (src_take.get("deps") or {}).items() if not k.startswith("preset:")} or None)
    P._add_take(shot, take, activate=False)
    n = take.n     # 出图期间同阶段号被占 → _add_take 顺延
    FE.annotate(shot, stage, n, edit_id=it["edit_id"], edit_engine=meta["engine"], edit_unmasked=unmasked,
                edit_region=meta.get("region") if unmasked else None,
                gen_contract={"pre": meta["preflight"], "post": meta["postflight"], "attempts": meta["attempts"]})
    out = {"take_n": n, "file": f"data/{rel}", "url": f"/files/{rel}", "postflight": meta["postflight"],
           "attempts": meta["attempts"]}
    _finish(it["edit_id"], out)
    return {"take": {**take.model_dump(), "url": f"/files/{rel}"}, **out}


# ============================================================ 执行层：视频
def _video_job(it: dict, ctx: dict, plan: dict, gpu) -> dict:
    from ns_api import video_jobs as VJ
    v = plan.get("video") or {}
    params = (ctx.get("take") or {}).get("params") or {}
    req = VJ.VideoJobRequest(parent=ctx["n"], seed=int(time.time()) % 2_000_000_000 if plan.get("seed_change", True) else params.get("seed"),
                             seconds=v.get("seconds"), steps=v.get("steps"), base=v.get("base"),
                             last_frame_mode=v.get("last_frame_mode"), gpu=gpu)
    out = VJ.create_video_job(ctx["shot_id"], req)
    if not isinstance(out, dict):    # JSONResponse 409：首尾帧没定稿
        body = json.loads(out.body.decode("utf-8"))
        raise HTTPException(409, body.get("detail") or "不能出视频")
    it["result"] = {"job_id": out["job_id"], "kind": "take", "shot_id": ctx["shot_id"], "stage": "video",
                    "parent": ctx["n"], "params": req.model_dump(exclude_none=True)}
    return out


# ============================================================ 执行层：文本（写作模型改写，待确认）
WRITER_SYSTEM = ("你是写作方。按“修改要点”改写下面这段文字，只改要点涉及的地方，其余逐字保留，格式（标题、表格、字段名）保持不变。"
                 "所有角色都是 22 岁以上成年人；已锁定角色的发色、发型、标志物不得改变。只输出改写后的全文，不要解释。")


def _text_rewrite(it: dict, ctx: dict, plan: dict, llm: dict | None) -> dict:
    src = str(ctx.get("text") or "")
    if ctx["type"] == "prompt" and plan.get("prompt_patch"):
        pp = plan["prompt_patch"]
        new, meta = src.replace(pp["find"], pp.get("replace") or "", 1), {"by": "prompt_patch"}
    else:
        if ctx["type"] == "prompt":   # 提示词没有可用替换 → 交写作模型
            pass
        user = f"修改要点：{plan.get('rewrite_brief') or plan.get('instruction') or it['feedback']}\n\n原文：\n{src}"
        res = call_llm("script_write", WRITER_SYSTEM, user, REWRITE_MAX_TOKENS, llm)
        new = res["content"].strip()
        meta = {k: v for k, v in res.items() if k != "content"} | {"by": "writer"}
    checks = _lock_checks([new])
    chain = None
    if ctx["type"] == "script":
        chain = _chain_validate(ctx, new)
    it["result"] = {"kind": "proposal", "status": "待确认", "text": new, "before_sha": hashlib.sha256(src.encode()).hexdigest()[:16],
                    "writer": meta, "lock_checks": checks, "chain_check": chain,
                    "diff": _diff(src, new)}
    return it["result"]


def _diff(a: str, b: str) -> str:
    import difflib
    return "\n".join(list(difflib.unified_diff(a.splitlines(), b.splitlines(), "当前", "修改后", lineterm="", n=1))[:400])


def _chain_validate(ctx: dict, text: str) -> dict | None:
    try:
        from ns_api import story_runs as SR
        d = SR._run_dir(ctx["run_id"])
        link = SR.LINK_OF[ctx["node"]]
        rep, _obj, _ = SR._rc().validate(link, text, SR._ctx_upto(d, link))
        return {"ok": rep.ok, "report": rep.as_dict()}
    except HTTPException as e:
        return {"ok": None, "error": str(e.detail)}
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "error": f"{type(e).__name__}: {e}"[:300]}


# ============================================================ 结果回写
def _finish(edit_id: str, extra: dict, keep_status: bool = False) -> None:
    with _lock:
        try:
            it = _load_item(edit_id)
        except HTTPException:
            return
        it["result"] = {**(it.get("result") or {}), **extra}
        if not keep_status:
            if extra.get("contract_failed"):
                it["status"] = "contract_failed"
            elif "version" in extra or "take_n" in extra:
                it["status"] = "done"
        _save_item(it)
        if not keep_status and extra.get("contract_failed"):
            ledger("contract_failed", it)


def _sync_job(it: dict) -> dict:
    """把任务状态并进编辑记录（take 类结果在任务完成时拿到新版本号）"""
    r = it.get("result") or {}
    jid = r.get("job_id")
    if not jid or it.get("status") in ("adopted", "rejected", "rolled_back"):
        return it
    j = J.get(jid)
    if not j:
        return it
    it["job"] = {k: j.get(k) for k in ("state", "gpu", "eta_s", "started_at", "finished_at", "error", "wall_s")}
    changed = False
    if j.get("state") == "done" and it.get("status") == "running" and (r.get("kind") != "take" or (j.get("take") or {}).get("n") is not None
                                                                        or r.get("take_n") is not None):
        t = j.get("take") or {}
        if r.get("kind") == "take" and t:
            r.update(take_n=t.get("n"), file=f"data/{t['file']}" if t.get("file") else None,
                     url=f"/files/{t['file']}" if t.get("file") else None)
        if r.get("kind") == "take" or r.get("version") is not None or j.get("version") is not None:
            if j.get("version") is not None:
                r.update(version=j["version"], file=j.get("file"), url=j.get("url"))
            it["status"] = "done"
            changed = True
    elif j.get("state") in ("failed", "cancelled") and it.get("status") == "running":
        it["status"] = j["state"]
        it["error"] = j.get("error")
        changed = True
    if changed:
        it["result"] = r
        _save_item(it)
        ledger("result", it)
    return it


# ============================================================ 接口
class EditBody(BaseModel):
    type: str
    id: str
    version: int | None = None
    feedback: str = Field(min_length=1, max_length=4000)
    annotations: dict | None = None
    gpu: int | str | None = None
    llm: dict | None = None
    dry_run: bool = False          # 只出计划，不执行
    plan: dict | None = None       # 已确认的计划（跳过逻辑模型，直接执行）
    by: str | None = None
    allow_bad_base: bool = False   # 底图 Q4 不过也照改（默认不改：标“底图不合格”）
    front: bool = False            # ComfyUI 插队（front=true），只在分到插队位时用
    engine: str | None = None      # 编辑模型（config/edit_engines.json）；不给 = default


def learn_key(feedback: str) -> str | None:
    f = (feedback or "").lower()
    hits = [k for k, ws in LEARN_KEYS.items() if any(w.lower() in f for w in ws)]
    return "+".join(sorted(hits)) if hits else None


def actor(request: Request | None, claimed: str | None = None) -> dict:
    """操作人从登录会话取（项目方 2026-10-31：登录后的所有行为都是本人行为，不用再打字）；没登录 → 用声明值"""
    u = None
    if request is not None:
        try:
            from ns_api import auth as AUTH
            u = AUTH.user_of(request)
        except Exception:  # noqa: BLE001
            u = None
    if u:
        return {"by": "owner" if u.get("role") == "owner" else u["name"], "user": u["name"], "role": u.get("role")}
    return {"by": claimed, "user": None, "role": None}


@router.post("/api/edits")
def create_edit(body: EditBody, request: Request):
    who = actor(request, body.by)
    body.by = who["by"]
    ctx = describe(body.type, body.id, body.version)
    if ctx.get("running"):
        raise HTTPException(409, "这一段正在写作，写完或停下后再改")
    edit_id = "ed-" + uuid.uuid4().hex[:10]
    it = {"edit_id": edit_id, "type": body.type, "id": body.id, "kind": ctx["kind"], "feedback": body.feedback.strip(),
          "annotations": body.annotations, "created_at": P.now(), "status": "planning", "adopted": None,
          "by": body.by, "user": who["user"], "learn_key": learn_key(body.feedback),
          "before": {k: ctx.get(k) for k in ("file", "n", "chain_v", "stage", "shot_id", "field", "node", "run_id")
                     if ctx.get(k) is not None}}
    if body.plan is not None:
        plan, meta = normalize_plan(body.plan, {**ctx, "feedback": body.feedback}, body.annotations), {"model": "owner-confirmed"}
    else:
        try:
            plan, meta = make_plan(ctx, body.feedback.strip(), body.annotations, body.llm)
        except LLMC.LLMConfigError as e:
            raise HTTPException(502, f"逻辑模型调用失败：{e}")
    it["plan"], it["planner"] = plan, meta
    if plan["action"] == "reject":
        it["status"] = "blocked"
        _save_item(it)
        ledger("blocked", it)
        return it
    if body.dry_run:
        it["status"] = "planned"
        _save_item(it)
        ledger("planned", it)
        return it
    _save_item(it)
    try:
        if body.type == "image":
            if plan["action"] == "prompt_only":
                _text_rewrite(it, {**ctx, "type": "prompt", "text": ctx.get("prompt")}, plan, body.llm)
                it["status"] = "proposed"
            else:
                bq = None if body.allow_bad_base or plan["action"] in ("regen", "seed") else base_quality(_abs(ctx["file"]))
                if bq is not None and not bq["ok"]:
                    # REFLOCK：底图本身 Q4 不过 → 在它上面改、重出 3 次也过不了；直接标“底图不合格”，不占卡
                    it["status"] = "base_rejected"
                    it["result"] = {"kind": "chain" if ctx["kind"] == "file" else "take", "base_quality": bq,
                                    "message": "底图不合格（生成契约 Q4）：" + "；".join(bq["reasons"])
                                               + "。请在 v9 配方出的新首帧上编辑，或整图重出。"}
                    _save_item(it)
                    ledger("base_rejected", it)
                    return it
                _image_job(it, ctx, plan, body.gpu, body.engine, body.front)
                it["status"] = "running"
        elif body.type == "video":
            if plan["action"] == "prompt_only":
                _text_rewrite(it, {**ctx, "type": "prompt", "text": ctx.get("prompt")}, plan, body.llm)
                it["status"] = "proposed"
            else:
                _video_job(it, ctx, plan, body.gpu)
                it["status"] = "running"
        else:
            _text_rewrite(it, ctx, plan, body.llm)
            it["status"] = "proposed"
    except HTTPException as e:
        it["status"], it["error"] = "failed", str(e.detail)
        _save_item(it)
        ledger("failed", it)
        raise
    except LLMC.LLMConfigError as e:
        it["status"], it["error"] = "failed", str(e)
        _save_item(it)
        ledger("failed", it)
        raise HTTPException(502, f"写作模型调用失败：{e}")
    with _lock:
        cur = _load_item(edit_id)       # 任务可能已经回写过 result（假 ComfyUI 立即完成）
        it["result"] = {**(it.get("result") or {}), **{k: v for k, v in (cur.get("result") or {}).items()
                                                       if k in ("version", "file", "url", "composite_error", "postflight", "take_n", "attempts")}}
        if cur.get("status") in ("done", "contract_failed"):
            it["status"] = cur["status"]
        it["result"].update({k: v for k, v in (cur.get("result") or {}).items() if k in ("attempts", "contract_failed", "message")})
        _save_item(it)
    ledger("submitted", it)
    return it


@router.get("/api/edits")
def list_edits(type: str | None = None, id: str | None = None, limit: int = 50):
    items = []
    hide_v1, cur = _RP.v1_hidden(), _RP.current_run()
    for p in sorted(_items_dir().glob("ed-*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            it = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: 列表接口跳过读坏的单条（写到一半 / 正被删），该条本身不受影响；其余照列
            continue
        if (type and it.get("type") != type) or (id and it.get("id") != id):
            continue
        if hide_v1 and it.get("run") != cur:     # L-125：只显示当前剧（V2）的修改单；V1 的已归档
            continue
        items.append(_sync_job(it))
        if len(items) >= max(1, min(limit, 500)):
            break
    return {"edits": items}


@router.get("/api/edits/versions")
def get_versions(type: str, id: str):
    ctx = describe(type, id)
    if ctx["kind"] == "file":
        ch = load_chain(id, ctx["original"])
        return {"kind": "chain", "current": ch["current"],
                "versions": [{**v, "url": _url(v.get("file")), "raw_url": _url(v.get("raw_file"))} for v in ch["versions"]]}
    if ctx["kind"] == "take":
        data = P.load_takes(ctx["shot_id"])
        vs = [{"n": t["n"], "parent": t.get("parent"), "mode": t.get("mode"), "instruction": t.get("instruction"),
               "file": f"data/{t['file']}", "url": f"/files/{t['file']}", "created_at": t.get("created_at")}
              for t in data.get("takes") or [] if t.get("stage") == ctx["stage"]]
        return {"kind": "take", "current": (data.get("active") or {}).get(ctx["stage"]),
                "locked": (data.get("locked") or {}).get(ctx["stage"]), "versions": vs}
    return {"kind": "proposal", "edits": list_edits(type, id)["edits"]}


@router.get("/api/edits/planner-prompt")
def get_planner_prompt():
    return {"path": _prel(PLANNER_PROMPT), "text": planner_prompt()}


@router.post("/api/edits/planner-prompt/rebuild")
def rebuild_planner_prompt():
    return {"path": _prel(PLANNER_PROMPT), "text": build_planner_prompt()}


@router.get("/api/edits/engines")
def get_engines():
    cfg = engines_cfg()
    return {"default": cfg["default"], "gen_contract": cfg.get("gen_contract"),
            "engines": [{"id": k, **{x: v.get(x) for x in ("label", "builder", "enabled", "max_refs", "note")}}
                        for k, v in cfg["engines"].items()]}


@router.get("/api/edits/learned")
def learned():
    return {"min": LEARN_MIN, "groups": _learn_groups()}


@router.get("/api/edits/{edit_id}")
def get_edit(edit_id: str):
    return _sync_job(_load_item(edit_id))


class AdoptBody(BaseModel):
    by: str | None = None
    note: str = ""


@router.post("/api/edits/{edit_id}/adopt")
def adopt(edit_id: str, request: Request, body: AdoptBody | None = None):
    body = body or AdoptBody()
    who = actor(request, body.by)
    body.by = who["by"]
    it = _sync_job(_load_item(edit_id))
    if it.get("status") not in ("done", "proposed"):
        raise HTTPException(409, f"这条编辑现在是“{it.get('status')}”，还不能采用")
    r = it.get("result") or {}
    applied = None
    if r.get("kind") == "take":
        if r.get("take_n") is None:
            raise HTTPException(409, "任务还没出结果")
        try:
            P.set_active(r["shot_id"], r["stage"], r["take_n"])
        except (StopIteration, KeyError):
            raise HTTPException(404, "新版本已不在（被删除？）")
        except ValueError as e:
            raise HTTPException(409, str(e))
        applied = {"active": r["take_n"]}
    elif r.get("kind") == "chain":
        if r.get("version") is None:
            raise HTTPException(409, "任务还没出结果")
        with _lock:
            ch = load_chain(it["id"])
            if not any(v["v"] == r["version"] for v in ch["versions"]):
                raise HTTPException(404, "新版本已不在（被删除？）")
            it.setdefault("before", {})["chain_current"] = ch["current"]
            ch["current"] = r["version"]
            save_chain(ch)
        applied = {"current": r["version"]}
    elif r.get("kind") == "proposal":
        applied = _apply_proposal(it, body)
    it.update(status="adopted", adopted=True, adopted_at=P.now(), adopted_by=body.by, applied=applied)
    _save_item(it)
    ledger("adopted", it, note=body.note)
    _invalidate()
    it["learning"] = learn_from(it)
    _save_item(it)
    return it


def _apply_proposal(it: dict, body: AdoptBody) -> dict:
    r = it["result"]
    text = r.get("text") or ""
    if any(c.get("level") == "block" for c in r.get("lock_checks") or []):
        raise HTTPException(409, "改写结果触发锁定规则（block），不能采用；请重新提反馈")
    kind = it["kind"]
    if kind == "shot" or (it["type"] in ("image", "video") and kind == "take"):
        shot = it["before"].get("shot_id")
        field = it["before"].get("field") or ("image_prompt" if it["before"].get("stage") == "image" else
                                              "last_prompt" if it["before"].get("stage") == "last" else None)
        if not field:
            raise HTTPException(409, "视频提示词请经 H3 覆盖（项目方）修改")
        with P.shot_lock(shot):
            ed = P.load_edit(shot)
            setattr(ed, field, text)
            P.save_edit(shot, ed)
        return {"shot_id": shot, "field": field}
    if kind == "run":
        if body.by != "owner":
            raise HTTPException(403, "剧本文字写回只接受项目方本人确认（by=owner）")
        from ns_api import story_runs as SR
        b = it["before"]
        out = SR.edit_artifact(b["run_id"], b["node"], SR.EditBody(text=text))
        return {"run_id": b["run_id"], "node": b["node"], "status": out.get("status")}
    if kind == "asset":
        return {"asset_field": it["before"].get("field"), "text": text, "note": "资产页按原接口保存这段文字"}
    return {"text": text}


@router.post("/api/edits/{edit_id}/reject")
def reject(edit_id: str, body: dict | None = None):
    it = _load_item(edit_id)
    it.update(status="rejected", adopted=False, rejected_at=P.now(), reject_reason=(body or {}).get("reason"))
    _save_item(it)
    ledger("rejected", it)
    return it


@router.post("/api/edits/{edit_id}/rollback")
def rollback(edit_id: str):
    """回到编辑前：take → 父版本设为当前；版本链 → current 指回编辑前；提示词 → 恢复编辑前文字"""
    it = _load_item(edit_id)
    r, b = it.get("result") or {}, it.get("before") or {}
    if r.get("kind") == "take":
        try:
            P.set_active(r["shot_id"], r["stage"], r["parent"])
        except (StopIteration, KeyError):
            raise HTTPException(404, "原版本已不在")
        except ValueError as e:
            raise HTTPException(409, str(e))
    elif r.get("kind") == "chain":
        with _lock:
            ch = load_chain(it["id"])
            ch["current"] = b.get("chain_current", r.get("parent_v", 0))
            save_chain(ch)
    elif r.get("kind") == "proposal" and it.get("applied", {}) and it["applied"].get("field"):
        raise HTTPException(409, "提示词回滚请在本镜编辑里改回（原文在编辑记录 before / diff 里）")
    else:
        raise HTTPException(409, "这条编辑没有可回滚的版本")
    it.update(status="rolled_back", rolled_back_at=P.now())
    _save_item(it)
    ledger("rolled_back", it)
    _invalidate()
    return it


def _invalidate():
    try:
        _app()._summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass


# ============================================================ 学习：采用的改法 → 规则草案
def _learn_groups() -> dict:
    groups: dict[str, list] = {}
    for rec in read_ledger():
        if rec.get("event") == "adopted" and rec.get("learn_key"):
            groups.setdefault(rec["learn_key"], []).append({"edit_id": rec["edit_id"], "feedback": rec.get("feedback"),
                                                            "action": (rec.get("plan") or {}).get("action"),
                                                            "instruction": (rec.get("plan") or {}).get("instruction"),
                                                            "at": rec.get("at")})
    return groups


def _kn_rel(p: Path) -> str:
    return "knowledge/" + p.relative_to(KNOWLEDGE).as_posix()


LEARN_LINK = {"image": ("render", "REN", "P5-P6"), "video": ("render", "REN", "P6-P7"),
              "script": ("writer", "WRT", "P3-P4"), "prompt": ("render", "REN", "P4-P6"), "asset": ("asset", "AST", "P4-P5")}


def _learn_id(key: str, prefix: str) -> str:
    """K-<域>-E<两位>：按改法类别固定分配（data/edits/learn_ids.json），满足 knowledge 的 id 格式"""
    p = data_dir() / "learn_ids.json"
    with _lock:
        ids = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}   # 不存在 = 还没分配过；读坏 = 抛错（不重新从 E01 发号撞 id）
        k = f"{prefix}:{key}"
        if k not in ids:
            used = {int(v.rsplit("E", 1)[1]) for v in ids.values() if v.startswith(f"K-{prefix}-E")}
            ids[k] = f"K-{prefix}-E{next(i for i in range(1, 100) if i not in used):02d}"
            p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_json(p, ids)
        return ids[k]


def learn_from(it: dict) -> dict | None:
    key = it.get("learn_key")
    if not key:
        return None
    g = [x for x in _learn_groups().get(key) or []]
    if len(g) < LEARN_MIN:
        return {"key": key, "count": len(g), "draft": None}
    domain, prefix, link = LEARN_LINK.get(it["type"], LEARN_LINK["image"])
    rid = _learn_id(key, prefix)
    path = KNOWLEDGE / "inbox" / f"{time.strftime('%Y-%m-%d')}_edit_{key.replace('+', '_')}.yaml"
    exists = any((KNOWLEDGE / "inbox").glob(f"*_edit_{key.replace('+', '_')}.yaml"))
    import yaml
    ins = [x["instruction"] for x in g if x.get("instruction")][-3:]
    acts = sorted({x["action"] for x in g if x.get("action")})
    words = LEARN_KEYS.get(key.split("+")[0], (key,))[:4]
    draft = {"rules": [{
        "id": rid, "domain": domain, "link": link,
        "title": f"项目方反复提出的同类修改（{key}）已被采用 {len(g)} 次：建议改成默认做法",
        "when": f"项目方反馈含“{'、'.join(words)}”类问题",
        "then": (f"采用过的改法：{' / '.join(acts) or '-'}；近期修改指令：{' | '.join(i[:80] for i in ins) or '-'}。"
                 "建议把对应修正写进出图预设后缀或编译器规则（确认后改）"),
        "evidence": [{"src": "data/edits/ledger.jsonl", "note": f"edit_id：{', '.join(x['edit_id'] for x in g[-5:])}"}],
        "confidence": "low" if len(g) < 4 else "medium", "status": "待确认", "date": time.strftime("%Y-%m-%d"),
    }]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 规则草案（ns_api.edits 由项目方采用的编辑自动沉淀，EDITDEL）。status 待确认：总调度 / ARCH 确认后移到 "
                    "knowledge/rules/。\n" + yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if not exists:
        _rsi_line(rid, key, len(g), path)
    return {"key": key, "count": len(g), "draft": _kn_rel(path), "rule_id": rid}


def _rsi_line(rid: str, key: str, n: int, path: Path) -> None:
    """RSI_LEDGER 记一行；规则列写“inbox 草案 REN-Exx”（不带 K- 前缀：草案不是正式规则，免得 compile.py 的 id 存在性检查报错）"""
    led = KNOWLEDGE / "RSI_LEDGER.md"
    if not led.is_file():
        raise FileNotFoundError(f"{led} 不在，编辑闭环沉淀记不了（RSI_LEDGER 是必备文件）")
    txt = led.read_text(encoding="utf-8")
    if "## E. 编辑闭环沉淀" not in txt:
        txt = (txt.rstrip("\n") + "\n\n## E. 编辑闭环沉淀（EDITDEL，自动）\n\n"
               "| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |\n|---|---|---|---|---|---|---|\n")
    row = (f"| E-{key} | 反复出现的“{key}”类修改可沉淀为默认做法 | 项目方在编辑抽屉里提反馈并采用结果 | 同类被采用 {n} 次 | ⏳ "
           f"| inbox 草案 {rid.split('-', 1)[1]} | {_kn_rel(path)}；data/edits/ledger.jsonl |\n")
    led.write_text(txt.rstrip("\n") + "\n" + row, encoding="utf-8")
