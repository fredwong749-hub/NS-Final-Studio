"""ASSETUX（2026-10-31）人物资产页：一人一页、点选即生效、上传单品、删除走回收站。

项目方原话：“我要添加这个鞋子进去作为资产，我怎么做呀？”“很多事情只有一个确认按钮就可以，甚至不用确认按钮就行了，
就是我选这个图按一下就可以了”。全部在临时目录（临时项目根 / 衣橱 / 回收站），不碰生产数据。"""
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_agent import asset_refs as R
from ns_agent.looks import DEFAULT_SCRIPT_JSON, LookStore
from ns_api import character_hub as H
from ns_api import looks as LK
from ns_render import pipeline as P

pytestmark = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
PJ = "testproj"


def _png(color=(10, 10, 10)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (32, 48), color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path
    run = root / "data" / "pipeline" / "runs" / PJ
    sheets = run / "images" / "sheets" / "lin_wan"
    sheets.mkdir(parents=True)
    for lk in "ABC":
        for s in (101, 202):
            (sheets / f"lin_wan_look{lk}_s{s}.png").write_bytes(_png((s % 255, 20, 20)))
    face = root / "assets" / "characters" / "lin_wan" / "refs" / "face1.png"
    face.parent.mkdir(parents=True)
    face.write_bytes(_png())
    (sheets / "lin_wan_face_ref.png").write_bytes(_png((1, 2, 3)))
    (run / "P1_looks.json").write_text(json.dumps([{"name": "林晚", "char_id": "lin_wan", "marker": "", "looks": [
        {"id": "A", "use": "职场", "zh": "服装=米白衬衫｜鞋=透明12cm细高跟｜饰品=细银链"},
        {"id": "B", "use": "私域", "zh": "服装=黑色漆皮短裙｜鞋=12cm侧开透明细高跟｜饰品=九串铁珠"},
        {"id": "C", "use": "日常", "zh": "服装=雾蓝针织长裙｜鞋=白球鞋｜饰品=红绳手链"}]}], ensure_ascii=False), encoding="utf-8")
    (run / "assets").mkdir()
    (run / "assets" / "sheets_chosen.json").write_text(json.dumps({"sheet:lin_wan_lookA": {
        "file": f"data/pipeline/runs/{PJ}/images/sheets/lin_wan/lin_wan_lookA_s202.png", "char": "lin_wan", "seed": 202,
        "sim": {"lin_wan": 0.9}}}), encoding="utf-8")
    cfg = root / "config" / "recipes" / "asset_refs.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"projects": {PJ: {"run_dir": f"data/pipeline/runs/{PJ}", "looks_file": f"data/pipeline/runs/{PJ}/P1_looks.json",
                                                  "sheets_file": f"data/pipeline/runs/{PJ}/assets/sheets_chosen.json",
                                                  "faces": {"lin_wan": ["assets/characters/lin_wan/refs/face1.png"]},
                                                  "item_map": {}}}}), encoding="utf-8")
    # K-OPS-W20：当前剧读 config/pipeline/runs.json 的 primary（不再按目录修改时间猜）
    (root / "config" / "pipeline").mkdir(parents=True, exist_ok=True)
    (root / "config" / "pipeline" / "runs.json").write_text(json.dumps({"primary": PJ, "legacy_unprefixed_run": PJ, "runs": {PJ: {"priority": 0, "status": "producing"}}}), encoding="utf-8")
    looks_dir = root / "data" / "looks"
    looks_dir.mkdir(parents=True, exist_ok=True)
    (looks_dir / "wardrobe.json").write_text(json.dumps({"version": 2, "items": [], "decor_states": []}), encoding="utf-8")
    for n in ("looks", "schedule"):
        (looks_dir / f"{n}.json").write_text(json.dumps({"version": 2}), encoding="utf-8")
    store = LookStore(looks_dir)
    for k, v in {"ROOT": root, "CFG": cfg, "WARDROBE": looks_dir / "wardrobe.json",
                 "OVERRIDES": looks_dir / "item_map_overrides.json", "FACE_OVERRIDES": looks_dir / "face_overrides.json",
                 "HUB_LOOKS": looks_dir / "hub_extra_looks.json", "HUB_EP_LOOKS": looks_dir / "hub_episode_looks.json"}.items():
        monkeypatch.setattr(R, k, v, raising=False)
    monkeypatch.setattr(P, "DATA", root / "data")
    real_get_store = LK.get_store                              # 先记下原函数（路由的依赖键），再替换模块属性
    monkeypatch.setattr(LK, "get_store", lambda: store)        # 回收站内部取衣橱用
    from ns_api import auth as AU
    monkeypatch.setattr(AU, "REPO", root)
    app = FastAPI()
    app.include_router(H.router)
    from ns_api import trash as T
    app.include_router(T.router)
    app.dependency_overrides[real_get_store] = lambda: store
    assert H.get_store is real_get_store
    return {"c": TestClient(app), "root": root, "store": store, "looks_dir": looks_dir}


