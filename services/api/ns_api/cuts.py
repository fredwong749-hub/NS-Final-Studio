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

from ns_api import clock as _clock   # L-212 #10：页面时间一律 JST
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_render import pipeline as P

router = APIRouter(tags=["cuts"])
_lock = threading.Lock()
JOBS: dict[int, dict] = {}
TAGS = (("PREVIEW", "预览"), ("未完成", "未完成"), ("勿用", "勿用"), ("H3原声", "H3 原声"), ("4k", "4K"))


def _epdir() -> Path:
    """UIUX-LOOP-3 r12：按剧取（V2 = data/episodes/<run>/）；以前写死 data/episodes/ → 第 1 集 60 多版成片一版都列不出来"""
    return _RP.episodes_for_data(P.DATA)


def _jst_iso(epoch: float) -> str:
    """文件 mtime → JST 串（页面钟点一律 JST，ns_api/clock.py）"""
    from ns_api.clock import JST
    from datetime import datetime
    return datetime.fromtimestamp(float(epoch), JST).strftime("%Y-%m-%dT%H:%M:%S")


def film_gate(tl: dict | None) -> dict | None:
    """合成闸门（装配器写进 timeline.json 的 gates：verdict pass / fail + missing_shots）→ 页面用的诚实标签。
    preview=True 是装配器自己标的“预览版，非交付”；闸门没过的片也只能叫预览版（缺镜用静帧 / 黑场占位）"""
    if not isinstance(tl, dict):
        return None
    g = tl.get("gates") or {}
    miss = [{"shot": str(m.get("shot") or ""), "reason": str(m.get("reason") or "")} for m in (g.get("missing_shots") or []) if isinstance(m, dict)]
    verdict = g.get("verdict")
    preview = bool(tl.get("preview"))
    post = tl.get("post") if isinstance(tl.get("post"), dict) else None
    if verdict == "fail":
        word = f"合成闸门没过：缺 {len(miss)} 镜用占位" if miss else "合成闸门没过"
    elif verdict == "pass":
        word = "合成闸门通过"
    else:
        word = "没有闸门记录"
    kind = "final" if verdict == "pass" and not preview else "preview"
    return {"verdict": verdict, "missing": miss, "missing_n": len(miss), "preview": preview, "kind": kind,
            "kind_word": "成片" if kind == "final" else "预览版", "word": word,
            "post": {"at": post.get("at"), "steps": list(post.get("steps") or [])} if post else None,
            "overflow": list(g.get("overflow") or [])}


def film_version(name: str) -> int:
    m = re.search(r"_v(\d+)", name)
    return int(m.group(1)) if m else -1


def _incomplete(f: Path) -> bool:
    """还在写的文件不算：*.part、0 字节、旁边有同名 .part（同步 / 合成没写完）"""
    try:
        if f.name.endswith(".part") or f.stat().st_size == 0:
            return True
    except OSError:
        return True
    return f.with_name(f.name + ".part").exists()


def film_tier(f: Path) -> int:
    """0 = 合成闸门通过的成片；1 = 没有闸门记录（timeline 还没同步到 / 没写）；2 = 预览版 / 闸门没过"""
    g = film_gate(_tl(f))
    if g is None:
        return 1
    if g["kind"] == "final":
        return 0
    return 2 if (g["preview"] or g["verdict"] == "fail") else 1


def film_rank_key(f: Path) -> tuple:
    """成片排序（UIUX-LOOP-3 r14，PS-MASTER 定）：① 闸门通过 > 没有闸门记录 > 预览 / 闸门没过；② 同一档版本号大的在前
    （不按 mtime——同步会重新 touch，v64_post 看起来比 v65 还“新”）；③ 没有版本号才看 mtime。元组越小越靠前"""
    try:
        mt = f.stat().st_mtime
    except OSError:
        mt = 0.0
    return (film_tier(f), -film_version(f.name), -mt)


def episode_films(epdir: Path, n: int) -> list[Path]:
    """本集整集成片文件（目录顶层 epNN*.mp4，不含 _work / _partial 半成品、*.part / 0 字节 / 正在写的），按 film_rank_key 排，最好的在前"""
    if not epdir.is_dir():
        return []
    files = [f for f in epdir.glob(f"ep{n:02d}*.mp4") if f.is_file() and re.match(rf"ep{n:02d}(?!\d)", f.name) and not _incomplete(f)]
    return sorted(files, key=film_rank_key)


