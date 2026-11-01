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


def test_flush_words_cover_redden_and_cn_variants():
    """VIDEO-RCA r1：ep05-S4 写 redden 原先拦不住；子串匹配，补 redden / reddening 与中文变体"""
    reg = R.load()
    words = reg.overlays["flush_risk"]["words"]
    for w in ("redden", "reddening", "泛红", "脸红", "涨红", "羞红", "发红"):
        assert w in words


def test_pika_dejudder_wired_before_upscale(monkeypatch, tmp_path):
    """VIDEO-RCA r1：Pika 片 J4 超门槛（或没打分）→ 合成前去抖（K-LOOP-004 tools/dejudder.py），放大版从去抖片做"""
    sys.path.insert(0, str(ROOT / "tools/series10_video"))
    import upscale_preview as U
    monkeypatch.setattr(U, "VID", tmp_path)
    (tmp_path / "scores").mkdir()
    cfg = {"enabled": True, "recipes": ["i2va_pika_flex"], "j4_gt": 1.25, "j4_z_ge": 3.0, "always": False}
    (tmp_path / "scores/ep01-S3__v1.json").write_text(json.dumps({"J4": 1.33, "J4_z": 6.2}), encoding="utf-8")
    (tmp_path / "scores/ep01-S4__v1.json").write_text(json.dumps({"J4": 1.05, "J4_z": 0.4}), encoding="utf-8")
    assert U.needs_dejudder({"shot": "ep01-S3", "chosen": "v1", "recipe": "i2va_pika_flex"}, cfg)[0] is True
    assert U.needs_dejudder({"shot": "ep01-S4", "chosen": "v1", "recipe": "i2va_pika_flex"}, cfg)[0] is False
    assert U.needs_dejudder({"shot": "ep01-S9", "chosen": "v1", "recipe": "i2va_pika_flex"}, cfg)[0] is True   # 未测 ≠ 通过
    assert U.needs_dejudder({"shot": "ep01-S3", "chosen": "v1", "recipe": "i2va_pdd2"}, cfg)[0] is False
    assert U.dejudder_cfg()["recipes"] == ["i2va_pika_flex"]


def test_vidgen_holds_rl_e3_prompt_and_pattern_parity():
    """AUDIT 20:15（K-OPS-Q24 扩到提示词）：16:56 旧编译稿里系统锚点句带 facing the camera 的 Pika 变体，派单时也要 hold"""
    sys.path.insert(0, str(ROOT / "tools/series10_video"))
    import vidgen as VG
    from ns_recipes import lint as LN
    assert VG.PROMPT_FACING_RE.pattern == LN.SYS_CAMERA_FACING_RE.pattern
    bad = {"status": "ready", "recipe": "i2va_pika_flex", "variant": "v1",
           "prompt": "x. The frame keeps 林晚 at center facing the camera. y"}
    ok = dict(bad, prompt="x. The frame keeps 林晚 at center, angled off to the side. y", variant="s2")
    assert "RL-E3" in VG.prompt_hold(bad) and VG.prompt_hold(ok) is None
    assert LN.system_facing_camera(bad["prompt"]) and LN.system_facing_camera(ok["prompt"]) is None
    shot = {"variants": {"v1": bad, "s2": ok}}
    assert VG.next_variant(shot, {"renders": []}) is None or VG.next_variant(shot, {"renders": []}) == "s2"
    assert VG.policy_ok(bad) is False and VG.policy_ok(ok) is True
