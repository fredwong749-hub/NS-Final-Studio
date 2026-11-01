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
    r = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
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


def main(argv):
    path = argv[-1]
    streams, fmt = info(path)
    if "stream=r_frame_rate" in argv:
        v = next((s for s in streams if s["codec_type"] == "video"), None)
        print(v["r_frame_rate"] if v else "")
        return 0
    if "stream=duration" in argv or "format=duration" in argv:
        print(fmt.get("duration", ""))
        return 0
    out = {}
    if "-show_streams" in argv:
        out["streams"] = streams
    if "-show_format" in argv:
        out["format"] = fmt
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
