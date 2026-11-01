"""BE-5：流水线出图登记为画布候选版本——走 pipeline._add_take、不设当前、不加锁、标暂定 + 来源、可重复执行。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import register_takes as RT  # noqa: E402


@pytest.fixture
def renders(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    data = tmp_path / "data"
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    return P, tmp_path


def _png(path: Path, w=576, h=1008):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (120, 90, 200)).save(path)
    return path


def test_register_is_candidate_tentative_and_idempotent(renders):
    P, tmp = renders
    img = _png(tmp / "imggen" / "ep01-S1_s1.png")
    item = {"shot": "ep01-S1", "file": str(img), "seed": 7, "prompt": "p", "refs": ["data/x.png"],
            "origin": {"run": "series10_v1", "job": "frame:ep01-S1", "attempt": "frame:ep01-S1#0"}}
    r = RT.register(item, label="旧配方")
    assert r["status"] == "registered" and r["n"] == 1
    d = P.load_takes("ep01-S1")
    t = d["takes"][0]
    assert t["stage"] == "image" and t["source"] == "pipeline" and (P.DATA / t["file"]).is_file()
    assert t["params"]["tentative"] is True and t["params"]["label"] == "旧配方"
    assert t["params"]["origin"]["sha256"] and t["params"]["origin"]["job"] == "frame:ep01-S1"
    assert t["params"]["rendered_size"] == [576, 1008] and not t.get("bad")
    assert not (d.get("active") or {}).get("image") and not (d.get("locked") or {}).get("image")   # 不设当前、不加锁
    assert RT.register(item, label="旧配方")["status"] == "skipped"                              # 重复执行不重复登记
    img2 = _png(tmp / "imggen" / "ep01-S1_s2.png", 576, 1000)
    r2 = RT.register({**item, "file": str(img2)}, label="新配方")
    assert r2["status"] == "registered" and r2["n"] == 2
    assert [x["params"]["label"] for x in P.load_takes("ep01-S1")["takes"]] == ["旧配方", "新配方"]


def test_imggen_adapter_and_unknown_shot(renders, tmp_path):
    P, tmp = renders
    img = _png(tmp / "imggen" / "a.png")
    st = {"jobs": {"frame:ep02-S3": {"kind": "frame", "shot": "ep02-S3", "chosen": "frame:ep02-S3#1", "status": "pass",
                                     "attempts": [{"id": "frame:ep02-S3#0", "file": str(img), "seed": 1, "t_done": 1},
                                                  {"id": "frame:ep02-S3#1", "file": str(img), "seed": 2, "prompt": "q", "t_done": 2}, {"id": "frame:ep02-S3#2", "file": str(img), "seed": 3}]},
                   "sheet:x": {"kind": "sheet", "attempts": []}}}
    sp = tmp_path / "run" / "images" / "state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps(st), encoding="utf-8")
    items = RT.items_from_imggen(sp)
    assert len(items) == 1 and items[0]["seed"] == 2 and items[0]["origin"]["chosen"]
    assert len(RT.items_from_imggen(sp, all_attempts=True)) == 2
    out = RT.run(items + [{"shot": "ep99-S1", "file": str(img)}], label="新配方", log=lambda *_: None,
                 known={"ep02-S3"})
    assert out["registered"] == 1 and out["missing"] == 1


def test_postflight_pass_written_and_set_current(renders, tmp_path):
    """总调度接口决定：契约通过的帧写 postflight {ok, items, reasons, ts} 并设为当前；不过的只登记不设当前"""
    P, tmp = renders
    img = _png(tmp / "a" / "ok.png")
    pf = {"ok": True, "items": [{"id": "Q1", "status": "pass"}], "reasons": []}
    r = RT.register({"shot": "ep03-S2", "stage": "image", "file": str(img), "postflight": pf}, label="新配方")
    d = P.load_takes("ep03-S2")
    t = d["takes"][0]
    assert r.get("active") and d["active"]["image"] == r["n"]
    assert t["postflight"]["ok"] is True and t["postflight"]["items"][0]["id"] == "Q1" and t["postflight"]["ts"]
    bad = _png(tmp / "a" / "bad.png", 576, 1000)
    r2 = RT.register({"shot": "ep03-S2", "stage": "image", "file": str(bad),
                      "postflight": {"ok": False, "items": [], "reasons": ["Q1 0.55 < 0.70"]}}, label="新配方·不合格")
    d = P.load_takes("ep03-S2")
    assert not r2.get("active") and d["active"]["image"] == r["n"]            # 不合格不抢当前
    assert d["takes"][1]["postflight"]["ok"] is False


def test_mark_episode_done(tmp_path):
    p = tmp_path / "video" / "frames_ok.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"ep01-S1": {"x": 1}}), encoding="utf-8")
    assert RT.mark_episode_done(3, p) == [3]
    assert RT.mark_episode_done(1, p) == [1, 3]
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["_episodes_done"] == [1, 3] and d["ep01-S1"] == {"x": 1} and "3" in d["_episodes_done_at"]
