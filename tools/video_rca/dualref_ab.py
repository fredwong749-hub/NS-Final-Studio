"""VIDEO-RCA r2（总调度 11-01 19:2x 决定 4）：单人首帧看镜头——“正脸 + 四分之三 / 侧脸 双参考槽” vs 现行单正脸参考。
LOCALGPU 已测：只用侧脸参考 sface 0.914 → 0.460（不可行）；双参考槽没测过。

A = 现行（refs[0] = 正脸 lin_wan_face_hd_A_s202.png，提示词原样）
D = 双参考：refs = [正脸, 侧脸裁切 lin_wan_face_side_A_s202.png, 其余原参考…]；提示词把“图1是林晚的脸部参考（只取脸和发型）”
    改成“图1、图2都是林晚的脸部参考（图1正面、图2侧面；只取五官身份和发型，头部角度和视线按正文）”，其余“图N”顺延 +1。
其余全同（first_frame_jobs.json 作业、frame_v9 = S★ 参数、同 seed）。出图走生产 build_graph，本机道 laptop:0，scope=ab：
图只进 data/ab/video_rca/r2_dualref/，不写 takes.json / 契约账本。度量复用 tools/localgpu/identity_gaze_ab.measure
（gaze_mp = Q9 旁证、YuNet 视线、sface 对现行正脸）。生产要用本机道时先让：每张图前查 18388 队列为空。

    .venv/Scripts/python.exe tools/video_rca/dualref_ab.py run ep01-S2,ep01-S3,ep01-S6 --seeds job,job+100
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/localgpu"))
import identity_gaze_ab as IG  # noqa: E402

OUT = ROOT / "data/ab/video_rca/r2_dualref"
SIDE = IG.FACE_B
OLD = "图1是林晚的脸部参考（只取脸和发型）"
NEW = "图1、图2都是林晚的脸部参考（图1正面、图2侧面；只取五官身份和发型，头部角度和视线按正文）"


def dual_prompt(p: str) -> str:
    if OLD not in p:
        raise SystemExit("提示词里没有现行图1句")
    body = p.replace(OLD, "\0")
    body = re.sub(r"图([2-9])", lambda m: f"图{int(m.group(1)) + 1}", body)
    return body.replace("\0", NEW)


def lane_idle() -> bool:
    try:
        q = json.loads(urllib.request.urlopen(IG.URL + "/queue", timeout=10).read())
        return not (q["queue_running"] or q["queue_pending"])
    except Exception:  # noqa: BLE001
        return False


def run(shots, seed_spec):
    OUT.mkdir(parents=True, exist_ok=True)
    IG.OUT = OUT
    log = OUT / "takes.jsonl"
    done = set()
    if log.exists():
        for ln in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            done.add((r["shot"], r["arm"], r["seed"]))
    for sid in shots:
        job = IG.load_job(sid)
        for seed in IG.seeds_for(job, seed_spec):
            for arm in ("A", "D"):
                if (sid, arm, seed) in done:
                    continue
                while not lane_idle():
                    print("让道：本机道有任务", flush=True)
                    time.sleep(60)
                if arm == "A":
                    j, IG.ARMS = job, {"A": IG.FACE_A}
                    r = IG.render(j, "A", seed)
                else:
                    j = {**job, "prompt": dual_prompt(job["prompt"]), "refs": [IG.FACE_A, SIDE, *job["refs"][1:]]}
                    IG.ARMS = {"D": IG.FACE_A}          # render 用 ARMS[arm] 替换 refs[0]；refs[0] 仍是正脸
                    r = IG.render(j, "D", seed)
                rec = {"scope": "ab", "experiment": "video_rca_r2_dualref", "shot": sid, "arm": arm, "seed": seed, **r,
                       "metrics": IG.measure(ROOT / r["file"]), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(json.dumps({k: rec[k] for k in ("shot", "arm", "seed", "comfy_s")} | rec["metrics"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run(sys.argv[2].split(","), sys.argv[sys.argv.index("--seeds") + 1] if "--seeds" in sys.argv else "job")
