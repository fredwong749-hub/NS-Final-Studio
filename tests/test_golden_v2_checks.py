"""golden_v2 看图核对项从本镜 P4 编译结果动态生成（ISS-1103-003851-4541，总调度 11-03）：不写死服装 / 场景。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]


def _load():
    """独立模块名加载、不进 sys.modules["golden_v2"]：golden_v2 导入时按当时的 NS_RUN 定剧，别污染 test_promptfix_v2 的 v2_env"""
    import importlib.util as u
    sp = u.spec_from_file_location("golden_v2_checks_iso", ROOT / "tools" / "promptfix" / "golden_v2.py")
    m = u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


GV = _load()
NL = chr(10)

LOOKS = {"ch_a": {
    "L1": NS(parts=[NS(label="红色羊毛大衣", extra=False), NS(label="黑色短靴", extra=False), NS(label="临时胸针", extra=True)]),
    "L2": NS(parts=[NS(label="白色真丝衬衫", extra=False), NS(label="灰色阔腿裤", extra=False)])}}


def _job(look, size="近景", cast=(("ch_a", "甲"),)):
    return {"asset_refs": {"size": size, "characters": [
        {"character": cid, "name": n, "presence": "在画", "look": look} for cid, n in cast]}}


def _shot(scene="sk_room", detail="窗边", img="甲坐在窗边看信"):
    return {"scene_id": scene, "scene_detail": detail, "img_prompt": img}


def test_items_differ_when_look_differs():
    a = GV.check_items(_job("L1"), _shot(), LOOKS)
    b = GV.check_items(_job("L2"), _shot(), LOOKS)
    assert a != b
    ja, jb = NL.join(a), NL.join(b)
    assert "红色羊毛大衣" in ja and "黑色短靴" in ja and "白色真丝衬衫" not in ja
    assert "白色真丝衬衫" in jb and "灰色阔腿裤" in jb and "红色羊毛大衣" not in jb
    assert "临时胸针" not in ja                     # extra 部件按词触发，不进固定核对项


def test_items_follow_scene_cast_and_size():
    it = GV.check_items(_job("L1", size="全景", cast=(("ch_a", "甲"), ("ch_b", "乙"))), _shot("sk_bar", "吧台尽头", "两人对坐"), LOOKS)
    j = NL.join(it)
    assert it[0].startswith("画面里恰好 2 个人（甲、乙）")
    assert "场景是 sk_bar：吧台尽头" in j and "景别是全景" in j and "两人对坐" in j
    assert "乙的造型 L1 在造型表里没有单品登记" in j          # 缺登记如实写，不拿甲的造型顶替
    for hard in ("黑色漆皮", "亚克力椅", "外滩", "白幕"):    # 旧版写死的内容不得再出现
        assert hard not in j


def test_question_numbers_items():
    q = GV.vlm_question(["一", "二"])
    assert "1. 一；2. 二。" in q and "总结：全部符合" in q


def test_invisible_accessory_parts_skipped():
    """近景（编译器 zones 不含 feet）不核鞋；服装本体照核"""
    lk = {"ch_a": {"L3": NS(parts=[NS(label="黑色连衣裙", extra=False, slot="outfit", zone="lower"),
                                   NS(label="透明高跟", extra=False, slot="shoes", zone="feet")])}}
    job = _job("L3")
    job["asset_refs"]["zones"] = ["face", "upper"]
    j = NL.join(GV.check_items(job, _shot(), lk))
    assert "黑色连衣裙" in j and "透明高跟" not in j
    job["asset_refs"]["zones"] = ["face", "upper", "feet"]
    assert "透明高跟" in NL.join(GV.check_items(job, _shot(), lk))


# ---------------------------------------------------------------- ISS-1103-005000-2af2：不带镜号失败关闭、去掉 V1 夹具骨架
def test_no_shot_fails_closed(capsys, monkeypatch):
    monkeypatch.setattr(GV, "SHOT", None)
    for argv in ([], ["--compile"], ["--summary"], ["--render"], ["--rejudge"]):
        assert GV.main(argv) == 2, argv
        assert "必须指定镜号" in capsys.readouterr().err
    import pytest
    with pytest.raises(SystemExit) as e:
        GV.compile_job()
    assert e.value.code == 2 and "必须指定镜号" in GV.NEED_SHOT


def test_no_v1_skeleton_or_hardcoded_text():
    src = (ROOT / "tools" / "promptfix" / "golden_v2.py").read_text(encoding="utf-8")
    for w in ("frozen_v1", "build_script", "外滩", "风衣", "陆家嘴", "IMG_NIGHT", "SEGMENT_DETAIL"):
        assert w not in src, w
