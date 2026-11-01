"""音色试听 / 换音色（UIRSI 2026-10-31）。

项目方原话：“声音模型那边，我需要监听它的播放……接不接受？能不能修改？我连播放按钮都没有。”

  POST /api/voices/preview     {cid?, sid?, speed?, text?}  用本机 Kokoro（CPU，不花钱）合成一句试听，返回 wav 地址（按内容缓存）。
                               text 没给就取当前剧本里这个人物的第一句台词；都没有就用一句通用句。
  GET  /api/voices/candidates?cid=   同性别可选的音色（sid）列表，附已知名字
  POST /api/voices/{cid}/select {sid, speed?, by:"owner", note?}  一键换成这个音色（登录的项目方点选即生效）：
                               改 config/voices.json 这个人物的 sid / voice / speed（改前整份备份到 data/assets/voice_backups/），
                               之后合成成片就用新音色；撤销 = 再选回原来的 sid。
  GET  /api/voices/narrator-samples  旁白候选试听文件（旁白用远端复刻音色，本机不能现合成，列出已有样本）
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["voice-preview"])
_lock = threading.Lock()
FEMALE = (3, 57)      # sherpa-onnx kokoro-multi-lang-v1_1：sid 3..57 中文女声
MALE = (58, 102)      # 58.. 中文男声
FALLBACK = {"female": "今天的事，我想再好好想一想。", "male": "你先坐下，我们慢慢说。"}


def _voices_path() -> Path:
    return REPO / "config" / "voices.json"


def _cfg() -> dict:
    return json.loads(_voices_path().read_text(encoding="utf-8"))


def _post():
    p = str(REPO / "services" / "post")
    if p not in sys.path:
        sys.path.insert(0, p)
    from ns_post import tts  # noqa: PLC0415
    return tts


def _first_line(name: str) -> str | None:
    try:
        s = json.loads((REPO / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for ep in s.get("episodes", []):
        for sh in ep.get("shots", []):
            for d in sh.get("dialogue") or []:
                spk, txt = (d[0], d[1]) if isinstance(d, (list, tuple)) and len(d) >= 2 else (d.get("speaker"), d.get("text")) if isinstance(d, dict) else (None, None)
                if spk == name and txt and 4 <= len(txt) <= 40:
                    return re.sub(r"<[^>]+>", "", txt)
    return None


class PreviewBody(BaseModel):
    cid: str | None = None
    sid: int | None = None
    speed: float | None = None
    text: str | None = None


@router.post("/api/voices/preview")
def preview(body: PreviewBody):
    cfg = _cfg()
    ch = (cfg.get("characters") or {}).get(body.cid or "", {})
    sid = body.sid if body.sid is not None else ch.get("sid")
    if sid is None:
        raise HTTPException(422, "要给 cid 或 sid")
    speed = float(body.speed or ch.get("speed") or 1.0)
    if not 0.6 <= speed <= 1.5:
        raise HTTPException(422, "语速 0.6–1.5")
    gender = ch.get("gender") or ("female" if FEMALE[0] <= sid <= FEMALE[1] else "male")
    text = (body.text or "").strip() or _first_line(ch.get("name", "")) or FALLBACK.get(gender, FALLBACK["female"])
    text = text[:120]
    tts = _post()
    voice = tts.Voice(speaker=body.cid or f"sid{sid}", sid=int(sid), speed=speed)
    try:
        backend = tts.KokoroBackend(tts.load_voice_config(), num_threads=4)
        [path] = tts.synthesize_cached(backend, [(text, voice)])
    except tts.TtsUnavailable as e:
        raise HTTPException(503, f"这台电脑上的配音模型没装好，暂时不能试听（{e}）")
    except tts.TtsError as e:
        raise HTTPException(502, f"合成试听没成功：{e}")
    rel = Path(path).resolve().relative_to((REPO / "data").resolve()).as_posix()
    return {"url": f"/files/{rel}", "sid": sid, "speed": speed, "text": text}


@router.get("/api/voices/candidates")
def candidates(cid: str):
    cfg = _cfg()
    ch = (cfg.get("characters") or {}).get(cid)
    if not ch:
        raise HTTPException(404, f"没有这个人物：{cid}")
    lo, hi = FEMALE if ch.get("gender") == "female" else MALE
    known = {v.get("sid"): k for k, v in (cfg.get("characters") or {}).items()}
    cur = int(ch.get("sid") or lo)
    # 当前音色前后各几个 + 全部（前端先给“附近的”，再展开全部）
    near = [s for s in range(max(lo, cur - 4), min(hi, cur + 4) + 1)]
    return {"cid": cid, "current": cur, "near": near, "all": list(range(lo, hi + 1)),
            "used_by": {str(k): v for k, v in known.items() if k is not None}}


class SelectBody(BaseModel):
    sid: int
    speed: float | None = None
    by: str = ""
    note: str = ""


@router.post("/api/voices/{cid}/select")
def select(cid: str, body: SelectBody):
    if body.by != "owner":
        raise HTTPException(403, "换音色要登录的项目方本人操作")
    p = _voices_path()
    with _lock:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        ch = (cfg.get("characters") or {}).get(cid)
        if not ch:
            raise HTTPException(404, f"没有这个人物：{cid}")
        lo, hi = FEMALE if ch.get("gender") == "female" else MALE
        if not lo <= body.sid <= hi:
            raise HTTPException(422, "这个音色和人物性别不对")
        bk = REPO / "data" / "assets" / "voice_backups"
        bk.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, bk / f"voices_{time.strftime('%Y%m%d_%H%M%S')}.json")
        prev = {"sid": ch.get("sid"), "voice": ch.get("voice"), "speed": ch.get("speed")}
        ch["sid"] = int(body.sid)
        if prev["sid"] != ch["sid"]:
            ch["voice"] = f"sid{body.sid}"
        if body.speed:
            ch["speed"] = round(float(body.speed), 2)
        ch.setdefault("owner_selections", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": prev,
                                                        "to": {"sid": ch["sid"], "speed": ch.get("speed")}, "note": body.note})
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    return {"ok": True, "cid": cid, "prev": prev, "now": {"sid": ch["sid"], "speed": ch.get("speed")}}


@router.get("/api/voices/narrator-samples")
def narrator_samples():
    d = REPO / "data" / "review_pages" / "narrator_pick"
    out = []
    for f in sorted(d.rglob("*.mp3")) if d.is_dir() else []:
        rel = f.resolve().relative_to((REPO / "data").resolve()).as_posix()
        out.append({"name": f.stem, "url": f"/files/{rel}", "group": f.parent.name if f.parent != d else ""})
    try:
        cur = _cfg().get("voiceover_speaker")
    except (OSError, ValueError):
        cur = None
    return {"current": cur, "samples": out}


@router.get("/api/voices/in-script")
def in_script():
    """当前剧本里出现的人物名（出场 / 台词说话人）：音色页默认只列这些人（旧剧本的人物不显示）"""
    try:
        s = json.loads((REPO / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"names": []}
    names: set[str] = set()
    for ep in s.get("episodes", []):
        for sh in ep.get("shots", []):
            for c in sh.get("cast") or []:
                names.add(c if isinstance(c, str) else (c.get("name") or c.get("character") or ""))
            for d in sh.get("dialogue") or []:
                spk = d[0] if isinstance(d, (list, tuple)) and d else d.get("speaker") if isinstance(d, dict) else None
                if spk:
                    names.add(spk)
            vo = sh.get("voiceover")
            if isinstance(vo, (list, tuple)) and vo:
                names.add(vo[0])
            elif isinstance(vo, dict) and vo.get("speaker"):
                names.add(vo["speaker"])
    return {"names": sorted(n for n in names if n)}


# ================================================================== VOICE10 series10 角色音色候选（2026-11-01）
# 项目方一键答复“重做候选我来挑”。series10 的人物（P1 角色表 ∩ P3 有台词的人；旁白除外，仍是 QAg）只从
# data/assets/voices/<cid>_cand/<cN>/ 取候选（tools/voice10/voice10.py 生成并自动检查，checks.pass=true 才列出），
# 不再给这些人列 Kokoro 的“附近音色”。A = 现在 config/voices.json 里配的音色念同样两句台词（Kokoro 当场合成；
# 已选过候选的就是那个候选的 sample.wav），时长由后端量好一起返回。“用 B” = POST /api/voices/{cid}/pick（登录的项目方点选
# 即生效，审计由 auth 中间件记 data/audit/），撤销 = POST /api/voices/pick-undo/{undo_id}（10 秒内，前端 showUndo）。
#   GET  /api/voices/s10                 series10 人物 + 当前音色（可播放地址、时长）+ 过检候选 + 状态（待你挑 / 已选）
#   POST /api/voices/{cid}/pick          {cand:"c2", by:"owner"}   写 config/voices.json 这个人物（改前整份备份）
#   POST /api/voices/pick-undo/{undo_id} {by:"owner"}              这个人物恢复成选之前的样子（只动这一个人物）

import copy  # noqa: E402
import hashlib  # noqa: E402
import wave  # noqa: E402

def _vdir() -> Path:
    return REPO / "data" / "assets" / "voices"


def _udir() -> Path:
    return REPO / "data" / "assets" / "voice_backups" / "undo"


def _s10_run() -> Path:
    try:
        from ns_api.edits import engines_cfg  # noqa: PLC0415
        project = engines_cfg().get("project") or "series10_v1"
    except Exception:  # noqa: BLE001
        project = "series10_v1"
    return REPO / "data" / "pipeline" / "runs" / project


def _wav_s(p: Path) -> float | None:
    try:
        with wave.open(str(p), "rb") as w:
            return round(w.getnframes() / w.getframerate(), 2)
    except (OSError, wave.Error, EOFError):
        return None


def _url(p: Path) -> str:
    return "/files/" + p.resolve().relative_to((REPO / "data").resolve()).as_posix()


def _s10_cast() -> list[dict]:
    run = _s10_run()
    try:
        chars = json.loads((run / "P1_storyline.json").read_text(encoding="utf-8")).get("characters") or []
    except (OSError, ValueError):
        return []
    speakers: set[str] = set()
    for f in sorted(run.glob("ep[0-9][0-9]/P3_ep*_screenplay.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for sc in d.get("scenes") or []:
            for ln in sc.get("lines") or []:
                if ln.get("kind") == "dialogue" and ln.get("speaker"):
                    speakers.add(ln["speaker"])
    return [c for c in chars if c.get("name") in speakers and c.get("char_id")]


def _cands(cid: str) -> list[dict]:
    out = []
    d = _vdir() / f"{cid}_cand"
    dirs = [p for p in d.glob("c*") if p.is_dir() and p.name[1:].isdigit()]
    for cd in sorted(dirs, key=lambda p: int(p.name[1:])):
        try:
            m = json.loads((cd / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (m.get("checks") or {}).get("pass") or not (cd / "sample.wav").is_file() or not (cd / "ref.wav").is_file():
            continue
        it = m["checks"].get("items") or {}
        out.append({"cand": cd.name, "url": _url(cd / "sample.wav"), "ref_url": _url(cd / "ref.wav"),
                    "seconds": _wav_s(cd / "sample.wav"), "text": m.get("sample_text"),
                    "instruct": (m.get("design") or {}).get("instruct"), "seed": (m.get("design") or {}).get("seed"),
                    "checks": {k: v.get("value") for k, v in it.items() if k != "ref_ok"},
                    "asr": (it.get("cer") or {}).get("asr"), "voice": f"{cid}_cand/{cd.name}"})
    return out


def _current(cid: str, ch: dict | None, text: str) -> dict:
    """现在配置的音色真正念同样两句（可播放地址 + 量好的时长）"""
    if not ch:
        return {"kind": "none", "label": "还没有音色"}
    eng = ch.get("engine") or "kokoro"
    if eng != "kokoro":
        v = str(ch.get("voice") or "")
        cd = _vdir() / v
        if v.startswith(f"{cid}_cand/") and (cd / "sample.wav").is_file():
            return {"kind": "cand", "voice": v, "cand": cd.name, "label": f"候选 {cd.name[1:]}",
                    "url": _url(cd / "sample.wav"), "seconds": _wav_s(cd / "sample.wav"), "text": text}
        return {"kind": eng, "voice": v, "label": f"{v}（{eng}，远端复刻，本页不能现合成）"}
    if ch.get("sid") is None:
        return {"kind": "none", "label": "还没有音色"}
    tts = _post()
    voice = tts.Voice(speaker=cid, sid=int(ch["sid"]), speed=float(ch.get("speed") or 1.0))
    label = f"旧 Kokoro {ch.get('voice')}"
    try:
        backend = tts.KokoroBackend(tts.load_voice_config(), num_threads=4)
        [path] = tts.synthesize_cached(backend, [(text, voice)])
    except tts.TtsError as e:  # TtsUnavailable 是它的子类
        return {"kind": "kokoro", "voice": ch.get("voice"), "label": label, "error": f"本机合成没成功：{e}"}
    return {"kind": "kokoro", "voice": ch.get("voice"), "sid": ch.get("sid"), "label": label,
            "url": _url(Path(path)), "seconds": _wav_s(Path(path)), "text": text}


@router.get("/api/voices/s10")
def s10_voices():
    cfg = _cfg()
    chars = cfg.get("characters") or {}
    rows = []
    for c in _s10_cast():
        cid = c["char_id"]
        cands = _cands(cid)
        text = cands[0]["text"] if cands else (_first_line(c["name"]) or FALLBACK["female"])
        ch = chars.get(cid)
        cur = _current(cid, ch, text)
        picked = cur.get("kind") == "cand" and any(x["cand"] == cur.get("cand") for x in cands)
        dec = (ch or {}).get("owner_decision") or {}
        status = ("自动选" if dec.get("auto") else "已选") if picked else "待你挑"
        rows.append({"cid": cid, "name": c["name"], "gender": c.get("gender"), "age": c.get("age"),
                     "voice_phrase": c.get("voice_phrase"), "current": cur, "candidates": cands,
                     "status": status, "decision": dec if picked else None})
    return {"run": _s10_run().name, "characters": rows,
            "source": "data/assets/voices/<cid>_cand/<cN>/meta.json（tools/voice10/voice10.py，checks.pass=true）；旁白不在本表，仍是 QAg"}


class PickBody(BaseModel):
    cand: str
    by: str = ""


def _write_cfg(p: Path, cfg: dict) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


OWNER_AUTO_QUOTE = "音色问题,采取qad类似模型给林晚,和其他男人的,我来不及筛选"


@router.post("/api/voices/{cid}/pick")
def s10_pick(cid: str, body: PickBody):
    if body.by != "owner":
        raise HTTPException(403, "换音色要登录的项目方本人操作")
    return apply_pick(cid, body.cand, decision={
        "by": "owner", "how": "声音页 角色音色·旁白 → A/B → 用 B（登录点选，审计 data/audit/）",
        "context": "项目方点选（覆盖之前的自动选择）"}, note="项目方在声音页点选")


def apply_pick(cid: str, cand: str, *, decision: dict, note: str) -> dict:
    """选定一个 series10 候选：写 config/voices.json 这一个人物（改前重读 + 整份备份 + 撤销记录）。
    项目方点“用 B”和按检查自动选（tools/voice10/voice10.py autopick，项目方 2026-11-01 原话授权）走同一条路径。"""
    body = PickBody(cand=cand)
    cast = {c["char_id"]: c for c in _s10_cast()}
    if cid not in cast:
        raise HTTPException(404, f"{cid} 不是 series10 有台词的人物")
    if not any(x["cand"] == body.cand for x in _cands(cid)):
        raise HTTPException(404, f"{cid} 没有过检的候选 {body.cand}")
    cd = _vdir() / f"{cid}_cand" / body.cand
    meta = json.loads((cd / "meta.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256((cd / "ref.wav").read_bytes()).hexdigest()
    design = meta.get("design") or {}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    p = _voices_path()
    with _lock:
        cfg = json.loads(p.read_text(encoding="utf-8"))  # 改前重读（别的会话可能刚改过别的条目，只动这一个人物）
        chars = cfg.setdefault("characters", {})
        prev = copy.deepcopy(chars.get(cid))
        bk = REPO / "data" / "assets" / "voice_backups"
        bk.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, bk / f"voices_{time.strftime('%Y%m%d_%H%M%S')}.json")
        c, base = cast[cid], prev or {}
        # 语速只在项目方对语速有过原话决定时沿用（旧 Kokoro 音色调过的语速不带到新音色上）
        keep = {k: base[k] for k in ("speed", "vo_speed", "speed_owner_decision") if k in base}             if base.get("speed_owner_decision") else {}
        hist = list(base.get("owner_selections") or [])
        hist.append({"at": now, "from": {k: v for k, v in base.items() if k != "owner_selections"} or None,
                     "to": {"voice": f"{cid}_cand/{body.cand}"}, "note": note})
        f0 = (meta.get("checks") or {}).get("ref_f0_hz")
        chars[cid] = {
            "name": c["name"], "gender": {"女": "female", "男": "male"}.get(c.get("gender"), c.get("gender")),
            "age": c.get("age"), "series": _s10_run().name, "engine": "cosyvoice3_zs",
            "voice": f"{cid}_cand/{body.cand}", "speed": 1.0, **keep,
            "f0_hz": round(float(f0)) if f0 else None,
            "asset": f"data/assets/voices/{cid}_cand/{body.cand}/meta.json",
            "ref_wav": f"data/assets/voices/{cid}_cand/{body.cand}/ref.wav", "ref_sha256": sha,
            "note": f"series10 音色：Qwen3-TTS VoiceDesign 文字设计（{design.get('instruct')}，seed {design.get('seed')}，"
                    f"不克隆任何真人）+ Fun-CosyVoice3 zero-shot 复刻；候选 {body.cand}（{note}）",
            "owner_decision": {**decision, "at": now},
            "owner_selections": hist}
        _udir().mkdir(parents=True, exist_ok=True)
        undo_id = f"{cid}_{time.strftime('%Y%m%d_%H%M%S')}_{body.cand}"
        (_udir() / f"{undo_id}.json").write_text(
            json.dumps({"cid": cid, "prev": prev, "now_voice": chars[cid]["voice"]}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        _write_cfg(p, cfg)
    return {"ok": True, "cid": cid, "voice": chars[cid]["voice"], "undo_id": undo_id, "prev_voice": (prev or {}).get("voice")}


class UndoBody(BaseModel):
    by: str = ""


@router.post("/api/voices/pick-undo/{undo_id}")
def s10_pick_undo(undo_id: str, body: UndoBody):
    if body.by != "owner":
        raise HTTPException(403, "撤销要登录的项目方本人操作")
    if not re.fullmatch(r"[a-z0-9_]+", undo_id):
        raise HTTPException(422, "undo_id 不对")
    f = _udir() / f"{undo_id}.json"
    if not f.is_file():
        raise HTTPException(404, "没有这次选择的撤销记录")
    u = json.loads(f.read_text(encoding="utf-8"))
    p = _voices_path()
    with _lock:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        chars = cfg.setdefault("characters", {})
        cur = chars.get(u["cid"]) or {}
        if cur.get("voice") != u["now_voice"]:
            raise HTTPException(409, "这个人物之后又改过音色，不能撤销这一次")
        hist = list(cur.get("owner_selections") or []) + [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "undo": undo_id}]
        if u["prev"] is None:
            chars.pop(u["cid"], None)
        else:
            chars[u["cid"]] = {**u["prev"], "owner_selections": hist}
        _write_cfg(p, cfg)
    f.replace(f.with_name(f"{undo_id}.done.json"))
    return {"ok": True, "cid": u["cid"], "voice": (u["prev"] or {}).get("voice")}
