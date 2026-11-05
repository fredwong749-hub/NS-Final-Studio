"""L-191：首帧 35 步 base 档（按剧开关，默认关）+ 人数闸。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/autopilot", "tools/pipeline", ""):
    sys.path.insert(0, str(ROOT / p))

from ns_agent import frame_job as FJ  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402
from tools.vqa import accept as ACC  # noqa: E402
import producer as PR  # noqa: E402


def test_default_config_is_preview_for_all_runs():
    assert FJ.first_frame_tier("series10_v2") == ("preview", {})
    assert FJ.first_frame_tier("series10_v1") == ("preview", {})


def test_tier_switch_reads_config(monkeypatch, tmp_path):
    cfg = {"first_frame_tier": {"runs": {"series10_v2": "base35"}, "base35": {"unet": "base", "steps": 35, "cfg": 3.0}}}
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "render_quality.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(FJ, "_ROOT", tmp_path)
    assert FJ.first_frame_tier("series10_v2") == ("base35", {"unet": "base", "steps": 35, "cfg": 3.0})
    assert FJ.first_frame_tier("series10_v1")[0] == "preview"


def test_build_graph_applies_tier_overrides():
    job = {"prompt": "p", "refs": [], "negative": "neg", "tier": "base35",
           "tier_overrides": {"unet": "base", "steps": 35, "cfg": 3.0, "sampler": "euler", "scheduler": "simple"}}
    wf, eff, _ = UF.build_graph(job, 1, lambda f: "x.png", "t")
    assert eff["steps"] == 35 and eff["cfg"] == 3.0 and eff["unet"] == "base"
    assert eff["render_scale"] == 1.5                      # 1152x2016 出图 + 缩回不变
    wf8, eff8, _ = UF.build_graph({"prompt": "p", "refs": []}, 1, lambda f: "x.png", "t")
    assert eff8["unet"] == "turbo"


def test_job_sig_changes_with_tier(monkeypatch, tmp_path):
    def sig(job):
        monkeypatch.setattr(PR, "jl", lambda p, d=None: {"jobs": [job]})

        class Paths:
            run = tmp_path
            root = tmp_path
        return PR.job_sig(Paths, "ep01-S1")
    base = {"shot": "ep01-S1", "prompt": "x", "compiler_inputs_sha": "a", "refs": []}
    s8 = sig(base)
    s35 = sig({**base, "tier": "base35", "tier_overrides": {"steps": 35}})
    assert s8 != s35
    assert sig({**base}) == s8                       # preview 不加段，旧签名不变


def test_people_range_and_verdict():
    cast = [{"presence": "在画"}] * 3 + [{"presence": "背影"}]
    assert ACC.people_range(cast) == (3, 4)
    assert ACC.people_verdict(3, cast) is None
    assert ACC.people_verdict(4, cast) is None          # 背影可见
    assert "多画了人" in ACC.people_verdict(5, cast)
    assert "少人" in ACC.people_verdict(2, cast)
    three = [{"presence": "在画"}] * 3
    assert "多画了人" in ACC.people_verdict("4", three)  # S1：三人镜出第 4 人
    assert ACC.people_verdict(None, three) is None and ACC.people_verdict("多", three) is None
    assert ACC.people_verdict(4, None) is None


def test_prompt_check_fails_on_extra_person(monkeypatch):
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import continuity as CT
    from ns_agent.gen_contract import accept as GA
    from tools.vqa import anomaly as AN
    monkeypatch.setattr(CT, "shot_rec", lambda sid: {})
    monkeypatch.setattr(GA, "shot_description", lambda rec, stage=None: "三人同框")
    monkeypatch.setattr(AN, "shot_cast", lambda sid: [{"presence": "在画"}] * 3)
    monkeypatch.setattr(ACC, "people_gate_on", lambda project=None: True)
    seen = {}

    def gen(req, **kw):
        seen["text"] = req["text"]
        return {"text": '{"people_count": "符合", "positions": "符合", "action": "符合", "scene": "符合", "visible_people": 4, "e": ""}'}
    monkeypatch.setattr(VC, "generate", gen)
    r = ACC.prompt_check("ep01-S1", "x.png")
    assert r["status"] == "fail" and "people_count" in r["why"]
    assert "visible_people" in seen["text"]
    monkeypatch.setattr(ACC, "people_gate_on", lambda project=None: False)    # 关闭：行为同旧版（不问、不判）
    r2 = ACC.prompt_check("ep01-S1", "x.png")
    assert r2["status"] == "pass" and "visible_people" not in seen["text"]
