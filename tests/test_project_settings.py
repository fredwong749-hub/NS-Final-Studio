"""项目设置页后端（ns_api.project_settings）：K-UI-030 恢复旧向导的设置项。

全部在临时目录：GET 列表、PUT 局部改一个键（JSON / TOML 格式与注释原样保留）、改前备份、
越权 / 只读项 / 并入项拒绝、expect 冲突 409、真实配置副本逐项改一遍只变那一个键。"""
import json
import shutil
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import project_settings as S

REPO = Path(__file__).resolve().parents[1]

VB_TEXT = """# 视觉圣经 # 带井号的注释
[project]
name = "测试剧"
image_doc = "a.md"
corrector_doc = "b.md"

[look]
use_script_suffix = true
fallback_suffix = "暖调 #1 通透"   # A3 注释里也有 # 号
lens_template = "Leica {mm}mm f/{f}"
style_negative = "字幕、水印"
color_reference = "assets/style/ref.png"

[look.video]
style = "不该被改"

[[materials]]
id = "m1"                  # B5
match = ["漆皮", "ptx"]
term = "高亮漆皮"

[[materials]]
id = "m2"
match = ["高跟"]
term = "细跟"

[[shot_rules]]
id = "closeup"
match = ["特写"]
term = "面部清晰"

[shot_rules_safe]
term = "衣装完整"
negative = "裸露"

[characters.lin_wan]
name = "林晚"
nails = "长甲"
hair_color = "蓝发"
wardrobe_rule = "性感"
heels_default = "hh12clear"
makeup_palette = "莓果"

[generation]
nudity_qc_non_adult = "report_only"
"""

RQ = {
    "schema": "x",
    "default_preset": "p1",
    "tiers": {"final": {"realism_loras": [["krea2_film_texture_qwen21.safetensors", 0.5]],
                        "grade": {"method": "reinhard_lab", "strength": 0.6, "reference": "assets/style/ref.png"}}},
    "image_presets": [
        {"id": "p0", "label": "旧", "params": {"style_suffix": "旧后缀", "loras": []}},
        {"id": "p1", "label": "徕卡", "params": {"style_suffix": "徕卡后缀", "loras": [
            {"name": "other.safetensors", "strength": 0.9}, {"name": "krea2_film_texture_qwen21.safetensors", "strength": 0.5}]}},
    ],
    "user_presets": [],
    "post": {"h3_music": {"default": "duck_under_bgm"}, "dialogue_source": {"default": "h3"}},
}


