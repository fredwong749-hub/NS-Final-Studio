"""
G2 母版候选任务（T43）：为新剧角色出 3 档写实强度 × 2 种子的候选任务，写进 data/jobs/queue/（gpu_grab 消费）。
不出图、不用 GPU、从不自动选母版（项目方在 G2 挑）。配方见 services/orchestrator/ns_orch/g2_candidates.py。

    uv run python tools/g2_candidates.py scan --project <slug>                 # 所有已确认且有参考图的角色（已出过的跳过）
    uv run python tools/g2_candidates.py emit --project <slug> --char char01   # 单个角色（默认最新上传的参考图）
        [--ref assets/characters/char01/refs/ref_xxx.png] [--kind stylised|photo] [--force] [--dry-run]
    uv run python tools/g2_candidates.py status --project <slug> --char char01 # 候选落盘情况（只读）
"""
from __future__ import annotations

import argparse
import json
import sys

from ns_api.project_ctx import get_project
from ns_orch import g2_candidates as G


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "emit", "status"):
        p = sub.add_parser(name)
        p.add_argument("--project", default=None, help="项目 slug（默认《为他而骚》）")
        if name != "scan":
            p.add_argument("--char", required=True)
        if name != "status":
            p.add_argument("--kind", choices=("stylised", "photo"), default=None,
                           help="参考图是风格化（加 Anything2Real）还是已是照片质感；默认读人物卡 reference_kind，否则 stylised")
            p.add_argument("--force", action="store_true", help="同一参考图已出过也重出")
            p.add_argument("--dry-run", action="store_true", help="只打印，不写队列")
        if name == "emit":
            p.add_argument("--ref", default=None, help="项目内相对路径；默认最新上传的参考图")
    a = ap.parse_args(argv)
    ctx = get_project(a.project)
    if a.cmd == "status":
        print(json.dumps(G.candidates_status(ctx, a.char), ensure_ascii=False, indent=1))
        return 0
    kw = dict(reference_kind=a.kind, force=a.force, dry_run=a.dry_run)
    if a.cmd == "scan":
        rows = G.scan(ctx, **kw)
    else:
        try:
            rows = [{"character": a.char, **G.emit(ctx, a.char, ref=a.ref, **kw)}]
        except G.G2Blocked as e:
            print("blocked:", e)
            return 2
    for r in rows:
        doc = r.pop("doc", None)
        print(json.dumps(r, ensure_ascii=False))
        if doc and a.dry_run:
            for j in doc["jobs"]:
                print(f"  {j['id']}  seed={j['seed']}  lora={j['lora']}  → {j['out_dir']}{j['file']}")
    print("母版由项目方在 G2 从候选里挑；本工具不写 master.png。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
