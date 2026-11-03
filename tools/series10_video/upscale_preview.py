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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ctx as RC  # noqa: E402

VID = RC.vid_dir(RC.resolve())          # MERGE-VID-O：按剧（night 传 NS_RUN；服务器侧必须显式给）
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


POLICY = ROOT / "config/pipeline/video_policy.json"


def dejudder_cfg() -> dict:
    """VIDEO-RCA r1（11-01 19:0x）：Pika 也有 4 帧一顿（同首帧 4 条里 3 条 J4 1.23–1.40、z 4.5–10.8）→ 合成前复用 K-LOOP-004 的
    tools/dejudder.py。参数在 config/pipeline/video_policy.json dejudder（VIDEO-RCA 量化后可改），缺省 = iterate_loop R-J4 的门槛"""
    try:
        d = json.loads(POLICY.read_text(encoding="utf-8")).get("dejudder") or {}
    except (OSError, ValueError):
        d = {}
    return {"enabled": d.get("enabled", True), "recipes": d.get("recipes", ["i2va_pika_flex"]),
            "j4_gt": float(d.get("j4_gt", 1.25)), "j4_z_ge": float(d.get("j4_z_ge", 3.0)), "always": bool(d.get("always", False))}


def needs_dejudder(s: dict, cfg: dict | None = None) -> tuple[bool, str]:
    """→ (要不要去抖, 原因)。只看这一镜入选版本的打分（video/scores/<镜>__<变体>.json 的 J4 / J4_z）"""
    cfg = cfg or dejudder_cfg()
    if not cfg["enabled"] or s.get("recipe") not in cfg["recipes"]:
        return False, "不在去抖配方范围"
    if cfg["always"]:
        return True, "always"
    sc = {}
    try:
        sc = json.loads((VID / "scores" / f"{s['shot']}__{s.get('chosen')}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, "没有打分（未测 ≠ 通过）→ 去抖"
    j4, z = sc.get("J4"), sc.get("J4_z")
    if j4 is None or z is None:
        return True, "打分缺 J4 → 去抖"
    hit = float(j4) > cfg["j4_gt"] and float(z) >= cfg["j4_z_ge"]
    return hit, f"J4 {j4} z {z}（门槛 >{cfg['j4_gt']} 且 z≥{cfg['j4_z_ge']}）"


def _ff_env() -> dict:
    import os
    ff = Path(ffmpeg())
    return {**os.environ, "PATH": (str(ff.parent) + os.pathsep if ff.parent != Path(".") else "") + os.environ.get("PATH", "")}


def dejudder_for(clip: Path) -> Path:
    return clip.with_name(clip.stem + "_dj.mp4")


def run_dejudder(clip: Path) -> Path:
    """K-LOOP-004 原样：tools/dejudder.py in out（bt709、音轨原样）；先写 .part 再改名"""
    dst = dejudder_for(clip)
    if dst.is_file():
        return dst
    tmp = dst.with_name(dst.stem + ".part.mp4")
    r = subprocess.run([sys.executable, str(ROOT / "tools/dejudder.py"), str(clip), str(tmp)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT), env=_ff_env())   # dejudder.py 调裸 ffmpeg：把找到的 ffmpeg 目录放进 PATH（服务器上不在默认 PATH）
    if r.returncode or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError("dejudder 失败：" + (r.stderr or r.stdout)[-300:])
    tmp.replace(dst)
    return dst


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
        dj, why = needs_dejudder(s)
        if dst.is_file() and (not dj or dejudder_for(clip).is_file()):
            rows.append({"shot": s["shot"], "status": "exists", "file": str(dst.relative_to(ROOT)), "dejudder": dj})
            continue
        src = clip
        if dj:                              # 链路：原片 → 去抖（_dj）→ 放大（_sr1080）；放大版从去抖片做
            try:
                src = run_dejudder(clip)
            except RuntimeError as e:
                rows.append({"shot": s["shot"], "status": "dejudder_failed", "why": str(e)[:200]})
                continue
        secs = lanczos(src, dst)
        rows.append({"shot": s["shot"], "status": "lanczos_unsharp", "secs": secs, "file": str(dst.relative_to(ROOT)),
                     "dejudder": dj, "dejudder_why": why})
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
