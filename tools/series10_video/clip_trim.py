"""W46（总调度 05:1x 定）：进整集合成前，单镜视频统一裁到 ≤ 6.0 s（C-08）——尾部裁、首帧保留。
gpu36 实测 ep01-S2 / S3 = 79 帧 @12 fps = 6.58 s（build_jobs 帧数向上对齐到 17k+5 所致，根因已在 ns_recipes.compiler.cap_frames_c08 修；
已经出好的片在这里兜底）。产物 = 同目录 <名>_le6.mp4（已有且比原片新 → 直接用），原片不动。

    from clip_trim import trim_le   # trim_le(Path) → Path（不超的原样返回）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MAX_S = 6.0
TOL_S = 0.02


def duration(p: Path) -> float:
    exe = shutil.which("ffprobe") or "ffprobe"
    try:
        r = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)],   # 服务器 ffprobe 壳认得的写法
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"clip_trim: ffprobe 跑不了 {p}: {e}", file=sys.stderr)
        return 0.0                                   # 读不到时长 = 不裁（原样）；登记口 register_takes 对 0 时长失败关闭
    try:
        return float((json.loads(r.stdout or "{}").get("format") or {}).get("duration") or 0)
    except ValueError as e:
        print(f"clip_trim: ffprobe 输出解析不了 {p}: {e}", file=sys.stderr)
        return 0.0


def trimmed_path(src: Path, max_s: float = MAX_S) -> Path:
    return src.with_name(f"{src.stem}_le{int(max_s)}.mp4")


def trim_le(src: Path, max_s: float = MAX_S, run=subprocess.run, dur=duration) -> Path:
    """超过 max_s 的片裁成 max_s（从 0 开始，保留首帧；视频重编码 x264 crf 14 保画质，音轨 aac）；读不到时长 = 原样返回"""
    src = Path(src)
    d = dur(src)
    if not d or d <= max_s + TOL_S:
        return src
    dst = trimmed_path(src, max_s)
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    tmp = dst.with_name(dst.stem + ".part.mp4")
    ff = shutil.which("ffmpeg") or "ffmpeg"
    r = run([ff, "-v", "error", "-y", "-i", str(src), "-t", f"{max_s:.3f}", "-map", "0:v:0", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(tmp)], capture_output=True, timeout=600)
    if getattr(r, "returncode", 1) or not tmp.is_file():
        if tmp.is_file():
            tmp.replace(tmp.with_suffix(".failed"))      # 不删：留着查
        raise RuntimeError(f"裁到 {max_s}s 失败：{src.name}：{(getattr(r, 'stderr', b'') or b'')[-200:]!r}")
    os.replace(tmp, dst)
    return dst
