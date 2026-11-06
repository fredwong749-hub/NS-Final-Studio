"""ORPHAN-TAKE（11-06）：出好的版本打分一直没结论（打分线程随 producer 进程重启丢了）→ producer 自己发现：
标 orphan（界面 / 候选一律不给看）+ 对象还在 ready 时只重打分（不占道、不重出、不计次；打完写 outbox，puller 拉回）。
现场：ep01-S5 尾帧 v12（gpu36:1 借道 20:31 出好，20:33 重启）postflight 永远 {state: running, ok: null}，之后又出了 v13、
又 review_adopt 了 v8——v12 既不是当前版（K-OPS-F12 只看当前版），也没人再管它。全部临时目录。"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
for p in ("services/render_router", "services/agent", "services/api"):
    sys.path.insert(0, str(ROOT / p))
import producer as PR  # noqa: E402


def _iso(age_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - age_s))


def _take(n, stage, pf, age_s, producer=True, **kw):
    return {"n": n, "stage": stage, "file": f"renders/series10_v2/ep01/S5/takes/{stage}_{n:03d}.png", "created_at": _iso(age_s),
            "postflight": pf, **({"producer": {"lane": "gpu36:1", "attempt": 3}} if producer else {}), **kw}


def _pr(tmp_path, ledger=None):
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id="series10_v2")
    paths.pd.mkdir(parents=True, exist_ok=True)
    paths.renders.mkdir(parents=True, exist_ok=True)
    if ledger:
        paths.ledger.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    return pr, paths


def _shot(paths, takes, active):
    d = paths.renders / "ep01" / "S5"
    d.mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}, ensure_ascii=False), encoding="utf-8")
    return d / "takes.json"


def _reg(status="ready"):
    o = {"id": "last:ep01-S5", "kind": "last", "shot": "ep01-S5", "ep": 1, "status": status}
    return {"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S5", "index": 5, "objects": {"last": o}}]}]}


def _events(paths):
    return [json.loads(x) for x in paths.log.read_text(encoding="utf-8").splitlines() if x.strip()] if paths.log.exists() else []


def _patch_fe(monkeypatch, tj: Path):
    """frame_edit.annotate 走 pipeline 的当前剧目录；测试里直接改临时 takes.json"""
    from ns_render import frame_edit as FE

    def annotate(sid, stage, n, **fields):
        d = json.loads(tj.read_text(encoding="utf-8"))
        t = next(x for x in d["takes"] if x["stage"] == stage and x["n"] == n)
        t.update({k: v for k, v in fields.items() if v is not None})
        tj.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return t
    monkeypatch.setattr(FE, "annotate", annotate)


def test_take_unscored_rule():
    assert PR.take_unscored({"postflight": {"state": "running", "ok": None}})
    assert PR.take_unscored({"postflight": {"ok": None, "error": "x"}})
    assert not PR.take_unscored({"postflight": {"ok": False, "blocking": ["Q9"], "items": [{"id": "Q9", "status": "fail"}]}})
    assert not PR.take_unscored({"postflight": {"ok": True}})
    assert not PR.take_unscored({"postflight": {"state": "orphan", "ok": False}})   # 已标过的不再处理
    assert not PR.take_unscored({})                                                   # 没 postflight 记录（画布 / 手工）不算


def test_sweep_marks_orphan_and_requests_rescore_when_ready(tmp_path, monkeypatch):
    pr, paths = _pr(tmp_path)
    tj = _shot(paths, [_take(8, "last", {"ok": True}, 7200), _take(12, "last", {"state": "running", "ok": None}, 1800),
                       _take(13, "last", {"ok": False, "blocking": ["Q9"], "items": [{"id": "Q9", "status": "fail"}]}, 900)], {"last": 8})
    _patch_fe(monkeypatch, tj)
    out = PR.orphan_take_sweep(pr, _reg("ready"))
    assert out == [("last:ep01-S5", 12, "orphan+rescore")]
    t12 = next(t for t in json.loads(tj.read_text(encoding="utf-8"))["takes"] if t["n"] == 12)
    pf = t12["postflight"]
    assert pf["state"] == "orphan" and pf["ok"] is False and pf["orphan"]["rule"] == "ORPHAN-TAKE" and pf["orphan"]["pf_before"] == {"state": "running", "ok": None}
    led = json.loads(paths.ledger.read_text(encoding="utf-8"))["last:ep01-S5"]
    assert led["rescore_take"] == 12 and "只重打分" in led["reason"]
    ev = [e for e in _events(paths) if e["ev"] == "orphan_take"]
    assert len(ev) == 1 and ev[0]["take"] == 12 and ev[0]["counted"] is False
    # 界面口径：标了 orphan 的版本不给项目方看
    from ns_api import takes_ui as TU
    assert TU._verdict(t12, None)[0] is False
    # 第二拍（节流内）不重复；节流过后也不再处理（已标 orphan）
    assert PR.orphan_take_sweep(pr, _reg("ready")) == []
    pr._orphan_t = 0
    assert PR.orphan_take_sweep(pr, _reg("ready")) == []
    # 只重打分链路认这张：dispatch_rescores 从账本拿 rescore_take=12
    assert pr._rescore_dispatchable({"id": "last:ep01-S5", "kind": "last", "shot": "ep01-S5", "status": "ready", "waiting_for": "空闲道"}) == 12


def test_sweep_only_marks_when_object_passed_or_has_other_rescore(tmp_path, monkeypatch):
    """对象已通过（v8 review_adopt）→ 只标 orphan，不再花打分；账本已有别的只重打分 → 不覆盖"""
    pr, paths = _pr(tmp_path, {"last:ep01-S5": {"rescore_take": 11}})
    tj = _shot(paths, [_take(12, "last", {"state": "running", "ok": None}, 1800)], {"last": 8})
    _patch_fe(monkeypatch, tj)
    assert PR.orphan_take_sweep(pr, _reg("passed")) == [("last:ep01-S5", 12, "orphan")]
    assert json.loads(paths.ledger.read_text(encoding="utf-8"))["last:ep01-S5"]["rescore_take"] == 11
    pr2, paths2 = _pr(tmp_path / "b")
    tj2 = _shot(paths2, [_take(12, "last", {"state": "running", "ok": None}, 1800)], {"last": 8})
    _patch_fe(monkeypatch, tj2)
    assert PR.orphan_take_sweep(pr2, _reg("passed")) == [("last:ep01-S5", 12, "orphan")]
    assert "rescore_take" not in (pr2.ledger().get("last:ep01-S5") or {})    # 已通过的对象不再花打分


def test_sweep_skips_young_leased_inflight_active_and_non_producer(tmp_path, monkeypatch):
    pr, paths = _pr(tmp_path)
    tj = _shot(paths, [
        _take(12, "last", {"state": "running", "ok": None}, 60),                       # 刚出好：打分还在跑
        _take(3, "image", {"state": "running", "ok": None}, 1800, producer=False),     # 不是 producer 出的（画布）
        _take(5, "image", {"state": "running", "ok": None}, 1800),                     # 当前版：归 K-OPS-F12（_frame_obj 只重打分）
    ], {"image": 5})
    _patch_fe(monkeypatch, tj)
    assert PR.orphan_take_sweep(pr, _reg("ready")) == []
    # 对象有活租约 / 在本进程在途（出好等打分）→ 不碰
    d = json.loads(tj.read_text(encoding="utf-8"))
    d["takes"][0]["created_at"] = _iso(1800)
    tj.write_text(json.dumps(d), encoding="utf-8")
    pr._orphan_t = 0
    assert pr.leases.acquire("last:ep01-S5", lane="gpu36:1")
    assert PR.orphan_take_sweep(pr, _reg("ready")) == []
    pr.leases.release("last:ep01-S5")
    pr._orphan_t = 0
    pr.inflight["last:ep01-S5"] = {"lane": "gpu36:1", "since": time.time()}
    assert PR.orphan_take_sweep(pr, _reg("ready")) == []
    pr.inflight.pop("last:ep01-S5")
    pr._orphan_t = 0
    assert PR.orphan_take_sweep(pr, _reg("ready")) == [("last:ep01-S5", 12, "orphan+rescore")]
    assert json.loads(tj.read_text(encoding="utf-8"))["takes"][0]["postflight"]["state"] == "orphan"


def test_sweep_age_from_config_and_wired_into_tick(tmp_path, monkeypatch):
    pr, paths = _pr(tmp_path)
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / "config" / "pipeline" / "producer.json").write_text(json.dumps({"orphan_take": {"age_s": 30}}), encoding="utf-8")
    tj = _shot(paths, [_take(12, "last", {"state": "running", "ok": None}, 90)], {})
    _patch_fe(monkeypatch, tj)
    assert PR.orphan_take_sweep(pr, _reg("ready")) == [("last:ep01-S5", 12, "orphan+rescore")]
    src = (ROOT / "tools" / "autopilot" / "producer.py").read_text(encoding="utf-8")
    tick = src.split("    def tick(self", 1)[1].split("    def hb_counts", 1)[0]
    assert "orphan_take_sweep(self, reg)" in tick
