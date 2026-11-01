"""剧本 Markdown（写作模型产出）→ Shot Spec v2。

- 主体字段沿用现有导入器 services/agent/ns_agent/importer/script_md.py（ScriptImport）：img / 场景 / 人物 / 衔接 / motion /
  时长 / sound / 对白 / 🎙 / H3提示词。
- 新增字段（docs/ep02_iter/writer_rules_addendum.md）写成镜头里的普通 **标签**：行，现有导入器把未知标签放进
  shot.extras，本模块逐个解析：站位、地标、光线、分拍、镜头运动、嘴型、台词时段、独白时段、出画、下镜、尾帧曝光、镜型。
- 资产侧字段（身份参考图、定稿关键帧）从 assets/ 与 data/renders/ 读，不由写作方写。
只做确定性映射，原文原样保留，不补写内容；缺什么由 ns_schema.shot_spec.missing_fields() 列给写作方。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ns_schema.shot_spec import (CAMERA_MOVES, SIZES, Audio, Beat, Camera, Continuity, Exited, FrameIntent, H3Text,
                                 IdentityRef, Landmark, Lighting, Motion, OnScreenCharacter, Rating, Scene, ShotSpec,
                                 Source, SpeechSeg)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IDS = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu"}   # ns_agent.asset_revs.CHARACTERS
SPEECH_CPS = 4.5   # 估算语速（字/秒），只在剧本没写时段时用；待 ASR 校准（LEARNED_SPECS 待验）
SPEECH_LEAD_S = 0.5

TIME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[–\-~～至到]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?")
AMP = {"小": "small", "中": "medium", "大": "large", "small": "small", "medium": "medium", "large": "large"}
SPD = {"慢": "slow", "正常": "normal", "快": "fast", "slow": "slow", "normal": "normal", "fast": "fast"}
EXPO = {"正常": "normal", "暗": "dark", "全黑": "black", "黑": "black", "normal": "normal", "dark": "dark", "black": "black"}
MOUTH = {"张": "open", "开": "open", "open": "open", "闭": "closed", "closed": "closed"}
MOVE_ALIASES = {"static camera": "static shot", "static": "static shot", "fixed camera": "static shot",
                "push-in": "push in", "pull-out": "pull out", "tracking": "tracking shot", "arc": "arc shot"}


def rules_version(root: Path = ROOT) -> str | None:
    """当前写作规则版本：config/script_chat.json default_rules + config/script_chat_rules.md 里的 rules_addendum_version"""
    parts = []
    try:
        parts.append(json.loads((root / "config" / "script_chat.json").read_text(encoding="utf-8")).get("default_rules"))
    except (OSError, ValueError):
        pass
    try:
        ms = re.findall(r"rules_addendum_version:\s*(\S+?)[。.\s]", (root / "config" / "script_chat_rules.md").read_text(encoding="utf-8"))
        parts.append(ms[-1] if ms else None)   # 附录逐版追加，最后一个 = 当前版本
    except OSError:
        pass
    parts = [x for x in parts if x]
    return "+".join(parts) or None


MS_RULES_RE = re.compile(r"(?:rules_version|writer_rules_version)\s*[:：=]\s*([A-Za-z0-9_.+\-]+)")


def manuscript_rules_version(md_text: str | None) -> str:
    """稿件写作时用的规则版本：稿件里的 `rules_version: rules_v2+sysimpl-v2`（通常在头部注释，写作链路落稿时盖章）。
    取不到 = "unknown"（不拿导入时的当前配置冒充写稿版本，CHAINSPEC 2026-10-31 指出）"""
    m = MS_RULES_RE.search(md_text or "")
    return m.group(1) if m else "unknown"


def stamp(md_text: str, version: str | None = None) -> str:
    """给新稿盖规则版本章（写作链路 / Autopilot 落稿时用）"""
    v = version or rules_version() or "unknown"
    return f"<!-- rules_version: {v} -->\n" + (md_text or "")


def _sha16(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


IDENTITY_MANIFEST = "data/assets/identity_refs/manifest.json"


def identity_ref(char_id: str, root: Path = ROOT) -> IdentityRef | None:
    """优先项目方登记的身份图（data/assets/identity_refs/manifest.json，by=owner，Ref2VA 用脸部裁切），
    其次 assets/characters/<id>/<id>.png（定妆）"""
    man = root / IDENTITY_MANIFEST
    if man.exists():
        try:
            mj = json.loads(man.read_text(encoding="utf-8"))
            ent = (mj.get("chars") or {}).get(char_id) or {}
            f = ent.get("file")
            if f and (root / f).exists():
                return IdentityRef(path=f, sha=_sha16(root / f),
                                   version=f"manifest:{mj.get('registered_at', '')}:{ent.get('source_sheet', '')[-24:]}")
        except (OSError, ValueError):
            pass
    d = root / "assets" / "characters" / char_id
    for name in (f"{char_id}.png", f"{char_id}.jpg"):
        p = d / name
        if p.exists():
            ver = None
            prov = d / f"{char_id}.provenance.json"
            if prov.exists():
                try:
                    pj = json.loads(prov.read_text(encoding="utf-8"))
                    ver = (pj.get("rev") or pj.get("version") or (pj.get("sha256") or "")[:12]) or None
                except (OSError, ValueError):
                    pass
            return IdentityRef(path=str(p.relative_to(root)).replace("\\", "/"), sha=_sha16(p), version=ver)
    return None


def locked_keyframes(shot_id: str, root: Path = ROOT) -> dict[str, IdentityRef]:
    ep, s = shot_id.split("-")
    tk = root / "data" / "renders" / ep / s / "takes.json"
    out: dict[str, IdentityRef] = {}
    if not tk.exists():
        return out
    try:
        d = json.loads(tk.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    locked = d.get("locked") or {}
    for key, stage in (("first", "image"), ("last", "last")):
        n = locked.get(stage)
        if n is None:
            continue
        t = next((t for t in d.get("takes", []) if t.get("stage") == stage and t.get("n") == n), None)
        if t and t.get("file"):
            p = root / "data" / t["file"]
            out[key] = IdentityRef(path="data/" + t["file"], sha=_sha16(p), version=f"{stage}#{n}")
    return out


# ---------------------------------------------------------------------------------------------
def size_of(img: str) -> str | None:
    hits = [(img.find(w), -len(w), w) for w in SIZES if w in (img or "")]
    return min(hits)[2] if hits else None


def camera_from_motion(motion: str) -> tuple[str | None, str | None, str | None]:
    low = (motion or "").lower()
    move = None
    for alias, canon in MOVE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            move = canon
            break
    if move is None:
        hits = [(low.find(m), m) for m in CAMERA_MOVES if re.search(rf"\b{re.escape(m)}\b", low)]
        move = min(hits)[1] if hits else None
    amp = "small" if "small amplitude" in low else ("large" if "large amplitude" in low else None)
    spd = "slow" if "slow speed" in low else ("fast" if "fast speed" in low else None)
    return move, amp, spd


def _kv(text: str, seps: str = "｜|") -> dict[str, str]:
    out = {}
    for part in re.split(f"[{seps}]", text or ""):
        if "=" in part or "＝" in part:
            k, v = re.split("[=＝]", part, 1)
            out[k.strip()] = v.strip()
    return out


def _items(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[；;]", text or "") if x.strip()]


def parse_positions(text: str) -> dict[str, tuple[str | None, str | None]]:
    """**站位**：林晚：朝镜头｜坐在桌前；顾沉：侧左｜俯身 → {name: (facing, pose)}"""
    out = {}
    for it in _items(text):
        m = re.match(r"^([^：:]+)[：:](.*)$", it)
        if not m:
            continue
        parts = [p.strip() for p in re.split(r"[｜|]", m.group(2))]
        facing = parts[0].removeprefix("朝").strip() if parts and parts[0] else None
        out[m.group(1).strip()] = (facing or None, parts[1] if len(parts) > 1 and parts[1] else None)
    return out


def parse_landmarks(text: str) -> list[Landmark]:
    """**地标**：门框@右三分之一｜EN=door frame；… （EN 名进重试锚点句，中文名只做对照）"""
    out = []
    for it in _items(text):
        kv = _kv(it)
        head = re.split(r"[｜|]", it)[0]
        name, _, pos = head.partition("@")
        out.append(Landmark(name=kv.get("EN") or name.strip(), screen_pos=pos.strip() or None))
    return out


def parse_lighting(text: str, baseline: str | None) -> Lighting:
    kv = _kv(text)
    return Lighting(key=kv.get("主光"), fill=kv.get("补光"), rim=kv.get("轮廓光"),
                    modifier=kv.get("修正") or kv.get("本镜修正"), baseline_text=baseline)


def parse_beats(text: str) -> list[Beat]:
    """**分拍**：0–2秒｜<动作>｜视线=<…>｜表情=<…>｜反应=<…>｜运镜=<…>｜位置=<…>｜声音=<…>｜交接=<…>；2–4秒｜…"""
    out = []
    # 只在“；”后面紧跟下一拍时间段时才断拍：拍内写两个人用“；”分隔时不会把一拍截断（PROMPT v2，ep02 S2 实测）
    items = [x.strip() for x in re.split(r"[；;](?=\s*\d+(?:\.\d+)?\s*(?:秒|s)?\s*[–\-~～至到]\s*\d)", text or "") if x.strip()]
    for it in items:
        m = TIME_RE.match(it)
        if not m:
            continue
        rest = it[m.end():].lstrip("｜| ")
        parts = [p.strip() for p in re.split(r"[｜|]", rest)]
        kv = _kv(rest)
        action = next((p for p in parts if p and "=" not in p and "＝" not in p), "")
        out.append(Beat(t0=float(m.group(1)), t1=float(m.group(2)), action=action, camera=kv.get("运镜"),
                        position=kv.get("位置"), audio=kv.get("声音"), handoff=kv.get("交接"),
                        gaze=kv.get("视线"), expression=kv.get("表情"), reaction=kv.get("反应")))
    return out


def parse_times(text: str) -> dict[int, tuple[float, float]]:
    """**台词时段**：1=0.5–3.0秒；2=3.5–5秒 → {1: (0.5, 3.0), …}"""
    out = {}
    for it in _items(text):
        m = re.match(r"^(?:第)?(\d+)(?:句)?\s*[=＝:：]\s*(.*)$", it)
        if m and (t := TIME_RE.search(m.group(2))):
            out[int(m.group(1))] = (float(t.group(1)), float(t.group(2)))
    return out


def _estimate(text: str, start: float) -> tuple[float, float]:
    n = len(re.sub(r"[\s，。！？、…—“”‘’：；,.!?]", "", text or ""))
    return start, round(start + n / SPEECH_CPS, 2)


def spec_from_shot(shot, ep, glob, *, root: Path = ROOT, script_file: str | None = None,
                   script_sha: str | None = None, with_assets: bool = True,
                   new_fields: dict[str, str] | None = None, rules_ver: str = "unknown") -> ShotSpec:
    extras = {e.label.split("（")[0].strip(): e.text for e in (shot.extras or [])}
    extras.update(new_fields or {})
    reg = {c.name: c for c in getattr(glob, "character_registry", []) or []}
    looks = {}
    for lk in getattr(ep, "looks", []) or []:
        if lk.from_shot is None or lk.from_shot <= shot.index:
            looks[lk.character] = lk.en or looks.get(lk.character)
    scene_entry = next((s for s in getattr(glob, "scene_library", []) or [] if s.scene_id == shot.scene_id), None)
    pos = parse_positions(extras.get("站位", ""))
    chars = []
    visible_names = []
    for c in shot.cast or []:
        if c.presence not in ("在画", "局部"):
            continue
        r = reg.get(c.name)
        cid = (r.char_id if r and r.char_id else None) or DEFAULT_IDS.get(c.name) or c.name
        facing, pose = pos.get(c.name, (None, None))
        face_visible = None
        if facing == "背对" or (c.presence == "局部" and c.part and "脸" not in c.part):
            face_visible = False
        chars.append(OnScreenCharacter(
            id=cid, name=c.name, presence=c.presence, screen_x=c.x, depth=c.depth, part=c.part, facing=facing,
            pose=pose, face_visible=face_visible, look=looks.get(c.name), en_phrase=(r.en if r else None) or None,
            voice_phrase=(r.voice if r else None) or None,
            identity_ref=identity_ref(cid, root) if with_assets and face_visible is not False else None))
        visible_names.append(c.name)
    if chars and not any(c.focus == "primary" for c in chars):
        chars[0].focus = "primary"
    known = set(reg) | set(DEFAULT_IDS) | set(visible_names)

    def norm(name):
        """说话人归一：“林晚内心” / “顾沉低声” → 以已登记角色名开头的取角色名"""
        if not name:
            return name
        return next((k for k in sorted(known, key=len, reverse=True) if name.startswith(k)), name)

    mentioned = sorted({norm(d.speaker) for d in shot.dialogue if d.speaker and norm(d.speaker) not in visible_names}
                       | ({norm(shot.voiceover.speaker)} if shot.voiceover and shot.voiceover.speaker
                          and norm(shot.voiceover.speaker) not in visible_names else set()))
    move, amp, spd = camera_from_motion(shot.motion_prompt)
    cm = _kv(extras.get("镜头运动", ""))
    if extras.get("镜头运动"):
        head = re.split(r"[｜|]", extras["镜头运动"])[0].strip().lower()
        move = MOVE_ALIASES.get(head, head) if head in CAMERA_MOVES or head in MOVE_ALIASES else move
        amp = AMP.get(cm.get("幅度", ""), amp)
        spd = SPD.get(cm.get("速度", ""), spd)
    times = parse_times(extras.get("台词时段", ""))
    dia, t = [], SPEECH_LEAD_S
    for i, d in enumerate(shot.dialogue, 1):
        note = (d.speaker_note or "") + " " + (d.stage or "")
        off = any(k in note for k in ("画外", "电话", "语音", "OS", "VO"))
        if i in times:
            t0, t1 = times[i]
            src = "script"
        else:
            t0, t1 = _estimate(d.text, t)
            src = "estimate"
        t = t1 + 0.3
        spk = norm(d.speaker or (d.speaker_note or "?"))
        dia.append(SpeechSeg(speaker=spk, speaker_id=DEFAULT_IDS.get(spk),
                             text=d.text, tone=d.speaker_note, t0=t0, t1=t1, t_source=src, off_screen=off))
    vo = None
    if shot.voiceover is not None and shot.voiceover.text:
        tv = TIME_RE.search(extras.get("独白时段", ""))
        if tv:
            vt0, vt1, vsrc = float(tv.group(1)), float(tv.group(2)), "script"
        else:
            (vt0, vt1), vsrc = _estimate(shot.voiceover.text, 0.0), "estimate"
        vo = SpeechSeg(speaker=norm(shot.voiceover.speaker) or "?", text=shot.voiceover.text, tone=shot.voiceover.note,
                       t0=vt0, t1=vt1, t_source=vsrc, off_screen=True)
    mouth = {}
    for it in _items(extras.get("嘴型", "")):
        k, _, v = it.partition("=")
        if MOUTH.get(v.strip()):
            mouth[k.strip()] = MOUTH[v.strip()]
    for d in dia:
        mouth.setdefault(d.speaker, "closed" if d.off_screen else "open")
    if vo:
        mouth.setdefault(vo.speaker, "closed")
    exited = []
    for it in _items(extras.get("出画", "")):
        name, _, rest = it.partition("——")
        where, _, why = rest.partition("｜")
        exited.append(Exited(name=name.strip(), where=where.strip() or None, why=why.strip() or None))
    motion_txt = shot.motion_prompt or ""
    end_state = motion_txt.rsplit("——", 1)[1].strip() if "——" in motion_txt else None
    h3_text = shot.h3_prompt
    h3_mode = None
    if h3_text:
        first = h3_text.strip().splitlines()[0]
        h3_mode = ("fl2va" if first.startswith("How the reference pictures align") and "Picture 2" in first else
                   "i2va" if first.startswith("For the target video") else
                   "ref2va" if first.startswith("subject_definitions") else "t2va")
    link = shot.link
    hard = "HARD CUT" in (shot.link_carry or "") or extras.get("硬切", "").strip() in ("是", "HARD CUT")
    spec = ShotSpec(
        id=shot.id, episode=shot.episode, index=shot.index,
        source=Source(script_file=script_file, script_sha=script_sha, line=shot.source_line,
                      rules_version=rules_ver),
        duration_s=float(shot.duration), duration_source=shot.duration_source,
        scene=Scene(id=shot.scene_id, time_of_day=scene_entry.time_of_day if scene_entry else None,
                    detail=shot.scene_detail,
                    landmarks=parse_landmarks(extras.get("地标", "")),
                    lighting=(parse_lighting(extras.get("光线", ""), scene_entry.light if scene_entry else None)
                              if (extras.get("光线") or scene_entry) else None)),
        camera=Camera(size=size_of(shot.img_prompt), move=move, amplitude=amp, speed=spd),
        characters_on_screen=chars, mentioned_only=mentioned, exited=exited,
        first_frame=FrameIntent(text=shot.img_prompt),
        end_frame=FrameIntent(text=end_state or "", exposure_intent=EXPO.get(extras.get("尾帧曝光", "").strip(), "normal")),
        motion=Motion(text=motion_txt, beats=parse_beats(extras.get("分拍", "")), end_state=end_state),
        audio=Audio(dialogue=dia, voiceover=vo, soundscape_en=shot.sound_h3 or None, soundscape_zh=shot.sound or None,
                    music_cue=shot.music_cue or None, mouth=mouth),
        continuity=Continuity(link=link, from_prev=shot.link_carry, to_next=extras.get("下镜") or None, hard_cut=hard),
        rating=Rating(explicit=shot.adult),
        h3=H3Text(mode=h3_mode, text=h3_text),
        recipe_hint=(extras.get("镜型") or None),
        keyframes=locked_keyframes(shot.id, root) if with_assets else {},
        extras={k: v for k, v in extras.items() if k not in KNOWN_EXTRAS},
    )
    # 场景光线：只有场景表基线、没有本镜 **光线** 行时，key/fill/rim 留空（missing_fields 不报 SS-S2，基线已继承）
    return spec


def scan_new_fields(md_text: str) -> dict[tuple[int, int], dict[str, str]]:
    """现有导入器把未知的镜头标签放进 ep.extras（丢了归属镜头），这里按行重新扫一遍，只取增补规则的新标签。
    → {(集, 镜): {标签: 原文}}"""
    from ns_agent.importer.script_md import EP_RE, FIELD_RE, SHOT_RE
    out: dict[tuple[int, int], dict[str, str]] = {}
    ep = shot = None
    for raw in md_text.splitlines():
        line = raw.rstrip().replace(r"\*", "*")
        if m := EP_RE.match(line):
            ep, shot = int(m.group(1)), None
            continue
        if line.startswith("## ") or line.startswith("# "):
            ep = shot = None
            continue
        if ep is None:
            continue
        if m := SHOT_RE.match(line):
            shot = int(m.group(1))
            continue
        if shot is not None and (m := FIELD_RE.match(line)):
            label = m.group(1).split("（")[0].strip()
            if label in KNOWN_EXTRAS:
                out.setdefault((ep, shot), {})[label] = (m.group(2) or "").strip()
    return out


KNOWN_EXTRAS = {"站位", "地标", "光线", "分拍", "镜头运动", "嘴型", "台词时段", "独白时段", "出画", "下镜", "尾帧曝光",
                "镜型", "硬切"}


def _source_for(si, episode: int):
    srcs = list(getattr(si, "sources", None) or [])
    return next((s for s in srcs if episode in (s.episodes or [])), srcs[0] if srcs else None)


def specs_from_import(si, episode: int, md_text: str | None = None, **kw) -> list[ShotSpec]:
    ep = next(e for e in si.episodes if e.number == episode)
    src = _source_for(si, episode)
    if md_text is None and src is not None:
        p = Path(src.path) if Path(src.path).is_absolute() else ROOT / src.path
        try:
            md_text = p.read_text(encoding="utf-8")
        except OSError:
            md_text = None
    nf = scan_new_fields(md_text) if md_text else {}
    rv = manuscript_rules_version(md_text)
    return [spec_from_shot(s, ep, si.globals, script_file=src.path if src else None,
                           script_sha=src.sha256 if src else None, new_fields=nf.get((episode, s.index)),
                           rules_ver=rv, **kw)
            for s in ep.shots]


def specs_from_markdown(path: Path, episode: int, **kw) -> list[ShotSpec]:
    from ns_agent.importer.script_md import import_script
    path = Path(path)
    return specs_from_import(import_script(path), episode, md_text=path.read_text(encoding="utf-8"), **kw)
