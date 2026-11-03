"""W33（C-14 / L-126，P0）：版本文件 rel 带剧名前缀 + registry 只认本剧的 frames_v2 尝试。

1) ns_render.render_paths：V2 写 renders/<run>/epNN/SNN/takes/…，V1（legacy）保持 renders/epNN/…；旧 rel 迁移前后都能读；
   新 rel 找不到时不退回 V1 目录（防 V1 同名文件冒充）。
2) producer.fv2_for_run：全局 frames_v2/state.json 的 V1 尝试 / final 不计入 V2（不再把 V2 镜判尽力、不标 ASSETMASTER 在做）。
3) tools/debug/migrate_renders_prefix.py --dry：按 takes.json 归属列出 V1 目录里的本剧文件，不动文件。
全部在临时目录，不碰真实 data/。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
sys.path.insert(0, str(ROOT / "tools" / "debug"))
import producer as PR  # noqa: E402
from ns_render import render_paths as RP  # noqa: E402


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path):
    _w(tmp_path / "config/pipeline/run.json", {"run_id": "series10_v2"})
    _w(tmp_path / "config/pipeline/runs.json", {"primary": "series10_v2", "legacy_unprefixed_run": "series10_v1",
                                                "runs": {"series10_v1": {"status": "archived"},
                                                         "series10_v2": {"status": "producing", "assets_manifest": "assets_v2/manifest.json"}}})
    _w(tmp_path / "assets_v2/manifest.json", {"characters": {"lead_f": {}}})
    _w(tmp_path / "data/pipeline/runs/series10_v2/P1_looks.json", [{"name": "祁念", "char_id": "lead_f"}])
    return tmp_path


# ------------------------------------------------------------------ 1) 写入 / 读取路径
def test_write_rel_v2_has_run_prefix(tmp_path):
    data = tmp_path / "data"
    renders = data / "renders" / "series10_v2"
    d = renders / "ep01" / "S2"
    assert RP.take_rel_dir(d, data, renders) == "renders/series10_v2/ep01/S2/takes"
    assert RP.shot_rel_dir(d, data, renders) == "renders/series10_v2/ep01/S2"


def test_write_rel_legacy_unchanged(tmp_path):
    data = tmp_path / "data"
    renders = data / "renders"
    assert RP.take_rel_dir(renders / "ep01" / "S2", data, renders) == "renders/ep01/S2/takes"


def test_write_rel_outside_data_keeps_old_form(tmp_path):
    data, renders = tmp_path / "data", tmp_path / "elsewhere"
    assert RP.take_rel_dir(renders / "ep01" / "S2", data, renders) == "renders/ep01/S2/takes"


def test_take_rel_by_run():
    assert RP.take_rel("series10_v2", "ep01", "S2", "image_001.png", root=ROOT) == "renders/series10_v2/ep01/S2/takes/image_001.png"
    assert RP.take_rel("series10_v1", "ep01", "S2", "image_001.png", root=ROOT) == "renders/ep01/S2/takes/image_001.png"


def test_pipeline_rel_dir_matches_real_write_location(tmp_path, monkeypatch):
    """shot_take_rel_dir 给出的 rel 拼回 DATA 后正好在 RENDERS 下（原 bug：拼回后落进 V1 目录）"""
    from ns_render import pipeline as P
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders" / "series10_v2")
    rel = RP.shot_take_rel_dir("ep01-S2")
    assert (P.DATA / rel).resolve() == (P.RENDERS / "ep01" / "S2" / "takes").resolve()


def test_resolve_old_rel_before_and_after_migration(tmp_path):
    data = tmp_path / "data"
    old = "renders/ep01/S2/takes/image_001.png"
    (data / old).parent.mkdir(parents=True)
    (data / old).write_bytes(b"x")
    assert RP.resolve_rel(old, data, run="series10_v2", root=ROOT) == data / old          # 迁移前：原处
    assert RP.resolve_rel("data/" + old, data, run="series10_v2", root=ROOT) == data / old
    moved = data / "renders/series10_v2/ep01/S2/takes/image_001.png"
    moved.parent.mkdir(parents=True)
    (data / old).rename(moved)
    assert RP.resolve_rel(old, data, run="series10_v2", root=ROOT) == moved             # 迁移后：旧 rel 找到新位置
    assert RP.resolve_rel("renders/series10_v2/ep01/S2/takes/image_001.png", data, run="series10_v2", root=ROOT) == moved


def test_resolve_new_rel_never_falls_back_to_v1(tmp_path):
    data = tmp_path / "data"
    v1 = data / "renders/ep01/S2/takes/image_001.png"
    v1.parent.mkdir(parents=True)
    v1.write_bytes(b"v1")
    p = RP.resolve_rel("renders/series10_v2/ep01/S2/takes/image_001.png", data, run="series10_v2", root=ROOT)
    assert p == data / "renders/series10_v2/ep01/S2/takes/image_001.png" and not p.exists()


def test_resolve_legacy_run_does_not_look_in_v2(tmp_path):
    data = tmp_path / "data"
    v2 = data / "renders/series10_v2/ep01/S2/takes/image_001.png"
    v2.parent.mkdir(parents=True)
    v2.write_bytes(b"v2")
    assert RP.resolve_rel("renders/ep01/S2/takes/image_001.png", data, run="series10_v1", root=ROOT) == \
        data / "renders/ep01/S2/takes/image_001.png"


def test_no_write_site_uses_relative_to_renders():
    """回归：写入点不许再用 relative_to(RENDERS) 拼 rel（会丢剧名前缀）"""
    import re
    bad = []
    for base in ("services", "tools"):
        for f in (ROOT / base).rglob("*.py"):
            if "__pycache__" in f.parts or f.name == "render_paths.py":
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if re.search(r"relative_to\((?:P\.|_?P\.)?RENDERS\)", line) and "renders/" in line:
                    bad.append(f"{f.relative_to(ROOT)}:{i}")
    assert not bad, bad


# ------------------------------------------------------------------ 2) registry 不读他剧 attempts
V1_ATTS = [{"file": f"data/assetmaster/frames_v2/ep01/ep01-S2_image_s{i}_raw_post.png", "seed": i,
            "postflight": {"ok": False}} for i in range(4)]


def _fv2_global():
    return {"ep01-S2": {"image": {"attempts": V1_ATTS, "job": {"preflight": {"ok": False, "reasons": ["V1 缺 lin_wan"]}},
                                  "final": {"status": "不合格", "file": V1_ATTS[-1]["file"], "why": ["V1 不合格"]}}},
            "ep01-S3": {"image": {"attempts": [{"file": "data/assetmaster/frames_v2/ep01/x.png", "run": "series10_v2", "seed": 9}],
                                  "final": {"status": "通过", "file": "data/assetmaster/frames_v2/ep01/x.png"}}},
            "ep01-S4": {"image": {"attempts": [{"file": "data/assetmaster/frames_v2/ep01/y.png", "run": "smoke_v2"}]}}}


def test_fv2_for_run_drops_v1_and_other_runs(tmp_path):
    paths = PR.Paths(root=_root(tmp_path), run_id="series10_v2")
    got = PR.fv2_for_run(paths, _fv2_global())
    assert "ep01-S2" not in got                 # V1 无剧名尝试 + V1 final + V1 preflight 全不认
    assert "ep01-S4" not in got                 # 他剧
    assert len(got["ep01-S3"]["image"]["attempts"]) == 1 and got["ep01-S3"]["image"]["final"]["status"] == "通过"


def test_fv2_for_run_legacy_unchanged(tmp_path):
    paths = PR.Paths(root=_root(tmp_path), run_id="series10_v1")
    fv = _fv2_global()
    assert PR.fv2_for_run(paths, fv) is fv


def test_world_reads_filtered_fv2(tmp_path):
    paths = PR.Paths(root=_root(tmp_path), run_id="series10_v2")
    _w(paths.frames_v2, _fv2_global())
    w = PR.World(paths)
    assert "ep01-S2" not in w.fv2 and "ep01-S3" in w.fv2


def test_frame_obj_v1_attempts_do_not_make_v2_best_effort(tmp_path):
    """事故形态：V1 试了 4 次、final=不合格 → 原来 V2 同镜号直接“试了 4 次仍没过契约→尽力”"""
    paths = PR.Paths(root=_root(tmp_path), run_id="series10_v2")
    td = {"takes": [], "active": {}}
    raw = _fv2_global()["ep01-S2"]
    before = PR._frame_obj("first", "image", "ep01-S2", 1, td, raw, {}, {}, {}, False, True)
    assert before["status"] == "best_effort"    # 证明未过滤时确实会误判
    fv = PR.fv2_for_run(paths, _fv2_global()).get("ep01-S2") or {}
    after = PR._frame_obj("first", "image", "ep01-S2", 1, td, fv, {}, {}, {}, False, True)
    assert after["status"] != "best_effort" and after["attempts"] == 0


def test_fv2_proc_run_ok(tmp_path):
    root = _root(tmp_path)
    v2, v1 = PR.Paths(root=root, run_id="series10_v2"), PR.Paths(root=root, run_id="series10_v1")
    c_v1 = "python tools/assetmaster/frames_v2.py run --run series10_v1 --eps 1-3"
    c_bare = "python tools/assetmaster/frames_v2.py run --eps 1-3"
    assert not PR.fv2_proc_run_ok(v2, c_v1) and not PR.fv2_proc_run_ok(v2, c_bare)
    assert PR.fv2_proc_run_ok(v1, c_v1) and PR.fv2_proc_run_ok(v1, c_bare)


def test_reset_best_effort_dry_only_this_run(tmp_path):
    root = _root(tmp_path)
    paths = PR.Paths(root=root, run_id="series10_v2")
    reg = {"episodes": [{"ep": 1, "shots": [{"shot": s, "objects": {"first": {"id": f"first:{s}", "status": "best_effort"},
                                                                    "last": {"id": f"last:{s}", "status": "pending"}}}
                                            for s in ("ep01-S2", "ep01-S5")]}]}
    _w(paths.registry, reg)
    v1_reg = root / "data/producer/registry.json"           # V1 的 registry（legacy 不带前缀）
    _w(v1_reg, reg)
    _w(paths.frames_v2, _fv2_global())
    before = {p: p.read_bytes() for p in (paths.registry, v1_reg, paths.frames_v2)}
    r = PR.reset_best_effort_dry(paths, {"ep01-S2"})
    assert r["would_reset"] == 1 and r["objs"][0]["obj"] == "first:ep01-S2"
    assert r["objs"][0]["fv2_attempts_all"] == 4 and r["objs"][0]["fv2_attempts_this_run"] == 0 and r["objs"][0]["fv2_final_foreign"]
    assert r["registry"].startswith("data/producer/runs/series10_v2/")
    assert all(p.read_bytes() == b for p, b in before.items())          # dry 不写
    assert not paths.ledger.exists()


# ------------------------------------------------------------------ 3) 迁移 --dry
def test_migrate_dry_lists_own_files_only(tmp_path):
    import migrate_renders_prefix as MG
    root = _root(tmp_path)
    data = root / "data"
    for f in ("renders/ep01/S2/takes/image_001_aa_raw_post.png", "renders/ep01/S2/takes/image_001_aa_raw.png",
              "renders/ep01/S2/takes/image_002_v1.png"):
        (data / f).parent.mkdir(parents=True, exist_ok=True)
        (data / f).write_bytes(b"x")
    own = {"n": 1, "stage": "image", "file": "renders/ep01/S2/takes/image_001_aa_raw_post.png",
           "raw_file": "renders/ep01/S2/takes/image_001_aa_raw.png", "workflow": "frame_v9_unified"}
    foreign = {"n": 2, "stage": "image", "file": "renders/ep01/S2/takes/image_002_v1.png",
               "params": {"origin": {"run": "assetmaster/frames_v2"}}}
    prefixed = {"n": 3, "stage": "image", "file": "renders/series10_v2/ep01/S2/takes/image_003.png"}
    _w(data / "renders/series10_v2/ep01/S2/takes.json", {"takes": [own, foreign, prefixed], "active": {}})
    _w(data / "renders/ep01/S2/takes.json", {"takes": [{"n": 1, "stage": "image", "file": "renders/ep01/S2/takes/image_002_v1.png"}]})
    snap = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    r = MG.plan("series10_v2", root=root, producer_mod=PR)
    assert r["files"] == 2 and r["takes_skipped_foreign"] == 1 and r["shared_with_v1"] == 0
    assert {x["dst"] for x in r["rows"]} == {"data/renders/series10_v2/ep01/S2/takes/image_001_aa_raw_post.png",
                                            "data/renders/series10_v2/ep01/S2/takes/image_001_aa_raw.png"}
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == snap      # 不动任何文件


def test_migrate_apply_and_dry_together_refused():
    import migrate_renders_prefix as MG
    assert MG.main(["--run", "series10_v2", "--apply", "--dry"]) == 2      # 参数检查在动任何文件之前


def test_migrate_refuses_legacy(tmp_path):
    import migrate_renders_prefix as MG
    with pytest.raises(SystemExit):
        MG.plan("series10_v1", root=_root(tmp_path), producer_mod=PR)


# ------------------------------------------------------------------ 4) W34 迁移 --apply（只搬不删 / 不覆盖 / 幂等 / takes rel 改写）
def _fake_mutate(sid, fn, *, path, op, by):
    """测试用 mutate_takes：读-改-写同一个 takes.json（真实写入口的锁 / 备份在 pipeline 测试里另测）"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc = fn(doc) or doc
    Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc


