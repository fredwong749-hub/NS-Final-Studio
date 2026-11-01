"""EDITDEL（2026-10-31）：处处可编辑（反馈 → 逻辑模型计划 → 执行 → 版本链 → 采用 / 回滚 → 记账与沉淀）+ 删除到回收站。
逻辑模型与写作模型一律 mock（不花钱），出图用假 ComfyUI（不占卡），全部在临时 data / knowledge 目录。"""
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_agent.looks import DEFAULT_SCRIPT_JSON
from ns_api import app as app_mod
from ns_api import edits as ED
from ns_api import jobs as J
from ns_api import story_runs as SR
from ns_api import trash as TR
from ns_render import pipeline as P
from test_frame_jobs_w2 import FakeComfy, _png, _wait

pytestmark = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
SHOT = "ep02-S1"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "renders").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    # REFLOCK K-REN-134：资产项目的画布重出走唯一出图路径（tests/test_unified_frame.py 覆盖）；这里测编辑链路机制，用旧画布路径
    from ns_render import unified_frame as _UF
    monkeypatch.setattr(_UF, "project_for", lambda script: None)
    own = tmp_path / "shot_ownership.json"
    own.write_text(json.dumps({"projects": {"weita": {"owner": "canvas"}}}), encoding="utf-8")
    monkeypatch.setattr(P, "OWNERSHIP", own)
    from ns_api import readiness as RD
    monkeypatch.setattr(RD, "OWNERSHIP_FILE", own)
    kn = tmp_path / "knowledge"
    (kn / "inbox").mkdir(parents=True)
    (kn / "rules").mkdir()
    (kn / "RSI_LEDGER.md").write_text("# RSI 账本\n\n## A. x\n\n| # | a |\n|---|---|\n", encoding="utf-8")
    monkeypatch.setattr(ED, "KNOWLEDGE", kn)
    monkeypatch.setattr(ED, "PLANNER_PROMPT", tmp_path / "edit_planner.md")
    monkeypatch.setattr(SR, "RUNS", data / "pipeline" / "runs")
    from ns_api import auth as AU
    monkeypatch.setattr(AU, "REPO", tmp_path)      # 登录账户 / 审计写在临时目录
    import sys
    import types
    gc = types.ModuleType("ns_agent.gen_contract")      # 默认：契约校验放行并记下请求（真校验见 test_real_gen_contract_*）
    gc.seen = []
    gc.preflight = lambda kind, p: (gc.seen.append(("pre", kind, p)), {"ok": True, "items": []})[1]
    gc.postflight = lambda kind, p: (gc.seen.append(("post", kind, p)), {"ok": True, "items": []})[1]
    monkeypatch.setitem(sys.modules, "ns_agent.gen_contract", gc)
    import ns_agent as _NA                                # 包属性也换掉：别的模块先导入过真契约时 from ns_agent import gen_contract 会拿到真的
    monkeypatch.setattr(_NA, "gen_contract", gc, raising=False)
    monkeypatch.setattr(ED, "base_quality", lambda path: None)   # 假图 64×112：底图质感检查默认不拦（见 test_bad_base_*）
    clients = {}

    def factory(gpu):
        clients.setdefault(gpu, []).append(FakeComfy(gpu))
        return clients[gpu][-1]
    monkeypatch.setattr(J, "client_factory", factory)
    calls = []

    def fake_llm(plan=None, text=None):
        def call(purpose, system, user, max_tokens, override=None):
            calls.append({"purpose": purpose, "system": system, "user": user})
            content = json.dumps(plan, ensure_ascii=False) if purpose == "edit_plan" else (text or "改写后")
            return {"content": content, "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "mock",
                    "seconds": 0.0, "cost_usd": 0.0}
        monkeypatch.setattr(ED, "call_llm", call)
    yield {"gc": gc, "c": TestClient(app_mod.app), "data": data, "clients": clients, "kn": kn, "llm": fake_llm, "calls": calls,
           "tmp": tmp_path}


def _frame(env, color=(120, 90, 80)) -> str:
    f = env["data"] / "pipeline" / "runs" / "series10_v1" / "images" / "frames" / "ep02" / "ep02-S1_s1.png"
    from PIL import Image
    f.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 112), color).save(f)
    return "data/" + f.relative_to(env["data"]).as_posix()


