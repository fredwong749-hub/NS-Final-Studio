"""L-197 B：previz 自动摆位（tools/previz/auto_blocking.py）+ 生产图 Fun ControlNet 选项 + 作业签名。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/autopilot", "tools/previz", ""):
    sys.path.insert(0, str(ROOT / p))

import auto_blocking as AB  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402
import producer as PR  # noqa: E402

MD = """【祁念】23岁成年女性，二十三岁｜高挑纤细、腿长｜雾蓝色及腰长直发、空气感碎刘海｜黑色漆皮
【卓琳】35岁成年女性，三十五岁｜匀称干练｜黑色齐肩直发、中分｜酒红与黑
【周序】25岁成年男性，二十五岁｜结实中等身高｜黑色寸头｜藏青与灰

**镜2｜img**：中近景，过肩机位，从卓琳右肩后方越过她的肩拍祁念。
**机位与景别**：中近景｜过肩、略仰（A 区）｜从卓琳（左下，前景，只露右肩与后脑）右肩后方越肩拍祁念（右偏中，脸在焦点上）
**光学**：85mm｜T1.4｜高度=1.1m（卓琳蹲姿肩高）
**场景**：sk_white_cyc｜【现实段】白幕前，环形灯架关着在右前景
**人物**：祁念（在画｜右｜中）、卓琳（在画｜左｜前）
**站位**：祁念：侧右｜站在白幕中央、脸在焦点上，右手搭白幕弧面；卓琳：背对镜头｜只以右肩与后脑在画面左下前景入画、大幅虚化，蹲在祁念的左前方
**构图**：背景=白幕中灰弧面｜视线方向=向右前看
**镜3｜img**：中景，侧 45° 机位，周序坐在驾驶座。
**机位与景别**：中景｜侧 30°、平视｜周序一人在画
**光学**：50mm｜T2｜高度=1.2m（驾驶座眼平）
**场景**：sk_rooftop_bar｜【现实段】楼下街口路灯下的网约车驾驶座，方向盘
**人物**：周序（在画｜中｜中）
**站位**：周序：侧左｜坐在驾驶座，左手搭方向盘，右手举手机
**构图**：背景=车窗外路灯
**镜4｜img**：大特写，插入镜头，俯拍桌面。
**机位与景别**：大特写｜俯拍｜只拍两只手
**光学**：100mm｜T2｜高度=1.5m
**场景**：sk_rooftop_bar｜高圆桌桌面，一把钥匙
**人物**：祁念（局部｜右手｜左）、卓琳（局部｜右手｜右）
**站位**：祁念：局部｜右手从画面左侧探入；卓琳：局部｜右手从画面右上探入
**构图**：背景=桌面
"""


def _spec(n):
    cast = AB.read_cast(MD)
    return AB.auto_blocking(n, AB.split_shots(MD)[n], cast)


def test_parse_cast_and_shots():
    cast = AB.read_cast(MD)
    assert cast["祁念"]["sex"] == "女" and cast["祁念"]["hair"] == "long" and cast["卓琳"]["hair"] == "bob"
    assert cast["周序"]["height"] == 1.74
    assert sorted(AB.split_shots(MD)) == [2, 3, 4]
    assert AB.parse_optics("85mm｜T1.4｜高度=1.1m（x）") == (85.0, 1.4, 1.1)


def test_ots_blocking_hides_face_and_places_foreground():
    s = _spec(2)
    a = {x["id"]: x for x in s["actors"]}
    assert s["camera"]["focal_mm"] == 85 and s["camera"]["pos"][2] == 1.1
    assert a["卓琳"]["pos"][1] < a["祁念"]["pos"][1]               # 背对镜头的前景人物在主体前面
    assert a["卓琳"]["pos"][0] < 0 < a["祁念"]["pos"][0]            # 左下前景 / 右偏中
    assert a["卓琳"]["pose"] == "seated"                            # 蹲姿
    assert a["卓琳"]["face_to"][1] > a["卓琳"]["pos"][1]            # 背对镜头 = 朝向画里
    assert a["祁念"]["face_to"][1] < a["祁念"]["pos"][1]            # 脸朝相机
    assert 1.5 < a["祁念"]["pos"][1] < 3.0                          # 85mm 中近景的主体距离
    assert any(p["type"] == "cyc" for p in s["props"])


def test_car_and_hands_shots():
    s = _spec(3)
    assert s["actors"][0]["pose"] == "seated"
    assert any(p["name"] == "steering_wheel" for p in s["props"])
    h = _spec(4)
    assert h["actors"] == [] and h["camera"]["look_at"][2] == 1.05
    assert h["camera"]["pos"][2] > h["camera"]["look_at"][2]       # 俯拍


def test_deterministic_and_renders(tmp_path):
    assert json.dumps(_spec(2), sort_keys=True) == json.dumps(_spec(2), sort_keys=True)
    spec = _spec(2)
    AB.render_shot(spec, tmp_path, "S2", scale=0.1)
    assert (tmp_path / "S2_depth.png").is_file() and (tmp_path / "S2_preview.png").is_file()


def test_graph_without_previz_unchanged_and_with_previz_inserts_chain():
    base, _, _ = UF.build_graph({"prompt": "p", "refs": []}, 1, lambda f: "x.png", "t")
    assert not any(n["class_type"] == "ZImageFunControlnet" for n in base.values())
    job = {"prompt": "p", "refs": [], "previz": {"control": "data/previz/x.png", "strength": 0.55, "end_percent": 0.7}}
    wf, _, _ = UF.build_graph(job, 1, lambda f: "ctl.png", "t")
    cn = wf["202"]
    assert cn["class_type"] == "ZImageFunControlnet" and cn["inputs"]["model"] == base["13"]["inputs"]["model"]
    assert wf["13"]["inputs"]["model"] == ["202", 0] and cn["inputs"]["strength"] == 0.55
    assert wf["200"]["inputs"]["name"] == UF.FUN_CN_PATCH and wf["201"]["inputs"]["image"] == "ctl.png"
    assert base["13"]["inputs"]["model"] != ["202", 0]             # 原图未被改（不就地修改）


def test_turbo_previz_tier_and_fallback(monkeypatch, tmp_path):
    cfg = {"first_frame_tier": {"runs": {"r": "turbo_previz"}, "base35": {"unet": "base", "steps": 35, "cfg": 3.0},
                                "turbo_previz": {"unet": "turbo", "steps": 8, "cfg": 1.0, "dir": "data/previz",
                                                 "control": {"strength": 0.5, "end_percent": 0.8}}}}
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "render_quality.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(FJ, "_ROOT", tmp_path)
    assert FJ.first_frame_tier("r") == ("turbo_previz", {"unet": "turbo", "steps": 8, "cfg": 1.0})
    assert FJ.first_frame_tier("r", force="base35")[0] == "base35"
    assert FJ.previz_inputs("ep02-S3") is None                      # 没有深度图 → 退回
    d = tmp_path / "data/previz/ep02-S3/out"
    d.mkdir(parents=True)
    (d / "S3_depth.png").write_bytes(b"png")
    pv = FJ.previz_inputs("ep02-S3")
    assert pv["control"] == "data/previz/ep02-S3/out/S3_depth.png" and pv["strength"] == 0.5 and pv["end_percent"] == 0.8
    assert pv["start_percent"] == 0.0 and pv["shot_spec"] is None


def test_job_sig_includes_control_sha(monkeypatch, tmp_path):
    def sig(job):
        monkeypatch.setattr(PR, "jl", lambda p, d=None: {"jobs": [job]})

        class Paths:
            run = tmp_path
            root = tmp_path
        return PR.job_sig(Paths, "ep02-S1")
    base = {"shot": "ep02-S1", "prompt": "x", "compiler_inputs_sha": "a", "refs": []}
    s0 = sig(base)
    pa = {"sha": "aaa", "strength": 0.55, "end_percent": 0.7}
    sa, sb = sig({**base, "previz": pa}), sig({**base, "previz": {**pa, "sha": "bbb"}})
    assert len({s0, sa, sb}) == 3
    assert sig({**base}) == s0
