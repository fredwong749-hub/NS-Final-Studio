"""造型（衣橱）：种子器、三层解析、冲突、哈希、受影响镜头、API 处理函数。用临时目录，不碰 data/looks/。"""
from pathlib import Path

import pytest
from fastapi import HTTPException

from ns_agent.looks import (LookStore, Resolver, compute_look_prompt, effective_look_prompt,
                            parse_continuity_tables, parse_episode_list, resolve_character, seed)
from ns_api import looks as api
from ns_schema.looks import CHARACTERS, Look, LookPatch, WardrobeItem
from ns_schema.script import ScriptImport

# 固定测试数据（与 t06 金标准同一份 60 集 v2 剧本）：data/import 里导入了什么都不影响这些测试
PINNED_SCRIPT = Path(__file__).resolve().parent / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json"


@pytest.fixture(scope="module")
def script() -> ScriptImport:
    return ScriptImport.model_validate_json(PINNED_SCRIPT.read_text(encoding="utf-8"))


@pytest.fixture()
def store(tmp_path, script) -> LookStore:
    s = LookStore(tmp_path / "looks")
    s._script = script
    return s


def _lw(store, shot_id):
    return next(c for c in store.shot_looks(shot_id).characters if c.character == "lin_wan")


# ---------------------------------------------------------------- seeder

def test_seed_is_deterministic(script):
    assert [m.model_dump() for m in seed(script)] == [m.model_dump() for m in seed(script)]


def test_seed_wardrobe(script):
    w, _, _ = seed(script)
    items = {i.id: i for i in w.items}
    heels = items["lora-hh12clear"]
    assert heels.slot == "shoes" and heels.lora_file == "wardrobe_heels_v1.safetensors" and heels.trigger == "hh12clear"
    assert items["lora-ptxcorset"].slot == "outfit"
    nip = items["lora-nprng2"]
    assert nip.slot == "accessory" and nip.prompt_policy == "when_in_shot" and not nip.removable
    assert items["lora-lbrng9_beads"].removable
    assert "lnwan01" not in {i.trigger for i in w.items}  # 视频身份 LoRA 不是衣橱单品
    assert items["lw-hair"].description == "蓝发及腰、齐刘海"
    assert items["gc-shirt"].description == "黑色高定衬衫"
    assert all(i.needs_review for i in w.items if i.source == "keyword")


def test_seed_decor_states(script):
    w, _, sched = seed(script)
    states = {s.id: s for s in w.decor_states}
    assert states["D0"].items == [] and states["D0"].episodes == list(range(1, 9))
    assert states["D1"].items == ["lora-nprng2"]
    assert "lora-lbrng9" in states["D2"].items and "lora-lbrng9_beads" not in states["D2"].items
    assert "lora-lbrng9_beads" in states["D6"].items
    assert "lora-lbrng9_beads" not in states["DN"].items
    assert 17 in states["D4"].episodes and 17 not in states["D3"].episodes
    assert all(s.needs_review and s.description == "" for s in states.values())
    assert sched.episodes["17"]["lin_wan"].d_state == "D4"          # decor_schedule override
    assert sched.episodes["54"]["lin_wan"].visibility == "hidden"   # “D10隐藏”
    assert sched.episodes["53"]["lin_wan"].visibility == "in_box"   # “珠链在匣”


def test_seed_layers(script):
    _, book, sched = seed(script)
    assert sched.character_defaults["lin_wan"] == "lin_wan-default"
    # RECALL 2026-11-01：演员表 = 当前正式剧本登记表（series10：林晚 / 顾沉 / 陈宇 / 阿岚），旧 Alex/Ryan/Kai/Leo 已撤
    assert {lk.id for lk in book.looks} == {f"{c}-default" for c in CHARACTERS}
    ep1 = sched.episodes["1"]["lin_wan"]
    assert ep1.slots == {"makeup": ["lw-makeup-bare"]} and ep1.d_state == "D0"
    assert "lora-hh12clear" in ep1.candidate_items["shoes"]   # 只作候选，不进 slots
    ep6 = sched.episodes["6"]["lin_wan"]
    assert ep6.needs_review and any("妆容冲突" in n for n in ep6.notes)
    ep30 = sched.episodes["30"]["lin_wan"]
    assert ep30.slots == {"makeup": ["lw-makeup-heavy"]} and ep30.needs_review
    assert "REF-LW-03" in ep30.candidate_references
    assert sched.shot_overrides == {}