def test_list_and_detail(env):
    c = env["c"]
    r = c.get("/api/character-hub").json()
    assert r["project"] == PJ and [x["cid"] for x in r["characters"]] == ["lin_wan"]
    assert {x["id"] for x in r["categories"]} >= {"outfit", "shoes", "accessory", "nails", "bag"}
    d = c.get("/api/character-hub/lin_wan").json()
    assert d["face"]["file"] == "assets/characters/lin_wan/refs/face1.png"
    assert len(d["faces"]) == 2                              # 当前 + 设定图目录里的 *face*
    a = next(x for x in d["looks"] if x["look"] == "A")
    assert a["sheet"]["file"].endswith("lookA_s202.png") and len(a["candidates"]) == 2
    b = next(x for x in d["looks"] if x["look"] == "B")
    assert b["sheet"] is None and b["counts"]["missing"] == len(b["parts"]) >= 3   # 造型 B 没选设定图 → 每个部件都缺图（部件怎么拆归解析器）
    assert c.get("/api/character-hub/nobody").status_code == 404


def test_one_click_face_and_sheet_with_undo(env, monkeypatch):
    c = env["c"]
    monkeypatch.setattr(H, "face_crop_check", lambda p: (True, "测试夹具的纯色小图不做人脸检测"))   # 校验本身见下一条测试
    other = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_face_ref.png"
    r = c.post("/api/character-hub/lin_wan/face", json={"file": other}).json()   # 不要原话、不要 by
    assert r["prev"] == "assets/characters/lin_wan/refs/face1.png"
    assert R.face_of(PJ, "lin_wan") == other                  # 解析器立刻用上
    c.post("/api/character-hub/lin_wan/face", json={"file": r["prev"]})          # 撤销 = 用 prev 再点一次
    assert R.face_of(PJ, "lin_wan") == r["prev"]
    assert c.post("/api/character-hub/lin_wan/face", json={"file": "assets/x.png"}).status_code == 422

    f101 = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_lookB_s101.png"
    r = c.post("/api/character-hub/lin_wan/sheet", json={"look": "B", "file": f101}).json()
    assert r["prev"] is None and R.sheet_of(PJ, "lin_wan", "B") == f101
    fa = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_lookA_s101.png"
    r = c.post("/api/character-hub/lin_wan/sheet", json={"look": "A", "file": fa}).json()
    sc = json.loads((env["root"] / "data/pipeline/runs/testproj/assets/sheets_chosen.json").read_text(encoding="utf-8"))
    assert sc["sheet:lin_wan_lookA"]["seed"] == 101 and "sim" not in sc["sheet:lin_wan_lookA"] and sc["sheet:lin_wan_lookA"]["picked_by"]
    log = (env["looks_dir"] / "character_hub_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == 4 and json.loads(log[-1])["action"] == "sheet"     # 谁、何时、做了什么


def test_face_must_look_like_face_crop(env):
    """L-086（项目方 11-01 17:2x）：设为身份脸只接受脸部裁切；整张设定图 / 没有人脸的图 → 422（RSI 经总调度授权加）"""
    c = env["c"]
    other = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_face_ref.png"     # 纯色小图：没有人脸
    r = c.post("/api/character-hub/lin_wan/face", json={"file": other})
    assert r.status_code == 422 and "脸部裁切" in r.json()["detail"]
    real = Path(__file__).resolve().parents[1]
    sheet = real / "assets/characters/lin_wan/refs/lin_wan/ar-f9519334bc.png"
    if sheet.exists():
        assert not H.face_crop_check(sheet)[0]                                           # 整张 4 栏设定图（宽高比 1.77）
        assert H.face_crop_check(real / "data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png")[0]


def test_faces_carry_backend_crop_verdict(env):
    """总调度 11-01 r5：/api/character-hub/{cid} 的 faces 带 crop_ok / crop_why（同 set_face 的 face_crop_check），前端不再按宽高比猜"""
    d = env["c"].get("/api/character-hub/lin_wan").json()
    assert d["faces"] and all("crop_ok" in f and isinstance(f["crop_why"], str) for f in d["faces"])
    assert all(f["crop_ok"] is False for f in d["faces"])          # 夹具都是纯色小图：没有人脸
    assert d["face"] is None or "crop_ok" in d["face"]


def test_upload_shoe_map_and_trash_restore(env):
    c = env["c"]
    r = c.post("/api/character-hub/lin_wan/wardrobe",
               files={"file": ("shoe.png", _png((5, 5, 5)), "image/png")},
               data={"cat": "shoes", "name": "黑色漆皮细带高跟凉鞋", "looks": json.dumps([{"look": "B", "part": "12cm侧开透明细高跟"}])})
    assert r.status_code == 201, r.text
    it = r.json()["item"]
    iid = it["id"]
    assert it["slot"] == "shoes" and it["image"]["file"].startswith("assets/characters/lin_wan/wardrobe/")
    assert (env["root"] / it["image"]["file"]).is_file()
    # 解析器：造型 B 的鞋现在用这件单品图
    b = next(x for x in R.look_inventory(PJ, "lin_wan") if x["look"] == "B")
    shoe = next(p for p in b["parts"] if p["slot"] == "shoes")
    assert shoe["item_id"] == iid and shoe["status"] == "wardrobe"
    # 同一张图再传 → 409（不重复登记）
    r2 = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("s.png", _png((5, 5, 5)), "image/png")},
                data={"cat": "shoes", "name": "x"})
    assert r2.status_code == 409
    # 包 = 饰品槽 + 标签
    r3 = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("b.png", _png((9, 9, 9)), "image/png")},
                data={"cat": "bag", "name": "黑色手袋"})
    assert r3.json()["item"]["slot"] == "accessory" and r3.json()["item"]["slot_name"] == "包"
    # 不挂造型的上传也在人物页显示
    d = c.get("/api/character-hub/lin_wan").json()
    assert {x["id"] for x in d["items"]} >= {iid, r3.json()["item"]["id"]}
    # 改挂：解除 B 的鞋、挂到 C 的鞋
    c.post("/api/character-hub/lin_wan/map", json={"look": "B", "part": "12cm侧开透明细高跟", "item_id": None})
    c.post("/api/character-hub/lin_wan/map", json={"look": "C", "part": "白球鞋", "item_id": iid})
    d = c.get("/api/character-hub/lin_wan").json()
    assert next(x for x in d["items"] if x["id"] == iid)["looks"] == [{"look": "C", "part": "白球鞋"}]
    # 删除 → 回收站（映射一起解除）；撤销 → 回来、映射也回来
    t = c.post(f"/api/character-hub/lin_wan/items/{iid}/trash").json()
    assert t["entry_id"] and t["maps"] == [{"look": "C", "part": "白球鞋", "prev": iid}]
    assert iid not in {x["id"] for x in c.get("/api/character-hub/lin_wan").json()["items"]}
    c.post(f"/api/character-hub/lin_wan/items/{iid}/restore", json={"entry_id": t["entry_id"], "maps": t["maps"]})
    d = c.get("/api/character-hub/lin_wan").json()
    assert next(x for x in d["items"] if x["id"] == iid)["looks"] == [{"look": "C", "part": "白球鞋"}]
    # 改名
    assert c.post(f"/api/character-hub/lin_wan/items/{iid}/rename", json={"name": "凉鞋"}).json()["prev"] == "黑色漆皮细带高跟凉鞋"


