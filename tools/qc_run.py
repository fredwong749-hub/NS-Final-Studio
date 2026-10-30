"""Run all ns_qc gates over one episode of the local gpu3 mirror and write docs/audit/qc_epNN.{md,json}.

  .venv\\Scripts\\python.exe tools\\qc_run.py --episode 1
  .venv\\Scripts\\python.exe tools\\qc_run.py --episode 1 --shots S1,S3 --gpu3-host gpu33

--gpu3-host: keyframes recorded with a gpu3 absolute path that are not in the mirror are copied read-only
(scp BatchMode) into data/qc/kf_cache/. Nothing on gpu3 is modified. Exit code: 0 pass/warn, 2 fail.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "qc"))

from ns_qc.runner import run_episode  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", "-e", type=int, required=True)
    ap.add_argument("--shots", help="comma list, e.g. S1,S3")
    ap.add_argument("--mirror", help="default <root>/data/renders_gpu3")
    ap.add_argument("--out", help="report dir (default docs/audit)")
    ap.add_argument("--gpu3-host", help="ssh host for read-only keyframe fetch (e.g. gpu33)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    r = run_episode(a.episode, mirror=Path(a.mirror) if a.mirror else None, out_dir=Path(a.out) if a.out else None,
                    gpu3_host=a.gpu3_host, shots=a.shots.split(",") if a.shots else None)
    print(f"[qc] ep{a.episode:02d} verdict: {r['verdict']}")
    for p in r["_paths"]:
        print(f"[qc] wrote {p}")
    return 2 if r["verdict"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
