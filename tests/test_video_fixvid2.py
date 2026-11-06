"""FIX-VID / FIX-VID-2（11-06，REVIEW-RUN D1 / D8 / D10 / D12 / D13 + 视频审计快改）：
D1  relay 先拉各台 state 再送 owner；helper 失联 → owner sticky 收回；
D8  尾帧回退 I2VA（takes.json last_frame_fallback，绑定首帧）→ build_jobs 编 I2VA；派不了的镜 → blocked（帧等待有宽限）、静帧占位进合成；
D10 过期片（首帧 ≠ 当前首帧）不进成片；没过闸门的镜留在 jobs（route=hold）且算落定；
D12 finish.py 传本剧导入稿；finalize 清旧错误；代码类合成错误不定时重试；
D13 领取表生效不等重编、合并视图认领取台。全部在 tmp_path；不连服务器。"""
from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "tools", "tools/series10_video", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import video_shard as VS  # noqa: E402
import vidgen as VG  # noqa: E402

RUN = "series10_v2"
C2 = {"owner": "gpu36", "hosts": ["gpu36", "gpu33"]}


def _state(vid: Path, host: str, shots: dict, saved: float | None = None):
    d = {"host": host, "shots": shots}
    if saved is not None:
        d["saved"] = saved
    (vid / f"state_{host}.json").write_text(json.dumps(d), encoding="utf-8")


# ---------------------------------------------------------------- D1 / D13：分片仲裁
def test_state_age_missing_or_unsaved_is_inf(tmp_path):
    assert VS.state_age(tmp_path, "gpu33") == float("inf")
    _state(tmp_path, "gpu33", {})
    assert VS.state_age(tmp_path, "gpu33") == float("inf")
    _state(tmp_path, "gpu33", {}, saved=1000.0)
    assert VS.state_age(tmp_path, "gpu33", now=1100.0) == 100.0


def test_decide_claims_reclaims_stale_helper_sticky():
    plan = {"ep01-S1": "gpu36", "ep01-S2": "gpu33", "ep01-S3": "gpu33", "ep01-S4": "gpu33"}
    merged = {"ep01-S2": {"status": "done", "renders": [{}]}, "ep01-S3": {"status": "rendering", "renders": [{"state": "submitted"}]}}
    cl = VS.decide_claims(C2, plan, merged, {}, {"gpu36": 1, "gpu33": 0}, now=100.0, stale_hosts={"gpu33"})
    assert set(cl) == {"ep01-S3", "ep01-S4"}                      # 落定的不收；开工但失联的也收回
    assert all(c["host"] == "gpu36" and c["sticky"] and c["from"] == "gpu33" for c in cl.values())
    # 租约过了也不作废（sticky）
    assert set(VS.live_claims(cl, {}, now=100.0 + 10 * VS.CLAIM_LEASE_S)) == {"ep01-S3", "ep01-S4"}


def test_decide_claims_only_from_fresh_hosts():
    plan = {"ep01-S1": "gpu33", "ep01-S2": "gpu33"}
    # gpu36 空闲；gpu33 state 不新鲜（“没开工”不可信）→ 不领
    assert VS.decide_claims(C2, plan, {}, {}, {"gpu36": 0, "gpu33": 2}, now=1.0, claim_from={"gpu36"}) == {}
    cl = VS.decide_claims(C2, plan, {}, {}, {"gpu36": 0, "gpu33": 2}, now=1.0, claim_from={"gpu36", "gpu33"})
    assert list(cl) == ["ep01-S2"] and cl["ep01-S2"]["host"] == "gpu36" and not cl["ep01-S2"].get("sticky")


def test_effective_mine_no_double_render():
    lease = VS.CLAIM_LEASE_S
    c = {"host": "gpu36", "from": "gpu33", "at": 100.0}
    # 领取台（jobs 还写 gpu33）：租约内归 gpu36；被领台：租约内没开工 → 不归自己
    assert VS.effective_mine("gpu36", "s", "gpu33", c, False, 200.0) is True
    assert VS.effective_mine("gpu33", "s", "gpu33", c, False, 200.0) is False
    assert VS.effective_mine("gpu33", "s", "gpu33", c, True, 200.0) is True          # 已开工的不中途丢
    # 租约过了、领取台没开工 → 回到 jobs 的归属
    assert not VS.effective_mine("gpu36", "s", "gpu33", c, False, 100.0 + lease + 1)
    assert VS.effective_mine("gpu33", "s", "gpu33", c, False, 100.0 + lease + 1)
    sticky = dict(c, sticky=True)
    assert VS.effective_mine("gpu36", "s", "gpu33", sticky, False, 1e9) and not VS.effective_mine("gpu33", "s", "gpu33", sticky, False, 1e9)
    assert VS.effective_mine("gpu36", "s", "gpu36", None, False, 0) and not VS.effective_mine("gpu33", "s", "gpu36", None, False, 0)


