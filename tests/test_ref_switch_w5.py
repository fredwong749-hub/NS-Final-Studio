"""api_v1_contract §E（fredw-92/W5）：本镜参考切换三层继承、影响面预览、应用范围、owner 闸门、资产参考图组 / 生成 / 版本。
临时目录 + 固定剧本（tests/fixtures/t06_golden），假 ComfyUI，不碰 GPU 和 data/。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_agent import ref_overrides as RO
from ns_agent.looks import LookStore
from ns_api import asset_edit as AED
from ns_api import assets as A
from ns_api import jobs as J
from ns_api import ref_switch as RSW
from ns_api.looks import get_store
from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient
from ns_schema.edits import EpisodeEdit, ShotEdit
from ns_schema.looks import Look
from ns_schema.script import ScriptImport

PINNED = Path(__file__).resolve().parent / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
# ep02-S1..S3 = 同一场景 sk_office；ep02-S4 = sk_taxi
S1, S2, S3, S4 = "ep02-S1", "ep02-S2", "ep02-S3", "ep02-S4"
CLEAR, PATENT = "lora-hh12clear", "lora-hh12patent"


@pytest.fixture(scope="module")
def script() -> ScriptImport:
    return ScriptImport.model_validate_json(PINNED.read_text(encoding="utf-8"))


@pytest.fixture()
def env(tmp_path, script, monkeypatch):
    root = tmp_path / "proj"
    data = root / "data"
    (root / "assets" / "characters" / "lin_wan").mkdir(parents=True)
    (root / "assets" / "scenes" / "sk_office").mkdir(parents=True)
    (root / "assets" / "scenes" / "sk_office" / "plate.png").write_bytes(PNG)
    (root / "assets" / "scenes" / "sk_office" / "night.png").write_bytes(PNG + b"n")
    store = LookStore(data / "looks")
    store._script = script
    store.upsert_look(Look(id="lw-look-b", character="lin_wan", name="通勤 B", label="B",
                           items={"shoes": [PATENT], "outfit": ["kw-suit-skirt"]}))
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(A, "ROOT", root)
    monkeypatch.setattr(A, "ASSETS_DIR", root / "assets")
    monkeypatch.setattr(RSW, "project_root", lambda: root)
    app = FastAPI()
    for r in (A.router, RSW.router, AED.router, J.router):
        app.include_router(r)
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app), store, root


def _lw(store, shot_id):
    return next(c for c in store.shot_looks(shot_id).characters if c.character == "lin_wan")


def _shoes(store, shot_id):
    r = _lw(store, shot_id)
    return r.slots["shoes"].items if "shoes" in r.slots else [], r.slots.get("shoes") and r.slots["shoes"].source


def _apply(c, shot, scope, change, **kw):
    return c.post(f"/api/shots/{shot}/refs/apply", json={"scope": scope, "change": change, **kw})


# ---------------------------------------------------------------- schema

def test_schema_backward_compatible():
    assert ShotEdit.model_validate({}).ref_overrides.is_empty()
    assert ShotEdit.model_validate({"ref_overrides": None}).ref_overrides.is_empty()
    assert EpisodeEdit.model_validate({"boost_first": "x"}).scene_overrides == {}
    e = ShotEdit.model_validate({"ref_overrides": {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}}})
    assert e.ref_overrides.characters["lin_wan"].parts == {"shoes": CLEAR}
    with pytest.raises(ValueError):
        ShotEdit.model_validate({"ref_overrides": {"characters": {"lin_wan": {"parts": {"wings": "x"}}}}})


# ---------------------------------------------------------------- 三层继承

def test_resolution_precedence_episode_scene_shot(env):
    c, store, _ = env
    assert _shoes(store, S1)[0] == []
    r = _apply(c, S1, "scene", {"characters": {"林晚": {"parts": {"shoes": CLEAR}}}})
    assert r.status_code == 200, r.text
    assert set(r.json()["affected"]) == {S1, S2, S3}
    r = _apply(c, S2, "shot", {"characters": {"lin_wan": {"parts": {"shoes": PATENT}}}})
    assert r.status_code == 200 and r.json()["affected"] == [S2]
    assert _shoes(store, S1) == ([CLEAR], "scene")
    assert _shoes(store, S2) == ([PATENT], "shot")      # 镜头 > 场景
    assert _shoes(store, S3) == ([CLEAR], "scene")
    assert _shoes(store, S4)[0] == []                    # 别的场景不受影响
    # 写在契约位置：edits.json ref_overrides、episode_edit.json scene_overrides，索引同步
    assert P.load_edit(S2).ref_overrides.characters["lin_wan"].parts == {"shoes": PATENT}
    assert P.load_episode_edit(2).scene_overrides["sk_office"].characters["lin_wan"].parts == {"shoes": CLEAR}
    assert RO.rebuild_index(P.RENDERS) == RO.load_index(P.RENDERS) | {}
    view = c.get(f"/api/shots/{S2}/refs").json()
    lw = next(x for x in view["characters"] if x["id"] == "lin_wan")
    assert lw["source"] == "shot" and lw["effective"]["parts"]["shoes"] == PATENT
    assert lw["layers"]["scene"]["parts"] == {"shoes": CLEAR}
    assert any(o["id"] == "lw-look-b" for o in lw["options"]["looks"])
    assert {o["id"] for o in lw["options"]["parts"]["shoes"]} >= {CLEAR, PATENT}
    assert c.get(f"/api/shots/{S4}/refs").json()["characters"][0]["source"] == "episode"
    # 恢复集默认：清掉镜头层 → 回到场景层
    r = _apply(c, S2, "shot", {"reset": True})
    assert r.status_code == 200 and _shoes(store, S2) == ([CLEAR], "scene")
    assert S2 not in RO.load_index(P.RENDERS)["shots"]


def test_look_swap_replaces_whole_set_and_parts_override_on_top(env):
    c, store, _ = env
    _apply(c, S1, "shot", {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}})
    r = _apply(c, S1, "shot", {"characters": {"lin_wan": {"look": "lw-look-b"}}})
    lw = _lw(store, S1)
    assert lw.look_id == "lw-look-b" and lw.slots["shoes"].items == [PATENT]   # 整套换掉，本层旧单件清空
    assert r.json()["layer"]["characters"]["lin_wan"] == {"look": "lw-look-b", "parts": {}}
    _apply(c, S1, "shot", {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}})
    lw = _lw(store, S1)
    assert lw.look_id == "lw-look-b" and lw.slots["shoes"].items == [CLEAR] and lw.slots["outfit"].items == ["kw-suit-skirt"]


def test_only_existing_assets(env):
    c, _, _ = env
    bad = [({"characters": {"lin_wan": {"parts": {"shoes": "no-such"}}}}, "没有这个资产"),
           ({"characters": {"lin_wan": {"parts": {"shoes": "kw-suit-skirt"}}}}, "不能放到"),
           ({"characters": {"lin_wan": {"parts": {"outfit": "gc-shirt"}}}}, "属于"),
           ({"characters": {"lin_wan": {"look": "gu_chen-default"}}}, "属于"),
           ({"scene": "sk_office/nope.png"}, "场景底图")]
    for change, msg in bad:
        r = c.post(f"/api/shots/{S1}/refs/preview", json={"scope": "shot", "change": change})
        assert r.status_code == 422 and msg in r.json()["detail"], (change, r.text)


# ---------------------------------------------------------------- 预览

def test_preview_affected_stale_continuity_and_no_write(env):
    c, store, _ = env
    d = P.shot_dir(S2)
    d.mkdir(parents=True)
    (d / "takes.json").write_text(json.dumps({"active": {"image": 1}, "takes": [
        {"n": 1, "stage": "image", "file": "x.png", "seed": 1, "prompt": "p", "created_at": "2026"}]}), encoding="utf-8")
    r = c.post(f"/api/shots/{S2}/refs/preview",
               json={"scope": "shot", "change": {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}},
                                                 "scene": "sk_office/night.png"}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["affected"] == [S2] and out["stale"] == [S2] and out["scope_shots"] == [S2]
    w = out["continuity_warnings"]
    assert {(x["prev_shot_id"], x["shot_id"]) for x in w if x["kind"] == "look_differs"} == {(S1, S2), (S2, S3)}
    assert any(x["kind"] == "plate_differs" for x in w)
    assert all("shoes" in x["fields"] for x in w if x["kind"] == "look_differs")
    assert not RO.index_path(P.RENDERS).exists() and P.load_edit(S2).ref_overrides.is_empty()   # 预览不写
    # 整场改：场内一致，无衔接警告
    out = c.post(f"/api/shots/{S2}/refs/preview", json={"scope": "scene", "change": {
        "characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}}}).json()
    assert set(out["affected"]) == {S1, S2, S3} and out["continuity_warnings"] == []
    # 与下一层相同的单件不记录（只存差异）
    out = c.post(f"/api/shots/{S2}/refs/preview", json={"scope": "episode", "change": {
        "characters": {"lin_wan": {"parts": {"makeup": "lw-makeup-bare"}}}}}).json()
    assert out["affected"] == [] and out["requires_owner"]


def test_copy_from_other_shot(env):
    c, store, _ = env
    _apply(c, S1, "shot", {"characters": {"lin_wan": {"look": "lw-look-b"}}})
    r = _apply(c, S3, "shot", {"copy_from": S1})
    assert r.status_code == 200, r.text
    assert _lw(store, S3).look_id == "lw-look-b"


# ---------------------------------------------------------------- 集默认（owner 闸门）

def test_episode_scope_requires_owner_and_invalidates_confirmation(env):
    c, store, _ = env
    store.confirm_episodes("2", "lin_wan", "项目方原话：ep02 造型确认")
    assert store.resolver().episode_confirmed("lin_wan", 2)
    change = {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}}
    r = _apply(c, S1, "episode", change)
    assert r.status_code == 403 and "by=owner" in r.json()["detail"]
    assert _apply(c, S1, "episode", change, by="agent").status_code == 403
    r = _apply(c, S1, "episode", change, by="owner")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["look_confirmed"] is False and "失效" in out["message"]
    assert not store.resolver().episode_confirmed("lin_wan", 2)
    ep = store.schedule().episodes["2"]["lin_wan"]
    assert ep.slots["shoes"] == [CLEAR] and ep.slots.get("makeup")   # 只并入这一件，集计划其它槽位保留
    assert ep.owner_confirmed_at is None
    assert set(out["affected"]) >= {S1, S2, S3, S4}
    assert _shoes(store, S4) == ([CLEAR], "episode")
    assert _apply(c, S1, "episode", {"scene": "none"}, by="owner").status_code == 422


# ---------------------------------------------------------------- 哈希 / 过期 / 编译器

def test_override_changes_hash_and_compiler_fragments(env, monkeypatch):
    c, store, _ = env
    before = store.shot_looks(S2).look_hash
    _apply(c, S2, "shot", {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}})
    after = store.shot_looks(S2).look_hash
    assert before != after and store.shot_looks(S1).look_hash == store.resolver(canvas=False).shot_looks(
        store.shot(S1)).look_hash
    # 无覆盖时与不读画布的解析完全一致（旧 take 不会因为上线本功能而过期）
    assert store.resolver(canvas=False).shot_looks(store.shot(S2)).look_hash == before
    # 编译器：[looks] inject 关闭 / 集未确认时，只注入画布换过的槽位
    from ns_agent import compiler as CMP
    from ns_agent.bible import load_bible
    res = store.resolver()
    monkeypatch.setattr(CMP, "_resolver", lambda root: res)
    shot = store.shot(S2)
    frags = CMP.look_fragments(shot, ["林晚"], "", [], load_bible(), canvas_only=True)
    assert len(frags) == 1 and frags[0].startswith("【林晚造型】") and "透明细高跟" in frags[0]
    assert "素颜" not in frags[0]                       # 集计划的妆不注入（未确认）
    assert CMP.look_fragments(store.shot(S1), ["林晚"], "", [], load_bible(), canvas_only=True) == []
    # take 盖章的 look_hash 与当前不同 → API 判“造型已改”；inputs_sha 用同一解析（state_timeline）
    assert res.canvas_slots("lin_wan", 2, S2) == ["shoes"]


def test_scene_plate_override_enters_inputs_hash(env):
    _, store, root = env
    cv = RO.Canvas({"shots": {}, "scenes": {}})
    assert RO.effective_scene(cv, 2, "sk_office", S1) == (None, "episode")
    cv = RO.Canvas({"shots": {S1: RO.RefOverrides(scene="none")},
                    "scenes": {"2": {"sk_office": RO.RefOverrides(scene="sk_office/night.png")}}})
    assert RO.effective_scene(cv, 2, "sk_office", S1) == ("none", "shot")
    assert RO.effective_scene(cv, 2, "sk_office", S2) == ("sk_office/night.png", "scene")
    assert RO.plate_path(root, "sk_office/night.png").is_file()
    assert RO.plate_path(root, "../x.png") is None and RO.plate_path(root, "none") is None
    from ns_agent import state_timeline as ST
    assert any(p.name == "ref_overrides.json" for p in ST.input_files(root))


def test_render_refs_prefer_overridden_part_images(env, monkeypatch):
    from ns_render import refs as R
    _, _, root = env
    face = root / "face.png"
    face.write_bytes(PNG)
    shoe = root / "assets" / "shoe.png"
    shoe.write_bytes(PNG + b"s")
    monkeypatch.setattr(R, "ROOT", root)
    monkeypatch.setattr(R, "face_plate", lambda cid, design, angle="F": (face, {}))
    monkeypatch.setattr(R, "_item", lambda cid, kind: None)
    plan = R.plan_refs("林晚踩着高跟鞋走进", ["林晚"], {"林晚": {"part_images": {"shoes": "assets/shoe.png"}}})
    assert [(r.kind, r.path) for r in plan.refs] == [("face", face), ("shoes", shoe)]


# ---------------------------------------------------------------- 资产：参考图组

def test_asset_ref_upload_roles_from_take_copy(env):
    c, store, root = env
    r = c.post(f"/api/assets/{CLEAR}/refs", files={"file": ("a.png", PNG, "image/png")}, data={"role": "style"})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["role"] == "style" and ref["role_label"] == "取风格" and (root / ref["file"]).is_file()
    assert ref["file"].startswith("assets/characters/lin_wan/refs/lora-hh12clear/")
    assert c.post(f"/api/assets/{CLEAR}/refs", files={"file": ("a.png", PNG)}, data={"role": "pose"}).status_code == 422
    assert c.post(f"/api/assets/{CLEAR}/refs", files={"file": ("a.txt", b"x")}, data={"role": "item"}).status_code == 422
    assert c.post("/api/assets/no-such/refs", files={"file": ("a.png", PNG)}, data={"role": "item"}).status_code == 404
    # 从定稿帧设为参考
    d = P.shot_dir(S1) / "takes"
    d.mkdir(parents=True)
    (d / "image_001.png").write_bytes(PNG + b"t")
    (P.shot_dir(S1) / "takes.json").write_text(json.dumps({"active": {"image": 1}, "takes": [
        {"n": 1, "stage": "image", "file": "renders/ep02/S1/takes/image_001.png", "seed": 1, "prompt": "",
         "created_at": "2026"}]}), encoding="utf-8")
    r = c.post("/api/assets/lw-look-b/refs/from-take", json={"shot": S1, "stage": "first", "n": 1, "role": "identity"})
    assert r.status_code == 200, r.text
    assert r.json()["origin"] == {"shot": S1, "stage": "image", "n": 1, "file": "renders/ep02/S1/takes/image_001.png"}
    assert c.post("/api/assets/lw-look-b/refs/from-take",
                  json={"shot": S1, "stage": "first", "n": 9, "role": "item"}).status_code == 404
    # 从其他资产复制（用途可改）
    r = c.post("/api/assets/lin_wan/refs/copy", json={"from_asset": CLEAR, "ref_id": ref["ref_id"], "role": "color"})
    assert r.status_code == 200 and r.json()["role"] == "color"
    detail = c.get("/api/assets/characters/lin_wan").json()
    assert set(detail["asset_refs"]) == {CLEAR, "lw-look-b", "lin_wan"} and 2 in detail["episodes"]
    assert A.resolve_asset_ref(ref["ref_id"]) == ref["file"]          # W2 frame-jobs 用
    assert c.delete(f"/api/assets/{CLEAR}/refs/{ref['ref_id']}").json() == []


# ---------------------------------------------------------------- 资产：生成 + 版本

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
        dest.write_bytes(PNG + b"gen")
        return dest

    def interrupt(self):
        pass


def _wait(c, jid):
    for _ in range(200):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.02)
    raise AssertionError("任务没结束")


def test_asset_gen_job_and_version(env, monkeypatch):
    c, store, root = env
    fc = FakeComfy()
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    up = lambda role: c.post(f"/api/assets/{CLEAR}/refs", files={"file": (f"{role}.png", PNG + role.encode())},  # noqa: E731
                             data={"role": role}).json()["ref_id"]
    base, style, ident = up("item"), up("style"), up("identity")
    prompt = "图1的鞋换成图3的色调，保持图2的人物 —— 原话原样"
    r = c.post(f"/api/assets/{CLEAR}/gen-jobs", json={"base": base, "refs": [{"ref_id": style}, {"ref_id": ident}],
                                                     "prompt": prompt, "strength": "small", "gpu": 0})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["state"] == "done", job
    wf = fc.submitted[0]
    assert wf["20"]["inputs"]["prompt"] == prompt                     # 提示词原样
    assert "110" in wf and wf["110"]["inputs"]["image"].endswith(".png")   # 底图作 init_image
    roles = [x["role"] for x in job["params"]["images"]]
    assert roles == ["base", "identity", "style"]                      # 底图 → 人物 → 风格
    assert (root / job["file"]).is_file() and job["result"]["denoise"] == 0.35
    bad = c.post(f"/api/assets/{CLEAR}/gen-jobs", json={"refs": [{"ref_id": "ar-nope"}], "prompt": "x", "strength": "small"})
    assert bad.status_code == 422
    assert c.post(f"/api/assets/{CLEAR}/gen-jobs", json={"prompt": "x", "strength": "huge"}).status_code == 422
    # 存为资产新版本（默认资产库新增 <id>-vN）→ 原资产不动，返回新 asset_id，接着 refs/apply“只这一镜”
    _apply(c, S2, "shot", {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}})
    h = store.shot_looks(S2).look_hash
    r = c.post(f"/api/assets/{CLEAR}/versions", json={"job_id": job["job_id"], "label": "改色"})
    assert r.status_code == 200, r.text
    v = r.json()
    new_id = v["asset_id"]
    assert new_id == f"{CLEAR}-v2" and v["from_asset"] == CLEAR and v["affected_shots"] == []
    assert store.shot_looks(S2).look_hash == h
    it = next(i for i in store.wardrobe().items if i.id == new_id)
    assert it.slot == "shoes" and it.images[0].source == "generated" and it.reference_images == [it.images[0].file]
    r = _apply(c, S2, "shot", {"characters": {"lin_wan": {"parts": {"shoes": new_id}}}})
    assert r.status_code == 200 and _shoes(store, S2) == ([new_id], "shot")
    detail = c.get("/api/assets/characters/lin_wan").json()
    entry = next(x for x in detail["assets"] if x["asset_id"] == CLEAR)
    assert entry["versions"][0]["asset_id"] == new_id and len(entry["refs"]) == 3
    assert entry["id"] == CLEAR and entry["versions"][0]["n"] == 2 and entry["versions"][0]["url"]
    assert {r["role"] for r in entry["refs"]} == {"item", "style", "identity"} and entry["refs"][0]["ref_id"]
    # in_place：原资产加图片版本，用到它的镜头过期
    _apply(c, S3, "shot", {"characters": {"lin_wan": {"parts": {"shoes": CLEAR}}}})
    h3 = store.shot_looks(S3).look_hash
    r = c.post(f"/api/assets/{CLEAR}/versions", json={"gen_id": job["gen_id"], "label": "x", "in_place": True}).json()
    assert r["asset_id"] == CLEAR and S3 in r["affected_shots"] and store.shot_looks(S3).look_hash != h3
    r = c.post("/api/assets/lw-look-b/versions", json={"gen_id": job["gen_id"], "label": "x"})
    assert r.status_code == 404                                         # 生成记录属于另一个资产
    r = c.post("/api/assets/lw-look-b/versions", json={"file": job["file"], "label": "形象 B2"})
    assert r.status_code == 200 and r.json()["asset_id"] == "lw-look-b-v2"
    assert store.get_look("lw-look-b-v2").preview_image and store.get_look("lw-look-b").version == 1
    assert c.post("/api/assets/lin_wan/versions", json={"file": job["file"]}).status_code == 422
