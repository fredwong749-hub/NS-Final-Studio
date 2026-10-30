"""state_timeline 的 gpu3 渲染侧字段（docs/state_timeline.md「gpu3 渲染侧字段」）：
props / changes_within_shot + items_end / framing + faces_visible / plate_detail.light / 段切法 / signature。
全部在临时项目根目录里跑（固定剧本 tests/fixtures/t06_golden + 仓库 data/looks 副本），不碰真实 data/。"""
import shutil
from pathlib import Path

import pytest

from ns_agent import gpu3_fields as G
from ns_agent import state_timeline as T

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "t06_golden"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("gpu3") / "proj"
    shutil.copytree(FIX / "config", root / "config")
    shutil.copytree(FIX / "data", root / "data")
    shutil.copytree(REPO / "data" / "looks", root / "data" / "looks",
                    ignore=shutil.ignore_patterns("*.tmp", "*.bak*"))
    (root / "config" / "shot_ownership.json").write_text("{}", encoding="utf-8")
    tl, sc = T.build(root)
    return tl, sc, {r["shot_id"]: r for r in tl["shots"]}


# ------------------------------------------------------------------ 1. 道具

def test_state_cue_words():
    t = "射灯聚焦挂在墙上的黑色漆皮束腰"
    i = t.index("束腰")
    assert G.state_near(t, i, i + 2) == "hanging"
    t = "她抱紧怀里的文件夹贴在胸前"
    i = t.index("文件夹")
    assert G.state_near(t, i, i + 3) == "held"
    t = "她把手机扣在茶几上的动作特写"
    i = t.index("手机")
    assert G.state_near(t, i, i + 2) == "on_table"
    t = "她一身黑色漆皮长风衣"
    i = t.index("风衣")
    assert G.state_near(t, i, i + 2) == "worn"
    t = "穿孔工作室，图纸"                       # 穿孔 ≠ 穿；不同分句不算
    assert G.state_near(t, t.index("图纸"), t.index("图纸") + 2) is None


def test_ep05_corset_hangs_not_worn(built):
    _, _, by = built
    p = next(p for p in by["ep05-S1"]["props"] if p["trigger"] == "ptxcorset")
    assert p["state"] == "hanging" and p["state_source"] == "text" and p["holder"] is None
    assert p["trigger_conflict"] is True             # 触发词会画成“穿着”→ 渲染侧须按 state
    assert {"id", "name", "description", "state", "ref_image"} <= set(p)
    # 同段后面没写状态的镜头沿用“挂着”
    p3 = next(p for p in by["ep05-S3"]["props"] if p["trigger"] == "ptxcorset")
    assert p3["state"] == "hanging" and p3["state_source"] == "inherited"


def test_props_held_and_guess(built):
    _, _, by = built
    folder = next(p for p in by["ep01-S1"]["props"] if p["name"] == "文件夹")
    assert folder["state"] == "held" and folder["state_source"] == "guess"       # img 没写怎么拿
    phone = next(p for p in by["ep41-S4"]["props"] if p["name"] == "手机")
    assert phone["state"] == "on_table" and phone["state_source"] == "text"
    for r in by.values():
        for p in r["props"]:
            assert p["state"] in ("worn", "hanging", "held", "on_table")
            assert p["state_source"] in ("text", "inherited", "guess")
        assert len({p["id"] for p in r["props"]}) == len(r["props"])            # 每镜同一道具只一条


# ------------------------------------------------------------------ 2. 镜内换装

def test_changes_within_shot_and_end_state(built):
    _, _, by = built
    lw = by["ep28-S6"]["characters"]["lin_wan"]       # 束腰脱下、挂回衣架
    ch = next(c for c in lw["changes_within_shot"] if c["item"] == "lora-ptxcorset")
    assert ch["to"] == "removed" and ch["from"] == "worn" and ch["slot"] == "outfit"
    p = next(p for p in by["ep28-S6"]["props"] if p["id"] == "lora-ptxcorset")
    assert p["state"] == "worn" and p["state_end"] == "hanging"
    assert lw["signature"] != lw["signature_end"]
    gc = by["ep12-S1"]["characters"]
    assert not gc["gu_chen"]["changes_within_shot"]                     # 他解开的是她的衬衫
    assert gc["lin_wan"]["changes_within_shot"][0]["to"] == "opened"
    robe = by["ep31-S5"]["characters"]["lin_wan"]["changes_within_shot"][0]
    assert robe["to"] == "worn" and robe["garment"] == "睡袍"
    for r in by.values():
        for c in r["characters"].values():
            assert "items_end" in c and c["visibility_end"] in ("visible", "hidden", "in_box")
            if not c["changes_within_shot"]:
                assert c["items_end"] == {sl: [i["id"] for i in lst] for sl, lst in c["items"].items()}


def test_change_verbs_ignore_non_garments():
    chars = {"lin_wan": {"present": True, "items": {}}}
    assert G.shot_changes("她拉开窗帘，光涌满", "", [], ["lin_wan"], chars) == {}
    out = G.shot_changes("", "她脱下外套", [], ["lin_wan"], chars)
    assert out["lin_wan"][0]["to"] == "removed" and out["lin_wan"][0]["garment"] == "外套"


