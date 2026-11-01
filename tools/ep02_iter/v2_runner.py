"""
V2（2026-10-31）：ep02 第 2 版重出 —— 只经 :8800 API 提交（by="V2"），记在 data/ab/v2_iter/manifest.json。

与 tools/lab_ep02/lab_runner.py 同一协议：API 出完会把新版本设为“当前”，watch 立刻撤回到出片前的当前版本
（只在当前版本 == V2 版本时撤回）。不定稿、不写 review.json（“通过”是项目方闸门）；合成用 --sources-from。
每次只改一个维度：manifest 每条记 attempt / axis / 相对上一次改了什么。

用法：
  python tools/ep02_iter/v2_runner.py submit <label> <S2> <gpu> <axis> '<json body>'
  python tools/ep02_iter/v2_runner.py watch
  python tools/ep02_iter/v2_runner.py status
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8800"
ROOT = Path(__file__).resolve().parents[2]
MAN = ROOT / "data" / "ab" / "v2_iter" / "manifest.json"
TAG = "V2"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as f:
        return json.loads(f.read().decode("utf-8"))


def load():
    return json.loads(MAN.read_text(encoding="utf-8")) if MAN.exists() else {"entries": [], "active_seen": {}}


def save(m):
    MAN.parent.mkdir(parents=True, exist_ok=True)
    MAN.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")


def active_video(shot):
    a = req("GET", f"/api/shots/{shot}/video-takes").get("active")
    return a.get("video") if isinstance(a, dict) else a


def submit(label, shot, gpu, axis, body):
    shot = shot if shot.startswith("ep02-") else f"ep02-{shot}"
    m = load()
    pre = active_video(shot)
    mine = {e.get("take") for e in m["entries"] if e["shot"] == shot}
    if pre not in mine:
        m["active_seen"][shot] = pre
    attempt = 1 + sum(1 for e in m["entries"] if e["shot"] == shot)
    if attempt > 3:
        raise SystemExit(f"{shot} 已出 3 次（每镜上限），标待项目方")
    b = {**body, "gpu": gpu if not str(gpu).isdigit() else int(gpu), "by": TAG}
    res = req("POST", f"/api/shots/{shot}/video-jobs", b)
    e = {"label": label, "shot": shot, "attempt": attempt, "axis": axis, "gpu": gpu, "body": b,
         "job": res.get("id") or res.get("job_id"), "submitted": time.strftime("%H:%M:%S"), "pre_active": pre,
         "state": res.get("state"), "take": None, "tag": TAG}
    m["entries"].append(e)
    save(m)
    print(json.dumps({k: e[k] for k in ("label", "shot", "attempt", "axis", "gpu", "job", "state")}, ensure_ascii=False))


def poll_once():
    m = load()
    pending = 0
    mine = {(e["shot"], e.get("take")) for e in m["entries"] if e.get("take")}
    for e in m["entries"]:
        if e["state"] in ("done", "failed", "cancelled") and e.get("reverted") is not None:
            continue
        j = req("GET", f"/api/jobs/{e['job']}")
        e["state"] = j.get("state")
        if e["state"] == "done":
            e["take"] = j.get("take")
            e["finished"] = j.get("finished_at")
            mine.add((e["shot"], e["take"]))
            if active_video(e["shot"]) == e["take"]:
                back = m["active_seen"].get(e["shot"]) or e["pre_active"]
                if back is not None and (e["shot"], back) not in mine:
                    req("POST", f"/api/shots/{e['shot']}/takes/video/{back}/activate")
                    e["reverted"] = back
                else:
                    e["reverted"] = "skip"
            else:
                e["reverted"] = "not_active"
            print(time.strftime("%H:%M:%S"), "DONE", e["label"], e["shot"], "take", e["take"], flush=True)
        elif e["state"] in ("failed", "cancelled"):
            e["error"] = str(j.get("error"))[:300]
            e["reverted"] = "n/a"
            print(time.strftime("%H:%M:%S"), "FAILED", e["label"], e["shot"], e["error"], flush=True)
        else:
            pending += 1
    for shot in {e["shot"] for e in m["entries"]}:
        cur = active_video(shot)
        if (shot, cur) not in mine:
            m["active_seen"][shot] = cur
    save(m)
    return pending, m


def main(argv):
    if argv[0] == "submit":
        submit(argv[1], argv[2], argv[3], argv[4], json.loads(argv[5]))
    elif argv[0] == "watch":
        while True:
            try:
                pending, _ = poll_once()
            except Exception as ex:  # noqa: BLE001
                print("poll error", ex, flush=True)
                pending = 1
            if pending == 0:
                print("ALL_DONE", flush=True)
                break
            time.sleep(30)
    elif argv[0] == "status":
        _, m = poll_once()
        for e in m["entries"]:
            print(e["label"], e["shot"], e["attempt"], e["axis"], e["gpu"], e["state"], "take", e.get("take"),
                  "rev", e.get("reverted"), e.get("error", ""))


if __name__ == "__main__":
    main(sys.argv[1:])