def _edit_wait(c, eid, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        it = c.get(f"/api/edits/{eid}").json()
        if it["status"] not in ("running", "planning"):
            return it
        time.sleep(0.05)
    raise AssertionError(it)


PLAN_OIL = {"understanding": "脸不像林晚、皮肤反光", "action": "edit", "instruction": "让脸部更接近图2的林晚，皮肤去掉油光，哑光质感",
            "strength": "medium", "use_identity_ref": True, "lock_conflicts": []}


# ------------------------------------------------------------------ 编辑：file 对象（流水线首帧）
def test_file_image_inpaint_chain_adopt_rollback(env):
    c = env["c"]
    rel = _frame(env)
    env["llm"](PLAN_OIL)
    oid = f"file:{rel}"
    r = c.post("/api/edits", json={"type": "image", "id": oid, "feedback": "脸不像林晚、皮肤太油",
                                   "annotations": {"box": [0.25, 0.1, 0.5, 0.4]}, "gpu": 0})
    assert r.status_code == 200, r.text
    it = r.json()
    assert it["plan"]["action"] == "inpaint" and it["plan"]["region"] == [0.25, 0.1, 0.5, 0.4]
    assert any("局部重绘" in f for f in it["plan"]["fixes"])
    assert "皮肤太油" in env["calls"][0]["user"] and "只输出 JSON" in env["calls"][0]["user"]
    it = _edit_wait(c, it["edit_id"])
    assert it["status"] == "done", (it.get("error"), it.get("job"))
    v = it["result"]["version"]
    assert v == 1 and it["result"]["url"].startswith("/files/edits/versions/")
    # 工作流：Image 2.1 编辑，图1 = 原图，指令带编译器角色锁段（K-REN-103）
    wf = env["clients"][0][-1].workflows[-1]
    texts = json.dumps(wf, ensure_ascii=False)
    assert "哑光" in texts and "保持角色锁定外貌" in texts
    # 局部重绘：框外像素 = 原图（假 ComfyUI 出的图颜色不同）
    from PIL import Image
    out = Image.open(env["data"] / it["result"]["file"][5:]).convert("RGB")
    assert out.getpixel((1, out.size[1] - 2)) == (120, 90, 80)
    vs = c.get("/api/edits/versions", params={"type": "image", "id": oid}).json()
    assert vs["kind"] == "chain" and vs["current"] == 0 and [x["v"] for x in vs["versions"]] == [0, 1]
    a = c.post(f"/api/edits/{it['edit_id']}/adopt", json={"by": "owner"}).json()
    assert a["status"] == "adopted" and a["applied"] == {"current": 1}
    assert c.get("/api/edits/versions", params={"type": "image", "id": oid}).json()["current"] == 1
    rb = c.post(f"/api/edits/{it['edit_id']}/rollback").json()
    assert rb["status"] == "rolled_back"
    assert c.get("/api/edits/versions", params={"type": "image", "id": oid}).json()["current"] == 0
    events = [x["event"] for x in ED.read_ledger()]
    assert events[:1] == ["submitted"] and "adopted" in events and "rolled_back" in events
    # 原图没被覆盖
    assert Image.open(env["data"] / rel[5:]).convert("RGB").getpixel((30, 50)) == (120, 90, 80)


def test_lock_rule_blocks_plan(env):
    c = env["c"]
    rel = _frame(env)
    env["llm"]({"action": "edit", "instruction": "把她的头发染成红色", "lock_conflicts": []})
    it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "换个红头发"}).json()
    assert it["status"] == "blocked" and it["plan"]["action"] == "reject"
    assert any(x["rule"] == "HC-07" for x in it["plan"]["lock_conflicts"])
    assert not env["clients"]      # 没出图


def test_dry_run_and_bad_json(env, monkeypatch):
    c = env["c"]
    rel = _frame(env)
    env["llm"](PLAN_OIL)
    it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油", "dry_run": True}).json()
    assert it["status"] == "planned" and not env["clients"]
    monkeypatch.setattr(ED, "call_llm", lambda *a, **k: {"content": "我觉得应该……", "usage": {}})
    r = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油"})
    assert r.status_code == 502 and "JSON" in r.text


