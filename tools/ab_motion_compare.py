"""
MOT 对照结果的可看文件（fredw-92，2026-10-31）：并排 mp4（原速，带标签）+ 腿部慢放并排 + 腿部逐帧条带。

用法：python tools/ab_motion_compare.py OUT_STEM label1=path1 label2=path2 ...
      [--crop W:H:X:Y]（腿部区域，默认 560:560:0:784，S1 的脚） [--range A:B]（腿部条带帧段，默认 64:96）
输出：OUT_STEM_sbs.mp4（原速并排，每格 384×672）、OUT_STEM_legs_halfspeed.mp4（腿部 0.5× 慢放并排）、
      OUT_STEM_legs_strip.jpg（每行一个变体，帧段内每 2 帧一格）
标签只用 ASCII（drawtext 字体）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FONT = "C\\:/Windows/Fonts/arial.ttf"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise SystemExit(r.stderr.decode("utf-8", "replace")[-800:])


def main(a):
    crop, rng = "560:560:0:784", "64:96"
    if "--crop" in a:
        i = a.index("--crop")
        crop = a[i + 1]
        del a[i:i + 2]
    if "--range" in a:
        i = a.index("--range")
        rng = a[i + 1]
        del a[i:i + 2]
    stem = a[0]
    items = [x.split("=", 1) for x in a[1:]]
    n = len(items)
    ins = sum((["-i", p] for _, p in items), [])
    # 1) 原速并排
    fl = []
    for i, (lab, _) in enumerate(items):
        fl.append(f"[{i}:v]fps=24,scale=384:672,drawtext=fontfile='{FONT}':text='{lab}':x=8:y=8:fontsize=22:"
                  f"fontcolor=white:box=1:boxcolor=black@0.6[v{i}]")
    fl.append("".join(f"[v{i}]" for i in range(n)) + f"hstack=inputs={n}[out]")
    run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[out]", "-map", "0:a?",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", f"{stem}_sbs.mp4"])
    # 2) 腿部慢放并排（0.5×，无声）
    fl = []
    for i, (lab, _) in enumerate(items):
        fl.append(f"[{i}:v]crop={crop},scale=420:420,setpts=2*PTS,drawtext=fontfile='{FONT}':text='{lab} (0.5x)':"
                  f"x=8:y=8:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6[v{i}]")
    fl.append("".join(f"[v{i}]" for i in range(n)) + f"hstack=inputs={n}[out]")
    run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[out]", "-r", "24",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", f"{stem}_legs_halfspeed.mp4"])
    # 3) 腿部逐帧条带（每行一个变体）
    lo, hi = (int(x) for x in rng.split(":"))
    cols = (hi - lo) // 2 + 1
    fl = []
    for i, (lab, _) in enumerate(items):
        fl.append(f"[{i}:v]select='between(n\\,{lo}\\,{hi})*not(mod(n-{lo}\\,2))',crop={crop},scale=200:200,"
                  f"drawtext=fontfile='{FONT}':text='{lab}':x=4:y=4:fontsize=14:fontcolor=white:"
                  f"box=1:boxcolor=black@0.6,tile={cols}x1[r{i}]")
    fl.append("".join(f"[r{i}]" for i in range(n)) + f"vstack=inputs={n}[out]")
    run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[out]", "-frames:v", "1",
         f"{stem}_legs_strip.jpg"])
    print("ok", stem)


if __name__ == "__main__":
    main(sys.argv[1:])
