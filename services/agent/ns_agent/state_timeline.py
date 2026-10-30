"""
方案 D：每镜人物状态时间线 + 场景分组（T51）。格式见 docs/state_timeline.md。

    from ns_agent.state_timeline import build, write
    timeline, scenes = build()            # 纯计算（读项目文件，不写）
    write()                               # → data/state_timeline.json + data/scenes.json

只读：script_v2.json、data/looks/*.json、config/visual_bible.toml、comfy/models.lock、
data/renders_gpu3/LORA_REGISTRY.json、data/import/s1_gate.json、assets/scenes/<scene_id>/manifest.json。
从不触发渲染。
"""
import hashlib
import json
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

from ns_schema.looks import CHARACTERS, SLOTS
from ns_schema.script import ScriptImport, Shot

from . import gpu3_fields as G
from .bible import Bible, _sha_file, bible_version, load_bible, project_root, source_hashes

FORMAT = "ns.state_timeline/1"
SCENES_FORMAT = "ns.scenes/1"

# ------------------------------------------------------------------ 场景分组（确定性词表）
# (place_key, 中文名, 强词, 弱词)；弱词只在整句没有任何强词时才算（“写字楼旋转门”= 大堂，不是办公区）
PLACES: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("office_lobby", "写字楼大堂", ("旋转门", "大堂", "写字楼大门"), ()),
    ("elevator", "电梯", ("电梯",), ()),
    ("office_pantry", "公司茶水间", ("茶水间", "咖啡机"), ()),
    ("office_restroom", "公司洗手间", ("公司洗手间", "洗手间隔间", "隔间"), ()),
    ("canteen", "员工食堂", ("食堂",), ()),
    ("office", "写字楼办公区", ("工位", "办公", "会议", "加班"), ("写字楼", "公司")),
    ("counter", "专柜", ("专柜",), ()),
    ("piercing_studio", "穿孔工作室", ("穿孔工作室", "穿孔室", "诊床", "候诊区", "工作室"), ()),
    ("tattoo_studio", "纹身店", ("纹身店", "纹身椅"), ()),
    ("banquet", "酒店宴会厅", ("宴会厅", "会场", "茶歇区"), ()),
    ("subway", "地铁", ("地铁",), ()),
    ("restaurant", "高级餐厅", ("餐厅",), ()),
    ("taxi", "出租车", ("出租车",), ()),
    ("car", "豪车车内", ("豪车", "车内", "副驾"), ()),
    ("alley", "小巷", ("巷",), ()),
    ("gu_chen_gate", "顾沉家楼下", ("顾沉家楼下", "宅门"), ()),
    ("street", "街道", ("街道", "商业街", "街头", "大街", "夜路", "归途", "路边", "路灯"), ()),
)
# 房间：归属看“谁家”（顾沉家 / 出租屋）
ROOMS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("closet", "衣帽间", ("衣帽间", "更衣间", "衣橱", "衣柜"), ()),
    ("kitchen", "厨房", ("厨房", "水槽"), ()),
    ("dining", "餐桌", ("餐桌",), ()),
    ("bathroom", "浴室", ("浴室", "浴缸", "洗手台", "洗手间", "淋浴"), ()),
    ("entry", "玄关", ("玄关",), ()),
    ("balcony", "阳台", ("阳台",), ()),
    ("bedroom", "卧室", ("卧室", "睡房", "床上", "床头", "床沿"), ("床",)),
    ("living", "客厅", ("客厅", "软垫圈", "单人椅", "茶几"), ("沙发",)),
    ("study", "书房", ("书桌",), ()),
)
HOMES = {"gu_chen": ("顾沉家", ("顾沉家",)), "rental": ("出租屋", ("出租屋", "回家", "归家", "自己房间", "她的睡房"))}
TIMES = (("morning", ("清晨", "早晨", "晨光", "晨跑", "闹钟", "晨风")),
         ("day", ("白天", "午后", "午餐", "中午", "下午")),
         ("dusk", ("黄昏", "傍晚", "晚霞", "下班")),
         ("night", ("深夜", "夜", "晚间", "当晚", "睡前", "月光", "晚上")))
TRANSITIONS = ("次日", "第二天", "翌日", "转场", "闪回", "回忆", "梦境", "数日后", "几天后", "一周后", "当晚")
WEEKDAY_RE = re.compile(r"(?:^|[，,；;。：:])\s*(周[一二三四五六日末])")
QUOTE_RE = re.compile(r"“[^”]*”|\"[^\"]*\"")
TRIGGER_PREFIX_RE = re.compile(r"^(?:[a-z][a-z0-9_]*\d[a-z0-9_]*\s*[，,]\s*)+")


def _clean(text: str) -> str:
    return QUOTE_RE.sub("", TRIGGER_PREFIX_RE.sub("", text or ""))


def _match(table, text: str) -> tuple[int, str, str, bool] | None:
    """最早出现的强词所属地点 (位置, key, 中文名, 是否弱词)；没有强词时用最早出现的弱词"""
    for weak in (False, True):
        best = None
        for key, label, strong, weak_words in table:
            for w in (weak_words if weak else strong):
                i = text.find(w)
                if i >= 0 and (best is None or i < best[0]):
                    best = (i, key, label, weak)
        if best:
            return best
    return None


def shot_place(text: str) -> tuple[str, str, str | None] | None:
    """→ (地点 id, 中文名, 原文写明的房屋归属) 或 None。房间的 id 先不带归属（"room:bedroom"），归属在整段上确定。
    地点与房间都命中时取原文里先出现的（弱词让位于强词）"""
    owner = next((o for o, (_, words) in HOMES.items() if any(w in text for w in words)), None)
    place, room = _match(PLACES, text), _match(ROOMS, text)
    if place and room:
        if place[3] != room[3]:
            room = None if room[3] else room
            place = None if room else place
        elif room[0] < place[0]:
            place = None
        else:
            room = None
    if place:
        return place[1], place[2], None
    if room:
        return f"room:{room[1]}", room[2], owner
    if owner:
        return "room:home", "", owner
    return None


