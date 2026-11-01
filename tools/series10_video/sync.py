"""VIDEO10：笔记本端同步——从 gpu33 / gpu36 的 video10_srv 拉 state / log / 打分 JSON / 印样 / ≤2 MB 预览（不拉原片）。

    python tools/series10_video/sync.py            # 拉一次
    python tools/series10_video/sync.py --loop     # 每 120 s 一轮
一条 ssh + tar 流，只拉比上一轮新的文件（留 120 s 重叠）。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID_REL = "data/pipeline/runs/series10_v1/video"
DEST = "/root/work/fredw/video10_srv"
MARK = ROOT / VID_REL / "_sync_marks.json"


def write_atomic(dst: Path, data: bytes) -> None:
    """K-OPS-308：先写 .part 再 os.replace——别的进程（register_takes / episode_report / API）读 state_*.json 时
    不会读到写了一半的 JSON（离线 11-01 10:54 register_takes JSONDecodeError line 280）。
    JSON 先验一遍：服务器端那份本身坏了就不覆盖本地好的（下一轮再拉）"""
    if dst.suffix == ".json":
        try:
            json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            print(time.strftime("%H:%M:%S"), "skip_bad_json", dst.name, flush=True)
            return
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dst)


def pull(host: str, since: float) -> tuple[int, int]:
    rem = (f"cd {DEST} 2>/dev/null || exit 0; find {VID_REL} -maxdepth 3 -type f \\( -name 'state_*.json' -o -name 'vidgen_*.log' "
           f"-o -path '*/scores/*.json' -o -path '*/_thumbs/*.jpg' -o -path '*/_preview/*.mp4' -o -path '*/episodes/*' \\) "
           f"-newermt @{int(since) - 120} 2>/dev/null | tar cf - -T - 2>/dev/null")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, rem], capture_output=True, timeout=1800)
    if not r.stdout:
        return 0, 0
    n = 0
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as t:
        for m in t.getmembers():
            if not m.isfile() or ".." in m.name or not m.name.startswith(VID_REL + "/"):
                continue
            dst = ROOT / m.name
            if dst.suffix == ".mp4" and m.size > 2_100_000:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(dst, t.extractfile(m).read())
            n += 1
    return n, len(r.stdout)


def chosen_clips(host: str) -> list[str]:
    """K-EDT-S10：每镜入选版本（status done / best_effort 的 chosen）的原片相对路径（state 的 file 字段，video/clips/…）"""
    try:
        st = json.loads((ROOT / VID_REL / f"state_{host}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for sid, r in sorted((st.get("shots") or {}).items(), key=lambda kv: (kv[0][:4], int(kv[0].split("-S")[1]))):
        if r.get("status") != "done" or not r.get("chosen"):   # 尽力版不进合成（manifest excluded），不占慢链路
            continue
        x = next((x for x in r.get("renders") or [] if x.get("variant") == r["chosen"] and x.get("file")), None)
        f = (x or {}).get("file") or ""
        if f.startswith(VID_REL + "/clips/") and ".." not in f:
            out.append(f)
    return list(dict.fromkeys(out))   # 按集、镜号排序：先补齐前面的集


CLIPS_PER_ROUND = 4   # 跳板实测约 17 KB/s（11-01 16:50，2.2 MB 用 130 s）：每轮每台最多 4 条，不把 night 一轮拖成几小时


def pull_clips(host: str, limit: int = CLIPS_PER_ROUND) -> int:
    """K-EDT-S10（项目方 11-01“s5等视频出来很糊”）：入选版本的原片（768×1344，约 2–4 MB）必须拉回本机 clips/，
    成片只用原片合成；_preview / 代理只给审片页。只拉本机没有的；JSON 之外不验内容，大小与远端一致才落盘"""
    want = [f for f in chosen_clips(host) if not (ROOT / f).is_file()][:limit]
    if not want:
        return 0
    rem = f"cd {DEST} 2>/dev/null || exit 0; tar cf - --ignore-failed-read {' '.join(want)} 2>/dev/null"
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, rem], capture_output=True, timeout=3600)
    n = 0
    if r.stdout:
        with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as t:
            for m in t.getmembers():
                if not m.isfile() or ".." in m.name or m.name not in want:
                    continue
                data = t.extractfile(m).read()
                if len(data) != m.size:
                    continue
                dst = ROOT / m.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(dst, data)
                n += 1
    return n


def once(marks):
    for h in ("gpu33", "gpu36"):
        t = time.time()
        try:
            n, b = pull(h, marks.get(h, 0))
            marks[h] = t
            print(time.strftime("%H:%M:%S"), h, f"{n} 个文件 {b / 1e3:.0f} KB", flush=True)
        except Exception as e:  # noqa: BLE001
            print(time.strftime("%H:%M:%S"), h, "sync_err", str(e)[:160], flush=True)
        try:
            # 总调度 G0（11-01 ~17:00）：原片不拉回笔记本（跳板约 17 KB/s），合成改在服务器上做；
            # 只有 night_control.json 显式 "pull_clips": true 时才拉（应急用）
            ctl = {}
            try:
                ctl = json.loads((ROOT / VID_REL / "night_control.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            c = pull_clips(h) if ctl.get("pull_clips") else 0
            if c:
                print(time.strftime("%H:%M:%S"), h, f"原片 {c} 条", flush=True)
        except Exception as e:  # noqa: BLE001
            print(time.strftime("%H:%M:%S"), h, "clip_err", str(e)[:160], flush=True)
    MARK.parent.mkdir(parents=True, exist_ok=True)
    MARK.write_text(json.dumps(marks), encoding="utf-8")


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    marks = json.loads(MARK.read_text(encoding="utf-8")) if MARK.exists() else {}
    while True:
        once(marks)
        if "--loop" not in argv:
            return 0
        time.sleep(120)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
