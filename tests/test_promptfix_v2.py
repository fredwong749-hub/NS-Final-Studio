"""PROMPTFIX 11-02 19:1x（L-125 / L-126 V2 完全切割）：编译层接 V2 资产包。
I-14 按剧取路径（run_paths）、K-REN-958 造型封闭 + 本地专用资产只许本地道、K-REN-959 品牌字样。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import run_paths as RP  # noqa: E402

V2 = "series10_v2"
need_v2 = pytest.mark.skipif(not AR.manifest_rel(V2) or not (ROOT / AR.manifest_rel(V2)).is_file(), reason="V2 资产包清单缺")


def _golden(monkeypatch):
    """golden_v2 必须指定镜号（ISS-1103-005000-2af2）：取当前剧第 1 集里第一个 golden 认的女主单人镜（非成人），不写死镜号"""
    sys.path.insert(0, str(ROOT / "tools" / "promptfix"))
    import golden_v2 as GV
    from ns_agent import cast_table as CT
    lead = CT.lead_id()
    names = (CT.speaker_cast(V2) or {}).get("names") or {}
    for n in range(1, 60):
        try:
            _s, _e, sh = GV.load_imported(n)
        except (SystemExit, StopIteration):
            continue
        if {names.get(c.name, c.name) for c in sh.cast if c.visible} != {lead}:   # 金样口径：女主单人镜
            continue
        monkeypatch.setattr(GV, "SHOT", n)
        monkeypatch.setattr(GV, "SID", f"{V2}-ep01-S{n}")
        return GV
    pytest.skip("当前剧第 1 集没有 golden 可出的镜")


# ---------------------------------------------------------------- I-14 run_paths
def test_run_paths_sandbox_is_legacy(tmp_path):
    assert RP.script_json(tmp_path) == tmp_path / "data/import/script_v2.json"
    assert RP.looks_dir(tmp_path) == tmp_path / "data/looks"
    assert RP.renders_dir(tmp_path) == tmp_path / "data/renders"


def test_run_paths_v2_never_resolves_v1(tmp_path, monkeypatch):
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    (tmp_path / "tools/autopilot/runs.py").write_text((ROOT / "tools/autopilot/runs.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({
        "legacy_unprefixed_run": "series10_v1", "primary": "series10_v2",
        "runs": {"series10_v1": {"status": "paused"}, "series10_v2": {"status": "producing", "assets_manifest": "assets_v2/manifest.json"}}}),
        encoding="utf-8")
    monkeypatch.delenv("NS_SCRIPT_JSON", raising=False)
    monkeypatch.delenv("NS_RENDERS_DIR", raising=False)
    monkeypatch.delenv("NS_RUN", raising=False)
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)
    RP._runs_mod.cache_clear()
    try:
        r = RP.current_run(tmp_path)
        assert r == "series10_v2"
        assert RP.script_json(tmp_path) == tmp_path / "data/import/runs/series10_v2/script_v2.json"
        assert RP.looks_dir(tmp_path) != tmp_path / "data/looks"
        assert RP.renders_dir(tmp_path) == tmp_path / "data/renders/series10_v2"
        monkeypatch.setenv("NS_RUN", "series10_v1")
        assert RP.looks_dir(tmp_path) == tmp_path / "data/looks"        # V1 自己照旧
    finally:
        RP._runs_mod.cache_clear()


def test_no_hard_v1_paths_left_in_compile_modules():
    import re
    pat = re.compile(r'"data"\s*/\s*"import"\s*/\s*"script_v2\.json"|"data"\s*/\s*"looks"(?!\s*\))|"data"\s*/\s*"renders"')
    for f in ("compiler.py", "frame_spec.py", "bible.py", "state_timeline.py", "asset_revs.py", "lora_registry.py",
              "prompt_snapshot.py", "framing.py"):
        src = (ROOT / "services/agent/ns_agent" / f).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert not pat.search(code), f"{f} 仍写死 V1 路径"


# ---------------------------------------------------------------- K-REN-958 造型封闭 + 本地专用
@need_v2
def test_lead_f_looks_closed_and_routes():
    cl = AR.closed_looks(V2)
    assert cl.get("lead_f") == {"O1", "O2", "O3", "O4"}
    meta = AR.manifest_meta(V2)
    assert meta["look:lead_f:O2"]["route"] == "local_only" and meta["look:lead_f:O3"]["route"] == "local_only"
    assert meta["look:lead_f:O1"]["route"] == "server_ok"
    assert meta["item:lead_f:J1"]["route"] == "local_only" and meta["item:lead_f:J2"]["route"] == "local_only"
    assert meta["item:lead_f:SH2"]["no_brand"]


class _SR:
    def __init__(self, chars):
        self.characters = chars


class _Slot:
    def __init__(self, file, members=None):
        self.file, self.members = file, members or [{"file": file}]


class _Plan:
    def __init__(self, slots):
        self.slots = slots


@need_v2
def test_plan_route_local_only_from_look_and_board_member():
    meta = AR.manifest_meta(V2)
    j1_file = next(f for f, m in meta.items() if not f.startswith(("item:", "look:")) and m.get("item") == "J1")
    r, why = AR.plan_route(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O2"}]), _Plan([]))
    assert r == "local_only" and "O2" in why[0]
    r, why = AR.plan_route(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O1"}]),
                           _Plan([_Slot("data/pipeline/runs/series10_v2/images/refboards/board_x.png",
                                        [{"file": "x.png"}, {"file": j1_file}])]))
    assert r == "local_only"                                         # 参考板里任何一格是本地专用 → 整镜本地
    r, why = AR.plan_route(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O4"}]), _Plan([]))
    assert r == "server_ok" and not why


def _pf(req):
    from ns_agent.gen_contract import preflight as PF
    base = {"kind": "image", "model": "qwen_image_2.1", "cast": [], "prompt": "近景构图，女主站在窗边", "refs": [],
            "asset_refs": {"slots": [], "characters": []}, "loras": [], "compiled_by": "ns_agent.frame_job.build_first",
            "project": V2, "framing_project": V2, "shot_id": "ep01-S1"}
    base.update(req)
    return {i.id: i for i in PF.check(base).items}


@need_v2
def test_preflight_i12_blocks_local_only_on_server():
    # L-128：gpu33 / gpu36 / 笔记本都是项目方自有机器（hosts.json owner_controlled=true）→ 放行；不认识的机器 / 没给道 → 挡
    assert _pf({"route": "local_only", "route_reasons": ["女主 造型 O2"], "lane": "gpu36:1"})["I12"].status == "pass"
    assert _pf({"route": "local_only", "route_reasons": ["x"], "lane": "laptop:0"})["I12"].status == "pass"
    assert _pf({"route": "local_only", "route_reasons": ["x"], "lane": "rented99:0"})["I12"].status == "fail"
    assert _pf({"route": "local_only", "route_reasons": ["x"]})["I12"].status == "fail"          # 没给道 = 失败关闭
    assert _pf({"route": "server_ok", "lane": "rented99:0"})["I12"].status == "pass"


@need_v2
def test_plan_adult_marks_owner_trigger_only():
    sr = _SR([{"character": "lead_f", "name": "女主", "look": "O3"}])
    assert AR.plan_adult(V2, sr, _Plan([]))
    assert not AR.plan_adult(V2, _SR([{"character": "lead_f", "name": "女主", "look": "O1"}]), _Plan([]))


def test_producer_blocks_adult_job_without_owner_trigger():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert 'if job.get("adult") and not ({f"first:{sid}", f"{self.p.run_id}/first:{sid}"} & trig)' in src   # FACTORY 19:4x：原写法引用了未定义的 o（syntax_guard E3）


# ---------------------------------------------------------------- K-REN-959 品牌字样
def test_brand_hits():
    assert AR.brand_hits("黑色漆皮细带露趾高跟凉鞋（脚踝扣带）") == []
    assert "Louboutin" in AR.brand_hits("穿 Louboutin 红底鞋")
    assert AR.brand_hits("SLV 款") == [] and "LV" in AR.brand_hits("手拿 LV 包")


@need_v2
def test_preflight_i13_blocks_brand_words():
    assert _pf({"prompt": "女主穿 Christian Louboutin 高跟鞋"})["I13"].status == "fail"
    assert _pf({"prompt": "女主穿黑色漆皮细带露趾高跟凉鞋"})["I13"].status == "pass"


@need_v2
def test_no_brand_slot_line():
    meta = AR.manifest_meta(V2)
    sh2 = next(f for f, m in meta.items() if not f.startswith(("item:", "look:")) and m.get("item") == "SH2")
    sr = AR.ShotRefs("ep01-S1", V2, "全景", None, ["feet"], "lead_f", [{"character": "lead_f", "name": "女主", "presence": "在画"}],
                     [AR.Ref("item", "lead_f", sh2, "鞋：黑色漆皮细带露趾高跟凉鞋", 2, "feet", "manifest", "SH2", "O4")], [], [])
    plan = AR.plan_slots(sr, capacity=3)
    assert "没有任何标志和文字" in plan.slots[0].line          # W-40 起句尾还接 render_prompt（普通细跟…），不再只是 NO_BRAND_NOTE
    assert not AR.brand_hits(plan.prompt_prefix)


# ---------------------------------------------------------------- 派生参考图 sha 账本（总调度 20:10 ②）
def test_derived_index_server_rejects_unrecorded_or_tampered(tmp_path, monkeypatch):
    from PIL import Image
    f = tmp_path / "board_x.png"
    Image.new("RGB", (8, 8), "white").save(f)
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")                 # 模拟服务器
    with pytest.raises(AR.DerivedRefMissing):
        AR._derived_on_server(f)                                 # 没登记 → 挡
    monkeypatch.delenv("OFFLINE_SELF")
    AR.record_derived(f, V2)                                     # 笔记本生成时登记（V2 在制作中，允许写）
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert AR._derived_on_server(f)                              # 登记且 sha 对 → 用
    Image.new("RGB", (8, 8), "black").save(f)                    # 字节变了（服务器本地重生成 / 推送损坏）
    with pytest.raises(AR.DerivedRefMissing):
        AR._derived_on_server(f)
    monkeypatch.delenv("OFFLINE_SELF")
    with pytest.raises(AR.DerivedRefMissing):
        monkeypatch.setenv("NS_FACTORY_HOST", "gpu33")
        AR._derived_on_server(tmp_path / "board_missing.png")   # 服务器上没有 → 挡，不生成


@need_v2
def test_manifest_violations_check_sha_and_derived_index():
    face = AR.face_of(V2, "lead_f")
    assert face and AR.manifest_violations(V2, [face]) == []
    assert AR.manifest_violations(V2, ["assets/characters/lin_wan/refs/lin_wan/ar-c2351c9dcf.png"])      # V1 脸 → 挡
    pc = AR.project_cfg(V2)
    assert AR.manifest_violations(V2, [pc["board_dir"].rstrip("/") + "/board_not_recorded.png"])          # 没登记的派生图 → 挡


@need_v2
def test_manifest_allows_own_video_inputs_only():
    """W41：视频首帧输入 JPEG（本剧 video/inputs/）不挡 I11；别的剧的 video/inputs 照挡"""
    assert AR.manifest_violations(V2, [f"data/pipeline/runs/{V2}/video/inputs/ep01-S10_1ecbaecd.jpg"]) == []
    assert AR.manifest_violations(V2, ["data/pipeline/runs/series10_v1/video/inputs/ep01-S10_084acef2.jpg"])
    assert AR.manifest_violations(V2, [f"data/pipeline/runs/{V2}/video/clips/x.jpg"])


@need_v2
def test_v2_manifest_names_and_looks():
    AR.register_manifest_names(V2)
    assert AR.NAME_ID.get("女主") == "lead_f" or AR.NAME_ID.get(AR.ID_NAME.get("lead_f")) == "lead_f"
    lk = AR.load_looks(V2).get("lead_f") or {}
    assert set(lk) >= {"O1", "O4"}
    assert any(p.item_id == "O1_garment" for p in lk["O1"].parts)


# ---------------------------------------------------------------- OVERSIGHT-F P1-5a / P1-5b：V2 不带 V1 人物 / 项目
@pytest.fixture
def v2_env(monkeypatch):
    monkeypatch.setenv("NS_RUN", V2)
    monkeypatch.setenv("NS_PRIMARY_RUN", V2)
    yield


@need_v2
def test_p15b_she_resolves_to_lead_f(v2_env):
    from ns_agent import cast_table as CT
    from ns_agent import frame_spec as FS
    from ns_agent import gpu3_fields as G3
    assert CT.lead_id() == "lead_f" and "lead_f" in CT.female_ids()
    m = FS.mentions()
    assert all("林晚" not in k and "顾沉" not in k for k in m)            # 不带 V1 人物
    assert any("她" in ws for ws in m.values())
    found = FS.resolve_characters("中近景，她站在江边", "她望向对岸")
    assert [AR.NAME_ID.get(k, k) for k in found] == ["lead_f"]
    assert G3.who("她的风衣被风吹起", 2, ["lead_f"])[0] == "lead_f"


@need_v2
def test_p15b_v2_compile_refs_all_from_assets_v2(v2_env, monkeypatch):
    GV = _golden(monkeypatch)
    job = GV.compile_job()
    assert job["compile_trace"]["faces"] == ["lead_f"]
    # W13 CUTB-PREP 11-03：数据态陈旧（不是放宽）。原断言“全部以 assets_v2/ 开头”写于 03:08，那时 O4 还没设定图；
    # O4 设定图登记后 asset_refs.sheet_crop 会按本剧 crop_dir 裁去头半身参考（源图仍在 assets_v2）。性质：每张参考要么在
    # assets_v2/，要么在 V2 自己的派生目录（crop_dir / board_dir，= preflight I11 认的同一口径），不进任何别剧目录。
    pc = AR.project_cfg(V2)
    own = ("assets_v2/",) + tuple(str(x).rstrip("/") + "/" for x in (pc.get("crop_dir"), pc.get("board_dir")) if x)
    assert all(V2 in o for o in own[1:]), own                                    # 派生目录确是本剧的
    assert job["refs"] and all(str(f).startswith(own) for f in job["refs"]), job["refs"]
    assert not [f for f in job["refs"] if "series10_v1" in str(f) or str(f).startswith("data/refcrops")], job["refs"]
    assert "lin_wan" not in json.dumps(job["asset_refs"], ensure_ascii=False)


def test_p15a_edit_project_follows_run(v2_env, monkeypatch):
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from ns_api import edits as E
    assert E.edit_project() == V2
    with pytest.raises(ValueError):
        E.edit_project("no_such_run")
    assert "project" not in E.engines_cfg() or not E.engines_cfg().get("project")


# ---------------------------------------------------------------- P1-6b 统一写入口守卫：不在制作中的剧一律只读
def test_p16b_derived_write_guard_by_run_status(tmp_path):
    assert AR.derived_writable(V2)                               # preparing
    assert not AR.derived_writable("series10_v1")                # archived
    assert not AR.derived_writable("series10_s2")                # paused
    assert not AR.derived_writable("no_such_run")                # 没登记 = 失败关闭
    v1_target = ROOT / "data/pipeline/runs/series10_v1/images/refcrops/p16b_guard_probe.png"   # 不存在；守卫在读写之前就拦
    with pytest.raises(AR.DerivedWriteRefused):
        AR.record_derived(v1_target, "series10_v1")
    assert not v1_target.exists()
    f = tmp_path / "x.png"                                       # 仓库外（测试临时目录）：不按剧名一刀切，照常可写
    f.write_bytes(b"x")
    AR.record_derived(f, "series10_v1")
    assert (tmp_path / AR.DERIVED_INDEX).exists()


def test_p16b_make_board_refuses_new_board_for_archived_run(monkeypatch):
    v1_face = "assets/characters/lin_wan/refs/lin_wan/ar-c2351c9dcf.png"
    if not (ROOT / v1_face).is_file():
        pytest.skip("V1 身份脸不在")
    with pytest.raises(AR.DerivedWriteRefused):
        AR.make_board("series10_v1", [(v1_face, "p16b-guard-test-unique-label")])


# ---------------------------------------------------------------- V1 风格后缀不进 V2（总调度 20:4x，L-126）
@need_v2
def test_v2_style_suffix_from_run_style_not_v1(v2_env, monkeypatch):
    from ns_agent.gen_contract import style as ST
    suf = ST.preset_suffix()
    assert suf and not ST.v1_style_hits(suf) and "时尚杂志大片质感，色彩艳丽、浓郁、高饱和" not in suf   # L-130：临时句已换掉
    assert not ST.banned_hits(suf)
    monkeypatch.setattr(ST, "run_style_cfg", lambda: {})
    with pytest.raises(ST.StyleMissing):                          # V2 没登记风格 → 失败关闭，不退回 S★
        ST.preset_suffix()


@need_v2
def test_v2_compiled_prompt_has_no_v1_style(v2_env, monkeypatch):
    GV = _golden(monkeypatch)
    from ns_agent.gen_contract import style as ST
    job = GV.compile_job()
    assert not ST.v1_style_hits(job["prompt"]), ST.v1_style_hits(job["prompt"])
    # ⤴ L-145（项目方 11-03 04:3x“徕卡级锐利风格是我要的”）：V2 后缀用英文 Leica / ARRI / Kodak 质感句；V1 S★ 原句（中文徕卡 / 50mm f/2 / 暖调通透）照挡
    assert "徕卡" not in job["prompt"] and "50mm f/2" not in job["prompt"] and "暖调通透" not in job["prompt"]
    assert any(x in job["prompt"] for x in ST.run_suffixes())          # 分段剧：本镜那一段的风格句（L-130）


@need_v2
def test_v2_preflight_blocks_v1_style_phrase(v2_env):
    from ns_agent.gen_contract import style as ST
    v1 = "专业电影画面，徕卡M 50mm f/2镜头，焦点锐利，微反差强，暖调通透，干净真实"
    it = _pf({"prompt": "近景构图，女主站在窗边，" + v1 + "，" + ST.preset_suffix() + "，无字幕、无文字、无水印"})
    assert it["I7"].status == "fail" and "V1 风格短语" in it["I7"].detail


def test_v1_leak_vocab_has_style_phrases():
    sys.path.insert(0, str(ROOT / "tools" / "script_rsi"))
    import v1_leak as VL
    v = VL.vocab(ROOT, "series10_v2")
    assert "徕卡" in v["style"] and "暖调通透" in v["style"]
    assert any(h["kind"] == "style" for h in VL.scan("徕卡M 50mm f/2镜头，暖调通透", v))


# ---------------------------------------------------------------- V2 编译完全不读 V1 visual_bible（总调度 21:1x，L-126）
@need_v2
def test_v2_compile_never_opens_v1_visual_bible(v2_env, monkeypatch):
    from ns_agent import bible as B
    B._BIBLE_CACHE.clear()
    B._SRC_CACHE.clear()
    opened = []
    real_rt, real_rb = Path.read_text, Path.read_bytes

    def rt(self, *a, **k):
        opened.append(str(self))
        return real_rt(self, *a, **k)

    def rb(self, *a, **k):
        opened.append(str(self))
        return real_rb(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", rt)
    monkeypatch.setattr(Path, "read_bytes", rb)
    GV = _golden(monkeypatch)
    job = GV.compile_job()
    assert not [f for f in opened if f.replace("\\", "/").endswith("config/visual_bible.toml")]
    assert any(f.replace("\\", "/").endswith("config/compile/bible_series10_v2.toml") for f in opened)
    p = job["prompt"]
    assert "光比1:4" not in p                                      # V1 布光风格去掉
    assert "面部清晰对焦" in p                                      # 技术句保留（来自 V2 自己的规则文件；漆皮句随镜头内容触发，金样已不写死服装）
    B._BIBLE_CACHE.clear()
    B._SRC_CACHE.clear()


@need_v2
def test_v2_bible_missing_entry_fails_closed(v2_env, monkeypatch, tmp_path):
    from ns_agent import bible as B
    rs = json.loads((ROOT / "config/compile/run_style.json").read_text(encoding="utf-8"))
    assert rs["runs"][V2]["bible"] == "config/compile/bible_series10_v2.toml"
    b = B.load_bible(ROOT)
    assert not b.characters and "光比" not in "".join(r.term for r in b.shot_rules)
    assert all("Leica" not in x for x in (b.image_style_fallback, b.video_style))


# ---------------------------------------------------------------- W-40：SH2 品牌 logo 永远不进出图
@need_v2
def test_w40_sh2_uses_render_reference_not_logo_original():
    mf = json.loads((ROOT / AR.manifest_rel(V2)).read_text(encoding="utf-8"))
    sh2 = mf["characters"]["lead_f"]["items"]["SH2"]
    assert sh2.get("render_file") and sh2["render_file"] != sh2["file"]
    assert AR.item_image("SH2", V2) == sh2["render_file"]                 # 出图用去 logo 的版本
    assert AR.manifest_violations(V2, [sh2["file"]])                      # 带 logo 的原图不许进参考槽
    assert AR.manifest_violations(V2, [sh2["render_file"]]) == []


@need_v2
def test_w40_slot_line_negative_and_vqa_check():
    sh2 = AR.item_image("SH2", V2)
    sr = AR.ShotRefs("ep01-S1", V2, "全景", None, ["feet"], "lead_f", [{"character": "lead_f", "name": "女主", "presence": "在画"}],
                     [AR.Ref("item", "lead_f", sh2, "鞋：黑色漆皮细带露趾高跟凉鞋", 2, "feet", "manifest", "SH2", "O4")], [], [])
    plan = AR.plan_slots(sr, capacity=3)
    assert "普通细跟" in plan.slots[0].line and "没有任何标志和文字" in plan.slots[0].line
    assert "品牌logo" in AR.brand_negative(V2, plan)
    vq = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    assert vq["checks"]["brand_logo"]["blocking"] is True
    assert '"brand_logo"' in (ROOT / "config/prompts/vqa_inspect.md").read_text(encoding="utf-8")


def test_w40_negative_reaches_graph_only_when_cfg_above_one():
    from ns_render import workflows as W
    m = W.QwenModel()
    neg = W.negative_for(m, "品牌logo")
    assert neg == ("" if W.effective_cfg(m) <= 1.0 else "品牌logo")      # Turbo cfg=1 丢负面词：所以主防线是参考图 + 正向句 + 出图后判



# ---------------------------------------------------------------- L-130：幻想段 / 现实段风格按段取
@need_v2
def test_l130_segment_styles(v2_env):
    from ns_agent.gen_contract import style as ST
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    by = {p["id"]: p["params"]["style_suffix"] for p in rq["image_presets"] if p["id"].startswith("v2_editorial")}
    fan, rea = by["v2_editorial_fantasy_c"], by["v2_editorial_reality_c2"]
    assert ST.preset_suffix(V2, "fantasy") == fan and ST.preset_suffix(V2, "reality") == rea
    assert ST.preset_suffix(V2, None) == rea                                   # 没标记 → 默认现实段
    assert ST.segment_of({"scene_detail": "【幻想段】外滩日落"})[0] == "fantasy"
    assert ST.segment_of({"img_prompt": "【现实段】出租屋"})[0] == "reality"
    assert ST.segment_of({"img_prompt": "中景，她坐着"})[0] is None
    assert set(ST.run_suffixes(V2)) == {fan, rea}


@need_v2
def test_l130_compiled_prompt_by_segment(v2_env, monkeypatch):
    """同一镜：场景细节标【幻想段】→ 幻想段预设、标记不进提示词；没标记 → 现实段 + 告警（镜头取当前剧导入稿，不用夹具）"""
    GV = _golden(monkeypatch)
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import style as ST
    sc, ep, sh = GV.load_imported(GV.SHOT)
    base = (sh.scene_detail or "").replace("【幻想段】", "").replace("【现实段】", "")
    job = FJ.build_first(V2, ep, sh.model_copy(update={"scene_detail": "【幻想段】" + base}), sc.globals)
    assert job["preset"] == "v2_editorial_fantasy_c" and job["style_segment"] == "fantasy" and not job["style_warning"]
    assert ST.preset_suffix(V2, "fantasy") in job["prompt"]
    assert "时尚杂志大片质感，色彩艳丽、浓郁、高饱和" not in job["prompt"]
    job2 = FJ.build_first(V2, ep, sh.model_copy(update={"scene_detail": base}), sc.globals)
    assert job2["style_segment"] == "reality" and job2["style_warning"]
    assert ST.preset_suffix(V2, "reality") in job2["prompt"]
    i7 = next(i for i in GV.preflight(job2, "gpu33:0").items if i.id == "I7")
    assert i7.status == "pass", i7.detail


@need_v2
def test_l130_segment_marker_never_in_prompt(v2_env, monkeypatch):
    """ISS-1103-005241-bf53：带 scene_id 的镜，场景细节 / img / motion 里的【幻想段】只用来判段（调色 + 元数据），
    首帧 / 尾帧 / 视频提示词一律不含标记"""
    GV = _golden(monkeypatch)
    from ns_agent import compiler as C
    from ns_agent import frame_job as FJ
    sc, ep, sh = GV.load_imported(GV.SHOT)
    assert sh.scene_id, "本测试要求镜头带 scene_id"
    mk = "【" + "幻想段】"
    sh2 = sh.model_copy(update={"scene_detail": mk + (sh.scene_detail or ""), "img_prompt": mk + sh.img_prompt,
                                "motion_prompt": mk + (sh.motion_prompt or "")})
    job = FJ.build_first(V2, ep, sh2, sc.globals)
    assert job["style_segment"] == "fantasy" and job["compile_trace"]["style_segment"] == "fantasy"   # 元数据照样判段
    # W13 CUTB-PREP 11-03：数据态陈旧（不是放宽）。04:50 重导后导入稿 ep01-S8 的 scene_detail 本身带【现实段】，原断言拿“原始”
    # scene_detail 去 prompt 里找，等于要求标记进提示词，与本测试守的 L-130 自相矛盾。改为比去标记后的场景细节（编译器同一函数）。
    from ns_agent.gen_contract import style as ST
    # 11-05 series10_v2 开 prompt_template v2（项目方“基于最新架构和规则重跑 ep01”）：v2 场景块只留本镜陈设、不带“本镜场景：”原文；
    # “场景细节原文保留”只对 v1 编译成立 → 用 v1 强制复核，v2 只守“标记不进提示词”（下方）
    from ns_agent import prompt_template_v2 as PT2
    with PT2.force(image="v1"):
        job_v1 = FJ.build_first(V2, ep, sh2, sc.globals)
    assert "本镜场景：" in job_v1["prompt"] and (ST.strip_segment_marks(sh.scene_detail) or "").strip() in job_v1["prompt"]   # 场景细节保留，只去标记
    assert mk not in job_v1["prompt"] and "【现实段】" not in job_v1["prompt"]
    assert "【现实段】" not in job["prompt"]
    for k in ("prompt", "last_prompt"):
        assert mk not in (job.get(k) or ""), k
    c = C.compile_shot(ep, sh2, sc.globals, set())
    for k in ("image_prompt", "last_prompt", "video_prompt", "legacy_video_prompt"):
        assert mk not in (getattr(c, k, "") or ""), k


# ---------------------------------------------------------------- OVERSIGHT-F 第 12 轮 P2-2：守卫覆盖 renders / 共用默认目录
def test_p12_guard_covers_renders_and_shared_dirs():
    assert AR._run_of_path(ROOT / "data/renders/series10_v2/ep01/S1/x.png") == V2
    assert AR._run_of_path(ROOT / "data/renders/ep01/S1/x.png") == "series10_v1"           # legacy 不带前缀
    assert AR._run_of_path(ROOT / "data/refcrops/x.png", "series10_s2") == "series10_s2"
    with pytest.raises(AR.DerivedWriteRefused):
        AR._guard_derived_write("series10_s2", ROOT / "data/refcrops/p12_probe.png")       # 暂停的剧写共用目录 → 拦
    with pytest.raises(AR.DerivedWriteRefused):
        AR._guard_derived_write(None, ROOT / "data/refboards/p12_probe.png")               # 共用目录不知道是哪部剧 → 拦
    AR._guard_derived_write(V2, ROOT / "data/renders/series10_v2/ep01/S1/x.png")             # 制作中的剧 → 放行
