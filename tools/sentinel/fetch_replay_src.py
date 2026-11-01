"""回放取证（只读）：把服务器 producer 当晚的日志 / 登记表摘要经 rssh 常驻主连接拉回 data/sentinel/replay_src/（K-OPS-N09，nice + timeout）。
  .venv/Scripts/python.exe tools/sentinel/fetch_replay_src.py [--since 1793541600]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/netfix"))
OUT = ROOT / "data/sentinel/replay_src"
R = "/root/work/fredw/offline_20261101/repo"

PY = r'''
import json, sys, gzip
since = float(sys.argv[1])
out = []
for ln in open("data/producer/log.jsonl", encoding="utf-8", errors="replace"):
    if '"preflight_block"' in ln:
        continue
    try:
        d = json.loads(ln)
    except ValueError:  # arch-ok: 服务器端坏行跳过
        continue
    if d.get("t", 0) >= since:
        out.append(ln.rstrip("\n"))
sys.stdout.buffer.write(gzip.compress(("\n".join(out) + "\n").encode("utf-8")))
'''


def main() -> int:
    import rssh
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=float, default=1793541600.0)   # 11-01 23:00
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for h in ("gpu33", "gpu36"):
        cmd = f"cd {R} && cat > /tmp/sentinel_fetch.py && timeout 90 nice -n 19 env OMP_NUM_THREADS=1 python3 /tmp/sentinel_fetch.py {a.since}"
        r = rssh.run(h, cmd, input=PY.encode(), timeout=140)
        p = OUT / f"{h}_producer_log.jsonl.gz"
        if r.returncode == 0 and r.stdout:
            p.write_bytes(r.stdout)
        print(h, r.returncode, len(r.stdout), r.stderr.decode("utf-8", "replace")[-200:])
        r2 = rssh.run(h, f"timeout 30 nice -n 19 cat {R}/data/producer/registry.json | gzip -c", timeout=80)
        if r2.returncode == 0 and r2.stdout:
            (OUT / f"{h}_registry_now.json.gz").write_bytes(r2.stdout)
        print(h, "registry", r2.returncode, len(r2.stdout))
    return 0


if __name__ == "__main__":
    sys.exit(main())