def test_body_jewelry_category_note_and_second_image(env):
    c = env["c"]
    r = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("a.png", _png((1, 50, 1)), "image/png")},
               data={"cat": "body", "name": "横杆铃铛链环", "note": "项目方说明：部位类别 X"}).json()
    it = r["item"]
    assert it["slot"] == "accessory" and it["slot_name"] == "身体饰品·穿环" and it["cat"] == "body"
    assert it["note"] == "项目方说明：部位类别 X"
    r2 = c.post(f"/api/character-hub/lin_wan/items/{it['id']}/images", files={"file": ("b.png", _png((1, 60, 1)), "image/png")})
    assert r2.status_code == 201 and r2.json()["version"] == 2
    d = c.get("/api/character-hub/lin_wan").json()
    x = next(i for i in d["items"] if i["id"] == it["id"])
    assert x["images"] == 2 and len(x["gallery"]) == 2 and x["image"]["file"].endswith("_v1.png")   # 主参考图仍是第一张
    assert c.post(f"/api/character-hub/lin_wan/items/{it['id']}/images", files={"file": ("b.png", _png((1, 60, 1)), "image/png")}).status_code == 409
    chain = json.loads((env["root"] / "data" / "assets" / "asset_versions.json").read_text(encoding="utf-8"))[it["id"]]
    assert [v["version"] for v in chain] == [1, 2]


