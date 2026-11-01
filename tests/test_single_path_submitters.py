"""K-REN-134 唯一出图路径（RECALL MASTER_PICTURE R1/G7，总调度 11-01）：任何提交入口送出的首帧图都必须由唯一构建函数
（ns_agent.frame_job.build_first → ns_render.unified_frame.build_graph）产生，且不得含禁用 LoRA（config/gen_contract.json lora_banned）。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/pipeline", "tools/series10_imggen", "tools/prompt_v2"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

JOBS = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"
SCRIPT = ROOT / "data/import/script_v2.json"
BANNED = set(json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8")).get("lora_banned") or {})
pytestmark = pytest.mark.skipif(not JOBS.exists() or not SCRIPT.exists(), reason="series10 数据不在本机")


def _loras(g):
    return {n["inputs"].get("lora_name") for n in g.values() if "Lora" in n.get("class_type", "")}


def _upload(p):
    return "@upload:" + Path(p).resolve().relative_to(ROOT.resolve()).as_posix()


def test_stored_first_frame_jobs_are_unified_and_clean():
    d = json.loads(JOBS.read_text(encoding="utf-8"))
    for j in d["jobs"]:
        assert j.get("built_by") == "unified_frame", j["shot"]
        assert not (_loras(j["graph"]) & BANNED), j["shot"]
        assert "lin_wan_qi" not in json.dumps(j["graph"]) and "lnwan_qi" not in j["prompt"], j["shot"]


def test_imggen_frame_graph_equals_unified_builder():
    import imggen as IG
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    script = P.load_script()
    for shot in ("ep01-S1", "ep01-S4"):
        g, _p, refs = IG.frame_graph(shot, 4242)
        ep, sh = P.find_shot(script, shot)
        want, _e, _s = UF.build_graph(FJ.build_first(UF.project_for(script), ep, sh, script.globals), 4242, _upload,
                                      f"imggen_s10/{shot}_s4242")
        assert g == want
        assert not (_loras(g) & BANNED)


def test_submit_gate_rejects_banned_lora_graph():
    """手塞一个禁用 LoRA 进作业 → 生成契约 preflight（I8）拒交"""
    import image_jobs as IJ
    from ns_agent.gen_contract import preflight as PF
    j = json.loads(JOBS.read_text(encoding="utf-8"))["jobs"][0]
    j["loras"] = j["loras"] + [["lin_wan_qi_v1.safetensors", 0.6]]
    assert "I8" in [i.id for i in PF.check(IJ.contract_request(j)).blocking]


def test_no_submitter_source_hardcodes_banned_lora():
    """出图提交入口的代码里不得写死禁用 LoRA（对照实验工具 tools/ab/** 除外）"""
    files = ["tools/series10_imggen/imggen.py", "tools/pipeline/image_jobs.py", "tools/pipeline/submit_jobs.py",
             "services/render_router/ns_render/unified_frame.py", "services/render_router/ns_render/frame_edit.py",
             "services/agent/ns_agent/frame_job.py", "tools/assetmaster/frames_v2.py", "tools/autopilot/producer.py"]
    for f in files:
        p = ROOT / f
        if not p.exists():
            continue
        code = "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("#"))
        for b in BANNED:
            assert f'"{b}"' not in code and f"'{b}'" not in code, f"{f} 写死了禁用 LoRA {b}"
