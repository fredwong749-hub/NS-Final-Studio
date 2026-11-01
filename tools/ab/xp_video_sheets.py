"""H3 实验的对照材料：并排 mp4（带编号）、抽帧拼图（0/25/50/75/100%）、params.md（全参数 + 耗时 + 首尾帧 PSNR，仅客观数）。
用法：python tools/ab/xp_video_sheets.py <实验目录名> [<实验目录名> ...] [--with X1_turbo_versions:A_fl2v_t8_v1.1_s1.0_8st]"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402
from ns_post.ffmpeg import FFmpeg  # noqa: E402
from ns_render import h3_video as HV  # noqa: E402
from ns_render import pipeline as P   # noqa: E402

FF = FFmpeg.discover()
TW, TH = 288, 504
FONT = "C\\:/Windows/Fonts/arial.ttf"


def nframes(mp4: Path) -> int:
    out = subprocess.run([FF.ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
    return int(out.stdout.strip().split(",")[0])


def frames_at(mp4: Path, idx: list[int], tmp: Path) -> list[Path]:
    tmp.mkdir(parents=True, exist_ok=True)
    sel = "+".join(f"eq(n\\,{i})" for i in idx)
    for f in tmp.glob(f"{mp4.stem}_*.png"):
        f.unlink()
    FF.run(["-i", mp4, "-vf", f"select='{sel}'", "-fps_mode", "passthrough", tmp / f"{mp4.stem}_%02d.png"])
    return sorted(tmp.glob(f"{mp4.stem}_*.png"))


def psnr(a, b) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    mse = float(((a - b) ** 2).mean())
    return round(10 * np.log10(255 ** 2 / mse), 2) if mse > 0 else 99.0


def build(exp_dirs: list[str], extra: list[tuple[str, str]], out_name: str):
    from PIL import Image
    recs = []
    for exp, jid in extra:
        r = json.loads((X.AB / exp / "results.json").read_text(encoding="utf-8")).get(jid)
        if r and r.get("file"):
            recs.append((exp, r))
    for exp in exp_dirs:
        d = json.loads((X.AB / exp / "results.json").read_text(encoding="utf-8"))
        recs += [(exp, r) for r in d.values() if r.get("file")]
    out = X.AB / exp_dirs[0]
    fr = HV.locked_frames("ep02-S2")
    kf_first = Image.open(HV.keyframe_file(P.DATA / fr["first"]["file"])).convert("RGB")
    kf_last = Image.open(HV.keyframe_file(P.DATA / fr["last"]["file"])).convert("RGB")
    tiles = [(kf_first, "KF", f"锁定首帧 {fr['first']['file']}"), (kf_last, "KL", f"锁定尾帧 {fr['last']['file']}")]
    tiles += [(Image.new("RGB", (768, 1344), (24, 24, 24)), "", "")] * 3
    rows_md = []
    for i, (exp, r) in enumerate(recs):
        tag = r['id'].split('_')[0]
        mp4 = X.AB / exp / r["file"]
        n = nframes(mp4)
        idx = [0, n // 4, n // 2, 3 * n // 4, n - 1]
        fs = frames_at(mp4, idx, X.AB / "_tmp_frames")
        ims = [Image.open(f).convert("RGB") for f in fs]
        p0, p1 = psnr(ims[0], kf_first), psnr(ims[-1], kf_last)
        r["_tag"], r["_psnr"], r["_n"] = tag, (p0, p1), n
        for j, (im, k) in enumerate(zip(ims, idx)):
            tiles.append((im, tag if j == 0 else "", f"{r['id']}\n帧 {k}/{n - 1}" + (f"\n{r['label']}" if j == 0 else "")))
        p = r["params"]
        rows_md.append(f"| {tag} | {exp}/{r['file']} | {r['label']} | {p['unet']} | "
                       f"{'; '.join(f'{a} @{b}' for a, b in p['loras']) or '无'} | {p['steps']} | {p['shift'][0]}/{p['shift'][1]} | "
                       f"{p['mode']} | {p.get('card') or '—'} | {p['seed']} | {p['frames']} | {r['exec_s']} | {r.get('vram_peak_gb')} | "
                       f"{r['lane']} | {p0} | {p1} |")
    X.sheet(tiles, out / f"{out_name}_frame_sheet.jpg", 216, 378, cols=5, label_h=120, max_lines=5,
            title=f"ep02-S2 · {' + '.join(exp_dirs)} · 每行一个变体，帧 0 / 25% / 50% / 75% / 末帧；第一行 = 锁定首尾帧")
    # 并排 mp4（左上角编号 = params.md 的字母；无声）
    cols = min(4, len(recs))
    inputs, filt = [], []
    for i, (exp, r) in enumerate(recs):
        inputs += ["-i", X.AB / exp / r["file"]]
        filt.append(f"[{i}:v]scale={TW}:{TH},drawtext=fontfile='{FONT}':text='{r['_tag']} {r['id'][:28]}':"
                    f"x=6:y=6:fontsize=14:fontcolor=yellow:box=1:boxcolor=black@0.6[v{i}]")
    lay = "|".join(f"{(i % cols) * TW}_{(i // cols) * TH}" for i in range(len(recs)))
    filt.append("".join(f"[v{i}]" for i in range(len(recs))) +
                f"xstack=inputs={len(recs)}:layout={lay}:fill=black:shortest=0[o]" if len(recs) > 1 else "[v0]null[o]")
    FF.run([*inputs, "-filter_complex", ";".join(filt), "-map", "[o]", "-an", "-c:v", "libx264", "-crf", "20",
            "-pix_fmt", "yuv420p", out / f"{out_name}_side_by_side.mp4"])
    md = [f"# {out_name}：ep02-S2 H3 对照（只列参数和客观数，不评优劣，由项目方选）", "",
          f"- 镜头 ep02-S2，6 s → {recs[0][1]['params']['frames']} 帧 @24fps，768×1344，种子 {recs[0][1]['params']['seed']}（video_001 同种子）",
          f"- 首帧 {fr['first']['file']}（sha {fr['first']['sha']}），尾帧 {fr['last']['file']}（sha {fr['last']['sha']}）",
          f"- 提示词：剧本 H3 提示词原样（来源 {recs[0][1]['params']['prompt_source']}），所有变体同一份；X4 也用同一份（未改写为 Ref2VA 六段式——内容由写作模型负责）",
          f"- 文本编码器 {recs[0][1]['params']['clip']}；视频 VAE {recs[0][1]['params']['video_vae']}；音频 VAE {recs[0][1]['params']['audio_vae']}；euler / simple；BasicGuider（cfg 1）",
          "- 材料：`*_side_by_side.mp4`（无声，左上角编号对应下表）、`*_frame_sheet.jpg`、各变体原 mp4（含声）",
          "- PSNR = 片子第 0 帧 / 末帧 对 锁定首/尾帧（同样 center-crop 到 768×1344）的 PSNR(dB)，只是客观数",
          "",
          "| 编号 | 文件 | 说明 | DiT | LoRA | 步数 | shift 视/音 | 条件 | 角色卡 | 种子 | 帧 | GPU 秒 | 显存峰值 GB | 道 | PSNR 首 | PSNR 尾 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|", *rows_md]
    for exp in exp_dirs:
        d = json.loads((X.AB / exp / "results.json").read_text(encoding="utf-8"))
        bad = [r for r in d.values() if not r.get("file")]
        if bad:
            md += ["", f"## {exp} 未出片的变体", *[f"- {r['id']}：{r.get('error') or r.get('skipped')}" for r in bad]]
    (out / f"{out_name}_params.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("ok", out)


if __name__ == "__main__":
    args = sys.argv[1:]
    extra = []
    if "--with" in args:
        i = args.index("--with")
        extra = [tuple(x.split(":")) for x in args[i + 1].split(",")]
        args = args[:i] + args[i + 2:]
    build(args, extra, args[0])
