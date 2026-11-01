"""DEBUG-RSI r2（总调度 fredw-2b 派）：用 ComfyUI /history 实测出图道占用率（GPU 实际执行时间 / 窗口时长）。

用法：.venv/Scripts/python.exe tools/debug/lane_util.py [--min 30] [--json]
- 每台服务器只开一次 rssh（复用 NETFIX 主连接），远端命令带 timeout + nice（K-OPS-E06）；
- 道表读 config/debug_lanes.json（缺省 = 5 条出图道 gpu33:0/1/3、gpu36:0/1）；
- 结果追加到 data/debug/lane_util.jsonl。占用 = 窗口内各作业 [execution_start, 结束] 并集长度 / 窗口长度；按 ns_tag.agent 分开统计。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_LANES = {"gpu33:0": 8188, "gpu33:1": 8189, "gpu33:3": 8191, "gpu36:0": 8188, "gpu36:1": 8189}
OUT = ROOT / "data" / "debug" / "lane_util.jsonl"

REMOTE = r'''
for p in __PORTS__; do
  printf '##PORT %s\n' "$p"
  timeout 20 curl -s -m 15 "http://127.0.0.1:$p/history?max_items=200" || true
  printf '\n'
done
'''


def intervals(hist: dict, t0: float, t1: float) -> list[tuple[float, float, str]]:
    out = []
    for v in (hist or {}).values():
        ms = {m[0]: m[1].get("timestamp") for m in (v.get("status") or {}).get("messages", [])
              if isinstance(m, list) and len(m) > 1 and isinstance(m[1], dict)}
        s = ms.get("execution_start")
        e = ms.get("execution_success") or ms.get("execution_error") or ms.get("execution_interrupted")
        if not s:
            continue
        s, e = s / 1000, (e / 1000 if e else t1)
        if e < t0 or s > t1:
            continue
        pr = v.get("prompt") or []
        tag = (pr[3] if len(pr) > 3 and isinstance(pr[3], dict) else {}).get("ns_tag") or {}
        out.append((max(s, t0), min(e, t1), str(tag.get("agent") or "未标")))
    return out


def union_len(iv: list[tuple[float, float, str]]) -> float:
    tot, cur = 0.0, None
    for s, e, _ in sorted(iv):
        if cur is None or s > cur[1]:
            if cur:
                tot += cur[1] - cur[0]
            cur = [s, e]
        else:
            cur[1] = max(cur[1], e)
    return tot + (cur[1] - cur[0] if cur else 0.0)


def parse(raw: str) -> dict[int, dict]:
    res, port, buf = {}, None, []
    for ln in raw.splitlines():
        if ln.startswith("##PORT "):
            if port is not None:
                res[port] = "".join(buf)
            port, buf = int(ln.split()[1]), []
        else:
            buf.append(ln)
    if port is not None:
        res[port] = "".join(buf)
    out = {}
    for p, txt in res.items():
        try:
            out[p] = json.loads(txt) if txt.strip() else {}
        except ValueError:
            out[p] = None
    return out


def measure(minutes: float = 30, lanes: dict | None = None, fetch=None) -> dict:
    lanes = lanes or DEFAULT_LANES
    t1 = time.time()
    t0 = t1 - minutes * 60
    by_host: dict[str, list[int]] = {}
    for lane, port in lanes.items():
        by_host.setdefault(lane.split(":")[0], []).append(port)
    rows = {}
    for host, ports in by_host.items():
        hist = fetch(host, ports) if fetch else _fetch(host, ports)
        for lane, port in lanes.items():
            if lane.split(":")[0] != host:
                continue
            h = hist.get(port)
            if h is None:
                rows[lane] = {"util": None, "why": "取不到 /history"}
                continue
            iv = intervals(h, t0, t1)
            agents: dict[str, float] = {}
            for a in {x[2] for x in iv}:
                agents[a] = round(union_len([x for x in iv if x[2] == a]) / (t1 - t0), 3)
            rows[lane] = {"util": round(union_len(iv) / (t1 - t0), 3), "jobs": len(iv), "by_agent": agents}
    vals = [r["util"] for r in rows.values() if r.get("util") is not None]
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "window_min": minutes, "lanes": rows,
            "mean": round(sum(vals) / len(vals), 3) if vals else None, "target": 0.8}


def _fetch(host: str, ports: list[int]) -> dict:
    from tools.netfix import rssh
    cmd = REMOTE.replace("__PORTS__", " ".join(str(p) for p in ports))
    r = rssh.run(host, "timeout 90 nice -n 19 bash -s", input=cmd.encode(), timeout=120)
    return parse(r.stdout.decode("utf-8", "replace"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=30)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = ROOT / "config" / "debug_lanes.json"
    lanes = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else None
    res = measure(a.min, lanes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(res, ensure_ascii=False) + "\n")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for k, v in res["lanes"].items():
            print(k, v.get("util"), v.get("jobs"), v.get("by_agent") or v.get("why"))
        print("mean", res["mean"], "target", res["target"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
