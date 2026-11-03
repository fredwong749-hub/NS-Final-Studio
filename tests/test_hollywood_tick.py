"""tools/pipeline/hollywood_tick.py：好莱坞质感分自动打分拍（低优先级、只在看图空闲时跑、结果给 episode_metrics 读）。
全部临时目录 + 假看图 / 假 /health，不碰真实 GPU、队列、data/。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


HT = _load("hollywood_tick_t", "tools/pipeline/hollywood_tick.py")
EM = _load("episode_metrics_t", "tools/master/episode_metrics.py")
RUN = "fx_run"
CFG = {**HT.DEFAULTS, "enabled": True, "max_per_tick": 2}
IDLE = {"queue": 0, "inflight": {}, "loaded": True, "instances": 1}
BUSY = {"queue": 1, "inflight": {"a": 1}, "loaded": True, "instances": 2}


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, bytes):
        p.write_bytes(obj)
    elif isinstance(obj, list):
        p.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in obj), encoding="utf-8")
    else:
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    aj = root / "data" / "pipeline" / "asset_jobs" / RUN
    _w(aj / "face-ch_a.json", {"schema": "nsfs.asset_job/1", "id": "face-ch_a", "kind": "face", "episode": 1, "episodes": [1], "state": "done",
                               "candidates": [{"key": "ch_a#1", "file": "data/review_pages/v2_cast/a1.png", "passed": True},
                                              {"key": "ch_a#2", "file": "data/review_pages/v2_cast/a2.png", "passed": False},
                                              {"key": "ch_a#3", "file": "data/review_pages/v2_cast/a3_missing.png", "passed": True}]})
    _w(aj / "sheet-ch_a-A.json", {"schema": "nsfs.asset_job/1", "id": "sheet-ch_a-A", "kind": "sheet", "episode": 1, "episodes": [1], "state": "awaiting_pick",
                                  "candidates": [{"key": "s1", "file": "data/ab/v2_assets/fx_run/sheet-ch_a-A/s1.png", "contract_ok": True}]})
    _w(aj / "golden-ep01-S01.json", {"schema": "nsfs.asset_job/1", "id": "golden-ep01-S01", "kind": "golden", "episode": 1, "state": "awaiting_pick",
                                     "spec": {"shot": 1}, "slots": [{"id": "s7", "state": "passed", "review_file": "data/review_pages/golden/ep01_S01_s7.png"},
                                                                    {"id": "s8", "state": "rejected", "review_file": "data/review_pages/golden/ep01_S01_s8.png"}]})
    _w(aj / "_ready_ep01.json", {"ready": False})
    _w(aj / "bad.json", b"{not json")
    # 阶段 A 账本：同一张图和 candidates 重复 → 去重
    _w(root / "data" / "ab" / "v2_assets" / RUN / "sheet-ch_a-A" / "takes.jsonl",
       [{"file": "ab/v2_assets/fx_run/sheet-ch_a-A/s1.png", "passed": True}, {"file": "ab/v2_assets/fx_run/sheet-ch_a-A/s0.png", "passed": False}])
    # 已登记金样首帧（第 2 集）
    _w(root / "data" / "pipeline" / "golden" / RUN / "ep02" / "S03.json", {"run": RUN, "episode": 2, "shot": 3, "file": "data/review_pages/golden/ep02_S03_s1.png"})
    for f in ("review_pages/v2_cast/a1.png", "review_pages/v2_cast/a2.png", "ab/v2_assets/fx_run/sheet-ch_a-A/s1.png",
              "review_pages/golden/ep01_S01_s7.png", "review_pages/golden/ep01_S01_s8.png", "review_pages/golden/ep02_S03_s1.png"):
        _w(root / "data" / f, b"png")
    return root


def _fake_generate(script: list[str]):
    calls = []

    def gen(req):
        calls.append(req["images"][0]["path"])
        assert "composition" in req["text"] and req["system"]
        txt = script.pop(0) if script else '{"composition": 7, "lighting": 8, "texture": 6, "performance": 7, "consistency": 9, "note": "ok"}'
        return {"text": txt, "model": "fake-vlm", "seconds": 1.0, "via": "http://127.0.0.1:8870"}
    gen.calls = calls
    return gen


def test_discover_and_pending_dedup(tmp_path):
    root = fixture(tmp_path)
    items = HT.discover(root, RUN)
    files = sorted(i["file"] for i in items)
    assert files == ["ab/v2_assets/fx_run/sheet-ch_a-A/s1.png", "review_pages/golden/ep01_S01_s7.png", "review_pages/golden/ep02_S03_s1.png",
                     "review_pages/v2_cast/a1.png", "review_pages/v2_cast/a3_missing.png"]
    by = {i["file"]: i for i in items}
    assert by["review_pages/v2_cast/a1.png"]["source"] == "cast_face" and by["review_pages/golden/ep01_S01_s7.png"]["source"] == "golden"
    assert by["review_pages/golden/ep02_S03_s1.png"] == {"file": "review_pages/golden/ep02_S03_s1.png", "source": "golden_registered", "episode": 2, "shot": 3}
    pend = HT.pending(root, RUN, CFG)
    assert [p["file"] for p in pend] == ["review_pages/golden/ep02_S03_s1.png", "review_pages/golden/ep01_S01_s7.png",
                                         "ab/v2_assets/fx_run/sheet-ch_a-A/s1.png", "review_pages/v2_cast/a1.png"]   # 文件不在的不排；登记首帧最先


def test_tick_respects_switch_and_idle(tmp_path):
    root = fixture(tmp_path)
    gen = _fake_generate([])
    r = HT.tick(root, [RUN], {**CFG, "enabled": False}, probe=lambda u: IDLE, generate=gen)
    assert r["skipped"].startswith("开关关着") and not gen.calls
    r = HT.tick(root, [RUN], CFG, probe=lambda u: BUSY, generate=gen)
    assert "忙" in r["skipped"] and r["pending"] == 4 and not gen.calls and not HT.ledger(root, RUN, 1).exists()
    r = HT.tick(root, [RUN], CFG, probe=lambda u: None, generate=gen)              # 两边都不在：不打
    assert "忙" in r["skipped"] and not gen.calls
    assert not HT.lock_path(root).exists()


def test_tick_scores_in_budget_then_yields(tmp_path):
    root = fixture(tmp_path)
    probes = iter([IDLE, IDLE, IDLE, IDLE, BUSY, BUSY, IDLE, IDLE])                 # 两边各探一次：第 1 张空闲、第 2 张空闲，下一拍第 1 张忙
    gen = _fake_generate(["乱回答"])
    r = HT.tick(root, [RUN], CFG, probe=lambda u: next(probes), generate=gen)
    assert len(gen.calls) == 2 and r["pending"] == 2
    assert [x["file"] for x in r["failed"]] == ["review_pages/golden/ep02_S03_s1.png"] and [x["file"] for x in r["scored"]] == ["review_pages/golden/ep01_S01_s7.png"]
    rows2 = [json.loads(l) for l in HT.ledger(root, RUN, 2).read_text(encoding="utf-8").splitlines()]
    assert rows2[0]["error"] and "scores" not in rows2[0] and rows2[0]["source"] == "golden_registered"
    rows1 = [json.loads(l) for l in HT.ledger(root, RUN, 1).read_text(encoding="utf-8").splitlines()]
    assert rows1[0]["scores"]["consistency"] == 9 and rows1[0]["mean"] == 7.4 and rows1[0]["model"] == "fake-vlm" and rows1[0]["shot"] == 1
    r = HT.tick(root, [RUN], CFG, probe=lambda u: next(probes), generate=gen)       # 这一拍看图忙 → 一张都不打
    assert len(gen.calls) == 2 and "忙" in r["skipped"]
    r = HT.tick(root, [RUN], {**CFG, "max_per_tick": 9}, probe=lambda u: IDLE, generate=gen)   # 失败那张重试 1 次，其余打完
    assert len(gen.calls) == 5 and r["pending"] == 0 and len(r["scored"]) == 3
    r = HT.tick(root, [RUN], {**CFG, "max_per_tick": 9}, probe=lambda u: IDLE, generate=gen)
    assert len(gen.calls) == 5 and r["pending"] == 0                                           # 都打过了，不重复
    # 失败满 max_attempts 的不再排
    gen2 = _fake_generate(["x", "y", "z"])
    root2 = fixture(tmp_path / "b")
    for _ in range(3):
        HT.tick(root2, [RUN], {**CFG, "max_per_tick": 1}, probe=lambda u: IDLE, generate=gen2)
    assert len(gen2.calls) == 3 and gen2.calls[0] == gen2.calls[1] and gen2.calls[2] != gen2.calls[0]   # 第 3 拍跳过失败满 2 次的那张


def test_force_and_lock(tmp_path):
    root = fixture(tmp_path)
    gen = _fake_generate([])
    HT.lock_path(root).parent.mkdir(parents=True, exist_ok=True)
    HT.lock_path(root).write_text("1")
    r = HT.tick(root, [RUN], CFG, probe=lambda u: IDLE, generate=gen)
    assert r["skipped"] == "另一份 hollywood_tick 在跑" and not gen.calls
    import os, time
    os.utime(HT.lock_path(root), (time.time() - 7200, time.time() - 7200))                                      # 2 小时前的陈旧锁
    r = HT.tick(root, [RUN], {**CFG, "lock_stale_s": 1800}, probe=lambda u: BUSY, generate=gen, force=True)  # 陈旧锁接管；--force 不等空闲
    assert len(gen.calls) == 2 and r["skipped"] is None


def test_episode_metrics_reads_ledger(tmp_path):
    root = fixture(tmp_path)
    gen = _fake_generate(['{"composition": 5, "lighting": 5, "texture": 5, "performance": 5, "consistency": 5}'])
    HT.tick(root, [RUN], {**CFG, "max_per_tick": 9}, probe=lambda u: IDLE, generate=gen)
    P = EM.Paths(root, RUN)
    nulls = EM.Nulls()
    h = EM.hollywood_read(P, 1, nulls)
    assert h["n"] == 3 and h["by_source"] == {"golden": 7.4, "sheet": 7.4, "cast_face": 7.4} and h["models"] == ["fake-vlm"] and h["failed_attempts"] == 0
    h2 = EM.hollywood_read(P, 2, nulls)
    assert h2["n"] == 1 and h2["mean"] == 5.0 and not nulls.items
    assert EM.hollywood_read(P, 3, nulls)["mean"] is None and nulls.items[0]["key"] == "quality.hollywood"


def test_parse_scores_and_cfg(tmp_path):
    assert HT.parse_scores('前言 {"composition": 7, "lighting": 8, "texture": 6, "performance": 7, "consistency": 9} 后记')["mean"] == 7.4
    assert HT.parse_scores('{"composition": 11, "lighting": 1, "texture": 1, "performance": 1, "consistency": 1}') is None
    assert HT.parse_scores('{"composition": true, "lighting": 1, "texture": 1, "performance": 1, "consistency": 1}') is None
    assert HT.parse_scores("没有 json") is None
    root = tmp_path / "r"
    assert HT.load_cfg(root)["enabled"] is False                                       # 没配置文件 = 关
    _w(root / HT.CFG_PATH, {"enabled": True, "max_per_tick": 3, "_doc": "x"})
    c = HT.load_cfg(root)
    assert c["enabled"] is True and c["max_per_tick"] == 3 and c["max_attempts"] == 2 and "_doc" not in c
    (root / HT.CFG_PATH).write_text("{bad", encoding="utf-8")
    c = HT.load_cfg(root)
    assert c["enabled"] is False and c["_config_error"]
    assert HT.tick(root, [RUN], c, probe=lambda u: IDLE, generate=_fake_generate([]))["errors"]


def test_real_config_is_sane():
    c = json.loads((ROOT / HT.CFG_PATH).read_text(encoding="utf-8"))
    assert c["require_idle"] is True and c["max_per_tick"] >= 1 and c["max_attempts"] >= 1
