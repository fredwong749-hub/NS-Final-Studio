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


def test_reimport_skips_unimported_and_identical(tmp_path, monkeypatch):
    """总调度 11-02：已导入过的季，补丁过闸 + 事实核对后自动覆盖导入；没导入过 = None（仍走项目方闸门）；逐镜一致 = 不重导"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("autoflow_agent", ROOT / "tools" / "script_rsi" / "autoflow_agent.py")
    AG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(AG)

    class St:
        def __init__(self):
            self.d = {}

        def set(self, **k):
            self.d.update(k)

        def save(self):
            pass
    monkeypatch.setattr(AG, "_imported_shots", lambda run, ep: None)
    assert AG.reimport(tmp_path, 1, tmp_path / "x.md", "abc", St()) is None
    called = []
    monkeypatch.setattr(AG.subprocess if hasattr(AG, "subprocess") else __import__("subprocess"), "run", lambda *a, **k: called.append(a))
    st = St()
    st.d["imported_sha"] = "abc"
    monkeypatch.setattr(AG, "_imported_shots", lambda run, ep: {1: "x"})
    assert AG.reimport(tmp_path, 1, tmp_path / "x.md", "abc", st)["skipped"] and not called


def test_light_source_visible_in_scene_counts():
    """总调度 11-02 灯光规则修订：动机光源出现在本镜 / 本场场景描述或道具里，或在 lighting.yaml 词表里，都算合规"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
    RC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RC)
    lt = "酒店柜台（自定）｜动机光源=店门（左侧），柜台油灯（下方）｜布光=主光从左侧，主辅比约 4:1｜色温=4500K"
    assert RC.light_sources(lt) == ["店门", "柜台油灯"]
    assert RC.source_seen("柜台油灯", "| sk_x | 酒店 | … | 柜台上油灯暖光 |", [])
    assert not RC.source_seen("壁炉", "门口的天光", [])
    assert RC.source_seen("台灯", "", ["台灯", "窗"])


def test_test_brief_never_overwrites(tmp_path):
    """11-02 事故：test-brief 覆盖了 V2 的 P0_brief.json 并调了外部 API —— 已有 Brief 时必须拒绝，且不调网关"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("autoflow", ROOT / "tools" / "script_rsi" / "autoflow.py")
    AF = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(AF)
    (tmp_path / "P0_brief.json").write_text('{"keep": 1}', encoding="utf-8")
    assert AF.main(["test-brief", "--run-dir", str(tmp_path)]) == 2
    assert (tmp_path / "P0_brief.json").read_text(encoding="utf-8") == '{"keep": 1}'
