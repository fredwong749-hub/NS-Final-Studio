"""Run every gate over one episode of the local mirror (data/renders_gpu3/epNN) and write the reports."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import QC_VERSION
from . import media as M
from . import provenance as P
from .thresholds import T, describe, judge, worst

BACK_VIEW = ("背对镜头", "背影", "背对")  # gpu3 weita_series BACK_VIEW
LEAD = "林晚"


def project_root() -> Path:
    return Path(os.environ.get("NS_PROJECT_ROOT") or Path(__file__).resolve().parents[3])


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def shot_dirs(ep_dir: Path) -> list[Path]:
    ds = [d for d in ep_dir.iterdir() if d.is_dir() and re.fullmatch(r"S\d+", d.name)]
    return sorted(ds, key=lambda d: int(d.name[1:]))


def genders(root: Path) -> dict[str, str]:
    v = _load(root / "config" / "voices.json") or {}
    out = {}
    def walk(o):
        if isinstance(o, dict):
            if "name" in o and "gender" in o:
                out[o["name"]] = o["gender"]
            for x in o.values():
                walk(x)
    walk(v)
    return out


def fetch_gpu3(host: str, remote: str, cache: Path) -> Path | None:
    """Read-only copy of one gpu3 file (scp BatchMode) into the cache; nothing on gpu3 is modified."""
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / P.gpu3_cache_name(Path(remote).as_posix())
    if dst.is_file():
        return dst
    r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"{host}:{remote}", str(dst)],
                       capture_output=True, timeout=120)
    return dst if r.returncode == 0 and dst.is_file() else None


def resolve_keyframes(shot_dir: Path, data: Path, takes: dict, vtake: dict, clip: Path, cache: Path,
                      gpu3_host: str | None) -> tuple[Path | None, Path | None, dict]:
    prov: dict = {}
    out = []
    for which, key in (("first", "reference"), ("last", "last_target")):
        rec = vtake.get(key)
        p, how = P.local_path(rec, data, shot_dir, cache)
        if p is None and rec and gpu3_host and str(rec).startswith("/"):
            p = fetch_gpu3(gpu3_host, rec, cache)
            how = "fetched from gpu3 (read-only copy)" if p else "not in the local mirror; gpu3 fetch failed"
        prov[which] = {"recorded": rec, "how": how, "file": str(p) if p else None}
        out.append(p)
    first, last = out
    if first is None:  # infer: a local keyframe whose structure matches frame 0 (provenance = inferred)
        f0 = M.decode_indices(clip, [0]).get(0)
        rows = takes.get("takes") or []
        act = (takes.get("active") or {}).get("image")
        cands = [shot_dir / "frame.png"]
        cands += [P.local_path(t.get("file"), data, shot_dir)[0] for t in
                  sorted((t for t in rows if t.get("stage") == "image"),
                         key=lambda t: (t.get("n") != act, -int(t.get("n") or 0)))]
        tried = []
        for c in cands:
            if c is None or not c.is_file() or f0 is None:
                continue
            m = M.structure_match(f0, M.h3_geometry(M.load_rgb(c), (f0.shape[1], f0.shape[0])))
            tried.append({"file": c.name, "match": round(m, 3)})
            if m >= 0.85:
                first = c
                prov["first"].update(file=str(c), inferred=True,
                                     how=prov["first"]["how"] + "; INFERRED by structure match " f"{m:.3f}")
                break
        prov["first"]["tried"] = tried
    if last is None:
        lt = [t for t in (takes.get("takes") or []) if t.get("stage") == "last"]
        if lt:
            p, how = P.local_path(sorted(lt, key=lambda t: -int(t.get("n") or 0))[0].get("file"), data, shot_dir)
            if p:
                last = p
                prov["last"].update(file=str(p), how=f"independent last take ({how})")
    return first, last, prov


def shown_frame_gate(shown: Path, clip: Path, first: Path | None, kf: dict) -> dict:
    """Q-P6: the first frame the canvas shows (shot/frame.png) vs the video's decoded frame 0."""
    if not shown.is_file():
        return judge("Q-P6", None, unchecked="shot has no frame.png in the mirror")
    f0 = M.decode_indices(clip, [0]).get(0)
    if f0 is None:
        return judge("Q-P6", None, unchecked="frame 0 not decoded")
    m = round(M.structure_match(f0, M.h3_geometry(M.load_rgb(shown), (f0.shape[1], f0.shape[0]))), 3)
    same_file = None
    if first is not None and Path(first).is_file():
        same_file = M.sha256(shown) == M.sha256(Path(first))
    return judge("Q-P6", m, detail=f"frame.png structure vs video frame 0; sha equal to the keyframe used: "
                                   f"{same_file} ({(kf.get('first') or {}).get('how')})", same_sha=same_file)


