"""BAKEOFF：用 REFLOCK 的服务器版 postflight（tools/gen_contract/remote_score.postflight_full）分批重打契约分（只打分不重出）。
一批太多会撞 remote_score 的 900 s ssh 超时（11-01 164 张一批超时），所以每批 20 张、逐批落盘、可续跑。
用法：.venv/Scripts/python.exe tools/bakeoff/rescore.py data/ab/image_bakeoff/rescore_jobs.json data/ab/image_bakeoff/rescore_pf33.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gen_contract"))


def main(jobs_p, out_p, batch=20):
    import remote_score as RS
    jobs = json.loads(Path(jobs_p).read_text(encoding="utf-8"))
    outp = Path(out_p)
    out = json.loads(outp.read_text(encoding="utf-8")) if outp.exists() and outp.stat().st_size > 2 else {}
    todo = [j for j in jobs if j["id"] not in out or out[j["id"]].get("measure_error")]
    for k in range(0, len(todo), batch):
        part = todo[k:k + batch]
        t0 = time.time()
        try:
            out.update(RS.postflight_full("gpu33", part))
        except Exception as e:  # noqa: BLE001
            print("批失败", k, str(e)[:200], flush=True)
            continue
        outp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print(f"{k + len(part)}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    bad = [i for i, v in out.items() if v.get("measure_error")]
    print("完成", len(out), "测量出错", len(bad), bad[:10])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(*sys.argv[1:3])
