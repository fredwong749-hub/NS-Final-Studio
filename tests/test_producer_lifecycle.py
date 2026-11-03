"""W18 PRODUCER-LIFECYCLE：主剧到“出图”自动起 producer / night、自动 promote、首帧超时代选（L-142）。
全部临时目录夹具 + 打桩：不连服务器、不起进程、不写真实 data/ / config/ / V2_LIVE。

覆盖：阶段未到不起（C-16）· 到了且无心跳起（笔记本 ps1 + 分区服务器 request_restart，mode=producer-only）· 已有心跳不重复起 ·
起后 grace 内不重起、连续 3 次起不来报 P0 且只报一次 · 尾帧起 night（同机合并一次重启，mode=all）· 服务器健康过期 = 判不了不起 ·
promote 条件（可进才写、不可进不起、auto 读取）· dry 不动不写 · 首帧代选超时触发 / 未超时不触发 / 硬规定（成人镜、本地专用候选）不放行 /
项目方动过不代 / 已定稿不代 / 同分按 bundle 顺序 · L-136 关着首帧代选照样走。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
for p in ("services/post", "services/agent", "services/api"):
    sys.path.insert(0, str(ROOT / p))

import resident_sync as RS  # noqa: E402
from ns_api import owner_delegate as OD  # noqa: E402

RUN = "tv_w18"
STAGES = ["剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧", "视频", "整集预览"]


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _root(tmp_path: Path, status="producing", apply=True, auto=True) -> Path:
    _w(tmp_path / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1",
                                                "runs": {RUN: {"status": status}, "old_v1": {"status": "archived"}}})
    _w(tmp_path / "config/pipeline/sop_gate.json", {"promote": {"auto": auto, "stage": "出图"},
                                                    "lifecycle": {"apply": apply, "hb_stale_min": 5, "grace_min": 10, "max_fails": 3}})
    _w(tmp_path / "config/netfix/partition.json", {"images": {"gpu33": [1, 3], "gpu36": [2], "laptop": []},
                                                   "video": {"gpu33": [1, 3], "gpu36": [2]}})
    _w(tmp_path / "config/pipeline/owner_delegate.json", {"enabled": False, "first_frame": {"enabled": True, "timeout_min": 30}})
    _w(tmp_path / "data/import/runs" / RUN / "script_v2.json",                  # W18b：导入稿读不到 = 整集不代，夹具补一份
       {"episodes": [{"number": 1, "shots": [{"index": i} for i in range(1, 13)]}]})
    return tmp_path


def _stage(*eps: tuple[int, str], status="producing"):
    def fn(root, run):
        return {"status": status, "legacy": False, "stages": STAGES,
                "episodes": [{"episode": e, "stage": s, "stage_index": STAGES.index(s)} for e, s in eps]}
    return fn


class Rec:
    def __init__(self, ok=True, executes=True):
        self.laptop, self.server, self.issues, self.live, self.promote = [], [], [], [], []
        self.ok = ok
        self.executes = executes          # 假 restart_queue：True = 请求写下就被执行（done_t = 写请求的时刻）；False = 一直排队
        self.reqs: dict = {}              # req_id → (host, 写入时刻)
        self.now = 0.0

    def _server(self, host, reason, mode):
        self.server.append((host, mode))
        rid = f"r{len(self.server)}"
        self.reqs[rid] = (host, self.now)
        return {"ok": self.ok, "request": rid}

    def _rq(self, host, req_id):
        pend = (not self.executes) and any(h == host for h, _ in self.reqs.values())
        done = self.reqs.get(req_id, (None, None))[1] if (self.executes and req_id in self.reqs) else None
        return {"pending": pend, "done_t": done}

    def kw(self, hbs=None, promote=None):
        return dict(hb_fn=lambda root, run, hosts, now, max_age: setattr(self, "now", now) or dict(hbs or {}),
                    laptop_fn=lambda root, ps1, run: self.laptop.append((ps1, run)) or {"ok": self.ok, "out": "restarted"},
                    server_fn=self._server, rq_fn=self._rq,
                    issue_fn=lambda root, run, ep, tgt, what: self.issues.append((tgt, what)) or f"ISS-{len(self.issues)}",
                    live_fn=lambda root, line: self.live.append(line),
                    promote_fn=promote or (lambda run, root, apply: self.promote.append(apply) or {"promote": True, "applied": apply,
                                                                                                    "episodes": [1], "why": "ep1 可进"}))


# ------------------------------------------------------------------ 起 / 不起
def test_stage_before_images_starts_nothing(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "提示词"), (2, "资产就绪")), now=1e9, **r.kw())
    assert "C-16" in out["skip"] and not r.laptop and not r.server and not out["actions"]


def test_images_stage_no_heartbeat_starts_laptop_and_partition_server(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图"), (2, "资产就绪")), now=1e9, **r.kw())
    assert out["producer_eps"] == [1] and out["night_eps"] == []
    assert r.laptop == [("ops/autostart/restart_producer.ps1", RUN)]
    assert r.server == [("gpu33", "producer-only")]                 # 只起负责 ep1 出图的 gpu33；阶段 < 尾帧 → 不带 night
    assert set(out["actions"]) == {"laptop:producer", "gpu33:producer"}
    assert out["actions"]["laptop:producer"]["action"] == "started" and out["actions"]["gpu33:producer"]["action"] == "requested"
    st = json.loads((root / "data/autopilot/lifecycle.json").read_text(encoding="utf-8"))
    assert st["gpu33:producer"].get("attempts", 0) == 0 and st["gpu33:producer"]["req_id"] == "r1" and len(r.live) == 2   # W18b P1-2：只写请求不算 attempt


def test_fresh_heartbeat_not_restarted(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图检测")), now=1e9,
                            **r.kw(hbs={"laptop:producer": 0.5, "gpu33:producer": 1.9}))
    assert not r.laptop and not r.server
    assert {a["action"] for a in out["actions"].values()} == {"running"}


def test_stale_heartbeat_over_5min_restarts(tmp_path):
    """W18b P1-1：hb_stale_min 2 → 5：2.5 分钟（一拍里 import_err 重试就能到）仍算在跑；5.5 分钟才拉起"""
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图")), now=1e9, **r.kw(hbs={"laptop:producer": 2.5, "gpu33:producer": 0.3}))
    assert not r.laptop and out["actions"]["laptop:producer"]["action"] == "running"
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图")), now=1e9, **r.kw(hbs={"laptop:producer": 5.5, "gpu33:producer": 0.3}))
    assert r.laptop and not r.server and out["actions"]["gpu33:producer"]["action"] == "running"


def test_hb_stale_default_is_5_in_code_and_config():
    assert RS.LC_DEFAULT["hb_stale_min"] == 5
    assert json.loads((ROOT / "config/pipeline/sop_gate.json").read_text(encoding="utf-8"))["lifecycle"]["hb_stale_min"] == 5
    assert isinstance(RS.lifecycle_cfg(ROOT)["apply"], bool)                         # 开关由总调度按审计结果定（L-171 11-03 16:0x 开），测试不钉死取值


def test_server_only_requests_never_count_or_report_p0(tmp_path):
    """W18b P1-2：restart_queue 一直没执行（30 分钟间隔 / 排空中）→ 只写一次请求，之后 queued，attempts 不加，不登记 P0"""
    root, r = _root(tmp_path), Rec(executes=False)
    st, t = _stage((1, "出图")), 1e9
    for i in range(6):
        out = RS.lifecycle_tick(root, stage_fn=st, now=t + 660 * i, **r.kw(hbs={"laptop:producer": 0.1}))
    assert r.server == [("gpu33", "producer-only")] and out["actions"]["gpu33:producer"]["action"] == "queued"
    sd = json.loads((root / "data/autopilot/lifecycle.json").read_text(encoding="utf-8"))
    assert sd["gpu33:producer"].get("attempts", 0) == 0 and not r.issues


def test_server_attempt_counted_only_after_queue_executed_and_grace(tmp_path):
    root, r = _root(tmp_path), Rec()
    st, t, hb = _stage((1, "出图")), 1e9, {"laptop:producer": 0.1}
    RS.lifecycle_tick(root, stage_fn=st, now=t, **r.kw(hbs=hb))                     # 写请求 r1（假队列立即执行）
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 300, **r.kw(hbs=hb))         # 执行后 5 分钟：grace 内等心跳，不计
    assert out["actions"]["gpu33:producer"]["action"] == "waiting" and out["actions"]["gpu33:producer"]["attempts"] == 0
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 660, **r.kw(hbs=hb))         # 过 grace 仍无心跳：+1 并写下一条
    assert out["actions"]["gpu33:producer"]["attempts"] == 1 and len(r.server) == 2
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 700, **r.kw(hbs=hb))         # 同一条请求不重复计数
    assert out["actions"]["gpu33:producer"]["attempts"] == 1


def test_grace_then_three_failures_report_p0_once(tmp_path):
    root, r = _root(tmp_path), Rec(ok=False)
    st = _stage((1, "出图"))
    t = 1e9
    RS.lifecycle_tick(root, stage_fn=st, now=t, **r.kw())
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 300, **r.kw())          # 5 分钟后：grace 内不重起
    assert out["actions"]["laptop:producer"]["action"] == "waiting" and len(r.laptop) == 1
    for i in (1, 2):
        RS.lifecycle_tick(root, stage_fn=st, now=t + 660 * i, **r.kw())
    assert len(r.laptop) == 3 and not r.issues
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 660 * 3, **r.kw())
    assert out["actions"]["laptop:producer"]["action"] == "gave_up" and len(r.laptop) == 3
    assert {i[0] for i in r.issues} == {"laptop:producer", "gpu33:producer"} and "P0" in r.issues[0][1]
    RS.lifecycle_tick(root, stage_fn=st, now=t + 660 * 4, **r.kw())
    assert len(r.issues) == 2                                                    # 只报一次
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 660 * 5, **r.kw(hbs={"laptop:producer": 0.1, "gpu33:producer": 0.1}))
    sd = json.loads((root / "data/autopilot/lifecycle.json").read_text(encoding="utf-8"))
    assert sd["laptop:producer"]["attempts"] == 0 and sd["laptop:producer"]["issue"] is None   # 恢复后清零


def test_lasts_stage_starts_night_merged_one_server_restart(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "尾帧"), (2, "出图")), now=1e9, **r.kw())
    assert out["night_eps"] == [1]
    assert ("gpu33", "all") in r.server and ("gpu36", "producer-only") in r.server
    assert len([h for h, _ in r.server if h == "gpu33"]) == 1                     # producer + night 同机：一次重启
    assert out["actions"]["gpu33:night"]["action"] == "merged"


def test_night_not_started_before_lasts(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图检测")), now=1e9, **r.kw())
    assert not any(k.endswith(":night") for k in out["actions"])


def test_server_health_stale_is_unknown_not_started(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图")), now=1e9, **r.kw(hbs={"laptop:producer": 0.1, "gpu33:producer": "unknown"}))
    assert out["actions"]["gpu33:producer"]["action"] == "unknown" and not r.server


def test_paused_or_legacy_run_untouched(tmp_path):
    root, r = _root(tmp_path), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图"), status="paused"), now=1e9, **r.kw())
    assert "paused" in out["skip"] and not r.laptop


def test_dry_plans_without_acting_or_writing(tmp_path):
    root, r = _root(tmp_path, apply=False), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图")), now=1e9, **r.kw())
    assert out["dry"] is True
    assert {a["action"] for a in out["actions"].values()} == {"would_start"}
    assert "restart_producer.ps1" in out["actions"]["laptop:producer"]["how"]
    assert "request_restart('gpu33', mode=producer-only)" in out["actions"]["gpu33:producer"]["how"]
    assert not r.laptop and not r.server and not (root / "data/autopilot/lifecycle.json").exists()


# ------------------------------------------------------------------ promote
def test_promote_applied_when_preparing_and_judge_ok(tmp_path):
    root, r = _root(tmp_path, status="preparing"), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图"), status="preparing"), now=1e9, **r.kw())
    assert r.promote == [True] and out["promote"]["applied"] and r.laptop
    assert any("preparing → producing" in x for x in r.live)


def test_promote_not_ok_does_not_start(tmp_path):
    root, r = _root(tmp_path, status="preparing"), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((2, "出图"), status="preparing"), now=1e9,
                            **r.kw(promote=lambda run, root, apply: {"promote": False, "why": "第1集复盘：draft"}))
    assert "判不可进" in out["skip"] and not r.laptop and not r.server


def test_promote_auto_false_reads_config_and_holds(tmp_path):
    root, r = _root(tmp_path, status="preparing", auto=False), Rec()
    out = RS.lifecycle_tick(root, stage_fn=_stage((1, "出图"), status="preparing"), now=1e9,
                            **r.kw(promote=lambda run, root, apply: r.promote.append(apply) or {"promote": True, "episodes": [1]}))
    assert r.promote == [False] and "promote.auto=false" in out["skip"] and not r.laptop


def test_promote_default_path_writes_status_history_auto(tmp_path, monkeypatch):
    root, r = _root(tmp_path, status="preparing"), Rec()
    calls = []

    class FakeSG:
        @staticmethod
        def promote(run, root, by, apply):
            calls.append((by, apply))
            return {"promote": True, "applied": apply, "episodes": [1], "why": "ok"}
    monkeypatch.setitem(RS._LC_MODS, f"ns_sop_gate_lc:{Path(root).resolve()}", FakeSG)
    kw = r.kw()
    kw.pop("promote_fn")
    RS.lifecycle_tick(root, stage_fn=_stage((1, "出图"), status="preparing"), now=1e9, **kw)
    assert calls == [("auto:resident_sync.lifecycle", True)]


# ------------------------------------------------------------------ 心跳读取
def test_heartbeats_laptop_file_and_server_health(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    pd = root / RS.producer_rel(RUN)
    _w(pd / "heartbeat.json", {"t": now - 30, "run": RUN})
    _w(root / "data/autopilot/resident_sync.json", {
        "gpu33": {"health": {"at": time.strftime("%F %T", time.localtime(now - 60)), "producer_hb_age_min": 0.4, "night_state_age_min": 99}},
        "gpu36": {"health": {"at": time.strftime("%F %T", time.localtime(now - 3600)), "producer_hb_age_min": 0.4}}})
    hb = RS.lifecycle_heartbeats(root, RUN, ["gpu33", "gpu36"], now)
    assert hb["laptop:producer"] == 0.5 and hb["gpu33:producer"] == 0.4 and hb["gpu33:night"] == 99.0
    assert hb["gpu36:producer"] == "unknown"
    _w(pd / "heartbeat.json", {"t": now - 30, "run": RUN, "state": "exited", "exited": "x"})
    assert RS.lifecycle_heartbeats(root, RUN, [], now)["laptop:producer"] is None
    _w(pd / "heartbeat.json", {"t": now - 30, "run": "other_run"})
    assert RS.lifecycle_heartbeats(root, RUN, [], now)["laptop:producer"] is None


# ------------------------------------------------------------------ 首帧代选（L-142）
def _pf(q1: float, bundle_ok: int, bundle_n: int, ts: str, ok=True, q9="pass") -> dict:
    return {"ok": ok, "ts": ts, "items": [{"id": "Q1", "status": "pass", "evidence": {"value": q1}},
                                          {"id": "Q9", "status": q9},
                                          {"id": "QB", "status": "pass", "evidence": {"bundle": {"items": [{"ok": i < bundle_ok} for i in range(bundle_n)]}}}]}


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _shot(root: Path, sid: str, takes: list[dict], lane: str | None = "gpu33:1", **extra) -> Path:
    ep, s = sid.split("-")
    d = root / "data/renders" / RUN / ep / s
    for t in takes:
        _w(root / "data" / t["file"], "png")
    if lane:                                                                      # W18b P1-3：producer 账本记录每版用的道
        led = root / "data/producer/runs" / RUN / "attempts.json"
        cur = json.loads(led.read_text(encoding="utf-8")) if led.is_file() else {}
        cur[f"first:{sid}"] = {"history": [{"try": i + 1, "lane": lane, "take": t["n"], "ok": True} for i, t in enumerate(takes)]}
        _w(led, cur)
    _w(d / "takes.json", {"takes": takes, "active": {"image": takes[-1]["n"]} if takes else {}, **extra})
    return d / "takes.json"


def _take(n: int, pf: dict, **kw) -> dict:
    return {"n": n, "stage": "image", "file": f"renders/{RUN}/img_{n}.png", "created_at": pf["ts"], "postflight": pf, **kw}


def _fr(root: Path, now: float, adult=(), **kw):
    locks = []
    out = OD.frame_tick(root, now=now, lock_fn=lambda r, sid, n, meta, tj: locks.append((sid, n, meta)) or {"final_job": True},
                        adult_fn=lambda run, ep: set(adult), live_fn=lambda r, line: None, **kw)
    return out, locks


def test_frame_pick_after_timeout_best_contract_score(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    old = _iso(now - 40 * 60)
    _shot(root, "ep01-S1", [_take(1, _pf(0.6, 3, 4, old)), _take(2, _pf(0.7, 4, 4, old)), _take(3, _pf(0.9, 1, 4, old, ok=False))])
    out, locks = _fr(root, now)
    assert [(s, n) for s, n, _ in locks] == [("ep01-S1", 2)]                     # v3 没过检不参选；v2 契约分最高
    assert locks[0][2]["label"] == "系统代选·可改" and locks[0][2]["ledger"] == "L-142"
    assert out[0]["event"] == "frame_pick" and out[0]["choice"] == 2
    seen = json.loads((root / OD.FRAME_SEEN_REL).read_text(encoding="utf-8"))
    assert seen[f"first:{RUN}/ep01-S1"]["n"] == 2
    assert any(r.get("event") == "frame_pick" for r in OD.log_rows(root))


def test_frame_no_pick_before_timeout(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S1", [_take(1, _pf(0.6, 3, 4, _iso(now - 10 * 60)))])
    out, locks = _fr(root, now)
    assert not out and not locks


def test_frame_timeout_from_config(tmp_path):
    root = _root(tmp_path)
    _w(root / OD.CFG_REL, {"enabled": False, "first_frame": {"enabled": True, "timeout_min": 5}})
    now = time.time()
    _shot(root, "ep01-S1", [_take(1, _pf(0.6, 3, 4, _iso(now - 10 * 60)))])
    assert _fr(root, now)[1]


def test_frame_tie_takes_bundle_order(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    old = _iso(now - 40 * 60)
    _shot(root, "ep01-S2", [_take(4, _pf(0.7, 2, 4, old)), _take(5, _pf(0.7, 2, 4, old))])
    assert [n for _, n, _ in _fr(root, now)[1]] == [4]


def test_frame_adult_shot_never(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S3", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    out, locks = _fr(root, now, adult=(3,))
    assert not locks and not out
    assert any(r.get("event") == "skip" and "成人" in r.get("reason", "") for r in OD.log_rows(root))


def test_frame_local_only_candidate_never(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)), route="local_only")])
    assert not _fr(root, now)[1]


def test_frame_adult_unknown_fails_closed(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S5", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])

    def boom(run, ep):
        raise RuntimeError("导入稿读不了")
    out = OD.frame_tick(root, now=now, lock_fn=lambda *a: pytest.fail("不该定稿"), adult_fn=boom, live_fn=lambda r, l: None)
    assert not out


def test_frame_owner_touched_or_locked_not_picked(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    old = _iso(now - 99 * 60)
    _shot(root, "ep01-S6", [_take(1, _pf(0.8, 4, 4, old))], locked={"image": 1})
    _shot(root, "ep01-S7", [_take(1, _pf(0.8, 4, 4, old))],
          locked_history=[{"stage": "image", "n": 1, "released_by": "项目方"}])
    _w(root / OD.FRAME_SEEN_REL, {f"first:{RUN}/ep01-S8": {"n": 1}})               # 系统代选过、之后被撤 → 不再代
    _shot(root, "ep01-S8", [_take(1, _pf(0.8, 4, 4, old))])
    assert not _fr(root, now)[1]


def test_frame_missing_config_is_off(tmp_path):
    root = _root(tmp_path)
    (root / OD.CFG_REL).unlink()
    now = time.time()
    _shot(root, "ep01-S1", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    assert _fr(root, now) == ([], [])


def test_frame_dry_and_disabled(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S1", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    out, locks = _fr(root, now, dry=True)
    assert out and out[0]["dry"] and not locks
    _w(root / OD.CFG_REL, {"enabled": False, "first_frame": {"enabled": False}})
    assert _fr(root, now) == ([], [])


def test_frame_runs_even_when_l136_inactive(tmp_path):
    root = _root(tmp_path)
    _w(root / OD.CFG_REL, {"enabled": False, "first_frame": {"enabled": True, "timeout_min": 30}})
    now = time.time()
    _shot(root, "ep01-S1", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    locks = []
    out = OD.tick(root, sync_looks=False, frame_lock=lambda r, sid, n, meta, tj: locks.append((sid, n)) or {})
    assert out["active"] is False and locks == [("ep01-S1", 1)] and out["frames"]


def test_never_reason_still_hard_coded():
    assert OD.never_reason({"kind": "pick", "id": "x", "adult": True})
    assert OD.never_reason({"kind": "pick", "id": "x", "category": "spend"})
    assert OD.never_reason({"kind": "pick", "id": "x", "category": "delete"})


# ------------------------------------------------------------------ W18b（A18 第 29 轮 P0-1 / P1-3 / P1-4 / P2-3）
def _no_lock(*a):
    pytest.fail("不该定稿")


def test_frame_adult_unknown_closes_whole_episode(tmp_path):
    """P0-1：成人判定抛异常 → 同集 S4 / S6 都不代（不是只关当前镜），skip 原因写“整集不代”"""
    root = _root(tmp_path)
    now = time.time()
    old = _iso(now - 99 * 60)
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, old))])
    _shot(root, "ep01-S6", [_take(1, _pf(0.8, 4, 4, old))])

    def boom(run, ep):
        raise RuntimeError("导入稿读不了")
    out = OD.frame_tick(root, now=now, lock_fn=_no_lock, adult_fn=boom, live_fn=lambda r, l: None)
    assert not out
    skips = {r["item"]: r["reason"] for r in OD.log_rows(root) if r.get("event") == "skip"}
    assert set(skips) == {f"first:{RUN}/ep01-S4", f"first:{RUN}/ep01-S6"} and all("整集不代" in v for v in skips.values())


def test_frame_missing_import_doc_closes_episode(tmp_path):
    """P0-1：默认成人判定在导入稿缺失时不再当“没有成人镜”放行"""
    root = _root(tmp_path)
    (root / "data/import/runs" / RUN / "script_v2.json").unlink()
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    assert not OD.frame_tick(root, now=now, lock_fn=_no_lock, live_fn=lambda r, l: None)


def test_frame_default_adult_from_import_doc(tmp_path):
    root = _root(tmp_path)
    _w(root / "data/import/runs" / RUN / "script_v2.json", {"episodes": [{"number": 1, "shots": [{"index": 4, "adult": True}, {"index": 5}]}]})
    now = time.time()
    old = _iso(now - 99 * 60)
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, old))])
    _shot(root, "ep01-S5", [_take(1, _pf(0.8, 4, 4, old))])
    locks = []
    OD.frame_tick(root, now=now, lock_fn=lambda r, sid, n, meta, tj: locks.append(sid) or {}, live_fn=lambda r, l: None)
    assert locks == ["ep01-S5"]


def test_frame_laptop_lane_candidate_never(tmp_path):
    """P1-3：producer 账本记录 lane=laptop:0 的候选 = 本地专用，不代"""
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))], lane="laptop:0")
    out, locks = _fr(root, now)
    assert not locks and not out
    assert any("本地专用" in r.get("reason", "") for r in OD.log_rows(root) if r.get("event") == "skip")


def test_frame_take_producer_lane_laptop_never(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)), producer={"lane": "laptop:1"})])
    assert not _fr(root, now)[1]


def test_frame_unknown_lane_fails_closed(tmp_path):
    """P1-3：候选没有 producer 道记录 → 判不出来 → 不代"""
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))], lane=None)
    assert not _fr(root, now)[1]
    assert any("判不出来" in r.get("reason", "") for r in OD.log_rows(root) if r.get("event") == "skip")


def test_frame_h3_local_only_shot_never(tmp_path):
    root = _root(tmp_path)
    _w(root / "data/import/runs" / RUN / "script_v2.json",
       {"episodes": [{"number": 1, "shots": [{"index": 4, "h3_check": "本地生成（亲密镜）"}]}]})
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    assert not OD.frame_tick(root, now=now, lock_fn=_no_lock, live_fn=lambda r, l: None)


def test_frame_web_unlocked_once_not_picked(tmp_path):
    """P1-4：网页解锁（frame_edit.unlock 不留 locked_history）→ 从 data/audit 认出来，不代"""
    root = _root(tmp_path)
    now = time.time()
    old = _iso(now - 99 * 60)
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, old))])
    _shot(root, "ep01-S5", [_take(1, _pf(0.8, 4, 4, old))])
    _w(root / "data/audit/20261103.jsonl", json.dumps({"at": "2026-11-03T10:00:00", "user": "fred", "role": "owner", "method": "POST",
                                                        "path": "/api/shots/ep01-S4/takes/image/1/unlock", "status": 200}) + "\n")
    out, locks = _fr(root, now)
    assert [s for s, _, _ in locks] == ["ep01-S5"]
    assert any("解锁" in r.get("reason", "") for r in OD.log_rows(root) if r.get("item") == f"first:{RUN}/ep01-S4")


def test_frame_owner_queue_action_not_picked(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])
    _w(root / "data/owner_queue/decisions.jsonl", json.dumps({"id": "pick:first:ep01-S4", "by": "fred", "choice": "1"}) + "\n")
    assert not _fr(root, now)[1]


def test_frame_owner_marks_unreadable_fails_closed(tmp_path):
    root = _root(tmp_path)
    now = time.time()
    _shot(root, "ep01-S4", [_take(1, _pf(0.8, 4, 4, _iso(now - 99 * 60)))])

    def boom(r):
        raise OSError("审计读不了")
    assert not OD.frame_tick(root, now=now, lock_fn=_no_lock, adult_fn=lambda r, e: set(), marks_fn=boom, live_fn=lambda r, l: None)


def test_frame_owner_marks_parses_audit_ignores_s10_vs_s1(tmp_path):
    root = _root(tmp_path)
    _w(root / "data/audit/a.jsonl", json.dumps({"method": "POST", "path": "/api/shots/ep01-S10/takes/image/2/lock"}) + "\n")
    m = OD._owner_marks(root)
    assert "ep01-S10" in m and "ep01-S1" not in m


def test_frame_dry_ignores_enabled_and_writes_nothing(tmp_path):
    """P2-3：first_frame.enabled=false 时 dry 仍能看到“会代哪些镜”；dry 不落盘 delegate_seen / delegate_log / delegate_frames"""
    root = _root(tmp_path)
    _w(root / OD.CFG_REL, {"enabled": False, "first_frame": {"enabled": False, "timeout_min": 30}})
    now = time.time()
    old = _iso(now - 99 * 60)
    _shot(root, "ep01-S1", [_take(1, _pf(0.8, 4, 4, old))])
    _shot(root, "ep01-S3", [_take(1, _pf(0.8, 4, 4, old))])
    out, locks = _fr(root, now, adult=(3,), dry=True)
    assert not locks
    assert [(r["event"], r["item"].split("/")[-1]) for r in out] == [("frame_pick", "ep01-S1"), ("skip", "ep01-S3")]
    assert all(r["dry"] for r in out) and out[0]["enabled"] is False
    for rel in (OD.SEEN_REL, OD.LOG_REL, OD.FRAME_SEEN_REL):
        assert not (root / rel).exists()
    assert _fr(root, now) == ([], [])                                               # 非 dry 仍受开关
