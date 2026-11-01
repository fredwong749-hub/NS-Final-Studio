"""
出片前资料闸门（PREP，2026-10-31）：一镜出首帧 / 尾帧 / 视频之前，剧本与资产资料是否齐全、彼此是否一致。

项目方原话：“现在你能不能把ep02真的完整全部资料才render？不具备资料的，会不要render，准好全部资料，prompt，镜头描写，
背景，等才render，目的是一次完整render能不能找出现在不一致性问题”。

和 ns_api/readiness.py（出图之后的就绪闸门：首尾帧同链、衔接、声音）互补：本模块只看“出图之前该有的资料”。
清单来自 docs/production_rules_v3.md §1.1–§1.5（人物表、集头造型行、每镜字段、H3 四块）与画布“每镜必有字段”
（REQUIREMENTS E3、canvas-ui-spec-v3-merge）。只查结构 / 字符串是否存在、是否逐字对得上，不写、不改、不评任何内容。

级别：
  missing   缺资料 → 整集出片（EB）与自动提交一律不出；项目方自己点的单镜出图照出，响应里带提醒
  conflict  资料都在但彼此对不上（例如 H3 锚点句没逐字包含人物表 EN 短语、说话人写“她”）→ 只提示，不拦

GET /api/episodes/{ep}/readiness → {episode, ready, total, episode_items, shots:[{id, ready, missing, conflicts, checked}]}
GET /api/readiness/checklist      → 清单本身（每项 key / 名称 / 级别 / 规则出处 / 由谁补）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["material-readiness"])

# 由谁补：写作模型（剧本文字）/ 资产（出图后定稿）/ 项目方（确认）
W, A, O = "写作模型", "资产", "项目方确认"

# (key, 名称, 缺了的级别, 规则出处, 由谁补)
CHECKLIST: list[tuple[str, str, str, str, str]] = [
    # ---- 集头（对本集每一镜都算）
    ("ep_cast", "集头·出场人物", "missing", "v3 §1.2 QW-E4", W),
    ("ep_scenes", "集头·用到的场景", "missing", "v3 §1.2 QW-E5", W),
    ("ep_music", "集头·配乐 / BGM", "missing", "v3 §1.2 R-C1", W),
    # ---- 人物（本镜在画 / 发声的每个角色）
    ("char_entry", "人物表行", "missing", "v3 §1.1 QW-P1", W),
    ("char_ethnicity", "人物族裔", "missing", "v3 §1.1 EN外貌短语（夜间定妆出成西方面孔的原因）", W + " + " + O),
    ("char_en", "人物 EN 外貌短语", "missing", "v3 §1.1 QW-P3", W),
    ("char_voice", "说话人 VOICE 声线", "missing", "v3 §1.1 QW-P4", W),
    ("look", "集头造型行（服装 / 鞋 / 妆 / 发 / EN）", "missing", "v3 §1.2 QW-E6", W),
    ("look_extra", "造型行·甲 / 饰品", "conflict", "v3 §1.2 造型槽位（选填，缺了只提示）", W),
    ("identity_ref", "人物身份参考图", "missing", "v3 §2.1 / §2.5", A),
    # ---- 场景
    ("scene_line", "场景行", "missing", "v3 §1.3 QW-SC1", W),
    ("scene_entry", "场景表条目", "missing", "v3 §1.1 全剧 / 本集场景表", W),
    ("scene_plate", "场景底图（定稿）", "missing", "v3 §2.2 / §2.4", A),
    # ---- 每镜字段
    ("cast_line", "人物行", "missing", "v3 §1.3 QW-CH1", W),
    ("link", "衔接行", "missing", "v3 §1.3 QW-LK1", W),
    ("img", "首帧提示词 img", "missing", "v3 §1.3 镜头行", W),
    ("motion", "镜头描写 motion", "missing", "v3 §1.3 S1-W1", W),
    ("camera", "运镜", "conflict", "v3 §1.3 QW-C1（motion 触发词后的英文运镜）", W),
    ("end_state", "尾帧描述（结束状态）", "missing", "v3 §1.3 IMG-L1", W),
    ("duration", "时长（剧本写明 4–15 秒）", "missing", "v3 §1.3 S1-W2", W),
    ("sound", "sound 行", "missing", "v3 §1.3 R-C1", W),
    ("h3_audio", "【H3 audio】声音", "missing", "v3 §1.3 QW-S1", W),
    ("music_cue", "【配乐】cue", "missing", "v3 §1.3 QW-M1", W),
    ("h3", "H3 视频提示词", "missing", "v3 §1.5", W),
    ("speaker", "对白 / 独白说话人", "conflict", "v3 §1.3 QW-D1 / QW-D2", W),
    ("h3_align", "H3 与剧本对齐（对齐句时长 / soundscape / 台词逐字）", "conflict", "v3 §1.5 P-B1 / H3-S1 / H3-D3", W),
    ("h3_anchor", "H3 锚点句含人物 EN + 造型 EN、声线", "conflict", "v3 §1.5 H3-X1 / H3-X3", W),
]
META = {k: {"label": lb, "level": lv, "rule": r, "who": who} for k, lb, lv, r, who in CHECKLIST}

# 族裔标记（只做字符串是否出现，不评价写的是什么）
ETHNICITY_WORDS = ("中国", "华人", "华裔", "东亚", "亚洲", "汉族", "日本", "韩国", "欧美", "白人", "黑人", "拉丁",
                   "混血", "Chinese", "East Asian", "Asian", "Japanese", "Korean", "Caucasian", "European", "white",
                   "Black", "African", "Latina", "Latino", "Hispanic", "mixed-race", "Western")
_ETH_RE = re.compile("|".join(re.escape(w) if not w.isascii() else rf"\b{re.escape(w)}\b" for w in ETHNICITY_WORDS),
                     re.I)
LINKS = ("接力", "同场换机位", "换场", "接上一集")
LOOK_REQUIRED = ("服装", "鞋", "妆", "发")
LOOK_EXTRA = ("甲", "饰品")
MOVES = ("push in", "pull out", "zoom in", "zoom out", "pan left", "pan right", "truck left", "truck right",
         "tilt up", "tilt down", "pedestal up", "pedestal down", "arc shot", "tracking shot", "static shot",
         "static camera")
_D_RE = re.compile(r"<d>\s*(?:\[[^\]]*\])?\s*(.*?)</d>", re.S)
_ALIGN_RE = re.compile(r"Picture 2 \(from Shot 1\) aligns with the ([0-9.]+)-second mark")
_SND_RE = re.compile(r"overall_soundscape:\s*(.*?)(?:\n\s*\n|$)", re.S)


def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _norm(s: str) -> str:
    return re.sub(r"[\s，。,.！!？?…—\-“”\"'‘’、：:；;（）()]", "", s or "")


def _item(key: str, reason: str, who: str | None = None, level: str | None = None) -> dict:
    m = META[key]
    return {"key": key, "label": m["label"], "level": level or m["level"], "reason": reason,
            "who": who or m["who"], "rule": m["rule"]}


# ------------------------------------------------------------------ 资产侧（只读）

def _asset_refs(root: Path) -> dict:
    try:
        d = json.loads((root / "data" / "assets" / "asset_refs.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def identity_ref(root: Path, slug: str | None, refs: dict) -> dict | None:
    """人物身份参考：资产参考图组里 role=identity 且没作废的一张；林晚另认 pipeline.CHARACTER_REFS 的母版图"""
    if not slug:
        return None
    for r in refs.get(slug) or []:
        if isinstance(r, dict) and r.get("role") == "identity" and not r.get("void") and r.get("file"):
            if (root / r["file"]).is_file():
                return {"ref_id": r.get("ref_id"), "file": r["file"]}
    if slug == "lin_wan":
        p = root / "assets" / "characters" / "lin_wan" / "lin_wan.png"
        if p.is_file():
            return {"ref_id": None, "file": p.relative_to(root).as_posix()}
    return None


def scene_plate(script, shot_id: str, scene_id: str, root: Path) -> dict | None:
    from ns_render import scene_plate as SP
    from ns_render import pipeline as P
    try:
        return SP.shot_plate(script, shot_id, root, P.RENDERS)
    except Exception:  # noqa: BLE001
        rec = SP.lock_record(root, scene_id)
        return {"plate_id": rec["plate_id"]} if rec else None


# ------------------------------------------------------------------ 人物

def _characters(script) -> tuple[dict, dict]:
    g = script.globals
    reg = {e.name: e for e in (g.character_registry or [])}
    locks = {c.name: c.description for c in (g.character_locks or [])}
    return reg, locks


def _slug(name: str, reg: dict) -> str | None:
    from ns_schema.looks import CHARACTER_SLUG
    e = reg.get(name)
    return (e.char_id if e and e.char_id else None) or CHARACTER_SLUG.get(name)


def speaker_of(speaker: str | None, note: str | None, known: set[str]) -> str | None:
    """说话人：导入器给的 speaker（v3）；旧导入没有时取括号开头的已登记角色名（“顾沉低声”→ 顾沉；“她慌”→ None）"""
    if speaker and speaker in known:
        return speaker
    note = (note or "").strip()
    return next((n for n in sorted(known, key=len, reverse=True) if note.startswith(n)), None)


def shot_people(shot, known: set[str]) -> tuple[list[str], list[str], bool]:
    """→ (在画 / 局部的角色, 说话人, 是否来自人物行)。没有人物行（旧剧本）时按 img 里出现的已登记角色名推断"""
    speakers = [speaker_of(d.speaker, d.speaker_note, known) for d in shot.dialogue]
    if shot.voiceover:
        speakers.append(speaker_of(shot.voiceover.speaker, shot.voiceover.note, known))
    speakers = [x for x in speakers if x]
    if shot.cast is not None:
        vis = [c.name for c in shot.cast if c.visible]
        return vis, list(dict.fromkeys(speakers)), True
    img = shot.img_prompt or ""
    vis = sorted((n for n in known if n in img), key=img.index)
    return vis, list(dict.fromkeys(speakers)), False


def current_look(ep, name: str, index: int) -> tuple[dict, str]:
    slots, en = {}, ""
    for lk in sorted((x for x in ep.looks if x.character == name), key=lambda x: x.from_shot or 0):
        if (lk.from_shot or 0) <= index:
            slots.update({k: v for k, v in lk.slots.items() if _txt(v)})
            en = lk.en or en
    return slots, en


# ------------------------------------------------------------------ 主函数

def episode_items(ep) -> list[dict]:
    out = []
    if not ep.cast:
        out.append(_item("ep_cast", "集头没有 **出场人物** 行（旧格式剧本）"))
    if not ep.scene_ids:
        out.append(_item("ep_scenes", "集头没有 **用到的场景** 行（旧格式剧本）"))
    if not (_txt(ep.music) and _txt(ep.music_bgm)):
        out.append(_item("ep_music", "集头 **配乐** 行缺中文说明或【BGM】英文"))
    return out


def shot_check(script, ep, shot, *, root: Path, refs: dict | None = None, plates: bool = True) -> dict:
    reg, locks = _characters(script)
    known = set(reg) | set(locks)
    scenes = {s.scene_id: s for s in (script.globals.scene_library or [])}
    refs = _asset_refs(root) if refs is None else refs
    miss: list[dict] = []
    conf: list[dict] = []
    vis, speakers, from_cast = shot_people(shot, known)
    people = list(dict.fromkeys(vis + speakers))

    # ---- 每镜字段
    if shot.cast is None:
        miss.append(_item("cast_line", "没有 **人物** 行" + (f"（按 img 推断在画：{'、'.join(vis)}）" if vis else "")))
    link = _txt(shot.link)
    if not link:
        miss.append(_item("link", "没有 **衔接** 行（不知道首帧是否接上一镜尾帧）"))
    elif link not in LINKS:
        conf.append(_item("link", f"衔接值“{link}”不在 {'/'.join(LINKS)} 里", level="conflict"))
    if not _txt(shot.img_prompt):
        miss.append(_item("img", "剧本没有首帧 img 提示词"))
    mo = _txt(shot.motion_prompt)
    if not mo:
        miss.append(_item("motion", "剧本没有 motion 镜头描写"))
    else:
        low = mo.lower()
        if not any(m in low for m in MOVES):
            conf.append(_item("camera", "motion 里没有认得的英文运镜词（camera push in / static shot …）"))
        end = mo.rsplit("——", 1)[1].strip(" ，。；、") if "——" in mo else ""
        if len(end) < 8:
            miss.append(_item("end_state", "motion 最后一个“——”之后没有结束状态（尾帧编辑提示词来源）"))
    if getattr(shot, "duration_source", "default") != "script" or not (4 <= int(shot.duration or 0) <= 15):
        miss.append(_item("duration", f"剧本没写 **时长**（现在按默认 {shot.duration}s）"
                          if getattr(shot, "duration_source", "") != "script" else f"时长 {shot.duration}s 不在 4–15"))
    if not _txt(shot.sound):
        miss.append(_item("sound", "剧本没有 **sound** 行"))
    if not _txt(shot.sound_h3):
        miss.append(_item("h3_audio", "sound 行没有【H3 audio】英文声音"))
    if not _txt(shot.music_cue):
        miss.append(_item("music_cue", "sound 行没有【配乐】cue"))
    h3 = _txt(shot.h3_prompt)
    if not h3:
        miss.append(_item("h3", "剧本没有 **H3提示词**"))

    # ---- 场景
    sid = _txt(shot.scene_id)
    if not sid:
        miss.append(_item("scene_line", "没有 **场景** 行（不知道本镜用哪个场景 / 底图）"))
    else:
        if sid not in scenes:
            miss.append(_item("scene_entry", f"场景表里没有 {sid}"))
        if ep.scene_ids and sid not in ep.scene_ids:
            conf.append(_item("scene_entry", f"{sid} 不在集头 **用到的场景** 里", level="conflict"))
        if plates and not scene_plate(script, shot.id, sid, root):
            miss.append(_item("scene_plate", f"{sid} 还没有定稿底图（assets/scenes/{sid}/manifest.json）"))

    # ---- 人物
    for name in people:
        e = reg.get(name)
        lock = locks.get(name, "")
        if name not in known:
            conf.append(_item("speaker", f"“{name}”不是已登记的角色名（人物表 / 角色锁里没有）"))
            continue
        if e is None:
            miss.append(_item("char_entry", f"{name}：人物表里没有这一行（只有角色锁）"))
        eth = " ".join(x for x in (e.en if e else "", e.zh if e else "", lock) if x)
        if not _ETH_RE.search(eth):
            miss.append(_item("char_ethnicity", f"{name}：人物表 / 角色锁都没写族裔"))
        if name in vis and not (e and _txt(e.en)):
            miss.append(_item("char_en", f"{name}：没有 EN外貌短语（H3 锚点句要逐字用）"))
        if name in speakers and not (e and _txt(e.voice)):
            miss.append(_item("char_voice", f"{name}：说话但没有 VOICE声线短语"))
        if name in vis:
            slots, en = current_look(ep, name, shot.index)
            lack = [k for k in LOOK_REQUIRED if not _txt(slots.get(k))] + ([] if _txt(en) else ["EN"])
            if not any(x.character == name for x in ep.looks):
                miss.append(_item("look", f"{name}：本集没有 **造型｜{name}** 行（服装 / 鞋 / 妆 / 发 / 甲 / 饰品 / EN）"))
            elif lack:
                miss.append(_item("look", f"{name}：造型行缺 {'、'.join(lack)}"))
            else:
                extra = [k for k in LOOK_EXTRA if not _txt(slots.get(k))]
                if extra:
                    conf.append(_item("look_extra", f"{name}：造型行没写 {'、'.join(extra)}"))
            if not identity_ref(root, _slug(name, reg), refs):
                miss.append(_item("identity_ref", f"{name}：没有可用的身份参考图（没有，或已作废）"))

    # ---- 说话人写法
    for d in shot.dialogue:
        if speaker_of(d.speaker, d.speaker_note, known) is None:
            conf.append(_item("speaker", f"对白括号（{d.speaker_note or ''}）没有以角色名开头，认不出说话人"))
    if shot.voiceover and speaker_of(shot.voiceover.speaker, shot.voiceover.note, known) is None:
        conf.append(_item("speaker", f"🎙 括号（{shot.voiceover.note or ''}）没有以角色名开头，认不出说话人"))

    # ---- H3 与剧本对齐
    if h3:
        from ns_schema.h3_lint import frames_for_seconds
        m = _ALIGN_RE.search(h3)
        want = f"{frames_for_seconds(shot.duration) / 24:.2f}"
        if m and m.group(1) != want:
            conf.append(_item("h3_align", f"对齐句写 {m.group(1)} 秒，剧本时长 {shot.duration}s 应为 {want}"))
        snd = _SND_RE.search(h3)
        if _txt(shot.sound_h3) and snd and _norm(snd.group(1)) != _norm(shot.sound_h3):
            conf.append(_item("h3_align", "overall_soundscape 与 sound 行【H3 audio】不是同一段文字"))
        said = [_norm(x) for x in _D_RE.findall(h3)]
        for d in shot.dialogue:
            if _norm(d.text) and _norm(d.text) not in said:
                conf.append(_item("h3_align", f"台词“{d.text[:16]}”在 H3 的 <d> 里没有逐字出现"))
        if from_cast:
            from ns_schema import h3_lint as L
            anchors = []
            for name in [c.name for c in shot.cast if c.presence == "在画"]:
                e = reg.get(name)
                if e and e.en:
                    anchors.append((f"{name} EN外貌短语", e.en))
                _, en = current_look(ep, name, shot.index)
                if en:
                    anchors.append((f"{name} 造型 EN", en))
            order = list(dict.fromkeys(x for x in (speaker_of(d.speaker, d.speaker_note, known)
                                                   for d in shot.dialogue) if x))
            voices = [(n, reg[n].voice if reg.get(n) else "") for n in order]
            try:
                for r in L.lint_h3_registry(h3, anchors=anchors, voices=voices if order else None):
                    if not r["ok"]:
                        conf.append(_item("h3_anchor", f"{r['rule_id']}：{r['detail']}"))
            except Exception as ex:  # noqa: BLE001
                conf.append(_item("h3_anchor", f"锚点检查没跑成：{type(ex).__name__}"))
    checked = sorted({k for k, *_ in CHECKLIST if not k.startswith("ep_")} - {x["key"] for x in miss + conf})
    return {"id": shot.id, "ready": not miss, "missing": miss, "conflicts": conf, "people": people,
            "people_from": "人物行" if from_cast else "按 img 推断", "scene_id": sid or None, "ok": checked}


def episode_check(script, number: int, *, root: Path | None = None, plates: bool = True) -> dict:
    from ns_render import pipeline as P
    root = Path(root or P.ROOT)
    ep = next((e for e in script.episodes if e.number == number), None)
    if ep is None:
        raise KeyError(number)
    refs = _asset_refs(root)
    epi = episode_items(ep)
    shots = []
    for s in ep.shots:
        r = shot_check(script, ep, s, root=root, refs=refs, plates=plates)
        r["missing_count"] = len(r["missing"])
        r["ready"] = r["ready"] and not epi
        shots.append(r)
    return {"episode": number, "title": ep.title, "ready": sum(1 for x in shots if x["ready"]), "total": len(shots),
            "episode_items": epi, "missing_total": sum(x["missing_count"] for x in shots) + len(epi),
            "conflicts_total": sum(len(x["conflicts"]) for x in shots), "shots": shots}


def shot_gate(script, shot_id: str, root: Path | None = None) -> dict:
    """单镜闸门 → {ready, reasons:[中文]}（出片接口用）"""
    from ns_render import pipeline as P
    root = Path(root or P.ROOT)
    ep, s = P.find_shot(script, shot_id)
    epi = episode_items(ep)
    r = shot_check(script, ep, s, root=root)
    reasons = [f"{i['label']}：{i['reason']}" for i in epi + r["missing"]]
    return {"ready": not reasons, "reasons": reasons, "missing_count": len(reasons)}


def refuse_text(shot_id: str, reasons: list[str], limit: int = 6) -> str:
    more = f"（另 {len(reasons) - limit} 项）" if len(reasons) > limit else ""
    return f"{shot_id} 资料不全，不自动出：" + "；".join(reasons[:limit]) + more + \
        "。补齐后再出；项目方可在画布单镜手动出（会带提醒）"


# 出片接口的 by：这些算“自动提交”（整集出片 / 夜间 / SOP 驱动），资料不全一律 409；其余（画布上项目方点的）照出 + 提醒
AUTO_BY = ("auto", "episode_produce", "eb", "night", "nd", "sop")


def job_gate(script, shot_id: str, by: str | None) -> list[str]:
    """frame-jobs / video-jobs 用：自动提交且资料不全 → HTTP 409（中文原因）；手动 → 返回提醒列表（空 = 资料齐）"""
    auto = (by or "").strip().lower() in AUTO_BY
    try:
        g = shot_gate(script, shot_id)
    except Exception as e:  # noqa: BLE001
        if auto:
            raise HTTPException(409, f"{shot_id} 资料闸门没跑成，不自动出：{type(e).__name__}: {str(e)[:120]}")
        return []
    if g["ready"]:
        return []
    if auto:
        raise HTTPException(409, refuse_text(shot_id, g["reasons"]))
    more = f"（另 {len(g['reasons']) - 6} 项）" if len(g["reasons"]) > 6 else ""
    return [f"资料不全（项目方手动出，照出）：" + "；".join(g["reasons"][:6]) + more]


# ------------------------------------------------------------------ 接口

def _script():
    from ns_api import app as A
    return A._script


@router.get("/api/episodes/{ep}/readiness")
def get_episode_readiness(ep: int, plates: bool = True):
    try:
        return episode_check(_script(), ep, plates=plates)
    except KeyError:
        raise HTTPException(404, f"没有第 {ep} 集")


@router.get("/api/readiness/checklist")
def get_checklist():
    return {"items": [{"key": k, "label": lb, "level": lv, "rule": r, "who": who} for k, lb, lv, r, who in CHECKLIST],
            "levels": {"missing": "缺资料：整集出片 / 自动提交不出", "conflict": "对不上：只提示"}}
