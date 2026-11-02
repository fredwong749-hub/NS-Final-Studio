"""解除某镜的项目方定稿锁（只在项目方点选 / 总调度转达后用）：locked[stage] 移到 locked_history（带 by / why / at），不删记录。
在所属主机 repo 目录跑（经 rsh 从 stdin 喂给 python -）：
  python - <sid> <stage,stage> <by> <why> [--apply]
"""
import json
import os
import sys
import time

R = os.getcwd()
sys.path[:0] = [f"{R}/services/render_router", f"{R}/packages/schema", f"{R}/services/agent", f"{R}/services/recipes"]
from ns_render import pipeline as P  # noqa: E402

sid, stages, by, why = sys.argv[1], sys.argv[2].split(","), sys.argv[3], sys.argv[4]
d = P.load_takes(sid)
print(json.dumps({"sid": sid, "locked": d.get("locked"), "locked_by": d.get("locked_by"), "active": d.get("active")}, ensure_ascii=False))


def fn(doc):
    hist = doc.setdefault("locked_history", [])
    for st in stages:
        n = (doc.get("locked") or {}).pop(st, None)
        if n is None:
            continue
        hist.append({"stage": st, "n": n, "locked_by": ((doc.get("locked_by") or {}).pop(st, None)),
                     "released_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "released_by": by, "why": why})


if "--apply" in sys.argv:
    if hasattr(P, "mutate_takes"):
        d = P.mutate_takes(sid, fn, op="owner_unlock", by=by, op_id=f"owner_unlock:{sid}:{','.join(stages)}")
    else:
        with P.shot_lock(sid):
            d = P.load_takes(sid)
            fn(d)
            P._save_takes(sid, d)
    print(json.dumps({"locked": d.get("locked"), "history": d.get("locked_history")[-len(stages):]}, ensure_ascii=False))
