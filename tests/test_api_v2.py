"""画布 v2 后端：资产清单 / manifest 导入 / 单品上传 / 参考图组 / 批量人物信息 / 本集导演加强 / 加强建议 /
卡片结构化字段。全部用临时目录（资产、衣橱、renders），不碰 data/ 和 assets/；不调用 /render。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_agent.looks import DEFAULT_SCRIPT_JSON, LookStore
from ns_api import app as app_mod
from ns_api import assets as A
from ns_api import shotinfo as SI
from ns_api.looks import get_store
from ns_render import pipeline as P
from ns_schema.script import ScriptImport

pytestmark = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture(scope="module")
def script() -> ScriptImport:
    return ScriptImport.model_validate_json(Path(DEFAULT_SCRIPT_JSON).read_text(encoding="utf-8"))


@pytest.fixture()
def env(tmp_path, script, monkeypatch):
    """临时项目根：assets/characters/lin_wan 下放 1 张 manifest 妆容图 + 1 张 loose 正面 plate"""
    root = tmp_path / "proj"
    base = root / "assets" / "characters" / "lin_wan"
    (base / "items" / "makeup").mkdir(parents=True)
    (base / "plates").mkdir(parents=True)
    (base / "items" / "makeup" / "M1_s0.png").write_bytes(PNG)
    (base / "items" / "makeup" / "M9_s0.png").write_bytes(PNG + b"x")
    (base / "plates" / "front.png").write_bytes(PNG + b"front")
    (base / "items" / "makeup" / "manifest.json").write_text(json.dumps([
        {"file": "M1_s0.png", "kind": "item/makeup", "design": "M1", "name": "素颜通勤（REF-LW-01）", "seed": 1,
         "sha256": A.sha256_file(base / "items" / "makeup" / "M1_s0.png")},
        {"file": "M9_s0.png", "kind": "item/makeup", "design": "M9", "name": "测试妆"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", root)
    monkeypatch.setattr(A, "ASSETS_DIR", root / "assets")
    store = LookStore(tmp_path / "looks")
    store._script = script
    app_mod.app.dependency_overrides[get_store] = lambda: store
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(app_mod, "BOOST_LLM_CONFIG", tmp_path / "config" / "director_boost_llm.json")
    yield TestClient(app_mod.app), store, root
    app_mod.app.dependency_overrides.clear()


def test_asset_listing(env):
    c, _, _ = env
    r = c.get("/api/assets/characters")
    assert r.status_code == 200
    lw = next(x for x in r.json()["characters"] if x["id"] == "lin_wan")
    assert lw["plates"]["front"]["source"] == "loose"
    assert lw["face_url"].startswith("/api/assets/file?path=assets/characters/lin_wan/plates/front.png")
    assert [e["design"] for e in lw["items"]["makeup"]] == ["M1", "M9"]
    assert lw["items"]["nails"] == []                       # 空类别也要有键（前端显示空状态 + 动作）
    assert "plate/3q" in lw["missing"] and lw["unregistered"] == 2
    gu = next(x for x in r.json()["characters"] if x["id"] == "gu_chen")
    assert gu["dir_exists"] is False and gu["face_url"] is None


def test_asset_file_is_confined(env):
    c, _, _ = env
    assert c.get("/api/assets/file", params={"path": "assets/characters/lin_wan/plates/front.png"}).status_code == 200
    assert c.get("/api/assets/file", params={"path": "../etc/passwd"}).status_code == 404
    assert c.get("/api/assets/file", params={"path": "pyproject.toml"}).status_code == 404


def test_import_attaches_ref_and_dedupes(env):
    c, store, _ = env
    r = c.post("/api/assets/characters/林晚/import").json()
    assert [a["item_id"] for a in r["attached"]] == ["lw-makeup-bare"]          # REF-LW-01 → 已有单品
    assert [x["item_id"] for x in r["created"]] == ["lw-makeup-m9"]
    items = {i.id: i for i in store.wardrobe().items}
    bare = items["lw-makeup-bare"]
    assert bare.images[0].file == "assets/characters/lin_wan/items/makeup/M1_s0.png"
    assert bare.reference_images[0] == bare.images[0].file and "REF-LW-01" in bare.reference_images
    assert items["lw-makeup-m9"].character == "lin_wan" and items["lw-makeup-m9"].slot == "makeup"
    again = c.post("/api/assets/characters/lin_wan/import").json()
    assert not again["created"] and not again["attached"] and len(again["skipped"]) == 2


def test_upload_item_image_versions(env):
    c, store, root = env
    r = c.post("/api/looks/wardrobe/items/lw-hair/images", files={"file": ("n.png", PNG, "image/png")},
               data={"variant": "clean"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image"]["version"] == 1 and body["rendering_triggered"] is False
    assert body["affected_count"] > 0                       # 发型在默认造型里：参考图变了 → 镜头受影响
    r2 = c.post("/api/looks/wardrobe/items/lw-hair/images", files={"file": ("n.png", PNG + b"2", "image/png")},
                data={"variant": "worn"}).json()
    assert r2["image"]["version"] == 2
    it = next(i for i in store.wardrobe().items if i.id == "lw-hair")
    assert [im.version for im in it.images] == [1, 2] and it.version == 2
    assert it.reference_images[0] == it.images[1].file
    assert (root / it.images[0].file).is_file()
    assert c.post("/api/looks/wardrobe/items/lw-hair/images", files={"file": ("n.png", PNG, "image/png")},
                  data={"variant": "nope"}).status_code == 422
    assert c.post("/api/looks/wardrobe/items/nope/images", files={"file": ("n.png", PNG, "image/png")}).status_code == 404
    assert c.put("/api/looks/wardrobe/items/lw-hair/tags", json={"tags": ["5cm", " 透明 ", ""]}).json()["tags"] \
        == ["5cm", "透明"]


def test_shot_refs_and_batch_looks(env):
    c, _, _ = env
    c.post("/api/looks/wardrobe/items/lw-hair/images", files={"file": ("n.png", PNG + b"n", "image/png")})
    r = c.get("/api/looks/shots/ep01-S3/refs").json()
    roles = [x["role"] for x in r["refs"]]
    assert roles[0] == "face" and "hair" in roles
    assert r["refs"][0]["index"] == 1 and r["count"] == len(r["files"]) <= A.QWEN_MAX_REFS
    assert r["anchor_lines"][0].startswith("@图1")
    shots = c.get("/api/looks/shots", params={"episode": 1}).json()
    assert [s["shot_id"] for s in shots][:2] == ["ep01-S1", "ep01-S2"]
    lw = next(ch for ch in shots[0]["characters"] if ch["character"] == "lin_wan")
    assert lw["face_url"] and [s["slot"] for s in lw["slots"]] == ["outfit", "shoes", "nails", "hair", "makeup", "accessory"]
    assert c.get("/api/looks/shots", params={"episode": 99}).status_code == 404


def test_refs_truncate_over_limit(env):
    _, store, _ = env
    idx = A.AssetIndex(store)
    r = A.shot_refs(store, "ep01-S3", idx, limit=0)
    assert all(x["truncated"] for x in r["refs"] if not x["text_only"] and not x["duplicate"]) and r["count"] == 0


def test_episode_edit_roundtrip(env):
    c, _, _ = env
    assert c.get("/api/episodes/1/edit").json()["boost_first"] is None
    r = c.put("/api/episodes/1/edit", json={"boost_first": "  甲  ", "boost_last": ""}).json()
    assert r["boost_first"] == "甲" and r["boost_last"] is None and r["updated_at"]
    assert c.get("/api/episodes/1/edit").json()["boost_first"] == "甲"
    assert c.put("/api/episodes/99/edit", json={}).status_code == 404


class _FakeLLM:
    """本机假 OpenAI 兼容服务：记录请求，返回固定建议"""

    def __enter__(self):
        import http.server
        import threading
        seen = self.seen = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.update(path=self.path, auth=self.headers.get("Authorization"), body=body)
                out = json.dumps({"choices": [{"message": {"content": " 建议 "}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/v1"
        return self

    def __exit__(self, *a):
        self.srv.shutdown()


def test_boost_suggest_requires_owner_config(env, tmp_path, monkeypatch):
    c, _, _ = env
    monkeypatch.delenv("NS_BOOST_API_KEY", raising=False)
    r = c.post("/api/shots/ep01-S1/boost/suggest", json={"which": "first"})
    assert r.status_code == 400 and "director_boost_llm" in r.json()["detail"]
    cfg = tmp_path / "config" / "director_boost_llm.json"
    cfg.parent.mkdir(parents=True)
    rules = tmp_path / "rules.md"
    with _FakeLLM() as llm:
        cfg.write_text(json.dumps({"base_url": "", "model": "m", "instruction_file": str(rules)}), encoding="utf-8")
        # .local.json 覆盖同名键（base_url、密钥）
        (tmp_path / "config" / "director_boost_llm.local.json").write_text(
            json.dumps({"base_url": llm.url, "api_key": "sk-SECRET"}), encoding="utf-8")
        r = c.post("/api/shots/ep01-S1/boost/suggest", json={"which": "first"})
        assert r.status_code == 400 and "规则" in r.json()["detail"]          # 规则文件不存在
        rules.write_text("<!-- 项目方在这里写规则 -->\n\n", encoding="utf-8")
        r = c.post("/api/shots/ep01-S1/boost/suggest", json={"which": "first"})
        assert r.status_code == 400                                           # 只有注释 = 没写
        st = c.get("/api/boost/config").json()
        assert st["api_key"] == "已配置" and st["rules_ready"] is False and "SECRET" not in json.dumps(st)
        rules.write_text("<!-- c -->OWNER", encoding="utf-8")
        r = c.post("/api/shots/ep01-S1/boost/suggest", json={"which": "last"})
        assert r.status_code == 200 and r.json()["suggestion"] == "建议" and "SECRET" not in r.text
        assert llm.seen["auth"] == "Bearer sk-SECRET" and llm.seen["path"] == "/v1/chat/completions"
        msgs = llm.seen["body"]["messages"]
        assert msgs[0] == {"role": "system", "content": "OWNER"} and "ep01-S1" in msgs[1]["content"]
        assert c.get("/api/boost/config").json()["ready"] is True
    assert c.post("/api/shots/ep01-S1/boost/suggest", json={"which": "x"}).status_code == 422
    # 环境变量也可以给密钥
    (tmp_path / "config" / "director_boost_llm.local.json").unlink()
    monkeypatch.setenv("NS_BOOST_API_KEY", "sk-ENV")
    assert c.get("/api/boost/config").json()["api_key"] == "已配置"


def test_generate_validation():
    store = LookStore()
    req = A.GenerateRequest(target="item/heels", prompt="p", references=["assets/characters/lin_wan/lin_wan.png"])
    if (A.ROOT / req.references[0]).exists():
        assert A.validate_generate("lin_wan", req, store).references == ["assets/characters/lin_wan/lin_wan.png"]
    with pytest.raises(Exception) as e:
        A.validate_generate("lin_wan", A.GenerateRequest(target="item/heels", prompt="p", model="klein"), store)
    assert getattr(e.value, "status_code", None) == 501
    with pytest.raises(Exception) as e:
        A.validate_generate("lin_wan", A.GenerateRequest(target="plate/top", prompt="p"), store)
    assert getattr(e.value, "status_code", None) == 422


def test_multi_ref_workflow():
    from ns_render import workflows as W
    wf = A.multi_ref_workflow(W, "p", "n", ["a.png", "b.png", "c.png"], 64, 64, 1, "x")
    enc = wf["20"]["inputs"]
    assert enc["images.image_1"] and enc["images.image_2"] == ["202", 0] and enc["images.image_3"] == ["203", 0]
    assert wf["203"]["inputs"]["image"] == "c.png"
    assert "images.image_1" not in A.multi_ref_workflow(W, "p", "n", [], 64, 64, 1, "x")["20"]["inputs"]


def test_shotinfo_extraction():
    cam = SI.camera_info(None, "hh12clear，极近特写，低机位仰拍，林晚", "lnwan01，camera push in 缓慢推近，她咬唇")
    assert (cam["size"], cam["angle"], cam["source"]) == ("极近特写", "低机位仰拍", "auto")
    assert cam["move"].startswith("camera push in")
    ed = SI.camera_info("近景，camera pull back 拉远，85mm", "极近特写", "static camera")
    assert (ed["size"], ed["lens"], ed["sources"]["size"], ed["source"]) == ("近景", "85mm", "edit", "edit")
    ex = SI.expression_info(None, "林晚", "lnwan01，static camera，她睫毛颤动，嘴唇抿了抿，走向门口")
    assert ex["source"] == "auto" and ex["cues"] == ["她睫毛颤动", "嘴唇抿了抿"]
    assert SI.expression_info("咬唇", "", "")["source"] == "edit"
    assert SI.expression_info(None, "空镜", "static camera，门开")["source"] == "none"
    assert SI.script_text("收尾镜", "lnwan01，camera push in 缓推，她挂好外套") == "【收尾镜】她挂好外套"


def test_summary_card_fields(env):
    c, _, _ = env
    s = c.get("/api/episodes").json()[0]["shots"][0]
    for k in ("image_prompt", "video_prompt", "last_prompt", "script_text", "camera", "expression", "takes_count",
              "characters", "last_frame_source", "last_frame_target", "last_frame_actual", "stale", "stale_global",
              "boost", "has_boost", "last_supported"):
        assert k in s, k
    assert set(s["camera"]) >= {"size", "angle", "move", "lens", "source"}
    assert set(s["takes_count"]) == {"image", "last", "video"}


def test_master_plate_is_hero_and_face_fallback(env):
    c, _, root = env
    base = root / "assets" / "characters" / "lin_wan" / "plates"
    (base / "master.png").write_bytes(PNG + b"master")
    lw = next(x for x in c.get("/api/assets/characters").json()["characters"] if x["id"] == "lin_wan")
    assert lw["master"]["file"].endswith("plates/master.png")
    assert lw["hero"]["file"].endswith("plates/master.png")          # 写实母版优先当大图
    assert lw["plates"]["front"]["file"].endswith("plates/front.png")  # 正面 plate 仍是脸图
    assert "plates/front.png" in lw["face_url"]
    (base / "front.png").unlink()
    lw = next(x for x in c.get("/api/assets/characters").json()["characters"] if x["id"] == "lin_wan")
    assert "plates/master.png" in lw["face_url"]                     # 没有正面 plate → 母版兜底


def test_import_same_design_becomes_new_version(env):
    c, store, root = env
    mk = root / "assets" / "characters" / "lin_wan" / "items" / "makeup"
    (mk / "M9_s1.png").write_bytes(PNG + b"y")
    data = json.loads((mk / "manifest.json").read_text(encoding="utf-8"))
    data.append({"file": "M9_s1.png", "kind": "item/makeup", "design": "M9", "name": "测试妆"})
    (mk / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = c.post("/api/assets/characters/lin_wan/import").json()
    assert [x["item_id"] for x in r["created"]] == ["lw-makeup-m9"] and not r["skipped"]
    assert {a["item_id"] for a in r["attached"]} == {"lw-makeup-bare", "lw-makeup-m9"}
    m9 = next(i for i in store.wardrobe().items if i.id == "lw-makeup-m9")
    assert [im.version for im in m9.images] == [1, 2]
    lw = next(x for x in c.get("/api/assets/characters").json()["characters"] if x["id"] == "lin_wan")
    assert lw["unregistered"] == 0                                   # 「导入 manifest」一次就清零


def test_summary_latest_take(env):
    c, _, _ = env
    s = c.get("/api/episodes").json()[0]["shots"][0]
    assert set(s["latest_take"]) == {"image", "last", "video"}
    assert s["duration"]["seconds"] >= 3 and "stage" in (s["dialogue"][0] if s["dialogue"] else {"stage": None})


def test_audio_fields_and_partial_episode_edit(env):
    c, _, _ = env
    s = c.get("/api/episodes").json()[0]["shots"][0]
    a = s["audio"]
    assert set(a) >= {"soundscape", "music", "episode_music", "supported"}
    assert a["soundscape"]["source"] in ("edit", "script", "script_h3", "none")
    assert set(a["supported"]) == {"soundscape", "music", "episode_music"}
    # 只保存导演加强：不应该清掉其它字段
    c.put("/api/episodes/1/edit", json={"boost_first": "加强A"})
    r = c.put("/api/episodes/1/edit", json={"boost_last": "加强B"}).json()
    assert r["boost_first"] == "加强A" and r["boost_last"] == "加强B"
    if not app_mod.audio_supported()["episode_music"]:
        assert c.put("/api/episodes/1/edit", json={"music": "Sparse piano"}).status_code == 501