def test_duplicate_image_is_not_an_error_use_existing_or_force(env, monkeypatch):
    """项目方 11-01 截图：选了一张旧剧登记过的图，只看到红字“这张图已经是单品…了”。现在：先查 → 给出那件单品 → 一键用这件。"""
    c, st, root = env["c"], env["store"], env["root"]
    from ns_schema.looks import WardrobeItem
    old = root / "assets" / "characters" / "lin_wan" / "items" / "outfit" / "O12_flatlay_dark_s0.png"
    old.parent.mkdir(parents=True)
    data = _png((77, 7, 7))
    old.write_bytes(data)

    def fn():
        w = st.wardrobe()
        w.items.append(WardrobeItem(id="lw-outfit-lw-o12", slot="outfit", name="黑色漆皮细带捆绑内衣（平铺，深色背景）", character="lin_wan",
                                    reference_images=["assets/characters/lin_wan/items/outfit/O12_flatlay_dark_s0.png"], source="reference"))
        st._write("wardrobe", w)
    st._mutate(fn)
    calls = []
    monkeypatch.setattr(H, "_name_from_model", lambda d, cat: calls.append(cat) or {"name": "黑色漆皮绑带内衣", "cat": "outfit", "model": "mock"})
    # 旧单品不在当前衣橱（折叠在“以前登记”里）
    assert "lw-outfit-lw-o12" not in {x["id"] for x in c.get("/api/character-hub/lin_wan").json()["items"]}
    r = c.post("/api/character-hub/lin_wan/check-image", files={"file": ("O12_flatlay_dark_s0.png", data, "image/png")}).json()
    assert r["dup"]["id"] == "lw-outfit-lw-o12" and r["dup_in_current"] is False
    assert r["suggested"] == {"name": "黑色漆皮细带捆绑内衣（平铺，深色背景）", "source": "existing"} and calls == []   # 用已有名字，不调模型、不用文件名
    # 一键：用这件，挂到造型 B → 移进当前衣橱 + 挂上
    a = c.post("/api/character-hub/lin_wan/items/lw-outfit-lw-o12/adopt", json={"looks": [{"look": "B", "part": "黑色漆皮短裙"}]}).json()
    assert a["mapped"][0]["look"] == "B"
    cur = {x["id"]: x for x in c.get("/api/character-hub/lin_wan").json()["items"]}
    assert cur["lw-outfit-lw-o12"]["looks"] == [{"look": "B", "part": "黑色漆皮短裙"}]
    # 撤销“放进当前衣橱”+ 映射还原后，只剩被挂过的那条映射会让它留在当前衣橱；都撤掉就回到折叠区
    c.post("/api/character-hub/lin_wan/map", json={"look": "B", "part": "黑色漆皮短裙", "item_id": a["mapped"][0]["prev"]})
    c.post("/api/character-hub/lin_wan/items/lw-outfit-lw-o12/adopt", json={"remove": True})
    assert "lw-outfit-lw-o12" not in {x["id"] for x in c.get("/api/character-hub/lin_wan").json()["items"]}
    # 直接调上传仍然 409（带 dup 和 item_id），force=true 才另起一件
    r2 = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("x.png", data, "image/png")}, data={"cat": "outfit", "name": "新的"})
    assert r2.status_code == 409 and r2.json()["detail"]["item_id"] == "lw-outfit-lw-o12"
    r3 = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("x.png", data, "image/png")}, data={"cat": "outfit", "name": "黑色漆皮绑带内衣（另一件）", "force": "true"})
    assert r3.status_code == 201
    # 新图：看图起名（模型 mock）
    r4 = c.post("/api/character-hub/lin_wan/check-image", files={"file": ("Screenshot 1.png", _png((3, 99, 3)), "image/png")}, data={"cat": "outfit"}).json()
    assert r4["dup"] is None and r4["suggested"]["name"] == "黑色漆皮绑带内衣" and r4["suggested"]["source"] == "model" and calls == ["outfit"]
    # 模型挂了：不报错，名字留空让人写
    monkeypatch.setattr(H, "_name_from_model", lambda d, cat: (_ for _ in ()).throw(RuntimeError("timeout")))
    r5 = c.post("/api/character-hub/lin_wan/check-image", files={"file": ("a.png", _png((4, 4, 99)), "image/png")}).json()
    assert r5["suggested"]["name"] == "" and r5["suggested"]["source"] == "none"


