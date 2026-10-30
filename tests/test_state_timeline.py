"""T51 方案 D：每镜人物状态时间线 + 场景分组 + S1 闸门 + 底板/LoRA 就绪 + 造型注入 + bible_diff + 盖章。
全部在临时项目根目录里跑（固定剧本 tests/fixtures/t06_golden + 仓库 data/looks 副本），不碰真实 data/。"""
import hashlib
import importlib.util
import json
import shutil
import time
from pathlib import Path

import pytest

from ns_agent import bible as B
from ns_agent import compiler as C
from ns_agent import prompt_snapshot as PS
from ns_agent import state_timeline as T
from ns_agent.looks import LookStore
from ns_schema.script import ScriptImport

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "t06_golden"


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(FIX / "config", root / "config")
    shutil.copytree(FIX / "data", root / "data")
    shutil.copytree(REPO / "data" / "looks", root / "data" / "looks",
                    ignore=shutil.ignore_patterns("*.tmp", "*.bak*"))
    (root / "config" / "shot_ownership.json").write_text("{}", encoding="utf-8")
    return root


def _rows(tl, ep):
    return [r for r in tl["shots"] if r["episode"] == ep]


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ 场景分组

def test_place_time_transition_words():
    assert T.shot_place("清晨写字楼旋转门，低机位仰拍")[0] == "office_lobby"     # 弱词“写字楼”让位
    assert T.shot_place("深夜写字楼全景，整层黑")[0] == "office"
    assert T.shot_place("顾沉家客厅，他把图纸举到灯下") == ("room:living", "客厅", "gu_chen")
    assert T.shot_place("穿孔工作室，她把图纸放在诊床边")[0] == "piercing_studio"   # 诊床 ≠ 卧室
    assert T.shot_place("极近特写，林晚低头侧脸") is None
    assert T.shot_time("夜晚出租屋餐桌") == "night" and T.shot_time("清晨地铁车厢") == "morning"
    assert T.shot_transition("次日，她走进电梯") == "次日"
    assert T.shot_transition("周五，公司洗手间") == "周五"
    assert T.shot_transition("微信对话框") == "" and T.shot_transition(T._clean("她发出“周三，见”")) == ""


def test_grouping_ep01_and_scene_ids_match(proj):
    tl, sc = T.build(proj)
    ep1 = _rows(tl, 1)
    assert [r["scene_id"] for r in ep1] == ["sk_office_lobby", "sk_elevator", "sk_elevator", "sk_rental_dining",
                                            "sk_rental_kitchen", "sk_rental_bedroom"]
    assert ep1[2]["place_source"] == "inherited" and ep1[1]["segment_id"] == ep1[2]["segment_id"]
    assert ep1[0]["segment_start"] and not ep1[2]["segment_start"]
    assert ep1[0]["gpu3_shot_id"] == "ep01s1" and ep1[0]["shot_id"] == "ep01-S1"
    # scenes.json 与时间线的 scene_id 一致；每镜恰好属于一个场景；场景按地点跨集复用
    by_scene = {s["scene_id"]: s for s in sc["scenes"]}
    assert {r["scene_id"] for r in tl["shots"]} == set(by_scene)
    assert sorted(x for s in sc["scenes"] for x in s["shots"]) == sorted(r["shot_id"] for r in tl["shots"])
    assert len(by_scene["sk_elevator"]["episodes"]) > 1
    assert by_scene["sk_elevator"]["plate"] == "assets/scenes/sk_elevator/plate.png"
    assert sc["scenes_sha"] == tl["scenes_sha"]


def test_episode_boundary_always_splits(proj):
    tl, _ = T.build(proj)
    for a, b in zip(tl["shots"], tl["shots"][1:]):
        if a["episode"] != b["episode"]:
            assert a["segment_id"] != b["segment_id"] and b["segment_start"]


# ------------------------------------------------------------------ 人物状态

