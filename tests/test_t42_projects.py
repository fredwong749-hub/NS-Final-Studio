"""T42：项目模型 / 「新建剧」向导 / 编排器 / 待办 / 进度看板。

全部在临时 projects 目录里（NS_PROJECTS_DIR），用 dry-run 执行器或假执行器；不调用 /render、/render-batch，
不出图，不向真实 gpu3 发 series 请求。"""
import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_api import project_ctx as PC
from ns_api import projects as PJ
from ns_api import wizard as W
from ns_orch import engine as E
from ns_orch.executors import BaseExecutor, DryRunExecutor, StepFailed

FIX = Path(__file__).parent / "fixtures" / "t42"
SCRIPT = FIX / "雾港来信（剧本和镜头）.md"
IMAGE_DOC = FIX / "雾港来信（image提示词）.md"
CORRECTOR = FIX / "雾港来信（纠正器）.md"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")


class FakeBridge:
    """记录 series 调用，返回预设的 gpu3 集状态（不连网）"""

    def __init__(self):
        self.calls, self.status = [], {}

    def episodes(self, ctx):
        return self.status

    def series(self, ctx, action, episodes, *, adult_content, requested_by):
        self.calls.append((action, list(episodes or []), adult_content))
        return {"via": "fake"}

    def gpus(self):
        return {"reachable": False, "gpus": []}


@pytest.fixture()
def tmp_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("NS_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NS_ORCH_BACKGROUND", "0")
    monkeypatch.setenv("NS_ORCH_SYNC", "1")
    E._live.clear()
    return tmp_path / "projects"


@pytest.fixture()
def client(tmp_projects):
    from ns_api import app as app_mod
    return TestClient(app_mod.app)


def _upload(c, slug, kind, path: Path):
    return c.post(f"/api/projects/{slug}/script", params={"kind": kind},
                  files={"file": (path.name, path.read_bytes(), "text/markdown")})


def _wizard(c, name="雾港来信") -> str:
    """走完整个向导，返回 slug"""
    slug = c.post("/api/projects", json={"name": name, "slug": "wugang"}).json()["slug"]
    _upload(c, slug, "script", SCRIPT)
    _upload(c, slug, "image_doc", IMAGE_DOC)
    rep = _upload(c, slug, "corrector", CORRECTOR).json()
    assert rep["ok"], rep
    form = c.get(f"/api/projects/{slug}/style").json()["form"]
    assert c.put(f"/api/projects/{slug}/style", json=form).status_code == 200
    assert c.post(f"/api/projects/{slug}/style/confirm", json={"by": "项目方"}).status_code == 200
    for ch in c.get(f"/api/projects/{slug}/characters").json()["characters"]:
        c.post(f"/api/projects/{slug}/characters/{ch['id']}/references", files={"file": ("a.png", PNG, "image/png")})
        assert c.post(f"/api/projects/{slug}/characters/{ch['id']}/confirm",
                      json={"confirmed": True, "by": "项目方"}).status_code == 200
    c.put(f"/api/projects/{slug}/settings", json={"lora_plan": {"identity_image": True}, "adult_content": False})
    r = c.post(f"/api/projects/{slug}/create")
    assert r.status_code == 200, r.text
    return slug


# ------------------------------------------------------------------ 项目模型

def test_default_project_is_repo_root(tmp_projects):
    ps = PC.list_projects()
    assert ps[0].slug == "weita" and ps[0].is_default and ps[0].root == PC.REPO
    d = PC.default_project()
    assert d.script_json == PC.REPO / "data" / "import" / "script_v2.json"
    assert d.renders_gpu3 == PC.REPO / "data" / "renders_gpu3"
    assert "NS_PROJECT_ROOT" not in d.env()


def test_create_project_layout_and_registry(tmp_projects):
    ctx = PC.create_project("雾港来信", "wugang")
    for sub in PC.PROJECT_SUBDIRS:
        assert (ctx.root / sub).is_dir()
    assert ctx.env()["NS_PROJECT_ROOT"] == str(ctx.root)
    assert PC.get_project("wugang").root == ctx.root
    with pytest.raises(ValueError):
        PC.create_project("雾港来信")
    with pytest.raises(ValueError):
        PC.create_project("x", "weita")
    with pytest.raises(ValueError):
        ctx.resolve_inside("../../etc")
    assert PC.slugify("雾港", set()) == "drama-02"


