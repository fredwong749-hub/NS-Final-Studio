"""ARCH：video-jobs 的 recipe_plan 接入点（take 记 plan_hash；graph 原样出片 + 校验）。假 ComfyUI，不碰 GPU。"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "recipes"))

from ns_api import recipe_render as RR  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import registry as R  # noqa: E402
from ns_render import pipeline as P  # noqa: E402

from test_readiness import env, script  # noqa: E402,F401
from test_recipes_engine import mk  # noqa: E402
from test_video_jobs_v1 import SHOT, _frame, _wait, fake  # noqa: E402,F401


def _plan(**kw):
    reg = R.load(learned_path=ROOT / "tests" / "fixtures" / "_no_learned.yaml")
    return C.compile_shot(mk(), reg, **kw)


def test_recipe_plan_without_graph_annotates_take(fake):
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    r = c.post(f"/api/shots/{SHOT}/video-jobs",
               json={"base": "official_turbo", "recipe_plan": {"plan_hash": "abc123", "recipe_id": "static_emotion"}})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t["params"]["recipe"] == {"plan_hash": "abc123", "recipe_id": "static_emotion"}
    assert t["params"]["base"] == "official_turbo"                  # 原有字段保留


def test_recipe_graph_submitted_as_is(fake):
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    plan = _plan()
    body = {"recipe_plan": {"plan_hash": plan["plan_hash"], "recipe_id": plan["recipe"]["id"], "graph": plan["graph"]},
            "seed": 7}
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json=body)
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j
    wf = fc.submitted[-1]
    want = copy.deepcopy(plan["graph"])
    want["200"]["inputs"]["image"] = wf["200"]["inputs"]["image"]
    want["129"]["inputs"]["noise_seed"] = 7
    assert wf == want                                               # 除首帧文件名 / 种子外与计划逐字相同
    assert not wf["200"]["inputs"]["image"].startswith("@")
    t = [t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video"][-1]
    assert t["params"]["method"] == "recipe_graph" and t["workflow"] == "recipe_graph"
    assert t["params"]["recipe"]["plan_hash"] == plan["plan_hash"]
    assert t["params"]["recipe"]["graph_sha"] == RR.graph_sha(plan["graph"])


def test_recipe_graph_rejected(fake):
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    plan = _plan()
    bad = copy.deepcopy(plan["graph"])
    bad["999"] = {"class_type": "TeaCache", "inputs": {"model": ["127", 0]}}
    r = c.post(f"/api/shots/{SHOT}/video-jobs",
               json={"recipe_plan": {"plan_hash": "x", "recipe_id": "y", "graph": bad}})
    assert r.status_code == 422 and "TeaCache" in r.json()["detail"]
    ref = _plan(recipe_id="two_person_ref2va")
    r = c.post(f"/api/shots/{SHOT}/video-jobs",
               json={"recipe_plan": {"plan_hash": "x", "recipe_id": "y", "graph": ref["graph"],
                                     "images": {"@ref:林晚": "../../etc/passwd"}}})
    assert r.status_code == 422 and "参考图" in r.json()["detail"]
    assert not fc.submitted


def test_validate_graph_unit():
    plan = _plan()
    assert RR.validate_graph(plan["graph"]) == []
    g = copy.deepcopy(plan["graph"])
    g["125"]["inputs"]["latent_image"] = ["nope", 1]
    assert any("nope" in e for e in RR.validate_graph(g))
    ref = _plan(recipe_id="two_person_ref2va")
    assert any("@ref:林晚" in e for e in RR.validate_graph(ref["graph"], {}))
