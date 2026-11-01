"""印样目检补数（版本 2026-11-01f-q4metrics）：给每镜印样上展示的那张首 / 尾帧补 Q4 脸部质感度量（face_hf / p_plastic / face_oil …），
用 REFLOCK 的 remote_score.postflight_full("gpu33", file=本机交付图, post=None) 重算，只取结果里 Q4 的 evidence，
写进 data/assetmaster/frames_v2/q4_metrics.json（按文件路径索引）——**不改通过结论、不重出、不计次**，不写 state.json
（编排器在跑，避免并发覆盖）。frames_v2.write_page 读这份文件合并进 Q4，按 R.q4_sort_key 排序、R.q4_caption 标注。

用法：.venv/Scripts/python.exe tools/assetmaster/q4_backfill.py [--eps 1-10] [--threads 2]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "services/api", "packages/schema", "tools/pipeline", "tools/series10_imggen",
          "tools/gen_contract", "services/recipes", "tools/assetmaster"):
    sys.path.insert(0, str(ROOT / p))
OUT = ROOT / "data/assetmaster/frames_v2/q4_metrics.json"
TAG = "2026-11-01f-q4metrics"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", default="1-10")
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args(argv)
    import frames_v2 as F
    import image_jobs as IJ
    import remote_score as RS
    eps = F.parse_eps(a.eps)
    st = F.jl(F.STATE, {}) or {}
    jobs = {j["id"]: j for j in F.build_jobs(eps)}
    have = F.jl(OUT, {}) or {}
    todo = []
    for sid, s in st.items():
        if not sid.startswith("ep") or int(sid[2:4]) not in eps or sid not in jobs:
            continue
        for stage in ("image", "last"):
            r = s.get(stage) or {}
            f = (r.get("final") or {}).get("file")
            files = {f} if f else set()
            files |= {x["file"] for x in r.get("attempts", []) if x.get("file") and not x.get("stale")}
            for fl in files:
                if fl in have and have[fl].get("tag") == TAG:
                    continue
                j = jobs[sid] if stage == "image" else (F.last_job(jobs[sid], (s.get("image", {}).get("final") or {}).get("file") or "") or jobs[sid])
                todo.append((sid, stage, fl, j))
    print("q4 backfill", len(todo), flush=True)
    lk = threading.Lock()

    def worker():
        while True:
            with lk:
                if not todo:
                    return
                sid, stage, fl, j = todo.pop(0)
            try:
                req = IJ.contract_request({**j, "graph": {}})
                d = RS.postflight_full("gpu33", [{"id": "a", "file": str(ROOT / fl), "post": None, "request": req}])["a"]
                q4 = next((i for i in d.get("items") or [] if i.get("id") == "Q4"), None)
                with lk:
                    have[fl] = {"tag": TAG, "shot": sid, "stage": stage, "Q4": q4, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "measured_on": d.get("measured_on"), "measure_error": d.get("measure_error")}
                    tmp = OUT.with_suffix(".tmp")
                    tmp.write_text(json.dumps(have, ensure_ascii=False, indent=1), encoding="utf-8")
                    tmp.replace(OUT)
                print(time.strftime("%H:%M:%S"), sid, stage, (q4 or {}).get("detail", "")[:80], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", sid, stage, repr(e)[:200], flush=True)

    th = [threading.Thread(target=worker) for _ in range(a.threads)]
    [t.start() for t in th]
    [t.join() for t in th]
    # 补完重写印样
    st = F.jl(F.STATE, {}) or {}
    for n in eps:
        F.write_page(n, st)
    print("done", len(have))
    return 0


if __name__ == "__main__":
    sys.exit(main())
