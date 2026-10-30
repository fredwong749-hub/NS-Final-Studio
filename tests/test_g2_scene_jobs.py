"""T43 G2 母版候选任务（ns_orch.g2_candidates + tools/g2_candidates.py）与场景底板任务（tools/gen_scenes.py）。
全部在临时目录里：不出图、不碰 GPU、不写真实 data/jobs/queue。"""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ns_api.project_ctx import ProjectContext
from ns_orch import g2_candidates as G2

REPO = Path(__file__).resolve().parents[1]
EXAMPLE_KEYS = {"model", "steps", "cfg", "size", "lora", "vae", "refine", "negative", "bible_sha256",
                "reference_source", "character", "file", "prompt", "seed", "preset", "qc", "status", "out_dir"}


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _png(p: Path, color=(120, 140, 200), size=(64, 96)) -> bytes:
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(p)
    return p.read_bytes()


# ------------------------------------------------------------------ G2

@pytest.fixture
def proj(tmp_path) -> ProjectContext:
    root = tmp_path / "proj"
    ref = root / "assets" / "characters" / "char01" / "refs" / "ref_abc.png"
    _png(ref)
    (root / "config").mkdir(parents=True)
    (root / "config" / "visual_bible.toml").write_text(
        '[realism]\nbanned_words = ["网红脸", "精致完美"]\nskin_terms = "真实皮肤质感"\n', encoding="utf-8")
    chars = {
        "char01": {"id": "char01", "name": "苏晴", "description": "25岁女性设计师，网红脸，长卷发",
                   "references": ["assets/characters/char01/refs/ref_abc.png"], "confirmed": True,
                   "approved_by": "项目方", "approved_at": "2026-10-30T10:00:00"},
        "char02": {"id": "char02", "name": "未确认", "description": "30岁男性",
                   "references": ["assets/characters/char01/refs/ref_abc.png"], "confirmed": False},
        "char03": {"id": "char03", "name": "太小", "description": "19岁女生",
                   "references": ["assets/characters/char01/refs/ref_abc.png"], "confirmed": True},
        "char04": {"id": "char04", "name": "没图", "description": "28岁男性", "references": [], "confirmed": True},
    }
    (root / "project.json").write_text(json.dumps({"characters": chars}, ensure_ascii=False), encoding="utf-8")
    return ProjectContext(slug="newdrama", name="新剧", root=root)


def test_g2_six_jobs_three_tiers(proj):
    doc = G2.build(proj, "char01")
    jobs = doc["jobs"]
    assert len(jobs) == 6
    assert [j["tier"] for j in jobs] == ["CL", "CL", "CM", "CM", "CS", "CS"]
    assert len({j["seed"] for j in jobs}) == 6
    for j in jobs:
        assert EXAMPLE_KEYS <= set(j)                       # gpu_grab 队列格式
        assert j["model"] == G2.MODEL and j["steps"] == 35 and j["cfg"] == 3.0
        assert j["vae"].startswith("texture_fix_vae")
        assert j["refine"] == {"scale": 1.5, "steps": 12, "denoise": 0.3}
        assert sum(s for _, s in j["lora"]) <= G2.LORA_CAP
        assert j["reference"]["ai_generated_fictional_adult"] is True and j["reference"]["min_age"] == 22
        assert "#808080" in j["prompt"] and "no necklace" in j["prompt"]
        assert "网红脸" not in j["prompt"] and "精致完美" not in j["prompt"]   # banned_words 去掉
        assert "25 years old" in j["prompt"] and "adult woman" in j["prompt"]
        assert j["out_dir"].endswith("assets/characters/char01/candidates/")
        assert "master" not in j["file"]
    strong = dict(map(tuple, jobs[-1]["lora"]))
    assert strong == {G2.A2R: 0.8, G2.KREA2: 0.5}           # SOP S2 锁定配方
    assert dict(map(tuple, jobs[2]["lora"])) == {G2.A2R: 0.45, G2.KREA2: 0.4}   # 林晚 CM_s1
    assert doc["jobs"][0]["bible_sha256"] == hashlib.sha256(proj.visual_bible.read_bytes()).hexdigest()


def test_g2_photo_reference_has_no_anything2real(proj):
    jobs = G2.build(proj, "char01", reference_kind="photo")["jobs"]
    assert all(n != G2.A2R for j in jobs for n, _ in j["lora"])
    assert [j["lora"][0][1] for j in jobs] == [0.3, 0.3, 0.4, 0.4, 0.5, 0.5]


@pytest.mark.parametrize("cid,why", [("char02", "AI 生成的虚构成年人"), ("char03", "< 22"), ("char04", "参考图"),
                                     ("nope", "没有角色")])
def test_g2_blocked(proj, cid, why):
    with pytest.raises(G2.G2Blocked, match=why):
        G2.build(proj, cid)


