"""可拍性判定（单一来源，K-WRT-H13；总调度 11-02 定：进 rubric 导入闸门，和 RSI 线 3 打分器同一套判法）。

逐镜按生产同一编译入口（tools/pipeline/image_jobs.frame_prompt_full → ns_agent.frame_job.compile_frame）编译首帧，判：
  孤儿描述   剧本 img 里写了名字的在画角色，编译后正文里名字没了；或分句归属人和剧本原文不一致（K-REN-901，判法 = tools/imglab/orphan_check.misowned）
  露脸冲突   同一首帧提示词既要求特写脸占比、又要求两张脸都清晰入画（特写 ≥2 人露脸，K-REN-902，判法 = ns_agent.framing.framing_clash）
读方：tools/script_rsi/rubric_audit.gate（导入闸门）、tools/script_rsi/line3_score.py（可拍性分项）、tools/script_rsi/autoflow.all_fails（补丁目标）。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools" / "pipeline", ROOT / "tools" / "autopilot", ROOT / "tools" / "imglab", ROOT / "packages" / "schema",
           ROOT / "services" / "agent", ROOT / "services" / "api", ROOT / "services" / "recipes", ROOT / "services" / "render_router",
           ROOT / "tools" / "prompt_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _orphan_check():
    spec = importlib.util.spec_from_file_location("orphan_check", ROOT / "tools" / "imglab" / "orphan_check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def shootable_rows(text: str, ep_no: int | None = None) -> list[dict]:
    """text = 带前言的剧本稿（一集或多集）。→ 每镜 {episode, shot, ok, lost, misowned, clash}；ep_no 给了就只判那一集"""
    import image_jobs as IJ
    import runs as RN
    from ns_agent import compiler as C
    from ns_agent import framing as FR
    from ns_agent.importer.script_md import import_script
    OC = _orphan_check()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "cand.md"
        f.write_text(text, encoding="utf-8")
        si = import_script(f)
    g = IJ.load_import().globals
    project = RN.primary_run(ROOT)          # 资产 / framing 项目键 = 主剧（剧名只许 runs.py 写死）
    rows = []
    for e in si.episodes:
        if ep_no is not None and e.number != ep_no:
            continue
        for sh in sorted(e.shots, key=lambda s: s.index):
            prompt, c, _sr, _plan = IJ.frame_prompt_full(e, sh, g, [], project)
            orig = C._strip_triggers(sh.img_prompt or "", list(sh.img_triggers or []))
            cast = [x.name for x in (sh.cast or []) if getattr(x, "visible", True)]
            body = c.image_body or ""
            lost = [n for n in cast if n in orig and n not in body]
            mis = OC.misowned(orig, body, cast) if cast else []
            clash = FR.framing_clash(prompt)
            rows.append({"episode": e.number, "shot": sh.index, "ok": not lost and not mis and not clash, "lost": lost,
                         "misowned": [f"{m['clause'][:20]}（{m['script_owner']}→{m['compiled_owner']}）" for m in mis],
                         "clash": clash})
    return rows


def why(row: dict) -> str:
    parts = []
    if row["lost"]:
        parts.append(f"编译后正文里丢了人名 {row['lost']}（这句描写会归给别人，K-REN-901）——描写外貌 / 动作 / 服装的分句都写人名主语")
    if row["misowned"]:
        parts.append(f"分句归属变了 {row['misowned']}（K-REN-901）——每个分句开头写清是谁")
    if row["clash"]:
        parts.append(f"特写里要求两张脸都清晰入画（K-REN-902：{row['clash']}）——特写只许一人露脸，另一人写背影 / 局部，或改成中景")
    return "；".join(parts)