# ------------------------------------------------------------------ 编辑：画布 take
def test_take_edit_goes_into_take_chain(env):
    c = env["c"]
    r = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "regen", "seed": 7, "gpu": 0})
    assert _wait(c, r.json()["job_id"])["state"] == "done"
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    it = c.post("/api/edits", json={"type": "image", "id": f"take:{SHOT}/image/1", "feedback": "皮肤太油", "gpu": 0}).json()
    assert it["status"] == "running" and it["result"]["kind"] == "take"
    _wait(c, it["result"]["job_id"])
    it = _edit_wait(c, it["edit_id"])
    assert it["status"] == "done" and it["result"]["take_n"] == 2
    t2 = next(t for t in P.load_takes(SHOT)["takes"] if t["n"] == 2)
    assert t2["parent"] == 1 and t2["mode"] in ("instruct", "refs") and "哑光" in t2["instruction"]
    c.post(f"/api/shots/{SHOT}/takes/image/1/activate")
    c.post(f"/api/edits/{it['edit_id']}/adopt", json={})
    assert P.load_takes(SHOT)["active"]["image"] == 2
    c.post(f"/api/edits/{it['edit_id']}/rollback")
    assert P.load_takes(SHOT)["active"]["image"] == 1


# ------------------------------------------------------------------ 提示词 / 剧本段：只出“待确认”方案
def test_prompt_patch_proposal_adopt(env):
    c = env["c"]
    cur = c.get("/api/edits/versions", params={"type": "prompt", "id": f"shot:{SHOT}/image_prompt"})
    assert cur.status_code == 200
    ctx = ED.describe("prompt", f"shot:{SHOT}/image_prompt")
    find = ctx["text"][:6]
    env["llm"]({"action": "prompt_only", "prompt_patch": {"find": find, "replace": find + "（哑光肌肤）"}})
    it = c.post("/api/edits", json={"type": "prompt", "id": f"shot:{SHOT}/image_prompt", "feedback": "提示词里加哑光"}).json()
    assert it["status"] == "proposed" and it["result"]["status"] == "待确认" and "哑光肌肤" in it["result"]["text"]
    assert P.load_edit(SHOT).image_prompt is None          # 没确认前不写
    c.post(f"/api/edits/{it['edit_id']}/adopt", json={"by": "owner"})
    assert "（哑光肌肤）" in P.load_edit(SHOT).image_prompt


@pytest.mark.anon      # 未登录身份（conftest 默认以项目方登录）
def test_script_rewrite_needs_owner(env):
    c = env["c"]
    d = SR.RUNS / "ui_test_ep01"
    d.mkdir(parents=True)
    (d / "ui_state.json").write_text(json.dumps({"id": d.name, "episode": 1, "status": "paused"}), encoding="utf-8")
    (d / "P4_ep01.md").write_text("# 原稿\n镜头 1\n", encoding="utf-8")
    env["llm"]({"action": "text_rewrite", "rewrite_brief": "镜头 1 改成镜头一"}, text="# 原稿\n镜头一\n")
    it = c.post("/api/edits", json={"type": "script", "id": "run:ui_test_ep01/P4", "feedback": "格式统一"}).json()
    assert it["status"] == "proposed" and it["result"]["status"] == "待确认"
    assert env["calls"][-1]["purpose"] == "script_write"           # 改写由写作模型给
    assert "chain_check" in it["result"] and "+镜头一" in it["result"]["diff"]
    assert c.post(f"/api/edits/{it['edit_id']}/adopt", json={}).status_code == 403
    assert (d / "P4_ep01.md").read_text(encoding="utf-8") == "# 原稿\n镜头 1\n"


def test_script_rewrite_owner_adopt_writes_back(env):
    """登录的项目方采用 → 经 story-runs 写回（重新校验，旧版留底）"""
    c = env["c"]
    d = SR.RUNS / "ui_test_ep02"
    d.mkdir(parents=True)
    (d / "ui_state.json").write_text(json.dumps({"id": d.name, "episode": 1, "status": "paused"}), encoding="utf-8")
    (d / "P4_ep01.md").write_text("# 原稿\n镜头 1\n", encoding="utf-8")
    env["llm"]({"action": "text_rewrite", "rewrite_brief": "镜头 1 改成镜头一"}, text="# 原稿\n镜头一\n")
    it = c.post("/api/edits", json={"type": "script", "id": "run:ui_test_ep02/P4", "feedback": "格式统一"}).json()
    # 这个临时运行没有合格提纲：写回接口按链条规则拒绝（409），原文不动、编辑仍是“待确认”
    r = c.post(f"/api/edits/{it['edit_id']}/adopt", json={})
    assert r.status_code == 409 and "提纲" in r.text
    assert (d / "P4_ep01.md").read_text(encoding="utf-8") == "# 原稿\n镜头 1\n"
    assert c.get(f"/api/edits/{it['edit_id']}").json()["status"] == "proposed"
    # 写回走 story-runs 的 PUT artifact（重新校验、旧版留底）：替身记录调用
    seen = []
    monkeypatch_edit = lambda run_id, node, body: (seen.append((run_id, node, body.text)), {"status": "ok"})[1]  # noqa: E731
    import ns_api.story_runs as SR2
    orig, SR2.edit_artifact = SR2.edit_artifact, monkeypatch_edit
    try:
        r = c.post(f"/api/edits/{it['edit_id']}/adopt", json={})
    finally:
        SR2.edit_artifact = orig
    assert r.status_code == 200, r.text
    assert seen == [("ui_test_ep02", "P4", "# 原稿\n镜头一")] and r.json()["applied"]["status"] == "ok"


