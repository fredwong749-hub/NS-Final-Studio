"""K-OPS-A01 制作自动推进、人类只处理闸门（PRODUCER，总调度 11-01）。

项目方原话：“自动执行对应制作,人类不应该点,坏了,系统自动做”。纯 CPU、临时目录、假出图 / 假视频：
  1. 一镜从首帧 → 尾帧 → 视频，全程没有任何人工操作；
  2. 注入：隧道 502（基础设施）不计次；内容不过 3 次 → 尽力，带人话原因；尾帧第 1 次不过 → 第 2 次过；
  3. 错误分类与租约互斥。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import producer as PR  # noqa: E402

pytestmark = pytest.mark.skipif(not (ROOT / "data" / "import" / "script_v2.json").exists(), reason="系统剧本不在本机")


def _run(tmp_path, inject):
    dest = tmp_path / "out.json"
    assert PR.dryrun(inject_fail=inject, dest=dest) == 0
    return json.loads(dest.read_text(encoding="utf-8"))


def test_chain_advances_without_clicks(tmp_path):
    d = _run(tmp_path, False)
    f = d["final"]["ep01-S1"]
    assert [f[k]["status"] for k in ("first", "last", "video")] == ["passed", "passed", "passed"]
    evs = [x["ev"] for x in d["log"]]
    assert evs.index("dispatch") < evs.index("passed") < evs.index("video_dispatch") < evs.index("video_done")
    assert all(x["comfy_tag"]["agent"] == "PRODUCER" for x in d["log"] if x["ev"] == "dispatch")


def test_ladder_and_infra(tmp_path):
    d = _run(tmp_path, True)
    s2 = d["final"]["ep01-S2"]["first"]
    assert s2["status"] == "best_effort" and s2["attempts"] == 3 and "不设为当前" in s2["reason"] and "不进合成" in s2["reason"]
    infra = [x for x in d["log"] if x["ev"] == "infra_error"]
    assert infra and infra[0]["counted"] is False and "不算一次尝试" in infra[0]["reason"]
    rungs = [x["rung"] for x in d["log"] if x["ev"] == "dispatch" and x["obj"] == "first:ep01-S2"]
    assert rungs[-1].startswith("第 3 次") and "换 seed" in rungs[-2]
    assert d["final"]["ep01-S1"]["last"]["status"] == "passed" and d["final"]["ep01-S1"]["last"]["attempts"] == 2
    assert d["final"]["ep01-S2"]["last"]["status"] == "best_effort"


def test_classify_and_lease(tmp_path):
    assert PR.classify("ComfyUnavailable: /prompt: [WinError 10061] connection refused") == "infra"
    assert PR.classify("ComfyError: 执行失败: CUDA out of memory") == "infra"
    assert PR.classify("ep01-S1 生成契约 preflight 不通过，未提交：缺身份参考") == "preflight"
    assert PR.classify("契约没过：Q1") == "content"
    L = PR.Leases(PR.Paths(root=tmp_path, pd=tmp_path / "pd"))
    assert L.acquire("first:ep01-S1", lane="gpu33:0")
    assert not L.acquire("first:ep01-S1", lane="gpu33:1")      # 同一对象不重复提交
    L.release("first:ep01-S1")
    assert L.acquire("first:ep01-S1", lane="gpu33:1")


def test_import_identity_guard(tmp_path, monkeypatch):
    """总调度 11-01：/api/script-inbox/import 的 PRODUCER 系统身份——令牌 + run；不能“仍然导入”；
    replace 遇到项目方定稿 = 推翻旧决定，仍是项目方闸门；control auto_import=false 即关"""
    import json as _j
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from fastapi import HTTPException
    from ns_api import script_inbox as SI
    monkeypatch.setattr(SI, "DATA", tmp_path)
    monkeypatch.setattr(SI, "PRODUCER_TOKEN", tmp_path / "producer" / "import_token")
    (tmp_path / "producer").mkdir()
    (tmp_path / "producer" / "import_token").write_text("tok", encoding="utf-8")

    class B:
        by, run, token, accept_blocking, mode = "PRODUCER", "series10_v1", "tok", False, "merge"

    SI._producer_guard(B())                                       # 正常：通过
    for k, v in (("token", "bad"), ("run", None), ("accept_blocking", True)):
        b = B()
        setattr(b, k, v)
        with pytest.raises(HTTPException):
            SI._producer_guard(b)
    tj = tmp_path / "renders" / "ep01" / "S1" / "takes.json"
    tj.parent.mkdir(parents=True)
    tj.write_text(_j.dumps({"takes": [], "active": {}, "locked": {"image": 2}}), encoding="utf-8")
    b = B()
    b.mode = "replace"
    with pytest.raises(HTTPException) as e:
        SI._producer_guard(b)
    assert "推翻旧决定" in str(e.value.detail)
    (tmp_path / "producer" / "control.json").write_text(_j.dumps({"auto_import": False}), encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        SI._producer_guard(B())
    assert "已关闭" in str(e.value.detail)


def test_train_lock_blocks_dispatch(tmp_path):
    """K-OPS-A02（IMGPERF 11-01）：有 train.lock.gpuN 的卡不派；锁还没读到过也不派；出发前现读到锁 → 不提交、不计次、换道"""
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    lanes = {"gpu33:0": "fake://0", "gpu33:1": "fake://1", "gpu36:0": "fake://2"}
    pr = PR.Producer(paths, script=object(), lanes=lanes, lane_probe=lambda url: {"ok": True, "n": 0, "agents": []},
                     train_locks_fn=lambda srv: {1} if srv == "gpu33" else None, lock_now_fn=lambda lane: lane == "gpu33:0")
    st = pr.probe_lanes({"hold_lanes": []})
    assert st["gpu33:0"]["free"] and not st["gpu33:1"]["free"] and "训练锁" in st["gpu33:1"]["why"]
    assert not st["gpu36:0"]["free"] and "还没读到" in st["gpu36:0"]["why"]

    class Boom:
        def render(self, *a, **k):
            raise AssertionError("锁着的卡不应提交")

    pr.frames = Boom()
    o = {"id": "first:ep01-S1", "shot": "ep01-S1", "kind": "first", "ep": 1}
    assert pr.leases.acquire(o["id"], lane="gpu33:0")
    pr._run_one(o, "gpu33:0", 1, {"name": "第 1 次", "seed": 1}, {})
    led = pr.ledger()[o["id"]]
    assert led.get("infra") == 1 and not led.get("tries") and "gpu33:0" in led["lanes_failed"] and "训练" in led["reason"]
    assert pr.lane_cool["gpu33:0"] > PR.now()


def test_unmeasured_contract_is_infra_not_content():
    """gpu33 打分 OOM → 退回本机、关键项 untested：算“没量成”（基础设施），不算内容不过"""
    bad = {"ok": False, "remote_error": "CUDA out of memory", "blocking": ["Q1", "Q5"],
           "items": [{"id": "Q1", "status": "untested"}, {"id": "Q5", "status": "untested"}]}
    real = {"ok": False, "blocking": ["Q5"], "items": [{"id": "Q5", "status": "fail"}]}
    mixed = {"ok": False, "remote_error": "x", "blocking": ["Q5"], "items": [{"id": "Q5", "status": "fail"}]}
    assert PR.score_unmeasured(bad) and not PR.score_unmeasured(real) and not PR.score_unmeasured(mixed)


def test_ledger_reconciles_with_takes_every_loop(tmp_path):
    """DATAALIGN 11-01：账本记“已通过”、但 takes.json 里这一版已被重打分撤下 → 每轮都对账：清次数、重新给 3 次（不等重启）"""
    import json as _j
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True)
    _j.dump({"first:ep01-S1": {"final": "passed", "tries": 3, "history": [{"try": 3, "take": 2, "ok": True}]},
             "first:ep01-S2": {"final": "passed", "tries": 1}}, open(paths.ledger, "w", encoding="utf-8"))

    class W:
        def takes(self, sid):
            ok = sid == "ep01-S2"
            return {"active": {"image": 2} if ok else {}, "takes": [{"stage": "image", "n": 2, "postflight": {"ok": ok}}]}

    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    pr.reconcile_demoted(W())
    L = pr.ledger()
    assert L["first:ep01-S1"]["tries"] == 0 and L["first:ep01-S1"]["final"] is None and L["first:ep01-S1"]["demoted_at"]
    assert L["first:ep01-S2"]["final"] == "passed"
    src = (ROOT / "tools" / "autopilot" / "producer.py").read_text(encoding="utf-8")
    assert "self.reconcile_demoted(w)" in src.split("def tick", 1)[1].split("def _tasks", 1)[0]   # 每轮 tick 都调


def test_ledger_follows_promotions(tmp_path):
    """D-LEDGER：总调度 approve 换上 v6、v2 被驳回 → 下一轮账本最后一条 ok 记录指向 v6"""
    import json as _j
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True)
    _j.dump({"first:ep02-S1": {"final": "passed", "tries": 1, "history": [{"try": 1, "take": 2, "ok": True}]}},
            open(paths.ledger, "w", encoding="utf-8"))

    class W:
        def takes(self, sid):
            return {"active": {"image": 6}, "takes": [
                {"stage": "image", "n": 2, "postflight": {"ok": True}, "master_reject": {"reason": "塑料感"}},
                {"stage": "image", "n": 6, "postflight": {"ok": True}, "master_review": {"ok": True}}]}

    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    pr.reconcile_demoted(W())
    r = pr.ledger()["first:ep02-S1"]
    okh = [h for h in r["history"] if h.get("ok")]
    assert okh[-1]["take"] == 6 and "驳回" in okh[-1]["note"] and "复核通过" in okh[-1]["note"] and r["final"] == "passed"
    pr.reconcile_demoted(W())                                   # 幂等
    assert len(pr.ledger()["first:ep02-S1"]["history"]) == len(r["history"])


def test_rescore_flip_resets_attempts_even_if_not_passed_in_ledger(tmp_path):
    """REFLOCK 11-01：别的会话重打分把“过”改成“不过”（postflight.rescored.was_ok）→ 门槛变化前用掉的次数清零"""
    import json as _j
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True)
    _j.dump({"first:ep02-S3": {"tries": 2, "history": [{"try": 1, "take": 1, "ok": False, "at": "2026-11-01T07:00:00"},
                                                        {"try": 2, "take": 3, "ok": False, "at": "2026-11-01T07:56:45"}]}},
            open(paths.ledger, "w", encoding="utf-8"))

    class W:
        def takes(self, sid):
            return {"active": {}, "takes": [{"stage": "image", "n": 2, "postflight": {"ok": False, "rescored": {
                "was_ok": True, "at": "2026-11-01T07:54:55"}}}]}

    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    pr.reconcile_demoted(W())
    r = pr.ledger()["first:ep02-S3"]
    assert r["tries"] == 1 and r["demoted_at"] == "2026-11-01T07:54:55"
    pr.reconcile_demoted(W())
    assert pr.ledger()["first:ep02-S3"]["tries"] == 1                       # 只清一次


def test_ledger_never_syncs_master_rejected_current(tmp_path):
    """K-OPS-Q23 / 总调度 11-01：当前版本带 master_reject → 不当“已通过”同步进账本"""
    import json as _j
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True)
    _j.dump({"first:ep02-S1": {"final": None, "tries": 1, "history": [{"try": 1, "take": 1, "ok": False}]}},
            open(paths.ledger, "w", encoding="utf-8"))

    class W:
        def takes(self, sid):
            return {"active": {"image": 2}, "takes": [
                {"stage": "image", "n": 2, "postflight": {"ok": True}, "master_reject": {"reason": "不像"}}]}

    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    pr.reconcile_demoted(W())
    r = pr.ledger()["first:ep02-S1"]
    assert not any(h.get("ok") for h in r.get("history") or []) and r.get("final") != "passed"


def _p_shot(tmp_path, monkeypatch, takes, active):
    sys.path.insert(0, str(ROOT / "services" / "render_router"))
    from ns_render import pipeline as P
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    d = tmp_path / "renders" / "ep99" / "S1"
    (d / "takes").mkdir(parents=True)
    for t in takes:
        (tmp_path / t["file"]).write_bytes(b"x" * 10)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")
    return P


def test_master_reject_clears_current_immediately_and_approve_audits_once(tmp_path, monkeypatch):
    """总调度 11-01（G0）：驳回即撤下当前版本；approve 走 set_active / clear_active，每次变化只记一条审计"""
    tk = lambda n, st="image", **kw: {"n": n, "stage": st, "file": f"renders/ep99/S1/takes/{st}_{n:03d}.png", **kw}
    P = _p_shot(tmp_path, monkeypatch, [tk(1), tk(2), tk(1, "last")], {"image": 1, "last": 1})
    from ns_render import frame_edit as FE
    monkeypatch.setattr(FE, "annotate", lambda sid, st, n, **kw: [t.update(kw) for d in [P.load_takes(sid)] for t in d["takes"]
                                                                  if t["stage"] == st and t["n"] == n] and None)
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True)
    PR.master_reject(paths, "first:ep99-S1", 1, "不像", [], None, "总调度")
    assert "image" not in (P.load_takes("ep99-S1").get("active") or {})
    PR.master_approve(paths, "first:ep99-S1", 2, "总调度", "ok")
    act = P.load_takes("ep99-S1")["active"]
    assert act.get("image") == 2 and "last" not in act                    # 首帧换了 → 旧尾帧撤下
    rows = [json.loads(x) for x in (tmp_path / "producer" / "current_changes.jsonl").read_text(encoding="utf-8").splitlines()]
    pairs = [(r["stage"], r["from"], r["to"]) for r in rows]
    assert pairs == [("image", 1, None), ("image", None, 2), ("last", 1, None)]
    assert all("producer.master_" in r["actor"] for r in rows)
