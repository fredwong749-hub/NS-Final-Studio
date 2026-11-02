"""PROMPTFIX 11-02 19:1x（L-125 / L-126 V2 完全切割）：编译层接 V2 资产包。
I-14 按剧取路径（run_paths）、K-REN-958 造型封闭 + 本地专用资产只许本地道、K-REN-959 品牌字样。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import run_paths as RP  # noqa: E402

V2 = "series10_v2"
need_v2 = pytest.mark.skipif(not AR.manifest_rel(V2) or not (ROOT / AR.manifest_rel(V2)).is_file(), reason="V2 资产包清单缺")


# ---------------------------------------------------------------- I-14 run_paths
def test_run_paths_sandbox_is_legacy(tmp_path):
    assert RP.script_json(tmp_path) == tmp_path / "data/import/script_v2.json"
    assert RP.looks_dir(tmp_path) == tmp_path / "data/looks"
    assert RP.renders_dir(tmp_path) == tmp_path / "data/renders"


def test_run_paths_v2_never_resolves_v1(tmp_path, monkeypatch):
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    (tmp_path / "tools/autopilot/runs.py").write_text((ROOT / "tools/autopilot/runs.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({
        "legacy_unprefixed_run": "series10_v1", "primary": "series10_v2",
        "runs": {"series10_v1": {"status": "paused"}, "series10_v2": {"status": "producing", "assets_manifest": "assets_v2/manifest.json"}}}),
        encoding="utf-8")
    monkeypatch.delenv("NS_SCRIPT_JSON", raising=False)
    monkeypatch.delenv("NS_RENDERS_DIR", raising=False)
    monkeypatch.delenv("NS_RUN", raising=False)
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)
    RP._runs_mod.cache_clear()
    try:
        r = RP.current_run(tmp_path)
        assert r == "series10_v2"
        assert RP.script_json(tmp_path) == tmp_path / "data/import/runs/series10_v2/script_v2.json"
        assert RP.looks_dir(tmp_path) != tmp_path / "data/looks"
        assert RP.renders_dir(tmp_path) == tmp_path / "data/renders/series10_v2"
        monkeypatch.setenv("NS_RUN", "series10_v1")
        assert RP.looks_dir(tmp_path) == tmp_path / "data/looks"        # V1 自己照旧
    finally:
        RP._runs_mod.cache_clear()


def test_no_hard_v1_paths_left_in_compile_modules():
    import re
    pat = re.compile(r'"data"\s*/\s*"import"\s*/\s*"script_v2\.json"|"data"\s*/\s*"looks"(?!\s*\))|"data"\s*/\s*"renders"')
    for f in ("compiler.py", "frame_spec.py", "bible.py", "state_timeline.py", "asset_revs.py", "lora_registry.py",
              "prompt_snapshot.py", "framing.py"):
        src = (ROOT / "services/agent/ns_agent" / f).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert not pat.search(code), f"{f} 仍写死 V1 路径"


# ---------------------------------------------------------------- K-REN-958 造型封闭 + 本地专用
@need_v2
def test_lead_f_looks_closed_and_routes():
    cl = AR.closed_looks(V2)
    assert cl.get("lead_f") == {"O1", "O2", "O3", "O4"}
    meta = AR.manifest_meta(V2)
    assert meta["look:lead_f:O2"]["route"] == "local_only" and meta["look:lead_f:O3"]["route"] == "local_only"
    assert meta["look:lead_f:O1"]["route"] == "server_ok"
    assert meta["item:lead_f:J1"]["route"] == "local_only" and meta["item:lead_f:J2"]["route"] == "local_only"
    assert meta["item:lead_f:SH2"]["no_brand"]


class _SR:
    def __init__(self, chars):
        self.characters = chars


class _Slot:
    def __init__(self, file, members=None):
        self.file, self.members = file, members or [{"file": file}]


class _Plan:
    def __init__(self, slots):
        self.slots = slots


@need_v2
def test_plan_route_local_only_from_look_and_board_member():
    meta = AR.manifest_meta(V2)
    j1_file = next(f for f, m in meta.items() if not f.startswith(("item:", "look:")) and m.get("item") == "J1")
    r, why = AR.plan_route(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O2"}]), _Plan([]))
    assert r == "local_only" and "O2" in why[0]
    r, why = AR.plan_route(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O1"}]),
                           _Plan([_Slot("data/pipeline/runs/series10_v2/images/refboards/board_x.png",
                                        [{"file": "x.png"}, {"file": j1_file}])]))
    assert r == "local_only"                                         # 参考板里任何一格是本地专用 → 整镜本地
    r, why = AR.plan_route(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O4"}]), _Plan([]))
    assert r == "server_ok" and not why


def _pf(req):
    from ns_agent.gen_contract import preflight as PF
    base = {"kind": "image", "model": "qwen_image_2.1", "cast": [], "prompt": "近景构图，女主站在窗边", "refs": [],
            "asset_refs": {"slots": [], "characters": []}, "loras": [], "compiled_by": "ns_agent.frame_job.build_first",
            "project": V2, "framing_project": V2, "shot_id": "ep01-S1"}
    base.update(req)
    return {i.id: i for i in PF.check(base).items}


@need_v2
def test_preflight_i12_blocks_local_only_on_server():
    # L-128：gpu33 / gpu36 / 笔记本都是项目方自有机器（hosts.json owner_controlled=true）→ 放行；不认识的机器 / 没给道 → 挡
    assert _pf({"route": "local_only", "route_reasons": ["女主 造型 O2"], "lane": "gpu36:1"})["I12"].status == "pass"
    assert _pf({"route": "local_only", "route_reasons": ["x"], "lane": "laptop:0"})["I12"].status == "pass"
    assert _pf({"route": "local_only", "route_reasons": ["x"], "lane": "rented99:0"})["I12"].status == "fail"
    assert _pf({"route": "local_only", "route_reasons": ["x"]})["I12"].status == "fail"          # 没给道 = 失败关闭
    assert _pf({"route": "server_ok", "lane": "rented99:0"})["I12"].status == "pass"


@need_v2
def test_plan_adult_marks_owner_trigger_only():
    sr = _SR([{"character": "lead_f", "name": "女主", "look": "O3"}])
    assert AR.plan_adult(V2, sr, _Plan([]))
    assert not AR.plan_adult(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O1"}]), _Plan([]))


def test_producer_blocks_adult_job_without_owner_trigger():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert 'if job.get("adult") and not ({f"first:{sid}", f"{self.p.run_id}/first:{sid}"} & trig)' in src   # FACTORY 19:4x：原写法引用了未定义的 o（syntax_guard E3）


# ---------------------------------------------------------------- K-REN-959 品牌字样
def test_brand_hits():
    assert AR.brand_hits("黑色漆皮细带露趾高跟凉鞋（脚踝扣带）") == []
    assert "Louboutin" in AR.brand_hits("穿 Louboutin 红底鞋")
    assert AR.brand_hits("SLV 款") == [] and "LV" in AR.brand_hits("手拿 LV 包")


@need_v2
def test_preflight_i13_blocks_brand_words():
    assert _pf({"prompt": "女主穿 Christian Louboutin 高跟鞋"})["I13"].status == "fail"
    assert _pf({"prompt": "女主穿黑色漆皮细带露趾高跟凉鞋"})["I13"].status == "pass"


@need_v2
def test_no_brand_slot_line():
    meta = AR.manifest_meta(V2)
    sh2 = next(f for f, m in meta.items() if not f.startswith(("item:", "look:")) and m.get("item") == "SH2")
    sr = AR.ShotRefs("ep01-S1", V2, "全景", None, ["feet"], "lead_f", [{"character": "lead_f", "name": "女主", "presence": "在画"}],
                     [AR.Ref("item", "lead_f", sh2, "鞋：黑色漆皮细带露趾高跟凉鞋", 2, "feet", "manifest", "SH2", "O4")], [], [])
    plan = AR.plan_slots(sr, capacity=3)
    assert plan.slots[0].line.endswith(AR.NO_BRAND_NOTE)
    assert not AR.brand_hits(plan.prompt_prefix)
