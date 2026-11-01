"""
LAB（2026-10-31）：ep02 渲染配方对照实验 —— 只经 :8800 API 提交，产物标 LAB。

- submit：POST /api/shots/{shot}/video-jobs，by="LAB"（非自动提交，不触发自动闸门），记入 data/ab/lab/manifest.json
- watch：轮询自己提交的任务；API 出完会把新版本设为“当前”，LAB 版本一律撤回到出片前的当前版本
  （只在当前版本 == LAB 版本时撤回，不动 RR / 项目方后来设的版本）。不定稿、不审片通过。

用法：
  python tools/lab_ep02/lab_runner.py submit <label> <shot S2> <gpu> '<json body>'
  python tools/lab_ep02/lab_runner.py watch           # 前台循环，直到全部结束
  python tools/lab_ep02/lab_runner.py status
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8800"
ROOT = Path(__file__).resolve().parents[2]
MAN = ROOT / "data" / "ab" / "lab" / "manifest.json"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
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


def submit(label, shot, gpu, body):
    shot = shot if shot.startswith("ep02-") else f"ep02-{shot}"
    m = load()
    pre = active_video(shot)
    lab_takes = {e.get("take") for e in m["entries"] if e["shot"] == shot}
    if pre not in lab_takes:
        m["active_seen"][shot] = pre
    if body.pop("i2v_fix", False):   # I2VA 正文修正（去掉 Picture 2 分句），走 prompt_override
        sys.path.insert(0, str(ROOT / "services" / "render_router"))
        from ns_render import h3_video as HV
        c = json.loads((ROOT / f"data/renders/ep02/{shot[5:]}/compiled.json").read_text(encoding="utf-8"))
        body["prompt_override"] = HV.i2v_prompt(c["video_prompt"])[0]
    b = {**body, "gpu": gpu if not str(gpu).isdigit() else int(gpu), "by": "LAB"}
    res = req("POST", f"/api/shots/{shot}/video-jobs", b)
    e = {"label": label, "shot": shot, "gpu": gpu, "body": b, "job": res.get("id") or res.get("job_id"),
         "submitted": time.strftime("%H:%M:%S"), "pre_active": pre, "state": res.get("state"), "take": None,
         "tag": "LAB"}
    m["entries"].append(e)
    save(m)
    print(json.dumps({k: e[k] for k in ("label", "shot", "gpu", "job", "state")}, ensure_ascii=False))


def poll_once():
    m = load()
    pending = 0
    lab = {(e["shot"], e.get("take")) for e in m["entries"] if e.get("take")}
    for e in m["entries"]:
        if e["state"] in ("done", "failed", "cancelled") and e.get("reverted") is not None:
            continue
        j = req("GET", f"/api/jobs/{e['job']}")
        e["state"] = j.get("state")
        if e["state"] == "done":
            e["take"] = j.get("take")
            e["finished"] = j.get("finished_at")
            lab.add((e["shot"], e["take"]))
            cur = active_video(e["shot"])
            if cur == e["take"]:
                back = m["active_seen"].get(e["shot"]) or e["pre_active"]
                if back is not None and (e["shot"], back) not in lab:
                    req("POST", f"/api/shots/{e['shot']}/takes/video/{back}/activate")
                    e["reverted"] = back
                else:
                    e["reverted"] = "skip"
            else:
                e["reverted"] = "not_active"
        elif e["state"] in ("failed", "cancelled"):
            e["error"] = str(j.get("error"))[:300]
            e["reverted"] = "n/a"
        else:
            pending += 1
    # 记录每镜最新的非 LAB 当前版本（RR 改了也跟上）
    for shot in {e["shot"] for e in m["entries"]}:
        cur = active_video(shot)
        if (shot, cur) not in lab:
            m["active_seen"][shot] = cur
    save(m)
    return pending, m


def main(argv):
    if argv[0] == "submit":
        submit(argv[1], argv[2], argv[3], json.loads(argv[4]))
    elif argv[0] == "watch":
        while True:
            try:
                pending, _ = poll_once()
            except Exception as ex:  # noqa: BLE001
                print("poll error", ex, flush=True)
                pending = 1
            if pending == 0 and "--forever" not in argv:
                break
            time.sleep(30)
    elif argv[0] == "status":
        _, m = poll_once()
        for e in m["entries"]:
            print(e["label"], e["shot"], e["gpu"], e["state"], "take", e.get("take"), "rev", e.get("reverted"),
                  e.get("error", ""))


if __name__ == "__main__":
    main(sys.argv[1:])
