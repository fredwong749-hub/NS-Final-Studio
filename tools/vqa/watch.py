#!/usr/bin/env python3
"""VQA 离线看图复核 watcher（总调度 11-01：“包裹检查出图的模型部署到gpu机器去”）。只记录，不重派。

在 gpu33 / gpu36 的 offline_20261101/repo 里独立运行（nohup，PID → run/vqa.pid，日志 → logs/vqa.out）：
  每 60 s 扫 data/renders/ep*/S*/takes.json，取冻结（FREEZE_TS）之后新出的首帧 / 尾帧（stage image / last），
  逐张交本机本地看图服务（127.0.0.1:8870，tools/vqa/server.py；图片不出本机）→
  data/vqa/verdicts/<key>.parsed.json + data/vqa/index.json（postflight Q9 的 cached_for 查这里）→
  规则裁判（judge.rule_fallback，离线不调外部 API）给出修改建议 → data/vqa/records.jsonl 一行（R11-10 的“建议”，不自动重派）。
不改 takes.json（共享文件，走 API / register_takes 才能写）；回来后由总调度决定是否把记录并进 take.params.vqa_rounds。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))
from ns_agent.vqa import client, contract as VQ, judge, rubric  # noqa: E402

OFF = Path(os.environ.get("VQA_OFF", "/root/work/fredw/offline_20261101"))
REC = ROOT / "data" / "vqa" / "records.jsonl"
DONE = ROOT / "data" / "vqa" / "watch_done.json"
HB = Path("/root/work/fredw/gpu_heartbeats/VQA-watch.json")
HOST = os.environ.get("OFFLINE_SELF") or os.uname().nodename


def log(*a):
    print(time.strftime("%m-%d %H:%M:%S"), *a, flush=True)


def freeze_ts() -> float:
    try:
        return float((OFF / "FREEZE_TS").read_text().strip())
    except (OSError, ValueError):
        return 0.0


def pending(done: set, since: float) -> list[tuple[str, dict]]:
    out = []
    for f in sorted((ROOT / "data" / "renders").glob("ep*/S*/takes.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shot = f"{f.parts[-3]}-{f.parts[-2]}"
        for x in (t if isinstance(t, list) else t.get("takes") or []):
            if x.get("stage") not in ("image", "last") or not x.get("file"):
                continue
            p = ROOT / "data" / x["file"]
            if str(p) in done or not p.exists() or p.stat().st_mtime < since:
                continue
            out.append((shot, x))
    return out


def heartbeat(label: str, n_done: int, n_left: int):
    try:
        HB.parent.mkdir(parents=True, exist_ok=True)
        HB.write_text(json.dumps({"agent": "VQA", "label": label, "kind": "other", "server": HOST, "gpu": None,
                                  "step": n_done, "steps": n_done + n_left, "state": "running", "ttl": 300,
                                  "pid": os.getpid(), "updated": time.time()}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def main():
    since = freeze_ts()
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    log(f"VQA watch on {HOST}, repo {ROOT}, since FREEZE_TS {since}")
    while not (OFF / "STOP").exists():
        todo = pending(done, since)
        for i, (shot, x) in enumerate(todo):
            p = ROOT / "data" / x["file"]
            heartbeat(f"本地看图复核 · {shot} {x['stage']} #{x.get('n')}", len(done), len(todo) - i)
            t0 = time.time()
            try:
                v = client.inspect_image(str(p), x.get("prompt") or "", x.get("references") or [], wait_s=1800,
                                         label=f"{shot}-{x['stage']}-{x.get('n')}")
            except Exception as e:  # noqa: BLE001
                log("inspect failed", shot, x.get("file"), e)
                traceback.print_exc()
                time.sleep(30)
                break
            if v.get("error"):
                log("vlm error", shot, x.get("file"), v["error"])
                time.sleep(30)
                break                                   # 服务忙 / 没起：下一圈再来
            VQ.remember(p, v)
            desc, defects = rubric.describe(v)
            j = judge.rule_fallback(v, "离线：不调外部 API，规则裁判")
            rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": HOST, "shot": shot, "stage": x["stage"], "n": x.get("n"),
                   "file": x["file"], "vlm_key": v.get("key"), "vlm_seconds": v.get("seconds"), "vlm_text": desc,
                   "vlm_defects": defects, "defects": v.get("defects"), "unsure": v.get("unsure"),
                   "q9": VQ.q9(v)[:2], "judge": j,
                   "next_prompt": judge.apply_delta(x.get("prompt") or "", j.get("prompt_delta")) if j["verdict"] == "fail" else None,
                   "mode": "record_only", "rerun": False}
            REC.parent.mkdir(parents=True, exist_ok=True)
            with REC.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done.add(str(p))
            DONE.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
            log(f"{shot} {x['stage']} #{x.get('n')}: {','.join(v.get('defects') or []) or 'ok'} ({time.time() - t0:.0f}s)")
        heartbeat("本地看图复核 · 等新图", len(done), 0)
        time.sleep(60)
    log("STOP 文件出现，退出")


if __name__ == "__main__":
    main()
