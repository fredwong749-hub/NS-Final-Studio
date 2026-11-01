"""命令行：
  .venv/Scripts/python.exe -m ns_recipes.cli validate
  .venv/Scripts/python.exe -m ns_recipes.cli specs   --episode 2 [--script x.md] [--out data/recipes_out/ep02]
  .venv/Scripts/python.exe -m ns_recipes.cli compile --episode 2 [--shot ep02-S2] [--attempt 1] [--out …]
（PYTHONPATH 需含 services/recipes；tools/iterate_loop/loop.py 会自己加）
specs 输出：每镜 Shot Spec JSON + missing.md（缺字段清单，交写作方 / 资产方）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ns_schema.shot_spec import check_sequence, missing_fields

from . import compiler as C
from . import registry as R
from . import spec_import as SI

ROOT = R.ROOT


def load_specs(episode: int, script: str | None):
    if script:
        return SI.specs_from_markdown(Path(script), episode)
    from ns_render import pipeline as P
    return SI.specs_from_import(P.load_script(), episode)


def missing_report(specs) -> str:
    rows = [m for s in specs for m in missing_fields(s)] + check_sequence(specs)
    lines = ["# Shot Spec 缺字段清单（自动生成，只列格式 / 可实现性，不评内容）", "",
             "| 镜 | 字段 | 规则 | 级别 | 交给 | 说明 | 增补规则小节 |", "|---|---|---|---|---|---|---|"]
    for m in rows:
        lines.append(f"| {m.shot} | {m.field} | {m.rule} | {m.severity} | {m.owner} | {m.message} | {m.addendum or ''} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    for name in ("specs", "compile"):
        p = sub.add_parser(name)
        p.add_argument("--episode", type=int, required=True)
        p.add_argument("--script")
        p.add_argument("--shot")
        p.add_argument("--attempt", type=int, default=1)
        p.add_argument("--out")
    a = ap.parse_args(argv)
    reg = R.load()
    if a.cmd == "validate":
        errs = reg.validate()
        print("\n".join(errs) or f"OK：{len(reg.ids(True))} 个配方、{len(reg.overlays)} 个 overlay，provenance 完整")
        return 1 if errs else 0
    specs = load_specs(a.episode, a.script)
    if a.shot:
        specs = [s for s in specs if s.id == a.shot]
    out = Path(a.out) if a.out else ROOT / "data" / "recipes_out" / f"ep{a.episode:02d}"
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "specs":
        for s in specs:
            (out / f"{s.id}.spec.json").write_text(s.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
        (out / "missing.md").write_text(missing_report(specs), encoding="utf-8")
        print(f"{len(specs)} 镜 → {out}")
        return 0
    for s in specs:
        plan = C.compile_shot(s, reg, attempt=a.attempt)
        (out / f"{s.id}.a{a.attempt}.plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(s.id, plan["status"], plan["recipe"]["id"], plan.get("mode"), plan["plan_hash"][:12],
              [i["code"] for i in plan.get("lint", []) if i["level"] == "error"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
