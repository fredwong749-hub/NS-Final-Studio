"""VID-LOOP（11-06）：ep01-S1 口型重出（K-EDT-805）死循环 + 尽力镜黑场 + REOPEN 空转。
A) 每镜作废重出有上限（config/post/director.json lip_redo_max_per_shot，默认 1）；no H3 audio 不作废；到上限后请求只记账，
   状态不变（night.ep_sig 不变 → 不再 REOPEN）；lip_redo.record 到上限不再追加单；没有在出版本的镜不会一直挂 rendering。
B) 尽力版（best_effort 的 chosen）进 manifest / 合成（L-196 用尽采用最好一版）。
C) first_take_first 不被永远派不出的“新鲜”镜锁死。"""
from __future__ import annotations

import importlib
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/series10_video", "tools/director", "services/post"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import vidgen as VG  # noqa: E402
import lip_redo as LR  # noqa: E402

TL = "data/episodes/series10_v2/ep01_v{n}.timeline.json"


def _req(tmp_path, monkeypatch, n_versions, shot="ep01-S1", fallback="CER too high", variants=None):
    req = tmp_path / "redo.json"
    rows = [{"shot": shot, "timeline": TL.format(n=i), "at": f"2026-11-06 06:{i:02d}:00", "status": "pending",
             "reason": LR.REASON, "fallback_reason": fallback, **({"variants": variants} if variants else {})}
            for i in range(1, n_versions + 1)]
    req.write_text(json.dumps({"requests": rows}), encoding="utf-8")
    monkeypatch.setattr(VG, "LIP_REDO", req)
    return req


def _runner(monkeypatch):
    ev, logs = [], []
    monkeypatch.setattr(VG, "log", lambda host, *a: logs.append(" ".join(str(x) for x in a)))
    R = type("R", (), {"lock": threading.Lock(), "host": "gpu36", "event": lambda self, k, **kw: ev.append((k, kw)),
                       "st": {"shots": {}, "events": []}})()
    return R, ev, logs


def _scored(variant, seed, penalty, fails, ff="inputs/ep01-S1_cur.jpg", t=1.0):
    return {"variant": variant, "seed": seed, "state": "scored", "file": f"video/clips/ep01/ep01-S1__{variant}_s{seed}.mp4",
            "first_frame": ff, "t_done": t, "score": {"penalty": penalty, "gate": {"pass": not fails, "fails": fails}}}


def _sig(rec):
    return json.dumps([rec.get("status"), rec.get("chosen"), len(rec.get("renders") or [])])


def test_cap_config_default_and_read(tmp_path):
    assert VG.lip_redo_cap(tmp_path / "missing.json") == 1
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"lip_redo_max_per_shot": 2}), encoding="utf-8")
    assert VG.lip_redo_cap(p) == 2 and LR.cap(p) == 2
    p.write_text("{bad", encoding="utf-8")
    assert VG.lip_redo_cap(p) == 1
    real = json.loads((ROOT / "config/post/director.json").read_text(encoding="utf-8"))
    assert real.get("lip_redo_max_per_shot") == 1


def test_lip_redo_capped_after_one_supersede(tmp_path, monkeypatch):
    """第 1 张单照旧作废重出；第 2 张（新 timeline 版本号）只记账：状态 / 入选 / 版本数都不变（→ night.ep_sig 不变，不 REOPEN）"""
    _req(tmp_path, monkeypatch, 1)
    R, ev, logs = _runner(monkeypatch)
    r = {"renders": [_scored("alt", 1, 3.5, ["景别不符"])], "status": "best_effort", "chosen": "alt"}
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert r["status"] == "pending" and r["renders"] == [] and r["lip_redo_n"] == 1 and r["superseded"][0]["rule"] == "K-EDT-805"
    # 重出后又是尽力 → 重合成 v2 → 又开一张单
    r["renders"] = [_scored("alt", 1, 3.5, ["景别不符"])]
    r.update(status="best_effort", chosen="alt")
    _req(tmp_path, monkeypatch, 2)
    before = _sig(r)
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert _sig(r) == before and r["lip_redo_capped"] is True and r["lip_redo_n"] == 1
    assert len(r["lip_redo_applied"]) == 2 and ev[-1][0] == "lip_redo_capped"
    # v3、v4 … 继续开单也只记账，不再有 lip_redo 事件
    _req(tmp_path, monkeypatch, 4)
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert _sig(r) == before and [k for k, _ in ev].count("lip_redo") == 1 and len(r["lip_redo_applied"]) == 4


