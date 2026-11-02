"""
UX5 成片页（docs/ux_round5/D_workflow_visual.md D1 / §5「成片」）：看成片、版本列表、成片是否落后于定稿、合成新版本。

    GET  /api/episodes/{n}/cuts        本集全部成片文件（data/episodes/epNN*.mp4）+ 时间线摘要 + 和当前定稿相比哪几镜变了
    GET  /api/episodes/{n}/cut-job     合成任务状态（本进程内）
    POST /api/episodes/{n}/cut-job     合成一个新版本：起子进程 tools/assemble_episode.py epNN --variant UI<时间>
                                       {dialogue_source?: "tts"|"h3"|"auto"}；一律存成新的对照版文件，不覆盖已有成片、不建别名

合成只用 CPU（装配器自己的规则：Kokoro / SenseVoice / x264，不碰 GPU、不改 data/renders），不改现有装配行为——
只是把命令行入口挂到界面上；同一集同时只跑一个。不做内容检测。
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_render import pipeline as P

router = APIRouter(tags=["cuts"])
_lock = threading.Lock()
JOBS: dict[int, dict] = {}
TAGS = (("PREVIEW", "预览"), ("未完成", "未完成"), ("勿用", "勿用"), ("H3原声", "H3 原声"), ("4k", "4K"))


def _epdir() -> Path:
    return P.DATA / "episodes"


def _tl(mp4: Path) -> dict | None:
    for cand in (mp4.with_suffix(".timeline.json"), mp4.with_name(mp4.stem.removesuffix("_4k") + ".timeline.json")):
        try:
            return json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def _strip_cc(f: str | None) -> str | None:
    return re.sub(r"_cc(?=\.mp4$)", "", f) if f else f


def _current_video(shot_id: str) -> tuple[str | None, bool]:
    """本镜现在的视频：(文件, 是否定稿)；定稿优先，没有就当前"""
    d = P.shot_dir(shot_id)
    try:
        data = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, False
    lk, act = (data.get("locked") or {}).get("video"), (data.get("active") or {}).get("video")
    n = lk if lk is not None else act
    t = next((x for x in data.get("takes") or [] if x.get("stage") == "video" and x.get("n") == n), None)
    if not t or not t.get("file"):
        return None, False
    f = str(t["file"]).replace("\\", "/")
    if not f.startswith("data/"):
        f = f"data/{f}"
    return f, lk is not None


def _summary(mp4: Path, n: int) -> dict:
    st = mp4.stat()
    tl = _tl(mp4)
    try:
        rel = mp4.resolve().relative_to(P.DATA.resolve()).as_posix()
    except ValueError:
        rel = f"episodes/{mp4.name}"
    plan = re.search(r"(?:^|/)plan([A-Z])(?:/|_|$)", rel)
    out = {"name": (f"方案 {plan.group(1)} · " if plan else "") + mp4.name, "url": f"/files/{rel}?v={int(st.st_mtime)}", "size": st.st_size,
           "plan": plan.group(1) if plan else None,
           "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
           "tags": ([f"方案 {plan.group(1)}"] if plan else []) + [lab for k, lab in TAGS if k.lower() in mp4.name.lower()],
           "timeline": None, "changed": []}
    if tl:
        shots = tl.get("shots") or []
        out["timeline"] = {"duration_s": tl.get("duration_s"), "shots": len(shots), "preview": tl.get("preview"),
                           "dialogue_source": (tl.get("settings") or {}).get("dialogue_source"),
                           "missing": [s.get("shot") for s in shots if s.get("missing") or s.get("placeholder")],
                           "warnings": len(tl.get("warnings") or []), "warning_list": (tl.get("warnings") or [])[:20],
                           "note": tl.get("output_note")}
        for s in shots:
            sid = s.get("shot")
            if not sid or s.get("kind") != "video":
                continue
            cur, locked = _current_video(sid)
            used = _strip_cc((s.get("file") or "").replace("\\", "/"))
            if cur and used and cur != used:
                out["changed"].append({"shot_id": sid, "used": used, "current": cur, "current_locked": locked})
    return out


@router.get("/api/episodes/{n}/cuts")
def list_cuts(n: int):
    d = _epdir()
    files = sorted(d.glob(f"ep{n:02d}*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    files = [f for f in files if re.match(rf"ep{n:02d}(?!\d)", f.name)]
    files += plan_cuts(n)
    files += final_cuts(n)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    # UIRSI：比最近一次“整份替换”导入（import_log mode=replace…）更早合成的成片标 old_script——界面默认不显示
    # 旧剧本的成片（文件不动）。按集合并导入（merge）不算换剧本。
    smt = _last_replace_import()
    cuts = [_summary(f, n) | {"old_script": bool(smt and f.stat().st_mtime < smt)} for f in files]
    fin = _final_file(n)
    for c, f in zip(cuts, files):   # CUTEDIT：剪辑器导出的版本标“剪辑”，当前定稿标“定稿”
        if "_cut_" in f.name:
            c["tags"].append("剪辑")
        if fin and f.resolve() == fin:
            c["tags"].insert(0, "定稿")
            c["final"] = True
    return {"episode": n, "cuts": cuts, "job": _job_view(n),
            "script_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(smt)) if smt else None}


def _last_replace_import() -> float | None:
    log = P.DATA / "import" / "import_log.jsonl"
    last = None
    try:
        for ln in log.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(ln)
            except ValueError:
                continue
            if str(x.get("mode") or "").startswith("replace") and x.get("at"):
                last = x["at"]
    except OSError:
        return None
    if not last:
        return None
    try:
        return time.mktime(time.strptime(last[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


@router.get("/api/script/replaced-at")
def script_replaced_at():
    """UIRSI：最近一次整份替换导入（换剧本）的时间。界面据此隐藏换剧本之前的旧记录（旧成片、旧整集出片），文件不动。"""
    t = _last_replace_import()
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) if t else None}


def final_cuts(n: int) -> list[Path]:
    """CUTEDIT / ASSEMBLY：data/renders/epNN/_final/epNN_*.mp4（装配成片版 + 剪辑器导出的定稿；预览 preview_latest 不算）"""
    d = _RP.renders_for_data(P.DATA) / f"ep{n:02d}" / "_final"
    return [f for f in d.glob(f"ep{n:02d}_*.mp4") if f.is_file()] if d.is_dir() else []


def _final_file(n: int) -> Path | None:
    try:
        f = (json.loads((_RP.renders_for_data(P.DATA) / f"ep{n:02d}" / "_final" / "cut_project.json").read_text(encoding="utf-8"))
             .get("final") or {}).get("file")
    except FileNotFoundError:   # arch-ok: 还没建剪辑工程 = 没有定稿（正常状态，不是读失败）
        return None
    except (OSError, ValueError) as e:   # arch-ok: 工程文件坏了只影响“定稿”标签显示，打日志报出来，列表照常
        print(f"[cuts] cut_project.json 读不了（第 {n} 集，定稿标签先不显示）：{e!r}", file=sys.stderr)
        return None
    return (P.ROOT / f).resolve() if f else None


def plan_cuts(n: int) -> list[Path]:
    """UIRSI：方案 A/B/C 出的整集成片（只读列出，出来后自动出现）：data/ab/plan<X>/epNN/*.mp4（只取这一层，不含逐镜子目录）、
    data/ab/plan<X>/epNN*.mp4、data/episodes/plan<X>/epNN*.mp4。逐镜试验片（planX/epNN/S2/…）不算成片。"""
    out: list[Path] = []
    for base in (P.DATA / "ab", P.DATA / "episodes"):
        for d in sorted(base.glob("plan[A-Z]")) if base.is_dir() else []:
            out += [f for f in (d / f"ep{n:02d}").glob("*.mp4")] if (d / f"ep{n:02d}").is_dir() else []
            out += [f for f in d.glob(f"ep{n:02d}*.mp4") if re.match(rf"ep{n:02d}(?!\d)", f.name)]
    return [f for f in out if f.is_file()]


class CutBody(BaseModel):
    dialogue_source: str | None = None
    by: str | None = None


def _job_view(n: int) -> dict | None:
    j = JOBS.get(n)
    if not j:
        return None
    p = j.get("proc")
    if p is not None and j["state"] == "running" and p.poll() is not None:
        j["state"] = "done" if p.returncode == 0 else "failed"
        j["finished_at"] = P.now()
        j["returncode"] = p.returncode
    tail = ""
    try:
        tail = Path(j["log"]).read_text(encoding="utf-8", errors="replace")[-2000:]
    except OSError:
        pass
    return {k: v for k, v in j.items() if k != "proc"} | {"log_tail": tail}


def _command(n: int, variant: str, body: CutBody) -> list[str]:
    cmd = [sys.executable, str(P.ROOT / "tools" / "assemble_episode.py"), f"ep{n:02d}", "--variant", variant]
    if body.dialogue_source:
        cmd += ["--dialogue-source", body.dialogue_source]
    return cmd


@router.post("/api/episodes/{n}/cut-job")
def start_cut(n: int, body: CutBody | None = None):
    b = body or CutBody()
    if b.dialogue_source not in (None, "tts", "h3", "auto"):
        raise HTTPException(422, "dialogue_source 只能是 tts | h3 | auto")
    with _lock:
        cur = _job_view(n)
        if cur and cur["state"] == "running":
            raise HTTPException(409, f"第 {n} 集正在合成（{cur['variant']}），等它跑完")
        variant = "UI" + time.strftime("%m%d-%H%M%S")
        logs = P.DATA / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f"cut_ep{n:02d}_{variant}.log"
        cmd = _command(n, variant, b)
        fh = open(log, "w", encoding="utf-8")  # noqa: SIM115 — 子进程写完由系统关
        proc = subprocess.Popen(cmd, cwd=str(P.ROOT), stdout=fh, stderr=subprocess.STDOUT)
        JOBS[n] = {"episode": n, "variant": variant, "state": "running", "started_at": P.now(), "finished_at": None,
                   "by": b.by or "canvas", "cmd": cmd[1:], "log": str(log), "proc": proc}
        return _job_view(n)


@router.get("/api/episodes/{n}/cut-job")
def cut_job(n: int):
    return _job_view(n) or {"episode": n, "state": "none"}