def test_g2_emit_idempotent_and_never_picks_master(proj, tmp_path):
    jobs_dir = tmp_path / "jobs"
    q = jobs_dir / "queue"
    r = G2.emit(proj, "char01", queue_dir=q, jobs_dir=jobs_dir)
    assert r["status"] == "queued" and r["jobs"] == 6
    doc = json.loads(Path(r["path"]).read_text(encoding="utf-8"))
    assert doc["kind"] == "g2_master_candidates" and "never writes" in doc["selection"]
    assert G2.emit(proj, "char01", queue_dir=q, jobs_dir=jobs_dir)["status"] == "exists"
    # 队列执行器把文件挪走（done/）也算出过
    done = jobs_dir / "done"
    done.mkdir()
    Path(r["path"]).replace(done / Path(r["path"]).name)
    assert G2.emit(proj, "char01", queue_dir=q, jobs_dir=jobs_dir)["status"] == "exists"
    assert G2.emit(proj, "char01", queue_dir=q, jobs_dir=jobs_dir, force=True)["status"] == "queued"
    # 新上传一张参考图 → 新队列文件
    _png(proj.root / "assets/characters/char01/refs/ref_new.png", color=(10, 20, 30))
    s = proj.settings()
    s["characters"]["char01"]["references"].append("assets/characters/char01/refs/ref_new.png")
    proj.save_settings(s)
    r2 = G2.emit(proj, "char01", queue_dir=q, jobs_dir=jobs_dir)
    assert r2["status"] == "queued" and r2["path"] != r["path"]
    assert not (proj.root / "assets/characters/char01/plates/master.png").exists()
    assert G2.candidates_status(proj, "char01")["master_exists"] is False


def test_g2_scan_reports_blocked(proj, tmp_path):
    rows = {r["character"]: r for r in G2.scan(proj, queue_dir=tmp_path / "q", jobs_dir=tmp_path)}
    assert rows["char01"]["status"] == "queued"
    assert {rows[c]["status"] for c in ("char02", "char03", "char04")} == {"blocked"}


