"""W26 G3 探针：按剧环境（runs.run_env）在隔离子进程里对每镜调唯一编译入口 ns_agent.frame_job.build_first，
打印 SMOKE_REFS {镜号: {cast, refs, face_files, missing_refs, asset_ref_keys, error}}。只读，不出图、不写任何文件。

  .venv/Scripts/python.exe eval/smoke/refs_probe.py --run smoke_v2 --episode 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/schema", "services/render_router", "services/agent", "services/recipes"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def _exists(f: str) -> bool:
    p = Path(f)
    p = p if p.is_absolute() else ROOT / f
    return p.is_file()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    a = ap.parse_args(argv)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.autopilot import runs as RN
    from ns_schema.script import ScriptImport
    from ns_agent import frame_job as FJ
    s = ScriptImport.model_validate(json.loads(RN.import_path(a.run, ROOT).read_text(encoding="utf-8")))
    e = next((x for x in s.episodes if int(x.number) == a.episode), None)
    rows: dict[str, dict] = {}
    for sh in (e.shots if e else []):
        n = str(int(sh.index))
        try:
            job = FJ.build_first(a.run, e, sh, s.globals)
            refs = [str(r) for r in job.get("refs") or []]
            faces = [str(r) for r in job.get("face_files") or []]
            ar = job.get("asset_refs") or {}
            rows[n] = {"cast": list(job.get("cast") or []), "refs": refs, "face_files": faces,
                       "missing_refs": [r for r in refs + faces if not _exists(r)],
                       "asset_ref_keys": sorted(ar.keys()) if isinstance(ar, dict) else [], "loras": job.get("loras") or [],
                       "error": None}
        except Exception as ex:  # noqa: BLE001  探针：编译出错 = 这一镜没解析出参考（原因原样带回）
            rows[n] = {"cast": [], "refs": [], "face_files": [], "missing_refs": [], "asset_ref_keys": [], "loras": [],
                       "error": f"{type(ex).__name__}: {ex}"[:400]}
    print("SMOKE_REFS " + json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
