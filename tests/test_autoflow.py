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
