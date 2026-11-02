"""部署后核对（总调度 20:3x：以后做进 deploy 自动流程，结果写进 deploy_*.json 的 post_verify）。
在服务器仓库目录跑：当前剧（runs.current_run）资产包清单里每个角色的 face_of + 文件 sha，与清单登记的 sha 比；另报本机版本号。
用法（服务器上）：<venv>/bin/python tools/factory/post_verify.py  → 一行 JSON"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] if not __file__.startswith("<") else Path.cwd()   # 经 stdin 送到服务器时 = 当前目录（仓库根）


def verify(root: Path = ROOT) -> dict:
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    sys.path[:0] = [str(root), str(root / "services/agent")]
    from tools.autopilot import runs as RN
    from ns_agent import asset_refs as AR
    run = RN.current_run(root)
    out = {"run": run, "faces": {}, "ok": True}
    try:
        out["version"] = json.loads((root / "data/system_version.txt").read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError):   # arch-ok: 版本文件读不出 = 记 None（核对结果照出）
        out["version"] = None
    man = AR.manifest(run) if AR.manifest_rel(run) else None
    for cid, c in ((man or {}).get("characters") or {}).items():
        f = AR.face_of(run, cid)
        want = (c.get("face") or {}).get("sha256")
        got = hashlib.sha256((root / f).read_bytes()).hexdigest() if f else None
        out["faces"][cid] = {"face_of": f, "sha": (got or "")[:16], "manifest_sha": (want or "")[:16], "match": bool(f) and got == want}
        out["ok"] = out["ok"] and (out["faces"][cid]["match"] or not want)
    return out


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT)))