def test_g2_cli_dry_run(proj, monkeypatch, capsys):
    cli = _tool("g2_candidates")
    monkeypatch.setattr(cli, "get_project", lambda slug: proj)
    assert cli.main(["emit", "--char", "char01", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert '"dry_run"' in out and "char01_CS_s1.png" in out
    assert cli.main(["emit", "--char", "char02", "--dry-run"]) == 2


# ------------------------------------------------------------------ 场景底板

@pytest.fixture
def scenes_root(tmp_path):
    root = tmp_path / "root"
    (root / "data" / "import").mkdir(parents=True)
    script = {"globals": {"image_suffix": "干净无字"}, "episodes": [{"number": 1, "shots": [
        {"index": 1, "img_prompt": "写字楼大堂，晨光从玻璃幕墙照进来，林晚走进来"},
        {"index": 2, "img_prompt": "电梯里，低机位仰拍，顶灯冷白光"}]}]}
    (root / "data/import/script_v2.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    scenes = {"format": "ns.scenes/1", "bible_version": "bv1", "provisional": True, "scenes_sha": "abc123",
              "scenes": [
                  {"scene_id": "sk_lobby", "place": "写字楼大堂", "time_of_day": "morning", "shots": ["ep01-S1"],
                   "plate_detail": {"light": {"time": "morning", "key_direction": "side", "colour_temp": "warm"}}},
                  {"scene_id": "sk_elevator", "place": "电梯", "time_of_day": "night", "shots": ["ep01-S2"],
                   "plate_detail": {"light": {"time": "night", "key_direction": None, "colour_temp": "cool"}}}]}
    (root / "data/scenes.json").write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
    (root / "data/state_timeline.json").write_text(json.dumps({"provisional": True}), encoding="utf-8")
    ref = np.zeros((64, 64, 3), np.uint8)
    ref[..., 0], ref[..., 1], ref[..., 2] = 200, 140, 80          # 暖色参考
    (root / "assets/style").mkdir(parents=True)
    Image.fromarray(ref).save(root / "assets/style/color_reference_01.png")
    return root


def _pass_s1(root):
    (root / "data/state_timeline.json").write_text(json.dumps({"provisional": False}), encoding="utf-8")


def test_scene_jobs_locked_recipe(scenes_root):
    gs = _tool("gen_scenes")
    head, jobs = gs.scene_jobs(scenes_root)
    assert {j["id"] for j in jobs} == {"scene_sk_lobby_plate", "scene_sk_elevator_plate", "scene_sk_elevator_plate_low"}
    sha = hashlib.sha256((scenes_root / "data/scenes.json").read_bytes()).hexdigest()
    assert head["scenes_json_sha256"] == sha and head["scenes_sha"] == "abc123"
    for j in jobs:
        assert {"model", "steps", "cfg", "size", "lora", "vae", "refine", "negative", "prompt", "seed", "file",
                "out_dir", "status"} <= set(j)
        assert j["cfg"] == 3.0 and j["steps"] == 35
        assert j["refine"]["upscale_to"] == [1152, 2016] and j["refine"]["denoise"] == 0.3
        assert j["refine"]["upscale_method"] == "lanczos"
        assert j["post"]["center_crop"] == [768, 1344] and j["post"]["resample"] == "lanczos"
        assert j["post"]["color_match"]["method"] == "reinhard_lab"
        assert j["post"]["color_match"]["reference"] == "assets/style/color_reference_01.png"
        assert j["built_from"]["scenes_json_sha256"] == sha
        assert "林晚" not in j["prompt"]
    by = {j["id"]: j for j in jobs}
    assert by["scene_sk_lobby_plate"]["post"]["color_match"]["strength"] == 0.6
    assert by["scene_sk_elevator_plate"]["post"]["color_match"]["strength"] == 0.3     # 夜景减弱
    assert by["scene_sk_elevator_plate"]["light"]["colour_temp"] == "cool"


def test_scene_emit_refused_while_provisional(scenes_root, tmp_path):
    gs = _tool("gen_scenes")
    with pytest.raises(SystemExit, match="provisional"):
        gs.emit(scenes_root, queue_dir=tmp_path / "q")
    assert not (tmp_path / "q").exists()
    r = gs.emit(scenes_root, draft=True, queue_dir=tmp_path / "q")
    assert r["status"] == "queued" and r["path"].endswith("_draft.json")
    doc = json.loads(Path(r["path"]).read_text(encoding="utf-8"))
    assert doc["draft"] is True and all(j["status"].startswith("draft") for j in doc["jobs"])


def test_scene_emit_finalize_manifest(scenes_root, tmp_path):
    gs = _tool("gen_scenes")
    _pass_s1(scenes_root)
    q = tmp_path / "q"
    r = gs.emit(scenes_root, only=["sk_lobby"], queue_dir=q)
    assert r["status"] == "queued" and r["jobs"] == 1
    assert gs.emit(scenes_root, only=["sk_lobby"], queue_dir=q)["status"] == "exists"
    d = scenes_root / "assets/scenes/sk_lobby"
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert man["scene_id"] == "sk_lobby" and "plate" in man["queued"]
    # 旧的项目方确认 + gpu 交回的 1152×2016 原图
    man.update(owner_confirmed_at="2026-10-30T00:00:00", owner_confirmed_ref="ok", plate_sha256="old")
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    Image.new("RGB", (1152, 2016), (90, 110, 160)).save(d / "plate_raw.png")
    done = gs.finalize(scenes_root)
    assert done == [{"scene_id": "sk_lobby", "stem": "plate", "status": "candidate",
                     "file": "assets/scenes/sk_lobby/plate.png"}]
    assert Image.open(d / "plate.png").size == (768, 1344)
    assert Image.open(d / "plate_ungraded.png").size == (768, 1344)
    # 调色朝暖色参考移动：R 升、B 降
    g = np.asarray(Image.open(d / "plate.png")).reshape(-1, 3).mean(0)
    u = np.asarray(Image.open(d / "plate_ungraded.png")).reshape(-1, 3).mean(0)
    assert g[0] > u[0] and g[2] < u[2]
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert man["plate"] == "plate.png" and man["plate_status"] == "candidate"
    assert man["light"] == {"time": "morning", "key_direction": "side", "colour_temp": "warm"}
    assert man["built_from"]["scenes_sha"] == "abc123" and man["built_from"]["scenes_json_sha256"]
    assert man["built_from"]["bible_version"] == "bv1"
    assert not any(k in man for k in ("owner_confirmed_at", "owner_confirmed_ref", "plate_sha256", "queued"))
    assert man["candidate_sha256"] == hashlib.sha256((d / "plate.png").read_bytes()).hexdigest()
    # state_timeline 读到的是 candidate（只有项目方能确认）
    from ns_agent import state_timeline as T
    info = T.plate_info(scenes_root, "sk_lobby")
    assert info["plate_status"] == "candidate" and info["plate_built_from"]["scenes_sha"] == "abc123"
    # 已有 plate.png → 不再重排，除非 --force
    assert gs.emit(scenes_root, only=["sk_lobby"], queue_dir=tmp_path / "q2")["status"] == "nothing"


def test_center_crop_cover(scenes_root):
    gs = _tool("gen_scenes")
    out = gs.center_crop(Image.new("RGB", (1200, 2016)), (768, 1344))
    assert out.size == (768, 1344)


def test_plate_prompt_drops_people_and_triggers(scenes_root):
    gs = _tool("gen_scenes")
    assert gs.strip_people("lbrng9_beads，晨光照进来，林晚走进来") == "晨光照进来"
    _, jobs = gs.scene_jobs(scenes_root)
    lobby = next(j for j in jobs if j["scene_id"] == "sk_lobby")
    assert "清晨" in lobby["prompt"] and "morning" not in lobby["prompt"]