# ------------------------------------------------------------------ 学习：同类采用 ≥2 次 → inbox 草案 + RSI 一行
def test_learning_writes_inbox_draft(env):
    import yaml
    c = env["c"]
    rel = _frame(env)
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    for _ in range(2):
        it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "皮肤太油了", "gpu": 0}).json()
        it = _edit_wait(c, it["edit_id"])
        a = c.post(f"/api/edits/{it['edit_id']}/adopt", json={"by": "owner"}).json()
    assert a["learning"]["count"] == 2 and a["learning"]["rule_id"] == "K-REN-E01"
    drafts = list((env["kn"] / "inbox").glob("*_edit_oily_skin.yaml"))
    assert len(drafts) == 1
    r = yaml.safe_load(drafts[0].read_text(encoding="utf-8"))["rules"][0]
    import re
    assert re.match(r"^K-(REN|PRM|WRT|EDT|REV|LOOP|AST|OPS|UI)-[A-Z]?\d{2,3}$", r["id"])
    assert r["domain"] == "render" and r["status"] == "待确认" and r["link"] == "P5-P6"
    led = (env["kn"] / "RSI_LEDGER.md").read_text(encoding="utf-8")
    assert "## E. 编辑闭环沉淀" in led and "inbox 草案 REN-E01" in led and "K-REN-E01" not in led
    assert c.get("/api/edits/learned").json()["groups"]["oily_skin"]


def test_planner_prompt_assembled_from_knowledge(env):
    (env["kn"] / "rules" / "x.yaml").write_text(
        "rules:\n- {id: K-REN-103, title: 出图走编译器, then: 一律经 ns_agent.compiler, status: 确认}\n", encoding="utf-8")
    txt = env["c"].post("/api/edits/planner-prompt/rebuild").json()["text"]
    assert "K-REN-103" in txt and "HC-07" in txt and "只输出 JSON" in txt
    assert ED.PLANNER_PROMPT.read_text(encoding="utf-8") == txt


# ------------------------------------------------------------------ 删除 / 回收站
def test_trash_take_locked_confirm_restore(env):
    c = env["c"]
    for s in (1, 2):
        r = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "regen", "seed": s, "gpu": 0})
        _wait(c, r.json()["job_id"])
    c.post(f"/api/shots/{SHOT}/takes/first/2/lock")
    imp = c.get("/api/trash/impact", params={"type": "take", "id": f"{SHOT}/image/2"}).json()
    assert imp["needs_confirm"] and imp["can_delete"] and any("已定稿" in x for x in imp["confirm"])
    r = c.delete("/api/trash/object", params={"type": "take", "id": f"{SHOT}/image/2"})
    assert r.status_code == 409 and r.json()["detail"]["needs_confirm"]
    e = c.delete("/api/trash/object", params={"type": "take", "id": f"{SHOT}/image/2", "confirm": True, "by": "owner"}).json()
    assert e["state"] == "trashed" and e["files"]
    data = P.load_takes(SHOT)
    assert [t["n"] for t in data["takes"] if t["stage"] == "image"] == [1]
    assert data["active"]["image"] == 1 and (data.get("locked") or {}).get("image") is None
    man = json.loads((env["data"] / "_trash" / e["day"] / "MANIFEST.json").read_text(encoding="utf-8"))
    assert man["entries"][0]["entry_id"] == e["entry_id"]
    assert c.get("/api/trash").json()["entries"][0]["entry_id"] == e["entry_id"]
    r = c.post(f"/api/trash/{e['entry_id']}/restore").json()
    assert r["state"] == "restored"
    data = P.load_takes(SHOT)
    assert sorted(t["n"] for t in data["takes"] if t["stage"] == "image") == [1, 2]
    assert data["active"]["image"] == 2 and data["locked"]["image"] == 2
    assert all((env["data"] / f["from"][5:]).is_file() for f in e["files"])
    assert c.get("/api/trash").json()["entries"] == []