def test_no_h3_audio_never_supersedes(tmp_path, monkeypatch):
    _req(tmp_path, monkeypatch, 3, fallback="no H3 audio")
    R, ev, logs = _runner(monkeypatch)
    r = {"renders": [_scored("alt", 1, 3.5, ["景别不符"])], "status": "best_effort", "chosen": "alt"}
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert r["status"] == "best_effort" and r["chosen"] == "alt" and len(r["renders"]) == 1 and "superseded" not in r
    assert r["lip_redo_skipped"] == 3 and VG.lip_redo_count(r) == 0 and ev == [("lip_redo_skip", ev[0][1])]
    assert any("LIP_REDO_SKIP" in x for x in logs)


def test_legacy_record_with_51_applied_counts_as_capped(tmp_path, monkeypatch):
    """线上 ep01-S1：lip_redo_applied 51 个键、没有 lip_redo_n → 一升级就是已到上限，不再作废"""
    _req(tmp_path, monkeypatch, 52)
    R, ev, _ = _runner(monkeypatch)
    r = {"renders": [_scored("alt", 1, 3.5, ["景别不符"])], "status": "best_effort", "chosen": "alt",
         "lip_redo_applied": [f"{TL.format(n=i)}@2026-11-06 06:{i:02d}:00" for i in range(1, 52)]}
    assert VG.lip_redo_count(r) == 51
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert r["status"] == "best_effort" and len(r["renders"]) == 1 and r["lip_redo_capped"] and ev[0][0] == "lip_redo_capped"


def test_extra_variants_request_counts_toward_cap(tmp_path, monkeypatch):
    _req(tmp_path, monkeypatch, 1, variants=["s3", "s4"])
    R, ev, _ = _runner(monkeypatch)
    r = {"renders": [_scored("alt", 1, 3.5, ["景别不符"])], "status": "best_effort", "chosen": "alt"}
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert r["force_queue"] == ["s3", "s4"] and r["lip_redo_n"] == 1 and len(r["renders"]) == 1
    _req(tmp_path, monkeypatch, 2, variants=["s3", "s4"])
    r["force_queue"] = []
    VG.Runner.check_lip_redo(R, "ep01-S1", r)
    assert r["force_queue"] == [] and r["lip_redo_capped"]


def test_restore_lip_superseded_dedupes_and_filters_first_frame():
    old = "inputs/ep01-S1_old.jpg"
    rec = {"renders": [_scored("alt", 1, 3.5, ["景别不符"], t=9)], "superseded": [
        {**_scored("v1", 7, 6.8, ["身份偏离"], t=1), "why": LR.REASON, "rule": "K-EDT-805", "superseded_at": 1},
        {**_scored("v1", 7, 6.8, ["身份偏离"], t=5), "why": LR.REASON, "rule": "K-EDT-805", "superseded_at": 5},
        {**_scored("alt", 1, 3.5, ["景别不符"], t=2), "why": LR.REASON, "rule": "K-EDT-805", "superseded_at": 2},
        {**_scored("s2", 2, 3.49, ["景别不符"], t=3), "why": LR.REASON, "rule": "K-EDT-805", "superseded_at": 3},
        {**_scored("mot", 3, 0.1, [], ff=old, t=4), "why": LR.REASON, "rule": "K-EDT-805", "superseded_at": 4},
        {**_scored("mot", 4, 0.2, [], t=4), "why": "首帧换版 / 撤销"},
    ]}
    n = VG.restore_lip_superseded(rec, "inputs/ep01-S1_cur.jpg")
    assert n == 2                                           # v1（取最新 t=5）+ s2；alt 已在 renders；mot 旧首帧 / 非口型作废不拿
    got = {(x["variant"], x["seed"]): x for x in rec["renders"]}
    assert set(got) == {("alt", 1), ("v1", 7), ("s2", 2)} and got[("v1", 7)]["t_done"] == 5
    assert all("why" not in x and "rule" not in x for x in rec["renders"]) and got[("s2", 2)]["restored_from_lip_redo"]
    assert [x.get("variant") for x in rec["superseded"]] == ["mot", "mot"]
    assert VG.restore_lip_superseded(rec, None) == 0 and VG.restore_lip_superseded(rec, "inputs/ep01-S1_cur.jpg") == 0


