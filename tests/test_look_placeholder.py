"""@look:<角色>（Ref2VA 造型槽，K-REN-303）：除 tools/series10_video/build_jobs.py 外，iterate_loop 提交器与 ns_api.recipe_render
也要认（ITERAUDIT 11-01；PRODUCER 代 AUTOPILOT，总调度批准）。来源同 build_jobs：计划 ref_slots 的 outfit 槽
（ns_recipes.compiler.look_slots：首帧 contract.asset_refs 的造型，缺了再 asset_refs.resolve_shot）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "services/render_router", "packages/schema", "tools/iterate_loop", "services/recipes"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def test_submitter_maps_look_slots():
    import submitter as S
    plan = {"plan_hash": "h", "recipe": {"id": "ref2va"}, "graph": {}, "ref_slots": [
        {"role": "identity", "character": "林晚", "path": "data/a.png"},
        {"role": "outfit", "character": "林晚", "path": "data/cache/look_a.png"},
        {"role": "outfit", "character": "顾沉", "path": None, "missing": "解不出本镜造型"}]}
    rp = S.recipe_plan_body(plan, with_graph=True)
    assert rp["images"] == {"@ref:林晚": "data/a.png", "@look:林晚": "data/cache/look_a.png"}


def test_recipe_render_accepts_look_placeholder(tmp_path):
    from ns_api import recipe_render as RR
    node = next(iter(RR.VIDEO_NODES))
    g = {"1": {"class_type": "LoadImage", "inputs": {"image": "@look:林晚"}},
         "2": {"class_type": node, "inputs": {}},
         "3": {"class_type": "SaveVideo", "inputs": {}}}
    errs = RR.validate_graph(g, {})
    assert not any("未知占位符" in e for e in errs) and any("@look:林晚" in e and "没有给参考图路径" in e for e in errs)
    ok = next(p for p in (ROOT / "data").rglob("*.png"))
    errs = RR.validate_graph(g, {"@look:林晚": str(ok.relative_to(ROOT)).replace("\\", "/")})
    assert not any("@look" in e for e in errs)
    g["1"]["inputs"]["image"] = "@bogus:x"
    assert any("未知占位符" in e for e in RR.validate_graph(g, {}))