def test_merged_shots_prefers_claim_host(tmp_path):
    _state(tmp_path, "gpu36", {"ep01-S2": {"status": "done", "renders": [{"variant": "a"}]}})
    _state(tmp_path, "gpu33", {"ep01-S2": {"status": "best_effort", "renders": [{"variant": "x"}, {"variant": "y"}]}})
    jobs = {"shots": [{"shot": "ep01-S2", "host": "gpu33"}]}
    assert VS.merged_shots(tmp_path, 1, ["gpu36", "gpu33"], jobs)["ep01-S2"]["status"] == "best_effort"
    VS.save_claims(tmp_path, {"ep01-S2": {"host": "gpu36", "from": "gpu33", "at": 1.0}})
    assert VS.merged_shots(tmp_path, 1, ["gpu36", "gpu33"], jobs)["ep01-S2"]["status"] == "done"


def test_relay_once_pulls_states_pushes_helper_and_reclaims(tmp_path, monkeypatch):
    import run_ctx as RC
    import shard_relay as SR
    rel = "vid"
    vid = tmp_path / rel
    vid.mkdir()
    monkeypatch.setattr(SR, "ROOT", tmp_path)
    monkeypatch.setattr(RC, "vid_rel", lambda run: rel)
    monkeypatch.setattr(VS, "shard_eps", lambda run: {1: C2})
    monkeypatch.setattr(VS, "load", lambda path=None: {})
    now = time.time()
    (vid / "jobs.json").write_text(json.dumps({"shots": [
        {"shot": "ep01-S1", "ep": 1, "host": "gpu36", "variants": {"v1": {}}},
        {"shot": "ep01-S2", "ep": 1, "host": "gpu33", "variants": {"v1": {}}}]}), encoding="utf-8")
    pulled, pushed = [], []

    def fake_pull(host, files, force=False):
        pulled.append((host, list(files), force))
        for f in files:
            if f.endswith("state_gpu36.json"):
                _state(vid, "gpu36", {"ep01-S1": {"status": "rendering", "renders": [{"state": "submitted"}]}}, saved=now)
            # gpu33 拉不到（失联）
        return sum(1 for f in files if f.endswith("state_gpu36.json"))
    monkeypatch.setattr(SR, "pull_from_helper", fake_pull)
    monkeypatch.setattr(SR, "pull_jobs", lambda owner, vid_rel, status: False)
    monkeypatch.setattr(SR, "push_to_owner", lambda owner, files, dry=False, marks_p=None: pushed.append((owner, list(files))) or len(files))
    res = SR.once(RUN)
    assert [p[0] for p in pulled if p[2]] == ["gpu36", "gpu33"]          # 每台 state 先强制拉
    assert res["ep01:health"]["gpu33"]["ok"] is False and res["ep01:health"]["gpu36"]["ok"] is True
    cl = VS.load_claims(vid)
    assert cl["ep01-S2"]["host"] == "gpu36" and cl["ep01-S2"]["sticky"]  # 失联 helper 名下的镜收回给 owner
    assert any(f"{rel}/{VS.CLAIMS_NAME}" in fs for _o, fs in pushed)      # 领取表送到两台
    assert (vid / SR.STATUS_NAME).is_file()


