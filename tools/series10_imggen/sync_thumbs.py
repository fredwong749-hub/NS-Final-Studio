"""INFRA（2026-10-31）：笔记本端同步——从 gpu33 / gpu36 的服务器编排器拉 state 和缩略图（不拉 PNG 原图）。

服务器目录（server_deploy.py 部署的仓库镜像）：/root/work/fredw/imggen_srv/data/pipeline/runs/series10_v1/images/
  state_gpu33.json / state_gpu36.json   各机编排器的状态（IMGGEN 约定的文件名）
  _thumbs/*.jpg                          审阅页缩略图（几十 KB）
拉到本机同样的相对路径；每轮只拉比上一轮新的缩略图（一条 ssh、tar 流）。原图需要时用 --full <相对路径…> 单独拉。

    python tools/series10_imggen/sync_thumbs.py            # 常驻，每 60 s 一轮
    python tools/series10_imggen/sync_thumbs.py --once
    python tools/series10_imggen/sync_thumbs.py --full data/pipeline/runs/series10_v1/images/frames/ep01/ep01-S1_s20261201.png@gpu36
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMG_REL = "data/pipeline/runs/series10_v1/images"
DEST = "/root/work/fredw/imggen_srv"
HOSTS = ("gpu33", "gpu36")
MARK = ROOT / IMG_REL / "_sync_marks.json"


def pull(host: str, since: float) -> tuple[int, int]:
    """返回 (文件数, 字节数)。since = 上一轮开始时的远端 epoch 秒（留 120 s 重叠，重复覆盖无害）。"""
    rem = (f"cd {DEST} 2>/dev/null || exit 0; "
           f"{{ ls {IMG_REL}/state_{host}.json 2>/dev/null; "
           f"find {IMG_REL}/_thumbs -type f -name '*.jpg' -newermt @{int(since) - 120} 2>/dev/null; }} | tar cf - -T - 2>/dev/null")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, rem], capture_output=True, timeout=600)
    if not r.stdout:
        return 0, 0
    n = 0
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as t:
        for m in t.getmembers():
            if not m.isfile() or ".." in m.name or not m.name.startswith(IMG_REL + "/"):
                continue
            dst = ROOT / m.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".part")
            tmp.write_bytes(t.extractfile(m).read())
            for _ in range(3):
                try:
                    tmp.replace(dst)
                    break
                except PermissionError:
                    time.sleep(0.2)
            n += 1
    return n, len(r.stdout)


def full(spec: str):
    rel, host = spec.rsplit("@", 1)
    dst = ROOT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"{host}:{DEST}/{rel}", str(dst)], capture_output=True, text=True)
    print("ok" if r.returncode == 0 else r.stderr.strip(), rel)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["--full"]:
        for s in argv[1:]:
            full(s)
        return 0
    once = "--once" in argv
    marks = json.loads(MARK.read_text(encoding="utf-8")) if MARK.exists() else {}
    while True:
        for h in HOSTS:
            t = time.time()
            try:
                n, b = pull(h, marks.get(h, 0))
                marks[h] = t
                if n:
                    print(time.strftime("%H:%M:%S"), h, f"{n} 个文件 {b / 1e3:.0f} KB", flush=True)
            except Exception as e:  # noqa: BLE001
                print(time.strftime("%H:%M:%S"), h, "sync_err", str(e)[:120], flush=True)
        MARK.parent.mkdir(parents=True, exist_ok=True)
        MARK.write_text(json.dumps(marks), encoding="utf-8")
        if once:
            return 0
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