@pytest.mark.anon      # 未登录身份（conftest 默认以项目方登录）
def test_trash_story_run_purge_guards(env):
    c = env["c"]
    d = SR.RUNS / "ui_old_ep03"
    d.mkdir(parents=True)
    (d / "P0_brief.json").write_text("{}", encoding="utf-8")
    e = c.delete("/api/trash/object", params={"type": "story_run", "id": "ui_old_ep03"}).json()
    assert not d.exists() and e["name"] == "ui_old_ep03"
    assert c.get("/api/story-runs").json()["runs"] == []
    eid = e["entry_id"]
    assert c.post(f"/api/trash/{eid}/purge", json={"confirm": True, "by": "owner"}).status_code == 403   # 没登录：声称 owner 也不算
    assert c.post("/api/auth/setup", json={"name": "fred", "password": "secret1"}).status_code == 200     # 登录 = 本人
    assert c.post(f"/api/trash/{eid}/purge", json={}).status_code == 422      # 没有二次确认
    assert (env["data"] / "_trash" / e["day"] / eid).is_dir()
    r = c.post(f"/api/trash/{eid}/purge", json={"confirm": True})
    assert r.status_code == 200
    assert not (env["data"] / "_trash" / e["day"] / eid).exists()
    assert c.post(f"/api/trash/{eid}/restore").status_code == 409
    allp = c.get("/api/trash", params={"include_purged": True}).json()["entries"]
    assert allp[0]["state"] == "purged"


def test_trash_series_run_needs_confirm_and_running_blocked(env, monkeypatch):
    c = env["c"]
    d = SR.RUNS / "series_x"
    (d / "ep01").mkdir(parents=True)
    imp = c.get("/api/trash/impact", params={"type": "story_run", "id": "series_x"}).json()
    assert imp["needs_confirm"] and any("整季" in x for x in imp["confirm"])
    monkeypatch.setattr(SR, "_alive", lambda rid: True)
    r = c.delete("/api/trash/object", params={"type": "story_run", "id": "series_x", "confirm": True})
    assert r.status_code == 409 and "正在写作" in json.dumps(r.json(), ensure_ascii=False)


def test_trash_cut_candidate_and_edit_version(env):
    c = env["c"]
    ep = env["data"] / "episodes"
    ep.mkdir()
    (ep / "ep02_UI1031-1200.mp4").write_bytes(b"x")
    (ep / "ep02_UI1031-1200.timeline.json").write_text("{}", encoding="utf-8")
    e = c.delete("/api/trash/object", params={"type": "cut", "id": "episodes/ep02_UI1031-1200.mp4"}).json()
    assert len(e["files"]) == 2 and not (ep / "ep02_UI1031-1200.mp4").exists()
    st = env["data"] / "staging_input"
    st.mkdir()
    (st / "旧稿.md").write_text("x", encoding="utf-8")
    r = c.delete("/api/trash/object", params={"type": "import_candidate", "id": "data/staging_input/旧稿.md"})
    assert r.status_code == 200 and not (st / "旧稿.md").exists()
    assert c.delete("/api/trash/object", params={"type": "import_candidate", "id": "config/x.md"}).status_code == 422
    # 编辑版本：当前版不能删，非当前可删可还原
    rel = _frame(env)
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    it = _edit_wait(c, c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "油", "gpu": 0}).json()["edit_id"])
    oid = f"file:{rel}|1"
    c.post(f"/api/edits/{it['edit_id']}/adopt", json={})
    assert c.delete("/api/trash/object", params={"type": "edit_version", "id": oid}).status_code == 409
    c.post(f"/api/edits/{it['edit_id']}/rollback")
    e = c.delete("/api/trash/object", params={"type": "edit_version", "id": oid}).json()
    assert [v["v"] for v in ED.load_chain(f"file:{rel}")["versions"]] == [0]
    c.post(f"/api/trash/{e['entry_id']}/restore")
    assert [v["v"] for v in ED.load_chain(f"file:{rel}")["versions"]] == [0, 1]