def test_relay_pushes_fresh_helper_state(tmp_path, monkeypatch):
    import run_ctx as RC
    import shard_relay as SR
    rel = "vid"
    vid = tmp_path / rel
    (vid / "clips").mkdir(parents=True)
    monkeypatch.setattr(SR, "ROOT", tmp_path)
    monkeypatch.setattr(RC, "vid_rel", lambda run: rel)
    monkeypatch.setattr(VS, "shard_eps", lambda run: {1: C2})
    monkeypatch.setattr(VS, "load", lambda path=None: {})

    def fake_pull(host, files, force=False):
        for f in files:
            if f.endswith(f"state_{host}.json"):
                _state(vid, host, {"ep01-S2": {"status": "done", "chosen": "v1",
                                               "renders": [{"variant": "v1", "file": f"{rel}/clips/a.mp4"}]}} if host == "gpu33" else {},
                       saved=time.time())
            elif f.endswith("a.mp4"):
                (tmp_path / f).write_bytes(b"1")
        return len(files)
    pushed = []
    monkeypatch.setattr(SR, "pull_from_helper", fake_pull)
    monkeypatch.setattr(SR, "pull_jobs", lambda owner, vid_rel, status: False)
    monkeypatch.setattr(SR, "push_to_owner", lambda owner, files, dry=False, marks_p=None: pushed.append((owner, list(files))) or len(files))
    SR.once(RUN)
    to_owner = [f for o, fs in pushed if o == "gpu36" for f in fs]
    assert f"{rel}/state_gpu33.json" in to_owner and f"{rel}/clips/a.mp4" in to_owner


# ---------------------------------------------------------------- D13：vidgen 认领取
def test_vidgen_shots_respects_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(VG, "VID", tmp_path)
    (tmp_path / "jobs.json").write_text(json.dumps({"shots": [
        {"shot": "ep01-S1", "ep": 1, "host": "gpu33"}, {"shot": "ep01-S2", "ep": 1, "host": "gpu36"}]}), encoding="utf-8")
    VS.save_claims(tmp_path, {"ep01-S1": {"host": "gpu36", "from": "gpu33", "at": time.time()}})
    R = SimpleNamespace(ctrl=lambda: {"jobs": "jobs.json", "eps": [1]}, st={"shots": {}})
    for host, want in (("gpu36", {"ep01-S1", "ep01-S2"}), ("gpu33", set())):
        R.host = host
        got, _c = VG.Runner.jobs(R)
        assert set(got) == want


def test_lane_last_foreign_starts_at_zero():
    assert VG.Lane("gpu36:0", 8188).last_foreign == 0.0


# ---------------------------------------------------------------- D8：尾帧回退 I2VA / 派不了 → blocked
def _takes(tmp_path, sid, doc):
    ep, s = sid.split("-")
    p = tmp_path / "renders" / ep / s
    p.mkdir(parents=True)
    (p / "takes.json").write_text(json.dumps(doc), encoding="utf-8")


def test_build_jobs_last_frame_fallback_bound_to_first(tmp_path, monkeypatch):
    import build_jobs as B
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(B, "RENDERS", Path("renders"))
    _takes(tmp_path, "ep01-S1", {"active": {"image": 2}, "last_frame_fallback": {"mode": "i2va", "first_n": 2}})
    _takes(tmp_path, "ep01-S2", {"active": {"image": 3}, "last_frame_fallback": {"mode": "i2va", "first_n": 2}})   # 首帧换了 → 作废
    _takes(tmp_path, "ep01-S3", {"last_frame_fallback": "i2va"})
    _takes(tmp_path, "ep01-S4", {"active": {"image": 1}})
    assert B.last_frame_fallbacks() == {"ep01-S1": "i2va", "ep01-S3": "i2va"}


def test_compile_variant_fallback_shot_is_i2va(monkeypatch):
    import build_jobs as B
    seen = []

    def fake_compile(spec, reg, **kw):
        seen.append(kw["overrides"].get("keyframes.last_frame_mode"))
        return {"status": "needs_writer", "reason": "stop"}
    monkeypatch.setattr(B.C, "compile_shot", fake_compile)
    monkeypatch.setattr(B, "_no_last", lambda spec: False)
    monkeypatch.setattr(B, "LAST_FALLBACK", {"ep01-S1": "i2va"})
    B.compile_variant(SimpleNamespace(id="ep01-S1"), None, "r", 1, "v1", {})
    B.compile_variant(SimpleNamespace(id="ep01-S2"), None, "r", 1, "v1", {})
    assert seen == ["none", None]


def _runner(monkeypatch):
    ev, logs = [], []
    monkeypatch.setattr(VG, "log", lambda host, *a: logs.append(" ".join(str(x) for x in a)))
    R = SimpleNamespace(lock=threading.Lock(), host="gpu36", st={"shots": {}, "events": []})
    R.event = lambda k, **kw: ev.append((k, kw))
    return R, ev, logs


