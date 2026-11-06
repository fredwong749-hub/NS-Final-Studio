"""UIUX-LOOP r5（11-06）：① 尾帧兜底（I2VA）的镜：总览标签 / 五态 / 板块都不再把尾帧算缺、算过期；
② 登记表已排进重出（ready / running）的旧版本 = 进行中，不是“过期”（main5 同口径）；③ 修改记录 at 给页面一律 JST。全部临时目录。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import frame_edit_queue as FEQ  # noqa: E402
from ns_api import shot_status as SS  # noqa: E402

FB = {"mode": "i2va", "first_n": 14, "why": "尾帧 24h 硬上限、无有效尾帧 → I2VA 兜底"}


def _reg(tmp_path, monkeypatch, objs):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S8", "index": 8, "objects": objs}]}]}), encoding="utf-8")
    monkeypatch.setattr(SS, "REGISTRY", reg)
    monkeypatch.setattr(SS, "_reg", {"mt": None, "val": {}})
    monkeypatch.setattr(SS, "_REG_EP", {"mt": None, "val": {}})


def test_fallback_shot_has_no_last_stage_tags_and_block_is_done(tmp_path, monkeypatch):
    takes = {"active": {"image": 14}, "last_frame_fallback": FB, "takes": [{"stage": "image", "n": 14}, {"stage": "last", "n": 18, "params": {"vqa_rounds": [{"judge": {"verdict": "fail", "failed_checks": ["Q1"]}}]}}]}
    cand = {"image": {"active": 14, "takes": [{"n": 14, "script": "current"}]}, "last": {"active": None, "takes": [{"n": 18, "script": "old"}]}}
    _reg(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 14}, "last": {"status": "ready", "stale": True}, "video": {"status": "pending", "waiting_for": "尾帧定下"}})
    st = SS.tags_for("ep01-S8", cand, takes)
    assert st["last_fallback"] is True and not any(t["stage"] == "尾帧" for t in st["tags"])
    assert st["main"] == "ok" and st["step"] == "video"           # 五态跳过尾帧，看视频
    blk = SS.episode_blocks(1, [{"id": "ep01-S8", "status": st}])
    assert {g["key"]: g["state"] for g in blk["stages"]}["last"] == "done" and blk["state"] != "stale"


def test_requeued_old_version_is_doing_not_stale(tmp_path, monkeypatch):
    """S9 现场：当前尾帧 v3 是首帧换过之前出的（old 标签），登记表 last=ready“跟着重出” → 板块尾帧 = 进行中；登记表 pending 且 stale → 过期"""
    cand = {"image": {"active": 22, "takes": [{"n": 22, "script": "current"}]}, "last": {"active": 3, "takes": [{"n": 3, "script": "old"}]}}
    takes = {"active": {"image": 22, "last": 3}, "takes": []}
    _reg(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 22}, "last": {"status": "ready", "reason": "首帧换过，尾帧作废"}})
    st = SS.tags_for("ep01-S8", cand, takes)
    assert any(t["kind"] == "old" for t in st["tags"]) and st["main5"] == "doing"
    assert {g["key"]: g["state"] for g in SS.episode_blocks(1, [{"id": "ep01-S8", "status": st}])["stages"]}["last"] == "doing"
    _reg(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 22}, "last": {"status": "pending", "stale": True}})
    st = SS.tags_for("ep01-S8", cand, takes)
    assert {g["key"]: g["state"] for g in SS.episode_blocks(1, [{"id": "ep01-S8", "status": st}])["stages"]}["last"] == "stale"


def test_edit_record_at_is_jst_for_pages(monkeypatch):
    import time
    naive = "2026-11-06T04:05:06"      # 本机时区的裸字符串（time.strftime）
    out = FEQ.to_jst(naive)
    exp = time.mktime(time.strptime(naive, "%Y-%m-%dT%H:%M:%S")) + 9 * 3600
    assert out == time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(exp))
    assert FEQ.to_jst(None) is None and FEQ.to_jst("garbage") == "garbage"