def _apply_fixture(tmp_path):
    root = _root(tmp_path)
    data = root / "data"
    for f in ("renders/ep01/S2/takes/image_001_aa_raw_post.png", "renders/ep01/S2/takes/image_001_aa_raw.png",
              "renders/ep01/S2/takes/image_002_v1.png", "renders/ep01/S3/takes/last_001_bb.png"):
        (data / f).parent.mkdir(parents=True, exist_ok=True)
        (data / f).write_bytes(b"src:" + f.encode())
    own = {"n": 1, "stage": "image", "file": "renders/ep01/S2/takes/image_001_aa_raw_post.png",
           "raw_file": "renders/ep01/S2/takes/image_001_aa_raw.png", "workflow": "frame_v9_unified"}
    q_own = {"n": 4, "stage": "image", "file": "renders/ep01/S2/takes/image_001_aa_raw_post.png"}
    foreign = {"n": 2, "stage": "image", "file": "renders/ep01/S2/takes/image_002_v1.png",
               "params": {"origin": {"run": "assetmaster/frames_v2"}}}
    _w(data / "renders/series10_v2/ep01/S2/takes.json", {"takes": [own, foreign], "quarantined": [q_own], "active": {"image": 1}})
    _w(data / "renders/series10_v2/ep01/S3/takes.json",
       {"takes": [{"n": 1, "stage": "last", "file": "renders/ep01/S3/takes/last_001_bb.png"}], "active": {"last": 1}})
    # S3 的目标已经有一个同名文件（不能覆盖）
    (data / "renders/series10_v2/ep01/S3/takes").mkdir(parents=True, exist_ok=True)
    (data / "renders/series10_v2/ep01/S3/takes/last_001_bb.png").write_bytes(b"already-there")
    return root, data