def test_undispatchable_blocks_then_unblocks(monkeypatch):
    monkeypatch.setattr(VG, "policy_ok", lambda var: True)
    R, ev, _ = _runner(monkeypatch)
    sh = {"variants": {"v1": {"status": "bad_lora:x"}, "s2": {"status": "ready", "preflight": {"ok": False, "reasons": ["脸"]}}}}
    r = {"renders": [], "status": "pending", "chosen": None}
    why = VG.undispatchable_reason(sh, r)
    assert "v1=bad_lora" in why and "s2=preflight:脸" in why
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "blocked" and r["block_kind"] == "undispatchable" and ev[-1][1]["status"] == "blocked"
    sh["variants"]["s2"]["preflight"] = {"ok": True}                # 重编后能派
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "pending" and "block_reason" not in r and ev[-1][0] == "unblock"


def test_undispatchable_frame_wait_has_grace(monkeypatch):
    R, _ev, _ = _runner(monkeypatch)
    sh = {"variants": {"v1": {"status": "no_last_frame"}, "v2": {"status": "no_last_frame:stale_pair"}}}
    r = {"renders": [], "status": "pending", "chosen": None}
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "pending" and r["undispatchable_since"]  # 尾帧还在出：先等
    r["undispatchable_since"] = time.time() - VG.UNDISPATCHABLE_GRACE_S - 1
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "blocked" and "undispatchable_since" not in r


def test_next_variant_first_falls_through_ladder(monkeypatch):
    monkeypatch.setattr(VG, "policy_ok", lambda var: True)
    sh = {"variants": {"v1": {"status": "ready", "preflight": {"ok": False}}, "s2": {"status": "ready"}}}
    assert VG.next_variant(sh, {"renders": []}) == "s2"


def test_assemble_sources_from_accepts_still(tmp_path):
    import assemble_episode as AE
    img = tmp_path / "ff.jpg"
    img.write_bytes(b"x")
    tl = tmp_path / "tl.json"
    tl.write_text(json.dumps({"shots": [{"index": 3, "kind": "still", "file": str(img), "origin": "占位"},
                                        {"index": 4, "kind": "still", "file": str(tmp_path / "missing.jpg")}]}), encoding="utf-8")
    out = AE._sources_from(tl)
    assert list(out) == [3] and out[3]["kind"] == "still" and out[3]["missing"] and out[3]["path"] == str(img)


# ---------------------------------------------------------------- night：D8 / D10 / D12
@pytest.fixture
def night_v2(monkeypatch, tmp_path):
    orig = os.environ.get("NS_RUN")
    import night as N
    os.environ["NS_RUN"] = RUN
    N = importlib.reload(N)
    vid = tmp_path / "run" / RUN / "video"
    vid.mkdir(parents=True)
    monkeypatch.setattr(N, "VID", vid)
    monkeypatch.setattr(N, "LOG", vid / "night.log")
    try:
        yield N
    finally:
        monkeypatch.undo()
        if orig is None:
            os.environ.pop("NS_RUN", None)
        else:
            os.environ["NS_RUN"] = orig
        importlib.reload(N)


def test_ep_resolved_counts_gate_excluded(night_v2, monkeypatch):
    N = night_v2
    monkeypatch.setattr(N, "HOLD_RESOLVE_S", 0)   # PS-MASTER 11-06：等闸门满时长才算落定；此用例测“满时长后”
    monkeypatch.setattr(VS, "CONFIG", Path("/nonexistent"))
    (N.VID / "jobs.json").write_text(json.dumps({"shots": [
        {"shot": "ep01-S1", "ep": 1, "host": "gpu36", "variants": {"v1": {}}},
        {"shot": "ep01-S2", "ep": 1, "host": "gpu36", "variants": {}, "route": "hold", "gate_excluded": True}]}), encoding="utf-8")
    _state(N.VID, "gpu36", {"ep01-S1": {"status": "done", "chosen": "v1", "renders": [{}]}})
    assert N.ep_resolved(1, "gpu36")[0] is True
    _state(N.VID, "gpu36", {"ep01-S1": {"status": "rendering", "renders": [{}]}})
    assert N.ep_resolved(1, "gpu36")[0] is False
    (N.VID / "jobs.json").write_text(json.dumps({"shots": [
        {"shot": "ep01-S1", "ep": 1, "host": "gpu36", "variants": {}, "route": "hold", "gate_excluded": True}]}), encoding="utf-8")
    assert N.ep_resolved(1, "gpu36")[0] is False                 # 整集都没过闸门 = 没开始，不落定


