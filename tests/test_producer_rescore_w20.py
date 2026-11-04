"""W20（MASTER-WSL 11-03）：受控重启后 heartbeat inflight=7 / rendering=7、9 分钟零 dispatch。

根因：7 个“只重打分”（打分超时 / score_infra 后 rescore_take）单塞进出图线程池、inflight 里记 lane=None，
心跳 rendering = inflight - scoring 把它们算成“在出图”；隧道断时 _postflight 卡在 ssh / 退回 CPU 慢算，没有时限，
回来又是 score_infra → 10 分钟后再派，无限占位。另：B 档 faces_board（frames_v2.two_person_board）只认 kind=="face"，
三人镜的脸板被丢 → preflight I2。
"""
import json
import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import producer as PR  # noqa: E402


def _pr(tmp_path, ledger=None):
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True, exist_ok=True)
    if ledger:
        paths.ledger.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    return pr, paths


def _reg(*objs):
    return {"episodes": [{"ep": 1, "shots": [{"shot": o["shot"], "index": 1, "objects": {"first": o}} for o in objs]}]}


def _o(sid, **kw):
    return {"id": f"first:{sid}", "kind": "first", "shot": sid, "ep": 1, "status": "ready", "waiting_for": "空闲道", **kw}


def _events(paths):
    return [json.loads(x) for x in paths.log.read_text(encoding="utf-8").splitlines() if x.strip()] if paths.log.exists() else []


def test_rescore_counts_as_scoring_not_rendering_and_needs_no_lane(tmp_path):
    pr, paths = _pr(tmp_path, {"first:ep01-S3": {"rescore_take": 2}})
    gate = threading.Event()
    pr._rescore_one = lambda o, n: gate.wait(5)          # 模拟卡在打分链路
    assert pr.dispatch_rescores(_reg(_o("ep01-S3"))) == 1  # lanes={}：没有空闲道照样派（不占道）
    hb = pr.hb_counts()
    assert hb["inflight"] == 1 and hb["scoring"] == 1 and hb["rescoring"] == 1 and hb["rendering"] == 0
    assert any(e["ev"] == "rescore_dispatch" for e in _events(paths))
    assert pr.dispatch_rescores(_reg(_o("ep01-S3"))) == 0   # 在途不重复派
    gate.set()
    pr.rescore_pool.shutdown(wait=True)


def test_dispatch_frames_never_puts_rescore_in_render_pool(tmp_path):
    src = (ROOT / "tools" / "autopilot" / "producer.py").read_text(encoding="utf-8")
    body = src.split("    def dispatch_frames", 1)[1].split("    def sop_gate_block", 1)[0]
    assert "_rescore_one" not in body and "dispatch_rescores" in body
    tick = src.split("    def tick(self", 1)[1].split("    def hb_counts", 1)[0]
    assert "self.dispatch_rescores(reg)" in tick and "self.reap_rescores()" in tick and "self.hb_counts()" in tick


def test_reap_timeout_releases_slot_backs_off_and_trips_breaker(tmp_path):
    pr, paths = _pr(tmp_path, {"first:ep01-S5": {"rescore_take": 2}})
    gate = threading.Event()
    pr._rescore_one = lambda o, n: gate.wait(5)
    assert pr.dispatch_rescores(_reg(_o("ep01-S5"))) == 1
    pr.inflight["first:ep01-S5"]["since"] -= 10
    assert pr.reap_rescores(timeout_s=1) == ["first:ep01-S5"]
    assert pr.hb_counts() == {"inflight": 0, "scoring": 0, "rescoring": 0, "rendering": 0}
    led = pr.ledger()["first:ep01-S5"]
    assert led["rescore_infra"] == 1 and led["backoff_until"] > PR.now() + 200 and led["rescore_take"] == 2   # 不计次、不重出
    assert pr.leases.get("first:ep01-S5") is None
    assert pr._score_down_until > PR.now()
    evs = [e["ev"] for e in _events(paths)]
    assert "rescore_timeout" in evs and "score_chain_down" in evs
    # 熔断期 + 线程还没回来：都不重派
    pr.led_update("first:ep01-S5", backoff_until=0)
    assert pr.dispatch_rescores(_reg(_o("ep01-S5"))) == 0
    pr._score_down_until = 0
    assert pr.dispatch_rescores(_reg(_o("ep01-S5"))) == 0      # future 未结束 → 不重派
    gate.set()
    pr.rescore_pool.shutdown(wait=True)


def test_breaker_defers_and_logs(tmp_path):
    pr, paths = _pr(tmp_path, {"first:ep01-S7": {"rescore_take": 2}})
    pr.score_chain_trip("测试")
    assert pr.dispatch_rescores(_reg(_o("ep01-S7"))) == 0 and not pr.inflight
    assert any(e["ev"] == "rescore_defer" for e in _events(paths))