def test_migrate_apply_moves_rewrites_and_never_overwrites(tmp_path):
    import migrate_renders_prefix as MG
    root, data = _apply_fixture(tmp_path)
    r = MG.apply("series10_v2", root=root, producer_mod=PR, mutate=_fake_mutate, ts="T1")
    assert r["moved"] == 2 and r["conflicts"] == 1 and r["errors"] == 0
    new = "renders/series10_v2/ep01/S2/takes/image_001_aa_raw_post.png"
    assert (data / new).read_bytes() == b"src:renders/ep01/S2/takes/image_001_aa_raw_post.png"
    assert not (data / "renders/ep01/S2/takes/image_001_aa_raw_post.png").exists()          # 搬走（不是复制）
    assert (data / "renders/ep01/S2/takes/image_002_v1.png").exists()                        # 他剧（V1 来源）的文件不动
    assert (data / "renders/series10_v2/ep01/S3/takes/last_001_bb.png").read_bytes() == b"already-there"   # 不覆盖
    assert (data / "renders/ep01/S3/takes/last_001_bb.png").exists()                         # 冲突的源留原处
    tk = json.loads((data / "renders/series10_v2/ep01/S2/takes.json").read_text(encoding="utf-8"))
    t1 = tk["takes"][0]
    assert t1["file"] == new and t1["file_legacy"] == "renders/ep01/S2/takes/image_001_aa_raw_post.png"
    assert t1["raw_file"] == "renders/series10_v2/ep01/S2/takes/image_001_aa_raw.png" and t1["raw_file_legacy"]
    assert tk["takes"][1]["file"] == "renders/ep01/S2/takes/image_002_v1.png" and "file_legacy" not in tk["takes"][1]
    assert tk["quarantined"][0]["file"] == new                                               # 隔离区引用同一文件也跟着改
    s3 = json.loads((data / "renders/series10_v2/ep01/S3/takes.json").read_text(encoding="utf-8"))
    assert s3["takes"][0]["file"] == "renders/ep01/S3/takes/last_001_bb.png"                 # 冲突 → rel 不改
    man = json.loads((data / "quarantine/series10_v2/migrate_T1/manifest.json").read_text(encoding="utf-8"))
    assert man["moved"] == 2 and man["conflict_rows"][0]["why"].startswith("目标已存在")
    assert (data / "quarantine/series10_v2/migrate_T1/takes_before/ep01/S2/takes.json").is_file()   # 改写前的 takes.json 留底


