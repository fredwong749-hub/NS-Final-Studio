"""L-206 ②A（项目方 11-06 16:2x）：ep02 起首帧（与尾帧 compose）改 8 步 turbo + 摆位图（previz 深度控制），修订 L-191 base35；ep01 跑完作基线不动。
① 首帧档按集表（runs[剧] 字符串 / {default, from_episode}）；② 摆位图从导入稿字段确定性算、按输入哈希缓存、算不出退回裸 turbo（永不拦本集）；
③ 身份：turbo 作业的参考槽与 base35 完全同一套；④ 尾帧 compose 按落幅字段算自己的摆位图；⑤ 对照工具 dry 离线可跑。
全部 mock / 临时目录，不碰 GPU、不写真实 data/（真导入稿只读）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/autopilot", "tools/previz", "tools/research", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import auto_blocking as AB  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402
import producer as PR  # noqa: E402

SCRIPT = ROOT / "data/import/runs/series10_v2/script_v2.json"
needs_script = pytest.mark.skipif(not SCRIPT.exists(), reason="series10_v2 导入稿不在")

TIER_CFG = {"runs": {"series10_v2": {"default": "base35", "from_episode": {"2": "turbo_previz"}}},
            "base35": {"unet": "base", "steps": 35, "cfg": 3.0, "sampler": "euler", "scheduler": "simple"},
            "turbo": {"unet": "turbo", "steps": 8, "cfg": 1.0},
            "turbo_previz": {"unet": "turbo", "steps": 8, "cfg": 1.0, "dir": "data/previz",
                             "auto": {"enabled": True, "render_scale": 0.12},
                             "control": {"strength": 0.55, "start_percent": 0.0, "end_percent": 0.7},
                             "last_frame": {"previz": True}, "fallback": "turbo"}}


def _cfg_root(tmp_path, monkeypatch, tier_cfg=None):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "render_quality.json").write_text(json.dumps({"first_frame_tier": tier_cfg or TIER_CFG}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(FJ, "_ROOT", tmp_path)
    return tmp_path


def _script():
    from ns_schema.script import ScriptImport
    return ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))


# ---------------------------------------------------------------- ① 按集表
def test_tier_name_string_and_per_episode_table():
    assert FJ.tier_name("base35", 1) == "base35" and FJ.tier_name("base35", None) == "base35"      # L-191 旧写法原样
    t = {"default": "base35", "from_episode": {"2": "turbo_previz", "x": "bad", "4": "preview"}}
    assert FJ.tier_name(t, 1) == "base35" and FJ.tier_name(t, 2) == "turbo_previz" and FJ.tier_name(t, 3) == "turbo_previz"
    assert FJ.tier_name(t, 4) == "preview" and FJ.tier_name(t, None) == "base35"                    # 没给集号 → default
    assert FJ.tier_name(None, 2) == "preview" and FJ.tier_name(7, 2) == "preview" and FJ.tier_name({}, 2) == "preview"


def test_first_frame_tier_per_episode_and_turbo_fallback(tmp_path, monkeypatch):
    _cfg_root(tmp_path, monkeypatch)
    assert FJ.first_frame_tier("series10_v2", episode=1)[0] == "base35"
    assert FJ.first_frame_tier("series10_v2", episode=2) == ("turbo_previz", {"unet": "turbo", "steps": 8, "cfg": 1.0})
    assert FJ.first_frame_tier("series10_v2")[0] == "base35"                                         # 旧调用（没集号）= default
    assert FJ.first_frame_tier("series10_v2", force="turbo") == ("turbo", {"unet": "turbo", "steps": 8, "cfg": 1.0})
    assert FJ.first_frame_tier("other", episode=5) == ("preview", {})
    assert FJ.previz_fallback_tier() == "turbo"
    # 配置里没有 turbo 档 → 退路的采样参数取 turbo_previz 的
    cfg2 = {**TIER_CFG, "turbo": None}
    _cfg_root(tmp_path, monkeypatch, cfg2)
    assert FJ.first_frame_tier("series10_v2", force="turbo") == ("turbo", {"unet": "turbo", "steps": 8, "cfg": 1.0})


def test_live_config_ep01_baseline_ep02_turbo_previz():
    """真配置：ep01 base35 不动（跑完作基线），ep02 起 turbo_previz；尾帧跟同一张表"""
    assert FJ.first_frame_tier("series10_v2", episode=1)[0] == "base35"
    t, ov = FJ.first_frame_tier("series10_v2", episode=2)
    assert t == "turbo_previz" and ov == {"unet": "turbo", "steps": 8, "cfg": 1.0}
    assert FJ.first_frame_tier("series10_v2", episode=3)[0] == "turbo_previz"
    cfg = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))["first_frame_tier"]["turbo_previz"]
    assert cfg["auto"]["enabled"] is True and cfg["last_frame"]["previz"] is True and cfg["fallback"] == "turbo"


# ---------------------------------------------------------------- ② 摆位图：导入稿字段 → 确定性 → 缓存 → 失败退路
SHOT_OTS = {"index": 4, "img_prompt": "中近景，过肩略仰的机位，从卓琳右肩后方越过她的肩拍祁念，祁念站在白幕中央、在画面右侧偏中、脸在焦点上，卓琳背对镜头，卓琳的后脑与右肩在前景大幅虚化",
            "scene_id": "sk_white_cyc", "scene_detail": "【现实段】白幕前，环形灯架关着在右前景",
            "cast": [{"name": "卓琳", "presence": "局部", "x": "左", "depth": None, "part": "背影右肩"},
                     {"name": "祁念", "presence": "在画", "x": "右", "depth": "中", "part": None}],
            "extras": [{"label": "机位与景别", "text": "中近景｜从卓琳的右肩后方越过她的肩拍祁念、过肩略仰（A 区过肩位：相机与卓琳蹲姿的肩同高）｜祁念脸在焦点上"},
                       {"label": "光学", "text": "85mm｜T1.4｜高度=1.1m（卓琳蹲姿肩高）"},
                       {"label": "构图", "text": "前景=卓琳的右肩与后脑在左下｜背景=白幕中灰弧面"},
                       {"label": "分拍", "text": "0–2秒｜不影响摆位的字段"}]}
SHOT_HANDS = {"index": 6, "img_prompt": "大特写，俯拍桌面，祁念的右手从画面左侧探入，黎岸的右手从画面右上探入，一把钥匙", "scene_id": "sk_rooftop_bar",
              "scene_detail": "高圆桌桌面",
              "cast": [{"name": "祁念", "presence": "局部", "x": "左", "depth": None, "part": "右手"},
                       {"name": "黎岸", "presence": "局部", "x": "右", "depth": None, "part": "右手"}],
              "extras": [{"label": "机位与景别", "text": "大特写｜俯拍｜只拍两只手"}, {"label": "光学", "text": "100mm｜T2｜高度=1.5m"}]}
LOCKS = [{"name": "祁念", "description": "23岁成年女性，二十三岁｜高挑纤细、腿长｜雾蓝色及腰长直发、空气感碎刘海｜黑色漆皮"},
         {"name": "卓琳", "description": "35岁成年女性，三十五岁｜匀称干练｜黑色齐肩直发、中分｜酒红与黑"},
         {"name": "黎岸", "description": "45岁成年男性，四十五岁｜高大挺拔｜黑色背头｜黑色羊绒大衣"}]


def test_fields_from_shot_ots_partial_back_is_hidden_foreground_not_hands():
    """L-204 ①：cast 局部“背影右肩”= 在画不露脸的前景人（不是只拍手的插入镜）；蹲姿从“卓琳蹲姿”读到；分拍等字段不进输入"""
    f = AB.fields_from_shot(SHOT_OTS)
    assert set(f) == {"img", "机位与景别", "光学", "构图", "场景", "cast", "人物"} and f["场景"].startswith("sk_white_cyc｜")
    cast = AB.cast_from_locks(LOCKS)
    assert cast["卓琳"] == {"sex": "女", "height": 1.65, "hair": "bob"} and cast["黎岸"]["height"] == 1.85
    ppl = {p["name"]: p for p in AB.parse_people(f, cast)}
    assert ppl["卓琳"]["presence"] == "in" and ppl["卓琳"]["hidden"] and ppl["卓琳"]["part"] == "右肩"
    assert ppl["祁念"]["presence"] == "in" and not ppl["祁念"]["hidden"]
    spec = AB.auto_blocking(4, f, cast)
    a = {x["id"]: x for x in spec["actors"]}
    assert spec["name"] == "S4 auto" and set(a) == {"卓琳", "祁念"}
    assert a["卓琳"]["pose"] == "seated" and a["祁念"]["pose"] == "standing"           # “蹲在祁念的左前方”不把祁念算成蹲
    assert a["卓琳"]["pos"][1] < a["祁念"]["pos"][1] and a["卓琳"]["pos"][0] < 0 < a["祁念"]["pos"][0]
    assert spec["meta"]["angle"]["azimuth"] == "ots" and spec["camera"]["focal_mm"] == 85
    h = AB.auto_blocking(6, AB.fields_from_shot(SHOT_HANDS), cast)
    assert h["name"] == "S6 hands insert" and h["actors"] == []


def test_ensure_previz_deterministic_cache_and_full_size(tmp_path):
    cast = AB.cast_from_locks(LOCKS)
    f = AB.fields_from_shot(SHOT_OTS)
    r1 = AB.ensure_previz("ep02-S4", f, cast, root=tmp_path, scale=0.12)
    assert r1["cached"] is False and r1["seconds"] is not None and r1["depth"].is_file() and r1["spec"].is_file() and r1["preview"].is_file()
    assert r1["dir"] == tmp_path / "data/previz/ep02-S4/auto" / r1["inputs_sha"][:12]
    from PIL import Image
    assert Image.open(r1["depth"]).size == (1152, 2016)                                   # 小图渲染、放大回出图尺寸
    r2 = AB.ensure_previz("ep02-S4", f, cast, root=tmp_path, scale=0.12)
    assert r2["cached"] is True and r2["dir"] == r1["dir"] and r2["inputs_sha"] == r1["inputs_sha"]
    # 不影响摆位的字段变了 → 哈希不变；景别变了 → 另一个缓存目录
    f_same = {**f, "img": f["img"]}
    assert AB.inputs_sha(f_same, cast, 0.12) == r1["inputs_sha"]
    f2 = {**f, "机位与景别": f["机位与景别"].replace("中近景", "近景")}
    assert AB.inputs_sha(f2, cast, 0.12) != r1["inputs_sha"]
    r3 = AB.ensure_previz("ep02-S4", f, cast, root=tmp_path, scale=0.12, stage="last")
    assert r3["dir"].parent.name == "auto_last" and r3["cached"] is False
    with pytest.raises(ValueError):
        AB.ensure_previz("bad", f, cast, root=tmp_path)


def test_previz_inputs_auto_and_manual(tmp_path, monkeypatch):
    _cfg_root(tmp_path, monkeypatch)
    g = {"character_locks": LOCKS}
    pv = FJ.previz_inputs("ep02-S4", shot=SHOT_OTS, g=g)
    assert pv["control"] == f"data/previz/ep02-S4/auto/{pv['sha'][:12]}/S4_depth.png" and (tmp_path / pv["control"]).is_file()
    assert pv["auto"]["stage"] == "first" and pv["auto"]["cached"] is False and pv["strength"] == 0.55 and pv["end_percent"] == 0.7
    assert len(pv["sha"]) == 16 and pv["file_sha"] and pv["shot_spec"]
    pv2 = FJ.previz_inputs("ep02-S4", shot=SHOT_OTS, g=g)
    assert pv2["sha"] == pv["sha"] and pv2["auto"]["cached"] is True
    assert FJ.previz_inputs("ep02-S9") is None                                              # 没给 shot → 手工图路径，没有 → None
    assert FJ.previz_inputs("nonsense", shot=SHOT_OTS, g=g) is None


def test_previz_or_none_never_raises(tmp_path, monkeypatch):
    _cfg_root(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("numpy 炸了")
    monkeypatch.setattr(FJ, "_auto_previz", boom)
    pv, why = FJ.previz_or_none("ep02-S4", SHOT_OTS, {"character_locks": LOCKS})
    assert pv is None and "RuntimeError" in why and "numpy 炸了" in why
    cfg = json.loads(json.dumps(TIER_CFG))
    cfg["turbo_previz"]["last_frame"]["previz"] = False
    _cfg_root(tmp_path, monkeypatch, cfg)
    pv, why = FJ.previz_or_none("ep02-S4", SHOT_OTS, {"character_locks": LOCKS}, stage="last")
    assert pv is None and "last_frame.previz=off" in why


@needs_script
def test_build_first_turbo_previz_and_fallback_to_plain_turbo(tmp_path, monkeypatch):
    """ep02 作业：turbo_previz + 摆位图；摆位图炸了 → 裸 turbo（同采样、无控制图、previz_missing 记原因），作业照样编出来"""
    from ns_render import pipeline as P
    _cfg_root(tmp_path, monkeypatch)
    sc = _script()
    ep, shot = P.find_shot(sc, "ep02-S1")
    job = FJ.build_first("series10_v2", ep, shot, sc.globals)
    assert job["tier"] == "turbo_previz" and job["tier_overrides"] == {"unet": "turbo", "steps": 8, "cfg": 1.0}
    assert job["previz"]["control"].startswith("data/previz/ep02-S1/auto/") and "previz_missing" not in job
    assert job["previz"]["auto"]["stage"] == "first"

    def boom(*a, **k):
        raise OSError("磁盘满")
    monkeypatch.setattr(FJ, "_auto_previz", boom)
    job2 = FJ.build_first("series10_v2", ep, shot, sc.globals)
    assert job2["tier"] == "turbo" and job2["tier_overrides"] == {"unet": "turbo", "steps": 8, "cfg": 1.0}
    assert "previz" not in job2 and "OSError" in job2["previz_missing"]
    assert job2["prompt"] == job["prompt"] and job2["refs"] == job["refs"]
    # ep01 不动：base35、没有摆位图
    ep1, shot1 = P.find_shot(sc, "ep01-S1")
    j1 = FJ.build_first("series10_v2", ep1, shot1, sc.globals)
    assert j1["tier"] == "base35" and "previz" not in j1 and "previz_missing" not in j1


# ---------------------------------------------------------------- ③ 身份：参考槽同一套
@needs_script
def test_identity_refs_identical_between_base35_and_turbo_previz(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    sc = _script()
    ep, shot = P.find_shot(sc, "ep02-S1")
    _cfg_root(tmp_path, monkeypatch, {**TIER_CFG, "runs": {"series10_v2": "base35"}})
    jb = FJ.build_first("series10_v2", ep, shot, sc.globals)
    _cfg_root(tmp_path, monkeypatch)
    jt = FJ.build_first("series10_v2", ep, shot, sc.globals)
    assert jb["tier"] == "base35" and jt["tier"] == "turbo_previz"
    assert jb["refs"] == jt["refs"] and jb["face_files"] == jt["face_files"] and jb["prompt"] == jt["prompt"]
    assert jb["asset_refs"]["slots"] == jt["asset_refs"]["slots"] and jb["compile_trace"]["faces"] == jt["compile_trace"]["faces"]
    assert jt["face_files"], "ep02-S1 祁念在画 → 必须送身份脸"
    # 图：ControlNet 节点插进模型链，参考图节点（image_1..n）一个不少、提示词编码不变
    wf_b, eff_b, sent_b = UF.build_graph(jb, 1, lambda f: Path(f).name, "t")
    wf_t, eff_t, sent_t = UF.build_graph(jt, 1, lambda f: Path(f).name, "t")
    assert eff_t["steps"] == 8 and eff_t["unet"] == "turbo" and eff_b["steps"] == 35
    assert sent_b == sent_t and wf_t["202"]["class_type"] == "ZImageFunControlnet" and wf_t["13"]["inputs"]["model"] == ["202", 0]
    loads = lambda wf: sorted(n["inputs"]["image"] for n in wf.values() if n.get("class_type") == "LoadImage")  # noqa: E731
    assert set(loads(wf_b)) <= set(loads(wf_t)) and len(loads(wf_t)) == len(loads(wf_b)) + 1       # 多的那张就是控制图


# ---------------------------------------------------------------- ④ 尾帧 compose 自己的摆位图
@needs_script
def test_last_compose_gets_end_framing_previz_or_plain_turbo(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "compose")
    _cfg_root(tmp_path, monkeypatch)
    sc = _script()
    ep, shot = P.find_shot(sc, "ep02-S1")
    first = FJ.build_first("series10_v2", ep, shot, sc.globals)
    last = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=sc.globals)
    assert last["last_frame_mode"] == "compose" and last["tier"] == "turbo_previz"
    assert last["previz"]["auto"]["stage"] == "last" and last["previz"]["sha"] != first["previz"]["sha"]
    assert last["previz"]["control"].startswith("data/previz/ep02-S1/auto_last/") and "previz_missing" not in last
    spec = json.loads((tmp_path / last["previz"]["auto"]["dir"] / "S1.json").read_text(encoding="utf-8"))
    assert spec["meta"]["size"] == FJ.last_angle_field(shot, last["end_framing"]).split("｜")[0]      # 尾帧摆位图按落幅的景别
    assert last["end_framing"] and last["prompt"] != first["prompt"]                        # 落幅经模板 v2 重编，不逐字出现
    cfg = json.loads(json.dumps(TIER_CFG))
    cfg["turbo_previz"]["last_frame"]["previz"] = False
    _cfg_root(tmp_path, monkeypatch, cfg)
    last2 = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=sc.globals)
    assert last2["tier"] == "turbo" and "previz" not in last2 and "last_frame.previz=off" in last2["previz_missing"]


# ---------------------------------------------------------------- 签名 / 重出判定认输入哈希
def test_job_sig_follows_previz_input_sha_not_timing(monkeypatch, tmp_path):
    def sig(job):
        monkeypatch.setattr(PR, "jl", lambda p, d=None: {"jobs": [job]})

        class Paths:
            run = tmp_path
            root = tmp_path
        return PR.job_sig(Paths, "ep02-S1")
    base = {"shot": "ep02-S1", "prompt": "x", "compiler_inputs_sha": "a", "refs": [], "tier": "turbo_previz", "tier_overrides": {"steps": 8}}
    pa = {"sha": "aaa", "strength": 0.55, "start_percent": 0.0, "end_percent": 0.7, "auto": {"seconds": 1.0, "cached": False}}
    pb = {**pa, "auto": {"seconds": 9.0, "cached": True}}
    assert sig({**base, "previz": pa}) == sig({**base, "previz": pb})
    assert sig({**base, "previz": pa}) != sig({**base, "previz": {**pa, "sha": "bbb"}})
    assert sig({**base, "previz": pa}) != sig({**base, "tier": "turbo"})                     # 退路（裸 turbo）≠ 带控制图


# ---------------------------------------------------------------- ⑤ 对照工具离线
@needs_script
def test_ab_tool_dry_runs_offline(tmp_path, monkeypatch):
    import turbo_previz_ab as T
    _cfg_root(tmp_path, monkeypatch)                                    # 摆位图缓存进临时目录
    monkeypatch.setattr(T, "exp_dir", lambda exp: tmp_path / "ab" / exp)
    monkeypatch.setattr(T, "base_take", lambda sid: {"n": 3, "active": True, "file": "renders/x.png", "seconds": 60.1, "tier": "base35",
                                                     "q1": {"status": "pass", "sims": {"lead_f": 0.51}, "faces": 1, "strangers": 0}, "seed": 1})
    doc = T.dry(["ep01-S4"], 0.55, 0.7, "tp_test", seeds_n=2)
    it = doc["items"][0]
    assert it["graph_ok"] and it["steps"] == 8 and it["unet"] == "turbo" and it["preflight_ok"], it["preflight_reasons"]
    assert it["seeds"] == [20641, 20642] and it["previz_s"] is not None and it["angle"]["azimuth"] == "ots" and it["tier_now"] == "base35"
    assert (tmp_path / "ab/tp_test/dry/jobs.json").is_file() and (tmp_path / "ab/tp_test/dry/previz_sheet.jpg").is_file()
    assert T.seeds_for("ep01-S1", 2) == [20611, 20612]
    assert T.q1_of({"items": [{"id": "Q1", "status": "pass", "evidence": {"sims": {"a": 0.7, "b": None}, "faces": 2}}]}) == \
        {"status": "pass", "sims": {"a": 0.7}, "faces": 2, "strangers": 0}
