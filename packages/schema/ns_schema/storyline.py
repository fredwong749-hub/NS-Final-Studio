"""P0 项目方故事提纲（Brief）与 P1 全剧 storyline 的 schema + 格式校验（CHAINSPEC 2026-10-31）。

链条契约：config/pipeline/chain.yaml（节点 P0 / P1，连接 P0-P1）；说明：docs/PIPELINE_CHAIN.md §P0、§P1。
P0 由项目方给（剧本创作页 #/script-create 的提纲 / 集数 / 镜数 / 时长字段，系统原样转成 Brief，不改写）。
P1 由写作 LLM 产出 JSON。本模块只查格式、id、登记一致和“提纲原文逐字传下去”，不评价剧情。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .upstream_common import (CHAR_ID_RE, EPISODE_S, SCENE_ID_RE, Report, en_problems, norm, parse_model)

BRIEF_SCHEMA = "nsfs.brief/1"
STORYLINE_SCHEMA = "nsfs.storyline/1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------- P0 Brief
class EpisodeRange(_Strict):
    first: int = Field(alias="from", ge=1)
    last: int = Field(alias="to", ge=1)


class Brief(_Strict):
    """P0：项目方故事提纲。outline / episode_lines 原文逐字，系统不改写。"""
    schema_: Literal["nsfs.brief/1"] = Field(BRIEF_SCHEMA, alias="schema")
    title: str = ""
    outline: str                                   # 提纲原文（项目方粘贴 / 上传）
    episodes: EpisodeRange
    episode_lines: dict[int, str] = Field(default_factory=dict)   # 项目方给的逐集一句话（原文），可空
    seconds_per_episode: tuple[int, int] = EPISODE_S
    shots_per_ep: int | None = None
    registry_from: list[str] = Field(default_factory=list)       # 继承登记（会话 id / 剧本 md）
    notes: str = ""
    source: str = ""                               # 来源文件或界面（provenance）


def check_brief(data) -> Report:
    rep = Report("P0")
    b = parse_model(rep, "BR-01", Brief, data)
    if b is None:
        return rep
    if not b.outline.strip():
        rep.add("BR-02", "block", "提纲为空", "outline")
    if b.episodes.last < b.episodes.first or b.episodes.last - b.episodes.first >= 100:
        rep.add("BR-03", "block", f"集数范围不合法：{b.episodes.first}–{b.episodes.last}（一次最多 100 集）", "episodes")
    out = [k for k in b.episode_lines if not b.episodes.first <= k <= b.episodes.last]
    if out:
        rep.add("BR-04", "block", f"逐集一句话的集号不在范围内：{out}", "episode_lines")
    return rep


# ---------------------------------------------------------------- P1 Storyline
class Relation(_Strict):
    to: str
    relation: str


class CharacterCard(_Strict):
    """人物表一行（与剧本 **全剧人物表** 五格一一对应，P4 原样抄进 H3）"""
    name: str                     # 中文名（全剧唯一）
    char_id: str                  # lin_wan / gu_chen / chen_yu / ch_<…>（series10 阿岚 = ch_a_lan）
    role: str                     # 主角 / 对手 / 配角 …（标签）
    age: int                      # 整数岁；全部 ≥ 18（★ 最高优先级规则）
    gender: Literal["女", "男", "其他"]
    zh_look: str                  # 中文外貌句：<年龄段>｜<体型>｜<发型发色>｜<服装主色>｜<标志物>｜<不可变特征>；有系统锁写“系统锁”
    en_phrase: str                # EN外貌短语：只写身份（年龄、性别、族裔、发、脸 / 肤色 / 体型），不写服装
    voice_phrase: str             # VOICE声线短语：英文，含 voice
    relations: list[Relation] = Field(default_factory=list)
    first_episode: int | None = None


class SceneCard(_Strict):
    """场景表一行（与剧本 **全剧场景表** 六格一一对应）"""
    scene_id: str
    name: str
    space: str
    time_of_day: str
    light: str
    fixtures: str


class World(_Strict):
    setting: str
    era: str = ""
    rules: list[str] = Field(default_factory=list)


class EpisodeLine(_Strict):
    episode: int
    title: str
    owner_line: str = ""          # 项目方逐集一句话原文（Brief.episode_lines[N]，逐字）；没有就空
    logline: str                  # 本集一段话剧情（写作 LLM）
    characters: list[str]         # 本集出场人物（中文名，须在 characters）
    scenes: list[str]             # 本集用到的场景 id（须在 scenes）
    intimate: bool = False        # 含亲密镜（P4 集标题加 🔴）
    carry_out: str = ""           # 本集结尾留给下一集的状态（P2 carry_in 接它）


class Storyline(_Strict):
    schema_: Literal["nsfs.storyline/1"] = Field(STORYLINE_SCHEMA, alias="schema")
    title: str
    premise: str
    world: World
    characters: list[CharacterCard]
    scenes: list[SceneCard]
    episodes: list[EpisodeLine]

    def char(self, name: str) -> CharacterCard | None:
        return next((c for c in self.characters if c.name == name), None)

    def episode(self, n: int) -> EpisodeLine | None:
        return next((e for e in self.episodes if e.episode == n), None)


PRONOUNS = ("她", "他", "她们", "他们")


def check_storyline(data, *, registry_chars: list[dict] | None = None, registry_scenes: list[dict] | None = None) -> Report:
    """P1 节点内部规则 SL-*。registry_* = 已登记人物 / 场景（ns_api.script_chat.registry_tables 的结果，原文）"""
    rep = Report("P1")
    s = parse_model(rep, "SL-01", Storyline, data)
    if s is None:
        return rep
    names = [c.name for c in s.characters]
    ids = [c.char_id for c in s.characters]
    for c in s.characters:
        f = f"characters[{c.name}]"
        if c.age < 18:
            rep.add("SL-02", "block", f"{c.name} 年龄 {c.age}：全部角色必须是成年人（≥18）", f + ".age")
        if not CHAR_ID_RE.match(c.char_id):
            rep.add("SL-03", "block", f"{c.name} 的 char_id「{c.char_id}」不合法（lin_wan/gu_chen/chen_yu 或 ch_<小写英文数字下划线>，例 ch_a_lan）", f + ".char_id")
        bad_names = [n for n in names] + [x.char_id for x in s.characters]
        p = en_problems(c.en_phrase, bad_names)
        if p:
            rep.add("SL-04", "block", f"{c.name} EN外貌短语：{'；'.join(p)}", f + ".en_phrase")
        p = en_problems(c.voice_phrase, bad_names)
        if "voice" not in c.voice_phrase.lower():
            p.append("缺 voice 一词")
        if p:
            rep.add("SL-05", "block", f"{c.name} VOICE声线短语：{'；'.join(p)}", f + ".voice_phrase")
        if c.zh_look != "系统锁" and c.zh_look.count("｜") < 5:
            rep.add("SL-11", "warn", f"{c.name} 中文外貌句应为六项全角｜分隔（或写 系统锁）", f + ".zh_look")
        if "|" in c.zh_look + c.en_phrase + c.voice_phrase:
            rep.add("SL-11", "block", f"{c.name} 格内出现半角 |（会破坏剧本表格）", f)
    dup = {x for x in names if names.count(x) > 1} | {x for x in ids if ids.count(x) > 1}
    if dup:
        rep.add("SL-03", "block", f"人物名 / char_id 重复：{sorted(dup)}", "characters")
    sids = [x.scene_id for x in s.scenes]
    for sc in s.scenes:
        f = f"scenes[{sc.scene_id}]"
        if not SCENE_ID_RE.match(sc.scene_id):
            rep.add("SL-06", "block", f"场景 id「{sc.scene_id}」应为 sk_<小写英文数字下划线>", f)
        cells = [sc.name, sc.space, sc.time_of_day, sc.light, sc.fixtures]
        if not all(x.strip() for x in cells) or any("|" in x for x in cells):
            rep.add("SL-06", "block", f"{sc.scene_id} 六格都要填、格内不用 |", f)
        hit = [w for w in names + list(PRONOUNS) if w and (w in sc.space or w in sc.fixtures)]
        if hit:
            rep.add("SL-07", "block", f"{sc.scene_id} 空间描述 / 固定陈设里写了人物：{hit}（场景卡只写环境）", f)
    if len(set(sids)) != len(sids):
        rep.add("SL-06", "block", "场景 id 重复", "scenes")
    for e in s.episodes:
        f = f"episodes[{e.episode}]"
        miss_c = [n for n in e.characters if n not in names]
        miss_s = [x for x in e.scenes if x not in sids]
        if miss_c:
            rep.add("SL-08", "block", f"ep{e.episode} 出场人物不在人物表：{miss_c}", f + ".characters")
        if miss_s:
            rep.add("SL-08", "block", f"ep{e.episode} 场景不在场景表：{miss_s}", f + ".scenes")
        if not e.characters or not e.scenes:
            rep.add("SL-08", "block", f"ep{e.episode} 出场人物 / 场景不能为空", f)
    eps = [e.episode for e in s.episodes]
    if eps != sorted(eps) or len(set(eps)) != len(eps):
        rep.add("SL-09", "block", f"集号须按顺序、不重复：{eps}", "episodes")
    # 已登记角色 / 场景：各格逐字照抄（QW-P7 / QW-SC9 同口径）
    reg_c = {r.get("name"): r for r in registry_chars or []}
    for c in s.characters:
        r = reg_c.get(c.name)
        if not r:
            continue
        for mine, theirs, lab in ((c.char_id, r.get("char_id"), "角色id"), (c.en_phrase, r.get("en"), "EN外貌短语"),
                                  (c.voice_phrase, r.get("voice"), "VOICE声线短语")):
            if theirs and norm(mine) != norm(theirs):
                rep.add("SL-10", "block", f"{c.name} 已登记，{lab} 须逐字照抄登记：「{theirs}」", f"characters[{c.name}]")
    reg_s = {r.get("scene_id"): r for r in registry_scenes or []}
    for sc in s.scenes:
        r = reg_s.get(sc.scene_id)
        if r and any(norm(getattr(sc, k)) != norm(r.get(k) or "") for k in ("name", "space", "time_of_day", "light", "fixtures")):
            rep.add("SL-10", "block", f"{sc.scene_id} 已登记，六格须逐字照抄登记", f"scenes[{sc.scene_id}]")
    return rep


def check_link_p0_p1(brief: Brief, s: Storyline) -> Report:
    """连接 P0-P1：集数范围一致；项目方逐集一句话逐字传下去；不新增集。"""
    rep = Report("P0-P1")
    want = list(range(brief.episodes.first, brief.episodes.last + 1))
    got = [e.episode for e in s.episodes]
    if got != want:
        rep.add("LK01-01", "block", f"storyline 的集号须正好是提纲范围 {want[0]}–{want[-1]}，现为 {got}", "episodes")
    for n, line in brief.episode_lines.items():
        e = s.episode(int(n))
        if e and norm(e.owner_line) != norm(line):
            rep.add("LK01-02", "block", f"ep{n} owner_line 须逐字照抄提纲原文：「{line}」", f"episodes[{n}].owner_line")
    if brief.title and s.title != brief.title:
        rep.add("LK01-03", "warn", f"剧名与提纲不同：提纲「{brief.title}」，storyline「{s.title}」", "title")
    lo, hi = brief.seconds_per_episode
    if (lo, hi) != EPISODE_S:
        rep.add("LK01-04", "warn", f"提纲要求每集 {lo}–{hi} 秒，与写作规则 50–75 秒不同（以提纲为准，下游按它校验）", "")
    return rep


RULE_IDS = {"BR-01", "BR-02", "BR-03", "BR-04", "SL-01", "SL-02", "SL-03", "SL-04", "SL-05", "SL-06", "SL-07",
            "SL-08", "SL-09", "SL-10", "SL-11", "LK01-01", "LK01-02", "LK01-03", "LK01-04"}