def test_trash_rejects_bad_ids(env):
    c = env["c"]
    assert c.get("/api/trash/impact", params={"type": "nope", "id": "x"}).status_code == 422
    assert c.get("/api/trash/impact", params={"type": "cut", "id": "../x.mp4"}).status_code == 422
    assert c.get("/api/trash/impact", params={"type": "take", "id": "ep02-S1/image/99"}).status_code == 404
    assert c.post("/api/trash/tr-0000000000/restore").status_code == 404


# ------------------------------------------------------------------ 可插拔编辑模型 + GEN_CONTRACT
def test_engine_template_and_gen_contract(env, monkeypatch):
    import sys
    import types
    c = env["c"]
    rel = _frame(env)
    tpl = env["tmp"] / "tpl.json"
    tpl.write_text(json.dumps({"1": {"class_type": "LoadImage", "inputs": {"image": "{{image1}}"}},
                               "2": {"class_type": "X", "inputs": {"text": "改：{{prompt}}", "seed": "{{seed}}"}},
                               "90": {"class_type": "SaveImage", "inputs": {"filename_prefix": "{{prefix}}"}}}), encoding="utf-8")
    cfg = env["tmp"] / "edit_engines.json"
    cfg.write_text(json.dumps({"default": "qwen_image_2_1_edit", "engines": {
        "tpl": {"label": "模板", "builder": "template", "graph": str(tpl), "enabled": True},
        "off": {"label": "未启用", "builder": "template", "graph": str(tpl), "enabled": False}}}), encoding="utf-8")
    monkeypatch.setattr(ED, "ENGINES_FILE", cfg)
    seen = []
    gc = types.ModuleType("ns_agent.gen_contract")
    gc.preflight = lambda kind, p: (seen.append(("pre", kind, p["edit"]["engine"])), {"ok": True, "items": []})[1]
    gc.postflight = lambda kind, p: (seen.append(("post", kind, p["image"])), {"ok": True})[1]
    monkeypatch.setitem(sys.modules, "ns_agent.gen_contract", gc)
    import ns_agent as _NA                                # 包属性也换掉：别的模块先导入过真契约时 from ns_agent import gen_contract 会拿到真的
    monkeypatch.setattr(_NA, "gen_contract", gc, raising=False)
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    assert {e["id"] for e in c.get("/api/edits/engines").json()["engines"]} >= {"tpl", "off", "qwen_image_2_1_edit"}
    assert c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "油", "engine": "off"}).status_code == 409
    it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "油", "engine": "tpl", "gpu": 0}).json()
    it = _edit_wait(c, it["edit_id"])
    assert it["status"] == "done" and it["result"]["engine"] == "tpl"
    wf = env["clients"][0][-1].workflows[-1]
    assert wf["2"]["inputs"]["text"].startswith("改：") and isinstance(wf["2"]["inputs"]["seed"], int)
    assert [s[0] for s in seen] == ["pre", "post"] and seen[0][1] == "image"
    assert it["result"]["postflight"]["status"] == "pass"
    gc.preflight = lambda kind, p: {"ok": False, "items": [{"id": "I2", "status": "fail"}]}
    r = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "油", "engine": "tpl"})
    assert r.status_code == 422 and "preflight" in r.text


def test_contract_request_shape(env):
    """契约请求：参考 = 槽位规划，提示词 = 槽位前缀 + 指令 + 预设后缀，禁用后缀词分句被去掉，LoRA 过白名单"""
    c = env["c"]
    rel = _frame(env)
    env["llm"]({**PLAN_OIL, "instruction": "脸更像林晚，去掉脸上的油光；皮肤改成哑光通透质感"})
    it = _edit_wait(c, c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油", "gpu": 0}).json()["edit_id"])
    assert it["status"] == "done", (it.get("error"), it.get("job"))
    pre = [p for k, kind, p in env["gc"].seen if k == "pre"][-1]
    assert pre["kind"] == "image" and pre["shot_id"] == "ep02-S1" and "ns_agent.compiler" in pre["compiled_by"]
    assert "油光" not in pre["prompt"] and "哑光通透" in pre["prompt"]
    assert all(f[0] != "lin_wan_qi_v1.safetensors" for f in pre["loras"])
    assert any("I7" in f for f in it["plan"]["fixes"])
    post = [p for k, kind, p in env["gc"].seen if k == "post"][-1]
    assert post["request"]["prompt"] == pre["prompt"] and post["image"].endswith(".png")


def test_required_contract_blocks_when_failing(env):
    c = env["c"]
    rel = _frame(env)
    env["gc"].preflight = lambda kind, p: {"ok": False, "items": [{"id": "I2", "status": "fail"}], "reasons": ["I2 缺身份脸"]}
    env["llm"](PLAN_OIL)
    r = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "油", "gpu": 0})
    assert r.status_code == 422 and "I2" in r.text and not env["clients"]