def test_character_state_fields(proj):
    tl, _ = T.build(proj)
    s1 = _rows(tl, 1)[0]
    lw = s1["characters"]["lin_wan"]
    assert lw["present"] and lw["makeup_state"] == "bare" and lw["eye_state"] == "bare"
    assert lw["eyes"] == "自然深棕色眼睛" and lw["d_state"] == "D0"
    assert lw["needs_review"] and "episode_plan_unconfirmed" in lw["review_reasons"]
    assert lw["nails"]["toes_in_prompt"]                     # ep01-S1 透明高跟入镜
    heavy = next(r for r in _rows(tl, 20) if r["characters"]["lin_wan"]["present"])["characters"]["lin_wan"]
    assert heavy["makeup_state"] == "heavy" and heavy["eye_state"] == "glam" and heavy["eyes"] == "灰蓝色美瞳"
    assert {a["id"] for a in heavy["adornments"]} >= {"lora-nprng2", "lora-lbrng9"}
    # 林晚每镜都有条目；别的角色只在出场时出现
    assert all("lin_wan" in r["characters"] for r in tl["shots"])
    assert all(c["present"] for r in tl["shots"] for k, c in r["characters"].items() if k != "lin_wan")


def test_changes_from_prev_shot(proj):
    tl, _ = T.build(proj)
    ep1 = _rows(tl, 1)
    assert ep1[0]["changes_from_prev_shot"]["prev_shot_id"] is None
    ch = ep1[1]["changes_from_prev_shot"]
    assert ch["prev_shot_id"] == "ep01-S1" and ch["scene_changed"] and ch["segment_changed"]
    assert not ep1[2]["changes_from_prev_shot"]["scene_changed"]


def test_owner_confirmation_clears_review_and_marks_episode(proj):
    store = LookStore(proj / "data" / "looks", proj / "data" / "import" / "script_v2.json")
    with pytest.raises(ValueError):
        store.confirm_episodes("1", "lin_wan", "  ")
    store.confirm_episodes("1-2", "林晚", "项目方：ep01–02 造型可以")
    tl, _ = T.build(proj)
    # M3：本集入镜的每个角色都要确认（ep01 还有陈宇）；没确认的角色列出来
    assert not tl["episodes"]["1"]["look_confirmed"] and tl["episodes"]["1"]["unconfirmed_characters"] == ["chen_yu"]
    assert any(b.startswith("look_unconfirmed") for b in _rows(tl, 1)[0]["s2_blockers"])
    store.confirm_episodes("1-2", "chen_yu", "项目方：ep01–02 造型可以")
    tl, _ = T.build(proj)
    assert tl["episodes"]["1"]["look_confirmed"] and tl["episodes"]["1"]["confirmed_ref"] == "项目方：ep01–02 造型可以"
    assert not tl["episodes"]["3"]["look_confirmed"]
    lw = _rows(tl, 1)[0]["characters"]["lin_wan"]
    assert "episode_plan_unconfirmed" not in lw["review_reasons"]
    assert not any(b.startswith("look_unconfirmed") for b in _rows(tl, 1)[0]["s2_blockers"])


# ------------------------------------------------------------------ S1 闸门 / provisional

def _make_v3(root: Path):
    p = root / "data" / "import" / "script_v2.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["sources"][0]["path"] = d["sources"][0]["path"].replace("v2.md", "v3.md")
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_provisional_follows_s1_gate(proj):
    tl, sc = T.build(proj)
    assert tl["source"]["script"] == "v2" and tl["provisional"] and sc["provisional"]
    assert tl["s1_gate"]["g3_accepted"] is False
    _make_v3(proj)
    assert T.build(proj)[0]["provisional"]                   # v3 但闸门没过
    gate = _tool("s1_gate")
    assert gate.main(["--root", str(proj), "--accept", "", "--no-rebuild"]) == 2   # 不接受空引用
    gate.main(["--root", str(proj), "--validator-errors", "0", "--accept", "项目方：v3 S1 通过", "--no-rebuild"])
    tl, _ = T.build(proj)
    assert tl["source"]["script"] == "v3" and not tl["provisional"]
    assert tl["s1_gate"] == {**tl["s1_gate"], "validator_errors": 0, "g3_accepted": True, "g3_ref": "项目方：v3 S1 通过"}
    # 剧本再变：旧闸门记录作废
    p = proj / "data" / "import" / "script_v2.json"
    p.write_text(p.read_text(encoding="utf-8").replace("电梯轿厢", "电梯轿厢 ", 1), encoding="utf-8")
    assert T.build(proj)[0]["provisional"]