def test_parsers():
    md = "|集|乳环|其他|\n|---|---|---|\n|ep11|愈合完成|—|\n|ep12|✔️完整|\\*\\*x\\*\\*|\n\ntext\n|ep13|y|z|\n"
    out = parse_continuity_tables(md)
    assert out[11] == ["自查表 乳环:愈合完成"] and out[12] == ["自查表 乳环:✔️完整｜其他:x"] and 13 not in out
    assert parse_episode_list("1-3, 17，ep20") == [1, 2, 3, 17, 20]
    for bad in ("", "1-", "3-1", "a", "1,,2"):
        with pytest.raises(ValueError):
            parse_episode_list(bad)
    with pytest.raises(ValueError):
        parse_episode_list("59-61", set(range(1, 61)))
    assert resolve_character("林晚") == "lin_wan" and resolve_character("阿岚") == "ch_a_lan"
    with pytest.raises(KeyError):
        resolve_character("nobody")


# ---------------------------------------------------------------- resolution

def test_three_layer_sources(store):
    r = _lw(store, "ep17-S1")
    assert r.slots["hair"].source == "default"
    assert r.slots["makeup"].source == "episode"
    assert r.d_state.value == "D4" and r.d_state.source == "episode"
    assert r.label == "林晚 · 默认 · D4"
    store.patch_shot("ep17-S1", "lin_wan", LookPatch(slots={"shoes": ["lora-hh12clear"]}))
    r = _lw(store, "ep17-S1")
    assert r.slots["shoes"].source == "shot" and r.has_override
    assert r.slots["makeup"].source == "episode"                      # 未覆盖的槽位仍继承


def test_changed_from_prev(store):
    r = _lw(store, "ep09-S1")
    prev = r.prev_shot_id
    assert prev and prev.startswith("ep08")
    assert "d_state" in r.changed_fields and r.d_state.changed_from_prev   # D0 → D1
    store.patch_shot("ep02-S3", "lin_wan", LookPatch(slots={"makeup": ["lw-makeup-heavy"]}))
    r = _lw(store, "ep02-S3")
    assert r.changed_from_prev and r.slots["makeup"].changed_from_prev
    nxt = _lw(store, "ep02-S4")
    assert nxt.prev_shot_id == "ep02-S3" and "makeup" in nxt.changed_fields   # 换回来也是换装点


def test_conflicts(store):
    kinds = {(c.kind, c.item_id) for c in _lw(store, "ep14-S1").conflicts}
    assert ("adornment_not_in_state", "lora-lbrng9") in kinds          # D1 还没有阴环
    kinds = {c.kind for c in _lw(store, "ep06-S1").conflicts}
    assert "script_item_not_in_look" in kinds                         # 素颜计划 vs 剧本“正红唇”
    store.patch_shot("ep23-S3", "lin_wan", LookPatch(d_state="D2"))
    kinds = {c.kind for c in _lw(store, "ep23-S3").conflicts}
    assert {"d_state_differs_from_script", "adornment_not_in_state"} <= kinds
    store.patch_shot("ep23-S3", "lin_wan", LookPatch(d_state=None, visibility="in_box"))
    r = _lw(store, "ep23-S3")
    assert "adornment_hidden" in {c.kind for c in r.conflicts}
    assert "lora-lbrng9_beads" in store.look_prompt("ep23-S3").characters[0].skipped_not_in_shot