def test_project_root_env_reaches_pipeline_modules(tmp_path):
    """NS_PROJECT_ROOT 让渲染/编译/造型/装配模块的 ROOT 指向项目（子进程里生效；默认不变）"""
    import os
    import subprocess
    import sys
    code = ("import sys; sys.path.insert(0, 'services/post'); from ns_render import pipeline as P, refs as R, grade as G; from ns_agent import compiler as C, looks as L;"
            "from ns_post import assemble as A; print(P.ROOT, R.ROOT, G.ROOT, C.ADULT_OVERRIDES_PATH.parent.parent, L.ROOT, A.ROOT, sep='|')")
    env = {**os.environ, "NS_PROJECT_ROOT": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=PC.REPO,
                         timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert set(out.stdout.strip().split("|")) == {str(tmp_path)}
    from ns_render import pipeline as P
    assert P.ROOT == PC.REPO                                   # 本进程未设变量：默认仍是仓库根


# ------------------------------------------------------------------ 向导

def test_script_validation_report(client):
    slug = client.post("/api/projects", json={"name": "雾港来信"}).json()["slug"]
    rep = _upload(client, slug, "script", SCRIPT).json()
    assert rep["ok"] and rep["episodes"] == 2 and rep["shots"] == 13
    assert [e["shots"] for e in rep["per_episode"]] == [6, 7]
    assert not any("缺少集数" in w for w in rep["warnings"])        # 按实际集数检查，不按 60 集
    assert any("image提示词" in w for w in rep["warnings"])
    assert rep["durations"]["script"] == 13 and rep["durations"]["min"] == 9
    assert rep["dialogue"]["lines"] == 4
    assert [c["name"] for c in rep["character_locks"]] == ["苏眠", "沈既白"]
    rep = _upload(client, slug, "image_doc", IMAGE_DOC).json()
    assert rep["decor"]["ranges"] == 1 and rep["decor"]["missing"] == []
    assert "sumian01" in rep["triggers"]["without_file"] and rep["triggers"]["unknown"] == []
    rep = _upload(client, slug, "corrector", CORRECTOR).json()
    assert rep["corrector"]["rule_count"] == 3
    assert (PC.get_project(slug).script_json).is_file()
    bad = client.post(f"/api/projects/{slug}/script", params={"kind": "script"},
                      files={"file": ("x.png", PNG, "image/png")})
    assert bad.status_code == 422


def test_script_fatal_without_character_locks(client):
    slug = client.post("/api/projects", json={"name": "空剧"}).json()["slug"]
    r = client.post(f"/api/projects/{slug}/script", params={"kind": "script"},
                    files={"file": ("a.md", "## ep01《一》\n\n**镜1｜img**：雨\n".encode(), "text/markdown")}).json()
    assert not r["ok"] and any("角色锁" in f for f in r["fatal"])


def test_style_generates_valid_visual_bible_and_preview(client):
    slug = client.post("/api/projects", json={"name": "雾港来信"}).json()["slug"]
    _upload(client, slug, "script", SCRIPT)
    st = client.get(f"/api/projects/{slug}/style").json()
    form = st["form"]
    assert form["materials"] and form["shot_rules"]                  # 来自模板默认值
    form.update(lens="Leica 50mm f/1.4 级别锐利", realism_texture_strength=0.35, bgm_style="钢琴与大提琴",
                materials=form["materials"] + [{"id": "trench", "match": ["风衣"], "term": "风衣为挺括的米色华达呢"}])
    r = client.put(f"/api/projects/{slug}/style", json=form).json()
    t = tomllib.loads(r["toml"])
    assert t["project"]["name"] == "雾港来信" and t["project"]["slug"] == slug
    assert t["realism"]["loras"][0]["strength"] == 0.35 and t["realism"]["realism_as_texture_only"] is True
    assert t["audio"]["bgm_style"] == "钢琴与大提琴"
    assert {c["name"] for c in t["characters"].values()} == {"苏眠", "沈既白"}
    assert "desire" not in r["toml"] and "欲望" not in r["toml"]      # 欲望强度不在本界面
    assert len(r["preview"]) == 2 and r["preview"][0]["shot"] != r["preview"][1]["shot"]
    p0 = r["preview"][0]
    assert "风衣为挺括的米色华达呢" in p0["prompt"] and "【苏眠】" in p0["prompt"]
    up = client.post(f"/api/projects/{slug}/style/color-reference", files={"file": ("c.jpg", PNG, "image/jpeg")}).json()
    assert up["color_reference"] == "assets/style/color_reference_01.jpg"
    assert tomllib.loads(up["toml"])["look"]["color_reference"] == "assets/style/color_reference_01.jpg"
    assert client.post(f"/api/projects/{slug}/style/confirm", json={"by": "项目方"}).json()["by"] == "项目方"
    assert "[approval]" in PC.get_project(slug).visual_bible.read_text(encoding="utf-8")


def test_character_confirmation_writes_face_reference(client):
    slug = client.post("/api/projects", json={"name": "雾港来信"}).json()["slug"]
    _upload(client, slug, "script", SCRIPT)
    chars = client.get(f"/api/projects/{slug}/characters").json()["characters"]
    cid = chars[0]["id"]
    r = client.post(f"/api/projects/{slug}/characters/{cid}/confirm", json={"confirmed": True, "by": "项目方"})
    assert r.status_code == 422                                      # 没参考图不能确认
    client.post(f"/api/projects/{slug}/characters/{cid}/references", files={"file": ("a.png", PNG, "image/png")})
    c = client.post(f"/api/projects/{slug}/characters/{cid}/confirm", json={"confirmed": True, "by": "项目方"}).json()
    assert c["confirmed"] and c["approved_by"] == "项目方" and c["approved_at"]
    fr = json.loads(PC.get_project(slug).face_reference.read_text(encoding="utf-8"))
    assert fr["characters"][cid]["ai_generated_fictional_adult"] is True
    assert fr["approved_for_adult"] is False                          # 另一个角色还没确认
    # 换参考图 → 确认作废
    c = client.post(f"/api/projects/{slug}/characters/{cid}/references",
                    files={"file": ("b.png", PNG + b"2", "image/png")}).json()
    assert not c["confirmed"]
    # 造型 A/B + 排期 → data/looks（ns_schema.looks 格式）
    body = {"realism": "high", "hair": "黑色及肩短发", "makeup": "淡妆", "looks": [
        {"label": "A", "name": "通勤", "outfit": "米色风衣"}, {"label": "B", "name": "夜", "outfit": "黑色针织裙"}],
        "schedule": [{"look": "B", "episodes": "2"}]}
    assert client.put(f"/api/projects/{slug}/characters/{cid}", json=body).status_code == 200
    from ns_schema.looks import LookBook, LookSchedule
    ctx = PC.get_project(slug)
    lb = LookBook.model_validate_json((ctx.looks_dir / "looks.json").read_text(encoding="utf-8"))
    assert {lk.label for lk in lb.looks if lk.character == cid} == {"A", "B"}
    sc = LookSchedule.model_validate_json((ctx.looks_dir / "schedule.json").read_text(encoding="utf-8"))
    assert sc.episodes["2"][cid].look_id == f"{cid}-look-b"
    bad = client.put(f"/api/projects/{slug}/characters/{cid}", json={"schedule": [{"look": "Z", "episodes": "1"}]})
    assert bad.status_code == 422


def test_create_requires_checklist_then_ready(client):
    slug = client.post("/api/projects", json={"name": "雾港来信"}).json()["slug"]
    r = client.post(f"/api/projects/{slug}/create")
    assert r.status_code == 422
    slug2 = _wizard(client, "雾港来信2")
    p = client.get(f"/api/projects/{slug2}").json()
    assert p["status"] == "ready" and p["readiness"]["ok"]
    assert p["settings"]["adult_content"] is False and p["settings"]["lora_plan"]["identity_image"] is True
    ctx = PC.get_project(slug2)
    assert json.loads(ctx.face_reference.read_text(encoding="utf-8"))["approved_for_adult"] is True
    assert (ctx.config_dir / "voices.json").exists() and ctx.adult_overrides.exists()
    names = [x["slug"] for x in client.get("/api/projects").json()]
    assert names[0] == "weita" and slug2 in names


def test_default_project_is_read_only(client):
    assert client.put("/api/projects/weita/settings", json={"adult_content": True}).status_code == 409
    assert client.post("/api/projects/weita/production/start", json={"mode": "dry_run", "by": "owner"}).status_code == 409


# ------------------------------------------------------------------ 编排器（dry-run，经 API）

def _tick(c, slug, n=1):
    for _ in range(n):
        b = c.post(f"/api/projects/{slug}/production/tick").json()
    return b


def test_production_dry_run_gates_and_board(client):
    slug = _wizard(client)
    b = client.post(f"/api/projects/{slug}/production/start", json={"mode": "dry_run", "by": "owner"}).json()
    assert b["project"]["running"] and b["project"]["mode"] == "dry_run"
    inbox = client.get("/api/inbox").json()
    assert {c["gate"] for c in inbox} == {"G2", "G3"}
    # 关口前什么都不跑
    b = _tick(client, slug, 3)
    assert all(r["lights"]["剧本"]["status"] == "waiting" for r in b["episodes"])
    assert all(r["lights"]["首帧"]["status"] == "pending" for r in b["episodes"])
    # G2：每个角色选母版
    g2 = next(c for c in inbox if c["gate"] == "G2")
    choices = {ch["id"]: ch["candidates"][0] for ch in g2["detail"]["characters"]}
    assert client.post(f"/api/projects/{slug}/cards/G2", json={"by": "owner", "decision": "approve", "payload": {"choices": {}}}).status_code == 409
    client.post(f"/api/projects/{slug}/cards/G2", json={"by": "owner", "decision": "approve", "payload": {"choices": choices}})
    ctx = PC.get_project(slug)
    assert all((ctx.assets_dir / "characters" / cid / "plates" / "master.png").exists() for cid in choices)
    # G3：没有 v3 → 不能采纳，只能跳过
    assert client.post(f"/api/projects/{slug}/cards/G3", json={"by": "owner", "decision": "approve"}).status_code == 409
    client.post(f"/api/projects/{slug}/cards/G3", json={"by": "owner", "decision": "skip"})
    b = _tick(client, slug, 8)                                       # 画面说明、首帧、尾帧……一次一个笔记本任务
    ep1 = b["episodes"][0]
    assert ep1["lights"]["剧本"]["status"] == "done" and ep1["lights"]["首帧"]["status"] == "done"
    cards = client.get("/api/inbox").json()
    assert [c["gate"] for c in cards] == ["GPU3"]                    # 交 gpu3 要项目方授权
    assert ep1["lights"]["视频"]["status"] == "pending"
    client.post(f"/api/projects/{slug}/cards/GPU3", json={"by": "owner", "decision": "approve"})
    b = _tick(client, slug, 2)
    st = json.loads((ctx.orchestrator_dir / "state.json").read_text(encoding="utf-8"))
    assert st["sim_gpu3"]["started"] == [1]                          # G4 前只交第一集
    assert st["episodes"]["2"]["steps"]["handoff"]["status"] == "waiting"
    b = _tick(client, slug, 4)
    assert any(c["gate"] == "G4" for c in client.get("/api/inbox").json())
    client.post(f"/api/projects/{slug}/cards/G4", json={"by": "owner", "decision": "approve"})
    assert (ctx.orchestrator_dir / "PIPELINE_LOCKED.json").exists()
    b = _tick(client, slug, 12)
    assert any(c["gate"] == "G5" for c in client.get("/api/inbox").json())
    assert b["episodes"][0]["lights"]["成片"]["status"] == "gate"
    client.post(f"/api/projects/{slug}/cards/G5:ep01", json={"by": "owner", "decision": "publish"})
    b = client.get(f"/api/projects/{slug}/production").json()
    assert b["episodes"][0]["accept"] == "done"
    assert set(b["episodes"][0]["lights"]) == {"剧本", "首帧", "尾帧", "视频", "QA", "声音", "4K", "成片"}
    assert b["eta"]["total_s"] >= 0 and b["log"]
    g = client.get("/api/gpus", params={"project": slug}).json()
    assert g["gpu3"]["simulated"] and any(x.get("faulty") for x in g["gpu3"]["gpus"])


# ------------------------------------------------------------------ 编排器（引擎直测）

class FlakyExecutor(DryRunExecutor):
    def __init__(self, fail_steps=()):
        super().__init__()
        self.fail_steps = set(fail_steps)

    def render_frames(self, ctx, ep, stage):
        if ("render", ep, stage) in self.fail_steps:
            raise StepFailed("ComfyUI 报错")
        return super().render_frames(ctx, ep, stage)


def _ready_engine(client, executor, bridge=None):
    slug = _wizard(client)
    ctx = PC.get_project(slug)
    eng = E.Engine(ctx, executor, bridge, sync=True)
    eng.start("real")
    st = eng.load()
    cands = {c["id"]: c["candidates"][0] for c in st["gates"]["G2"]["detail"]["characters"]}
    eng.decide("G2", "approve", {"choices": cands})
    eng.decide("G3", "skip")
    return ctx, eng


def test_engine_never_renders_video_or_adult_and_blocks_after_3_failures(client):
    ex = FlakyExecutor(fail_steps={("render", 2, "image")})
    bridge = FakeBridge()
    ctx, eng = _ready_engine(client, ex, bridge)
    for _ in range(20):
        eng.tick()
    stages = {c[3] for c in ex.calls if c[0] == "render"}
    assert stages <= {"image", "last"}                               # 笔记本只出图片
    st = eng.load()
    rec = st["episodes"]["2"]["steps"]["first"]
    assert rec["status"] == "blocked" and rec["attempts"] == 3       # 3 次后进异常队列
    assert st["episodes"]["1"]["steps"]["last"]["status"] == "done"  # 不影响别的集
    assert bridge.calls == []                                        # 未授权不交 gpu3
    b = eng.board()
    assert any(x["episode"] == 2 and x["step"] == "first" and x["retryable"] for x in b["exceptions"])
    ex.fail_steps.clear()
    eng.retry(2, "first")
    for _ in range(4):
        eng.tick()
    assert eng.load()["episodes"]["2"]["steps"]["first"]["status"] == "done"
    eng.decide("GPU3", "approve")
    assert bridge.calls[0] == ("start", [1], False)                 # 成人开关关 → adult_content False


def test_engine_reads_gpu3_status_and_is_idempotent(client):
    bridge = FakeBridge()
    ex = DryRunExecutor()
    ctx, eng = _ready_engine(client, ex, bridge)
    for _ in range(10):
        eng.tick()
    eng.decide("GPU3", "approve")
    n_calls = len(ex.calls)
    bridge.status = {1: {"frames": {"done": 6, "total": 6}, "videos": {"done": 6, "total": 6},
                         "qa": {"state": "auto_pass"}, "audio": {"voiceover": True, "music": "data/music/ep01.wav"},
                         "upscale_4k": {"state": "partial", "shots_4k": 2}, "eta_s": 1200, "errors": ["S3 HARD"]}}
    eng.tick()
    s = eng.load()["episodes"]["1"]["steps"]
    assert (s["video"]["status"], s["qa"]["status"], s["audio"]["status"], s["upscale"]["status"]) == \
        ("done", "done", "done", "running")
    assert any(c["gate"] == "G4" for c in eng.cards())
    b = eng.board()
    assert any(x["source"] == "gpu3" and "HARD" in x["error"] for x in b["exceptions"])
    # 重复 tick 不重复执行已完成的笔记本步骤（assemble 例外：视频齐了之后才第一次跑）
    before = [c for c in ex.calls if c[0] != "assemble"]
    for _ in range(3):
        eng.tick()
    assert [c for c in ex.calls if c[0] != "assemble"][:len(before)] == before
    assert len([c for c in ex.calls if c[0] == "render" and c[2] == 1]) == 2 and n_calls >= 4


def test_engine_resumes_running_step_after_restart(client):
    ctx, eng = _ready_engine(client, DryRunExecutor())
    st = eng.load()
    st["episodes"].setdefault("1", {"steps": {}})["steps"]["frame_spec"] = {"status": "running", "token": "dead", "attempts": 0}
    eng.save(st)
    st = E.Engine(ctx, DryRunExecutor(), None).load()
    assert st["episodes"]["1"]["steps"]["frame_spec"]["status"] == "pending"


def test_series_control_file_fallback(tmp_projects, monkeypatch, tmp_path):
    """桥不可达时写 series_control.json（测试项目，写到临时目录）"""
    from ns_orch import gpu3 as G
    ctx = PC.create_project("测试剧", "t42test")
    monkeypatch.setattr(G.Gpu3Bridge, "control_file", staticmethod(lambda c: tmp_path / "rg" / c.slug / "series_control.json"))
    b = G.Gpu3Bridge("http://127.0.0.1:9", timeout=0.2)
    r = b.series(ctx, "start", [1], adult_content=False, requested_by="项目方")
    assert r["via"] == "file"
    rec = json.loads((tmp_path / "rg" / "t42test" / "series_control.json").read_text(encoding="utf-8"))
    assert rec["schema"] == "nsfs_canvas.series_control/v1" and rec["project"] == "t42test" and rec["episodes"] == [1]
    assert (tmp_path / "rg" / "t42test" / "series_control.log.jsonl").exists()


def test_normalize_bridge_shapes():
    from ns_orch.gpu3 import normalize
    assert normalize({"done": 3, "total": 6})["status"] == "running"
    assert normalize({"state": "none", "issues": []})["status"] == "pending"
    assert normalize({"state": "stale"})["status"] == "failed"
    assert normalize({"verdict": "pass"})["status"] == "done"
    assert normalize({"voiceover": False, "music": None, "stems_shots": 0})["status"] == "pending"
    assert normalize({"exists": True, "file": "x"})["status"] == "done"
    assert normalize("3/6")["done"] == 3