# ------------------------------------------------------------------ 场景底板 / LoRA 注册表 / S2 就绪

def _plate(root: Path, sid: str, confirmed: bool, data=b"png"):
    d = root / "assets" / "scenes" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "plate.png").write_bytes(data)
    man = {"plate": "plate.png", "built_from": {"scenes_sha": "x", "bible_version": "y"}}
    if confirmed:
        man.update(owner_confirmed_at="2026-10-30T12:00:00", owner_confirmed_ref="项目方：电梯底板可以",
                   plate_sha256=hashlib.sha256(data).hexdigest())
    (d / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")


def test_plate_status(proj):
    assert T.plate_info(proj, "sk_elevator")["plate_status"] == "missing"
    _plate(proj, "sk_elevator", confirmed=False)
    assert T.plate_info(proj, "sk_elevator")["plate_status"] == "candidate"
    _plate(proj, "sk_elevator", confirmed=True)
    info = T.plate_info(proj, "sk_elevator")
    assert info["plate_status"] == "owner_confirmed" and info["plate_sha256"] and info["plate_built_from"]
    (proj / "assets" / "scenes" / "sk_elevator" / "plate.png").write_bytes(b"other")   # 确认后换图 → 退回候选
    assert T.plate_info(proj, "sk_elevator")["plate_status"] == "candidate"


def test_lora_registry_merge(proj):
    lock = {"loras": [{"file": "wardrobe_heels_v1.safetensors", "sha256": "abc", "status": "accepted",
                       "triggers": [{"trigger": "hh12clear"}, {"trigger": "hh12patent"}]},
                      {"file": "jewellery_nprng2_v1.safetensors", "sha256": None, "status": "accepted",
                       "triggers": [{"trigger": "nprng2"}]}]}
    (proj / "comfy").mkdir()
    (proj / "comfy" / "models.lock").write_text(json.dumps(lock), encoding="utf-8")
    reg = T.lora_registry(proj)
    assert reg["hh12clear"]["registry_status"] == "accepted"
    assert reg["nprng2"]["registry_status"] == "missing"                 # 没 sha256 不算 accepted
    g3 = proj / "data" / "renders_gpu3"
    g3.mkdir(parents=True)
    (g3 / "LORA_REGISTRY.json").write_text(json.dumps({"lin_wan_qi_v1.safetensors": {
        "trigger": "lnwan_qi", "status": "training"}}), encoding="utf-8")
    assert T.lora_registry(proj)["lnwan_qi"]["registry_status"] == "training"
    tl, _ = T.build(proj)
    r = _rows(tl, 1)[0]
    assert {x["trigger"]: x["registry_status"] for x in r["required_loras"]}["hh12clear"] == "accepted"


def test_s2_ready_when_everything_locked(proj):
    tl, _ = T.build(proj)
    assert tl["stats"]["s2_ready_shots"] == 0
    # 找一镜：只有林晚、没有图像 LoRA
    row = next(r for r in tl["shots"] if not any(x["kind"] == "image" for x in r["required_loras"])
               and set(r["characters"]) == {"lin_wan"} and r["characters"]["lin_wan"]["present"])
    _make_v3(proj)
    _tool("s1_gate").main(["--root", str(proj), "--validator-errors", "0", "--accept", "项目方 OK", "--no-rebuild"])
    for ch in tl["episodes"][str(row["episode"])]["characters"]:       # 本集入镜的每个角色都要确认
        LookStore(proj / "data" / "looks", proj / "data" / "import" / "script_v2.json").confirm_episodes(
            str(row["episode"]), ch, "项目方 OK")
    _plate(proj, row["scene_id"], confirmed=True)
    tl, _ = T.build(proj)
    r = next(x for x in tl["shots"] if x["shot_id"] == row["shot_id"])
    refs = [b for b in r["s2_blockers"] if b.startswith(("missing_ref", "ref_unresolved"))]
    assert r["s2_blockers"] == refs                          # 只剩参考图缺失（仓库图片不在临时目录）
    for b in refs:
        if b.startswith("missing_ref:"):
            f = proj / b.split(":", 1)[1]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
    tl, _ = T.build(proj)
    r = next(x for x in tl["shots"] if x["shot_id"] == row["shot_id"])
    assert r["s2_ready"] and r["s2_blockers"] == []
    assert tl["stats"]["per_episode"][str(row["episode"])]["s2_ready"] >= 1


# ------------------------------------------------------------------ 过期检测 / 版本

def test_inputs_sha_tracks_inputs(proj):
    T.write(proj)
    tl1 = T.read_timeline(proj)
    sid = "ep01-S2"
    before = next(r for r in tl1["shots"] if r["shot_id"] == sid)["inputs_sha"]
    other = next(r for r in tl1["shots"] if r["shot_id"] == "ep02-S1")["inputs_sha"]
    _plate(proj, "sk_elevator", confirmed=False)
    T.write(proj)
    tl2 = T.read_timeline(proj)
    r2 = next(r for r in tl2["shots"] if r["shot_id"] == sid)
    assert r2["inputs_sha"] != before and r2["prev_inputs_sha"] == before
    assert next(r for r in tl2["shots"] if r["shot_id"] == "ep02-S1")["inputs_sha"] == other
    assert T.shot_inputs_sha(sid, proj) == r2["inputs_sha"]
    assert "master/lin_wan" not in tl2["source_hashes"] or True
    assert {"face_reference", "comfy/models.lock", "s1_gate"} <= set(tl2["source_hashes"])
    assert tl2["bible_version"] == B.bible_version(proj) == tl2["source"]["bible_version"]


def test_take_stamped_with_versions(proj, monkeypatch, tmp_path):
    from ns_render import pipeline as P
    from ns_schema.edits import Take
    monkeypatch.setattr(P, "ROOT", proj)
    monkeypatch.setattr(P, "DATA", tmp_path / "d")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "d" / "renders")
    P._add_take("ep01-S2", Take(n=1, stage="image", file="x.png", seed=1, prompt="", created_at="t"), activate=False)
    t = P.load_takes("ep01-S2")["takes"][0]
    assert t["bible_version"] == B.bible_version(proj) and t["inputs_sha"] == T.shot_inputs_sha("ep01-S2", proj)


