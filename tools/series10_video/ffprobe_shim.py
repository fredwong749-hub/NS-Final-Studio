#!/usr/bin/env python3
"""VIDEO10：gpu36 没有 ffprobe（只有 imageio_ffmpeg 自带的静态 ffmpeg 7.0.2），打分器只用到 ffprobe 的两种调用：
  -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 <f>   → "24/1"
  -show_streams -show_format -of json <f>                                 → {"streams": [...], "format": {...}}
这里用 `ffmpeg -i` 的 stderr 解析出同样的字段（codec_type / width / height / r_frame_rate / color_space / duration）。
部署到 /root/work/fredw/tools_bin/ffprobe（server_deploy.py），PATH 里放在前面。
"""
import json
import os
import re
import subprocess
import sys

FF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg")


def info(path):
    r = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace", timeout=120)
    err = r.stderr
    streams = []
    for m in re.finditer(r"Stream #\d+:(\d+)[^:]*: (Video|Audio): (\w+)([^\n]*)", err):
        idx, kind, codec, rest = int(m.group(1)), m.group(2).lower(), m.group(3), m.group(4)
        s = {"index": idx, "codec_type": kind, "codec_name": codec}
        if kind == "video":
            wh = re.search(r"(\d{2,5})x(\d{2,5})", rest)
            if wh:
                s["width"], s["height"] = int(wh.group(1)), int(wh.group(2))
            fps = re.search(r"([\d.]+) fps", rest)
            f = float(fps.group(1)) if fps else 24.0
            s["r_frame_rate"] = f"{int(round(f * 1000))}/1000" if abs(f - round(f)) > 1e-6 else f"{int(round(f))}/1"
            s["avg_frame_rate"] = s["r_frame_rate"]
            cs = re.search(r"\(([^)]*)\)", rest)
            if cs:
                parts = [x.strip() for x in cs.group(1).split(",")]
                for x in parts:
                    if x in ("bt709", "smpte170m", "bt470bg", "bt2020nc"):
                        s["color_space"] = x
        if kind == "audio":
            sr = re.search(r"(\d+) Hz", rest)
            if sr:
                s["sample_rate"] = sr.group(1)
        streams.append(s)
    fmt = {"filename": path}
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if d:
        fmt["duration"] = str(int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)))
    return streams, fmt


REAL_CANDIDATES = [os.environ.get("NS_REAL_FFPROBE") or "", "/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin/ffprobe"]


def real_ffprobe() -> str | None:
    """W46：本机有能跑的真 ffprobe（gpu33 的 comfy env 有 9.0.2；anaconda pkgs 那个缺 libplacebo 跑不起）→ 用真的。
    gpu36 没有 → None（走下面的仿真）"""
    for c in REAL_CANDIDATES:
        if c and os.path.isfile(c) and os.access(c, os.X_OK) and os.path.realpath(c) != os.path.realpath(__file__):
            try:
                if subprocess.run([c, "-version"], capture_output=True, timeout=20).returncode == 0:
                    return c
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


def count_frames(path, stream="v:0"):
    """-count_packets / -count_frames：ffmpeg 解码到 null，取 -progress 最后的 frame= 计数（imageio 的 ffmpeg 7.0.2 流拷贝不报 frame=）"""
    r = subprocess.run([FF, "-hide_banner", "-nostats", "-progress", "pipe:1", "-i", path, "-map", f"0:{stream}", "-an",
                        "-f", "null", "-"], capture_output=True, text=True, errors="replace", timeout=300)
    n = re.findall(r"^frame=(\d+)", r.stdout or "", re.M)
    return int(n[-1]) if n else 0


def _arg(argv, k, d=None):
    return argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else d


def emulate(argv):
    """W46：原壳只认两种写法（别的输出 {}：night 合成 count_frames、dejudder 宽高都栽在这）。现在通用仿真：
    -select_streams v:0 / a:0、-show_entries section=k1,k2[:section=k3]、-count_packets / -count_frames（nb_read_packets /
    nb_read_frames / nb_frames）、-show_streams / -show_format、-of json / csv=p=0 / default=nw=1:nk=1 / flat"""
    path = argv[-1]
    streams, fmt = info(path)
    sel = _arg(argv, "-select_streams")
    if sel:
        kind = {"v": "video", "a": "audio"}.get(sel.split(":")[0])
        idx = int(sel.split(":")[1]) if ":" in sel and sel.split(":")[1].isdigit() else None
        cand = [s for s in streams if s["codec_type"] == kind]
        streams = cand[idx:idx + 1] if idx is not None else cand
    if "-count_packets" in argv or "-count_frames" in argv:
        for s in streams:
            if s["codec_type"] == "video":
                n = count_frames(path, "v:0")
                s["nb_read_packets"] = s["nb_read_frames"] = s["nb_frames"] = str(n)
    ent = _arg(argv, "-show_entries")
    want = {}
    if ent:
        for part in ent.split(":"):
            sec, _, keys = part.partition("=")
            want[sec] = [k for k in keys.split(",") if k] if keys else None
    else:
        if "-show_streams" in argv:
            want["stream"] = None
        if "-show_format" in argv:
            want["format"] = None

    def pick(d, keys):
        return dict(d) if keys is None else {k: d[k] for k in keys if k in d}
    rows_s = [pick(s, want["stream"]) for s in streams] if "stream" in want else []
    row_f = pick(fmt, want["format"]) if "format" in want else None
    of = _arg(argv, "-of") or _arg(argv, "-print_format") or "default"
    if of.startswith("json"):
        out = {}
        if "stream" in want:
            out["streams"] = rows_s
        if row_f is not None:
            out["format"] = row_f
        print(json.dumps(out))
        return 0
    lines = []
    for r in rows_s + ([row_f] if row_f is not None else []):
        keys = list(r)
        if of.startswith("csv"):
            lines.append(",".join(str(r[k]) for k in keys))
        elif "nk=1" in of or "noprint_wrappers=1:nokey=1" in of:
            lines += [str(r[k]) for k in keys]
        else:
            lines += [f"{k}={r[k]}" for k in keys]
    print("\n".join(lines))
    return 0


def main(argv):
    real = None if os.environ.get("NS_FFPROBE_EMULATE") == "1" else real_ffprobe()
    if real:
        os.execv(real, [real, *argv])
    return emulate(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
