"""HOLLYWOOD r8：新建剧本 → 可导入的全自动流程（tools/script_rsi/autoflow.py + services/api/ns_api/script_autoflow.py）。不调网关。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def AF():
    spec = importlib.util.spec_from_file_location("autoflow", ROOT / "tools" / "script_rsi" / "autoflow.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_patch_chain_injects_template_rules_and_64k(AF):
    RCH = AF._load("run_chain_t", "tools/pipeline/run_chain.py")
    AF.patch_chain(RCH)
    assert RCH.chain()["links"]["P3-P4"]["writer"]["max_tokens"] >= 64000
    ex = AF.extra_system()
    assert "红线：不改给定的剧情事实和人物设定" in ex and "writer_knowledge_version" in ex
    assert "第二步：用好莱坞方法重写" in ex


def test_status_file_shape(AF, tmp_path):
    st = AF.Status(tmp_path, 1, 1.0)
    st.stage("P1", "故事线", "ok", "api_model", usd=0.01)
    st.stage("code", "代码判定 + 补丁", "fails_left", "code", fails=2)
    d = json.loads((tmp_path / AF.STATUS).read_text(encoding="utf-8"))
    assert d["schema"] == "nsfs.autoflow/1" and [s["id"] for s in d["stages"]] == ["P1", "code"]
    assert all(s["decider"] in ("code", "api_model", "owner") for s in d["stages"])
    assert (tmp_path / "autoflow_ep01.json").exists()


def test_api_router_guards(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_api import script_autoflow as SA
    monkeypatch.setattr(SA, "RUNS", tmp_path)
    app = FastAPI()
    app.include_router(SA.router)
    c = TestClient(app)
    assert c.get("/api/script-autoflow/nope").status_code == 404
    (tmp_path / "r1").mkdir()
    (tmp_path / "r1" / "P0_brief.json").write_text("{}", encoding="utf-8")
    assert c.get("/api/script-autoflow/r1").json()["verdict"] == "not_started"
    assert c.post("/api/script-autoflow/r1/import", json={"episode": 1}).status_code == 409    # 没到 importable 不许导入
    assert c.post("/api/script-autoflow/r1/start", json={"episode": 1, "import_mode": "bad"}).status_code == 400


def test_l109_backend_default_claude_agent_and_packet(AF, tmp_path):
    AG = AF._load("autoflow_agent_t", "tools/script_rsi/autoflow_agent.py")
    assert AG.backend() == "claude_agent"                       # L-109：测试期默认不调外部 API
    st = AF.Status(tmp_path, 6, 0.0)
    pk = AG.packet(tmp_path, st, "P2_ep06", "writer", 6, "P1-P2", "SYS", "USER", "json", [], 1)
    assert (tmp_path / "writer_tasks" / "P2_ep06_a1.json").exists()
    assert "露骨的性描写不写" in pk["system"] and pk["output"]["path"].endswith("writer_out/P2_ep06_a1.json")
    op = tmp_path / "writer_out" / "P2_ep06_a1.json"
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text("{}", encoding="utf-8")
    assert AG.ready(op) is None                                  # 没有 .done 不读
    op.with_name(op.name + ".done").write_text("", encoding="utf-8")
    assert AG.ready(op) == "{}"


def test_v2_shot_block_and_lighting_checks():
    import importlib.util as iu
    spec = iu.spec_from_file_location("rubric_code_v2", ROOT / "tools" / "script_rsi" / "rubric_code.py")
    RC = iu.module_from_spec(spec)
    spec.loader.exec_module(RC)

    class S:
        index = 1
    good = ("**镜1｜img**：近景，台灯在右侧亮着\n**机位与景别**：近景，平视，林晚\n**构图**：台灯在画面右侧\n"
            "**灯光**：台灯在画面右侧作暖色主光，布光比 3:1，3000K\n**运镜**：推近，小幅\n**表演节拍**：0–2 秒……")
    r = RC.v2_checks([S()], [good])
    assert r[1][0] and r[2][0]
    bad = good.replace("**构图**：台灯在画面右侧\n", "").replace("布光比 3:1，", "")
    r2 = RC.v2_checks([S()], [bad])
    assert not r2[1][0] and not r2[2][0]
    assert RC.uses_v2([good]) and not RC.uses_v2(["**镜1｜img**：近景"])
