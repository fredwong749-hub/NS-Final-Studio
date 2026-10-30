"""
项目进度、系列控制标记、GPU 状态（只读推导，唯一会写的是 series_control.json）。

项目 slug：
- 默认项目（weita = 为他而骚）就是 renders_gpu3 根，系列渲染器工作目录是 ns-studio/data/run/weita（现有路径不动）；
- 新项目：<renders_gpu3>/<slug>/epXX/SN/…，渲染器状态文件（STATUS.log、HARD_SHOTS.jsonl…）也放在 <renders_gpu3>/<slug>/，
  剧本导入 JSON 放 <renders_gpu3>/<slug>/script.json（ScriptImport 格式，可选）。
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import RootCfg, Settings
from .models import now
from .sources import Root, load_json, make_roots, read_jsonl

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
GOOD_DEFAULT_FRAME_S = 60.0      # bench.csv 没数据时的兜底（每镜首帧 GPU 秒）
GOOD_DEFAULT_VIDEO_S = 1600.0    # 每镜视频（H3 FL2VA int8 t8，243 帧）


@dataclass
class Project:
    slug: str
    dir: Path                    # 渲染产物根（epXX/SN/…）
    out: Path | None             # 渲染器状态目录（STATUS.log 等）
    script: Path | None
    roots: list[Root]
    control_paths: list[Path]    # series_control.json 写到哪里


def project(settings: Settings, slug: str, default_roots: list[Root]) -> Project:
    if not SLUG_RE.match(slug):
        raise ValueError("slug 只能是小写字母、数字、- 和 _")
    base = settings.base
    if slug == settings.default_slug:
        # 默认项目映射到根；控制标记同时写到 <base>/<slug>/ 与根，渲染器任读其一
        return Project(slug, base, settings.series_out or base, settings.script_json, default_roots,
                       [base / slug / "series_control.json", base / "series_control.json"])
    d = base / slug
    if not d.is_dir():
        raise KeyError(f"项目 {slug}（{d} 不存在）")
    roots = make_roots([RootCfg("renders_gpu3", "takes", d, data_dir=base.parent)])
    # 剧本：projects/<slug>/data/import/script_v2.json（新剧向导导入）→ 回退 renders_gpu3/<slug>/script.json
    cands = [settings.projects_root / slug / "data" / "import" / "script_v2.json"] if settings.projects_root else []
    script = next((c for c in cands + [d / "script.json"] if c.exists()), None)
    return Project(slug, d, d, script, roots,
                   [d / "series_control.json"])


# ------------------------------------------------------------------ 进度
def script_episodes(p: Project) -> dict[int, dict]:
    data = load_json(p.script, None) if p.script else None
    if not data:
        return {}
    return {e["number"]: {"title": e.get("title", ""), "shots": [s["index"] for s in e.get("shots", [])]}
            for e in data.get("episodes", [])}


def bench_costs(path: Path | None) -> dict:
    """bench.csv 每行是一次尝试；按镜头求和（含重试），再取平均 → 每镜实际 GPU 秒。"""
    per: dict[tuple[str, str], float] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if str(r.get("ok", "")).lower() != "true":
                    continue
                kind = "video" if r.get("kind") == "video" else "frame" if r.get("kind") == "frame" else None
                if kind and r.get("gpu_seconds"):
                    per[(r["shot"], kind)] = per.get((r["shot"], kind), 0.0) + float(r["gpu_seconds"])
    except (OSError, ValueError, AttributeError):
        pass
    out = {}
    for kind, dflt in (("frame", GOOD_DEFAULT_FRAME_S), ("video", GOOD_DEFAULT_VIDEO_S)):
        xs = [v for (_, k), v in per.items() if k == kind]
        out[kind] = {"seconds_per_shot": round(sum(xs) / len(xs), 1) if xs else dflt, "samples": len(xs),
                     "source": str(path) if xs else "default"}
    return out


def _status_lines(out: Path | None) -> dict[int, str]:
    last: dict[int, str] = {}
    if out and (out / "STATUS.log").exists():
        for ln in (out / "STATUS.log").read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\[ep(\d+)\]", ln)
            if m:
                last[int(m.group(1))] = ln.strip()
    return last


def _by_episode(rows: list[dict], key_fields=("shot", "item", "shot_id")) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in rows:
        v = next((str(r[k]) for k in key_fields if r.get(k)), "")
        m = re.search(r"ep(\d+)", v, re.I)
        if m:
            out.setdefault(int(m.group(1)), []).append(r)
    return out


def _qa(ep: int, dirs: list[Path], status_line: str | None, final: Path | None) -> dict:
    """优先级：qa.json → QA_FAIL/QA_HOLD/QA_PASS 标记（与 upscale_4k.qa_gate 一致）→ STATUS.log 旗标 → 无。"""
    for d in dirs:
        q = load_json(d / "qa.json", None)
        if isinstance(q, dict) and q.get("verdict"):
            return {"state": q["verdict"], "source": str(d / "qa.json"), "issues": q.get("issues", [])[:20],
                    "by": q.get("by"), "at": q.get("at")}
    for m, state in (("QA_FAIL", "fail"), ("QA_HOLD", "hold")):
        for d in dirs:
            if (d / m).exists():
                return {"state": state, "source": str(d / m), "issues": []}
    for d in dirs:
        if (d / "QA_PASS").exists():
            shas = re.findall(r"\b[0-9a-f]{64}\b", (d / "QA_PASS").read_text(encoding="utf-8", errors="replace"))
            stale = bool(shas and final and final.exists() and _sha256(final) not in shas)
            return {"state": "stale" if stale else "pass", "source": str(d / "QA_PASS"), "issues": []}
    if status_line:
        flag = status_line.split("]", 1)[1].strip()[:2]
        state = {"✅": "auto_pass", "⚠": "blocked_shots", "⛔": "paused", "⏸": "paused"}.get(flag[:1], "pending")
        return {"state": state, "source": "STATUS.log", "issues": [], "line": status_line}
    return {"state": "none", "source": None, "issues": []}


_sha_cache: dict[tuple[str, float, int], str] = {}


def _sha256(p: Path) -> str:
    import hashlib
    st = p.stat()
    k = (str(p), st.st_mtime, st.st_size)
    if k not in _sha_cache:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        _sha_cache[k] = h.hexdigest()
    return _sha_cache[k]


def active_render_gpus(settings: Settings) -> int:
    """正在为系列渲染器干活的卡（gpu.lock.* 内容含 owner_script_render / weita_series / weita-series），至少 1。"""
    n = 0
    for f in settings.lock_dir.glob("gpu.lock.*"):
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        if re.search(r"owner_script_render|weita[_-]series|series", txt) and not re.search(r"llm|train|lora", txt, re.I):
            n += 1
    return max(n, 1)


def episodes_progress(settings: Settings, p: Project) -> dict:
    eps = script_episodes(p)
    numbers = set(eps)
    if p.dir.is_dir():
        numbers |= {int(d.name[2:]) for d in p.dir.glob("ep*") if d.is_dir() and re.fullmatch(r"ep\d+", d.name)}
    if p.out and p.out != p.dir and p.out.is_dir():
        numbers |= {int(d.name[2:]) for d in p.out.glob("ep*") if d.is_dir() and re.fullmatch(r"ep\d+", d.name)}
    status = _status_lines(p.out)
    hard = _by_episode(read_jsonl(p.out / "HARD_SHOTS.jsonl")) if p.out else {}
    blocked = _by_episode(read_jsonl(p.out / "BLOCKED.jsonl")) if p.out else {}
    werr = _by_episode(read_jsonl(p.out / "WORKER_ERRORS.jsonl")) if p.out else {}
    costs = bench_costs(settings.bench_csv)
    gpus = active_render_gpus(settings)
    rows, total_gpu_s = [], 0.0
    for n in sorted(numbers):
        epd = p.dir / f"ep{n:02d}"
        outd = p.out / f"ep{n:02d}" if p.out else None
        shots = eps.get(n, {}).get("shots") or sorted({s for r in p.roots for s in r.shot_numbers(n)})
        frames = videos = vid4k = 0
        shot_errors = []
        for s in shots:
            has_f = has_v = False
            for r in p.roots:
                found, active, err = r.takes(n, s)
                has_f |= any(t.stage == "image" and (t.active or not active.get("image")) for t, _ in found)
                has_v |= any(t.stage == "video" and (t.active or not active.get("video")) for t, _ in found)
                if err and r is p.roots[0]:
                    shot_errors.append(f"S{s}: {err[:200]}")
            if outd and (outd / "clips" / f"ep{n:02d}s{s}.mp4").exists():
                has_v = True
            frames += has_f
            videos += has_v
            sd = epd / f"S{s}" / "takes"
            vid4k += sd.is_dir() and any(sd.glob("video_*_4k.mp4"))
        # 成片：gpu3 系列装配（renders_gpu3/epXX/epXX_final.mp4、工作目录）或 T38 后期装配（data/episodes/epXX.mp4）
        episodes_dir = settings.base.parent / "episodes" / ("" if p.slug == settings.default_slug else p.slug)
        final = next((f for f in (epd / f"ep{n:02d}_final.mp4", (outd / f"ep{n:02d}_final.mp4") if outd else None,
                                  episodes_dir / f"ep{n:02d}.mp4") if f and f.exists()), None)
        up = next((f for f in (epd / f"ep{n:02d}_4k.mp4", episodes_dir / f"ep{n:02d}_4k.mp4") if f.exists()),
                  epd / f"ep{n:02d}_4k.mp4")
        man = load_json(epd / f"ep{n:02d}_4k.manifest.json", {}) or {}
        upscale = {"state": "done" if up.exists() and man.get("status", "done") == "done" else man.get("status") or ("none" if not vid4k else "partial"),
                   "file": str(up) if up.exists() else None, "shots_4k": vid4k}
        asm = (outd / "assembly") if outd else None
        music = next((m for m in ((settings.music_dir / f"ep{n:02d}.wav") if settings.music_dir else None,
                                  epd / "music.wav", epd / f"ep{n:02d}_music.wav") if m and m.exists()), None)
        audio = {"voiceover": bool(asm and (asm / "voiceover.json").exists()),
                 "voiceover_wavs": len(list(asm.glob("vo_*.wav"))) if asm and asm.is_dir() else 0,
                 "music": str(music) if music else None,
                 "stems_shots": sum((epd / f"S{s}" / "audio" / "stems.json").exists() for s in shots),
                 "music_cues": bool(music and music.with_suffix(".json").exists())}
        errors = [f"BLOCKED {r.get('shot') or r.get('item')}: {str(r.get('reason') or r.get('wrong') or r.get('error') or '')[:200]}"
                  for r in blocked.get(n, [])]
        errors += [f"HARD {r.get('shot')}: {'; '.join(map(str, r.get('wrong', [])))[:200]}" for r in hard.get(n, [])]
        errors += [f"WORKER {r.get('item')} {r.get('slot', '')}: {str(r.get('error', ''))[:200]}" for r in werr.get(n, [])[-5:]]
        errors += shot_errors
        if outd and (outd / "FAILURE_REPORT.md").exists():
            errors.append(f"FAILURE_REPORT: {outd / 'FAILURE_REPORT.md'}")
        total = len(shots)
        remaining = 0.0 if final else (max(total - frames, 0) * costs["frame"]["seconds_per_shot"]
                                       + max(total - videos, 0) * costs["video"]["seconds_per_shot"])
        total_gpu_s += remaining
        rows.append({
            "ep": n, "title": eps.get(n, {}).get("title", ""), "shots": total,
            "frames": {"done": frames, "total": total}, "videos": {"done": videos, "total": total},
            "qa": _qa(n, [d for d in (epd, outd) if d], status.get(n), final),
            "audio": audio, "upscale_4k": upscale,
            "final": {"exists": bool(final), "file": str(final) if final else None},
            "status_line": status.get(n),
            "hard_shots": len(hard.get(n, [])), "blocked": len(blocked.get(n, [])),
            "eta_s": round(remaining / gpus), "errors": errors,
        })
    return {"project": p.slug, "episodes": rows, "control": load_json(p.control_paths[0], None),
            "eta": {"total_s": round(total_gpu_s / gpus), "gpu_seconds": round(total_gpu_s), "active_gpus": gpus,
                    "per_shot": costs,
                    "formula": "(未出首帧镜数×每镜首帧GPU秒 + 未出视频镜数×每镜视频GPU秒) ÷ 正在出片的GPU数；已有成片的集为0"}}


# ------------------------------------------------------------------ 系列控制
def write_control(p: Project, action: str, episodes: list[int] | None, by: str, note: str = "",
                  adult_content: bool = False) -> dict:
    rec = {"schema": "nsfs_canvas.series_control/v1", "project": p.slug, "action": action,
           "episodes": episodes, "adult_content": adult_content, "by": by, "note": note, "at": now()}
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    for path in p.control_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        with (path.parent / "series_control.log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {**rec, "written": [str(x) for x in p.control_paths]}


# ------------------------------------------------------------------ GPU
def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _comfy_queue(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/queue", timeout=2) as r:
            q = json.loads(r.read())
        return {"url": url, "running": len(q.get("queue_running", [])), "pending": len(q.get("queue_pending", []))}
    except Exception:  # noqa: BLE001 —— 实例没起或不可达
        return {"url": url, "running": None, "pending": None, "error": "unreachable"}


def _lock(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        txt = path.read_text(errors="replace").strip()
    except OSError:
        return {"file": str(path), "text": None}
    m = re.match(r"pid:(\d+)\s*(.*)", txt, re.S)
    pid = int(m.group(1)) if m else None
    alive = None
    if pid:
        alive = Path(f"/proc/{pid}").exists() if Path("/proc").exists() else None
    return {"file": str(path), "text": txt[:300], "pid": pid, "pid_alive": alive,
            "owner": (m.group(2) if m else txt).split("(")[0].strip()[:80] or None}


def gpus(settings: Settings) -> list[dict]:
    smi = _run([settings.nvidia_smi, "--query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits"])
    apps = _run([settings.nvidia_smi, "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
                 "--format=csv,noheader,nounits"])
    procs: dict[str, list[dict]] = {}
    for line in apps.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 4:
            procs.setdefault(parts[0], []).append({"pid": int(parts[1]) if parts[1].isdigit() else parts[1],
                                                   "name": Path(parts[2]).name, "vram_mb": _num(parts[3])})
    rows = {}
    for line in smi.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 6 and parts[0].isdigit():
            rows[int(parts[0])] = {"uuid": parts[1], "name": parts[2], "vram_used_mb": _num(parts[3]),
                                   "vram_total_mb": _num(parts[4]), "util": _num(parts[5])}
    ids = sorted(set(rows) | set(settings.comfy) | set(settings.faulty_gpus))
    out = []
    for g in ids:
        r = rows.get(g, {})
        locks = {k: _lock(settings.lock_dir / f"{k}.gpu{g}") or _lock(settings.lock_dir / f"{k}.{g}")
                 for k in ("gpu.lock", "train.lock", "lend")}
        comfy = _comfy_queue(settings.comfy[g]) if g in settings.comfy else None
        faulty = g in settings.faulty_gpus
        busy_by, task = None, None
        for k in ("gpu.lock", "train.lock", "lend"):
            if locks[k]:
                busy_by = busy_by or locks[k].get("owner")
                task = task or (locks[k].get("text") or "")[:200]
        if not busy_by and comfy and comfy.get("running"):
            busy_by, task = "comfyui", f"ComfyUI 运行 {comfy['running']} / 排队 {comfy['pending']}"
        p = procs.get(r.get("uuid", ""), [])
        if not busy_by and p:
            busy_by, task = p[0]["name"], ", ".join(f"{x['name']}({x['pid']})" for x in p)[:200]
        out.append({
            "id": g, "name": r.get("name"), "faulty": faulty,
            "note": "faulty — never used（显存 >11 GB 静默算错，见 /root/README-GPU2-FAULTY.txt）" if faulty else None,
            "busy_by": None if faulty and not busy_by else busy_by, "task": task,
            "vram_used_mb": r.get("vram_used_mb"), "vram_total_mb": r.get("vram_total_mb"), "util": r.get("util"),
            "lock_file": locks["gpu.lock"], "train_lock": locks["train.lock"], "lend_file": locks["lend"],
            "comfy": comfy, "processes": p, "scheduler": _sched_for(settings, g),
        })
    return out


# T46 gpu3 阶段调度器（ns-studio/scripts/ns_sched.py）写在锁目录里的计划 / 分配，只读
def scheduler_plan(settings: Settings) -> dict | None:
    p = settings.lock_dir / "scheduler_plan.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sched_for(settings: Settings, g: int) -> dict | None:
    plan = scheduler_plan(settings)
    try:
        assign = json.loads((settings.lock_dir / f"assign.gpu{g}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        assign = None
    row = next((x for x in (plan or {}).get("gpus", []) if x.get("gpu") == g), None)
    if not row and not assign:
        return None
    return {"mode": (plan or {}).get("mode"), "at": (plan or {}).get("at"), "assign": assign,
            "planned": row.get("assigned") if row else None, "stage": row.get("stage") if row else None,
            "locked": row.get("locked") if row else None, "why": row.get("why") if row else None,
            "next": (row.get("next_at_boundary") or [])[:3] if row else []}


def _num(x: str):
    try:
        return float(x) if "." in x else int(x)
    except ValueError:
        return None
