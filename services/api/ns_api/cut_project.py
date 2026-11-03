"""CUTEDIT（成片页剪辑器 P1，设计稿 data/review_pages/cutedit/index.html，总调度 11-02 批准自做轻量时间线）。

剪辑工程 = data/renders/epNN/_final/cut_project.json（可编辑 JSON，浏览器只改它；导出在服务端用 assemble.py 合成）：
    {schema, episode, rev, updated_at, base_timeline,
     segments: [{shot, index, kind: video|still|black, file, origin, source_duration_s, still_s,
                 trim_head_s, trim_tail_s, trim_by: auto|owner, replaced_from?, trim_adjusted?}],
     bgm: {file, offset_s, gain_db, fade_in_s, fade_out_s}, dialogue_source,
     speech: [... 基准时间线的对白 / 独白（只读，界面显示用）], final: {file, rev, at} | null, history: [...]}

    GET  /api/episodes/{n}/cut-project              工程（没有就从最新装配时间线建一份）；顺带：镜头重出了 → 自动换段、裁切沿用
    PUT  /api/episodes/{n}/cut-project              保存 {rev, segments:[{index, trim_head_s, trim_tail_s}], bgm:{...}}；rev 不对 → 409
    POST /api/episodes/{n}/cut-project/export       导出成片：先收下（202，立即返回），后台 tools/cut_export.py 合成（只用 CPU）
    GET  /api/episodes/{n}/cut-project/export       导出进度 {state, stage, pct, eta_s, started_at, output, error}
    GET  /api/cut-frame?src=/files/...&t=秒          时间线上镜头段的小图（ffmpeg 抽一帧，缓存 data/_cache/cutedit/）

规则：手动裁切（trim_by=owner）导出时优先于自动裁切（assemble.py cut_edit，tests/test_cutedit_assemble.py）；
没动过的镜头仍由装配器自动裁（行为不变）。不烧字幕（L-002）；配乐只在整集上一条（L-118）。
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import copy
import hashlib
import json
import re
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ns_render import pipeline as P

router = APIRouter(tags=["cut_project"])
SCHEMA = "ns.cut_project/1"
_lock = threading.Lock()
PROCS: dict[int, subprocess.Popen] = {}
MIN_KEEP_S = 0.2
CODE = Path(__file__).resolve().parents[3]   # 代码根（P.ROOT 可被 NS_PROJECT_ROOT 指到别处）
DEFAULT_EST_S = 180


def _fin(n: int) -> Path:
    return _RP.renders_for_data(P.DATA) / f"ep{n:02d}" / "_final"


def proj_path(n: int) -> Path:
    return _fin(n) / "cut_project.json"


def job_path(n: int) -> Path:
    return _fin(n) / "_cut_export_job.json"


def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _wj(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _rel(p: str | Path | None) -> str | None:
    if not p:
        return None
    s = str(p).replace("\\", "/")
    root = str(P.ROOT).replace("\\", "/").rstrip("/") + "/"
    return s[len(root):] if s.startswith(root) else s


def file_url(rel: str | None) -> str | None:
    """data/... → /files/...（StaticFiles 挂在 data/）"""
    if not rel:
        return None
    r = rel.replace("\\", "/")
    return "/files/" + r[5:] if r.startswith("data/") else None


def base_timeline(n: int) -> Path | None:
    """最新的装配时间线（成片版 epNN_*.timeline.json，不含剪辑导出自己的 _cut_）"""
    fin = _fin(n)
    c = [p for p in fin.glob(f"ep{n:02d}_*.timeline.json") if "_cut_" not in p.name] if fin.is_dir() else []
    return max(c, key=lambda p: p.stat().st_mtime) if c else None


def _seg_from_shot(sh: dict) -> dict:
    kind = sh.get("kind") or "black"
    if sh.get("missing") or not sh.get("file"):
        kind = "black"
    seg = {"shot": sh.get("shot"), "index": int(sh["index"]), "kind": kind, "file": _rel(sh.get("file")),
           "origin": sh.get("origin"), "source_duration_s": sh.get("source_duration_s"),
           "still_s": None if kind == "video" else sh.get("duration_s"),
           "trim_head_s": float(sh.get("trim_head_s") or 0.0) if kind == "video" else 0.0,
           "trim_tail_s": float(sh.get("trim_tail_s") or 0.0) if kind == "video" else 0.0,
           "trim_by": "auto"}
    seg["base_trim_head_s"] = seg["trim_head_s"]
    seg["base_length_s"] = float(sh.get("duration_s") or 0.0) or None
    return seg


def init_project(n: int) -> dict:
    tlp = base_timeline(n)
    if tlp is None:
        # NAVFLOW-F 11-03：界面只说大白话（不露命令行）；具体卡在哪一步由 /api/pipeline/status 给
        raise HTTPException(404, f"第 {n} 集的视频还没全部出来，系统拼出整集预览后这里才能剪")
    tl = _jl(tlp, {}) or {}
    bgm = tl.get("bgm") or {}
    speech = [{"kind": s.get("kind"), "shot": s.get("shot"), "speaker": s.get("speaker_name") or s.get("speaker"),
               "text": s.get("text"), "start_s": s.get("start_s"), "end_s": s.get("end_s"),
               "files": [_rel(f) for f in s.get("files") or []], "source": s.get("source")}
              for s in tl.get("speech") or [] if s.get("start_s") is not None]
    return {"schema": SCHEMA, "episode": n, "rev": 1, "updated_at": P.now(), "base_timeline": _rel(tlp),
            "base_duration_s": tl.get("duration_s"),
            "segments": [_seg_from_shot(s) for s in sorted(tl.get("shots") or [], key=lambda x: int(x["index"]))],
            "bgm": {"file": _rel(bgm.get("file")) if bgm.get("used") and bgm.get("file") else None, "offset_s": 0.0,
                    "gain_db": 0.0, "fade_in_s": 0.0, "fade_out_s": 0.0},
            "dialogue_source": (tl.get("settings") or {}).get("dialogue_source") or "h3",
            "speech": speech, "final": None, "history": [{"at": P.now(), "what": f"从 {tlp.name} 建工程"}]}


# ---------------- 镜头重出 → 自动换段、裁切沿用

_dur_cache: dict[tuple[str, float], float | None] = {}


def media_duration(rel: str) -> float | None:
    p = P.ROOT / rel
    try:
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return None
    if key not in _dur_cache:
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
            _dur_cache[key] = round(float(out), 3)
        except (OSError, ValueError, subprocess.SubprocessError):
            _dur_cache[key] = None
    return _dur_cache[key]


def clamp(head: float, tail: float, src_s: float | None) -> tuple[float, float, bool]:
    """和 assemble.clamp_trim 同一规则（至少留 0.2 s）；返回是否被收过"""
    h, t = max(0.0, float(head)), max(0.0, float(tail))
    if not src_s:
        return round(h, 3), round(t, 3), False
    h2 = min(h, max(0.0, src_s - MIN_KEEP_S))
    t2 = min(t, max(0.0, src_s - h2 - MIN_KEEP_S))
    return round(h2, 3), round(t2, 3), (abs(h2 - h) > 1e-6 or abs(t2 - t) > 1e-6)


def current_sources(n: int) -> dict[int, dict]:
    """现在每镜入选的视频（只读本机 state，和 assemble_series.plan 同一口径；读不到 → 空 = 不换段）"""
    try:
        if str(P.ROOT) not in sys.path:
            sys.path.insert(0, str(P.ROOT))
        from tools import assemble_series as AS  # noqa: PLC0415
        rows = AS.plan(n, AS.local_state(AS.host_of(n)), best_effort_video=False)
    except Exception:  # noqa: BLE001 — 读不到就不自动换
        return {}
    return {int(r["index"]): r for r in rows if r.get("kind") == "video" and r.get("file")}


def refresh_sources(proj: dict, cur: dict[int, dict] | None = None) -> list[str]:
    """镜头换了定稿 / 占位变成了视频 → 换段；手动裁切沿用（新片短了就收到片尾并标 trim_adjusted）。返回变化说明"""
    cur = current_sources(int(proj["episode"])) if cur is None else cur
    notes = []
    for seg in proj["segments"]:
        r = cur.get(int(seg["index"]))
        if not r:
            continue
        f = _rel(r["file"])
        if f == seg.get("file"):
            continue
        if not (P.ROOT / f).is_file():
            continue
        old = seg.get("file")
        src_s = media_duration(f)
        seg.update(kind="video", file=f, origin=f"{r['shot']} {r.get('chosen')} {r.get('recipe')} seed {r.get('seed')}",
                   source_duration_s=src_s, still_s=None, replaced_from=old)
        if seg.get("trim_by") == "owner":
            h, t, adj = clamp(seg["trim_head_s"], seg["trim_tail_s"], src_s)
            seg.update(trim_head_s=h, trim_tail_s=t, trim_adjusted=adj)
            if adj:
                mark_field(proj, f"trim:{seg['index']}", "system", f"S{seg['index']} 新片更短，裁切收到片尾")
        else:   # 没动过的镜头导出时由装配器自动裁；这里先按整段显示
            seg.update(trim_head_s=0.0, trim_tail_s=0.0, trim_adjusted=False)
        notes.append(f"S{seg['index']} 换成新片{'（裁切沿用' + ('，已收到片尾' if seg.get('trim_adjusted') else '') + '）' if seg.get('trim_by') == 'owner' else ''}")
    return notes


def ensure_base(proj: dict) -> bool:
    """早期工程没记基准（建工程时每镜的自动裁头 / 长度）→ 从基准时间线补上；对白 / 字幕的位置换算靠它"""
    if all("base_length_s" in s for s in proj["segments"]):
        return False
    tl = _jl(P.ROOT / proj["base_timeline"], {}) if proj.get("base_timeline") else {}
    by = {int(x["index"]): x for x in (tl or {}).get("shots") or []}
    for s in proj["segments"]:
        sh = by.get(int(s["index"]), {})
        s.setdefault("base_trim_head_s", float(sh.get("trim_head_s") or 0.0) if s.get("kind") == "video" else 0.0)
        s.setdefault("base_length_s", float(sh.get("duration_s") or 0.0) or None)
    return True


def load_project(n: int, *, refresh: bool = True) -> dict:
    with _lock:
        proj = _jl(proj_path(n))
        created = False
        if not proj or proj.get("schema") != SCHEMA:
            proj, created = init_project(n), True
        migrated = ensure_base(proj)
        notes = refresh_sources(proj) if refresh else []
        if notes:
            proj["rev"] = int(proj["rev"]) + 1
            proj["updated_at"] = P.now()
            proj["history"] = (proj.get("history") or [])[-49:] + [{"at": P.now(), "what": "；".join(notes), "by": "system"}]
        if created or notes or migrated:
            _wj(proj_path(n), proj)
        return proj


def segment_length(seg: dict) -> float:
    if seg.get("kind") == "video" and seg.get("source_duration_s"):
        return round(max(MIN_KEEP_S, float(seg["source_duration_s"]) - seg["trim_head_s"] - seg["trim_tail_s"]), 3)
    return float(seg.get("still_s") or 4.0)


def cut_edit_of(proj: dict) -> dict:
    """工程 → assemble_episode(cut_edit=...)：只有项目方动过的镜头带手动入出点"""
    trims = {str(s["index"]): [s["trim_head_s"], s["trim_tail_s"]] for s in proj["segments"]
             if s.get("kind") == "video" and s.get("trim_by") == "owner"}
    b = proj.get("bgm") or {}
    bgm = {k: b.get(k) for k in ("file", "offset_s", "gain_db", "fade_in_s", "fade_out_s")}
    order = [int(s["index"]) for s in proj["segments"]]
    return {"trims": trims, "bgm": bgm, **({"order": order} if order != sorted(order) else {})}


def subtitles_of(proj: dict) -> list[dict] | None:
    """项目方改过的字幕：[{shot, text, d0, d1}]（d0/d1 = 相对这一镜在成片里起点的秒数，别的镜头裁切 / 换序后仍跟着本镜走）；
    没改过 = None（导出时按对白自动出 srt）"""
    subs = proj.get("subtitles")
    return subs if isinstance(subs, list) else None


def seed_subtitles(proj: dict) -> list[dict]:
    """第一次改字幕时，从当前对白（按当前裁切 / 顺序平移后的时间）生成可编辑字幕"""
    base = {int(s["index"]): s for s in proj["segments"]}
    t, starts = 0.0, {}
    for sg in proj["segments"]:
        starts[int(sg["index"])] = t
        t += segment_length(sg)
    # 基准时间线里每镜起点（建工程时的顺序和自动裁切）
    bt, bstarts = 0.0, {}
    for sg in sorted(proj.get("base_segments") or proj["segments"], key=lambda x: int(x["index"])):
        bstarts[int(sg["index"])] = bt
        bt += float(sg.get("base_length_s") or segment_length(sg))
    out = []
    for x in proj.get("speech") or []:
        k = int(x["shot"])
        if k not in base or x.get("start_s") is None:
            continue
        d0 = float(x["start_s"]) - bstarts.get(k, 0.0)
        d1 = float(x["end_s"]) - bstarts.get(k, 0.0)
        if x.get("kind") == "dialogue" and base[k].get("kind") == "video":
            shift = float(base[k]["trim_head_s"]) - float(base[k].get("base_trim_head_s", base[k]["trim_head_s"]))
            d0, d1 = d0 - shift, d1 - shift
        out.append({"shot": k, "text": x.get("text") or "", "d0": round(max(0.0, d0), 3), "d1": round(max(d0 + 0.2, d1), 3)})
    return out


# ---------------- 换序导出：按新顺序给镜头重新编号（装配器内部按镜号排序、对白按镜号挂），导出后再还原剧本镜号

def renumber_for_order(episode: dict, sources: dict[int, dict], cut_edit: dict) -> tuple[dict, dict, dict, dict[int, int]]:
    """cut_edit["order"] = 剧本镜号的新排列 → (按位置 1..n 重编号的剧集副本, sources, cut_edit, {新号: 剧本镜号})。
    没换序 = 原样返回（back 为恒等）。对白 / 独白挂在镜头上，跟着镜头走；手动裁切按新号重挂。"""
    order = [int(x) for x in cut_edit.get("order") or []]
    shots = sorted(episode["shots"], key=lambda x: int(x["index"]))
    if not order:
        return episode, sources, cut_edit, {int(s["index"]): int(s["index"]) for s in shots}
    by = {int(s["index"]): s for s in shots}
    if sorted(order) != sorted(by):
        raise ValueError(f"剪辑工程的镜头顺序 {order} 和剧本镜头 {sorted(by)} 对不上")
    new_shots, back = [], {}
    for pos, orig in enumerate(order, 1):
        sh = dict(by[orig])
        sh["index"] = pos
        if isinstance(sh.get("id"), str):   # 镜头 id（epNN-SK）跟着新号走，导出后 relabel_timeline 还原
            sh["id"] = re.sub(r"-S\d+$", f"-S{pos}", sh["id"])
        new_shots.append(sh)
        back[pos] = orig
    fwd = {v: k for k, v in back.items()}
    ce = dict(cut_edit)
    ce.pop("order", None)
    ce["trims"] = {str(fwd[int(k)]): v for k, v in (cut_edit.get("trims") or {}).items() if int(k) in fwd}
    return episode | {"shots": new_shots}, {fwd[k]: v for k, v in sources.items() if k in fwd}, ce, back


def relabel_timeline(tl: dict, back: dict[int, int], name: str) -> None:
    """导出时间线还原剧本镜号：shots[].index / shot 用剧本镜号，cut_position = 成片里的位置；对白同理"""
    for sh in tl.get("shots") or []:
        pos = int(sh["index"])
        orig = back.get(pos, pos)
        sh["cut_position"], sh["index"], sh["shot"] = pos, orig, f"{name}-S{orig}"
    for sp in tl.get("speech") or []:
        pos = int(sp.get("shot") or 0)
        if pos in back:
            sp["cut_position"], sp["shot"] = pos, back[pos]
            if isinstance(sp.get("key"), str):
                sp["key"] = sp["key"].replace(f"-S{pos}#", f"-S{back[pos]}#")


def srt_cues(tl: dict, proj: dict) -> list[tuple[float, float, str]]:
    """外挂字幕（L-002 不烧录）：项目方改过字幕 → 按“本镜在成片里的起点 + 相对秒数”换算；没改过 → 按装配的对白时间"""
    subs = subtitles_of(proj)
    if subs is None:
        cues = sorted((s for s in tl.get("speech") or [] if s.get("start_s") is not None), key=lambda s: s["start_s"])
        return [(float(s["start_s"]), float(s["end_s"]), str(s.get("text") or "")) for s in cues]
    start = {int(sh["index"]): float(sh["start_s"]) for sh in tl.get("shots") or []}
    total = float(tl.get("duration_s") or 0) or None
    out = []
    for x in subs:
        if int(x["shot"]) not in start or not str(x.get("text") or "").strip():
            continue
        a = start[int(x["shot"])] + float(x["d0"])
        b = start[int(x["shot"])] + float(x["d1"])
        if total:
            a, b = min(a, total), min(b, total)
        if b - a >= 0.1:
            out.append((round(a, 3), round(b, 3), str(x["text"]).strip()))
    return sorted(out)


_lib_cache: dict[tuple, list[dict]] = {}


def _rm():
    """ns_post.run_media（按剧取配乐 / 音色的唯一入口）；API 进程里先把 services/post 放进 sys.path（同 bgm_api）"""
    if str(CODE / "services" / "post") not in sys.path:
        sys.path.insert(0, str(CODE / "services" / "post"))
    from ns_post import run_media   # noqa: PLC0415
    return run_media


def _v2_library_choices(run: str) -> list[dict]:
    """资产包模式（V2）：曲库 config/music_v2.json 的曲目（逐条 sha 校验，按文件 mtime 缓存）+ 本剧配乐目录里的 ep*.wav"""
    RM = _rm()   # 按剧取配乐的唯一入口（STYLE-V2，OVERSIGHT-F P1-13a）
    cfg = P.ROOT / "config" / "music_v2.json"
    key = (run, str(P.ROOT), cfg.stat().st_mtime if cfg.is_file() else 0)
    if key not in _lib_cache:
        lib = RM.music_library(run, P.ROOT)
        _lib_cache.clear()
        _lib_cache[key] = [{"file": t["file"], "url": file_url(t["file"]), "name": f"{t.get('use') or ''} · {t.get('theme') or t['id']}".strip(" ·"),
                            "duration_s": t.get("duration_s"), "bpm": t.get("bpm"), "mine": False, "library_track": t["id"]}
                           for t in lib.values()]
    out = [dict(x) for x in _lib_cache[key]]
    d = RM.music_dir(run, P.ROOT)
    for w in sorted(d.glob("ep*.wav")) if d.is_dir() else []:
        meta = _jl(w.with_suffix(".json"), {}) or {}
        out.append({"file": _rel(w), "url": file_url(_rel(w)), "name": w.stem, "duration_s": meta.get("duration_s"),
                    "bpm": meta.get("bpm"), "mine": False, "library_track": meta.get("library_track")})
    return out


def music_choices(n: int, proj: dict | None = None) -> list[dict]:
    """可换的配乐。V2（资产包模式）只列曲库（config/music_v2.json）+ 本剧配乐目录——导出时 run_media.check_episode_music
    只认这两处，列别的选了会在导出时报错；V1 = 本集配乐所在目录里的 ep*.wav。本集还没有配乐且没有曲库 → 空。"""
    cur = ((proj or {}).get("bgm") or {}).get("file")
    try:
        RM = _rm()
        run = _RP.current_run(P.ROOT)
        if RM.is_asset_pack_run(run, P.ROOT):
            out = _v2_library_choices(run)
            for x in out:
                x["mine"] = x["file"] == cur
            return out
    except ImportError:   # arch-ok: 没有 run_media（旧部署）→ 按旧规则列本集配乐目录
        pass
    d = (P.ROOT / cur).parent if cur else None
    out = []
    for w in sorted(d.glob("ep*.wav")) if d and d.is_dir() else []:
        meta = _jl(w.with_suffix(".json"), {}) or {}
        out.append({"file": _rel(w), "url": file_url(_rel(w)), "name": w.stem, "duration_s": meta.get("duration_s"),
                    "bpm": meta.get("bpm"), "mine": w.stem == f"ep{n:02d}"})
    return out


def _view(n: int, proj: dict) -> dict:
    try:
        mc, merr = music_choices(n, proj), None
    except Exception as e:  # noqa: BLE001 — arch-ok: 曲库校验失败（sha 不符 / 没登记）→ 换曲列表为空并把原因显示在页面上，不挡剪辑
        mc, merr = [], f"{type(e).__name__}: {e}"
    segs = []
    t = 0.0
    for s in proj["segments"]:
        ln = segment_length(s)
        segs.append(s | {"url": file_url(s.get("file")), "start_s": round(t, 3), "length_s": ln})
        t += ln
    subs = subtitles_of(proj)
    return proj | {"segments": segs, "duration_s": round(t, 3), "music_choices": mc, "music_error": merr,
                   "subtitles": subs if subs is not None else seed_subtitles(proj), "subtitles_edited": subs is not None,
                   "bgm_url": file_url((proj.get("bgm") or {}).get("file")),
                   "speech": [x | {"urls": [file_url(f) for f in x.get("files") or []]} for x in proj.get("speech") or []],
                   "job": job_view(n)}


@router.get("/api/episodes/{n}/cut-project")
def get_project(n: int):
    return _view(n, load_project(n))


class SegEdit(BaseModel):
    index: int
    trim_head_s: float
    trim_tail_s: float


class BgmEdit(BaseModel):
    """只发改了的字段（None = 没动）"""
    file: str | None = None
    offset_s: float | None = None
    gain_db: float | None = None
    fade_in_s: float | None = None
    fade_out_s: float | None = None


class SubEdit(BaseModel):
    shot: int
    text: str
    d0: float
    d1: float


class ProjEdit(BaseModel):
    rev: int
    segments: list[SegEdit] | None = None
    bgm: BgmEdit | None = None
    order: list[int] | None = None          # 镜头新顺序（镜号排列）
    subtitles: list[SubEdit] | None = None  # 改过的字幕（整表）
    by: str | None = None
    client: str | None = None               # 哪个窗口发的（同一窗口自己的连改 / 重发不算“覆盖”）


FIELD_LABEL = {"order": "镜头顺序", "subtitles": "字幕", "bgm.file": "配乐曲目", "bgm.offset_s": "配乐起点",
               "bgm.gain_db": "配乐音量", "bgm.fade_in_s": "配乐淡入", "bgm.fade_out_s": "配乐淡出"}


def _label(field: str) -> str:
    return FIELD_LABEL.get(field) or (f"S{field.split(':')[1]} 裁切" if field.startswith("trim:") else field)


def field_value(proj: dict, field: str):
    """字段当前的完整值（三方合并比较 / 被覆盖时存 prev_value 用）"""
    if field.startswith("trim:"):
        seg = next((x for x in proj["segments"] if int(x["index"]) == int(field.split(":")[1])), None)
        return [round(float(seg["trim_head_s"]), 3), round(float(seg["trim_tail_s"]), 3)] if seg else None
    if field == "order":
        return [int(x["index"]) for x in proj["segments"]]
    if field == "subtitles":
        return copy.deepcopy(proj.get("subtitles"))
    if field.startswith("bgm."):
        return (proj.get("bgm") or {}).get(field[4:])
    raise KeyError(field)


def apply_field(proj: dict, field: str, value) -> None:
    if field.startswith("trim:"):
        seg = next(x for x in proj["segments"] if int(x["index"]) == int(field.split(":")[1]))
        seg.update(trim_head_s=float(value[0]), trim_tail_s=float(value[1]), trim_by="owner", trim_adjusted=False)
    elif field == "order":
        by_idx = {int(x["index"]): x for x in proj["segments"]}
        proj["segments"] = [by_idx[int(i)] for i in value]
    elif field == "subtitles":
        proj["subtitles"] = copy.deepcopy(value)
    elif field.startswith("bgm."):
        proj["bgm"] = dict(proj.get("bgm") or {}) | {field[4:]: value}
    else:
        raise KeyError(field)


def describe(field: str, value) -> str:
    if field.startswith("trim:"):
        return f"S{field.split(':')[1]} 入 {value[0]:.2f} / 尾裁 {value[1]:.2f}"
    if field == "order":
        return "镜头顺序 " + " ".join(f"S{i}" for i in value)
    if field == "subtitles":
        subs = value or []
        head = "／".join((str(x.get("text") or "（空）"))[:12] for x in subs[:3])
        return f"字幕 {len(subs)} 条" + (f"：{head}{'…' if len(subs) > 3 else ''}" if subs else "")
    if field == "bgm.file":
        return f"配乐曲目 {Path(str(value)).stem if value else '（无）'}"
    return f"{_label(field)} {value}"


def mark_field(proj: dict, field: str, by: str, what: str, client: str | None = None) -> None:
    """记下这个字段最后一次是哪一版、谁（哪个窗口）、改成了什么（三方合并靠它判断“基线之后别人改过没有”）"""
    proj.setdefault("field_rev", {})[field] = {"rev": int(proj["rev"]) + 1, "by": by, "client": client, "at": P.now(), "what": what}


def commit_changes(proj: dict, changes: list, *, base: int, by: str, client: str | None,
                   always_record: bool = False, extra: dict | None = None) -> dict | None:
    """逐字段应用（值相同的跳过）。基线之后别的窗口改过同一字段 → 以后到的为准，overrode 里存被覆盖的完整旧值（prev_value），
    以后可以用 restore 找回。同一个窗口（client 相同）自己的改动不算覆盖（重发 / 连改时不记假的“覆盖”）。
    always_record = 恢复操作：无论基线，被它盖掉的当前值也存下来（恢复本身也能再恢复回去）。返回新写的 history 条目。"""
    fr = proj.setdefault("field_rev", {})
    what, overrode = [], []
    for field, new in changes:
        old = field_value(proj, field)
        if old == new:
            continue
        prev = fr.get(field)
        other = bool(prev) and not (client and prev.get("client") == client)
        if (other and int(prev.get("rev") or 0) > base) or always_record:
            pv = prev or {}
            pwhat = pv.get("what") or describe(field, old)
            overrode.append({"field": field, "label": _label(field), "prev_rev": pv.get("rev"), "prev_by": pv.get("by"),
                             "prev_at": pv.get("at"), "prev_what": pwhat, "prev_value": old,
                             "text": f"{_label(field)}：覆盖了第 {pv.get('rev') or '?'} 版（{pv.get('by') or '?'} "
                                     f"{str(pv.get('at') or '')[11:16]}）的“{pwhat}”"})
        apply_field(proj, field, new)
        desc = describe(field, new)
        mark_field(proj, field, by, desc, client)
        what.append(desc)
    if not what:
        return None
    proj["rev"] = int(proj["rev"]) + 1
    proj["updated_at"] = P.now()
    note = f"（基于第 {base} 版改的，合并到第 {proj['rev']} 版）" if base != proj["rev"] - 1 else ""
    entry = {"id": uuid.uuid4().hex[:10], "at": P.now(), "what": "；".join(what) + note, "by": by, "base_rev": base,
             **(extra or {})}
    if overrode:
        entry["overrode"] = overrode
    proj["history"] = (proj.get("history") or [])[-49:] + [entry]
    return entry


@router.put("/api/episodes/{n}/cut-project", status_code=202)
def put_project(n: int, body: ProjEdit):
    """原位保存（202 收下，L-123 / 项目方的改动永不丢）——三方合并：
    网页只发“和它的基线版本（rev）相比改了的字段”；服务端逐字段应用，没发的字段一律不动（别的窗口刚改的不会被旧值盖回去）。
    同一字段在基线之后别处也改过 → 以后到的为准，history.overrode 存被覆盖的完整旧值，POST …/restore 可以找回。"""
    proj = load_project(n, refresh=False)
    with _lock:
        changes: list = []
        by_idx = {int(x["index"]): x for x in proj["segments"]}
        for e in body.segments or []:
            seg = by_idx.get(int(e.index))
            if not seg or seg.get("kind") != "video":
                continue
            h, t, _ = clamp(e.trim_head_s, e.trim_tail_s, seg.get("source_duration_s"))
            changes.append((f"trim:{seg['index']}", [h, t]))
        if body.order is not None:
            new = [int(x) for x in body.order]
            if sorted(new) != sorted(by_idx):
                raise HTTPException(422, "镜头顺序必须是本集全部镜头各出现一次")
            changes.append(("order", new))
        if body.subtitles is not None:
            subs = []
            for x in body.subtitles:
                if int(x.shot) not in by_idx:
                    raise HTTPException(422, f"字幕挂在不存在的镜头 S{x.shot} 上")
                ln = segment_length(by_idx[int(x.shot)])
                d0 = round(min(max(0.0, x.d0), max(0.0, ln - 0.2)), 3)
                d1 = round(min(max(d0 + 0.2, x.d1), ln + 3.0), 3)   # 允许跨到下一镜（独白常见），最多 3 s
                subs.append({"shot": int(x.shot), "text": x.text.strip(), "d0": d0, "d1": d1})
            changes.append(("subtitles", subs))
        if body.bgm is not None:
            b = {k: v for k, v in body.bgm.model_dump().items() if v is not None}
            if b.get("file"):
                f = _rel(b["file"])
                if not f or not f.startswith("data/") or ".." in f or not (P.ROOT / f).is_file():
                    raise HTTPException(422, f"配乐文件不在 data/ 下或不存在：{b['file']}")
                b["file"] = f
                allowed = {x["file"] for x in music_choices(n, proj)}
                if allowed and f not in allowed:
                    raise HTTPException(422, f"这条配乐不在本剧可用的曲目里：{f}")
            lim = {"offset_s": (0.0, 1e9, 3), "gain_db": (-30.0, 6.0, 2), "fade_in_s": (0.0, 10.0, 2), "fade_out_s": (0.0, 10.0, 2)}
            for k, v in b.items():
                if k in lim:
                    lo, hi, nd = lim[k]
                    v = round(min(hi, max(lo, float(v))), nd)
                changes.append((f"bgm.{k}", v))
        if commit_changes(proj, changes, base=int(body.rev), by=body.by or "owner", client=body.client):
            _wj(proj_path(n), proj)
    return _view(n, proj)


class RestoreBody(BaseModel):
    history_id: str
    field: str | None = None      # 只恢复这条里的某一个字段；不给 = 这条里被覆盖的全部
    by: str | None = None
    client: str | None = None


@router.post("/api/episodes/{n}/cut-project/restore", status_code=202)
def restore_overridden(n: int, body: RestoreBody):
    """把某条 history 里被覆盖的改动找回来（202 收下）：用 overrode.prev_value 原样写回，记成一次新改动（restored_from），
    被它盖掉的当前值也存进新条目的 overrode，可以再恢复回去。"""
    proj = load_project(n, refresh=False)
    with _lock:
        entry = next((h for h in proj.get("history") or [] if h.get("id") == body.history_id), None)
        if entry is None:
            raise HTTPException(404, "找不到这条记录（可能已超出最近 50 条）")
        ovs = [o for o in entry.get("overrode") or [] if isinstance(o, dict) and "prev_value" in o
               and (body.field is None or o.get("field") == body.field)]
        if not ovs:
            raise HTTPException(422, "这条记录里没有可恢复的被覆盖内容")
        segs = {int(x["index"]) for x in proj["segments"]}
        changes = []
        for o in ovs:
            v = o["prev_value"]
            if o["field"] == "order" and sorted(int(i) for i in v or []) != sorted(segs):
                continue
            if o["field"].startswith("trim:") and int(o["field"].split(":")[1]) not in segs:
                continue
            changes.append((o["field"], v))
        new = commit_changes(proj, changes, base=int(proj["rev"]), by=body.by or "owner", client=body.client,
                             always_record=True, extra={"restored_from": body.history_id})
        if new:
            new["what"] = "恢复被覆盖的改动：" + new["what"]
            entry.setdefault("restored", []).append({"at": P.now(), "by": body.by or "owner", "history_id": new["id"],
                                                     "fields": [f for f, _ in changes]})
            _wj(proj_path(n), proj)
    return _view(n, proj)


# ---------------- 导出（先收下、再异步）

def job_view(n: int) -> dict | None:
    j = _jl(job_path(n))
    if not j:
        return None
    p = PROCS.get(n)
    if j.get("state") not in ("done", "failed") and p is not None and p.poll() is not None and p.returncode != 0:
        j.update(state="failed", error=j.get("error") or f"导出进程退出码 {p.returncode}", finished_at=P.now())
        _wj(job_path(n), j)
    if j.get("state") not in ("done", "failed") and j.get("started_ts"):
        el = time.time() - float(j["started_ts"])
        j["elapsed_s"] = round(el)
        j["eta_s"] = max(5, round(float(j.get("est_s") or DEFAULT_EST_S) - el))
    if j.get("output"):
        j["url"] = file_url(j["output"])
    return j


def _est_s(n: int) -> float:
    fin = (_jl(proj_path(n), {}) or {}).get("final") or {}
    return float(fin.get("build_s") or DEFAULT_EST_S)


@router.post("/api/episodes/{n}/cut-project/export", status_code=202)
def start_export(n: int, body: dict | None = None):
    proj = load_project(n)
    with _lock:
        cur = job_view(n)
        if cur and cur.get("state") not in ("done", "failed", None):
            return cur   # 已在导出：原位显示同一个任务（不重复起）
        logs = P.DATA / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%m%d-%H%M%S")
        log = logs / f"cut_export_ep{n:02d}_{stamp}.log"
        job = {"episode": n, "rev": proj["rev"], "state": "queued", "stage": "收下", "pct": 2, "started_at": P.now(),
               "started_ts": time.time(), "est_s": _est_s(n), "by": (body or {}).get("by") or "owner",
               "log": _rel(log), "output": None, "error": None}
        _wj(job_path(n), job)
        cmd = [sys.executable, str(CODE / "tools" / "cut_export.py"), f"ep{n:02d}", "--rev", str(proj["rev"])]
        fh = open(log, "w", encoding="utf-8")  # noqa: SIM115 — 子进程写完由系统关
        PROCS[n] = subprocess.Popen(cmd, cwd=str(P.ROOT), stdout=fh, stderr=subprocess.STDOUT)
        return job_view(n)


@router.get("/api/episodes/{n}/cut-project/export")
def export_status(n: int):
    return job_view(n) or {"episode": n, "state": "none"}


# ---------------- 时间线小图

@router.get("/api/cut-frame")
def cut_frame(src: str, t: float = 0.5, w: int = 120):
    if not src.startswith("/files/") or ".." in src:
        raise HTTPException(422, "src 必须是 /files/ 下的路径")
    base = os.path.normpath(os.path.abspath(P.DATA))
    p = Path(os.path.normpath(os.path.join(base, src[len("/files/"):].split("?")[0])))
    if not str(p).startswith(base + os.sep) or not p.is_file():
        raise HTTPException(404, "文件不存在")
    w = max(60, min(480, int(w)))
    key = hashlib.sha1(f"{p}|{p.stat().st_mtime}|{t:.2f}|{w}".encode()).hexdigest()[:20]
    out = P.DATA / "_cache" / "cutedit" / f"{key}.jpg"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vf", f"scale={w}:-2", "-q:v", "5", str(out)]
        else:
            cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(p), "-frames:v", "1",
                   "-vf", f"scale={w}:-2", "-q:v", "5", str(out)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError) as e:
            raise HTTPException(500, f"抽帧失败：{e}") from e
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})
