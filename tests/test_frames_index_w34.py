"""W34（C-14 / L-126）：出图页 /api/frames-index 认 renders/<run>/ 前缀、旧 rel 解析到迁移后的位置、V1 文件照旧挡；
人物筛选按剧读该剧导入稿，不读全局 data/import/script_v2.json（V1 人物 lin_wan）。全部临时目录 / 不改真实 data。"""
import json
from pathlib import Path

import pytest

from ns_api import frames_index as FI
from ns_api import v1_guard as G
from ns_render import pipeline as P

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def v2data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": "series10_v2", "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    renders = data / "renders" / "series10_v2"
    for f in ("renders/series10_v2/ep01/S1/takes/image_001_new.png",       # 新写法（带前缀）
              "renders/series10_v2/ep01/S2/takes/image_001_moved.png",     # 已迁移，但 takes.json 还是旧 rel
              "renders/ep01/S3/takes/image_001_v1.png"):                   # V1 目录里的文件
        (data / f).parent.mkdir(parents=True, exist_ok=True)
        (data / f).write_bytes(b"x")
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", renders)
    G._cache.clear()
    yield data
    G._cache.clear()


def test_url_prefixed_rel(v2data):
    assert FI._url("renders/series10_v2/ep01/S1/takes/image_001_new.png") == "/files/renders/series10_v2/ep01/S1/takes/image_001_new.png"
    assert FI._url("data/renders/series10_v2/ep01/S1/takes/image_001_new.png") == "/files/renders/series10_v2/ep01/S1/takes/image_001_new.png"


def test_url_old_rel_resolves_to_migrated_location(v2data):
    assert FI._url("renders/ep01/S2/takes/image_001_moved.png") == "/files/renders/series10_v2/ep01/S2/takes/image_001_moved.png"
    assert FI._url("renders/ep01/S2/takes/image_001_moved.png", "series10_v2") == "/files/renders/series10_v2/ep01/S2/takes/image_001_moved.png"


def test_url_v1_file_still_blocked(v2data):
    assert FI._url("renders/ep01/S3/takes/image_001_v1.png") is None          # 只在 V1 目录 → 不给地址
    assert FI._url("renders/ep01/S9/takes/nothing.png") is None
    assert FI._url(None) is None


def test_build_ep01_urls_not_null(v2data, monkeypatch):
    for idx, f in ((1, "renders/series10_v2/ep01/S1/takes/image_001_new.png"), (2, "renders/ep01/S2/takes/image_001_moved.png")):
        d = P.RENDERS / "ep01" / f"S{idx}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "takes.json").write_text(json.dumps({"takes": [{"n": 1, "stage": "image", "file": f}], "active": {"image": 1}}), encoding="utf-8")
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {})
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {})
    monkeypatch.setattr(FI, "_edits_by_cell", lambda: {})
    s = {x["id"]: x for e in FI.build(1)["episodes"] for x in e["shots"]}
    assert s["ep01-S1"]["first"]["url"].startswith("/files/renders/series10_v2/ep01/S1/")
    assert s["ep01-S2"]["first"]["url"].startswith("/files/renders/series10_v2/ep01/S2/")


def test_script_chars_reads_run_script_not_v1():
    """真实仓库：series10_v2 的人物来自本剧导入稿，不出现 V1 人物"""
    v1 = {"lin_wan", "gu_chen", "chen_yu", "ch_a_lan", "林晚", "顾沉", "陈宇", "阿岚"}
    f = FI._script_path("series10_v2")
    assert f is not None and f.resolve() != (ROOT / "data/import/script_v2.json").resolve()
    if not f.is_file():
        pytest.skip("本机没有 series10_v2 导入稿")
    ch = FI._script_chars("series10_v2")
    assert ch, "series10_v2 人物映射为空"
    allc = {c for v in ch.values() for c in v}
    assert not (allc & v1), allc & v1


def test_script_chars_v2_never_reads_global_v1_script(monkeypatch):
    """runs.py 把非 legacy 剧解析到全局 V1 稿 → 不读（{}）"""
    from ns_agent import run_paths as RPA
    m = RPA.runs_module(ROOT)
    monkeypatch.setattr(m, "script_path", lambda run=None, root=None: ROOT / "data/import/script_v2.json")
    assert FI._script_path("series10_v2") is None
    assert FI._script_chars("series10_v2") == {}


def test_v1_take_merged_into_v2_does_not_shadow_v2_version(v2data, monkeypatch):
    """merge_pull 把 V1 的版本（n 更大、文件只在 V1 目录）并进本剧 takes.json：“新”仍指本剧那一版，不是 null"""
    d = P.RENDERS / "ep01" / "S3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps({"takes": [
        {"n": 1, "stage": "image", "file": "renders/series10_v2/ep01/S1/takes/image_001_new.png"},
        {"n": 9, "stage": "image", "file": "renders/ep01/S3/takes/image_001_v1.png"}], "active": {}}), encoding="utf-8")
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {})
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {})
    monkeypatch.setattr(FI, "_edits_by_cell", lambda: {})
    s = {x["id"]: x for e in FI.build(1)["episodes"] for x in e["shots"]}
    assert s["ep01-S3"]["first"]["new_n"] == 1
    assert s["ep01-S3"]["first"]["new_url"] == "/files/renders/series10_v2/ep01/S1/takes/image_001_new.png"


def test_video_index_url_old_rel_resolves(v2data):
    """W36：video_index._url 同口径——旧 rel 指向已迁移文件 → 出 url；V1 文件 → None"""
    from ns_api import video_index as VI
    assert VI._url("renders/ep01/S2/takes/image_001_moved.png") == "/files/renders/series10_v2/ep01/S2/takes/image_001_moved.png"
    assert VI._url("renders/ep01/S3/takes/image_001_v1.png") is None