def test_rescore_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "RESCORE_MAX", 2)
    led = {f"first:ep01-S{i}": {"rescore_take": 1} for i in range(1, 6)}
    pr, _ = _pr(tmp_path, led)
    gate = threading.Event()
    pr._rescore_one = lambda o, n: gate.wait(5)
    assert pr.dispatch_rescores(_reg(*[_o(f"ep01-S{i}") for i in range(1, 6)])) == 2
    assert pr.hb_counts()["rescoring"] == 2
    gate.set()
    pr.rescore_pool.shutdown(wait=True)


def test_backoff_objects_skipped(tmp_path):
    pr, _ = _pr(tmp_path, {"first:ep01-S8": {"rescore_take": 1, "backoff_until": PR.now() + 600}})
    assert pr.dispatch_rescores(_reg(_o("ep01-S8"))) == 0
    assert pr.dispatch_rescores(_reg(_o("ep01-S8", waiting_for="基础设施退避到 16:00"))) == 0


def test_rescore_one_infra_escalates_and_late_finish_does_not_touch_new_owner(tmp_path):
    pr, _ = _pr(tmp_path, {"first:ep01-S9": {"rescore_take": 1, "rescore_infra": 1}})

    def boom(*a, **k):
        raise RuntimeError("ssh 断")
    pr.script = boom
    pr.inflight["first:ep01-S9"] = {"lane": "gpu33:0", "since": PR.now()}    # 已被 reap 放位、又被出图占了
    pr.leases.acquire("first:ep01-S9", lane="gpu33:0")
    pr._rescore_one(_o("ep01-S9"), 1)
    led = pr.ledger()["first:ep01-S9"]
    assert led["rescore_infra"] == 2 and led["backoff_until"] > PR.now() + PR.RESCORE_BACKOFF[1] - 30
    assert "first:ep01-S9" in pr.inflight and pr.leases.get("first:ep01-S9")       # 别人的在途 / 租约不动
    assert pr._score_down_until > PR.now()


def test_retry_obj_clears_blocks_without_counting(tmp_path):
    pr, paths = _pr(tmp_path, {
        "first:ep01-S1": {"blocked_until": PR.now() + 1800, "tries": 2, "history": [{"try": 1}, {"try": 2}],
                          "waiting_asset": {"kind": "asset"}, "reason": "I2"},
        "assets:ep01-S1": {"blocked": True, "at": PR.now(), "reasons": ["I2"]}})
    out = PR.retry_obj(paths, "first:ep01-S1", "MASTER-WSL", "CODER-PS 修了脸板")
    L = json.loads(paths.ledger.read_text(encoding="utf-8"))
    r = L["first:ep01-S1"]
    assert r["blocked_until"] == 0 and r["waiting_asset"] is None and r["backoff_until"] == 0
    assert r["tries"] == 2 and len(r["history"]) == 2 and "不计次" in r["reason"]
    assert L["assets:ep01-S1"]["blocked"] is False
    assert out["assets_blocked_before"] is True
    ev = [e for e in _events(paths) if e["ev"] == "retry"]
    assert ev and ev[0]["by"] == "MASTER-WSL" and ev[0]["counted"] is False
    src = (ROOT / "tools" / "autopilot" / "producer.py").read_text(encoding="utf-8")
    assert '"retry"' in src.split("def main(", 1)[1] and "retry_obj(paths, a.obj, a.by, a.note)" in src   # CLI 入口（不跑：会写真账本）


