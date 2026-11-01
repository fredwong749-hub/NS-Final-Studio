"""离线 / 远端运行前依赖自检（K-OPS-W02 / W03，WORKFLOW 11-01）：tools/pipeline/remote_preflight.py + ops/offline/merge_pull.py 防截断。
全部在临时目录里造一个迷你仓库根，不读写真实 data/。"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/pipeline"))
import remote_preflight as RP  # noqa: E402


def _png(p: Path, truncate: bool = False):
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (120, 30, 200)).save(p)
    if truncate:
        b = p.read_bytes()
        p.write_bytes(b[: len(b) // 2])


def _repo(tmp: Path, *, bad_sheet=False, tts=True, series="proj_v1"):
    _png(tmp / "data/faces/a.png")
    _png(tmp / "data/sheets/a_lookA.png", truncate=bad_sheet)
    (tmp / "run/assets").mkdir(parents=True)
    (tmp / "run/assets/sheets_chosen.json").write_text(json.dumps({"a": {"A": "data/sheets/a_lookA.png"}}), encoding="utf-8")
    (tmp / "config/recipes").mkdir(parents=True)
    (tmp / "config/recipes/asset_refs.json").write_text(json.dumps({"projects": {"proj_v1": {
        "run_dir": "run", "sheets_file": "run/assets/sheets_chosen.json", "faces": {"a": ["data/faces/a.png"]}}}}), encoding="utf-8")
    py = tmp / "speech/python.exe"
    if tts:
        py.parent.mkdir(parents=True)
        py.write_text("x")
    (tmp / "config/voices.json").write_text(json.dumps({"series": series, "speech_python": {
        "env": "NS_TTS_PYTHON_TEST_UNSET", "default": str(py)}}), encoding="utf-8")
    return tmp


def _row(res, cid):
    return next(r for r in res["rows"] if r["id"] == cid)


def test_all_good_passes(tmp_path):
    res = RP.run(_repo(tmp_path))
    assert res["verdict"] == "pass", res


def test_truncated_sheet_fails(tmp_path):
    res = RP.run(_repo(tmp_path, bad_sheet=True))
    a1 = _row(res, "A1")
    assert res["verdict"] == "fail" and a1["status"] == "fail" and "读不全" in a1["bad"][0]


def test_missing_tts_and_series_fail(tmp_path):
    res = RP.run(_repo(tmp_path, tts=False, series="old_60"))
    assert _row(res, "T1")["status"] == "fail" and _row(res, "T2")["status"] == "fail"


def test_night_stall_detected(tmp_path):
    root = _repo(tmp_path)
    v = root / "run/video"
    v.mkdir(parents=True)
    (v / "night.pid").write_text("999999")
    st = v / "night_state.json"
    st.write_text("{}")
    old = time.time() - 3600
    os.utime(st, (old, old))
    res = RP.run(root, runtime=True, stall_min=30)
    assert _row(res, "H1")["status"] == "fail"
    os.utime(st, None)
    assert _row(RP.run(root, runtime=True, stall_min=30), "H1")["status"] == "pass"


def test_merge_pull_refuses_truncated_prefix(tmp_path):
    spec = importlib.util.spec_from_file_location("merge_pull", ROOT / "ops/offline/merge_pull.py")
    MP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MP)
    good = tmp_path / "local.png"
    _png(good)
    part = tmp_path / "pulled.png"
    part.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    assert MP.pulled_problem(part, good)                       # 解码不全 / 截断前缀 → 不覆盖
    blob_local, blob_part = tmp_path / "a.bin", tmp_path / "b.bin"
    blob_local.write_bytes(b"0123456789" * 100)
    blob_part.write_bytes(b"0123456789" * 30)
    assert "截断前缀" in MP.pulled_problem(blob_part, blob_local)
    newer = tmp_path / "newer.png"
    Image.new("RGB", (32, 32)).save(newer)
    assert MP.pulled_problem(newer, good) is None


def _mp():
    spec = importlib.util.spec_from_file_location("merge_pull", ROOT / "ops/offline/merge_pull.py")
    MP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MP)
    return MP


def test_merge_objects_keeps_unwait_and_other_eps(tmp_path, monkeypatch):
    """K-OPS-Q20：master_rejects.json 这类多集共享表按对象合并——服务器副本较新的整文件不得盖掉笔记本对别的集 / 更晚的 unwait"""
    MP = _mp()
    monkeypatch.setattr(MP, "backup", lambda rel: None)
    local = {"first:ep10-S8": {"reject_n": 1, "wait": None, "cleared": {"at": "2026-11-01T11:30:00"}},   # 笔记本 unwait（更晚）
             "first:ep02-S1": {"reject_n": 2, "at": "2026-11-01T04:42:30"},
             "first:ep03-S7": {"reject_n": 2, "at": "2026-11-01T04:42:30"}}
    remote = {"first:ep10-S8": {"reject_n": 1, "wait": "总调度", "at": "2026-11-01T09:00:00"},               # 服务器旧值
              "first:ep02-S1": {"reject_n": 3, "at": "2026-11-01T12:00:00"},                                # 服务器本机集新值
              "first:ep03-S7": {"reject_n": 9, "at": "2026-11-01T12:00:00"},                                # 别的机器的集：不收
              "first:ep04-S2": {"reject_n": 1, "at": "2026-11-01T12:10:00"}}                                # 新对象
    src, dst = tmp_path / "r.json", tmp_path / "l.json"
    src.write_text(json.dumps(remote), encoding="utf-8")
    dst.write_text(json.dumps(local), encoding="utf-8")
    n = MP.merge_objects("data/producer/master_rejects.json", src, dst, "gpu36")
    out = json.loads(dst.read_text(encoding="utf-8"))
    assert out["first:ep10-S8"]["wait"] is None                  # unwait 没丢
    assert out["first:ep02-S1"]["reject_n"] == 3 and out["first:ep04-S2"]["reject_n"] == 1
    assert out["first:ep03-S7"]["reject_n"] == 2                 # ep03 归 gpu33，gpu36 副本里的误改不并回
    assert n == 2


def test_merge_objects_lists_and_keys(tmp_path, monkeypatch):
    MP = _mp()
    monkeypatch.setattr(MP, "backup", lambda rel: None)
    src, dst = tmp_path / "r.json", tmp_path / "l.json"
    dst.write_text(json.dumps({"note": "L", "keys": ["ep01-S6|image|2"], "objs": [{"obj": "first:ep02-S1", "at": "2026-11-01T09:00:00"}]}), encoding="utf-8")
    src.write_text(json.dumps({"note": "R", "keys": ["ep01-S6|image|2", "ep02-S3|image|4", "ep03-S1|image|1"],
                               "objs": [{"obj": "first:ep02-S1", "at": "2026-11-01T10:00:00", "x": 1}]}), encoding="utf-8")
    MP.merge_objects("data/producer/outer_suspects.json", src, dst, "gpu36")
    out = json.loads(dst.read_text(encoding="utf-8"))
    assert out["note"] == "L" and out["keys"] == ["ep01-S6|image|2", "ep02-S3|image|4"] and out["objs"][0]["x"] == 1


def test_mp4_without_moov_is_truncated(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100)
    assert "moov" in RP.file_problem(p)