def shot_time(text: str) -> str:
    for key, words in TIMES:
        if any(w in text for w in words):
            return key
    return ""


def shot_transition(text: str) -> str:
    t = next((w for w in TRANSITIONS if w in text), "")
    if t:
        return t
    m = WEEKDAY_RE.search(text)
    return m.group(1) if m else ""


GU_CHEN_SIDE = {"gu_chen", "alex", "ryan", "kai", "leo"}


def _owner_hint(chars: set[str]) -> str | None:
    if chars & GU_CHEN_SIDE and "chen_yu" not in chars:
        return "gu_chen"
    if "chen_yu" in chars and not chars & GU_CHEN_SIDE:
        return "rental"
    return None


def group_scenes(script: ScriptImport, present=None) -> list[dict]:
    """→ 每镜 {shot_id, scene_id, segment_id, segment_start, place, place_key, place_source, time_of_day, time_source,
    transition}。同集连续、地点不变、时段不冲突、无转场词 → 同一段。
    present(shot) -> 入镜角色 slug 集合（用于判断房间是顾沉家还是出租屋）"""
    present = present or (lambda s: set())
    rows: list[dict] = []
    room_owner: dict[str, str] = {}      # 房间 → 最近一次的归属（跨集）
    last_place: tuple[str, str] | None = None
    for ep in script.episodes:
        segs: list[dict] = []
        cur: dict | None = None
        for s in ep.shots:
            text = _clean(s.img_prompt)
            pl, tm, tr = shot_place(text), shot_time(text), shot_transition(text)
            reason = ""
            if cur is None:
                reason = "episode"
            elif tr:
                reason = tr
            elif pl and cur["kind"] and pl[0] != cur["kind"] and not (pl[0] == "room:home" and cur["kind"].startswith("room:")):
                reason = "place"
            elif pl and pl[2] and cur["kind"] and pl[2] != cur["owner"]:
                reason = "place"             # 原文写明了另一处房屋（“深夜出租屋：…”）
            elif tm and cur["time"] and tm != cur["time"]:
                reason = "time"
            if reason:
                cur = {"n": len(segs) + 1, "kind": "", "label": "", "owner": None, "time": "", "shots": [],
                       "hints": Counter()}
                segs.append(cur)
            if pl:
                if not cur["kind"] or (cur["kind"] == "room:home" and pl[0].startswith("room:")):
                    cur["kind"], cur["label"] = pl[0], pl[1]
                if pl[2] and not cur["owner"]:
                    cur["owner"] = pl[2]
            if tm and not cur["time"]:
                cur["time"] = tm
            if (h := _owner_hint(set(present(s)))):
                cur["hints"][h] += 1
            cur["shots"].append((s, bool(pl), bool(tm), reason))
        ep_owner = None                  # 本集上一段的房屋归属
        for seg in segs:
            kind, label, src = seg["kind"], seg["label"], None
            if kind.startswith("room:"):
                room = kind[5:]
                # 归属：原文写明 > 本集上一段 > 入镜角色（顾沉方 / 陈宇）> 该房间上次的归属 > 出租屋
                hint = seg["hints"].most_common(1)[0][0] if seg["hints"] else None
                owner, osrc = next(((o, s_) for o, s_ in ((seg["owner"], "explicit"), (ep_owner, "episode"),
                                                          (hint, "characters"), (room_owner.get(room), "room_history"))
                                    if o), ("rental", "default"))
                room_owner[room] = ep_owner = owner
                kind, label = f"{owner}_{room}", HOMES[owner][0] + label
            else:
                osrc = None
            if not kind and seg["n"] == 1 and last_place:
                kind, label, src = last_place[0], last_place[1], "prev_episode"   # 集首没写地点：接上一集最后的地点
            if kind:
                last_place = (kind, label)
            sid = f"sk_{kind}" if kind else f"ep{ep.number:02d}_sc{seg['n']:02d}"
            for k, (s, has_pl, has_tm, reason) in enumerate(seg["shots"]):
                rows.append({"shot_id": s.id, "scene_id": sid, "segment_id": f"ep{ep.number:02d}_seg{seg['n']:02d}",
                             "segment_start": k == 0, "place": label, "place_key": kind, "home_owner_source": osrc,
                             "place_source": "explicit" if has_pl else (src or "inherited") if kind else "unknown",
                             "time_of_day": seg["time"], "time_source": "explicit" if has_tm else
                             "inherited" if seg["time"] else "unknown", "transition": reason if k == 0 else ""})
    return rows


# ------------------------------------------------------------------ S1 闸门 / 场景底板 / LoRA 注册表

S1_GATE = Path("data") / "import" / "s1_gate.json"


def script_version(script: ScriptImport) -> str:
    """剧本版本取自 sources 里《剧本和镜头》的文件名（…v2.md → v2）"""
    for s in script.sources:
        if "剧本和镜头" in s.path or len(script.sources) == 1:
            m = re.findall(r"v(\d+)", Path(s.path.replace("\\", "/")).name)
            if m:
                return f"v{m[-1]}"
    return "unknown"


def _ver_num(v: str) -> int:
    m = re.match(r"v(\d+)", v or "")
    return int(m.group(1)) if m else 0


