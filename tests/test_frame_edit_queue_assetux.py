"""项目方 16:58 / 17:0x（L-123 延伸）：镜头“修改”永远被收下——立即 202、不在请求里跑改写 / 检查 / 出图；后台改写 → 检查（失败带原因自动重改 ≤2 次）
→ 交 producer 队列；还不过 = “需要你看一眼”（大白话，不出现技术词）。全部在临时目录里，不碰生产数据。"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import frame_edit_queue as Q
from ns_api import prompt_rewrite as PR

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "STATE", tmp_path / "reqs.json")
    reg = tmp_path / "registry.json"
    shots = []
    for i in range(1, 6):
        shots.append({"shot": f"ep01-S{i}", "index": i, "objects": {"first": {"id": f"first:ep01-S{i}", "status": "ready" if i in (2, 3) else "passed"},
                                                                    "last": {"id": f"last:ep01-S{i}", "status": "ready" if i == 4 else "passed", "redo": i == 4}}})
    shots.append({"shot": "ep02-S1", "index": 1, "objects": {"first": {"id": "first:ep02-S1", "status": "running"}, "last": {"id": "last:ep02-S1", "status": "ready", "redo": True}}})
    reg.write_text(json.dumps({"episodes": [{"ep": 1, "shots": shots[:5]}, {"ep": 2, "shots": shots[5:]}]}), encoding="utf-8")
    monkeypatch.setattr(Q, "REGISTRY", reg)
    monkeypatch.setattr(Q, "_reg", {"mt": None, "val": []})
    monkeypatch.setattr(Q, "PARTITION", tmp_path / "none.json")           # 读不到 → 3 条道
    monkeypatch.setattr(Q, "_eta", {"at": 1e18, "val": None})             # 默认不读真实的估时模块（测试自己的口径）
    kicked = []
    monkeypatch.setattr(Q, "_kick", lambda rid: kicked.append(rid))        # 路由测试里不起后台线程
    app = FastAPI()
    app.include_router(Q.router)
    return {"c": TestClient(app), "kicked": kicked, "tmp": tmp_path}


def test_submit_is_202_immediately_and_only_records(env):
    t0 = time.time()
    r = env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "first", "n": 3, "text": "男主角穿了女孩子的衣服了，错误的地方", "chips": ["衣服鞋子按设定"]})
    dt = time.time() - t0
    assert r.status_code == 202 and dt < 0.3, dt                           # 目标 300 ms 内
    j = r.json()
    rows = json.loads((env["tmp"] / "reqs.json").read_text(encoding="utf-8"))
    assert rows[0]["text"] == "男主角穿了女孩子的衣服了，错误的地方" and rows[0]["chips"] == ["衣服鞋子按设定"] and rows[0]["base_n"] == 3 and rows[0]["state"] == "received"
    assert env["kicked"] == [j["id"]]                                      # 只是交给后台，请求里没跑改写 / 检查
    assert j["queue"]["pos"] == 2                                          # 前面还有 last:ep01-S4（集内插队 / 尾帧先）
    assert env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "video", "text": "x"}).status_code == 422


def test_queue_order_is_e30_and_positions_and_eta(env):
    s = env["c"].get("/api/frame-queue").json()
    order = [(i["oid"], i["state"], i["pos"]) for i in s["items"]]
    assert order == [("first:ep02-S1", "running", 0), ("last:ep01-S4", "queued", 1), ("first:ep01-S2", "queued", 2), ("first:ep01-S3", "queued", 3),
                     ("last:ep02-S1", "queued", 4)]                        # 按集、集内插队先、尾帧先、镜号；在跑的排最前
    assert s["running"] == 1 and s["queued"] == 4 and s["lanes"] == 3 and s["per_shot_s"] == 740
    eta = {i["oid"]: i["eta_at"] for i in s["items"]}
    assert eta["first:ep01-S2"] == eta["last:ep01-S4"]                     # 在跑 1 + 排第 1、2 个 = 3 条道的第 1 波
    assert (eta["first:ep01-S3"] - eta["last:ep01-S4"]) == pytest.approx(740, abs=2)       # 第 3、4 个 = 第 2 波
    assert eta["last:ep02-S1"] == eta["first:ep01-S3"]


def test_order_key_matches_producer_episode_order_key():
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    try:
        import producer as PD
    except Exception:  # noqa: BLE001  producer 依赖本机环境，导不进来就只测公式
        pytest.skip("producer 不可导入")
    for ep, k, idx, redo in [(1, 0, 4, True), (1, 1, 2, False), (2, 0, 1, True), (1, 0, 9, False)]:
        mine = Q.order_key({"ep": ep, "kind": "last" if k == 0 else "first", "idx": idx, "redo": redo})
        assert mine == PD.episode_order_key((ep, k, idx, {"redo": redo}))


def good_check(ctx, instruction):
    return []


def test_worker_rewrites_checks_then_submits_to_producer(env, monkeypatch):
    rid = env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "first", "text": "顾沉穿成女装了"}).json()["id"]
    sent = {}
    seen = []

    def rw(kind, text, ctx, chat=None):
        seen.append((kind, dict(ctx)))
        return {"prompt": "只把画面右侧顾沉的上衣改成他自己的男式白衬衫，去掉女装元素，其余保持不变。", "negative_add": "", "zh_summary": "把顾沉的衣服改回男装", "model": "m"}

    res = Q.process(rid, rewrite=rw, check=good_check, ctx_fn=lambda s, st, n: {"prompt": "原提示词", "spec": {"cast": ["林晚", "顾沉"]}},
                    submit_fn=lambda oid, why, plan, edit, by: sent.update(oid=oid, why=why, plan=plan, edit=edit) or {"ok": True})
    assert res["state"] == "queued" and sent["oid"] == "first:ep01-S2" and "顾沉穿成女装了" in sent["why"]
    assert sent["edit"]["prompt"].startswith("只把画面右侧顾沉") and sent["edit"]["zh_summary"] == "把顾沉的衣服改回男装"
    assert seen[0][0] == "shot_frame" and seen[0][1]["base_prompt"] == "原提示词" and "顾沉" in seen[0][1]["cast"]    # 改写带着这一镜的编译稿和站位
    st = env["c"].get("/api/shots/ep01-S2/frame-edits").json()["edits"][0]
    assert st["zh_summary"] == "把顾沉的衣服改回男装" and st["state"] == "queued" and st["pos"] == 2


def test_check_failure_auto_rewrites_with_reason_twice_then_needs_look_in_plain_words(env):
    rid = env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "first", "text": "x"}).json()["id"]
    calls = []

    def rw(kind, text, ctx, chat=None):
        calls.append(ctx.get("fail_reason"))
        return {"prompt": "修改要求" * 8, "negative_add": "", "zh_summary": "s", "model": "m"}
    res = Q.process(rid, rewrite=rw, check=lambda c, i: ["画面里的人物和站位没有写清楚"], ctx_fn=lambda *a: {"prompt": "p"},
                    submit_fn=lambda *a: pytest.fail("检查没过不该交队列"))
    assert res["state"] == "needs_look" and len(calls) == 3 and calls[0] is None and "站位" in calls[1] and "站位" in calls[2]   # 最多自动重改 2 次，带着原因
    st = env["c"].get("/api/shots/ep01-S2/frame-edits").json()["edits"][0]
    assert st["state"] == "needs_look" and st["word"] == "需要你看一眼" and "站位" in st["msg"] and not Q.TECH.search(st["msg"] + st["word"])


def test_second_attempt_passes_after_fix(env):
    rid = env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "first", "text": "x"}).json()["id"]
    n = {"i": 0}

    def chk(c, i):
        n["i"] += 1
        return ["修改要求里有系统不允许的词（旧的出图风格词）"] if n["i"] == 1 else []
    sent = {}
    res = Q.process(rid, rewrite=lambda k, t, c, chat=None: {"prompt": "修改要求" * 8, "negative_add": "", "zh_summary": "s", "model": "m"}, check=chk,
                    ctx_fn=lambda *a: {"prompt": "p"}, submit_fn=lambda oid, why, plan, edit, by: sent.update(ok=1) or {"ok": True})
    assert res["state"] == "queued" and sent and n["i"] == 2


def test_gateway_down_never_drops_the_request(env):
    rid = env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "last", "text": "手再自然一点"}).json()["id"]

    def boom(kind, text, ctx, chat=None):
        raise PR.RewriteError("网关挂了")
    res = Q.process(rid, rewrite=boom, ctx_fn=lambda *a: {}, submit_fn=lambda *a: pytest.fail("不该交队列"))
    assert res["state"] == "needs_look"
    rows = json.loads((env["tmp"] / "reqs.json").read_text(encoding="utf-8"))
    assert rows[0]["text"] == "手再自然一点"                                # 原话还在
    assert "写作助手" in rows[0]["note"]


def test_seed_only_skips_rewrite_and_submits(env):
    rid = env["c"].post("/api/shots/ep01-S2/frame-edit", json={"stage": "first", "text": ""}).json()["id"]
    sent = {}
    res = Q.process(rid, rewrite=lambda *a, **k: pytest.fail("只换种子不需要改写"), submit_fn=lambda oid, why, plan, edit, by: sent.update(edit=edit) or {"ok": True})
    assert res["state"] == "queued" and sent["edit"]["prompt"] == ""


def test_plain_words_have_no_technical_terms():
    for items in ([{"id": "I1", "status": "fail"}, {"id": "I7", "status": "fail"}, {"id": "I99", "status": "fail"}],):
        for w in Q.plain(items):
            assert not Q.TECH.search(w), w
    assert all(not Q.TECH.search(v) for v in Q.PLAIN.values())


def test_apply_owner_edit_appends_and_keeps_refs():
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    try:
        import producer as PD
    except Exception:  # noqa: BLE001
        pytest.skip("producer 不可导入")
    job = {"prompt": "图1是林晚的脸部参考。中景。", "refs": ["a.png"]}
    out = PD.apply_owner_edit(job, {"id": "fe-1", "prompt": "只把顾沉的上衣改成白衬衫，其余保持不变。"})
    assert out["prompt"].startswith(job["prompt"]) and "只把顾沉的上衣改成白衬衫" in out["prompt"] and out["refs"] == ["a.png"] and out["owner_edit"] == "fe-1"
    assert PD.apply_owner_edit(job, {"id": "x", "prompt": ""}) is job and PD.apply_owner_edit(job, None) is job
    assert PD.apply_owner_edit(out, {"id": "fe-1", "prompt": "只把顾沉的上衣改成白衬衫，其余保持不变。"}) is out        # 重复应用不叠加


def test_edits_anchor_no_longer_carries_banned_suffix_words():
    """17:0x 根因回归：编译稿的角色锁段（取 200 字）里夹着旧出图后缀（“奶油般柔焦虚化”）→ 以前被检查拒收；现在锁段先去掉含禁用词的分句"""
    from ns_api import edits as E
    plan = {"action": "edit", "instruction": "只改顾沉的衣服。"}
    ctx = {"compiled_prompt": "前言【林晚】22岁中国成年女性，蓝发及腰，前景与背景奶油般柔焦虚化，真人写实，手指甲为5厘米超长透明水晶甲，镶满钻石饰品，【顾沉】34岁成年男性CEO，成熟克制英俊，中景"}
    ins = E.compose_instruction(plan, ctx)
    assert "奶油" not in ins and "柔焦" not in ins and "林晚" in ins and any("角色锁段" in f for f in plan.get("fixes", []))


def test_real_eta_table_overrides_rough_estimate_and_flags_stale(env):
    now = time.time()
    Q._eta.update(at=1e18, val={"basis": {"stale": True}, "objects": {"last:ep01-S4": {"eta_s": now + 100, "pos": 1}, "first:ep01-S2": {"eta_s": now + 900, "pos": 2}}})
    s = env["c"].get("/api/frame-queue").json()
    eta = {i["oid"]: i["eta_at"] for i in s["items"]}
    assert eta["last:ep01-S4"] == pytest.approx(now + 100, abs=1) and eta["first:ep01-S2"] == pytest.approx(now + 900, abs=1)
    assert s["stale"] is True                                                    # 界面要写“数据可能过期”
    assert env["c"].get("/api/queue_eta").status_code == 200
    Q._eta.update(at=1e18, val=None)
    assert env["c"].get("/api/queue_eta").status_code == 503
