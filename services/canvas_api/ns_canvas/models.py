"""
gpu3 渲染桥（canvas bridge）的数据契约 v1。说明书：docs/canvas.md（两边一起改）。

这个服务不管剧本、编辑、造型、审核（那些在 services/api/ns_api）。它只做两件事：
1. 读 gpu3 上的渲染产物（renders_gpu3 目录，布局与 ns_render.pipeline 的 take 布局相同），并提供文件、缩略图、视频尾帧；
2. 管一个只追加的重渲队列 rerender_queue.jsonl（画布写请求，gpu3 系列渲染器消费），进度写回 rerender_events.jsonl。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, StrictBool

SCHEMA_QUEUE = "nsfs_canvas.rerender/v1"
SCHEMA_EVENT = "nsfs_canvas.render_event/v1"

Stage = Literal["image", "video", "both"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class QCVerdict(BaseModel):
    check: str                 # face_eyes / text / drift / decoration / frame
    verdict: Literal["pass", "warn", "fail", "unknown"] = "unknown"
    reasons: list[str] = Field(default_factory=list)
    score: float | None = None


class TakeOut(BaseModel):
    """一个版本（take）的产物。字段与 ns_schema.edits.Take 对齐，另加 URL、来源、QC。"""
    source: str                        # 渲染目录标签（renders_gpu3 / weita）
    stage: Literal["image", "video"]
    n: int
    active: bool = False
    file: str | None = None            # 相对 data/ 的路径（与 Take.file 同义；weita 来源为 None）
    url: str | None = None
    thumb: str | None = None
    last_frame_url: str | None = None  # 视频：实际尾帧（文件或 ffmpeg 现抽）
    last_target_url: str | None = None # 首尾帧模式的目标尾帧
    seed: int | None = None
    prompt: str | None = None
    seconds: float | None = None
    frames: int | None = None
    created_at: str | None = None
    workflow: str | None = None
    request_id: str | None = None      # 由哪条重渲请求产生（渲染器写进 takes.json）
    input_hash: str | None = None      # 渲染时输入哈希（见 RerenderRequest.input_hash）
    qc: list[QCVerdict] = Field(default_factory=list)


class ShotRenders(BaseModel):
    shot: str                          # ep01-S1
    takes: list[TakeOut] = Field(default_factory=list)
    active: dict[str, int | None] = Field(default_factory=dict)   # {"image": n, "video": n}，renders_gpu3 来源
    error: str | None = None
    status: Literal["none", "queued", "rendering", "done", "failed"] = "none"
    audit: dict | None = None          # status.json.audit（version, verdict, failures, warnings, not_checked, overrides, invalid_overrides, h3_edit, prompt_sha）
    h3: dict | None = None             # compiled.json h3_* + edits.json h3_prompt_override + effective_sha256
    shot_state: dict | None = None     # status.json: state, blocked, owner, scene_id, segment_id, continuity, bible_version
    active_video: dict | None = None   # active 视频 take：prompt, prompt_sha256, reference(s), last_target, frames
    video_gate: dict | None = None     # {verdict, prompt_sha, effective_sha256, blocked, video_ok}：画布“出视频”按钮的条件
    queue: list[dict] = Field(default_factory=list)


class RerenderRequest(BaseModel):
    """rerender_queue.jsonl 的一行。只追加；取消也是追加一行 op=cancel。"""
    schema_: str = Field(SCHEMA_QUEUE, alias="schema")
    id: str = ""
    op: Literal["render", "cancel"] = "render"
    project: str = "weita"             # 项目 slug；weita = 为他而骚（renders_gpu3 根），其他在 renders_gpu3/<slug>/
    shot: str                          # ep01-S1
    stage: Stage = "both"              # image=重画首帧 / video=只重生成视频（保留当前首帧）/ both
    keep_seed: bool = False            # True：沿用当前选用版本的种子（seed 字段已填好）
    seed: int | None = None            # 明确种子；None 且 keep_seed=False → 渲染器自取新种子
    edit: dict = Field(default_factory=dict)       # 画布那一刻的 ShotEdit（ns_schema.edits）快照
    compiled: dict = Field(default_factory=dict)   # 可选：ns_api 编译好的 image/video 提示词、负面词、LoRA、参考图（含造型）
    input_hash: str | None = None      # 可选：ns_api 计算的输入哈希（提示词+造型+参考），渲染器原样写回 take
    overrides: dict = Field(default_factory=dict)  # 可选：渲染参数覆盖，如 {"frames":158,"steps":20,"route":"fl2va_int8"}
    priority: int = 5                  # 0 最高
    batch: str | None = None
    requested_by: str = "owner"
    note: str = ""
    at: str = Field(default_factory=now)
    target_id: str | None = None       # op=cancel：被取消的请求 id
    model_config = {"populate_by_name": True}


class RenderEvent(BaseModel):
    """rerender_events.jsonl 的一行（渲染器写，或 POST /api/gpu3/queue/events）。"""
    schema_: str = Field(SCHEMA_EVENT, alias="schema")
    id: str                            # RerenderRequest.id
    state: Literal["started", "image_done", "video_done", "done", "failed", "skipped"]
    at: str = Field(default_factory=now)
    worker: str | None = None          # 如 gpu0
    take: dict | None = None           # {"stage":"image","n":3}
    error: str | None = None
    model_config = {"populate_by_name": True}


class SeriesControl(BaseModel):
    """POST /api/gpu3/projects/{slug}/series 的请求体；写成 series_control.json（离线也可手工放同样的 JSON）。"""
    action: Literal["start", "pause", "stop"]
    episodes: list[int] | None = None  # None = 全部
    adult_content: StrictBool = True   # 是否允许成人镜头；2026-10-30 起默认开（取消过滤器）
    by: str = "owner"
    note: str = ""


class H3EditBody(BaseModel):
    text: str
    by: str
    base_sha: str | None = None        # 改之前看到的 effective_sha256；不一致返回 409


class OverrideBody(BaseModel):
    rule_id: str
    owner_quote: str                   # 项目方原话（非空）
    by: str = "owner"


class RunBody(BaseModel):
    """POST /api/gpu3/projects/{slug}/episodes/{ep}/run"""
    steps: list[str]                   # frames | video | 4k（assemble 由 fredw-d9 在笔记本做，这里拒绝）
    gpu: int
    by: str
    note: str
    dry_run: StrictBool = False


class RunCancelBody(BaseModel):
    by: str