def read_s1_gate(root: Path, script_sha: str | None) -> dict:
    """data/import/s1_gate.json（项目方 / 协调写，tools/s1_gate.py）。g3 接受只对同一份剧本有效"""
    p = root / S1_GATE
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    same = raw.get("script_sha") == script_sha and script_sha is not None
    return {"validator_errors": raw.get("validator_errors") if same else None,
            "g3_accepted": bool(raw.get("g3_accepted")) and same and bool(raw.get("g3_ref")),
            "g3_ref": raw.get("g3_ref", "") if same else "",
            "checked_at": raw.get("checked_at") if same else None,
            "gate_script_sha": raw.get("script_sha"), "stale": bool(raw) and not same}


def plate_info(root: Path, scene_id: str) -> dict:
    d = root / "assets" / "scenes" / scene_id
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    plate = d / (man.get("plate") or "plate.png")
    sha = _sha_cached(plate) if plate.is_file() else None
    if not sha:
        status = "missing"
    elif man.get("owner_confirmed_at") and str(man.get("owner_confirmed_ref") or "").strip() \
            and man.get("plate_sha256") == sha:
        status = "owner_confirmed"   # 确认必须绑定图 sha：没记 sha / 确认后换了图 → 退回 candidate
    else:
        status = "candidate"
    return {"plate": plate.relative_to(root).as_posix(), "plate_status": status, "plate_sha256": sha,
            "plate_built_from": man.get("built_from") or None,
            "owner_confirmed_at": man.get("owner_confirmed_at") if status == "owner_confirmed" else None,
            "owner_confirmed_ref": man.get("owner_confirmed_ref") if status == "owner_confirmed" else None}


LORA_REGISTRIES = (Path("comfy") / "models.lock", Path("data") / "renders_gpu3" / "LORA_REGISTRY.json")
_RANK = {"missing": 0, "training": 1, "accepted": 2}


def _entries(obj) -> list[dict]:
    if isinstance(obj, dict):
        if "loras" in obj:
            return _entries(obj["loras"])
        return [dict(v, file=v.get("file") or k) for k, v in obj.items() if isinstance(v, dict)]
    return [x for x in obj if isinstance(x, dict)] if isinstance(obj, list) else []


def lora_registry(root: Path) -> dict[str, dict]:
    """触发词 → {lora_id, registry_status, sha256, source}。accepted 必须同时有 sha256 与 status=accepted；
    笔记本 comfy/models.lock 与 gpu3 data/renders_gpu3/LORA_REGISTRY.json 合并，取较好的状态"""
    out: dict[str, dict] = {}
    for rel in LORA_REGISTRIES:
        try:
            data = json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in _entries(data):
            st = str(e.get("status") or "").lower()
            status = "accepted" if st == "accepted" and e.get("sha256") else "training" if st in (
                "training", "queued", "eval", "evaluating") else "missing"
            trig = e.get("triggers") or ([e["trigger"]] if e.get("trigger") else [])
            for t in trig:
                t = t.get("trigger") if isinstance(t, dict) else t
                if not t:
                    continue
                cand = {"lora_id": e.get("file") or e.get("name") or e.get("id"), "registry_status": status,
                        "sha256": e.get("sha256"), "source": rel.as_posix()}
                if t not in out or _RANK[status] > _RANK[out[t]["registry_status"]]:
                    out[t] = cand
    return out


# ------------------------------------------------------------------ 人物状态

def _refs(item) -> list[str]:
    out = [i.file for i in getattr(item, "images", [])]
    return out + [r for r in item.reference_images if r not in out]


def _is_file_ref(r: str) -> bool:
    return "/" in r or "\\" in r


def makeup_state_of(item, bible_states: dict) -> str | None:
    refs = _refs(item)
    for state, cfg in bible_states.items():
        plate = (cfg or {}).get("plate", "")
        if plate and any(f"{plate}_" in r or r.endswith(plate) for r in refs):
            return state
    name = item.name or ""
    for state, words in (("tears", ("泪",)), ("night", ("夜场",)), ("transition", ("过渡",)), ("bare", ("素颜",))):
        if any(w in name for w in words):
            return state
    return "heavy" if item.slot == "makeup" else None


def _episode_set(text: str) -> set[int]:
    out: set[int] = set()
    for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", text or ""):
        out.update(range(int(a), int(b or a) + 1))
    return out


def bible_makeup_for_episode(states: dict, ep: int) -> str | None:
    """visual_bible 的按集妆容表：集号最具体（列出的集最少）的那条胜出；episodes = "default" 为兜底"""
    hits = [(len(_episode_set(c.get("episodes", ""))), k) for k, c in states.items()
            if ep in _episode_set(c.get("episodes", ""))]
    if hits:
        return min(hits)[1]
    return next((k for k, c in states.items() if c.get("episodes") == "default"), None)


class _Ctx:
    def __init__(self, root: Path, bible: Bible, script: ScriptImport, res):
        self.root, self.b, self.script, self.res = root, bible, script, res
        self.registry = lora_registry(root)
        self.trig_file = {t.trigger: (t.file, t.kind) for t in script.globals.lora_triggers}
        chars = bible.data.get("characters") or {}
        self.char_cfg = {k: v for k, v in chars.items() if isinstance(v, dict)}


def _nails(cfg: dict) -> tuple[str, str]:
    text = cfg.get("nails", "")
    hands = re.search(r"手指甲为([^；;]+)", text)
    toes = re.search(r"脚趾甲为([^；;]+)", text)
    return (hands.group(1) if hands else ""), (toes.group(1) if toes else "")


