"""series10 视频全部用 Pika（项目方 11-01 ~18:0x L-088，取代 16:2x L-082 的“已通过的镜头不动”与 flush 回退 pdd2；K-REN-301 修订）。
- i2va_pika_flex 参数 = config/render_quality.json video_bases.bases.pika_flex；
- recipe_choice.json 的 face / noface / ref 默认全是 i2va_pika_flex；
- config/pipeline/video_policy.json pika_only（只管 series10_v1 来源的镜）：非 Pika 配方编译成 hold，逐镜写原因；
- flush_risk 命中 → hold“等 Pika 方案（泛红防护）”，不回退 i2va_pdd2。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/recipes", "packages/schema", "services/agent"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import registry as R  # noqa: E402

S10 = SimpleNamespace(source=SimpleNamespace(script_file="data/staging_v3/merged/x_series10_v1_ep01-10.md"))
OLD = SimpleNamespace(source=SimpleNamespace(script_file="data/import/old_60ep.md"))


def _pika_base():
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    return next(b for b in rq["video_bases"]["bases"] if b["id"] == "pika_flex")


def test_pika_recipe_matches_video_base():
    reg = R.load()
    assert not reg.validate()
    rc = reg.resolve("i2va_pika_flex")
    b = _pika_base()
    s = rc["sampling"]
    assert s["steps"] == b["steps"] and s["sampler"] == b["sampler"] and s["sigmas"] == b["sigmas"]
    assert s["shift_node"] is False and not (rc.get("two_stage") or {}).get("enabled")
    lo = rc["loras"]["pika_flex"]
    assert lo["file"] == b["lora"] and float(lo["strength"]) == b["lora_strength"]
    assert rc["keyframes"]["last_frame_mode"] == "use"
    assert rc.get("fallback") == [] and reg.raw["i2va_pika_flex"].get("blocked_action") == "hold"


def test_recipe_choice_all_pika():
    ch = json.loads((ROOT / "data/pipeline/runs/series10_v1/video/recipe_choice.json").read_text(encoding="utf-8"))
    assert {ch["face_default"], ch["noface_default"], ch["ref_default"]} == {"i2va_pika_flex"}
    assert ch.get("decision") == "L-088" and "皮卡" in ch.get("owner_quote", "")


def test_policy_holds_non_pika_and_flush_for_series10_only():
    reg = R.load()
    pol = C.video_policy()
    assert pol["pika_only"]["enabled"] and pol["pika_only"]["allowed"] == ["i2va_pika_flex"]
    assert C.hold_reason(reg, "i2va_pika_flex", [], S10) is None
    assert "不是 Pika" in C.hold_reason(reg, "i2va_pdd2", [], S10)
    assert "不是 Pika" in C.hold_reason(reg, "establishing", [], S10)
    assert "泛红防护" in C.hold_reason(reg, "i2va_pika_flex", ["flush_risk"], S10)
    assert C.hold_reason(reg, "i2va_pdd2", [], OLD) is None              # 旧项目不受政策影响
    assert C.blocked_swap(reg, "i2va_pika_flex", ["flush_risk"]) == ("i2va_pika_flex", None)


def test_hold_plan_shape():
    spec = SimpleNamespace(id="ep05-S4", rev=1, duration_s=6, spec_hash=lambda: "h")
    sel = SimpleNamespace(recipe_id="i2va_pika_flex", reasons=[], features={}, overlays=["flush_risk"])
    p = C._hold(spec, "i2va_pika_flex", sel, "等 Pika 方案（泛红防护）")
    assert p["status"].startswith("hold:") and p["graph"] == {} and p["lane"]["long"] is False and p["plan_hash"]


def test_vidgen_dispatch_rechecks_policy():
    """K-OPS-Q24：L-088 之前编的 jobs.json（two_person_ref2va / establishing 变体 ready）派单时必须 hold，Pika 变体照派"""
    sys.path.insert(0, str(ROOT / "tools/series10_video"))
    import vidgen as VG
    shot = {"variants": {"v1": {"status": "ready", "recipe": "two_person_ref2va", "variant": "v1"},
                         "b24": {"status": "ready", "recipe": "establishing", "variant": "b24"}}}
    rec = {"renders": []}
    assert VG.next_variant(shot, rec) is None
    assert "Pika" in VG.policy_hold(shot["variants"]["b24"])
    shot["variants"]["v1"]["recipe"] = "i2va_pika_flex"
    assert VG.next_variant(shot, rec) == "v1"