def test_migrate_apply_idempotent(tmp_path):
    import migrate_renders_prefix as MG
    root, data = _apply_fixture(tmp_path)
    MG.apply("series10_v2", root=root, producer_mod=PR, mutate=_fake_mutate, ts="T1")
    snap = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    r2 = MG.apply("series10_v2", root=root, producer_mod=PR, mutate=_fake_mutate, ts="T2")
    assert r2["moved"] == 0 and r2["takes_rewritten"] == 0 and r2["errors"] == 0
    assert r2["planned"] == 1 and r2["conflicts"] == 1                                       # 只剩那个冲突，照旧不碰
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()
             if "migrate_T2" not in p.as_posix()}
    assert after == snap


def test_migrate_apply_resumes_after_move_without_rewrite(tmp_path):
    """上次文件搬了但 takes.json 没改成（锁超时等）：重跑认“源不在、目标在” = 已搬，只补改写"""
    import migrate_renders_prefix as MG
    root, data = _apply_fixture(tmp_path)
    src, dst = data / "renders/ep01/S2/takes/image_001_aa_raw.png", data / "renders/series10_v2/ep01/S2/takes/image_001_aa_raw.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    r = MG.apply("series10_v2", root=root, producer_mod=PR, mutate=_fake_mutate, ts="T1")
    assert r["already_moved"] == 1 and r["moved"] == 1
    tk = json.loads((data / "renders/series10_v2/ep01/S2/takes.json").read_text(encoding="utf-8"))
    assert tk["takes"][0]["raw_file"] == "renders/series10_v2/ep01/S2/takes/image_001_aa_raw.png"
