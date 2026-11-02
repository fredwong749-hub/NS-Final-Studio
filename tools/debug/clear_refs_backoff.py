"""一次性：清某个 run 里因 K-OPS-F03（refs 与期望表不一致）在退避中的对象（总调度 11-02 14:0x：FACTORY inbox 热修部署后清一次）。
E26 部署后不再需要手动清（签名一变自动放回）。

用法（在服务器 repo 目录跑；可经 rsh 把本文件从 stdin 喂给 python3 -）：
  python3 clear_refs_backoff.py <run> [--kind=asset] [--apply]
不带 --apply 只列出。写入时只改 blocked_until / reason / assets:<sid>.blocked，并在 log.jsonl 记 refs_backoff_cleared（counted=false）。
"""
import json
import os
import sys
import tempfile
import time

run = sys.argv[1]
apply = "--apply" in sys.argv
kind = "asset" if "--kind=asset" in sys.argv else "refs"     # refs：K-OPS-F03；asset：I3 / I4 缺设定图 / 单品（资产登记推到服务器后清）
sys.path.insert(0, os.path.join(os.getcwd(), "tools", "autopilot"))
import runs as RUNS  # noqa: E402
base = "data/producer" if run in ("", RUNS.primary_run(strict=True)) else f"data/producer/runs/{run}"   # 服务器侧失败关闭
led_p = os.path.join(base, "attempts.json")
now = time.time()


def load():
    with open(led_p, encoding="utf-8") as f:
        return json.load(f)


L = load()
hit = [oid for oid, r in L.items() if isinstance(r, dict) and (r.get("blocked_until") or 0) > now
       and ((kind == "refs" and "K-OPS-F03" in (r.get("last_error") or "")) or
            (kind == "asset" and any(k in (r.get("last_error") or "") for k in ("I3 ", "I4 ", "没有设定图", "资产缺图"))))]
print(json.dumps({"run": run, "ledger": led_p, "n": len(hit), "objs": hit}, ensure_ascii=False))
if apply and hit:
    L = load()                                   # 写前重读，窗口尽量短
    for oid in hit:
        r = L.get(oid) or {}
        r["blocked_until"] = 0
        r["reason"] = ("期望 refs 表已修（FACTORY inbox 热修）" if kind == "refs" else "设定图 / 单品已登记并推到服务器") + "，DEBUG_RSI 清退避重派（不计次）"
        sid = oid.split(":", 1)[-1]
        a = L.get(f"assets:{sid}")
        if isinstance(a, dict) and a.get("blocked"):
            a["blocked"] = False
            a["released_at"] = now
    fd, tmp = tempfile.mkstemp(dir=base, prefix="attempts.json.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(L, f, ensure_ascii=False, indent=1)
    os.replace(tmp, led_p)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(base, "log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "t": round(time.time(), 2), "ev": "refs_backoff_cleared" if kind == "refs" else "asset_backoff_cleared", "objs": hit, "by": "DEBUG_RSI", "counted": False},
                           ensure_ascii=False) + "\n")
    print(json.dumps({"applied": len(hit), "at": ts}, ensure_ascii=False))
