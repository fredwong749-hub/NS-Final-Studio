"""延长 data/autopilot/<名>_hold.json 的到期时间（顶层 expires_at 和 shots[].expires_at 一起），原文件先备份，记一条 extended。
在服务器 repo 目录跑（经 rsh 从 stdin 喂给 python3 -）：
  python3 hold_extend.py <hold 文件名> <新到期 YYYY-mm-ddTHH:MM:SS> <原因> [--apply]
"""
import json
import os
import shutil
import sys
import tempfile
import time

name, exp, why = sys.argv[1:4]
p = os.path.join("data/autopilot", name)
d = json.load(open(p, encoding="utf-8"))
print(json.dumps({"file": p, "active": d.get("active"), "expires_at": d.get("expires_at"),
                  "shots": [(i.get("shot"), i.get("expires_at")) for i in d.get("shots") or []]}, ensure_ascii=False))
if "--apply" in sys.argv:
    q = "data/_quarantine/debug_rsi_20261102"
    os.makedirs(q, exist_ok=True)
    shutil.copy2(p, os.path.join(q, f"{name}.{time.strftime('%H%M%S')}"))
    tz = "+09:00" if str(d.get("expires_at") or "").endswith("+09:00") else ""
    d["expires_at"] = exp + tz
    for i in d.get("shots") or []:
        i["expires_at"] = exp
    d.setdefault("extended", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "to": exp, "why": why, "by": "DEBUG-RSI"})
    fd, tmp = tempfile.mkstemp(dir="data/autopilot", prefix=name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    print(json.dumps({"extended_to": exp}, ensure_ascii=False))