def run_episode(ep: int, *, root: Path | None = None, mirror: Path | None = None, out_dir: Path | None = None,
                gpu3_host: str | None = None, shots: list[str] | None = None, now: float | None = None,
                log=print) -> dict:
    from . import audio_gates as A
    from . import face as F
    from . import video_gates as V
    root = root or project_root()
    data = root / "data"
    mirror = mirror or data / "renders_gpu3"
    ep_dir = mirror / f"ep{ep:02d}"
    cache = data / "qc" / "kf_cache"
    per_dir = data / "qc" / f"ep{ep:02d}"
    per_dir.mkdir(parents=True, exist_ok=True)
    gmap = genders(root)
    bv, bv_src = P.current_bible_version(root)
    models, ref_emb, face_note = None, None, ""
    paths = F.find_models(root)
    if paths:
        pins = F.verify_pins(paths)
        if all(pins.values()):
            models = F.FaceModels(*paths)
            fr = _load(root / "config" / "face_reference.json") or {}
            rp = root / fr.get("reference", "assets/characters/lin_wan/lin_wan.png")
            if rp.is_file():
                import cv2
                img = cv2.imread(str(rp))
                fs = models.faces(img) if img is not None else []
                if fs:
                    ref_emb = models.embed(img, F.largest(fs))
                    face_note = f"reference {rp.relative_to(root).as_posix()} (config/face_reference.json)"
        else:
            face_note = f"model sha mismatch {pins}"
    else:
        face_note = "YuNet/SFace not found"
    report = {"qc_version": QC_VERSION, "episode": ep, "mirror": str(ep_dir),
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "bible_version_current": bv, "bible_version_source": bv_src, "face_reference": face_note,
              "heartbeat": P.heartbeat(mirror / ".last_sync_gpu3", now), "shots": {}}
    for sd in shot_dirs(ep_dir):
        if shots and sd.name not in shots:
            continue
        t0 = time.time()
        takes = _load(sd / "takes.json") or {}
        compiled = _load(sd / "compiled.json") or {}
        stems = _load(sd / "audio" / "stems.json")
        act = takes.get("active") or {}
        vtake = next((t for t in takes.get("takes") or [] if t.get("stage") == "video" and t.get("n") == act.get("video")),
                     None)
        clip = None
        if vtake:
            clip, _ = P.local_path(vtake.get("file"), data, sd)
        if clip is None and (sd / "video.mp4").is_file():
            clip = sd / "video.mp4"
        shot = {"shot": sd.name, "active": act, "video": str(clip) if clip else None, "gates": []}
        kf = {}
        if clip is not None:
            try:
                info = M.video_info(clip)
                first, last, kf = resolve_keyframes(sd, data, takes, vtake or {}, clip, cache, gpu3_host)
                small = M.decode_small(clip, info=info)
                kr = V.keyframe_gate(clip, first, last, kf_provenance=kf, info=info, small=small)
                shot["keyframe"] = {k: v for k, v in kr.items() if k != "gates"}
                shot["gates"] += kr["gates"]
                shot["gates"].append(shown_frame_gate(sd / "frame.png", clip, first, kf))
                src =compiled.get("source") or {}
                text = (src.get("img") or "") + (src.get("motion") or "")
                vis = compiled.get("visible_characters")
                lead = (LEAD in vis) if isinstance(vis, list) else True
                dr = V.drift_gate(clip, models=models, ref_embedding=ref_emb, lead_expected=lead,
                                  back_view=any(b in text for b in BACK_VIEW), info=info)
                shot["drift"] = {k: v for k, v in dr.items() if k != "gates"}
                shot["gates"] += dr["gates"]
                dia = compiled.get("dialogue") or []
                g = {gmap.get(d.get("speaker"), "unknown") for d in dia if isinstance(d, dict)}
                ar = A.audio_gate(clip, prompt=(vtake or {}).get("prompt"), h3_dialogue_genders=g,
                                  has_dialogue=bool(dia), stems=stems, clip_sha=M.sha256(clip),
                                  vocals=sd / "audio" / "h3_vocals.wav",
                                  bed=(sd / "audio" / "h3_rest_full.wav") if (sd / "audio" / "h3_rest_full.wav").is_file()
                                  else None)
                shot["audio"] = {k: v for k, v in ar.items() if k != "gates"}
                shot["gates"] += ar["gates"]
            except Exception as e:  # noqa: BLE001 — a broken clip is a finding, not a crash
                shot["error"] = f"{type(e).__name__}: {e}"
                shot["gates"].append(judge("Q-K1", None, unchecked=f"clip unreadable: {e}"))
        else:
            why = "no active video in the local mirror" + (f" (takes.json active video #{act.get('video')})"
                                                           if act.get("video") else " (shot has no video take)")
            for g in ("Q-K1", "Q-K2", "Q-K3", "Q-D1", "Q-A1", "Q-A2", "Q-A3"):
                shot["gates"].append(judge(g, None, unchecked=why))
        pv = P.shot_provenance(sd, takes, bv, compiled, stems, vtake, clip, kf)
        shot["gates"] += pv["gates"]
        shot["stamps"] = {"active": pv["active_stamps"], "all": pv["all_take_stamps"]}
        shot["verdict"] = worst(g["verdict"] for g in shot["gates"])
        shot["seconds"] = round(time.time() - t0, 1)
        (per_dir / f"{sd.name}.json").write_text(json.dumps(shot, ensure_ascii=False, indent=1, default=_js),
                                                 encoding="utf-8")
        log(f"[qc] ep{ep:02d} {sd.name}: {shot['verdict']} ({shot['seconds']} s)")
        report["shots"][sd.name] = shot
    report["verdict"] = worst([s["verdict"] for s in report["shots"].values()] + [report["heartbeat"]["verdict"]])
    report["stale"] = [{"shot": k, **s} for k, v in report["shots"].items() for s in v["stamps"]["active"]
                       if s["state"] != "current"]
    out_dir = out_dir or root / "docs" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / f"qc_ep{ep:02d}.json", out_dir / f"qc_ep{ep:02d}.md"
    jp.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=_js), encoding="utf-8")
    mp.write_text(render_md(report), encoding="utf-8")
    report["_paths"] = [str(jp), str(mp)]
    return report


