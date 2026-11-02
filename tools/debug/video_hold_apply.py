"""把视频按镜 hold 立即落到正在用的 jobs.json（不等 night 下次重编）：items 里的镜 variants 清空、route=hold。
vidgen 每轮重读 jobs.json，无变体 → waiting_frame，不派单。night 之后重编由 build_jobs.video_holds 保持同样结果。
在 vidgen 所在 repo 跑（可经 rsh 从 stdin 喂给 python3 -）：
  python3 video_hold_apply.py <jobs.json 路径> <sid>[,<sid>…] <原因> [--apply]
"""
import json
import os
import sys
import tempfile

path, sids, why = sys.argv[1], set(sys.argv[2].split(",")), sys.argv[3]
d = json.load(open(path, encoding="utf-8"))
hit = [m for m in d.get("shots") or [] if m.get("shot") in sids]
print(json.dumps({"file": path, "hit": [(m["shot"], m.get("host"), len(m.get("variants") or {})) for m in hit]}, ensure_ascii=False))
todo = [m for m in hit if m.get("variants")]          # 已置空的不重写
if "--apply" in sys.argv and todo:
    for m in todo:
        m["variants"], m["ladder_order"], m["route"], m["hold"] = {}, [], "hold", why
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix="jobs.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print(json.dumps({"applied": len(todo)}, ensure_ascii=False))
