"""作废某镜某阶段的当前版本（项目方反馈 / 总调度指示用）：给这一版记 params.rejected（原因、反馈单号），撤下当前，
退到最新一张可用的旧版（没有就清空），之后按正常流程重出。逻辑同 :8800 takes_ui.reject，但支持 video，可在服务器上跑。

用法（服务器 repo 目录；可经 rsh 从 stdin 喂给 python3 -）：
  python3 void_take.py <sid> <stage image|last|video> <reason> <by> [--n N] [--no-fallback] [--apply]
不带 --apply 只显示当前版本。
"""
import json
import os
import sys

ROOT = os.getcwd()
for p in ("services/render_router", "packages/schema", "services/agent", "services/recipes"):
    sys.path.insert(0, os.path.join(ROOT, p))
from ns_render import pipeline as P  # noqa: E402

a = [x for x in sys.argv[1:] if not x.startswith("--")]
sid, stage, reason, by = a[0], a[1], a[2], a[3]
n_arg = next((int(sys.argv[i + 1]) for i, x in enumerate(sys.argv) if x == "--n"), None)
apply = "--apply" in sys.argv

d = P.load_takes(sid)
act = (d.get("active") or {}).get(stage)
n = n_arg if n_arg is not None else act
t = next((x for x in d.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
print(json.dumps({"sid": sid, "stage": stage, "active": act, "target": n, "found": bool(t),
                  "file": (t or {}).get("file") or (t or {}).get("path")}, ensure_ascii=False))
if not apply or not t:
    sys.exit(0 if t else 2)

with P.shot_lock(sid):
    d = P.load_takes(sid)
    t = next(x for x in d["takes"] if x.get("stage") == stage and x.get("n") == n)
    prm = t["params"] if isinstance(t.get("params"), dict) else {}
    t["params"] = prm
    prm["rejected"] = {"reason": reason[:300], "by": by, "at": P.now()}
    P._save_takes(sid, d)
if act == n:
    d = P.load_takes(sid)
    clean = [x for x in d["takes"] if x.get("stage") == stage and x["n"] != n and not P.ineligible_reason(x)]
    if clean and stage != "video" and "--no-fallback" not in sys.argv:   # --no-fallback：旧版同样有问题时直接清空、按新规则重出
        P.set_active(sid, stage, clean[-1]["n"], reason=f"v{n} 作废（{reason}），退回最新一张可用的旧版", actor=f"void_take（{by}）")
        new = clean[-1]["n"]
    else:                                      # 视频不退旧版：旧版多半同样的问题，清空后按正常流程重出
        P.clear_active(sid, stage, f"v{n} 作废（{reason}），清空当前、按正常流程重出", actor=f"void_take（{by}）")
        new = None
else:
    new = act
print(json.dumps({"voided": n, "active_now": new}, ensure_ascii=False))
