"""ASSETUX V2 资产页（总调度 20:10）：只读 assets_v2/manifest.json；成人类只给文字卡（没有图片地址、没有“修改”）；
清单外的文件不发；“修改”立刻 202 只记账；其他人物和场景是占位，不是空白格。临时目录里跑，不碰真实数据。"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import v2_assets as V

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def c(tmp_path, monkeypatch):
    root = tmp_path
    files = {"face": "assets_v2/characters/lead_f/face/f.png", "o1": "assets_v2/characters/lead_f/outfits/o1.png", "o2": "assets_v2/characters/lead_f/outfits/o2.png",
             "sh2": "assets_v2/characters/lead_f/shoes/sh2.png", "j1": "assets_v2/characters/lead_f/jewelry/j1.png"}
    for f in files.values():
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_bytes(b"png")
    man = {"run": "series10_v2", "locked": False, "scenes": {}, "characters": {"lead_f": {
        "display_name": None, "face": {"id": "lead_f_face_v1", "file": files["face"]},
        "looks": {"O1": {"name": "长风衣", "adult": False, "route": "server_ok", "items": {"O1_garment": {"file": files["o1"]}}, "sheet": None},
                  "O2": {"name": "绑带内衣", "adult": True, "route": "local_only", "items": {"O2_garment": {"file": files["o2"]}}, "sheet": None}},
        "items": {"SH1": {"slot": "shoes", "name": "透明高跟", "adult": False, "route": "server_ok", "file": None},
                  "SH2": {"slot": "shoes", "name": "细带凉鞋", "adult": False, "route": "server_ok", "file": files["sh2"]},
                  "J1": {"slot": "body_jewelry", "name": "圆环", "adult": True, "route": "local_only", "file": files["j1"]}}}}}
    (root / "assets_v2" / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(V, "ROOT", root)
    monkeypatch.setattr(V, "MANIFEST", root / "assets_v2" / "manifest.json")
    monkeypatch.setattr(V, "EDITS", root / "data" / "state" / "e.json")
    app = FastAPI()
    app.include_router(V.router)
    return TestClient(app)


def cards(d):
    return {x["id"]: x for g in d["characters"][0]["groups"] for x in g["cards"]}


def test_groups_and_adult_cards_are_text_only(c):
    d = c.get("/api/v2/assets").json()
    assert [g["key"] for g in d["characters"][0]["groups"]] == ["face", "looks", "shoes", "jewelry"]
    k = cards(d)
    assert k["lead_f:face"]["url"] and k["lead_f:O1"]["url"] and k["lead_f:SH2"]["url"]
    for aid in ("lead_f:O2", "lead_f:J1"):                                    # 成人类：没有图片地址、没有“修改”，只有这句话
        assert k[aid]["url"] is None and k[aid]["text"] == "仅本地，项目方触发" and k[aid]["can_edit"] is False and k[aid]["adult"] is True
    assert k["lead_f:SH1"]["url"] is None and "原图" in k["lead_f:SH1"]["text"] and k["lead_f:SH1"]["can_edit"] is False      # 没有原图：说明，不是空白格
    assert d["pending"] == [{"label": "其他人物和场景", "note": "等剧本定稿后出候选"}]


def test_file_endpoint_only_serves_registered_non_adult(c):
    ok = c.get("/api/v2/asset-file?path=assets_v2/characters/lead_f/outfits/o1.png")
    assert ok.status_code == 200
    assert c.get("/api/v2/asset-file?path=assets_v2/characters/lead_f/outfits/o2.png").status_code == 403          # 成人类不发图
    assert c.get("/api/v2/asset-file?path=assets_v2/manifest.json").status_code == 404                              # 清单外不发
    assert c.get("/api/v2/asset-file?path=../etc/passwd").status_code == 404


def test_edit_is_202_records_and_refuses_adult(c):
    r = c.post("/api/v2/assets/lead_f:O1/edit", json={"text": "领口再挺一点", "chips": ["更写实"]})
    assert r.status_code == 202 and r.json()["state"] == "received"
    d = c.get("/api/v2/assets").json()
    assert cards(d)["lead_f:O1"]["edit"]["text"] == "领口再挺一点"
    assert c.post("/api/v2/assets/lead_f:O2/edit", json={"text": "x"}).status_code == 409                      # 成人类不在网页改
    assert c.post("/api/v2/assets/lead_f:SH1/edit", json={"text": "x"}).status_code == 409                     # 没有原图
    assert c.post("/api/v2/assets/nobody:x/edit", json={"text": "x"}).status_code == 404


def test_missing_manifest_says_so(c, tmp_path, monkeypatch):
    monkeypatch.setattr(V, "MANIFEST", tmp_path / "none.json")
    r = c.get("/api/v2/assets")
    assert r.status_code == 503 and "清单" in r.json()["detail"]                                                 # 不退回 V1


def test_real_manifest_shape():
    d = json.loads((ROOT / "assets_v2" / "manifest.json").read_text(encoding="utf-8"))
    reg = V.registered_files(d)
    adult = {f for f, a in reg.items() if a}
    assert adult and all("lingerie" in f or "spiked" in f or "jewelry" in f for f in adult)                    # O2 / O3 / J1 / J2 都标成人
