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

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
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
    return P.DATA / "renders" / f"ep{n:02d}" / "_final"


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
    return seg


def init_project(n: int) -> dict:
    tlp = base_timeline(n)
    if tlp is None:
        raise HTTPException(404, f"第 {n} 集还没有装配好的时间线（先装配一次：tools/assemble_series.py ep{n:02d}）")
    tl = _jl(tlp, {}) or {}
    bgm = tl.get("bgm") or {}
    speech = [{"kind": s.get("kind"), "shot": s.get("shot"), "speaker": s.get("speaker_name") or s.get("speaker"),
               "text": s.get("text"), "start_s": s.get("start_s"), "end_s": s.get("end_s"),
               "files": [_rel(f) for f in s.get("files") or []], "source": s.get("source")}
              for s in tl.get("speech") or [] if s.get("start_s") is not None]
    return {"schema": SCHEMA, "episode": n, "rev": 1, "updated_at": P.now(), "base_timeline": _rel(tlp),
            "base_duration_s": tl.get("duration_s"),
            "segments": [_seg_from_shot(s) for s in sorted(tl.get("shots") or [], key=lambda x: int(x["index"]))],
            "bgm": {"file": _rel(bgm.get("file")) or f"data/music/series10/ep{n:02d}.wav", "offset_s": 0.0,
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
        else:   # 没动过的镜头导出时由装配器自动裁；这里先按整段显示
            seg.update(trim_head_s=0.0, trim_tail_s=0.0, trim_adjusted=False)
        notes.append(f"S{seg['index']} 换成新片{'（裁切沿用' + ('，已收到片尾' if seg.get('trim_adjusted') else '') + '）' if seg.get('trim_by') == 'owner' else ''}")
    return notes


def load_project(n: int, *, refresh: bool = True) -> dict:
    with _lock:
        proj = _jl(proj_path(n))
        created = False
        if not proj or proj.get("schema") != SCHEMA:
            proj, created = init_project(n), True
        notes = refresh_sources(proj) if refresh else []
        if notes:
            proj["rev"] = int(proj["rev"]) + 1
            proj["updated_at"] = P.now()
            proj["history"] = (proj.get("history") or [])[-49:] + [{"at": P.now(), "what": "；".join(notes), "by": "system"}]
        if created or notes:
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
    return {"trims": trims, "bgm": bgm}


def music_choices(n: int) -> list[dict]:
    d = P.DATA / "music" / "series10"
    out = []
    for w in sorted(d.glob("ep*.wav")) if d.is_dir() else []:
        meta = _jl(w.with_suffix(".json"), {}) or {}
        out.append({"file": _rel(w), "url": file_url(_rel(w)), "name": w.stem, "duration_s": meta.get("duration_s"),
                    "bpm": meta.get("bpm"), "mine": w.stem == f"ep{n:02d}"})
    return out


def _view(n: int, proj: dict) -> dict:
    segs = []
    t = 0.0
    for s in proj["segments"]:
        ln = segment_length(s)
        segs.append(s | {"url": file_url(s.get("file")), "start_s": round(t, 3), "length_s": ln})
        t += ln
    return proj | {"segments": segs, "duration_s": round(t, 3), "music_choices": music_choices(n),
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
    file: str | None = None
    offset_s: float = 0.0
    gain_db: float = 0.0
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0


class ProjEdit(BaseModel):
    rev: int
    segments: list[SegEdit] | None = None
    bgm: BgmEdit | None = None
    by: str | None = None


@router.put("/api/episodes/{n}/cut-project")
def put_project(n: int, body: ProjEdit):
    proj = load_project(n, refresh=False)
    with _lock:
        if int(body.rev) != int(proj["rev"]):
            raise HTTPException(409, f"工程已更新到第 {proj['rev']} 版（镜头换了新片或别处改过），刷新后再改")
        what = []
        by_idx = {int(s["index"]): s for s in proj["segments"]}
        for e in body.segments or []:
            seg = by_idx.get(int(e.index))
            if not seg or seg.get("kind") != "video":
                continue
            h, t, _ = clamp(e.trim_head_s, e.trim_tail_s, seg.get("source_duration_s"))
            if (h, t) != (round(seg["trim_head_s"], 3), round(seg["trim_tail_s"], 3)):
                seg.update(trim_head_s=h, trim_tail_s=t, trim_by="owner", trim_adjusted=False)
                what.append(f"S{seg['index']} 入 {h:.2f} / 尾裁 {t:.2f}")
        if body.bgm is not None:
            b = body.bgm.model_dump()
            if b.get("file"):
                f = _rel(b["file"])
                if not f or not f.startswith("data/") or ".." in f or not (P.ROOT / f).is_file():
                    raise HTTPException(422, f"配乐文件不在 data/ 下或不存在：{b['file']}")
                b["file"] = f
            else:
                b["file"] = (proj.get("bgm") or {}).get("file")
            b["offset_s"] = round(max(0.0, b["offset_s"]), 3)
            b["gain_db"] = round(min(6.0, max(-30.0, b["gain_db"])), 2)
            b["fade_in_s"] = round(min(10.0, max(0.0, b["fade_in_s"])), 2)
            b["fade_out_s"] = round(min(10.0, max(0.0, b["fade_out_s"])), 2)
            if b != proj.get("bgm"):
                proj["bgm"] = b
                what.append(f"配乐 {Path(b['file']).stem} · 起点 {b['offset_s']:g}s · {b['gain_db']:+g} dB · 淡入 {b['fade_in_s']:g}s · 淡出 {b['fade_out_s']:g}s")
        if what:
            proj["rev"] = int(proj["rev"]) + 1
            proj["updated_at"] = P.now()
            proj["history"] = (proj.get("history") or [])[-49:] + [{"at": P.now(), "what": "；".join(what), "by": body.by or "owner"}]
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