def test_hash_stable_and_sensitive(store):
    h1 = store.shot_looks("ep05-S3").look_hash
    assert store.shot_looks("ep05-S3").look_hash == h1
    store.patch_episode(5, "lin_wan", LookPatch(notes=["只是备注"]))     # 审核元数据不改哈希
    assert store.shot_looks("ep05-S3").look_hash == h1
    w = store.wardrobe()
    bare = next(i for i in w.items if i.id == "lw-makeup-bare")
    bare.description = "素颜，淡淡唇膏"
    aff = store.upsert_item(bare)                                       # 改单品内容 → 用到它的镜都过期
    assert store.shot_looks("ep05-S3").look_hash != h1
    assert "ep05-S3" in aff.affected_shots and "ep30-S1" not in aff.affected_shots


def test_prompt(store):
    lp = effective_look_prompt("ep01-S1", store)
    lw = lp.characters[0]
    assert "素颜" in lp.fragment and "lw-hair" in lw.already_in_prompt
    lp = effective_look_prompt("ep23-S3", store)
    lw = next(c for c in lp.characters if c.character == "lin_wan")
    assert "lbrng9_beads" in lp.triggers
    assert any(l.file == "jewellery_lbrng9_beads_v1.safetensors" and l.strength == 0.9 for l in lp.loras)
    assert "lora-nprng2" in lw.skipped_not_in_shot


def test_compute_is_pure(store, script):
    shot = store.shot("ep05-S3")
    args = (shot, script, store.wardrobe(), store.lookbook(), store.schedule())
    assert compute_look_prompt(*args) == compute_look_prompt(*args)


# ---------------------------------------------------------------- mutations / affected

def test_episode_switch_affects_only_that_episode(store):
    store.upsert_look(Look(id="lin_wan-trench", character="lin_wan", name="风衣",
                           items={"outfit": ["lora-ptxtrench"], "shoes": ["lora-hh12clear"]}))
    aff = store.patch_episode(22, "林晚", LookPatch(look_id="lin_wan-trench"))
    assert aff.affected_count == len(aff.affected_shots) > 0 and not aff.rendering_triggered
    assert all(s.startswith("ep22-") for s in aff.affected_shots)
    r = _lw(store, "ep22-S2")
    assert r.look_id == "lin_wan-trench" and r.look_id_source == "episode" and r.label == "林晚 · 风衣 · D6"
    assert r.slots["hair"].source == "default"                     # 造型没定义的槽位继续继承
    lp = store.look_prompt("ep22-S2")
    assert {"ptxtrench", "hh12clear"} <= set(lp.triggers)
    # 合并语义：只改 d_state，look_id 保留；显式 null 清空
    store.patch_episode(22, "lin_wan", LookPatch(d_state="D5"))
    p = store.schedule().episodes["22"]["lin_wan"]
    assert p.look_id == "lin_wan-trench" and p.d_state == "D5" and p.evidence
    store.patch_episode(22, "lin_wan", LookPatch(look_id=None))
    assert store.schedule().episodes["22"]["lin_wan"].look_id is None


def test_shot_override_and_reset(store):
    aff = store.patch_shot("ep22-S2", "lin_wan", LookPatch(slots={"shoes": []}))
    assert aff.affected_shots == ["ep22-S2"]
    assert _lw(store, "ep22-S3").has_override is False
    aff = store.patch_shot("ep22-S2", "lin_wan", None)
    assert aff.affected_shots == ["ep22-S2"] and "ep22-S2" not in store.schedule().shot_overrides
    # 没检测到出场的角色可以由覆盖加入；present=False 可以移除
    store.patch_shot("ep01-S1", "gu_chen", LookPatch(present=True))
    sl = store.shot_looks("ep01-S1")
    assert next(c for c in sl.characters if c.character == "gu_chen").present_source == "shot"
    store.patch_shot("ep01-S1", "lin_wan", LookPatch(present=False))
    assert "lin_wan" not in {c.character for c in store.shot_looks("ep01-S1").characters}