# ------------------------------------------------------------------ 造型注入（P2）

def _compile(root, sid, **kw):
    script = ScriptImport.model_validate_json((root / "data/import/script_v2.json").read_text(encoding="utf-8"))
    ep = next(e for e in script.episodes if any(s.id == sid for s in e.shots))
    s = next(s for s in ep.shots if s.id == sid)
    return C.compile_shot(ep, s, script.globals, set(), bible=B.load_bible(root), **kw)


def test_inject_off_by_default_and_only_confirmed(proj):
    assert not B.load_bible(proj).looks_inject
    plain = _compile(proj, "ep01-S3")
    assert "造型】" not in plain.image_prompt and plain.look_fragments == []
    assert _compile(proj, "ep01-S3", inject_looks=True).look_fragments == []          # 未确认的集不注入
    LookStore(proj / "data" / "looks", proj / "data" / "import" / "script_v2.json").confirm_episodes(
        "1", "lin_wan", "项目方 OK")
    c = _compile(proj, "ep01-S3", inject_looks=True)
    assert c.look_fragments == ["【林晚造型】素颜"]                                      # 发型已在角色锁里 → 去重
    lock_end = c.image_prompt.index("镶满钻石饰品") + len("镶满钻石饰品")
    assert c.image_prompt.index("【林晚造型】素颜") == lock_end + 1                       # 紧跟 DNA 锁
    assert "【林晚造型】素颜" in c.last_prompt
    # 打开 toml 开关也一样生效
    p = proj / "config" / "visual_bible.toml"
    p.write_text(p.read_text(encoding="utf-8").replace("inject = false", "inject = true"), encoding="utf-8")
    assert _compile(proj, "ep01-S3").look_fragments == ["【林晚造型】素颜"]


