"""S2/S3（fredw-92/S-back）：场景资产库（参考图 / 生成 / 版本 / 定稿 + S2 闸门语义）与首帧接入（底图参考 + 【场景】段 + 过期）。
临时目录 + 固定剧本（tests/fixtures/t06_golden，ep02-S1..S3 = sk_office），假 ComfyUI，不碰 GPU 和 data/。占位文本只是格式占位。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_agent.looks import LookStore
from ns_agent import state_timeline as ST
from ns_api import asset_edit as AED
from ns_api import assets as A
from ns_api import jobs as J
from ns_api import ref_switch as RSW
from ns_api import scene_assets as SA
from ns_api.looks import get_store
from ns_render import pipeline as P
from ns_render import refs as R
from ns_render import scene_plate as SP
from ns_render.comfy_client import ComfyClient
from ns_schema.script import SceneEntry, ScriptImport

PINNED = Path(__file__).resolve().parent / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
S1, S2, S3, S4 = "ep02-S1", "ep02-S2", "ep02-S3", "ep02-S4"


def _script_with_scenes() -> ScriptImport:
    sc = ScriptImport.model_validate_json(PINNED.read_text(encoding="utf-8"))
    sc.globals.scene_library = [SceneEntry(scene_id="sk_office", name="占位名称", space="占位空间", time_of_day="占位时段",
                                           light="占位光线", fixtures="占位陈设", defined_in=[None])]
    ep = next(e for e in sc.episodes if e.number == 2)
    ep.shots[0].scene_id, ep.shots[0].scene_detail = "sk_office", "占位细节"
    return sc


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    data = root / "data"
    (root / "assets" / "characters" / "lin_wan").mkdir(parents=True)
    (root / "assets" / "scenes" / "sk_office").mkdir(parents=True)
    (root / "assets" / "scenes" / "sk_office" / "plate.png").write_bytes(PNG + b"old")
    script = _script_with_scenes()
    store = LookStore(data / "looks")
    store._script = script
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(A, "ROOT", root)
    monkeypatch.setattr(A, "ASSETS_DIR", root / "assets")
    monkeypatch.setattr(RSW, "project_root", lambda: root)
    monkeypatch.setattr(SA, "_store", lambda: store)
    app = FastAPI()
    for r in (A.router, RSW.router, SA.router, AED.router, J.router):
        app.include_router(r)
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app), store, root, script


class FakeComfy:
    def __init__(self):
        self.submitted, self.uploads = [], []

    def check(self, wf):
        return []

    def upload_image(self, path, subfolder="ns_final"):
        self.uploads.append(Path(path).name)
        return f"{subfolder}/{Path(path).name}"

    def submit(self, wf):
        self.submitted.append(wf)
        return f"p{len(self.submitted)}"

    def _json(self, path, body=None):
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[-1]
            return {pid: {"status": {"completed": True, "status_str": "success"},
                          "outputs": {"90": {"images": [{"filename": f"{pid}.png", "subfolder": "", "type": "output"}]}}}}
        return {"queue_running": [], "queue_pending": []}

    output_files = staticmethod(ComfyClient.output_files)

    def download(self, item, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(PNG + f"gen{len(self.submitted)}".encode())
        return dest

    def interrupt(self):
        pass


def _wait(c, jid):
    for _ in range(300):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.02)
    raise AssertionError("任务没结束")


# ---------------------------------------------------------------- S1 对齐：分组以剧本场景 id 为准

def test_group_scenes_uses_script_scene_ids(env):
    _, store, _, script = env
    rows = {r["shot_id"]: r for r in ST.group_scenes(script)}
    assert rows[S1]["scene_id"] == "sk_office" and rows[S1]["place"] == "占位名称"
    assert rows[S1]["place_source"] == "script"
    old = ScriptImport.model_validate_json(PINNED.read_text(encoding="utf-8"))
    assert ST.group_scenes(old) == [r for r in ST.group_scenes(old)]          # 旧剧本：确定性、不变
    assert {r["scene_id"] for r in ST.group_scenes(old) if r["shot_id"] in (S1, S2, S3)} == {"sk_office"}


# ---------------------------------------------------------------- S2 资产库

def test_scene_list_detail_refs_gen_version_lock(env, monkeypatch):
    c, store, root, _ = env
    r = c.get("/api/assets/scenes")
    assert r.status_code == 200, r.text
    card = next(x for x in r.json()["scenes"] if x["scene_id"] == "sk_office")
    assert card["kind"] == "scene" and card["name"] == "占位名称" and card["description"]["source"] == "script"
    assert 2 in card["episodes"] and card["shot_count"] >= 3          # 跨集共用
    assert card["plate"]["plate_status"] == "candidate" and not card["plate"]["locked"]
    assert [x["id"] for x in r.json()["roles"]] == ["space", "style", "color", "prop"]
    assert c.get("/api/assets/scenes/sk_nope").status_code == 404

    # 参考图：用途 空间|风格|色彩|道具（中文也收）；人物用途不收
    up = c.post("/api/assets/sk_office/refs", files={"file": ("a.png", PNG + b"a")}, data={"role": "空间"})
    assert up.status_code == 200, up.text
    ref = up.json()
    assert ref["role"] == "space" and ref["role_label"] == "取空间"
    assert ref["file"].startswith("assets/scenes/sk_office/refs/")
    assert c.post("/api/assets/sk_office/refs", files={"file": ("a.png", PNG)}, data={"role": "identity"}).status_code == 422
    prop = c.post("/api/assets/sk_office/refs", files={"file": ("b.png", PNG + b"b")}, data={"role": "prop"}).json()

    # 生成（jobs.py 按卡队列）→ 版本
    fc = FakeComfy()
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    r = c.post("/api/assets/sk_office/gen-jobs", json={"refs": [{"ref_id": prop["ref_id"]}, {"ref_id": ref["ref_id"]}],
                                                      "prompt": "原话原样", "strength": "medium", "gpu": 0})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["state"] == "done", job
    assert [x["role"] for x in job["params"]["images"]] == ["space", "prop"]     # 空间 → 道具
    assert job["file"].startswith("assets/scenes/sk_office/refs/gen/")
    v1 = c.post("/api/assets/sk_office/versions", json={"job_id": job["job_id"], "label": "v1"})
    assert v1.status_code == 200, v1.text
    assert v1.json()["version"] == 1 and v1.json()["variant"] == "main" and v1.json()["asset_id"] == "sk_office"
    v2 = c.post("/api/assets/sk_office/versions", json={"file": ref["file"], "label": "夜", "variant": "night"}).json()
    assert v2["version"] == 2 and v2["variant"] == "night"
    assert c.post("/api/assets/sk_office/versions", json={"file": ref["file"], "variant": "Bad Name"}).status_code == 422

    # 定稿（画布）：主底图换成 v1，旧图留档；闸门仍是 candidate（不冒充项目方确认）
    r = c.post("/api/assets/scenes/sk_office/plate", json={"version": 1})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["plate"]["locked"] and out["plate"]["locked_by"] == "canvas"
    assert out["plate"]["plate_status"] == "candidate" and not out["plate"]["s2_gate_ok"]
    assert (root / "assets/scenes/sk_office/plate.png").read_bytes() == (root / job["file"]).read_bytes()
    assert any((root / "assets/scenes/sk_office/history").iterdir())
    assert ST.plate_info(root, "sk_office")["plate_status"] == "candidate"
    # 变体定稿 → plate_night.png（ref_switch 底图候选里能选到）
    r = c.post("/api/assets/scenes/sk_office/plate", json={"version": 2}).json()
    assert r["variant"] == "night" and r["plate_id"] == "sk_office/plate_night.png"
    assert any(o["plate_id"] == "sk_office/plate_night.png" for o in RSW.plate_options("sk_office"))
    # 项目方确认：必须带原话；带了 → owner_confirmed（S2 闸门通过）
    assert c.post("/api/assets/scenes/sk_office/plate", json={"version": 1, "by": "owner"}).status_code == 422
    r = c.post("/api/assets/scenes/sk_office/plate", json={"version": 1, "by": "owner", "owner_quote": "占位原话"})
    assert r.json()["plate"]["plate_status"] == "owner_confirmed" and r.json()["plate"]["s2_gate_ok"]
    # 详情：描述 / 底图 / 变体 / 版本 / 参考图 / 用到的镜头；资产编辑器同形 assets[]
    d = c.get("/api/assets/scenes/sk_office").json()
    assert {v["variant"] for v in d["variants"]} >= {"main", "night"}
    assert len(d["version_list"]) == 2 and len(d["refs_list"]) == 2 and d["assets"][0]["kind"] == "scene"
    shot = next(x for x in d["usage"]["shots"] if x["shot_id"] == S1)
    assert shot["scene_detail"] == "占位细节" and shot["scene_source"] == "script"
    assert c.get("/api/assets/sk_office").json()["asset"]["kind"] == "scene"
    # 取消画布定稿：文件不动
    r = c.delete("/api/assets/scenes/sk_office/plate", params={"variant": "night"})
    assert r.status_code == 200 and (root / "assets/scenes/sk_office/plate_night.png").is_file()


# ---------------------------------------------------------------- S3 首帧接入

def test_shot_plate_lock_and_stale(env, monkeypatch):
    c, store, root, script = env
    monkeypatch.setattr(SP, "scene_map", lambda sc: {r["shot_id"]: r["scene_id"] for r in ST.group_scenes(sc)})
    renders = root / "data" / "renders"
    assert SP.shot_plate(script, S1, root, renders) is None              # 有底图但没定稿：不带
    p = root / "x.png"
    p.write_bytes(PNG + b"v1")
    c.post("/api/assets/sk_office/versions", json={"file": "x.png", "label": "a"})
    c.post("/api/assets/scenes/sk_office/plate", json={"version": 1})
    sp = SP.shot_plate(script, S2, root, renders)                         # S2 没写场景：按推断分组也是 sk_office
    assert sp["scene_id"] == "sk_office" and sp["source"] == "locked" and sp["path"] == "assets/scenes/sk_office/plate.png"
    take = {"stage": "image", "scene_plate": sp}
    assert SP.stale_reasons(take, root) == []
    # 首帧版本记了这张底图 → 换定稿版本后过期「场景底图已改」，定稿接口报出受影响镜头
    d = P.shot_dir(S2) / "takes"
    d.mkdir(parents=True)
    (d / "image_001.png").write_bytes(PNG)
    (P.shot_dir(S2) / "takes.json").write_text(json.dumps({"active": {"image": 1}, "takes": [
        {"n": 1, "stage": "image", "file": "renders/ep02/S2/takes/image_001.png", "seed": 1, "prompt": "",
         "created_at": "2026", "scene_plate": sp}]}), encoding="utf-8")
    p.write_bytes(PNG + b"v2")
    c.post("/api/assets/sk_office/versions", json={"file": "x.png", "label": "b"})
    out = c.post("/api/assets/scenes/sk_office/plate", json={"version": 2}).json()
    assert out["stale_shots"] == [S2] and out["stale_reason"] == "场景底图已改"
    assert SP.stale_reasons(take, root) == ["场景底图已改"]
    # 画布本镜覆盖：选“不用底图” → 不带
    from ns_agent import ref_overrides as RO
    RO.set_shot(renders, S2, RO.RefOverrides(scene="none"))
    assert SP.shot_plate(script, S2, root, renders) is None


def test_role_line_scene_after_characters(tmp_path):
    face, plate = tmp_path / "f.png", tmp_path / "p.png"
    plan = R.RefPlan([R.RefImage(face, "face", "林晚")]).with_scene(plate)
    lines = plan.role_lines()
    assert [r.kind for r in plan.refs] == ["face", "scene"]
    assert "图2只取场景空间与陈设，不取人物。" in lines and lines.index("图1") < lines.index("图2只取场景")
    assert R.RefPlan().with_scene(plate).role_lines().startswith("图1只取场景空间与陈设，不取人物。")
    assert plan.with_scene(plate) is plan                                  # 不重复


def test_compiler_scene_segment_verbatim(env):
    from ns_agent.compiler import compile_shot, scene_segment
    _, _, _, script = env
    ep = next(e for e in script.episodes if e.number == 2)
    seg = scene_segment(ep.shots[0], script.globals)
    assert seg == "【场景】名称：占位名称；空间描述：占位空间；时段：占位时段；光线：占位光线；固定陈设：占位陈设；本镜场景：占位细节"
    assert scene_segment(ep.shots[1], script.globals) == ""               # 没写场景的镜头不加
    c = compile_shot(ep, ep.shots[0], script.globals, set())
    assert seg in c.image_prompt and seg not in c.last_prompt
    c2 = compile_shot(ep, ep.shots[1], script.globals, set())
    assert "【场景】" not in c2.image_prompt


def test_render_image_adds_scene_plate_ref(tmp_path, monkeypatch):
    """首帧（画布 regen 走 render_image）：没有身份底板时只带场景底图 = 图1 + 用途说明；take 记下 scene_plate"""
    data = tmp_path / "data"
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(P, "check_not_gpu3", lambda sid: None)
    plate = tmp_path / "plate.png"
    from PIL import Image
    Image.new("RGB", (64, 112), (10, 20, 30)).save(plate)
    sp = {"scene_id": "sk_office", "plate_id": "sk_office/plate.png", "path": str(plate), "sha256": "abc",
          "source": "locked"}
    monkeypatch.setattr(P, "shot_scene_plate", lambda script, shot_id: sp)
    monkeypatch.setattr(P, "shot_looks_map", lambda shot_id: {})
    monkeypatch.setattr(R, "prescale", lambda r, scale=1.0: r.path)     # 不往 data/cache 写

    class C(FakeComfy):
        def object_info(self):
            return {"LoraLoaderModelOnly": {"input": {"required": {"lora_name": [[]]}}}}

        def run(self, wf, timeout_s):
            pid = self.submit(wf)
            return self._json(f"/history/{pid}")[pid], 1.0
    fc = C()
    script = ScriptImport.model_validate_json(PINNED.read_text(encoding="utf-8"))
    take = P.render_image(fc, script, S1, candidates=1, rounds=1, score_fn=None, qc_fn=lambda p: None, grade=False,
                          face_lock=False)
    wf = fc.submitted[-1]
    prompt = next(n["inputs"]["prompt"] for n in wf.values() if "prompt" in n.get("inputs", {}))
    assert prompt.startswith("图1只取场景空间与陈设，不取人物。")
    assert take.scene_plate == sp and take.workflow.startswith("qwen_edit_plate")
    saved = P.load_takes(S1)["takes"][-1]
    assert saved["scene_plate"]["plate_id"] == "sk_office/plate.png"
    # 关掉 → 照旧文生图
    take2 = P.render_image(fc, script, S1, candidates=1, rounds=1, score_fn=None, qc_fn=lambda p: None, grade=False,
                           face_lock=False, scene_ref=False)
    assert take2.scene_plate is None and take2.workflow.startswith("qwen_t2i")
