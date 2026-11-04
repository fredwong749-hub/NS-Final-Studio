"""L1 提示词验收（L-188）：对某剧某集逐镜 build_first（+ preflight），统计 L1 禁用句命中（必须 0）与 L1 句覆盖（每镜 >= 1）。
只读：不出图、不写数据。用法：
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -X utf8 tools/qa/l1_prompt_audit.py --run series10_v2 --episode 1 [--import-path 临时导入稿.json] [--no-preflight]
退出码 0 = 禁用句 0 命中 + L1 句每镜覆盖 + preflight 全过；否则 1。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BANNED = ("正面高亮", "把影子打平", "白幕反射补脸", "one continuous depth", "高反差", "crisp sharpness", "micro-contrast", "纪实杂志快照")
L1_REALITY = ("上侧 45°", "上侧45", "黑旗", "中灰")      # 现实段：任一命中
L1_FANTASY = ("暖金",)                                    # 幻想段：任一命中


def scan(prompt: str, segment: str) -> tuple[list[str], list[str]]:
    """→ (命中的禁用句, 命中的 L1 句)"""
    banned = [w for w in BANNED if w in prompt]
    l1 = [w for w in (L1_FANTASY if segment == "fantasy" else L1_REALITY) if w in prompt]
    return banned, l1


def audit(run: str, ep: int, import_path: Path | None = None, preflight: bool = True) -> dict:
    for p in ("packages/schema", "services/render_router", "services/agent", "services/recipes", "services/api"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.autopilot import runs as RN
    os.environ.update(RN.run_env(run, ROOT))
    from ns_schema.script import ScriptImport
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import preflight as PF, style as ST
    path = Path(import_path) if import_path else RN.import_path(run, ROOT)
    s = ScriptImport.model_validate(json.loads(path.read_text(encoding="utf-8")))
    e = next((x for x in s.episodes if int(x.number) == int(ep)), None)
    rows, hits = {}, {"banned": 0, "no_l1": 0, "pf_fail": 0}
    for sh in (e.shots if e else []):
        n = str(int(sh.index))
        if getattr(sh, "adult", False):
            continue
        job = FJ.build_first(run, e, sh, s.globals)
        seg = ST.segment_of(sh)[0]
        banned, l1 = scan(job["prompt"], seg)
        row = {"segment": seg, "banned": banned, "l1": l1}
        if preflight:
            req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
            req.update(kind="image", project=run, framing_project=run, shot_id=f"{run}-ep{int(ep):02d}-S{n}")
            pf = PF.check(req)
            row["preflight_ok"] = bool(pf.ok)
            row["preflight_why"] = "；".join(pf.reasons())[:200]
            hits["pf_fail"] += 0 if pf.ok else 1
        hits["banned"] += len(banned)
        hits["no_l1"] += 0 if l1 else 1
        rows[n] = row
    return {"run": run, "episode": ep, "shots": rows, "n": len(rows), **hits, "ok": bool(rows) and not any(hits.values())}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--import-path", type=Path, default=None)
    ap.add_argument("--no-preflight", action="store_true")
    a = ap.parse_args(argv)
    r = audit(a.run, a.episode, a.import_path, preflight=not a.no_preflight)
    for n, row in r["shots"].items():
        print(f"S{n:<3} {row['segment']:<8} 禁用句={row['banned'] or 0}  L1句={row['l1'] or '无'}  preflight={row.get('preflight_ok', '-')} {row.get('preflight_why', '')}")
    print(f"共 {r['n']} 镜：禁用句命中 {r['banned']}；缺 L1 句 {r['no_l1']} 镜；preflight 失败 {r['pf_fail']} 镜 → {'通过' if r['ok'] else '不通过'}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
