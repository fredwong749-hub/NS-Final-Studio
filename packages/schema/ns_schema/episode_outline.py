"""P2 单集大纲（节拍 / 钩子标签 / 场次）schema + 格式校验（CHAINSPEC 2026-10-31）。

链条契约：config/pipeline/chain.yaml 节点 P2、连接 P1-P2；说明 docs/PIPELINE_CHAIN.md §P2。
节拍是 P3 剧本场次和 P4 分镜的骨架：P3 每场要标它覆盖的节拍 id，P4 每镜的场景 id 要能回溯到节拍。
purpose 只是受控标签（官方 shot-table-spec 的 Hook Type 思路），系统只查“有没有、在不在词表”，不判好坏。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .storyline import Storyline
from .upstream_common import EPISODE_S, SHOT_MAX_S, Report, norm, parse_model

SCHEMA = "nsfs.episode_outline/1"
PURPOSES = ("hook", "setup", "turn", "reveal", "tender", "intimate", "payoff", "bridge", "cliffhanger")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Beat(_Strict):
    id: str                                  # B1, B2 …（连续）
    summary: str                             # 这一拍发生什么（看得见 / 听得见的事）
    scene_id: str                            # 在哪个场景（storyline 场景表）
    characters: list[str]                    # 这一拍在场的人（中文名）
    est_s: int = Field(ge=2, le=40)          # 预计秒数（成片里占多久）
    purpose: str                             # PURPOSES 之一（标签）
    has_dialogue: bool = False               # 这一拍有没有台词（P3 才写具体台词）


class EpisodeOutline(_Strict):
    schema_: Literal["nsfs.episode_outline/1"] = Field(SCHEMA, alias="schema")
    episode: int
    title: str                               # 逐字 = storyline.episodes[N].title
    logline: str                             # 逐字 = storyline.episodes[N].logline
    intimate: bool                           # 逐字 = storyline.episodes[N].intimate
    target_duration_s: int                   # 本集目标秒数（50–75）
    characters: list[str]
    scenes: list[str]
    carry_in: str = ""                       # 从上一集 carry_out 接（ep 首集可空）
    beats: list[Beat]
    carry_out: str = ""                      # 留给下一集


B_RE = re.compile(r"^B(\d+)$")


def check_outline(data, *, seconds: tuple[int, int] = EPISODE_S) -> Report:
    rep = Report("P2")
    o = parse_model(rep, "EO-01", EpisodeOutline, data)
    if o is None:
        return rep
    nums = [int(m.group(1)) if (m := B_RE.match(b.id)) else -1 for b in o.beats]
    if nums != list(range(1, len(o.beats) + 1)):
        rep.add("EO-02", "block", f"节拍 id 须为 B1…Bn 连续：{[b.id for b in o.beats]}", "beats")
    if not 3 <= len(o.beats) <= 12:
        rep.add("EO-03", "warn", f"节拍数 {len(o.beats)}（建议 3–12；每拍落 1–3 个镜头）", "beats")
    lo, hi = seconds
    tot = sum(b.est_s for b in o.beats)
    if not lo <= o.target_duration_s <= hi:
        rep.add("EO-04", "block", f"target_duration_s={o.target_duration_s}，须在 {lo}–{hi} 秒", "target_duration_s")
    if abs(tot - o.target_duration_s) > 5:
        rep.add("EO-04", "block", f"节拍秒数合计 {tot}，与 target_duration_s {o.target_duration_s} 差超过 5 秒", "beats")
    for b in o.beats:
        f = f"beats[{b.id}]"
        if b.scene_id not in o.scenes:
            rep.add("EO-05", "block", f"{b.id} 的场景 {b.scene_id} 不在本集 scenes", f + ".scene_id")
        extra = [c for c in b.characters if c not in o.characters]
        if extra:
            rep.add("EO-05", "block", f"{b.id} 的人物 {extra} 不在本集 characters", f + ".characters")
        if b.purpose not in PURPOSES:
            rep.add("EO-06", "warn", f"{b.id} purpose「{b.purpose}」不在标签词表 {PURPOSES}", f + ".purpose")
        if not b.summary.strip():
            rep.add("EO-07", "block", f"{b.id} summary 为空", f + ".summary")
        if len(b.characters) > 3:
            rep.add("EO-08", "warn", f"{b.id} 同拍在场 {len(b.characters)} 人；单镜重要角色 ≤3（官方自检 3），P4 需拆镜", f)
        if b.est_s > 3 * SHOT_MAX_S:
            rep.add("EO-09", "warn", f"{b.id} 预计 {b.est_s} 秒，超过 3 个镜头上限，P4 拆镜会很碎", f)
    if not o.carry_out.strip():
        rep.add("EO-10", "warn", "carry_out 为空（下一集的开头衔接无处可接）", "carry_out")
    return rep


def check_link_p1_p2(s: Storyline, o: EpisodeOutline, prev: EpisodeOutline | None = None) -> Report:
    """连接 P1-P2：标题 / logline / intimate 逐字；不新增人物和场景；carry_in 接上一集 carry_out。"""
    rep = Report("P1-P2")
    e = s.episode(o.episode)
    if e is None:
        rep.add("LK12-01", "block", f"storyline 里没有 ep{o.episode}", "episode")
        return rep
    for k in ("title", "logline"):
        if norm(getattr(o, k)) != norm(getattr(e, k)):
            rep.add("LK12-01", "block", f"{k} 须逐字照抄 storyline：「{getattr(e, k)}」", k)
    if o.intimate != e.intimate:
        rep.add("LK12-01", "block", f"intimate 须与 storyline 相同（{e.intimate}）", "intimate")
    extra_c = [c for c in o.characters if c not in e.characters]
    extra_s = [x for x in o.scenes if x not in e.scenes]
    if extra_c:
        rep.add("LK12-02", "block", f"出现 storyline 本集没有的人物：{extra_c}（不新增人物）", "characters")
    if extra_s:
        rep.add("LK12-02", "block", f"出现 storyline 本集没有的场景：{extra_s}", "scenes")
    unused = [c for c in e.characters if c not in {x for b in o.beats for x in b.characters}]
    if unused:
        rep.add("LK12-03", "warn", f"storyline 本集出场的 {unused} 没有出现在任何节拍里", "beats")
    if prev is not None and prev.carry_out and norm(o.carry_in) != norm(prev.carry_out):
        rep.add("LK12-04", "warn", f"carry_in 应照抄上一集 carry_out：「{prev.carry_out}」", "carry_in")
    return rep


RULE_IDS = {"EO-01", "EO-02", "EO-03", "EO-04", "EO-05", "EO-06", "EO-07", "EO-08", "EO-09", "EO-10",
            "LK12-01", "LK12-02", "LK12-03", "LK12-04"}
