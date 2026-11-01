"""
LAB：按道串行跑实验（每道同一时刻只占 1 个：等该道 ComfyUI 队列空了才提交下一条），V2 / 生产优先。
计划文件 JSON：{"lanes": {"<comfy url>": [["<name>", "<script>", arg, ...], ...]}}
每条命令用 .venv python 运行（ref2va_run.py / fl2va_direct.py），日志 data/ab/lab/q_<name>.log。
用法：.venv/Scripts/python.exe tools/lab_ep02/lab_queue.py plan.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
LOG = ROOT / "data" / "ab" / "lab"


def busy(url: str) -> bool | None:
    try:
        with urllib.request.urlopen(url + "/queue", timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        return bool(d["queue_running"] or d["queue_pending"])
    except Exception:  # noqa: BLE001
        return None


def lane_worker(url: str, jobs: list):
    for job in jobs:
        name, script, *args = job
        free = 0
        while free < 2:            # 连续两次（间隔 30 s）看到空队列才提交，给 V2 / 生产让道
            b = busy(url)
            free = free + 1 if b is False else 0
            if free < 2:
                time.sleep(30)
        print(time.strftime("%H:%M:%S"), "start", name, url, flush=True)
        with open(LOG / f"q_{name}.log", "w", encoding="utf-8") as f:
            rc = subprocess.call([PY, script, name, url, *map(str, args)], stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
        print(time.strftime("%H:%M:%S"), "end", name, "rc", rc, flush=True)


def main(plan_path):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    ts = [threading.Thread(target=lane_worker, args=(u, j)) for u, j in plan["lanes"].items()]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


if __name__ == "__main__":
    main(sys.argv[1])
