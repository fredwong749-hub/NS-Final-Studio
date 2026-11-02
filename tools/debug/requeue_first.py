"""剧本补丁改了某镜首帧的写法、但这镜首帧是旧数据（账本没记 passed_sig，K-OPS-E24 不会自己触发）→ 给 first:<sid> 记一个
过期的 passed_sig 标记，producer 下一拍按 E24 判“作业输入变了” → 首帧回 ready 自动重出（不计次、不走驳回闸门）；
尾帧随 E13 作废重出，视频随 vidgen check_stale 作废重出。项目方定稿锁的镜 E24 本身不动。
在服务器 repo 目录跑（可经 rsh 从 stdin 喂给 python3 -）：
  python3 requeue_first.py <run> <sid> <原因> [--apply]
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.getcwd(), "tools", "autopilot"))
import runs as RUNS  # noqa: E402

run, sid, why = sys.argv[1:4]
base = "data/producer" if run == RUNS.primary_run(strict=True) else f"data/producer/runs/{run}"
led_p = os.path.join(base, "attempts.json")
L = json.load(open(led_p, encoding="utf-8"))
oid = f"first:{sid}"
r = L.get(oid) or {}
print(json.dumps({"ledger": led_p, "obj": oid, "final": r.get("final"), "passed_sig": r.get("passed_sig")}, ensure_ascii=False))
if "--apply" in sys.argv:
    if r.get("passed_input_sig") and not str(r.get("passed_input_sig")).startswith("stale:"):
        print(json.dumps({"skip": "已有 passed_input_sig，E24 会按剧本输入自己比对"}, ensure_ascii=False))
        sys.exit(0)
    L = json.load(open(led_p, encoding="utf-8"))   # 写前重读
    L.setdefault(oid, {}).update(passed_sig=f"stale:{why[:80]}", passed_input_sig=f"stale:{why[:80]}")   # K-REN-956 后 E24 只认 passed_input_sig
    fd, tmp = tempfile.mkstemp(dir=base, prefix="attempts.json.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(L, f, ensure_ascii=False, indent=1)
    os.replace(tmp, led_p)
    with open(os.path.join(base, "log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": round(time.time(), 2), "ev": "first_requeue_marked",
                            "obj": oid, "why": why, "by": "DEBUG_RSI", "counted": False}, ensure_ascii=False) + "\n")
    print(json.dumps({"applied": True}, ensure_ascii=False))
