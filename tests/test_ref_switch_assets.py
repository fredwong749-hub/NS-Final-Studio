"""DATA_MAP §6-1（REFLOCK 11-01）：资产项目里“切换本镜参考”必须写进出图实际读的来源（asset_refs），切换后下一次出图挂的参考随之改变。"""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "services/api"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from fastapi import HTTPException  # noqa: E402
from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_api import ref_switch as RS  # noqa: E402
from ns_api import ref_switch_assets as RA  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_schema.script import ScriptImport  # noqa: E402

SCRIPT = ROOT / "data/import/script_v2.json"
pytestmark = pytest.mark.skipif(not SCRIPT.exists() or not AR.project_cfg("series10_v1"), reason="series10 不在本机")


def _pick_full_shot(default="ep01-S3"):
    """CODE-RSI 11-01（K-OPS-C02）：不写死镜号。18:24 返修稿重排后 ep01-S3 变近景、鞋不入画，换鞋断言失去前提；
    改成选第一个“林晚单人在画、脚可见”的镜（换鞋 / 换场景都要求鞋在画）"""
    import json as _json
    if not SCRIPT.exists():
        return default
    for ep in _json.loads(SCRIPT.read_text(encoding="utf-8"))["episodes"]:
        for sh in ep["shots"]:
            cast = [c["name"] for c in sh.get("cast") or [] if c.get("presence") == "在画" and not c.get("part")]
            if cast == ["林晚"] and "feet" in AR.visible_zones(sh.get("img_prompt") or "")[2]:
                return f"ep{ep['number']:02d}-S{sh['index']}"
    return default


SHOT = _pick_full_shot()


@pytest.fixture
def env(tmp_path, monkeypatch):
    reg = ROOT / AR.project_cfg("series10_v1")["shot_looks_file"]
    tmp_reg = tmp_path / "shot_looks.json"
    if reg.exists():
        shutil.copy(reg, tmp_reg)
    cfg = json.loads(AR.CFG.read_text(encoding="utf-8"))
    cfg["projects"]["series10_v1"]["shot_looks_file"] = str(tmp_reg)
    # 参考板（超槽拼图）写到临时目录：原来落在真实 data/pipeline/runs/series10_v1/images/refboards，被 real_data_guard 拦下
    # （RSI r3，总调度 11-01 指派：测试本身的 bug，K-OPS-Q03）
    cfg["projects"]["series10_v1"]["board_dir"] = str(tmp_path / "refboards")
    monkeypatch.setattr(AR, "_cfg", lambda: cfg)
    monkeypatch.setattr(AR, "HUB_EP_LOOKS", tmp_path / "hub_episode_looks.json")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    return ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))


def _body(**kw):
    return RS.RefsBody(**kw)


def _plan(script):
    ep, shot = P.find_shot(script, SHOT)
    return FJ.build_first("series10_v1", ep, shot, script.globals)


def test_view_shape_matches_old_contract(env):
    v = RA.view(env, SHOT)
    assert {"shot_id", "episode", "scene_id", "characters", "scene", "ref_group"} <= set(v)
    c = v["characters"][0]
    assert {"id", "name", "effective", "source", "episode_default", "layers", "options"} <= set(c)
    assert {"looks", "parts"} <= set(c["options"]) and c["effective"]["look"] == "A"


def test_switch_look_changes_next_render_refs(env):
    before = _plan(env)
    assert any("lookA" in r for r in before["refs"])
    RA.apply(env, SHOT, _body(scope="shot", change={"characters": {"林晚": {"look": "B"}}}))
    after = _plan(env)
    lw = next(c for c in after["asset_refs"]["characters"] if c["character"] == "lin_wan")
    assert lw["look"] == "B" and lw["look_how"] == "shot_override"
    assert after["refs"] != before["refs"] and any("lookB" in r for r in after["refs"])
    assert RA.view(env, SHOT)["characters"][0]["source"] == "shot"
    RA.apply(env, SHOT, _body(scope="shot", change={"reset": True}))
    assert _plan(env)["refs"] == before["refs"]


def test_switch_part_and_scene(env):
    RA.apply(env, SHOT, _body(scope="shot", change={"characters": {"林晚": {"parts": {"shoes": "lw-shoes-up-62fd9e"}}},
                                                    "scene": "none"}))
    job = _plan(env)
    slots = job["asset_refs"]["slots"]
    assert any(m.get("item_id") == "lw-shoes-up-62fd9e" for s in slots for m in s["members"])
    assert not any(s["kind"] == "scene" for s in slots)
    assert not any(m["kind"] == "场景缺图" for m in job["asset_refs"]["missing"])


def test_episode_scope_owner_only_and_priority(env):
    with pytest.raises(HTTPException):
        RA.apply(env, SHOT, _body(scope="episode", change={"characters": {"林晚": {"look": "C"}}}))
    RA.apply(env, SHOT, _body(scope="shot", change={"characters": {"林晚": {"look": "B"}}}))
    RA.apply(env, SHOT, _body(scope="episode", by="owner", change={"characters": {"林晚": {"look": "C"}}}))
    lw = next(c for c in _plan(env)["asset_refs"]["characters"] if c["character"] == "lin_wan")
    assert lw["look"] == "C" and lw["look_how"] == "hub_episode"        # 整集排期 > 逐镜（优先级不变）


def test_invalid_choice_rejected(env):
    with pytest.raises(HTTPException):
        RA.apply(env, SHOT, _body(scope="shot", change={"characters": {"林晚": {"look": "Z"}}}))
    with pytest.raises(HTTPException):
        RA.apply(env, SHOT, _body(scope="shot", change={"characters": {"林晚": {"parts": {"shoes": "no-such-item"}}}}))
