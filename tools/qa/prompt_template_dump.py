"""提示词模板 v1 / v2 对照 dump（阶段 2.1，CODER-PT 11-05）：对某剧某集若干镜，编出 出图提示词（build_first）与 H3 视频提示词（compile_shot）
的 before（v1 现编译）/ after（v2 模板，force 覆盖开关、不写配置）各一份文本，外加 lint / L1 审计摘要。只读：不出图、不写 data/import。
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -X utf8 tools/qa/prompt_template_dump.py --run series10_v2 --episode 1 --shots 1,2,4,13 \
      --p4 data/pipeline/runs/series10_v2/staging/P4_ep01.L2_psm6.md --out data/ab/prompt_v2
--p4 给了就以当前导入稿为底合并这一集（import_script --merge-base）到 scratch 临时副本；不给 = 直接用当前导入稿。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/schema", "services/render_router", "services/agent", "services/recipes", "services/api", "tools/autopilot", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def scratch_import(run: str, p4: Path, out_dir: Path) -> Path:
    """P4 稿 → 临时导入副本（--merge-base 当前导入稿，只替换该稿里的集）；不进 data/import"""
    import runs as RN
    base = RN.script_path(run, ROOT)
    out = out_dir / f"script_v2.{p4.stem}.json"
    if out.exists() and out.stat().st_mtime >= p4.stat().st_mtime and out.stat().st_mtime >= base.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "tools/import_script.py"), "--script", str(p4), "-o", str(out), "--no-timeline", "--merge-base", str(base)]
    r = subprocess.run(cmd, capture_output=True, cwd=ROOT, timeout=900, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("临时导入失败：" + (r.stdout or b"").decode("utf-8", "replace")[-600:])
    return out


def h3_lint_summary(text: str, frames: int, dialogue: list[str]) -> dict:
    from ns_schema import h3_lint as L
    res = L.lint_h3(text, frames, mode="fl2va", dialogue=dialogue)
    return {"block": [f"{r['rule_id']}: {r['detail'][:80]}" for r in res if not r["ok"] and r.get("level") == "block"],
            "warn": [f"{r['rule_id']}: {r['detail'][:80]}" for r in res if not r["ok"] and r.get("level") == "warn"]}


def dump(run: str, ep_no: int, shots: list[int], import_path: Path, out: Path, recipes_path: bool = True) -> dict:
    import runs as RN
    os.environ.update(RN.run_env(run, ROOT))
    from ns_schema.script import ScriptImport
    from ns_schema import prompt_v2 as PV
    from ns_agent import frame_job as FJ
    from ns_agent import compiler as C
    from ns_agent import prompt_template_v2 as PT2
    from ns_agent.gen_contract import preflight as PF, style as ST
    sys.path.insert(0, str(ROOT / "tools" / "qa"))
    import l1_prompt_audit as A
    s = ScriptImport.model_validate(json.loads(import_path.read_text(encoding="utf-8")))
    e = next(x for x in s.episodes if int(x.number) == int(ep_no))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"run": run, "episode": ep_no, "import": str(import_path), "shots": {}}
    for sh in e.shots:
        if int(sh.index) not in shots:
            continue
        sid = f"ep{ep_no:02d}-S{sh.index}"
        seg = ST.segment_of(sh)[0] or "reality"
        dialogue = [d.text for d in sh.dialogue if d.text]
        rec = {"segment": seg}
        for tag, force in (("before", {"image": "v1", "video": "v1"}), ("after", {"image": "v2", "video": "v2"})):
            with PT2.force(**force):
                job = FJ.build_first(run, e, sh, s.globals)
                c = C.compile_shot(e, sh, s.globals, set(), image_style=ST.image_suffix(run, seg), framing_project=run)
            req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
            req.update(kind="image", project=run, framing_project=run, shot_id=f"{run}-{sid}")
            try:
                pf = PF.check(req)
                pf_ok, pf_why = bool(pf.ok), "；".join(pf.reasons())[:300]
            except Exception as ex:  # noqa: BLE001
                pf_ok, pf_why = None, f"{type(ex).__name__}: {ex}"[:300]
            banned, l1 = A.scan(job["prompt"], seg)
            vp = c.video_prompt
            frames = c.h3_frames or 0
            (out / f"{sid}.image.{tag}.txt").write_text(
                f"# {sid} image prompt — {tag} (template={job.get('prompt_template') or 'v1'}, chars={len(job['prompt'])})\n"
                f"# preflight={pf_ok} {pf_why}\n# L1 banned={banned} l1={l1}\n# negative: {job.get('negative')}\n\n{job['prompt']}\n",
                encoding="utf-8")
            lint = h3_lint_summary(vp, frames, dialogue)
            flat = PV.flat_light_hits(vp)
            (out / f"{sid}.video.{tag}.txt").write_text(
                f"# {sid} H3 prompt — {tag} (template={c.h3_template or 'v1'}, chars={len(vp)}, frames={frames})\n"
                f"# lint block={lint['block']}\n# lint warn={lint['warn']}\n# flat-light EN hits={flat}\n"
                f"# h3_norm={[x.get('why') for x in c.h3_norm]}\n\n{vp}\n", encoding="utf-8")
            rec[tag] = {"image_chars": len(job["prompt"]), "preflight": pf_ok, "preflight_why": pf_why, "banned": banned, "l1": l1,
                        "template": job.get("prompt_template") or "v1", "video_chars": len(vp), "video_template": c.h3_template or "v1",
                        "lint_block": lint["block"], "lint_warn": lint["warn"], "flat_light": flat,
                        "image_trace": job.get("prompt_template_trace")}
        summary["shots"][sid] = rec
    # 生产路径（ns_recipes.build_base）抽查：同一镜 v2 正文与 compile_shot 路径一致
    if recipes_path:
        try:
            from ns_recipes.spec_import import specs_from_import
            from ns_recipes import prompt as RP, prompt_v2 as RPV2
            specs = {x.index: x for x in specs_from_import(s, ep_no, with_assets=False)}
            same = {}
            for n in shots:
                sp = specs.get(n)
                if not sp or not sp.h3.text:
                    continue
                RPV2._FORCE["video"] = "v2"
                try:
                    b2 = RP.build_base(sp, {"prompt": {}}, "fl2va", sp.frames)
                finally:
                    RPV2._FORCE.clear()
                vp_after = (out / f"ep{ep_no:02d}-S{n}.video.after.txt").read_text(encoding="utf-8").split("\n\n", 1)[1]
                same[f"ep{ep_no:02d}-S{n}"] = b2["fields"]["integrated_multimodal_description"] in vp_after
                (out / f"ep{ep_no:02d}-S{n}.video.after.recipes.txt").write_text(
                    f"# ns_recipes.build_base fl2va, template v2; same body as compile_shot path: {same[f'ep{ep_no:02d}-S{n}']}\n# notes={b2['notes']}\n\n{b2['text']}\n",
                    encoding="utf-8")
            summary["recipes_path_same_body"] = same
        except Exception as ex:  # noqa: BLE001
            summary["recipes_path_error"] = f"{type(ex).__name__}: {ex}"[:300]
    tmp = out / "summary.json.tmp"                       # 原子写（ARCH_MAP §6）
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out / "summary.json")
    return summary


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--shots", default="1,2,4,13")
    ap.add_argument("--p4", type=Path, default=None, help="P4 稿（合并到 scratch 临时导入副本，不进 data/import）")
    ap.add_argument("--import-path", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "data/ab/prompt_v2")
    ap.add_argument("--scratch", type=Path, default=Path(tempfile.gettempdir()) / "ns_prompt_v2")
    a = ap.parse_args(argv)
    import runs as RN
    imp = a.import_path or (scratch_import(a.run, a.p4, a.scratch) if a.p4 else RN.script_path(a.run, ROOT))
    shots = [int(x) for x in a.shots.split(",") if x.strip()]
    r = dump(a.run, a.episode, shots, imp, a.out)
    for sid, rec in r["shots"].items():
        b, af = rec["before"], rec["after"]
        print(f"{sid}: image {b['image_chars']}→{af['image_chars']} 字 preflight {b['preflight']}→{af['preflight']} L1句 {bool(b['l1'])}→{bool(af['l1'])} | "
              f"video {b['video_chars']}→{af['video_chars']} 字 block {len(b['lint_block'])}→{len(af['lint_block'])} warn {len(b['lint_warn'])}→{len(af['lint_warn'])} "
              f"平光句 {b['flat_light']}→{af['flat_light']}")
        if af["preflight"] is False:
            print("   after preflight:", af["preflight_why"])
        if af["lint_block"]:
            print("   after lint block:", af["lint_block"])
    print("recipes_path_same_body:", r.get("recipes_path_same_body"), r.get("recipes_path_error", ""))
    print("→", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
