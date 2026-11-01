"""P3 单集剧本（场次 / 台词 / 动作 / 声音）schema + 格式校验 + 连接 P3-P4 的逐字一致校验（CHAINSPEC 2026-10-31）。

链条契约：config/pipeline/chain.yaml 节点 P3、连接 P2-P3 / P3-P4；说明 docs/PIPELINE_CHAIN.md §P3。
P3 是“文学剧本”层：写场次、人物、动作、台词、独白，不写镜头语言（景别、运镜、H3 英文都归 P4）。
P4（现行剧本分镜格式，config/script_chat_rules.md §2）必须把 P3 的台词 / 独白逐字带下去——这是本模块最重要的校验。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .episode_outline import EpisodeOutline
from .upstream_common import SHOT_MAX_S, SPEECH_CPS, Report, norm, parse_model, spoken_len

SCHEMA = "nsfs.screenplay/1"
OFF_MARKS = ("画外", "电话", "语音", "OS", "VO")
CAMERA_WORDS_RE = re.compile(r"(特写|近景|中景|全景|远景|景别|推镜|拉镜|摇镜|跟拍|机位|镜头|运镜|push in|pull out|zoom|pan |tilt |"
                             r"tracking shot|static shot|close-up|wide shot)", re.I)
QUOTE_CHARS = "“”\"「」『』"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Line(_Strict):
    kind: Literal["action", "dialogue", "voiceover", "sound"]
    text: str                                 # 动作 / 台词原文 / 独白原文 / 声音（中文）
    speaker: str | None = None                # dialogue / voiceover 必填，登记的中文名
    tone: str | None = None                   # 语气（舞台提示单独放这里，不进 text）
    off_screen: Literal["画外", "电话", "语音", "OS", "VO"] | None = None


class SceneBlock(_Strict):
    no: int                                   # 场次 1…n
    scene_id: str
    beat_ids: list[str]                       # 覆盖的 P2 节拍
    time: str = ""                            # 时段（照场景表或写跳时：次日 / 当晚 …）
    characters: list[str]
    lines: list[Line]


class Screenplay(_Strict):
    schema_: Literal["nsfs.screenplay/1"] = Field(SCHEMA, alias="schema")
    episode: int
    title: str
    target_duration_s: int
    scenes: list[SceneBlock]

    def speech(self, kind: str) -> list[tuple[str, str]]:
        return [(ln.speaker or "", ln.text) for sc in self.scenes for ln in sc.lines if ln.kind == kind]


def check_screenplay(data, *, roster: list[str] | None = None) -> Report:
    rep = Report("P3")
    sp = parse_model(rep, "SP-01", Screenplay, data)
    if sp is None:
        return rep
    if [s.no for s in sp.scenes] != list(range(1, len(sp.scenes) + 1)):
        rep.add("SP-02", "block", f"场次须从 1 连续：{[s.no for s in sp.scenes]}", "scenes")
    total = 0
    for sc in sp.scenes:
        f = f"scenes[{sc.no}]"
        if not any(ln.kind == "action" for ln in sc.lines):
            rep.add("SP-08", "warn", f"第 {sc.no} 场没有动作行（P4 首帧 / 尾帧无从落地）", f)
        for i, ln in enumerate(sc.lines, 1):
            g = f"{f}.lines[{i}]"
            if ln.kind in ("dialogue", "voiceover"):
                if not ln.speaker:
                    rep.add("SP-03", "block", f"第 {sc.no} 场第 {i} 行 {ln.kind} 缺 speaker", g)
                elif roster is not None and ln.speaker not in roster:
                    rep.add("SP-03", "block", f"说话人「{ln.speaker}」不在人物表", g)
                elif ln.kind == "dialogue" and ln.speaker not in sc.characters:
                    rep.add("SP-03", "block", f"说话人「{ln.speaker}」不在第 {sc.no} 场 characters", g)
                if any(q in ln.text for q in QUOTE_CHARS) or re.match(r"^\s*[（(]", ln.text) or \
                        (ln.speaker and re.match(rf"^\s*{re.escape(ln.speaker)}\s*[：:，,]", ln.text)):
                    rep.add("SP-04", "block", f"第 {sc.no} 场第 {i} 行 text 只放台词原文：不带引号、括号、说话人或语气（语气写 tone）", g)
                n = spoken_len(ln.text)
                total += n
                if n > SPEECH_CPS * SHOT_MAX_S:
                    rep.add("SP-09", "block", f"第 {sc.no} 场第 {i} 行 {n} 字，一句超过单镜上限 {int(SPEECH_CPS * SHOT_MAX_S)} 字（15 秒 × 3.5 字/秒），P4 放不下", g)
            elif ln.kind == "action" and CAMERA_WORDS_RE.search(ln.text):
                rep.add("SP-05", "warn", f"第 {sc.no} 场第 {i} 行动作里写了镜头语言（{CAMERA_WORDS_RE.search(ln.text).group(0)}）：景别 / 运镜归 P4", g)
        if roster is not None:
            extra = [c for c in sc.characters if c not in roster]
            if extra:
                rep.add("SP-03", "block", f"第 {sc.no} 场人物 {extra} 不在人物表", f + ".characters")
    budget = SPEECH_CPS * (sp.target_duration_s - 0.3 * max(1, len(sp.scenes)))
    if total > budget:
        rep.add("SP-06", "block", f"全集台词 + 独白 {total} 字，超过 {sp.target_duration_s} 秒能说完的 {int(budget)} 字（3.5 字/秒）", "scenes")
    return rep


def check_link_p2_p3(o: EpisodeOutline, sp: Screenplay) -> Report:
    """连接 P2-P3：每个节拍都被某场覆盖；场景 / 人物不超出大纲；标题、时长照抄。"""
    rep = Report("P2-P3")
    beats = {b.id: b for b in o.beats}
    covered = {b for sc in sp.scenes for b in sc.beat_ids}
    miss = [b for b in beats if b not in covered]
    if miss:
        rep.add("LK23-01", "block", f"节拍 {miss} 没有任何场次覆盖（不删大纲节拍）", "scenes")
    unknown = sorted(covered - set(beats))
    if unknown:
        rep.add("LK23-01", "block", f"场次引用了不存在的节拍 {unknown}", "scenes")
    for sc in sp.scenes:
        for b in sc.beat_ids:
            if b in beats and beats[b].scene_id != sc.scene_id:
                rep.add("LK23-02", "block", f"第 {sc.no} 场 scene_id {sc.scene_id} 与节拍 {b} 的场景 {beats[b].scene_id} 不同",
                        f"scenes[{sc.no}].scene_id")
        extra = [c for c in sc.characters if c not in o.characters]
        if extra:
            rep.add("LK23-03", "block", f"第 {sc.no} 场出现大纲本集没有的人物 {extra}（不新增人物）", f"scenes[{sc.no}].characters")
    if norm(sp.title) != norm(o.title) or sp.episode != o.episode:
        rep.add("LK23-04", "block", f"episode / title 须照抄大纲（ep{o.episode}《{o.title}》）", "title")
    if sp.target_duration_s != o.target_duration_s:
        rep.add("LK23-04", "block", f"target_duration_s 须照抄大纲（{o.target_duration_s}）", "target_duration_s")
    order = [sc.beat_ids[0] for sc in sp.scenes if sc.beat_ids and sc.beat_ids[0] in beats]
    if order != sorted(order, key=lambda x: int(x[1:])):
        rep.add("LK23-05", "warn", f"场次顺序与节拍顺序不一致：{order}", "scenes")
    return rep


def check_link_p3_p4(sp: Screenplay, shots: list[dict], *, total_s: tuple[int, int] | None = None) -> Report:
    """连接 P3-P4：shots = P4 剧本分镜每镜的 {index, scene_id, cast:[名], duration, dialogue:[(说话人, 台词)],
    voiceover:(说话人, 文本)|None}（tools/pipeline/p4_adapter.py 从真实导入器结果转来）。
    台词 / 独白逐字、不增不减；场景、人物不超出剧本。"""
    rep = Report("P3-P4")
    want_d = [(s, norm(t)) for s, t in sp.speech("dialogue")]
    got_d = [(s, norm(t)) for sh in shots for s, t in sh.get("dialogue") or []]
    miss = [t for t in want_d if t not in got_d]
    extra = [t for t in got_d if t not in want_d]
    if miss:
        rep.add("LK34-01", "block", f"剧本台词没有逐字进分镜（{len(miss)} 句）：{[t for _, t in miss][:4]}", "对白")
    if extra:
        rep.add("LK34-01", "block", f"分镜多出剧本没有的台词 / 台词被改写（{len(extra)} 句）：{[t for _, t in extra][:4]}", "对白")
    if not miss and not extra and got_d != want_d:
        rep.add("LK34-02", "warn", "台词全部在，但顺序与剧本不同（亲密镜男方台词移到相邻镜时允许，其余请保持顺序）", "对白")
    want_v = [norm(t) for _, t in sp.speech("voiceover")]
    got_v = [norm(sh["voiceover"][1]) for sh in shots if sh.get("voiceover")]
    # 一段独白允许拆到相邻几镜：拼起来逐字相等即可
    if norm("".join(want_v)) != norm("".join(got_v)):
        joined_w, joined_g = norm("".join(want_v)), norm("".join(got_v))
        extra_v = [f"镜{sh['index']}「{sh['voiceover'][1]}」" for sh in shots
                   if sh.get("voiceover") and norm(sh["voiceover"][1]) not in joined_w]
        miss_v = [w for w in want_v if w not in joined_g]
        rep.add("LK34-03", "block", f"独白须逐字进分镜（可拆到相邻镜）：剧本 {len(want_v)} 段，分镜 {len(got_v)} 段，拼接后不相等"
                + (f"；剧本里没有这些独白，删掉这些 🎙 整行：{'、'.join(extra_v)}" if extra_v else "")
                + (f"；剧本独白没进分镜 {miss_v}" if miss_v else ""), "🎙")
    sids = {sc.scene_id for sc in sp.scenes}
    names = {c for sc in sp.scenes for c in sc.characters}
    for sh in shots:
        if sh.get("scene_id") and sh["scene_id"] not in sids:
            rep.add("LK34-04", "block", f"镜{sh['index']} 场景 {sh['scene_id']} 不在剧本场次里", f"镜{sh['index']}.场景")
        extra_c = [c for c in sh.get("cast") or [] if c not in names]
        if extra_c:
            rep.add("LK34-04", "block", f"镜{sh['index']} 人物 {extra_c} 不在剧本里", f"镜{sh['index']}.人物")
    used = {sh.get("scene_id") for sh in shots}
    lost = [sc.no for sc in sp.scenes if sc.scene_id not in used]
    if lost:
        rep.add("LK34-05", "warn", f"剧本第 {lost} 场的场景没有任何镜头", "")
    tot = sum(sh.get("duration") or 0 for sh in shots)
    lo, hi = total_s or (sp.target_duration_s - 10, sp.target_duration_s + 10)
    if not lo <= tot <= hi:
        rep.add("LK34-06", "warn", f"分镜总时长 {tot} 秒，剧本目标 {sp.target_duration_s} 秒（允许 ±10）", "时长")
    return rep


RULE_IDS = {"SP-01", "SP-02", "SP-03", "SP-04", "SP-05", "SP-06", "SP-08", "SP-09",
            "LK23-01", "LK23-02", "LK23-03", "LK23-04", "LK23-05",
            "LK34-01", "LK34-02", "LK34-03", "LK34-04", "LK34-05", "LK34-06"}