def test_episode_range(store):
    aff = store.patch_episodes("1-2, 4", "lin_wan", LookPatch(d_state="D1"))
    eps = {s.split("-")[0] for s in aff.affected_shots}
    assert eps == {"ep01", "ep02", "ep04"}
    with pytest.raises(ValueError):
        store.patch_episodes("4-1", "lin_wan", LookPatch(d_state="D1"))


def test_validation(store):
    with pytest.raises(ValueError):
        store.upsert_look(Look(id="bad", character="lin_wan", items={"outfit": ["no-such-item"]}))
    with pytest.raises(ValueError):
        store.patch_episode(3, "lin_wan", LookPatch(look_id="gu_chen-default"))   # 别人的造型
    with pytest.raises(KeyError):
        store.patch_episode(3, "lin_wan", LookPatch(look_id="no-such-look"))
    with pytest.raises(ValueError):
        store.patch_episode(3, "lin_wan", LookPatch(d_state="D99"))
    with pytest.raises(ValueError):
        store.patch_shot("ep03-S1", "lin_wan", LookPatch(slots={"wings": []}))
    with pytest.raises(KeyError):
        store.shot("ep99-S1")
    with pytest.raises(FileExistsError):
        store.seed()   # 不覆盖人工修改


# ---------------------------------------------------------------- API handlers

def test_api_handlers(store):
    cat = api.get_catalog(store)
    assert {c["id"] for c in cat["characters"]} >= {"lin_wan", "gu_chen"}
    hair = next(i for i in cat["items"] if i["id"] == "lw-hair")
    assert hair["reference_urls"][0].startswith("/api/looks/ref-image?path=assets/")
    assert any(d["id"] == "D10" for d in cat["decor_states"])

    item = WardrobeItem(id="lw-qipao", slot="outfit", name="红旗袍", description="红色丝绸旗袍", character="林晚")
    assert api.create_item(item, store).affected_count == 0
    with pytest.raises(HTTPException) as e:
        api.create_item(item, store)
    assert e.value.status_code == 409

    api.put_look("lin_wan-qipao", Look(id="x", character="lin_wan", name="旗袍", items={"outfit": ["lw-qipao"]}), store)
    aff = api.put_episode_look(6, "林晚", LookPatch(look_id="lin_wan-qipao"), store)
    assert aff.affected_count == 6 and aff.rendering_triggered is False

    ep = api.get_episode(6, store)
    assert ep["characters"]["lin_wan"]["plan"]["look_id"] == "lin_wan-qipao"
    assert ep["characters"]["lin_wan"]["resolved"]["slots"]["outfit"]["source"] == "episode"
    s1 = ep["shots"][0]
    assert s1["look_hash"] and s1["characters"]["lin_wan"]["label"] == "林晚 · 旗袍 · D0"

    # 命名造型只覆盖它定义的槽位：default 没有 outfit → 旗袍仍在，不算改动
    assert api.put_shot_override("ep06-S3", "lin_wan", LookPatch(look_id="lin_wan-default"), store).affected_count == 0
    aff = api.put_shot_override("ep06-S3", "lin_wan", LookPatch(slots={"outfit": []}), store)
    assert aff.affected_shots == ["ep06-S3"]
    sl = api.get_shot("ep06-S3", store)
    lw = next(c for c in sl.characters if c.character == "lin_wan")
    assert lw.look_id_source == "shot" and lw.has_override and sl.look_hash
    assert lw.slots["outfit"].items == [] and lw.slots["outfit"].source == "shot"
    assert "红色丝绸旗袍" in api.get_shot_prompt("ep06-S4", store).fragment
    assert api.delete_shot_override("ep06-S3", "lin_wan", store).affected_shots == ["ep06-S3"]

    aff = api.put_episode_range("lin_wan", api.RangePatch(episodes="7-8", patch=LookPatch(d_state="D1")), store)
    assert aff.affected_count > 0
    with pytest.raises(HTTPException) as e:
        api.put_episode_range("lin_wan", api.RangePatch(episodes="8-7", patch=LookPatch()), store)
    assert e.value.status_code == 422

    aff = api.put_character_default("顾沉", api.DefaultLook(look_id="gu_chen-default"), store)
    assert aff.affected_count == 0

    for bad in (lambda: api.get_shot("ep06-S9", store), lambda: api.get_episode(99, store),
                lambda: api.put_episode_look(6, "nobody", LookPatch(), store)):
        with pytest.raises(HTTPException) as e:
            bad()
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        api.put_episode_look(6, "lin_wan", LookPatch(look_id="gu_chen-default"), store)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        api.get_ref_image("../pyproject.toml")


