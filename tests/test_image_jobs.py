"""PROMPT（2026-10-31，K-REN-103）：所有出图作业的提示词必须经系统编译器（ns_agent.compiler）——series10 首帧作业曾由
SERIES / IMGGEN 自己拼，视频触发词 lnwan01 混进 16 条、景别取舍与 LoRA 规则没有自动生效。纯 CPU，只读真数据。"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/pipeline", "tools/prompt_v2"):
    sys.path.insert(0, str(ROOT / p))

RUN = ROOT / "data" / "pipeline" / "runs" / "series10_v1"
JOBS = RUN / "assets" / "first_frame_jobs.json"
pytestmark = pytest.mark.skipif(not JOBS.exists() or not (ROOT / "data/import/script_v2.json").exists(),
                                reason="series10_v1 作业 / 分镜不在本机")


def _prompt(j):
    return next(x["inputs"]["prompt"] for x in j["graph"].values() if x.get("class_type") == "TextEncodeQwenImage21")


V1 = "series10_v1"


@pytest.fixture
def v1_jobs(tmp_path, monkeypatch):
    """PROMPTFIX 11-02 19:2x（L-125 V1 冻结）：显式钉到 V1，不读当前 primary；用现行编译器把 V1 作业表重编到临时目录
    （write 只落 tmp_path，绝不重建 / 改写冻结的 V1 数据），再拿这份去比——不变量“作业提示词 = 系统编译器输出”照查，
    不再和 V1 冻结时那份旧文件逐字比（编译器演进后旧文件天然对不上）"""
    import image_jobs as IJ
    monkeypatch.setenv("NS_PRIMARY_RUN", V1)
    monkeypatch.setenv("NS_RUN", V1)
    run = tmp_path / V1
    (run / "assets").mkdir(parents=True)
    IJ.rebuild_first_frame_jobs(RUN, project=V1, write=True, out=run / "assets" / "first_frame_jobs.json", run=V1)
    return run


def test_series_jobs_prompt_equals_compiler_output(v1_jobs):
    import audit_framing as A
    r = A.audit(v1_jobs)
    assert r["jobs"] >= 1 and r["ok"] == r["jobs"], r["rows"][:5]


def test_compiled_frame_prompt_has_no_video_trigger_and_leads_with_size():
    import image_jobs as IJ
    from ns_agent import framing as F
    si, ep = IJ.import_episode(1)          # K-OPS-Q24：生产来源 = 导入稿（P4 稿已禁用）
    g = si.globals
    for s in ep.shots:
        p, c, _sr, plan = IJ.frame_prompt_full(ep, s, g, ["data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png"], "series10_v1")
        assert not re.search(r"\blnwan01\b", p)
        # REFLOCK：资产模式下提示词 = 槽位标注（“图N是…必须完全一致”）+ 编译器输出；脸可见时图1 = 身份脸
        assert p.startswith(plan.prompt_prefix) and "图1是" in __import__("ns_agent.asset_refs", fromlist=["x"]).SINGLE_TURN_RE.sub("", p, count=1)[:20]  # IMGFIX K-REN-704
        body = p[len(plan.prompt_prefix):]
        size = F.size_of(s.img_prompt)
        if size and not F.lower_focus(s.img_prompt):
            assert F.lead(size) in body.split("，")[0] + "，" + body.split("，")[1]


def test_jobs_graph_loads_compiler_selected_loras():
    d = json.loads(JOBS.read_text(encoding="utf-8"))
    for j in d["jobs"]:
        want = [tuple(x) for x in j.get("loras") or []]
        got = [(n["inputs"]["lora_name"], n["inputs"]["strength_model"]) for k, n in sorted(j["graph"].items())
               if n.get("class_type") == "LoraLoaderModelOnly"]
        assert got == want, j["shot"]


def test_submit_gate_rejects_hand_written_prompt(v1_jobs):
    import submit_jobs as SJ
    d = json.loads((v1_jobs / "assets" / "first_frame_jobs.json").read_text(encoding="utf-8"))
    j = copy.deepcopy(d["jobs"][0])
    assert SJ.compile_mismatch(RUN, [j]) == []
    for n in j["graph"].values():
        if n.get("class_type") == "TextEncodeQwenImage21":
            n["inputs"]["prompt"] = "lnwan01，" + n["inputs"]["prompt"]
    assert SJ.compile_mismatch(RUN, [j]) == [j["id"]]