# ------------------------------------------------------------------ 契约自动重出（≤3 次，每次只改一个维度）
def _post_seq(env, oks):
    """postflight 依次返回 oks 里的结果（用完后一直返回最后一个）"""
    seq = list(oks)

    def post(kind, p):
        ok = seq.pop(0) if len(seq) > 1 else seq[0]
        env["gc"].seen.append(("post", kind, p))
        return {"ok": ok, "items": [{"id": "Q4", "status": "pass" if ok else "fail"}], "reasons": [] if ok else ["Q4 清晰度不够"]}
    env["gc"].postflight = post


def test_retry_until_pass_only_passing_version_is_candidate(env):
    c = env["c"]
    rel = _frame(env)
    _post_seq(env, [False, False, True])
    env["llm"](PLAN_OIL)
    it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "脸不像、太油",
                                    "annotations": {"box": [0.3, 0.1, 0.4, 0.3]}, "gpu": 0}).json()
    it = _edit_wait(c, it["edit_id"])
    assert it["status"] == "done", (it.get("error"), it.get("result"))
    at = it["result"]["attempts"]
    assert [a["ok"] for a in at] == [False, False, True]
    assert at[0]["change"] == "首次" and at[1]["change"].startswith("换 seed") and at[2]["change"].startswith("调局部重绘区域")
    assert at[1]["seed"] != at[0]["seed"] and at[2]["seed"] == at[1]["seed"]          # 每次只改一个维度
    assert at[2]["region"] != at[1]["region"] and at[1]["region"] == at[0]["region"]
    vs = c.get("/api/edits/versions", params={"type": "image", "id": f"file:{rel}"}).json()["versions"]
    assert [v["v"] for v in vs] == [0, 1]                                             # 失败的两张不进版本链
    assert len(env["clients"][0][-1].workflows) == 3
    assert c.post(f"/api/edits/{it['edit_id']}/adopt", json={}).status_code == 200


def test_retry_exhausted_marks_contract_failed(env):
    c = env["c"]
    rel = _frame(env)
    _post_seq(env, [False])
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油", "gpu": 0}).json()
    it = _edit_wait(c, it["edit_id"])
    assert it["status"] == "contract_failed" and it["result"]["contract_failed"], (it.get("error"), it.get("job"))
    at = it["result"]["attempts"]
    assert len(at) == 4 and not any(a["ok"] for a in at)
    assert [a["change"].split("：")[0] for a in at] == ["首次", "换 seed", "换 seed", "换 seed"]   # 非局部重绘、无别的模型 → 都换 seed
    assert all((env["data"] / a["file"][5:]).is_file() for a in at)                       # 尝试文件留档备查
    vs = c.get("/api/edits/versions", params={"type": "image", "id": f"file:{rel}"}).json()["versions"]
    assert [v["v"] for v in vs] == [0]
    assert c.post(f"/api/edits/{it['edit_id']}/adopt", json={}).status_code == 409
    assert any(r["event"] == "contract_failed" for r in ED.read_ledger())


def test_retry_switches_engine_on_third(env, monkeypatch):
    c = env["c"]
    rel = _frame(env)
    tpl = env["tmp"] / "tpl.json"
    tpl.write_text(json.dumps({"2": {"class_type": "X", "inputs": {"text": "{{prompt}}", "seed": "{{seed}}", "image": "{{image1}}"}},
                               "90": {"class_type": "SaveImage", "inputs": {"filename_prefix": "{{prefix}}"}}}), encoding="utf-8")
    cfg = env["tmp"] / "edit_engines.json"
    cfg.write_text(json.dumps({"default": "qwen_image_2_1_edit", "engines": {
        "alt": {"label": "备选", "builder": "template", "graph": str(tpl), "enabled": True}}}), encoding="utf-8")
    monkeypatch.setattr(ED, "ENGINES_FILE", cfg)
    _post_seq(env, [False, False, False, True])
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    it = _edit_wait(c, c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油", "gpu": 0}).json()["edit_id"])
    at = it["result"]["attempts"]
    assert it["status"] == "done" and at[3]["change"].startswith("换编辑模型") and at[3]["engine"] == "alt"
    assert at[3]["seed"] == at[2]["seed"]
    assert env["clients"][0][-1].workflows[-1]["2"]["class_type"] == "X"


def test_take_retry_failed_attempts_not_in_takes(env):
    c = env["c"]
    r = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "regen", "seed": 7, "gpu": 0})
    _wait(c, r.json()["job_id"])
    _post_seq(env, [False, True])
    env["llm"]({**PLAN_OIL, "use_identity_ref": False})
    it = c.post("/api/edits", json={"type": "image", "id": f"take:{SHOT}/image/1", "feedback": "太油", "gpu": 0}).json()
    _wait(c, it["result"]["job_id"])
    it = _edit_wait(c, it["edit_id"])
    assert it["status"] == "done" and it["result"]["take_n"] == 2 and len(it["result"]["attempts"]) == 2
    assert [t["n"] for t in P.load_takes(SHOT)["takes"] if t["stage"] == "image"] == [1, 2]   # 失败的那张不进 takes


