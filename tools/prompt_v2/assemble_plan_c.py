"""PROMPT（2026-10-31，方案 C）：按导演稿的转场合成 data/episodes/ep02_planC.mp4（只用 CPU / ffmpeg，不碰 takes、不改生产时间线）。

规则来源：
- 合成硬规则 = config/render_quality.json post.edit_rules（ns_post.assemble.resolve_settings 读取）：
  trim_frozen（freeze_still_diff / freeze_min_s / min_keep_s，用 ns_post.assemble.freeze_trims 剪开头 / 结尾定住段）、
  edge_fade_s 切点音频交叉淡化、room_tone、响度 -14 LUFS、1080×1920、24 fps、H.264、bt709。
  max_shot_s 拆刀与 pace_tighten 这里不做：导演稿已按 4–10 秒设计镜长，镜9 是导演稿明写的“三段同一镜头内完成”。
- 转场 = 导演稿（data/pipeline/runs/ep02_claude_director_v1/ep02_director_cut.md）：S4→S5 叠化 0.5 s、S7→S8 声音提前 0.4 s
  （J-cut）、S8→S9 叠化 0.3 s，其余硬切（动作 / 视线匹配由镜头内容完成）。
- 声音：每镜 H3 原声（对白嘴型同步）；不加 TTS、不加旁白（导演稿去掉了独白）。BGM：整集 BGM 暂缺（项目方配乐未出），只用 H3 原声。
每镜选片：--pick S1=path …；不给时按 video/ 目录里 official 优先、seed 小优先。
用法：.venv/Scripts/python.exe tools/prompt_v2/assemble_plan_c.py [--pick S3=…] [--out data/episodes/ep02_planC.mp4]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "post"))
from ns_post.assemble import Settings, frame_diffs, freeze_trims, resolve_settings  # noqa: E402

RUN = ROOT / "data" / "pipeline" / "runs" / "ep02_claude_director_v1"
FPS = 24
W, H = 1080, 1920
# 导演稿转场：(上一镜, 类型, 秒)
TRANS = {4: ("dissolve", 0.5), 7: ("jcut", 0.4), 8: ("dissolve", 0.3)}


def probe_dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def pick_clips(picks: dict[int, str]) -> dict[int, Path]:
    out = {}
    for n in range(1, 10):
        if n in picks:
            out[n] = ROOT / picks[n]
            continue
        c = sorted((RUN / "video").glob(f"S{n}_*.mp4"), key=lambda p: (0 if "_official_" in p.name else 1, p.name))
        if c:
            out[n] = c[0]
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", action="append", default=[])
    ap.add_argument("--out", default="data/episodes/ep02_planC.mp4")
    a = ap.parse_args(argv)
    s = resolve_settings(Settings(), 2)
    picks = {int(k.lstrip("S")): v for k, v in (x.split("=", 1) for x in a.pick)}
    clips = pick_clips(picks)
    missing = [n for n in range(1, 10) if n not in clips]
    if missing:
        raise SystemExit(f"缺镜 {missing}（video/ 里还没有）")
    work = RUN / "assemble"
    work.mkdir(exist_ok=True)
    plan = []
    for n in range(1, 10):
        p = clips[n]
        dur = probe_dur(p)
        h, t = (0, 0)
        if s.trim_frozen:
            h, t = freeze_trims(frame_diffs(p), FPS, still_diff=s.freeze_still_diff, min_s=s.freeze_min_s,
                                min_keep_s=s.min_keep_s)
        t0, t1 = h / FPS, dur - t / FPS
        plan.append({"shot": f"ep02-S{n}", "src": str(p.relative_to(ROOT)).replace("\\", "/"), "src_s": round(dur, 3),
                     "t0": t0, "t1": t1, "trim_head_s": round(t0, 3), "trim_tail_s": round(dur - t1, 3),
                     "len_s": round(t1 - t0, 3), "out_transition": TRANS.get(n), "path": p})
    # 时间线：叠化让后一镜提前 d 秒开始；J-cut 画面硬切、后一镜声音提前 d 秒（用它剪掉的开头里的原声，不够就整体提前）
    starts, t = [], 0.0
    for i, pl in enumerate(plan):
        if i > 0:
            kind, d = TRANS.get(i, ("cut", 0.0))
            t -= d if kind == "dissolve" else 0.0
        starts.append(t)
        t += pl["len_s"]
    total = t
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps={FPS},"
          f"format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709,settb=1/24")
    inputs, fc = [], []
    for i, pl in enumerate(plan):
        inputs += ["-i", str(pl["path"])]
    ef = s.edge_fade_s
    amix = []
    for i, pl in enumerate(plan):
        n = i + 1
        fc.append(f"[{i}:v]trim=start={pl['t0']:.3f}:end={pl['t1']:.3f},setpts=PTS-STARTPTS,{vf}[v{i}]")
        lead = 0.0
        if i > 0 and TRANS.get(i, ("cut", 0))[0] == "jcut":
            lead = TRANS[i][1]
        a0 = max(0.0, pl["t0"] - lead)
        shift = lead                                   # 声音比画面早进 lead 秒
        pl["audio_lead_s"] = round(lead, 3)
        pl["audio_desync_s"] = round(lead - (pl["t0"] - a0), 3)   # 剪掉的开头不够 lead 时，本镜声音整体提前这么多
        alen = pl["t1"] - a0
        fin = TRANS[i][1] if i > 0 and TRANS.get(i, ("cut", 0))[0] in ("dissolve", "jcut") else ef
        fout = TRANS[n][1] if TRANS.get(n, ("cut", 0))[0] == "dissolve" else ef
        pos = max(0.0, starts[i] - shift)
        fc.append(f"[{i}:a]atrim=start={a0:.3f}:end={pl['t1']:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                  f"aformat=channel_layouts=stereo,afade=t=in:d={fin:.3f},afade=t=out:st={max(0, alen - fout):.3f}:d={fout:.3f},"
                  f"adelay={int(pos * 1000)}|{int(pos * 1000)}[a{i}]")
        amix.append(f"[a{i}]")
    # 画面：叠化 = xfade，其余硬切 = concat
    v, acc = "[v0]", plan[0]["len_s"]
    for i in range(1, len(plan)):
        kind, d = TRANS.get(i, ("cut", 0.0))
        if kind == "dissolve":
            fc.append(f"{v}[v{i}]xfade=transition=fade:duration={d}:offset={acc - d:.3f}[x{i}]")
            acc = acc - d + plan[i]["len_s"]
        else:
            fc.append(f"{v}[v{i}]concat=n=2:v=1:a=0,settb=1/24[x{i}]")
            acc += plan[i]["len_s"]
        v = f"[x{i}]"
    fc.append("".join(amix) + f"amix=inputs={len(amix)}:normalize=0:duration=longest,atrim=end={total:.3f},"
              "loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    out = ROOT / a.out
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fc), "-map", v, "-map", "[aout]",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)]
    (work / "ffmpeg_cmd.json").write_text(json.dumps(cmd, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(cmd, check=True)
    # 时间线（review.py 用）：每镜起点与时长
    tl = {"episode": 2, "variant": "planC", "output": a.out, "duration_s": round(probe_dur(out), 3), "fps": FPS,
          "size": [W, H], "settings": s.to_dict() if hasattr(s, "to_dict") else {},
          "note": "方案 C（导演稿 + 写作模型转写 + Ref2VA），PROMPT 合成；不是生产时间线",
          "shots": [{"shot": p["shot"], "index": i + 1, "start_s": round(starts[i], 3), "duration_s": p["len_s"], "file": p["src"],
                     "trim_head_s": p["trim_head_s"], "trim_tail_s": p["trim_tail_s"], "out_transition": p["out_transition"],
                     "audio_lead_s": p.get("audio_lead_s"), "audio_desync_s": p.get("audio_desync_s"),
                     "kind": "video", "h3_audio": True} for i, p in enumerate(plan)]}
    (ROOT / a.out).with_suffix(".timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out, tl["duration_s"])


if __name__ == "__main__":
    main(sys.argv[1:])