def test_drop_stale_and_still_placeholders(night_v2, monkeypatch, tmp_path):
    N = night_v2
    monkeypatch.setattr(N, "ROOT", tmp_path)
    (tmp_path / "inputs").mkdir()
    for n in ("ep01-S1_new.jpg", "ep01-S2_a.jpg"):
        (tmp_path / "inputs" / n).write_bytes(b"x")
    man = {"shots": [{"shot": "ep01-S1", "index": 1, "proxy": "p1.mp4", "first_frame": "inputs/ep01-S1_old.jpg", "status": "done"},
                     {"shot": "ep01-S2", "index": 2, "status": "blocked", "block_reason": "没有可派的变体"},
                     {"shot": "ep01-S3", "index": 3, "proxy": "p3.mp4", "status": "done"}]}   # 没记 first_frame 的旧条目不判
    jff = {"ep01-S1": "inputs/ep01-S1_new.jpg", "ep01-S2": "inputs/ep01-S2_a.jpg", "ep01-S3": "inputs/x.jpg"}
    assert N.drop_stale(man, jff) == ["ep01-S1"]
    assert "proxy" not in man["shots"][0] and man["shots"][0]["stale"] and man["shots"][2]["proxy"] == "p3.mp4"
    man["shots"].pop()                                             # 只看占位
    tl, bad = N.assembly_sources(man, jff)
    assert bad == [] and [(s["index"], s["kind"], s["file"]) for s in tl["shots"]] == [
        (1, "still", "inputs/ep01-S1_new.jpg"), (2, "still", "inputs/ep01-S2_a.jpg")]
    assert "没有可派的变体" in tl["shots"][1]["origin"]


def test_retry_assembly_fails_fast_on_code_errors(night_v2, monkeypatch):
    N = night_v2
    sig = ["A"]
    monkeypatch.setattr(N, "asm_code_sig", lambda: sig[0])
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "S")
    st = {"eps": {"1": {"host": "h", "status": "assemble_failed", "finalized": 0, "resolved_sig": "S",
                        "assemble_err": "ModuleNotFoundError: No module named 'ns_schema'"},
                  "2": {"host": "h", "status": "assemble_failed", "finalized": 0, "resolved_sig": "S", "assemble_err": "ffmpeg 超时"}}}
    N.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "assemble_failed" and st["eps"]["1"]["assemble_fatal_sig"] == "A"
    assert st["eps"]["2"]["status"] == "rendering"                  # 非代码类照常定时重试
    N.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "assemble_failed"            # 代码没变 = 不重试
    sig[0] = "B"
    N.retry_assembly(st)
    assert st["eps"]["1"]["status"] == "rendering" and "assemble_fatal_sig" not in st["eps"]["1"]


def test_video_lanes_not_throttled_and_yield_default(night_v2):
    N = night_v2
    assert N.DEFAULT_CTRL["yield_s"] == 30
    assert N.video_shared(["gpu33:0", "gpu36:2"], {"video_lanes": ["gpu36:2"]}) == ["gpu33:0"]
    assert N.video_shared(["gpu33:0"], {}) == ["gpu33:0"]


def test_episode_report_lists_placeholders():
    import episode_report as ER
    lines = ER.placeholder_lines({"shots": [{"shot": "ep01-S1", "proxy": "p"},
                                            {"shot": "ep01-S2", "status": "blocked", "block_reason": "没有可派的变体"},
                                            {"shot": "ep01-S3", "status": "done", "stale": True, "excluded": "过期片"}]})
    assert lines == ["- ep01-S2（阻断）：没有可派的变体", "- ep01-S3（过期片）：过期片"]


def test_gate_hold_aged_needs_45min(tmp_path, monkeypatch):
    """PS-MASTER 11-06：等闸门的镜要连续等满 HOLD_RESOLVE_S 才按落定算（否则每来一镜就整集合成预览、阻塞 night）"""
    import importlib, sys
    night = sys.modules.get("night") or importlib.import_module("night")
    monkeypatch.setattr(night, "VID", tmp_path)
    assert night.gate_hold_aged(1, {"ep01-S5"}, now=1000.0) == set()
    assert night.gate_hold_aged(1, {"ep01-S5"}, now=1000.0 + night.HOLD_RESOLVE_S - 1) == set()
    assert night.gate_hold_aged(1, {"ep01-S5"}, now=1000.0 + night.HOLD_RESOLVE_S) == {"ep01-S5"}
    assert night.gate_hold_aged(1, set(), now=5000.0) == set()            # 不再等闸门 → 计时清掉
    assert night.gate_hold_aged(1, {"ep01-S5"}, now=6000.0) == set()       # 重新计时