def test_settle_rec():
    r = {"renders": [_scored("v1", 1, 2.0, ["动作不足"]), _scored("s2", 2, 0.3, []), _scored("s3", 3, 0.1, [])]}
    assert VG.settle_rec(r) == "done" and r["chosen"] == "s3"
    r = {"renders": [_scored("v1", 1, 2.0, ["动作不足"]), _scored("s2", 2, 1.5, ["景别不符"]), {"variant": "s3", "state": "error"}]}
    assert VG.settle_rec(r) == "best_effort" and r["chosen"] == "s2"
    assert VG.settle_rec({"renders": [{"variant": "v1", "state": "error"}]}) == "blocked"


def _shot(variants=("v1", "r24", "alt", "s2"), ff="inputs/ep01-S1_cur.jpg", recipe="i2va_pika_flex"):
    return {"shot": "ep01-S1", "ep": 1, "idx": 1, "first_frame": ff,
            "variants": {v: {"status": "ready", "seed": i + 1, "recipe": recipe, "frames": 60, "prompt": ""} for i, v in enumerate(variants)}}


def test_repair_idle_restores_when_capped_and_settles(monkeypatch):
    monkeypatch.setattr(VG, "policy_ok", lambda var: True)
    R, ev, logs = _runner(monkeypatch)
    sh = _shot()
    r = {"renders": [_scored("v1", 1, 6.8, ["身份偏离"]), _scored("r24", 2, 6.8, ["身份偏离"]), _scored("alt", 3, 3.5, ["景别不符"])],
         "status": "rendering", "chosen": None, "lip_redo_capped": True, "lip_redo_applied": ["a"],
         "superseded": [{**_scored("s2", 4, 3.4, ["景别不符"]), "why": LR.REASON, "rule": "K-EDT-805"}]}
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "best_effort" and r["chosen"] == "s2" and len(r["renders"]) == 4 and r["superseded"] == []
    assert [k for k, _ in ev] == ["lip_redo_restore", "shot_done"]


def test_repair_idle_leaves_shots_with_next_variant_or_in_flight(monkeypatch):
    monkeypatch.setattr(VG, "policy_ok", lambda var: True)
    R, ev, _ = _runner(monkeypatch)
    sh = _shot()
    r = {"renders": [_scored("v1", 1, 6.8, ["身份偏离"])], "status": "retry", "chosen": None}
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)          # 还有 r24 / alt / s2 可出 → 照常派，不定下
    assert r["status"] == "retry" and ev == []
    r = {"renders": [_scored("v1", 1, 6.8, ["身份偏离"]), {"variant": "r24", "state": "submitted"}], "status": "rendering", "chosen": None}
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "rendering" and ev == []
    r = {"renders": [], "status": "pending", "chosen": None}
    VG.Runner.repair_idle(R, "ep01-S1", sh, r)
    assert r["status"] == "pending"


def test_repair_orphans_settles_reassigned_shot(monkeypatch):
    """ep01-S1 被 gpu33 领走（jobs.json host 变了）后 gpu36 的记录不再永远挂 rendering"""
    R, ev, _ = _runner(monkeypatch)
    R.st["shots"] = {"ep01-S1": {"renders": [_scored("alt", 3, 3.5, ["景别不符"])], "status": "rendering", "chosen": None},
                     "ep01-S9": {"renders": [], "status": "rendering", "chosen": None},
                     "ep01-S2": {"renders": [{"variant": "v1", "state": "submitted"}], "status": "rendering", "chosen": None},
                     "ep01-S10": {"renders": [_scored("v1", 1, 1.0, ["x"])], "status": "rendering", "chosen": None}}
    VG.Runner.repair_orphans(R, {"ep01-S10": _shot()})
    s = R.st["shots"]
    assert s["ep01-S1"]["status"] == "best_effort" and s["ep01-S1"]["chosen"] == "alt" and s["ep01-S1"]["orphan_settled"]
    assert s["ep01-S9"]["status"] == "pending"
    assert s["ep01-S2"]["status"] == "rendering"            # 还在出，不动
    assert s["ep01-S10"]["status"] == "rendering"           # 本机作业里的镜交 pending / after_score 处理