def _js(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"
    if isinstance(v, list) and len(v) > 4:
        return f"[{len(v)} items]"
    return "—" if v is None else str(v)


ICON = {"pass": "✅ pass", "warn": "🟡 warn", "fail": "🔴 fail", "unchecked": "⚪ unchecked", "info": "ℹ info"}


def render_md(r: dict) -> str:
    L = [f"# QC 报告 ep{r['episode']:02d}（自动生成，{r['qc_version']}）", "",
         f"> 生成：{r['generated_at']}；镜像：`{r['mirror']}`；工具：`tools/qc_run.py --episode {r['episode']}`。",
         "> 只含技术量（尺寸、哈希、PSNR/SSIM、ΔE、SFace、LUFS、F0、版本、时间），不含任何内容或审美判断（G1–G6）。",
         "> 阈值与级别见 docs/qc_gates.md；`unchecked` 不等于通过。", "",
         f"**总判定：{ICON.get(r['verdict'], r['verdict'])}**　当前 bible_version：`{r['bible_version_current']}`"
         f"（{r['bible_version_source']}）；人脸参考：{r['face_reference']}", "",
         f"同步心跳 Q-S1：{ICON[r['heartbeat']['verdict']]}，{_fmt(r['heartbeat'].get('value'))} 分钟"
         f"（阈值 {r['heartbeat']['threshold']}；{r['heartbeat'].get('detail', '')}）", "",
         "## 逐镜汇总", "", "| 镜 | 判定 | fail | warn | unchecked | 视频 |", "|---|---|---|---|---|---|"]
    for k, s in r["shots"].items():
        c = lambda v: sum(1 for g in s["gates"] if g["verdict"] == v)  # noqa: E731
        L.append(f"| {k} | {ICON.get(s['verdict'])} | {c('fail')} | {c('warn')} | {c('unchecked')} | "
                 f"{Path(s['video']).name if s.get('video') else '无'} |")
    L += ["", "## 逐镜明细", ""]
    for k, s in r["shots"].items():
        L += [f"### {k}（{ICON.get(s['verdict'])}）", "", "| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |",
              "|---|---|---|---|---|---|---|---|"]
        for g in s["gates"]:
            d = (g.get("detail") or "").replace("|", "/").replace("\n", " ")
            L.append(f"| {g['gate']}{'·' + g['edge'] if g.get('edge') else ''} | {','.join(g['pi'])} | {g['metric']} | "
                     f"{_fmt(g.get('value'))} | {g['threshold']} | {g['status']}→{g['on_breach']} | "
                     f"{ICON.get(g['verdict'], g['verdict'])} | {d[:220]} |")
        if s.get("error"):
            L.append(f"\n错误：`{s['error']}`")
        L.append("")
    L += ["## 过期 / 未盖章的 active take（Q-P1，R-C8）", ""]
    if r["stale"]:
        L += ["| 镜 | stage | take | 状态 | take 的 bible_version |", "|---|---|---|---|---|"]
        L += [f"| {x['shot']} | {x['stage']} | {x['n']} | {x['state']} | {x.get('bible_version') or '—'} |"
              for x in r["stale"]]
    else:
        L.append("无。")
    L += ["", "## 阈值表（本次运行）", "", "| 闸门 | 指标 | 阈值 | 状态 | 级别 | 出处 |", "|---|---|---|---|---|---|"]
    L += [f"| {g} | {t['metric']} | {describe(g)} | {t['status']} | {t['on_breach']} | {t['source']} |"
          for g, t in T.items()]
    return "\n".join(L) + "\n"