def latest_film(epdir: Path, n: int, data_dir: Path | None = None) -> dict | None:
    """最新一版整集成片（按 film_rank_key：闸门通过 > 没闸门记录 > 预览，同档版本号大的在前；r14）：{name, url, at(JST), mtime(epoch), duration_s, shots, gate}；没有 = None。
    KPI 面板 / 整集预览 / 成片页共用这一处口径"""
    files = episode_films(epdir, n)
    if not files:
        return None
    f = files[0]
    st = f.stat()
    base = (data_dir or P.DATA).resolve()
    try:
        rel = f.resolve().relative_to(base).as_posix()
    except ValueError:
        rel = f"episodes/{f.name}"
    tl = _tl(f)
    shots = (tl or {}).get("shots") or []
    m = re.search(r"_v(\d+)", f.name)
    srt = f.with_suffix(".srt")
    return {"name": f.name, "version": int(m.group(1)) if m else None, "url": f"/files/{rel}?v={int(st.st_mtime)}",
            "srt_url": f"/files/{rel[:-4]}.srt?v={int(st.st_mtime)}" if srt.is_file() else None,
            "at": _jst_iso(st.st_mtime), "mtime": st.st_mtime, "size": st.st_size,
            "duration_s": (tl or {}).get("duration_s"), "shots": len(shots),
            "video_shots": sum(1 for s in shots if s.get("kind") == "video" and not s.get("placeholder")),
            "placeholder_shots": sum(1 for s in shots if s.get("placeholder") or s.get("kind") in ("still", "black")),
            "gate": film_gate(tl)}


_TL_CACHE: dict[str, tuple[tuple, dict]] = {}   # timeline.json 路径 → ((mtime_ns, size), 解析结果)（r12：66 版 × 60 KB 每次重解析 = 13 s）


def _tl(mp4: Path) -> dict | None:
    for cand in (mp4.with_suffix(".timeline.json"), mp4.with_name(mp4.stem.removesuffix("_4k") + ".timeline.json")):
        try:
            st = cand.stat()
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size)
        hit = _TL_CACHE.get(str(cand))
        if hit and hit[0] == key:
            return hit[1]
        try:
            d = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        _TL_CACHE[str(cand)] = (key, d)
        return d
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


def _summary(mp4: Path, n: int, memo: dict | None = None) -> dict:
    """memo（r12）：同一次请求里每镜的当前视频只问一次 takes.json（66 版 × 16 镜以前问 1000 多次）"""
    memo = {} if memo is None else memo
    st = mp4.stat()
    tl = _tl(mp4)
    try:
        rel = mp4.resolve().relative_to(P.DATA.resolve()).as_posix()
    except ValueError:
        rel = f"episodes/{mp4.name}"
    plan = re.search(r"(?:^|/)plan([A-Z])(?:/|_|$)", rel)
    gate = film_gate(tl)
    out = {"name": (f"方案 {plan.group(1)} · " if plan else "") + mp4.name, "url": f"/files/{rel}?v={int(st.st_mtime)}", "size": st.st_size,
           "plan": plan.group(1) if plan else None,
           "mtime": _jst_iso(st.st_mtime),   # r12：页面钟点一律 JST（以前是笔记本本地 = 美东）
           "tags": ([f"方案 {plan.group(1)}"] if plan else []) + [lab for k, lab in TAGS if k.lower() in mp4.name.lower()],
           "gate": gate, "timeline": None, "changed": []}
    if gate and gate["kind"] == "preview" and "预览" not in out["tags"]:   # 装配器标 preview / 闸门没过 → 诚实标“预览”，不冒充成片
        out["tags"].append("预览")
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
            if sid not in memo:
                memo[sid] = _current_video(sid)
            cur, locked = memo[sid]
            used = _strip_cc((s.get("file") or "").replace("\\", "/"))
            if cur and used and cur != used:
                out["changed"].append({"shot_id": sid, "used": used, "current": cur, "current_locked": locked})
    return out