def character_state(ctx: _Ctx, shot: Shot, slug: str, present: bool, present_source: str | None) -> dict:
    from .compiler import material_terms
    from .looks import item_in_shot
    res, b = ctx.res, ctx.b
    r = res.core(slug, shot.episode, shot.id, present_source or "detected")
    conflicts = res.conflicts(r, shot) if present else []
    cfg = ctx.char_cfg.get(slug, {})
    items: dict[str, list[dict]] = {}
    for slot in SLOTS:
        if slot not in r.slots:
            continue
        lst = []
        for iid in r.slots[slot].items:
            it = res.items.get(iid)
            if not it:
                lst.append({"id": iid, "name": f"?{iid}", "description": "", "reference_images": [], "in_shot": False,
                            "source": r.slots[slot].source, "missing": True})
                continue
            lst.append({"id": iid, "name": it.name, "description": it.description, "reference_images": _refs(it),
                        "in_shot": present and (it.prompt_policy == "always" or item_in_shot(it, shot)),
                        "trigger": it.trigger, "source": r.slots[slot].source})
        items[slot] = lst
    out: dict = {"present": present, "look_id": r.look_id, "look_label": r.label, "items": items}

    if slug == "lin_wan" or cfg.get("makeup_states"):
        states = cfg.get("makeup_states") or {}
        mk = [res.items[i] for i in (r.slots["makeup"].items if "makeup" in r.slots else []) if i in res.items]
        state, src, mk_item = None, "", None
        if mk:
            mk_item = mk[0]
            state, src = makeup_state_of(mk_item, states), "look"
        if not state:
            state, src = bible_makeup_for_episode(states, shot.episode), "bible"
        if not state:
            state, src = "heavy", "default"
        overlay = ""
        tears = states.get("tears") or {}
        if present and any(w in _clean(shot.img_prompt) for w in tears.get("when", [])):
            overlay = "tears"
        eyes = cfg.get("eyes") or {}
        eye = "bare" if state in ("bare", "transition") else "glam"
        if mk_item and "深棕" in mk_item.name:
            eye = "bare"
        elif mk_item and "灰蓝" in mk_item.name:
            eye = "glam"
        hands, toes = _nails(cfg)
        name = CHARACTERS.get(slug, slug)
        out.update({
            "makeup_state": state, "makeup_state_source": src, "makeup_item": mk_item.id if mk_item else None,
            "makeup_overlay": overlay, "eye_state": eye, "eyes": eyes.get(eye, ""),
            "hair": {"text": cfg.get("hair_color", ""), "items": r.slots["hair"].items if "hair" in r.slots else []},
            "nails": {"hands": hands, "toes": toes,
                      "toes_in_prompt": present and any(t.startswith("脚趾甲") for t in material_terms(
                          shot.img_prompt, present={name}, bible=b) if t not in shot.img_prompt)},
            "heels": cfg.get("heels_default", ""),
        })
    st = res.states.get(r.d_state.value or "")
    vis = r.visibility.value or "visible"
    adorn = []
    for iid in (st.items if st else []):
        it = res.items.get(iid)
        if not it:
            continue
        worn = not (vis == "in_box" and it.removable)
        adorn.append({"id": iid, "name": it.name, "trigger": it.trigger, "removable": it.removable, "worn": worn,
                      "visible": present and worn and vis != "hidden" and item_in_shot(it, shot)})
    out.update({"d_state": r.d_state.value, "d_state_source": r.d_state.source, "visibility": vis, "adornments": adorn})

    plan = res.schedule.episodes.get(str(shot.episode), {}).get(slug)
    reasons = []
    if plan is not None and not res.episode_confirmed(slug, shot.episode):
        reasons.append("episode_plan_unconfirmed")
    if plan is not None and plan.needs_review:
        reasons.append("episode_plan_needs_review")
    if any(c.severity == "error" for c in conflicts):
        reasons.append("look_conflict_error")
    out.update({"needs_review": bool(reasons), "review_reasons": reasons,
                "conflicts": [c.model_dump(include={"kind", "severity", "message", "item_id"}) for c in conflicts],
                "look_hash": r.hash})
    return out


def _signature(c: dict) -> dict:
    return {"present": c.get("present"), "look_id": c.get("look_id"),
            **{f"items.{s}": [i["id"] for i in v] for s, v in c.get("items", {}).items()},
            "makeup_state": c.get("makeup_state"), "eye_state": c.get("eye_state"),
            "hair": (c.get("hair") or {}).get("items"), "d_state": c.get("d_state"), "visibility": c.get("visibility"),
            "adornments": sorted(a["id"] for a in c.get("adornments", []) if a["visible"])}


def _diff(a: dict | None, b: dict) -> list[str]:
    sa, sb = _signature(a or {}), _signature(b)
    return [k for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)]


# ------------------------------------------------------------------ 输入哈希（过期检测）

BIBLE_SECTIONS = ("look", "realism", "materials", "shot_rules", "shot_rules_safe", "assembly", "classification", "looks")


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _master(root: Path, slug: str) -> str | None:
    return _sha_file(root / "assets" / "characters" / slug / "plates" / "master.png")


_SHA_CACHE: dict = {}


def _sha_cached(p: Path) -> str | None:
    """_sha_file，按 (路径, mtime, 大小) 缓存（过期检测每次请求都会算）"""
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _SHA_CACHE:
        _SHA_CACHE[key] = _sha_file(p)
    return _SHA_CACHE[key]


def input_hashes(root: str | Path | None = None) -> dict[str, str | None]:
    """时间线 source_hashes：bible_version 的输入 + 母版、脸部参考、LoRA 注册表、S1 闸门记录"""
    root = project_root(root)
    out: dict[str, str | None] = dict(source_hashes(root))
    for p in sorted((root / "assets" / "characters").glob("*/plates/master.png")):
        out[f"master/{p.parent.parent.name}"] = _sha_cached(p)
    out["face_reference"] = _sha_cached(root / "config" / "face_reference.json")
    for rel in LORA_REGISTRIES:
        out[rel.as_posix()] = _sha_cached(root / rel)
    out["s1_gate"] = _sha_cached(root / S1_GATE)
    return out