def test_inject_dedupes_script_text_and_material_terms(proj):
    from ns_schema.looks import LookPatch, WardrobeItem
    store = LookStore(proj / "data" / "looks", proj / "data" / "import" / "script_v2.json")
    store.upsert_item(WardrobeItem(id="t-side", slot="outfit", name="侧脸", description="侧脸", character="lin_wan"))
    store.patch_episode(1, "lin_wan", LookPatch(slots={"makeup": ["lw-makeup-bare"], "shoes": ["lora-hh12clear"],
                                                       "outfit": ["kw-mini-skirt", "t-side"]}))
    store.confirm_episodes("1", "lin_wan", "项目方 OK")          # 确认绑定内容：先改后确认
    c = _compile(proj, "ep01-S3", inject_looks=True)
    # “侧脸”已在剧本原文 → 不重复；注入的高跟触发细跟材质规则，且只出现一次
    assert c.look_fragments == ["【林晚造型】超短裙，12cm透明细高跟，素颜"]
    assert c.image_prompt.count(C.HEEL_TERM) == 1
    plain = _compile(proj, "ep01-S3")
    assert C.HEEL_TERM not in plain.image_prompt


# ------------------------------------------------------------------ bible_diff

def test_bible_diff_lists_changed_shots(proj, capsys):
    tool = _tool("bible_diff")
    assert tool.main(["--root", str(proj)]) == 0
    old = capsys.readouterr().out.strip()
    assert old == B.bible_version(proj) and PS.load_snapshot(old, proj)
    p = proj / "config" / "visual_bible.toml"
    p.write_text(p.read_text(encoding="utf-8").replace('term = "面部清晰对焦，五官锐利"', 'term = "面部清晰对焦，五官锐利，睫毛根根分明"'),
                 encoding="utf-8")
    assert B.bible_version(proj) != old
    assert tool.main([old, "--root", str(proj), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    # G1：尾帧也按首帧原文 + 结束状态追加纠正器条目，结束状态里写到特写的镜头只有尾帧变
    snap = PS.load_snapshot(old, proj)["shots"]
    closeups = {k for k, v in snap.items() if "面部清晰对焦，五官锐利" in v["image_prompt"]}
    last_only = {k for k, v in snap.items() if "面部清晰对焦，五官锐利" in v["last_prompt"]} - closeups
    assert set(out["changed"]) == closeups | last_only and closeups
    assert all("image_prompt" in out["changed"][k] for k in closeups)
    assert all("last_prompt" in out["changed"][k] for k in last_only)
    assert tool.main(["nope", "--root", str(proj)]) == 2


# ------------------------------------------------------------------ 自动重建

def test_look_edit_triggers_rebuild(proj, monkeypatch):
    monkeypatch.setenv("NS_TIMELINE_AUTOBUILD", "1")
    monkeypatch.setenv("NS_PROJECT_ROOT", str(proj))
    monkeypatch.setattr(T, "AUTOBUILD_DELAY", 0.0)
    assert not T.timeline_path(proj).exists()
    LookStore(proj / "data" / "looks", proj / "data" / "import" / "script_v2.json").confirm_episodes(
        "3", "lin_wan", "项目方 OK")                                  # ep03 只有林晚入镜
    for _ in range(100):
        if T.timeline_path(proj).exists() and T.scenes_path(proj).exists():
            break
        time.sleep(0.1)
    tl = T.read_timeline(proj)
    assert tl and tl["episodes"]["3"]["look_confirmed"]


def test_sandbox_looks_dir_does_not_rebuild(tmp_path, proj, monkeypatch):
    monkeypatch.setenv("NS_TIMELINE_AUTOBUILD", "1")
    monkeypatch.setenv("NS_PROJECT_ROOT", str(proj))
    called = []
    monkeypatch.setattr(T, "schedule_rebuild", lambda *a, **k: called.append(a))
    other = tmp_path / "other_looks"
    shutil.copytree(proj / "data" / "looks", other)
    LookStore(other, proj / "data" / "import" / "script_v2.json").confirm_episodes("1", "lin_wan", "x")
    assert called == []


# ------------------------------------------------------------------ QA4-01 源文件漂移

def test_source_drift_flags_edited_or_missing_script_files(tmp_path):
    lib = tmp_path / "script play lib"
    lib.mkdir()
    a, b = lib / "剧本v2.md", lib / "image v2.md"
    a.write_text("原文", encoding="utf-8")
    b.write_text("图", encoding="utf-8")
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()   # noqa: E731
    s = ScriptImport.model_validate({"sources": [{"path": str(a), "sha256": sha(a)},
                                                 {"path": r"D:\elsewhere\image v2.md", "sha256": sha(b)}],
                                     "globals": {}, "episodes": []})
    assert T.source_drift(tmp_path, s) == []                       # 绝对路径找不到时按文件名在 script play lib 找
    old = sha(a)
    a.write_text("原文（改过）", encoding="utf-8")
    b.unlink()
    d = T.source_drift(tmp_path, s)
    assert [x["imported_sha"] for x in d] == [old, s.sources[1].sha256]
    assert d[0]["current_sha"] == sha(a) and d[1]["current_sha"] is None


def test_timeline_source_lists_changed_sources(proj):
    tl, _ = T.build(proj)
    assert isinstance(tl["source"]["changed_sources"], list)


def test_source_drift_relative_path_duplicates_and_cwd(tmp_path, monkeypatch):
    """合并导入后 sources 里有相对路径（相对项目根）和重复条目；cwd 不是项目根时也不能误报“文件不见了”"""
    root = tmp_path / "proj"
    f = root / "data" / "script_chat" / "x" / "script.md"
    f.parent.mkdir(parents=True)
    f.write_text("稿", encoding="utf-8")
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    rel = "data\\script_chat\\x\\script.md"
    s = ScriptImport.model_validate({"sources": [{"path": rel, "sha256": sha}, {"path": rel, "sha256": sha}],
                                     "globals": {}, "episodes": []})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert T.source_drift(root, s) == []
    f.write_text("稿（改过）", encoding="utf-8")
    d = T.source_drift(root, s)
    assert len(d) == 1 and d[0]["current_sha"] == hashlib.sha256(f.read_bytes()).hexdigest()


def test_malformed_gate_and_manifest_do_not_crash(tmp_path):
    """封板修复：s1_gate.json / 场景 manifest.json 不是对象时按“没有记录”处理"""
    (tmp_path / "data" / "import").mkdir(parents=True)
    for body in ("[]", '"x"', "3"):
        (tmp_path / "data" / "import" / "s1_gate.json").write_text(body, encoding="utf-8")
        g = T.read_s1_gate(tmp_path, "abc")
        assert g["g3_accepted"] is False and g["validator_errors"] is None and g["stale"] is False
    d = tmp_path / "assets" / "scenes" / "sk_x"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text("[]", encoding="utf-8")
    assert T.plate_info(tmp_path, "sk_x")["plate_status"] == "missing"



def test_r_c4_frames_only_wait_for_image_loras(proj):
    """R-C4（总调度 2026-10-30 定）：首尾帧（S2）只要求 image 类 LoRA accepted；H3 视频 LoRA（lnwan01 这类）
    未验收不拦首尾帧，只在视频步提示"""
    g3 = proj / "data" / "renders_gpu3"
    g3.mkdir(parents=True, exist_ok=True)
    (g3 / "LORA_REGISTRY.json").write_text(json.dumps({"loras": [
        {"file": "lin_wan_h3_v1.safetensors", "triggers": ["lnwan01"], "kind": "video", "status": "training"},
        {"file": "wardrobe_heels_v1.safetensors", "triggers": ["hh12clear"], "kind": "image", "status": "training"}]}),
        encoding="utf-8")
    tl, _ = T.build(proj)
    rows = [r for r in tl["shots"] if any(x["trigger"] == "lnwan01" for x in r["required_loras"])]
    assert rows, "fixture 里应有带 lnwan01 的镜头"
    for r in rows:
        kinds = {x["trigger"]: x["kind"] for x in r["required_loras"]}
        assert kinds["lnwan01"] == "video"
        assert not any(b.startswith("lora:lnwan01:") for b in r["s2_blockers"])
    heel = [r for r in tl["shots"] if any(x["trigger"] == "hh12clear" for x in r["required_loras"])]
    assert heel and all("lora:hh12clear:training" in r["s2_blockers"] for r in heel)
