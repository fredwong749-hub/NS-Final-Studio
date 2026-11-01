"""VIDEO10 预览成片放大（项目方 11-01“s5等视频出来很糊”“估计你的参数坏了”；K-EDT-V10）。

原片（video/clips/epNN/<镜>__<变体>_s<seed>.mp4，768×1344 级）→ 同目录 <名>_sr1080.mp4（1080 宽，9:16 交合成器裁切）。
引擎顺序：
  1. SeedVR2（gpu33 scripts/upscale_4k.py shot --set sr_short=1080，GPU 空闲时）——结果文件放到同名 _sr1080.mp4 即被采用；
     本脚本 --seedvr2-result <本地 mp4> 把取回的 SeedVR2 中间片转成 _sr1080（不改调色）。
  2. 兜底：lanczos 放大 + 轻锐化（unsharp 5:5:0.6 只作用亮度），CRF 16。
SOP §12 原来是“4K 只做已批准片”；项目方 11-01 原话后，预览成片也至少过一遍放大（docs/SOP_production.md §12 已同步）。

    python tools/series10_video/upscale_preview.py ep01            # 该集所有入选原片做兜底放大（已有 _sr1080 跳过）
    python tools/series10_video/upscale_preview.py --clip <原片> --seedvr2-result <SeedVR2 输出>
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID = ROOT / "data/pipeline/runs/series10_v1/video"
UNSHARP = "unsharp=5:5:0.6:5:5:0.0"


def ffmpeg() -> str:
    """本机 / 服务器通用（总调度 G0 11-01：合成改在服务器上做，原片在服务器本地）：NS_FFMPEG > PATH > 两台服务器已知位置"""
    import os
    for c in (os.environ.get("NS_FFMPEG"), shutil.which("ffmpeg"), "/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin/ffmpeg",
              "/root/work/fredw/tools_bin/ffmpeg"):
        if c and Path(c).exists():
            return c
    return "ffmpeg"


def out_for(clip: Path) -> Path:
    return clip.with_name(clip.stem + "_sr1080.mp4")


def lanczos(clip: Path, dst: Path) -> float:
    t = time.time()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(clip), "-vf", f"scale=1080:-2:flags=lanczos,{UNSHARP}",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "copy", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(r.stderr[-400:])
    tmp.replace(dst)
    return round(time.time() - t, 1)


def from_seedvr2(clip: Path, result: Path, dst: Path) -> float:
    """SeedVR2 中间片 → 1080 宽（不再锐化，SeedVR2 自己出细节），音轨取原片"""
    t = time.time()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(result), "-i", str(clip), "-map", "0:v:0", "-map", "1:a?",
                        "-vf", "scale=1080:-2:flags=lanczos", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(r.stderr[-400:])
    tmp.replace(dst)
    return round(time.time() - t, 1)


def episode(ep: int) -> list[dict]:
    man = json.loads((VID / "episodes" / f"ep{ep:02d}" / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for s in man.get("shots", []):
        if not s.get("proxy") or not s.get("source"):
            continue
        clip = ROOT / s["source"]
        if not clip.is_file():
            rows.append({"shot": s["shot"], "status": "no_source"})
            continue
        dst = out_for(clip)
        if dst.is_file():
            rows.append({"shot": s["shot"], "status": "exists", "file": str(dst.relative_to(ROOT))})
            continue
        secs = lanczos(clip, dst)
        rows.append({"shot": s["shot"], "status": "lanczos_unsharp", "secs": secs, "file": str(dst.relative_to(ROOT))})
    return rows


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if "--clip" in argv:
        clip = Path(argv[argv.index("--clip") + 1])
        res = Path(argv[argv.index("--seedvr2-result") + 1])
        print(json.dumps({"file": str(out_for(clip)), "secs": from_seedvr2(clip, res, out_for(clip))}, ensure_ascii=False))
        return 0
    ep = int(argv[0].lower().lstrip("ep"))
    print(json.dumps(episode(ep), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