def stale_inputs(root: str | Path | None, timeline: dict | None, scenes: dict | None = None) -> list[str]:
    """已写好的时间线 / 场景表与磁盘上的输入是否一致 → 变了的输入名（空 = 不过期）。
    只比时间线里记了的字段（旧格式没记的不算过期）；底板按 scenes.json 的 plate_sha256 / plate_status 比。"""
    if not isinstance(timeline, dict):
        return []
    root = project_root(root)
    cur = input_hashes(root)
    out: list[str] = []
    src = timeline.get("source") or {}
    if "script_sha" in src and src.get("script_sha") != cur.get("script"):
        out.append("script")
    old = timeline.get("source_hashes")
    if isinstance(old, dict):
        out += [k for k in sorted(set(old) | set(cur)) if old.get(k) != cur.get(k) and k not in out]
    for sc in (scenes or {}).get("scenes") or []:
        if not isinstance(sc, dict) or not sc.get("scene_id") or "plate_sha256" not in sc:
            continue
        now = plate_info(root, sc["scene_id"])
        if now["plate_sha256"] != sc.get("plate_sha256") or now["plate_status"] != sc.get("plate_status"):
            out.append(f"plate/{sc['scene_id']}")
    return out


# ------------------------------------------------------------------ 主流程

def build(root: str | Path | None = None, previous: dict | None = None) -> tuple[dict, dict]:
    from .compiler import _resolver
    root = project_root(root)
    b = load_bible(root)
    script_path = root / "data" / "import" / "script_v2.json"
    script = ScriptImport.model_validate_json(script_path.read_text(encoding="utf-8"))
    res = _resolver(root)
    if res is None:
        raise FileNotFoundError(f"{root / 'data' / 'looks'}：造型数据缺失（先 uv run python -m ns_agent.looks seed）")
    ctx = _Ctx(root, b, script, res)
    version = bible_version(root)
    all_hashes = input_hashes(root)
    script_sha = all_hashes.get("script")
    sver = script_version(script)
    gate = read_s1_gate(root, script_sha)
    provisional = not (_ver_num(sver) >= 3 and gate["validator_errors"] == 0 and gate["g3_accepted"])
    source = {"script": sver, "script_sha": script_sha, "bible_version": version}
    prev_inputs = {s["shot_id"]: s.get("inputs_sha") for s in (previous or {}).get("shots", [])}

    groups = {r["shot_id"]: r for r in group_scenes(script, lambda s: {c for c, _ in res.characters(s)})}
    plates = {sid: plate_info(root, sid) for sid in {r["scene_id"] for r in groups.values()}}
    g = script.globals
    globals_h = _h(g.model_dump(include={"character_locks", "image_suffix", "motion_suffix", "base_negative",
                                         "lora_triggers"}))
    bible_sec = {k: _h(b.data.get(k)) for k in BIBLE_SECTIONS}

    # 集确认
    episodes: dict[str, dict] = {}
    lock_file = root / "data" / "looks" / "assets_lock.json"
    try:
        assets_locked = json.loads(lock_file.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        assets_locked = None
    for ep in script.episodes:
        plans = res.schedule.episodes.get(str(ep.number), {})
        # 本集要确认的角色 = 本集任一镜入镜的角色 + 有集计划的角色；没有计划 = 未确认
        required = list(dict.fromkeys([c for s in ep.shots for c, _ in res.characters(s)] + list(plans)))
        valid = {c: res.episode_confirmed(c, ep.number) for c in required}
        unconfirmed = [c for c in required if not valid[c]]
        ok = [plans[c] for c in required if valid[c]]
        refs = sorted({p.owner_confirmed_ref for p in ok if p.owner_confirmed_ref})
        episodes[str(ep.number)] = {"look_confirmed": bool(required) and not unconfirmed,
                                    "characters": required, "unconfirmed_characters": unconfirmed,
                                    "confirmed_ref": "；".join(refs) or None,
                                    "confirmed_at": max((p.owner_confirmed_at for p in ok), default=None),
                                    "assets_locked_version": assets_locked}

    shots_out: list[dict] = []
    prev: dict | None = None
    prop_cands = G.prop_candidates(res.items)
    img_text: dict[str, str] = {}
    seg_order: list[str] = []            # 全剧顺序的段（prev_segment_id 用）
    seg_props: dict[str, dict] = {}      # 本段道具的最近状态（没写状态的道具沿用）
    for ep in script.episodes:
        for s in ep.shots:
            grp = groups[s.id]
            if not seg_order or seg_order[-1] != grp["segment_id"]:
                seg_order.append(grp["segment_id"])
                seg_props = {}
            present = dict(res.characters(s))
            slugs = (["lin_wan"] if "lin_wan" in CHARACTERS else []) + [c for c in present if c != "lin_wan"]
            chars = {c: character_state(ctx, s, c, c in present, present.get(c)) for c in slugs}

            # 所需 LoRA：镜头触发词 + 造型里本镜生效、带触发词的单品
            want: list[tuple[str, str]] = [(t, "image") for t in s.img_triggers] + [(t, "video") for t in s.motion_triggers]
            for c in chars.values():
                if not c["present"]:
                    continue
                for lst in c["items"].values():
                    want += [(i["trigger"], "image") for i in lst if i.get("trigger") and i["in_shot"]]
                want += [(a["trigger"], "image") for a in c["adornments"] if a.get("trigger") and a["visible"]]
            req, seen = [], set()
            for t, kind in want:
                if t in seen:
                    continue
                seen.add(t)
                reg = ctx.registry.get(t, {})
                file, k2 = ctx.trig_file.get(t, (None, kind))
                req.append({"trigger": t, "kind": k2 or kind, "lora_id": reg.get("lora_id") or file,
                            "registry_status": reg.get("registry_status", "missing"), "sha256": reg.get("sha256")})

            plate = plates[grp["scene_id"]]
            blockers = []
            if provisional:
                blockers.append("s1_gate_not_passed")
            blockers += [f"lora:{r_['trigger']}:{r_['registry_status']}" for r_ in req
                         if r_["kind"] == "image" and r_["registry_status"] != "accepted"]
            if plate["plate_status"] != "owner_confirmed":
                blockers.append(f"plate:{grp['scene_id']}:{plate['plate_status']}")
            if not episodes[str(ep.number)]["look_confirmed"]:
                blockers.append(f"look_unconfirmed:ep{ep.number:02d}")
            for slug, c in chars.items():
                if not c["present"]:
                    continue
                for lst in c["items"].values():
                    for it in lst:
                        files = [r_ for r_ in it["reference_images"] if _is_file_ref(r_)]
                        if any(not (root / f).is_file() for f in files):
                            blockers += [f"missing_ref:{f}" for f in files if not (root / f).is_file()]
                        elif not files and it["reference_images"]:
                            blockers.append(f"ref_unresolved:{it['id']}:{'/'.join(it['reference_images'])}")
            blockers = list(dict.fromkeys(blockers))

            inputs = {
                "script": {k: getattr(s, k) for k in ("img_prompt", "img_triggers", "motion_prompt", "motion_triggers",
                                                      "decor_state", "duration")},
                "globals": globals_h, "episode_negative": ep.negative_extra,
                "looks": {c: [v["look_hash"], v.get("makeup_state"), v.get("makeup_overlay"), v["present"],
                              {sl: [[i["id"], i["description"], i["reference_images"]] for i in lst]
                               for sl, lst in v["items"].items()}] for c, v in chars.items()},
                "scene_id": grp["scene_id"], "plate_sha256": plate["plate_sha256"],
                "masters": {c: _master(root, c) for c, v in chars.items() if v["present"]},
                "loras": [[r_["trigger"], r_["sha256"]] for r_ in req],
                "bible": {**bible_sec, "characters": {c: _h(ctx.char_cfg.get(c)) for c, v in chars.items()
                                                      if v["present"]}},
            }
            inputs_sha = _h(inputs)[:16]
            row = {"shot_id": s.id, "gpu3_shot_id": f"ep{ep.number:02d}s{s.index}", "episode": ep.number,
                   "index": s.index, **{k: v for k, v in grp.items() if k != "shot_id"},
                   "characters": chars, "required_loras": req, "s2_ready": not blockers, "s2_blockers": blockers,
                   "inputs_sha": inputs_sha, "prev_inputs_sha": prev_inputs.get(s.id)}
            row["changes_from_prev_shot"] = {
                "prev_shot_id": prev["shot_id"] if prev else None,
                "scene_changed": bool(prev) and prev["scene_id"] != grp["scene_id"],
                "segment_changed": bool(prev) and prev["segment_id"] != grp["segment_id"],
                "characters": {c: d for c, v in chars.items()
                               if (d := _diff((prev or {}).get("characters", {}).get(c), v))} if prev else {},
            }
            row["needs_review"] = any(v["needs_review"] for v in chars.values() if v["present"]) \
                or not grp["place_key"]
            row["bible_version"] = version
            _gpu3_fields(row, s, chars, prop_cands, res.items, prev, seg_order, seg_props)
            seg_props.update({p_["id"]: p_ for p_ in row["props"]})
            img_text[s.id] = _clean(s.img_prompt)
            shots_out.append(row)
            prev = row

    # 场景
    scenes: dict[str, dict] = {}
    for row in shots_out:
        sc = scenes.setdefault(row["scene_id"], {
            "scene_id": row["scene_id"], "episode": row["episode"], "episodes": [], "place": row["place"],
            "place_key": row["place_key"], "time_of_day": "", "times": [], "shots": [], "segments": [],
            **plates[row["scene_id"]], "needs_review": not row["place_key"]})
        if row["episode"] not in sc["episodes"]:
            sc["episodes"].append(row["episode"])
        sc["shots"].append(row["shot_id"])
        if not sc["segments"] or sc["segments"][-1]["segment_id"] != row["segment_id"]:
            sc["segments"].append({"segment_id": row["segment_id"], "episode": row["episode"],
                                   "time_of_day": row["time_of_day"], "shots": [],
                                   "prev_segment_id": row["prev_segment_id"], "cut_type": row["cut_type"]})
        sc["segments"][-1]["shots"].append(row["shot_id"])
    for sc in scenes.values():
        times = Counter(seg["time_of_day"] for seg in sc["segments"] for _ in seg["shots"] if seg["time_of_day"])
        sc["times"] = sorted(times)
        sc["time_of_day"] = times.most_common(1)[0][0] if times else ""
        sc["plate_exists"] = sc["plate_status"] != "missing"
        for seg in sc["segments"]:
            seg["light"] = G.light_of([img_text[x] for x in seg["shots"]], seg["time_of_day"])
        # gpu3：底板对象（原 plate 字符串保留不动，见 docs「gpu3 渲染侧字段」）
        sc["plate_detail"] = {"path": sc["plate"], "sha256": sc["plate_sha256"], "status": sc["plate_status"],
                              "light": G.light_of([img_text[x] for x in sc["shots"]], sc["time_of_day"])}
    scene_list = sorted(scenes.values(), key=lambda x: (x["episode"], x["shots"][0]))
    scenes_sha = _h(scene_list)[:16]

    per_ep: dict[str, dict] = {}
    for row in shots_out:
        e = per_ep.setdefault(str(row["episode"]), {"shots": 0, "scenes": set(), "segments": set(),
                                                    "needs_review": 0, "s2_ready": 0})
        e["shots"] += 1
        e["scenes"].add(row["scene_id"])
        e["segments"].add(row["segment_id"])
        e["needs_review"] += row["needs_review"]
        e["s2_ready"] += row["s2_ready"]
    per_ep = {k: {**v, "scenes": len(v["scenes"]), "segments": len(v["segments"])} for k, v in per_ep.items()}
    seg_light = {seg["segment_id"]: seg["light"] for sc in scene_list for seg in sc["segments"]}
    episode_segments: dict[str, list[dict]] = {}
    for row in shots_out:
        lst = episode_segments.setdefault(str(row["episode"]), [])
        if not lst or lst[-1]["segment_id"] != row["segment_id"]:
            lst.append({"segment_id": row["segment_id"], "prev_segment_id": row["prev_segment_id"],
                        "scene_id": row["scene_id"], "place": row["place"], "time_of_day": row["time_of_day"],
                        "transition": row["transition"], "cut_type": row["cut_type"],
                        "light": seg_light[row["segment_id"]], "shots": []})
        lst[-1]["shots"].append(row["shot_id"])
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    head = {"generated_at": now, "bible_version": version, "source": source, "provisional": provisional,
            "s1_gate": {k: gate[k] for k in ("validator_errors", "g3_accepted", "g3_ref", "checked_at")}}
    timeline = {
        "format": FORMAT, **head, "source_hashes": all_hashes, "scenes_sha": scenes_sha,
        "episodes": episodes,
        "stats": {"shots": len(shots_out), "scenes": len(scene_list),
                  "segments": len({r["segment_id"] for r in shots_out}),
                  "needs_review_shots": sum(r["needs_review"] for r in shots_out),
                  "s2_ready_shots": sum(r["s2_ready"] for r in shots_out),
                  "unknown_place_segments": len({r["segment_id"] for r in shots_out if not r["place_key"]}),
                  "per_episode": per_ep, "gpu3": gpu3_stats(shots_out, scene_list)},
        "episode_segments": episode_segments,
        "shots": shots_out,
    }
    scenes_doc = {"format": SCENES_FORMAT, **head, "scenes_sha": scenes_sha, "scenes": scene_list}
    return timeline, scenes_doc


def _gpu3_fields(row: dict, s: Shot, chars: dict, cands: list[dict], wardrobe: dict, prev: dict | None,
                 seg_order: list[str], seg_props: dict[str, dict]) -> None:
    """gpu3 渲染侧字段（docs/state_timeline.md「gpu3 渲染侧字段」），就地写进 row 与 row.characters"""
    img, motion = _clean(s.img_prompt), _clean(s.motion_prompt)
    present = [c for c, v in chars.items() if v["present"]]
    props = G.shot_props(s, img, motion, cands, present, chars, seg_props)
    changes = G.shot_changes(img, motion, cands, present, chars, props)
    G.reconcile(props, changes)
    for slug, c in chars.items():
        ch = changes.get(slug, []) if c["present"] else []
        end = G.end_state(c, ch, wardrobe, img, motion)
        worn = [p["id"] for p in props if p["holder"] == slug and p["state"] == "worn"]
        worn_end = [p["id"] for p in props if p["holder"] == slug and p["state_end"] == "worn"]
        start_items = {sl: [i["id"] for i in lst] for sl, lst in c["items"].items()}
        c["changes_within_shot"] = ch
        c.update(end)
        c["signature"] = G.signature(start_items, c["adornments"], worn)
        adorn_end = c["adornments"] if end["visibility_end"] != "in_box" else \
            [dict(a, worn=False) if a["removable"] else a for a in c["adornments"]]
        c["signature_end"] = G.signature(end["items_end"], adorn_end, worn_end)
    framing, fsrc = G.shot_framing(img, motion)
    faces, facesrc = G.faces_visible(img, framing, present)
    i = seg_order.index(row["segment_id"])
    row.update({"props": props, "framing": framing, "framing_source": fsrc, "faces_visible": faces,
                "faces_visible_source": facesrc, "prev_segment_id": seg_order[i - 1] if i else None,
                "cut_type": G.cut_type(row["transition"]) if row["segment_start"] else prev["cut_type"]})


def gpu3_stats(shots: list[dict], scenes: list[dict]) -> dict:
    props = [p for r in shots for p in r["props"]]
    chs = [(r["shot_id"], c) for r in shots for c in r["characters"].values()]
    return {
        "props": len(props), "props_by_state": dict(Counter(p["state"] for p in props)),
        "props_by_state_source": dict(Counter(p["state_source"] for p in props)),
        "props_trigger_conflict": sum(p["trigger_conflict"] for p in props),
        "props_look_conflict": sum(p["look_conflict"] for p in props),
        "shots_with_changes": len({sid for sid, c in chs if c["changes_within_shot"]}),
        "changes": sum(len(c["changes_within_shot"]) for _, c in chs),
        "changes_guess": sum(x["source"] == "guess" for _, c in chs for x in c["changes_within_shot"]),
        "framing": dict(Counter(r["framing"] for r in shots)),
        "framing_guess": sum(r["framing_source"] == "guess" for r in shots),
        "faces_visible_guess": sum(r["faces_visible_source"] == "guess" for r in shots),
        "cut_type": dict(Counter(r["cut_type"] for r in shots if r["segment_start"])),
        "scene_light_unknown": {k: sum(sc["plate_detail"]["light"][k] is None for sc in scenes)
                                for k in ("time", "key_direction", "colour_temp")},
    }


def timeline_path(root: Path) -> Path:
    return root / "data" / "state_timeline.json"


def scenes_path(root: Path) -> Path:
    return root / "data" / "scenes.json"


def _atomic(p: Path, obj) -> None:
    """唯一临时文件（同目录 mkstemp）+ os.replace：并发写不会互相踩同一个 .tmp"""
    import tempfile
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="
") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "
")
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_timeline(root: str | Path | None = None) -> dict | None:
    try:
        return json.loads(timeline_path(project_root(root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _plate_files(root: Path) -> list[Path]:
    """每个场景 manifest 里登记的底板文件（不只 plate.png）"""
    out = []
    for m in sorted((root / "assets" / "scenes").glob("*/manifest.json")):
        try:
            name = json.loads(m.read_text(encoding="utf-8")).get("plate") or "plate.png"
        except (OSError, ValueError, AttributeError):
            name = "plate.png"
        out.append(m.parent / name)
    return sorted(set(out) | set((root / "assets" / "scenes").glob("*/plate.png")))


def input_files(root: Path) -> list[Path]:
    """时间线的全部输入文件（stat 键用于缓存 / 重建后复核）"""
    return [root / "config" / "visual_bible.toml", root / "data" / "import" / "script_v2.json",
            *sorted((root / "data" / "looks").glob("*.json")), root / "comfy" / "models.lock",
            root / LORA_REGISTRIES[1], root / "config" / "shot_ownership.json",
            root / "config" / "face_reference.json",
            *sorted((root / "assets" / "scenes").glob("*/manifest.json")), *_plate_files(root),
            *sorted((root / "assets" / "characters").glob("*/plates/master.png")), root / S1_GATE]


LOCK_STALE_S = 600.0
LOCK_TIMEOUT_S = 300.0
_build_tlock = threading.Lock()


class _BuildLock:
    """跨进程串行化重建：data/.state_timeline.lock（O_EXCL 创建；超过 LOCK_STALE_S 的视为残留）"""

    def __init__(self, root: Path):
        self.path = root / "data" / ".state_timeline.lock"

    def __enter__(self):
        _build_tlock.acquire()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_S:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() - t0 > LOCK_TIMEOUT_S:
                    _build_tlock.release()
                    raise TimeoutError(f"{self.path} 被占用超过 {LOCK_TIMEOUT_S:.0f}s")
                time.sleep(0.05)
            except BaseException:
                _build_tlock.release()
                raise

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass
        finally:
            _build_tlock.release()


def write(root: str | Path | None = None) -> tuple[dict, dict]:
    """建好再写；建的过程中输入变了（stat 键不同）→ 重建，不写过期结果。多进程/线程串行"""
    from .bible import _stat_key
    root = project_root(root)
    with _BuildLock(root):
        for _ in range(5):
            key = _stat_key(input_files(root))
            timeline, scenes = build(root, previous=read_timeline(root))
            if _stat_key(input_files(root)) == key:
                break
        _atomic(timeline_path(root), timeline)
        _atomic(scenes_path(root), scenes)
    return timeline, scenes


# ------------------------------------------------------------------ 过期检测（compiled.json / Take 盖章用）

_INPUTS_CACHE: dict = {}


def shot_inputs_sha(shot_id: str, root: str | Path | None = None) -> str | None:
    """本镜当前 inputs_sha（按输入文件 mtime 缓存整份时间线；算不出返回 None，不影响渲染）"""
    from .bible import _stat_key
    root = project_root(root)
    key = _stat_key(input_files(root))
    hit = _INPUTS_CACHE.get(str(root))
    if not hit or hit[0] != key:
        try:
            tl, _ = build(root)
            hit = (key, {s["shot_id"]: s["inputs_sha"] for s in tl["shots"]})
        except Exception:  # noqa: BLE001
            hit = (key, {})
        _INPUTS_CACHE[str(root)] = hit
    return hit[1].get(shot_id)


# ------------------------------------------------------------------ 自动重建（导入剧本 / 造型修改后）

_timers: dict[str, threading.Timer] = {}
_timer_lock = threading.Lock()
AUTOBUILD_DELAY = 2.0


def schedule_rebuild(root: str | Path | None = None, delay: float | None = None) -> None:
    """防抖后台重建（造型 API 连续修改只建一次；每个项目根各自防抖）。NS_TIMELINE_AUTOBUILD=0 关闭"""
    if os.environ.get("NS_TIMELINE_AUTOBUILD", "1") == "0":
        return
    key = str(project_root(root))

    def run():
        try:
            write(root)
            from .prompt_snapshot import save_snapshot
            save_snapshot(root)
        except Exception as e:  # noqa: BLE001 — 重建失败不影响造型保存
            print(f"[state_timeline] 重建失败：{type(e).__name__}: {e}")
    with _timer_lock:
        if key in _timers:
            _timers[key].cancel()
        t = _timers[key] = threading.Timer(AUTOBUILD_DELAY if delay is None else delay, run)
        t.daemon = True
        t.start()


def summary(timeline: dict) -> str:
    st = timeline["stats"]
    lines = [f"bible_version {timeline['bible_version']}  source {timeline['source']['script']}  "
             f"provisional={timeline['provisional']}",
             f"镜 {st['shots']}，场景 {st['scenes']}，段 {st['segments']}（地点未知 {st['unknown_place_segments']}），"
             f"needs_review {st['needs_review_shots']}，s2_ready {st['s2_ready_shots']}"]
    for ep, v in st["per_episode"].items():
        lines.append(f"  ep{int(ep):02d}: 镜 {v['shots']} 场景 {v['scenes']} 段 {v['segments']} "
                     f"needs_review {v['needs_review']} s2_ready {v['s2_ready']}")
    return "\n".join(lines)

