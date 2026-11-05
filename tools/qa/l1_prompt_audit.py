"""L1 提示词验收（L-188）：对某剧某集逐镜 build_first（+ preflight），统计 L1 禁用句命中（必须 0）与 L1 句覆盖（每镜 >= 1）。
只读：不出图、不写数据。用法：
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -X utf8 tools/qa/l1_prompt_audit.py --run series10_v2 --episode 1 [--import-path 临时导入稿.json] [--no-preflight]
退出码 0 = 禁用句 0 命中 + L1 句每镜覆盖 + preflight 全过；否则 1。
--h3（阶段 2.1，CODER-PT 11-05）：另对编译后的 H3 视频提示词（compile_shot.video_prompt）审计英文平光句（ns_schema.prompt_v2.FLAT_LIGHT_EN，
例 "bright ring light from the front flattening the shadows"）与 lint block 数；命中 > 0 也算不通过。"""
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


def scan_h3(video_prompt: str, frames: int, dialogue: list[str] | None = None) -> tuple[list[str], list[str]]:
    """H3 视频提示词 → (英文平光句命中, lint block 规则号)。平光句表：ns_schema.prompt_v2.FLAT_LIGHT_EN"""
    from ns_schema import prompt_v2 as PV
    from ns_schema import h3_lint as L
    flat = PV.flat_light_hits(video_prompt)
    blocks: list[str] = []
    if (video_prompt or "").startswith(L.ALIGN_PREFIX):
        res = L.lint_h3(video_prompt, frames or None, mode="fl2va", dialogue=dialogue)
        blocks = [r["rule_id"] for r in res if not r["ok"] and r.get("level") == "block"]
    return flat, blocks


def audit(run: str, ep: int, import_path: Path | None = None, preflight: bool = True, h3: bool = False) -> dict:
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
    if h3:
        hits["h3_flat"] = 0
        hits["h3_block"] = 0
        # AUDIT-RULES 11-05：模板默认句（run_style prompt_template_v2.lighting_en / constraint_en）里不得写死“ring light + front”组合
        from ns_schema import prompt_v2 as PV
        from ns_agent import prompt_template_v2 as PT2
        tpl_hits = PV.template_default_hits(PT2.options())
        hits["h3_tpl"] = len(tpl_hits)
    for sh in (e.shots if e else []):
        n = str(int(sh.index))
        if getattr(sh, "adult", False):
            continue
        job = FJ.build_first(run, e, sh, s.globals)
        seg = ST.segment_of(sh)[0]
        banned, l1 = scan(job["prompt"], seg)
        row = {"segment": seg, "banned": banned, "l1": l1, "template": job.get("prompt_template") or "v1"}
        if preflight:
            req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
            req.update(kind="image", project=run, framing_project=run, shot_id=f"{run}-ep{int(ep):02d}-S{n}")
            pf = PF.check(req)
            row["preflight_ok"] = bool(pf.ok)
            row["preflight_why"] = "；".join(pf.reasons())[:200]
            hits["pf_fail"] += 0 if pf.ok else 1
        if h3:   # 阶段 2.1：H3 视频提示词的 L1 英文审计（平光句）+ lint block
            from ns_agent import compiler as C
            c = C.compile_shot(e, sh, s.globals, set(), image_style=ST.image_suffix(run, seg), framing_project=run)
            flat, blocks = scan_h3(c.video_prompt, c.h3_frames, [d.text for d in sh.dialogue if d.text])
            row.update(h3_flat=flat, h3_block=blocks, h3_template=c.h3_template or "v1")
            hits["h3_flat"] += len(flat)
            hits["h3_block"] += len(blocks)
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
    ap.add_argument("--h3", action="store_true", help="另审计 H3 视频提示词：英文平光句 + lint block（阶段 2.1）")
    a = ap.parse_args(argv)
    r = audit(a.run, a.episode, a.import_path, preflight=not a.no_preflight, h3=a.h3)
    for n, row in r["shots"].items():
        h3s = f"  H3平光句={row.get('h3_flat') or 0} block={row.get('h3_block') or 0} 模板={row.get('h3_template')}" if a.h3 else ""
        print(f"S{n:<3} {row['segment']:<8} 禁用句={row['banned'] or 0}  L1句={row['l1'] or '无'}  preflight={row.get('preflight_ok', '-')} {row.get('preflight_why', '')}{h3s}")
    h3t = f"；H3 平光句 {r['h3_flat']}、lint block {r['h3_block']}、模板默认句 ring light+front {r.get('h3_tpl', 0)}" if a.h3 else ""
    print(f"共 {r['n']} 镜：禁用句命中 {r['banned']}；缺 L1 句 {r['no_l1']} 镜；preflight 失败 {r['pf_fail']} 镜{h3t} → {'通过' if r['ok'] else '不通过'}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