def test_upload_rejects_bad_input(env):
    c = env["c"]
    assert c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("a.txt", b"x", "text/plain")},
                  data={"cat": "shoes", "name": "a"}).status_code == 422
    assert c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("a.png", _png(), "image/png")},
                  data={"cat": "hat", "name": "a"}).status_code == 422
    assert c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("a.png", _png(), "image/png")},
                  data={"cat": "shoes", "name": " "}).status_code == 422


def test_wired_into_app():
    from ns_api import app as app_mod
    paths = set(app_mod.app.openapi()["paths"])
    assert "/api/character-hub/{cid}/wardrobe" in paths and "/api/character-hub" in paths


def test_part_matcher_node():
    """前端“单品挂造型替换哪一项”的判定（apps/web/src/v3/assets/hub_match.ts）：用 node --test 跑（11-01 审计日志复现）"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node")
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([node, "--test", "apps/web/e2e/assetux/hub_match.test.mjs"], cwd=root, capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def test_scene_space_ref_shows_on_card_and_one_click_pick(tmp_path, monkeypatch):
    """数据对不上（11-01 项目方截图：6 个场景都写“没有底图”）：IMGGEN 把暂定底图登记成 role=space 参考，
    场景卡只读定稿底图。登记了 space ref 的场景，卡片必须显示图；候选点一下设为当前（画布定稿，不冒充项目方确认）。"""
    from ns_api import asset_edit as AE
    from ns_api import assets as A
    from ns_api import scene_assets as SA
    monkeypatch.setattr(A, "ROOT", tmp_path)
    monkeypatch.setattr(A, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(A, "_ASSETS_RESOLVED", {})
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(SA, "scene_exists", lambda *a, **k: True)
    monkeypatch.setattr(SA, "_stale_shots", lambda *a, **k: [])
    monkeypatch.setattr(SA, "_rebuild", lambda: None)
    sid = "sk_test"
    ref = tmp_path / "assets" / "scenes" / sid / "refs" / "ar-1.png"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(_png((10, 20, 30)))
    run = tmp_path / "data" / "pipeline" / "runs" / "r1" / "images" / "scenes" / sid
    run.mkdir(parents=True)
    (run / "plate_s701_post.png").write_bytes(_png((10, 20, 30)))     # 同一张（已登记）→ 去重
    (run / "plate_s702_post.png").write_bytes(_png((40, 50, 60)))     # 第二张候选
    (tmp_path / "data" / "assets").mkdir(parents=True)
    AE._write("asset_refs", {sid: [{"ref_id": "ar-1", "asset_id": sid, "file": f"assets/scenes/{sid}/refs/ar-1.png", "role": "space"}]})
    pv = SA.plate_view(sid)
    assert pv["url"] and pv["provisional"] is True and pv["plate_status"] == "candidate" and pv["gate_status"] == "missing"
    cands = SA.plate_candidates(sid)
    assert len(cands) == 2 and cands[0]["source"] == "ref"
    out = SA.pick_plate(sid, SA.PlatePickBody(file=cands[1]["file"]), store=None)
    assert out["prev_version"] is None
    pv2 = SA.plate_view(sid)
    assert pv2["provisional"] is False and pv2["locked_by"] == "canvas" and pv2["url"]
    assert pv2["gate_status"] == "candidate"                     # 画布定稿 ≠ 项目方确认（S2 闸门不变）
    import pytest as _pt
    with _pt.raises(Exception):
        SA.pick_plate(sid, SA.PlatePickBody(file="assets/other.png"), store=None)


def test_new_look_sheet_upload_and_schedule(env):
    """UIAUDIT 回退清单：P0-3“＋ 新造型”、P1-13“排期：角色 × 集”可编辑（点一下生效，返回 prev 可撤销）"""
    c, root = env["c"], env["root"]
    r = c.post("/api/character-hub/lin_wan/looks", json={"use": "酒会", "outfit": "黑色缎面长裙", "shoes": "银色细高跟"}).json()
    assert r["look"] == "D"
    d = c.get("/api/character-hub/lin_wan").json()
    lk = next(x for x in d["looks"] if x["look"] == "D")
    assert lk["custom"] and not lk["pending_resolver"] and {p["label"] for p in lk["parts"]} >= {"黑色缎面长裙", "银色细高跟"}
    assert all(p["status"] == "missing" for p in lk["parts"])                      # 没设定图 = 缺图（解析器已合入新造型）
    up = c.post("/api/character-hub/lin_wan/looks/D/sheet", files={"file": ("s.png", _png((9, 9, 200)), "image/png")})
    assert up.status_code == 201, up.text
    assert R.sheet_of(PJ, "lin_wan", "D") == up.json()["uploaded"]                 # 写进 sheets_chosen，解析器读得到
    lk = next(x for x in c.get("/api/character-hub/lin_wan").json()["looks"] if x["look"] == "D")
    assert lk["sheet"]["file"] == up.json()["uploaded"] and lk["candidates"][0]["current"]
    # 挂单品到新造型
    it = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("x.png", _png((1, 2, 250)), "image/png")}, data={"cat": "outfit", "name": "缎面长裙"}).json()["item"]
    assert c.post("/api/character-hub/lin_wan/map", json={"look": "D", "part": "黑色缎面长裙", "item_id": it["id"]}).status_code == 200
    # 排期：第 3 集整集用 D，撤销 = prev
    s1 = c.post("/api/character-hub/lin_wan/schedule", json={"ep": 3, "look": "D"}).json()
    assert s1["prev"] is None
    sch = {x["ep"]: x for x in c.get("/api/character-hub/lin_wan").json()["schedule"]}
    assert sch[3]["override"] == "D"
    c.post("/api/character-hub/lin_wan/schedule", json={"ep": 3, "look": s1["prev"]})
    assert 3 not in {x["ep"] for x in c.get("/api/character-hub/lin_wan").json()["schedule"]}
    assert c.post("/api/character-hub/lin_wan/schedule", json={"ep": 3, "look": "Z"}).status_code == 422
    # 撤销新造型：只认人物页新建的
    assert c.post("/api/character-hub/lin_wan/looks/A/remove").status_code == 404
    assert c.post("/api/character-hub/lin_wan/looks/D/remove").status_code == 200
    assert "D" not in {x["look"] for x in c.get("/api/character-hub/lin_wan").json()["looks"]}


def test_reject_marks_and_undo(env):
    """UM-P0-02：“✗ 不要”只记账（不删文件、不动当前），人物页带出 rejected；撤销 = undo"""
    c = env["c"]
    f = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_lookA_s101.png"
    assert c.post("/api/asset-rejects", json={"kind": "sheet", "file": f, "reasons": ["衣服不对"], "note": "领口太低", "cid": "lin_wan"}).status_code == 200
    d = c.get("/api/character-hub/lin_wan").json()
    assert d["rejected"][f]["reasons"] == ["衣服不对"]
    assert (env["root"] / f).is_file()                                            # 不删文件
    c.post("/api/asset-rejects", json={"kind": "sheet", "file": f, "cid": "lin_wan", "undo": True})
    assert f not in c.get("/api/character-hub/lin_wan").json()["rejected"]
    assert c.post("/api/asset-rejects", json={"kind": "sheet", "file": "../x.png"}).status_code == 422


def test_item_image_candidates_primary_and_undo(env):
    """单品附图 ✓ 用这张：挪到主图（images[0]，解析器取它）；撤销 = 用 prev 再设一次"""
    c = env["c"]
    it = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("a.png", _png((5, 60, 5)), "image/png")}, data={"cat": "shoes", "name": "测试鞋"}).json()["item"]
    c.post(f"/api/character-hub/lin_wan/items/{it['id']}/images", files={"file": ("b.png", _png((5, 61, 5)), "image/png")})
    g = next(x for x in c.get("/api/character-hub/lin_wan").json()["items"] if x["id"] == it["id"])["gallery"]
    second = g[1]["file"]
    r = c.post(f"/api/character-hub/lin_wan/items/{it['id']}/primary", json={"file": second}).json()
    assert r["prev"] == g[0]["file"]
    x = next(x for x in c.get("/api/character-hub/lin_wan").json()["items"] if x["id"] == it["id"])
    assert x["image"]["file"] == second and x["gallery"][0]["file"] == second
    c.post(f"/api/character-hub/lin_wan/items/{it['id']}/primary", json={"file": r["prev"]})
    x = next(x for x in c.get("/api/character-hub/lin_wan").json()["items"] if x["id"] == it["id"])
    assert x["image"]["file"] == g[0]["file"]
    assert c.post(f"/api/character-hub/lin_wan/items/{it['id']}/primary", json={"file": "assets/x.png"}).status_code == 422


def test_asset_quarantine_list(env):
    """RECALL 隔离区：资产中心读 /api/asset-quarantine 的名字集合，任何视图都不列这些（旧场景、外国演员、证伪 LoRA）"""
    root = env["root"]
    q = root / "data" / "_quarantine_20261101"
    q.mkdir(parents=True)
    (q / "moves.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"src": "D:\\NS-Final Studio\\assets\\scenes\\sk_office", "status": "moved"},
        {"src": "/root/x/loras/lin_wan_qi_v1.safetensors", "status": "moved"},
        {"src": "D:\\NS-Final Studio\\data\\assets\\snapshots\\voice\\alex"},
        {"src": "assets/scenes/sk_keep", "status": "planned"},
    ]), encoding="utf-8")
    d = env["c"].get("/api/asset-quarantine").json()
    assert {"sk_office", "lin_wan_qi_v1", "lin_wan_qi_v1.safetensors", "alex"} <= set(d["names"])
    assert "sk_keep" not in d["names"]                       # 只计划、没移动的不算


def test_regen_submits_asset_gen_and_results_become_candidates(env, monkeypatch):
    """↻ 再生成（项目方 11-01）：当前图作底图 + 装备图作“取这一件”参考 + 提示词 → asset gen-jobs；
    出好的图按 label 回到对应位置当候选，点“✓ 用这张”才生效（不自动替换）"""
    from ns_api import asset_edit as AE
    c, root = env["c"], env["root"]
    sent = []
    monkeypatch.setattr(AE, "create_gen_job", lambda aid, body, store=None: sent.append((aid, body)) or {"job_id": "j1"})
    from ns_api import prompt_rewrite as PR   # L-119：项目方原话先经外部写作 API 改写；测试里替身，不发网络
    seen = []
    monkeypatch.setattr(PR, "rewrite", lambda kind, text, ctx=None, chat=None: seen.append((kind, text, ctx)) or
                        {"prompt": "Keep the same face; change shoes to silver stilettos.", "negative_add": "plastic skin",
                         "zh_summary": "鞋换银色细高跟", "model": "fake", "usd": 0.0, "owner_text": text})
    gear = c.post("/api/character-hub/lin_wan/wardrobe", files={"file": ("g.png", _png((7, 7, 77)), "image/png")}, data={"cat": "shoes", "name": "银色细高跟"}).json()["item"]
    sheet = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_lookA_s202.png"
    r = c.post("/api/character-hub/lin_wan/regen", json={"kind": "sheet", "look": "A", "file": sheet, "prompt": "鞋换成银色细高跟",
                                                         "gear": [{"path": gear["image"]["file"], "label": "鞋", "item_id": gear["id"]}]})
    assert r.status_code == 202, r.text
    aid, body = sent[0]
    assert aid == "lin_wan" and body.base == sheet and body.label == "再生成·sheet:A" and len(body.refs) == 1
    assert body.prompt.startswith("Keep the same face") and body.negative == "plastic skin"      # 出图用改写后的提示词
    assert seen[0][1] == "鞋换成银色细高跟" and seen[0][2]["gear"] == ["鞋"] and r.json()["rewrite"]["zh_summary"]
    assert c.post("/api/character-hub/lin_wan/regen", json={"kind": "sheet", "file": sheet, "prompt": "x"}).status_code == 422   # 没说造型
    # 不写 = 换种子：这个位置还没再生成过 → 422；有过 → 用上一次的提示词
    assert c.post("/api/character-hub/lin_wan/regen", json={"kind": "sheet", "look": "A", "file": sheet, "prompt": " "}).status_code == 422
    AE._write("asset_gens", {"lin_wan": [{"gen_id": "ag-0", "asset_id": "lin_wan", "label": "再生成·sheet:A", "prompt": "PREV PROMPT"}]})
    r2 = c.post("/api/character-hub/lin_wan/regen", json={"kind": "sheet", "look": "A", "file": sheet, "prompt": ""})
    assert r2.status_code == 202 and r2.json()["reseed"] and sent[-1][1].prompt == "PREV PROMPT" and len(seen) == 1
    # 改写失败 → 502，不出图
    monkeypatch.setattr(PR, "rewrite", lambda *a, **k: (_ for _ in ()).throw(PR.RewriteError("网关挂了")))
    n = len(sent)
    r3 = c.post("/api/character-hub/lin_wan/regen", json={"kind": "sheet", "look": "A", "file": sheet, "prompt": "再瘦一点"})
    assert r3.status_code == 502 and "没有出图" in r3.json()["detail"] and len(sent) == n
    # 模拟生成完成：写一条生成记录 → 造型 A 的候选里出现，点“用这张”= 设定图
    out = root / "assets" / "characters" / "lin_wan" / "refs" / "gen" / "ag-1.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_png((200, 1, 1)))
    rel = "assets/characters/lin_wan/refs/gen/ag-1.png"
    AE._write("asset_gens", {"lin_wan": [{"gen_id": "ag-1", "asset_id": "lin_wan", "file": rel, "label": "再生成·sheet:A"}]})
    a = next(x for x in c.get("/api/character-hub/lin_wan").json()["looks"] if x["look"] == "A")
    assert a["candidates"][0]["file"] == rel and not a["candidates"][0]["current"]          # 只是候选，不自动替换
    assert c.post("/api/character-hub/lin_wan/sheet", json={"look": "A", "file": rel}).status_code == 200
    assert R.sheet_of(PJ, "lin_wan", "A") == rel
    # 单品再生成：候选 → use-regen 加进单品并设主图
    AE._write("asset_gens", {gear["id"]: [{"gen_id": "ag-2", "asset_id": gear["id"], "file": rel, "label": "再生成·item"}]})
    x = next(i for i in c.get("/api/character-hub/lin_wan").json()["items"] if i["id"] == gear["id"])
    assert x["regen"][0]["file"] == rel
    u = c.post(f"/api/character-hub/lin_wan/items/{gear['id']}/use-regen", json={"file": rel}).json()
    assert u["prev"] == gear["image"]["file"]
    x = next(i for i in c.get("/api/character-hub/lin_wan").json()["items"] if i["id"] == gear["id"])
    assert x["image"]["file"] == u["file"] and x["image"]["file"] != gear["image"]["file"]
    # 撤销“用这张”：加进去的那张拿掉，主图回到原来的，单品回到原样（图数、版本号）
    c.post(f"/api/character-hub/lin_wan/items/{gear['id']}/unuse-regen", json={"file": u["file"], "prev": u["prev"]})
    x = next(i for i in c.get("/api/character-hub/lin_wan").json()["items"] if i["id"] == gear["id"])
    assert x["image"]["file"] == gear["image"]["file"] and x["images"] == 1 and x["version"] == 1