def test_router_paths():
    paths = {(r.path, m) for r in api.router.routes for m in r.methods}
    for p in [("/api/looks", "GET"), ("/api/look-schedule", "GET"), ("/api/look-schedule", "PUT"),
              ("/api/looks/wardrobe", "GET"), ("/api/looks/wardrobe/items", "POST"),
              ("/api/looks/wardrobe/items/{item_id}", "PUT"), ("/api/looks/episodes/{n}", "GET"),
              ("/api/looks/episodes/{n}/{character}", "PUT"), ("/api/looks/shots/{shot_id}/{character}", "PUT"),
              ("/api/looks/shots/{shot_id}", "GET"), ("/api/looks/shots/{shot_id}/{character}", "DELETE")]:
        assert p in paths


def test_characters_follow_current_script_after_reimport(store, script):
    """封板修复：schedule.shot_characters 只在种子时写；剧本重新 / 合并导入后新增或改写的镜头按当前剧本现算出场角色"""
    sc = script.model_copy(deep=True)
    ep = sc.episodes[0]
    new = ep.shots[-1].model_copy(update={"index": len(ep.shots) + 1, "img_prompt": "极近特写，林晚的脸占据画面中心",
                                          "motion_prompt": "她眨眼", "img_triggers": [], "motion_triggers": []})
    ep.shots.append(new)
    sched = store.schedule()
    assert new.id not in sched.shot_characters
    r = Resolver(sc, store.wardrobe(), store.lookbook(), sched)
    assert [c for c, _src in r.characters(new)] == ["lin_wan"]


def test_store_rereads_script_after_reimport(tmp_path, script):
    """封板修复（A-4）：剧本只有 ep01 时读进来的 LookStore，合并导入回到多集后要能识别新集（原来进程内只读一次 → 404）"""
    sj = tmp_path / "script_v2.json"
    one = script.model_copy(deep=True)
    one.episodes = one.episodes[:1]
    sj.write_text(one.model_dump_json(), encoding="utf-8")
    st = LookStore(tmp_path / "looks", sj)
    assert st.episode(1).number == 1
    with pytest.raises(KeyError):
        st.episode(2)
    two = script.model_copy(deep=True)
    two.episodes = two.episodes[:2]
    sj.write_text(two.model_dump_json(), encoding="utf-8")
    assert st.episode(2).number == 2 and len(st.script.episodes) == 2


def test_she_trigger_read_from_bible(tmp_path):
    """封板修复（D-6）：looks 判断“她”是不是林晚用 visual_bible 的 detect_she_with_trigger，不写死 lnwan01"""
    from ns_agent import bible as B
    from ns_agent.looks import detect_characters
    from ns_schema.script import Shot
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "visual_bible.toml").write_text(
        '[characters.lin_wan]\nname = "林晚"\ndetect = ["林晚"]\ndetect_she_with_trigger = "lw_new"\n', encoding="utf-8")
    b = B.load_bible(root=tmp_path)
    s_new = Shot(episode=1, index=1, img_prompt="她站在窗边", motion_prompt="lw_new，她转身", motion_triggers=["lw_new"],
                 source_line=1)
    s_old = s_new.model_copy(update={"motion_prompt": "lnwan01，她转身", "motion_triggers": ["lnwan01"]})
    assert detect_characters(s_new, b) == ["lin_wan"]
    assert detect_characters(s_old, b) == []