def test_end_state_applies_changes():
    wardrobe = {"coat": object()}
    char = {"present": True, "visibility": "hidden", "adornments": [],
            "items": {"outfit": [{"id": "coat", "name": "外套"}]}}
    ch = [{"slot": "outfit", "item": "coat", "to": "removed"}]
    end = G.end_state(char, ch, wardrobe, "", "")
    assert end["items_end"]["outfit"] == [] and end["visibility_end"] == "visible"
    assert end["visibility_end_source"] == "guess"
    end = G.end_state(dict(char, visibility="visible"), [], wardrobe, "", "她把珠串放进丝绒盒")
    assert end["visibility_end"] == "in_box"


# ------------------------------------------------------------------ 3. 景别 / 可见脸

def test_framing_words():
    assert G.shot_framing("极近特写，林晚低头侧脸", "") == ("extreme_close", "text")
    assert G.shot_framing("女性指尖悬停的特写", "") == ("close", "text")
    assert G.shot_framing("双人构图，顾沉立在她身后", "") == ("medium", "text")
    assert G.shot_framing("深夜写字楼全景，整层黑", "") == ("full", "text")
    assert G.shot_framing("电梯轿厢，两人并排而立", "")[1] == "guess"


def test_framing_and_faces_in_timeline(built):
    tl, _, by = built
    assert by["ep01-S3"]["framing"] == "extreme_close" and by["ep01-S3"]["faces_visible"] == ["lin_wan"]
    assert by["ep24-S3"]["framing"] == "close" and by["ep24-S3"]["faces_visible"] == []   # 解暗扣的手部特写
    assert by["ep01-S2"]["props"][0]["holder"] == "gu_chen"          # 黑色高定衬衫在顾沉的造型里
    assert by["ep01-S5"]["faces_visible"] == []                                         # 背对镜头
    assert "lin_wan" not in by["ep05-S5"]["faces_visible"]                               # 她走出去的背影
    for r in by.values():
        assert r["framing"] in ("extreme_close", "close", "medium", "full")
        present = {c for c, v in r["characters"].items() if v["present"]}
        assert set(r["faces_visible"]) <= present
    assert sum(tl["stats"]["gpu3"]["framing"].values()) == tl["stats"]["shots"]


# ------------------------------------------------------------------ 4. 底板光线

def test_plate_detail_light(built):
    _, sc, _ = built
    for s in sc["scenes"]:
        pd = s["plate_detail"]
        assert pd["path"] == s["plate"] and pd["status"] == s["plate_status"] == "missing"
        assert pd["sha256"] == s["plate_sha256"]
        assert set(pd["light"]) == {"time", "key_direction", "colour_temp"}
        assert pd["light"]["time"] == (s["time_of_day"] or None)
        for seg in s["segments"]:
            assert set(seg["light"]) == {"time", "key_direction", "colour_temp"}
    assert G.light_of(["暖黄台灯照着餐桌"], "night") == {"time": "night", "key_direction": None, "colour_temp": "warm"}
    assert G.light_of(["射灯聚焦挂在墙上的束腰"], "") == {"time": None, "key_direction": "top", "colour_temp": None}


# ------------------------------------------------------------------ 5. 段

def test_segments_prev_and_cut_type(built):
    tl, sc, by = built
    assert G.cut_type("闪回") == "flashback" and G.cut_type("次日") == "time_skip"
    assert G.cut_type("周五") == "time_skip" and G.cut_type("place") == "hard" and G.cut_type("episode") == "hard"
    segs = [s for ep in tl["episode_segments"].values() for s in ep]
    assert len(segs) == tl["stats"]["segments"]
    assert segs[0]["prev_segment_id"] is None
    for a, b in zip(segs, segs[1:]):
        assert b["prev_segment_id"] == a["segment_id"]                 # 全剧顺序（跨集也接上）
    for s in segs:
        assert s["cut_type"] in ("hard", "time_skip", "flashback")
        for sid in s["shots"]:
            assert by[sid]["segment_id"] == s["segment_id"] and by[sid]["cut_type"] == s["cut_type"]
            assert by[sid]["prev_segment_id"] == s["prev_segment_id"]
    assert [s["segment_id"] for s in tl["episode_segments"]["1"]] == sorted(
        {r["segment_id"] for r in tl["shots"] if r["episode"] == 1})
    seg_in_scenes = {seg["segment_id"]: seg for s in sc["scenes"] for seg in s["segments"]}
    assert all(seg_in_scenes[s["segment_id"]]["cut_type"] == s["cut_type"] for s in segs)


# ------------------------------------------------------------------ 6. 签名

def test_signature_stable_and_order_free():
    a = G.signature({"outfit": ["x", "y"], "makeup": ["m"]}, [{"id": "r", "worn": True}], [])
    b = G.signature({"outfit": ["y", "x"], "makeup": ["other"]}, [{"id": "r", "worn": True}], [])
    assert a == b and len(a) == 12                                   # 妆不进签名；顺序无关
    assert a != G.signature({"outfit": ["x", "y"]}, [{"id": "r", "worn": False}], [])
    assert a != G.signature({"outfit": ["x", "y"]}, [{"id": "r", "worn": True}], ["prop:外套"])


def test_signature_in_timeline(built):
    _, _, by = built
    for r in by.values():
        for c in r["characters"].values():
            assert len(c["signature"]) == 12 and len(c["signature_end"]) == 12
    # 同段两镜穿戴一样 → 签名一样
    a, b = by["ep01-S2"]["characters"]["lin_wan"], by["ep01-S3"]["characters"]["lin_wan"]
    assert a["signature"] == b["signature"]
