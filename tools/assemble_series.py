"""ASSEMBLY（FOCUS 第 6 条，2026-11-02）：series10 任意一集一键装配成片。

    .venv/Scripts/python.exe tools/assemble_series.py ep01            # 拉缺的片 + 装配 → data/renders/ep01/_final/ep01_v1.mp4
    .venv/Scripts/python.exe tools/assemble_series.py ep02 --variant v2 --no-pull
    .venv/Scripts/python.exe tools/assemble_series.py ep01 --include-best-effort   # 尽力版也进成片（默认当占位）

做什么：
 1. 读负责该集的服务器 state_<host>.json（经 tools/netfix/rsh.py，只读，不占出图卡）→ 每镜入选版本；
 2. 状态 done 的镜 = 视频（本机没有就经 rsh 拉原片 clips/）；其余镜（尽力 / 渲染中 / 无）= 首帧静帧缓推占位（拉当前首帧）；
 3. 调 tools/assemble_episode.py 的同一条后期链（--sources-from 指定每镜来源）：配音 = TTS 缓存 / H3 原声，
    BGM = 集级一条（data/music/series10/epNN.wav，L-118），转场 = 规则化（同场硬切 + J-cut，assemble.py 内置），响度 -14 LUFS；
 4. 字幕：硬规则“成片不烧字幕”（L-002 / ffmpeg.NO_SUBTITLES），所以只出外挂 <成片>.srt（不进视频流）；
 5. 产物：_final/epNN_<v>.mp4 + .timeline.json + .srt + _manifest.json（每镜来源 / 是否占位 / 闸门）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.autopilot import runs as RUNS  # noqa: E402
from tools.factory import hosts as HOSTS  # noqa: E402
from tools.netfix import rssh as RSSH  # noqa: E402

RUN_ID = RUNS.primary_run()
RUN_REL = f"data/pipeline/runs/{RUN_ID}"
RUN = ROOT / RUN_REL
VID = RUN / "video"


def rsh(host: str, cmd: str, out: Path | None = None) -> bytes:
    r = RSSH.run_retry(host, cmd, timeout=900)   # 统一远程命令入口（tools/netfix/rssh.py）
    if r.returncode != 0:
        raise RuntimeError(f"rsh {host} rc={r.returncode}: {(r.stderr or b'')[-200:]!r}")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_bytes(r.stdout)
        os.replace(tmp, out)
    return r.stdout


def srv(host: str) -> str:
    return HOSTS._host(host)["video_root"]


def pull(host: str, rel: str) -> Path:
    dst = ROOT / rel
    if not dst.is_file() or dst.stat().st_size == 0:
        rsh(host, f"cat {srv(host)}/{rel}", dst)
    return dst


def write_json(p: Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode")
    ap.add_argument("--variant", default="v1")
    ap.add_argument("--no-pull", action="store_true", help="不连服务器，用本机已有的 state / 片")
    ap.add_argument("--include-best-effort", action="store_true")
    ap.add_argument("--dialogue-source", default="h3", choices=("tts", "h3"))
    ap.add_argument("--no-bgm", action="store_true")
    a = ap.parse_args()
    ep = int(re.sub(r"\D", "", a.episode))
    name = f"ep{ep:02d}"
    hosts = json.loads((VID / "hosts.json").read_text(encoding="utf-8"))
    host = hosts[str(ep)]
    st_local = VID / f"state_{host}.json"
    if not a.no_pull:
        rsh(host, f"cat {srv(host)}/{RUN_REL}/video/state_{host}.json", st_local)
    state = json.loads(st_local.read_text(encoding="utf-8"))["shots"]
    script = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    ep_shots = next(e for e in script["episodes"] if int(e["number"]) == ep)["shots"]

    srcs, rows = [], []
    for sh in ep_shots:
        idx = int(sh["index"])
        key = f"{name}-S{idx}"
        s = state.get(key) or {}
        status, chosen = s.get("status"), s.get("chosen")
        r = next((x for x in s.get("renders", []) if x.get("variant") == chosen and x.get("file")), None)
        ok_status = status == "done" or (a.include_best_effort and status == "best_effort")
        row = {"shot": key, "index": idx, "state": status, "chosen": chosen}
        if ok_status and r:
            rel = r["file"]
            p = (ROOT / rel) if (ROOT / rel).is_file() or a.no_pull else pull(host, rel)
            if p.is_file():
                srcs.append({"index": idx, "kind": "video", "file": rel,
                             "origin": f"{key} {chosen} {r.get('recipe')} seed {r.get('seed')}"})
                row.update(source=rel, placeholder=False, verdict=(r.get("score") or {}).get("verdict"))
                rows.append(row)
                continue
        # 占位：首帧静帧缓推（首帧取该镜最新渲染记录里的 first_frame）
        ff = next((x.get("first_frame") for x in reversed(s.get("renders", [])) if x.get("first_frame")), None)
        if ff and not (ROOT / ff).is_file() and not a.no_pull:
            try:
                pull(host, ff)
            except RuntimeError:
                pass
        if ff and (ROOT / ff).is_file():
            srcs.append({"index": idx, "kind": "still", "file": ff, "origin": f"占位首帧 {key}",
                         "placeholder": True})
            row.update(source=ff, placeholder=True, reason=f"state={status}，无通过契约的视频")
        else:
            row.update(source=None, placeholder=True, reason=f"state={status}，连首帧也没有 → 本机旧静帧 / 黑场")
        rows.append(row)

    out_dir = ROOT / "data/renders" / name / "_final"
    work = out_dir / "_asm"
    work.mkdir(parents=True, exist_ok=True)
    tl_in = work / f"{name}_sources.timeline.json"
    write_json(tl_in, {"shots": [x for x in srcs if x["kind"] == "video"]})
    # 静帧占位走 assemble.find_source 的 still 分支：这里用 sources 覆盖，需在进程内调用而不是 CLI
    sys.path.insert(0, str(ROOT / "services/post"))
    sys.path.insert(0, str(ROOT / "tools"))
    from ns_post.assemble import Settings, assemble_episode, load_episode  # noqa: E402
    from ns_post.tts import KokoroBackend, SenseVoiceAsr, load_voice_config  # noqa: E402

    sources = {}
    for x in srcs:
        p = ROOT / x["file"]
        if x["kind"] == "video":
            sources[x["index"]] = {"kind": "video", "origin": x["origin"], "path": p, "path_4k": None}
        else:
            sources[x["index"]] = {"kind": "still", "origin": x["origin"], "path": p, "placeholder": True}
    cfg = load_voice_config()
    settings = Settings(threads=8, bgm=not a.no_bgm, deliver_4k="off", dialogue_source=a.dialogue_source,
                        music_dir=str(ROOT / "data/music/series10"))
    episode = load_episode(ROOT / "data/import/script_v2.json", ep)
    tl = assemble_episode(episode, out_dir / "_asm", tts=KokoroBackend(cfg, num_threads=4),
                          asr=SenseVoiceAsr(cfg, num_threads=4), settings=settings, voices_cfg=cfg,
                          allow_laptop_video=False, keep_work=False, sources=sources, variant=a.variant)
    produced = ROOT / next(iter(tl["deliveries"].values()))["file"]
    final = out_dir / f"{name}_{a.variant}.mp4"
    shutil.copyfile(produced, final)
    shutil.copyfile(next(iter((work).glob(f"*{a.variant}.timeline.json"))), out_dir / f"{name}_{a.variant}.timeline.json")

    # 外挂字幕（不烧录）：时间轴 = timeline.speech 的 start/end
    cues = sorted((s for s in tl["speech"] if s.get("start_s") is not None), key=lambda s: s["start_s"])
    srt = "\n".join(f"{i}\n{srt_time(s['start_s'])} --> {srt_time(s['end_s'])}\n{s['text']}\n"
                    for i, s in enumerate(cues, 1))
    (out_dir / f"{name}_{a.variant}.srt").write_text(srt, encoding="utf-8")

    by_idx = {int(s["index"]): s for s in tl["shots"]}
    for r in rows:
        t = by_idx.get(r["index"], {})
        r.update(start_s=t.get("start_s"), duration_s=t.get("duration_s"), audio=t.get("audio"),
                 timeline_kind=t.get("kind"))
    n_ph = sum(1 for r in rows if r["placeholder"])
    manifest = {"episode": name, "variant": a.variant, "output": str(final.relative_to(ROOT)).replace("\\", "/"),
                "complete": n_ph == 0, "video_shots": len(rows) - n_ph, "placeholder_shots": n_ph,
                "duration_s": tl["duration_s"], "bgm": tl["bgm"].get("file") or tl["bgm"].get("reason"),
                "loudness": tl["loudness"]["measured"], "subtitles": "sidecar .srt（不烧录，L-002）",
                "warnings": tl["warnings"], "shots": rows}
    write_json(out_dir / f"{name}_{a.variant}_manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("output", "complete", "video_shots", "placeholder_shots",
                                                 "duration_s", "loudness")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