def test_first_take_first_ignores_undispatchable_fresh_shots():
    shots = {"ep02-S1": {"variants": {"v1": {}}}, "ep01-S1": {"variants": {"v1": {}}}}
    recs = {"ep02-S1": {"renders": [], "status": "pending"}, "ep01-S1": {"renders": [{"variant": "v1"}], "status": "retry"}}
    todo = [("ep01-S1", "s2")]              # ep02-S1 的变体全被政策 / preflight 挡住 → 不在 todo
    assert VG.first_take_first(todo, shots, recs) == [("ep01-S1", "s2")]      # 以前：[]（整台空转）
    todo2 = [("ep02-S1", "v1"), ("ep01-S1", "s2")]
    assert VG.first_take_first(todo2, shots, recs) == [("ep02-S1", "v1")]      # 真能派的新鲜镜仍然优先


def test_proxies_include_best_effort_chosen(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(VG.subprocess, "run", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(VG, "ROOT", tmp_path)
    monkeypatch.setattr(VG, "RUN_ID", "series10_v2")
    vid = tmp_path / "video"
    monkeypatch.setattr(VG, "VID", vid)
    (vid / "clips" / "ep01").mkdir(parents=True)
    for n in ("ep01-S1__alt_s3.mp4", "ep01-S3__s2_s2.mp4", "ep01-S2__v1_s1.mp4"):
        (vid / "clips" / "ep01" / n).write_bytes(b"x")
    st = {"shots": {
        "ep01-S1": {"status": "best_effort", "chosen": "alt", "renders": [{"variant": "alt", "seed": 3, "state": "scored", "file": "video/clips/ep01/ep01-S1__alt_s3.mp4", "score": {"gate": {"pass": False, "fails": ["景别不符"]}}}]},
        "ep01-S2": {"status": "done", "chosen": "v1", "renders": [{"variant": "v1", "seed": 1, "state": "scored", "file": "video/clips/ep01/ep01-S2__v1_s1.mp4", "score": {"gate": {"pass": True}}}]},
        "ep01-S3": {"status": "best_effort", "chosen": "s2", "renders": [{"variant": "s2", "seed": 2, "state": "scored", "file": "video/clips/ep01/ep01-S3__s2_s2.mp4", "score": {"gate": {"pass": False, "fails": ["脸部泛红"]}}}]},
        "ep01-S4": {"status": "blocked", "chosen": None, "renders": [{"variant": "v1", "state": "error"}]},
        "ep02-S1": {"status": "done", "chosen": "v1", "renders": []}}}
    VG.jsave(vid / "state_gpu36.json", st)
    import video_shard as VS
    monkeypatch.setattr(VS, "ep_cfg", lambda run, ep, cfg=None: None)
    VG.proxies("gpu36", 1)
    man = json.loads((vid / "episodes" / "ep01" / "manifest.json").read_text(encoding="utf-8"))
    by = {s["shot"]: s for s in man["shots"]}
    assert set(by) == {"ep01-S1", "ep01-S2", "ep01-S3", "ep01-S4"}
    assert by["ep01-S1"]["proxy"] and by["ep01-S1"]["best_effort"] and by["ep01-S1"]["source"].endswith("ep01-S1__alt_s3.mp4")
    assert by["ep01-S3"]["proxy"] and by["ep01-S3"]["source"].endswith("ep01-S3__s2_s2.mp4") and "excluded" not in by["ep01-S3"]
    assert by["ep01-S2"]["proxy"] and "best_effort" not in by["ep01-S2"]
    assert "proxy" not in by["ep01-S4"]
    assert len(calls) == 3


def test_sync_chosen_clips_include_best_effort(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sync_vl", ROOT / "tools/series10_video/sync.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "VID_REL", "video")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "state_gpu36.json").write_text(json.dumps({"shots": {
        "ep01-S3": {"status": "best_effort", "chosen": "s2", "renders": [{"variant": "s2", "file": "video/clips/ep01/a.mp4"}]},
        "ep01-S4": {"status": "blocked", "chosen": None, "renders": []}}}), encoding="utf-8")
    assert S.chosen_clips("gpu36") == ["video/clips/ep01/a.mp4"]


def test_lip_redo_record_stops_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(LR, "REQ", tmp_path / "redo_requests.json")
    monkeypatch.setattr(LR, "ROOT", tmp_path)
    tl = {"episode": 1, "shots": [{"index": 1, "shot": "ep01-S1", "placeholder": True}],
          "speech": [{"shot": 1, "kind": "dialogue"}], "h3_dialogue": [{"shot": 1, "dialogue": "tts_fallback", "fallback_reason": "no H3 audio"}]}
    for n in (1, 2, 3):
        p = tmp_path / f"ep01_v{n}.timeline.json"
        p.write_text(json.dumps(tl), encoding="utf-8")
        rows = LR.record(p)
        assert [r["shot"] for r in rows] == ["ep01-S1"]
        if n > 1:
            assert rows[0]["capped"] == 1
    reqs = json.loads((tmp_path / "redo_requests.json").read_text(encoding="utf-8"))["requests"]
    assert len(reqs) == 1 and reqs[0]["timeline"].endswith("ep01_v1.timeline.json")      # 以前：3 张（每版一张）


def test_repair_lip_loop_script_on_legacy_state(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_repair_vl", ROOT / "tools/series10_video/repair_lip_loop.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    cur = "inputs/ep01-S1_cur.jpg"
    rec = {"status": "rendering", "chosen": None, "lip_redo_applied": [f"k{i}" for i in range(51)],
           "renders": [_scored("v1", 1, 6.8, ["身份偏离"]), _scored("r24", 1, 6.8, ["身份偏离"]), _scored("alt", 2, 3.495, ["景别不符"])],
           "superseded": [{**_scored("s2", 2, 3.495, ["景别不符"], t=i), "why": LR.REASON, "rule": "K-EDT-805"} for i in range(50)]
           + [{**_scored("mot", 9, 0.165, [], ff="inputs/ep01-S1_old.jpg"), "why": "首帧换版 / 撤销"}]}
    jobs = {"shots": [{"shot": "ep01-S1", "host": "gpu36", "first_frame": cur}]}
    assert M.current_first_frame("ep01-S1", rec, jobs) == cur
    assert M.current_first_frame("ep01-S1", rec, {}) == cur          # 不在作业里 → 取最新一条的首帧
    res = M.repair(rec, cur, 1)
    assert res["restored"] == 1 and res["after"]["status"] == "best_effort" and res["after"]["chosen"] == "alt"
    assert rec["lip_redo_n"] == 51 and rec["lip_redo_capped"] and len(rec["renders"]) == 4 and len(rec["superseded"]) == 1
    req = {"requests": [{"shot": "ep01-S1", "status": "pending"}, {"shot": "ep01-S1", "status": "pending"}, {"shot": "ep01-S4", "status": "pending"}]}
    assert M.cap_requests(req, "ep01-S1") == 2 and [q["status"] for q in req["requests"]] == ["capped", "capped", "pending"]
    busy = {"status": "rendering", "renders": [{"variant": "v1", "state": "submitted"}]}
    assert "skipped" in M.repair(busy, cur, 1)


def test_night_ep_sig_stable_after_cap(tmp_path, monkeypatch):
    """C) 到上限后 state 不再变 → ep_sig 不变 → reopen_changed 不再 REOPEN"""
    orig = os.environ.get("NS_RUN")
    import night as N
    os.environ["NS_RUN"] = "series10_v2"
    N = importlib.reload(N)
    try:
        vid = tmp_path / "video"
        vid.mkdir()
        monkeypatch.setattr(N, "VID", vid)
        monkeypatch.setattr(N, "LOG", vid / "night.log")
        monkeypatch.setattr(N, "_shard_cfg", lambda ep: None)
        _req(tmp_path, monkeypatch, 3)
        R, ev, _ = _runner(monkeypatch)
        r = {"renders": [_scored("alt", 1, 3.5, ["景别不符"])], "status": "best_effort", "chosen": "alt", "lip_redo_n": 1}
        VG.jsave(vid / "state_gpu36.json", {"shots": {"ep01-S1": r, "ep01-S2": {"status": "done", "chosen": "v1", "renders": [{}]}}})
        sig0 = N.ep_sig(1, "gpu36")
        VG.Runner.check_lip_redo(R, "ep01-S1", r)
        VG.jsave(vid / "state_gpu36.json", {"shots": {"ep01-S1": r, "ep01-S2": {"status": "done", "chosen": "v1", "renders": [{}]}}})
        assert N.ep_sig(1, "gpu36") == sig0
        st = {"eps": {"1": {"status": "assembled", "resolved_sig": sig0, "host": "gpu36"}}}
        logs = []
        monkeypatch.setattr(N, "log", lambda *a: logs.append(a))
        N.reopen_changed(st)
        assert st["eps"]["1"]["status"] == "assembled" and not any("REOPEN" in str(x) for x in logs)
    finally:
        monkeypatch.undo()
        if orig is None:
            os.environ.pop("NS_RUN", None)
        else:
            os.environ["NS_RUN"] = orig
        importlib.reload(N)