@router.get("/api/episodes/{n}/cuts")
def list_cuts(n: int):
    files = episode_films(_epdir(), n)
    files += [f for f in plan_cuts(n) + final_cuts(n) if not _incomplete(f)]
    files.sort(key=film_rank_key)   # r14：第 1 个（页面标“最新”）= 闸门通过且版本最高的，不是 mtime 最新的
    # UIRSI：比最近一次“整份替换”导入（import_log mode=replace…）更早合成的成片标 old_script——界面默认不显示
    # 旧剧本的成片（文件不动）。按集合并导入（merge）不算换剧本。
    smt = _last_replace_import()
    memo: dict = {}
    cuts = [_summary(f, n, memo) | {"old_script": bool(smt and f.stat().st_mtime < smt)} for f in files]
    fin = _final_file(n)
    for c, f in zip(cuts, files):   # CUTEDIT：剪辑器导出的版本标“剪辑”，当前定稿标“定稿”
        if "_cut_" in f.name:
            c["tags"].append("剪辑")
        if fin and f.resolve() == fin:
            c["tags"].insert(0, "定稿")
            c["final"] = True
    return {"episode": n, "cuts": cuts, "job": _job_view(n),
            "script_at": _clock.epoch_jst(smt) if smt else None}


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


CODE = Path(__file__).resolve().parents[3]   # 代码根（P.ROOT 可被 NS_PROJECT_ROOT 指到别处）


def _asset_pack_run() -> str | None:
    """当前剧是资产包模式（V2）→ 剧名；V1 / 判不了 → None。按剧取配乐 / 音色的唯一入口 ns_post.run_media（同 cut_project）"""
    from ns_api import cut_project as CP   # noqa: PLC0415
    from ns_api import run_paths as RP     # noqa: PLC0415
    run = RP.current_run(P.ROOT)
    return run if CP._rm().is_asset_pack_run(run, P.ROOT) else None


def _command(n: int, variant: str, body: CutBody) -> list[str]:
    """V2（资产包模式）：tools/assemble_series.py → build → compose（配乐 / 音色走 run_media，只认 music_v2 / voices_v2，
    不碰 V1 的 data/music/series10 和 voices.json；产物写当前剧的 renders/epNN/_final）。
    V1：照旧 tools/assemble_episode.py（V1 已冻结，行为不变）。"""
    if _asset_pack_run():
        cmd = [sys.executable, str(CODE / "tools" / "assemble_series.py"), f"ep{n:02d}", "--variant", variant]
        if body.dialogue_source in ("tts", "h3"):   # assemble_series 只收 tts / h3；“自动”= 它的默认（h3 回听不合格整镜 TTS 兜底）
            cmd += ["--dialogue-source", body.dialogue_source]
        return cmd
    cmd = [sys.executable, str(P.ROOT / "tools" / "assemble_episode.py"), f"ep{n:02d}", "--variant", variant]
    if body.dialogue_source:
        cmd += ["--dialogue-source", body.dialogue_source]
    return cmd


@router.post("/api/episodes/{n}/cut-job", status_code=202)
def start_cut(n: int, body: CutBody | None = None):
    """合成新版本：先收下（202，立即返回任务），后台子进程合成；同一集已在合成 → 原样返回那个任务（不重复起、不退回）"""
    b = body or CutBody()
    if b.dialogue_source not in (None, "tts", "h3", "auto"):
        raise HTTPException(422, "dialogue_source 只能是 tts | h3 | auto")
    with _lock:
        cur = _job_view(n)
        if cur and cur["state"] == "running":
            return cur
        variant = "UI" + time.strftime("%m%d-%H%M%S")
        logs = P.DATA / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f"cut_ep{n:02d}_{variant}.log"
        cmd = _command(n, variant, b)
        fh = open(log, "w", encoding="utf-8")  # noqa: SIM115 — 子进程写完由系统关
        proc = subprocess.Popen(cmd, cwd=str(CODE), stdout=fh, stderr=subprocess.STDOUT)
        JOBS[n] = {"episode": n, "variant": variant, "state": "running", "started_at": P.now(), "finished_at": None,
                   "by": b.by or "canvas", "cmd": cmd[1:], "log": str(log), "proc": proc,
                   "engine": "compose" if cmd[1].endswith("assemble_series.py") else "assemble_episode"}
        return _job_view(n)


@router.get("/api/episodes/{n}/cut-job")
def cut_job(n: int):
    return _job_view(n) or {"episode": n, "state": "none"}