def test_retry_rejects_bad_obj(tmp_path):
    _, paths = _pr(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        PR.retry_obj(paths, "assets:ep01-S1", "x")


def _slot(kind, file, members=None):
    return types.SimpleNamespace(kind=kind, file=file, members=members or [], line=f"[{kind}]")


def test_face_files_of_includes_faceboard_members():
    sl = [_slot("faceboard", "fb.png", [{"file": "a.png"}, {"file": "b.png"}, {"file": "c.png"}]), _slot("board", "bd.png")]
    assert PR.face_files_of(sl) == ["a.png", "b.png", "c.png"]
    assert PR.face_files_of([_slot("face", "x.png"), _slot("sheet", "s.png")]) == ["x.png"]


def test_two_person_board_keeps_faceboard(monkeypatch):
    """B 档（faces_board）：三人镜脸板必须留在脸槽，否则 preflight I2（W20 实测 15:47:33）"""
    import dataclasses
    sys.path.insert(0, str(ROOT / "tools" / "assetmaster"))
    import frames_v2 as F2
    from ns_agent import asset_refs as AR
    monkeypatch.setattr(AR, "make_board", lambda project, tiles: "board.png")

    @dataclasses.dataclass
    class Plan:
        slots: list
        capacity: int = 3
        prompt_prefix: str = ""
        dropped: list = dataclasses.field(default_factory=list)
    fb = _slot("faceboard", "fb.png", [{"file": "a.png"}])
    plan = Plan(slots=[fb, _slot("sheet", "s.png")])
    sr = types.SimpleNamespace(project="p", refs=[types.SimpleNamespace(role="sheet", file="s.png", label="造型")])
    out = F2.two_person_board(sr, plan)
    assert [s.kind for s in out.slots] == ["faceboard", "board"] and out.slots[1].index == 2


def test_w38_board_members_keep_zone(monkeypatch):
    """W38（ep01 S9）：参考板格成员带原参考的 zone / character —— 鞋格 zone=feet，preflight I4 才认得到板里的鞋"""
    import dataclasses
    sys.path.insert(0, str(ROOT / "tools" / "assetmaster"))
    import frames_v2 as F2
    from ns_agent import asset_refs as AR
    monkeypatch.setattr(AR, "make_board", lambda project, tiles: "board.png")

    @dataclasses.dataclass
    class Plan:
        slots: list
        capacity: int = 3
        prompt_prefix: str = ""
        dropped: list = dataclasses.field(default_factory=list)
    plan = Plan(slots=[_slot("face", "a.png"), _slot("face", "b.png")])
    ns = types.SimpleNamespace
    sr = ns(project="p", refs=[ns(role="item", file="shoe.png", label="鞋：透明尖头细高跟", zone="feet", character="lead_f", item_id="SH1"),
                               ns(role="sheet", file="s.png", label="造型", zone=None, character="ch_b", item_id=None)])
    out = F2.two_person_board(sr, plan)
    mem = out.slots[-1].members
    assert mem[0]["zone"] == "feet" and mem[0]["character"] == "lead_f" and mem[0]["item_id"] == "SH1"
    assert "zone" not in mem[1] and mem[1]["role"] == "sheet"


def _pf(ok, q9="pass", model=True, blocking=(), q1=0.6, extra=None):
    it = [{"id": "Q1", "status": "pass", "evidence": {"value": q1}},
          {"id": "Q9", "status": q9, "evidence": {"model": "m"} if model else {}}] + list(extra or [])
    return {"ok": ok, "blocking": list(blocking), "items": it}


def test_l183_q19_clean_and_pick():
    """L-183：Q1–Q9 全过（Q9 na 须真看过）才可取；取 score_key 最高；被驳回 / 坏图不取"""
    assert PR.q19_clean(_pf(False, blocking=["QB"]))
    assert PR.q19_clean(_pf(False, q9="na"))                                       # 只记录项 na（看过）
    assert not PR.q19_clean(_pf(False, q9="na", model=False))                      # 没看成
    assert not PR.q19_clean(_pf(False, extra=[{"id": "Q2", "status": "fail"}]))
    assert not PR.q19_clean({"items": [{"id": "Q1", "status": "pass"}]})           # 没有 Q9
    td = {"takes": [{"stage": "image", "n": 1, "postflight": _pf(False, blocking=["QB"], q1=0.5)},
                    {"stage": "image", "n": 2, "postflight": _pf(False, blocking=["QB"], q1=0.7)},
                    {"stage": "image", "n": 3, "postflight": _pf(False, blocking=["QB"], q1=0.9), "master_reject": {"by": "x"}},
                    {"stage": "image", "n": 4, "postflight": _pf(False, extra=[{"id": "Q2", "status": "fail"}], q1=0.99)}]}
    assert PR.review_pick(td, "image") == 2 and PR.review_pick(td, "image", {1}) == 1 and PR.review_pick(td, "last") is None


def test_l183_review_adopt_marks_and_activates(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    td = {"active": {}, "takes": [{"stage": "last", "n": 5, "postflight": _pf(False, blocking=["Q10", "QB"])}]}
    seen = {}
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    monkeypatch.setattr(P, "mutate_takes", lambda sid, fn, **k: fn(td))
    monkeypatch.setattr(P, "set_active", lambda sid, stage, n, **k: seen.update(sid=sid, stage=stage, n=n))
    monkeypatch.setattr(PR, "promote_live", lambda root, line: seen.update(live=line))
    _pr0, paths = _pr(tmp_path)
    n = PR.review_adopt(paths, "last:ep01-S6", by="W38")
    pf = td["takes"][0]["postflight"]
    assert n == 5 and seen["n"] == 5 and seen["stage"] == "last"
    assert pf["ok"] is True and pf["review_needed"] and pf["ok_before_review"] is False and pf["blocking_before_review"] == ["Q10", "QB"]
    assert "待项目方复核" in seen["live"]
    td["takes"][0]["postflight"] = _pf(False, extra=[{"id": "Q2", "status": "fail"}])
    assert PR.review_adopt(paths, "last:ep01-S6") is None