def test_bad_base_rejected_without_gpu(env, monkeypatch):
    """REFLOCK：底图本身 Q4 不过 → 直接标“底图不合格”，不出图、不重出"""
    c = env["c"]
    rel = _frame(env)
    monkeypatch.setattr(ED, "base_quality", lambda path: {"ok": False, "reasons": ["清晰度 78.1 < 175.0（塑料 / 糊）"], "metrics": {}})
    env["llm"](PLAN_OIL)
    it = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油", "gpu": 0}).json()
    assert it["status"] == "base_rejected" and "v9" in it["result"]["message"] and not env["clients"]
    assert c.post(f"/api/edits/{it['edit_id']}/adopt", json={}).status_code == 409
    it2 = c.post("/api/edits", json={"type": "image", "id": f"file:{rel}", "feedback": "太油", "gpu": 0,
                                     "allow_bad_base": True}).json()
    assert _edit_wait(c, it2["edit_id"])["status"] == "done"


def test_trash_sheet_candidate_and_prop(env):
    c = env["c"]
    d = env["data"] / "pipeline" / "runs" / "series10_v1"
    sd = d / "images" / "sheets" / "lin_wan"
    _png(sd / "lin_wan_lookA_s202.png")
    _png(sd / "lin_wan_lookA_s203.png")
    (d / "assets").mkdir(parents=True)
    (d / "assets" / "sheets_chosen.json").write_text(json.dumps({"sheet:lin_wan_lookA": {
        "file": "data/pipeline/runs/series10_v1/images/sheets/lin_wan/lin_wan_lookA_s202.png"}}), encoding="utf-8")
    chosen = "data/pipeline/runs/series10_v1/images/sheets/lin_wan/lin_wan_lookA_s202.png"
    other = "data/pipeline/runs/series10_v1/images/sheets/lin_wan/lin_wan_lookA_s203.png"
    imp = c.get("/api/trash/impact", params={"type": "sheet_candidate", "id": chosen}).json()
    assert not imp["can_delete"] and "选定" in imp["blocked"][0]
    assert c.delete("/api/trash/object", params={"type": "sheet_candidate", "id": chosen}).status_code == 409
    assert c.get("/api/trash/impact", params={"type": "sheet_candidate", "id": "data/x.png"}).status_code == 422
    e = c.delete("/api/trash/object", params={"type": "sheet_candidate", "id": other}).json()
    assert not (sd / "lin_wan_lookA_s203.png").exists()
    c.post(f"/api/trash/{e['entry_id']}/restore")
    assert (sd / "lin_wan_lookA_s203.png").is_file()
    # 道具
    (env["data"] / "props.json").write_text(json.dumps({"props": [{"id": "prop-1", "name": "钻石手包"}, {"id": "prop-2", "name": "x"}]},
                                                       ensure_ascii=False), encoding="utf-8")
    e = c.delete("/api/trash/object", params={"type": "prop", "id": "prop-1"}).json()
    assert e["name"] == "钻石手包"
    assert [p["id"] for p in json.loads((env["data"] / "props.json").read_text(encoding="utf-8"))["props"]] == ["prop-2"]
    c.post(f"/api/trash/{e['entry_id']}/restore")
    assert [p["id"] for p in json.loads((env["data"] / "props.json").read_text(encoding="utf-8"))["props"]] == ["prop-1", "prop-2"]
    assert c.get("/api/trash/impact", params={"type": "prop", "id": "nope"}).status_code == 404
