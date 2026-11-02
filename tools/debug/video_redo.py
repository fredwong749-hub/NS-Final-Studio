"""给视频编排（tools/series10_video/vidgen.py check_lip_redo）追加一条重出请求：data/director/redo_requests.json 的 requests 里
加 {shot, status: pending, reason, timeline, at, by}。vidgen 读到后把现有片子挪进 superseded、状态回到待出、变体从头算（不计次）。
在视频所在主机的 repo 目录跑（可经 rsh 从 stdin 喂给 python3 -）：
  python3 video_redo.py <sid> <reason> <timeline 标识（如 fb-0001）> <by> [--variants=r24,alt] [--apply]
"""
import json
import os
import sys
import tempfile
import time

sid, reason, tl, by = sys.argv[1:5]
p = os.path.join("data", "director", "redo_requests.json")
d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"requests": []}
reqs = d.setdefault("requests", [])
dup = [q for q in reqs if q.get("shot") == sid and q.get("timeline") == tl]
rec = {"shot": sid, "status": "pending", "reason": reason, "timeline": tl, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by}
vs = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--variants=")), "")
if vs:                              # 加变体再试（vidgen force_queue，sv-14 起）：不作废已有出片，不受 4 次上限
    rec["variants"] = [v for v in vs.split(",") if v]
print(json.dumps({"file": p, "n_requests": len(reqs), "dup": len(dup), "new": rec}, ensure_ascii=False))
if "--apply" in sys.argv and not dup:
    reqs.append(rec)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix="redo_requests.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    print(json.dumps({"applied": True}, ensure_ascii=False))