def _rq_text() -> str:
    # 故意混排：有的数组一行写完，有的多行，看局部替换后其余格式不变
    t = json.dumps(RQ, ensure_ascii=False, indent=2)
    return t.replace('[\n          "krea2_film_texture_qwen21.safetensors",\n          0.5\n        ]', '["krea2_film_texture_qwen21.safetensors", 0.5]')


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path
    (root / "config").mkdir()
    (root / "assets" / "style").mkdir(parents=True)
    (root / "assets" / "style" / "ref.png").write_bytes(b"x")
    (root / "assets" / "style" / "ref2.png").write_bytes(b"y")
    (root / "data" / "staging").mkdir(parents=True)
    (root / "data" / "staging" / "s1.md").write_text("# s1", encoding="utf-8")
    (root / "data" / "staging" / "s2.md").write_text("# s2", encoding="utf-8")
    (root / "config" / "visual_bible.toml").write_bytes(VB_TEXT.replace("\n", "\r\n").encode("utf-8"))  # CRLF 也要保住
    (root / "config" / "render_quality.json").write_text(_rq_text(), encoding="utf-8")
    (root / "config" / "script_mainline.json").write_text(json.dumps(
        {"note": "主线", "mainline": ["data/staging/s1.md"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "config" / "adult_overrides.json").write_text(json.dumps({"_comment": "c", "per_shot": False, "force_adult": {}},
                                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "config" / "face_reference.json").write_text(json.dumps({"approved_for_adult": True, "approved_by": "项目方"},
                                                                    ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(S, "ROOT", root)
    app = FastAPI()
    app.include_router(S.router)
    return root, TestClient(app)


def _item(c, iid):
    return next(x for x in c.get("/api/project-settings").json()["items"] if x["id"] == iid)


def test_list_has_all_groups_and_statuses(env):
    _, c = env
    d = c.get("/api/project-settings").json()
    ids = {x["id"]: x for x in d["items"]}
    assert len(d["items"]) >= 30
    assert set(x["group"] for x in d["items"]) <= set(d["groups"])
    # 每项都有旧版出处；并入项写了并入到哪；只读项写了在哪改
    for x in d["items"]:
        assert x["legacy"]
        if x["status"] == "merged":
            assert x["merged_into"]
        if x["status"] == "readonly":
            assert x["edit_where"]
    assert ids["fallback_suffix"]["value"] == "暖调 #1 通透" and ids["fallback_suffix"]["status"] == "edit"
    assert ids["realism_texture"]["value"] == 0.5
    assert ids["materials:m2"]["value"] == "细跟"
    assert ids["image_doc"]["status"] == "merged" and ids["image_doc"]["value"] == "a.md"
    assert ids["adult_ai_confirm"]["status"] == "readonly"
    # 缺文件的“可改”项降为只读并说明原因，不 500
    assert ids["voice_rule"]["error"]


def test_toml_edit_only_that_key_keeps_comments_and_crlf(env):
    root, c = env
    p = root / "config" / "visual_bible.toml"
    before = p.read_bytes()
    r = c.put("/api/project-settings/fallback_suffix", json={"value": "新后缀 # 带井号", "by": "owner", "key": "fallback_suffix"})
    assert r.status_code == 200, r.text
    assert r.json()["prev"] == "暖调 #1 通透"
    after = p.read_bytes()
    assert b"\r\n" in after and after.count(b"\r\n") == before.count(b"\r\n")
    a_lines, b_lines = after.decode().splitlines(), before.decode().splitlines()
    diff = [(x, y) for x, y in zip(b_lines, a_lines) if x != y]
    assert len(diff) == 1
    assert diff[0][1] == 'fallback_suffix = "新后缀 # 带井号"   # A3 注释里也有 # 号'
    assert tomllib.loads(after.decode())["look"]["video"]["style"] == "不该被改"
    # 备份是原文件原样
    bk = root / r.json()["backup"]
    assert bk.parent == root / "data" / "assets" / "settings_backups"
    assert bk.read_bytes() == before
    log = (root / "data" / "assets" / "settings_backups" / "changes.jsonl").read_text(encoding="utf-8")
    assert '"item": "fallback_suffix"' in log


def test_toml_array_of_tables_by_id(env):
    root, c = env
    r = c.put("/api/project-settings/materials:m2", json={"value": "针形细跟", "by": "owner"})
    assert r.status_code == 200, r.text
    d = tomllib.loads((root / "config" / "visual_bible.toml").read_text(encoding="utf-8"))
    assert [m["term"] for m in d["materials"]] == ["高亮漆皮", "针形细跟"]
    assert d["materials"][0]["match"] == ["漆皮", "ptx"]


def test_json_nested_selectors_keep_format(env):
    root, c = env
    p = root / "config" / "render_quality.json"
    before = p.read_text(encoding="utf-8")
    r = c.put("/api/project-settings/realism_texture", json={"value": 0.35, "by": "owner"})
    assert r.status_code == 200, r.text
    after = p.read_text(encoding="utf-8")
    d = json.loads(after)
    assert d["image_presets"][1]["params"]["loras"][1]["strength"] == 0.35
    assert d["image_presets"][1]["params"]["loras"][0]["strength"] == 0.9
    # 只差那一个数字；一行写完的数组格式还在
    assert after.replace("0.35", "0.5", 1) == before
    assert '["krea2_film_texture_qwen21.safetensors", 0.5]' in after
    r = c.put("/api/project-settings/realism_texture_final", json={"value": 0.4, "by": "owner"})
    assert r.status_code == 200, r.text
    assert json.loads(p.read_text(encoding="utf-8"))["tiers"]["final"]["realism_loras"] == [["krea2_film_texture_qwen21.safetensors", 0.4]]
    assert '["krea2_film_texture_qwen21.safetensors", 0.4]' in p.read_text(encoding="utf-8")


def test_validation_and_guards(env):
    root, c = env
    snap = {f.name: f.read_bytes() for f in (root / "config").iterdir()}
    assert c.put("/api/project-settings/fallback_suffix", json={"value": "x", "by": "unauthenticated"}).status_code == 403
    assert c.put("/api/project-settings/fallback_suffix", json={"value": "x"}).status_code == 403
    assert c.put("/api/project-settings/color_match_strength", json={"value": 1.5, "by": "owner"}).status_code == 422
    assert c.put("/api/project-settings/color_match_strength", json={"value": "abc", "by": "owner"}).status_code == 422
    assert c.put("/api/project-settings/h3_music", json={"value": "loud", "by": "owner"}).status_code == 422
    assert c.put("/api/project-settings/color_reference", json={"value": "assets/style/nope.png", "by": "owner"}).status_code == 422
    assert c.put("/api/project-settings/color_reference", json={"value": "../../etc/passwd", "by": "owner"}).status_code == 422
    assert c.put("/api/project-settings/mainline", json={"value": [], "by": "owner"}).status_code == 422
    # 只读 / 并入项不能写
    assert c.put("/api/project-settings/adult_ai_confirm", json={"value": False, "by": "owner"}).status_code == 409
    assert c.put("/api/project-settings/hair", json={"value": "红发", "by": "owner"}).status_code == 409
    assert c.put("/api/project-settings/nope", json={"value": 1, "by": "owner"}).status_code == 404
    # expect 不符 → 409，不覆盖
    r = c.put("/api/project-settings/style_negative", json={"value": "新", "by": "owner", "expect": "别人看到的旧值", "has_expect": True})
    assert r.status_code == 409
    assert {f.name: f.read_bytes() for f in (root / "config").iterdir()} == snap
    assert not (root / "data" / "assets" / "settings_backups").exists()


def test_select_bool_paths_and_unchanged(env):
    root, c = env
    r = c.put("/api/project-settings/adult_judge", json={"value": True, "by": "owner", "expect": False, "has_expect": True})
    assert r.status_code == 200, r.text
    assert json.loads((root / "config" / "adult_overrides.json").read_text(encoding="utf-8"))["per_shot"] is True
    r = c.put("/api/project-settings/default_preset", json={"value": "p0", "by": "owner"})
    assert r.status_code == 200
    # 默认预设换了，预设后缀那一项随之指向 p0
    assert _item(c, "preset_suffix")["value"] == "旧后缀"
    r = c.put("/api/project-settings/mainline", json={"value": ["data/staging/s1.md", " data/staging/s2.md "], "by": "owner"})
    assert r.status_code == 200, r.text
    assert json.loads((root / "config" / "script_mainline.json").read_text(encoding="utf-8"))["mainline"] == ["data/staging/s1.md", "data/staging/s2.md"]
    n = len(list((root / "data" / "assets" / "settings_backups").glob("*.json")))
    r = c.put("/api/project-settings/dialogue_source", json={"value": "h3", "by": "owner"})
    assert r.status_code == 200 and r.json()["unchanged"] is True
    assert len(list((root / "data" / "assets" / "settings_backups").glob("*.json"))) == n


@pytest.mark.skipif(not (REPO / "config" / "render_quality.json").exists() or not (REPO / "config" / "visual_bible.toml").exists(),
                    reason="没有真实配置")
def test_real_config_copies_every_editable_item(tmp_path, monkeypatch):
    """真实配置的副本：每个可改项改一次，解析结果只变那一个键，其它文本行不变"""
    for rel in ("config/visual_bible.toml", "config/render_quality.json", "config/script_mainline.json",
                "config/adult_overrides.json", "config/face_reference.json", "config/voices.json", "config/gen_contract.json"):
        src = REPO / rel
        if src.exists():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp_path / rel)
    monkeypatch.setattr(S, "ROOT", tmp_path)
    app = FastAPI()
    app.include_router(S.router)
    c = TestClient(app)
    items = c.get("/api/project-settings").json()["items"]
    edits = [x for x in items if x["status"] == "edit"]
    assert len(edits) >= 15
    for x in edits:
        if x["type"] in ("path", "paths"):
            continue               # 路径要求文件存在，副本目录里没有
        f = tmp_path / x["file"]
        before = f.read_text(encoding="utf-8-sig")
        v = x["value"]
        if x["type"] == "number":
            new = 0.45 if v != 0.45 else 0.55
        elif x["type"] == "select":
            new = next(o[0] for o in x["options"] if o[0] != v)
        else:
            new = (v or "") + "（改）"
        r = c.put(f"/api/project-settings/{x['id']}", json={"value": new, "by": "owner", "expect": v, "has_expect": True})
        assert r.status_code == 200, (x["id"], r.text)
        after = f.read_text(encoding="utf-8-sig")
        changed = [i for i, (a, b) in enumerate(zip(before.splitlines(), after.splitlines())) if a != b]
        assert len(before.splitlines()) == len(after.splitlines()), x["id"]
        assert len(changed) == 1, (x["id"], changed)
        # 改回去
        r = c.put(f"/api/project-settings/{x['id']}", json={"value": v, "by": "owner"})
        assert r.status_code == 200
        assert f.read_text(encoding="utf-8-sig") == before, x["id"]
