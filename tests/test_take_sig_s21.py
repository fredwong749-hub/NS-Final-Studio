"""S2.1（L209_S2_PLAN）：take 签名 + 签名不符自动换代。全 fixture，不碰真实数据 / 服务器。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/autopilot", "services/render_router", "services/agent", "packages/schema"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import take_sig as TS  # noqa: E402

RUN = "tv_sig"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    TS._cache.clear()
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    for f in TS.RULE_FILES:
        (tmp_path / f).write_text('{"v": 1}', encoding="utf-8")
    script = tmp_path / "data" / "import" / "runs" / RUN / "script_v2.json"
    script.parent.mkdir(parents=True)
    shots = [{"index": i, "img_prompt": f"镜{i} 原稿", "cast": ["a"]} for i in (1, 2, 3)]
    script.write_text(json.dumps({"episodes": [{"number": 1, "shots": shots}]}, ensure_ascii=False), encoding="utf-8")
    jobs = tmp_path / "data" / "pipeline" / "runs" / RUN / "assets" / "first_frame_jobs.json"
    jobs.parent.mkdir(parents=True)
    jobs.write_text(json.dumps({"jobs": [{"shot": f"ep01-S{i}", "prompt": f"p{i}"} for i in (1, 2, 3)]}), encoding="utf-8")
    monkeypatch.setattr(TS, "run_files", lambda root, run: (script, jobs))
    takes = {}
    regens = []
    logs = []

    def mk(sid, stage="image", n=1, sig=True, created="2026-11-06T20:00:00", trace=None, **extra):
        t = {"n": n, "stage": stage, "created_at": created, **extra}
        if sig:
            cur = TS.current(tmp_path, sid, script, jobs)
            t["sig"] = TS.for_new_take(tmp_path, sid, stage, {"params": {"compile_trace": {"prompt_sha": trace}}} if trace else {},
                                       script, jobs)
            assert t["sig"]["script_sig"] == cur["script_sig"]
        if trace:
            t.setdefault("params", {})["compile_trace"] = {"prompt_sha": trace}
        d = takes.setdefault(sid, {"takes": [], "active": {}})
        d["takes"].append(t)
        d["active"][stage] = n
        return t

    def run(mode="record", adult=(), triggers=(), status="producing", rejects=None, c=None, events=None):
        cc = {**TS.cfg(tmp_path), **(c or {})}
        return TS.check_run(tmp_path, RUN, sorted(takes), lambda s: takes.get(s, {"takes": [], "active": {}}), mode=mode, c=cc,
                            adult_shots=set(adult), triggers=set(triggers), run_status=status, rejects=rejects or {},
                            state_file=tmp_path / "pd" / "take_sig_state.json",
                            regen_fn=lambda s, why: (regens.append(list(s)), {"regen": list(s), "skipped": {}})[1],
                            log=lambda ev, **k: logs.append((ev, k)), events=events or tmp_path / "imports.jsonl")

    def edit_script(i, text):
        d = json.loads(script.read_text(encoding="utf-8"))
        d["episodes"][0]["shots"][i - 1]["img_prompt"] = text
        script.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        import os
        st = script.stat()
        os.utime(script, (st.st_atime, st.st_mtime + 5))

    return type("E", (), dict(root=tmp_path, script=script, jobs=jobs, takes=takes, mk=staticmethod(mk), run=staticmethod(run),
                              regens=regens, logs=logs, edit_script=staticmethod(edit_script)))


def test_rule_fp_and_fields_match_producer():
    import producer as PR
    assert TS.RULE_FILES == PR.BE_RULE_FILES and TS.INPUT_FIELDS == PR.INPUT_FIELDS
    assert TS.rule_fp(ROOT) == PR.be_rule_sig(ROOT)


def test_signature_recorded_on_new_take(env, monkeypatch):
    from ns_render import pipeline as P
    from ns_schema.edits import Take
    monkeypatch.setattr(P, "_take_sig", lambda sid, take: TS.for_new_take(env.root, sid, take.stage, take.model_dump(), env.script, env.jobs))
    t = Take(n=1, stage="image", file="x.png", seed=1, prompt="p", created_at="2026-11-06T20:00:00",
             params={"compile_trace": {"prompt_sha": "trace123"}})
    P.stamp_versions("ep01-S1", t)
    assert set(t.sig) >= {"script_sig", "prompt_sha", "rule_fp"} and t.sig["prompt_sha"] == "trace123"
    assert "sig" in t.model_dump()
    (env.root / TS.STATE_CFG).write_text(json.dumps({"take_sig": {"mode": "off"}}), encoding="utf-8")
    t2 = Take(n=2, stage="last", file="y.png", seed=1, prompt="p", created_at="2026-11-06T20:00:00")
    P.stamp_versions("ep01-S1", t2)
    assert t2.sig is None                               # off：不盖签名


def test_per_part_mismatch(env):
    env.mk("ep01-S1"); env.mk("ep01-S1", "last"); env.mk("ep01-S2")
    hb = env.run()
    assert hb["stale"] == {"first": 0, "last": 0, "video": 0}
    env.edit_script(1, "镜1 新稿")                       # 只改 S1 剧本
    hb = env.run()
    assert hb["stale"]["first"] == 1 and hb["stale"]["last"] == 1
    ev = [k for e, k in env.logs if e == "sig_stale"]
    assert {k["obj"] for k in ev} == {"first:ep01-S1", "last:ep01-S1"} and all(k["parts"] == ["script_sig"] for k in ev)
    (env.root / TS.RULE_FILES[0]).write_text('{"v": 2}', encoding="utf-8")   # 规则变 → 全部 rule_fp
    env.logs.clear()
    hb = env.run()
    assert hb["stale"]["first"] == 2
    assert any(k["obj"] == "first:ep01-S2" and k["parts"] == ["rule_fp"] for e, k in env.logs if e == "sig_stale")
    # 编译提示词变（只比首帧）
    env.logs.clear()
    env.jobs.write_text(json.dumps({"jobs": [{"shot": "ep01-S2", "prompt": "p2-new"}]}), encoding="utf-8")
    TS._cache.pop(f"jobs:{env.jobs}", None)
    env.run()
    assert any(k["obj"] == "first:ep01-S2" and "prompt_sha" in k["parts"] for e, k in env.logs if e == "sig_stale")


def test_record_mode_takes_no_action(env):
    env.mk("ep01-S1")
    env.edit_script(1, "改")
    hb = env.run("record")
    assert hb["stale"]["first"] == 1 and hb["regen"] == [] and env.regens == []
    assert not (env.root / "pd" / "take_sig_state.json").exists()
    env.run("record")
    assert len([1 for e, _ in env.logs if e == "sig_stale"]) == 1   # 同一签名只记一次


def test_enforce_idempotent_and_rate_limited(env):
    for i in (1, 2, 3):
        env.mk(f"ep01-S{i}")
    (env.root / TS.RULE_FILES[1]).write_text('{"v": 9}', encoding="utf-8")   # 全局规则变 → 3 镜都不符
    hb = env.run("enforce", c={"max_regen_per_tick": 2, "max_pending": 6, "rule_fp_enforce": True})   # 复审 11-07：rule_fp 换代须显式开
    assert len(hb["regen"]) == 2 and env.regens == [hb["regen"]]
    hb2 = env.run("enforce", c={"max_regen_per_tick": 2, "max_pending": 6, "rule_fp_enforce": True})
    assert hb2["regen"] == ["ep01-S3"]                                   # 已换代的不再换；剩下的下一拍
    hb3 = env.run("enforce", c={"max_regen_per_tick": 2, "max_pending": 6, "rule_fp_enforce": True})
    assert hb3["regen"] == [] and len(env.regens) == 2                    # 幂等
    # 在换代中的总量上限
    TS._cache.clear()
    (env.root / "pd" / "take_sig_state.json").unlink()
    rj = {f"first:ep01-S{i}": {"regen": {"by": TS.BY}} for i in (1, 2)}
    hb4 = env.run("enforce", rejects=rj, c={"max_regen_per_tick": 5, "max_pending": 2, "rule_fp_enforce": True})
    assert hb4["regen"] == []


def test_adult_untriggered_never_regen(env):
    env.mk("ep01-S1"); env.mk("ep01-S2")
    env.edit_script(1, "改"); env.edit_script(2, "改")
    hb = env.run("enforce", adult={"ep01-S1", "ep01-S2"}, triggers={f"{RUN}/first:ep01-S2"})
    assert hb["regen"] == ["ep01-S2"] and "成人" in hb["skipped"]["ep01-S1"]


def test_owner_locked_untouched(env):
    env.mk("ep01-S1")
    env.takes["ep01-S1"]["locked"] = {"image": 1}
    env.edit_script(1, "改")
    hb = env.run("enforce")
    assert hb["regen"] == [] and env.regens == []


def test_frozen_run_untouched(env):
    env.mk("ep01-S1")
    env.edit_script(1, "改")
    for st in ("frozen", "archived"):
        hb = env.run("enforce", status=st)
        assert hb["regen"] == [] and hb["stale"]["first"] == 0
    assert env.regens == []


def test_unknown_signature_rule(env):
    ev = env.root / "imports.jsonl"
    # 导入 21:53 JST（ts 精确）改了 S1、S2；S3 没改
    import datetime as dt
    ts = dt.datetime(2026, 11, 6, 21, 53, tzinfo=dt.timezone(dt.timedelta(hours=9))).timestamp()
    ev.write_text(json.dumps({"at": "2026-11-06T07:53:45", "ts": ts, "run_id": RUN, "episodes": [1],
                              "changed_shots": ["ep01-S1", "ep01-S2"]}) + "\n", encoding="utf-8")
    env.mk("ep01-S1", sig=False, created="2026-11-06T21:35:00", trace="oldsha")       # 早于导入 + 提示词变了 → 换
    env.mk("ep01-S2", sig=False, created="2026-11-06T21:35:00", trace=TS._sha16("p2"))  # 提示词没变 → 留
    env.mk("ep01-S3", sig=False, created="2026-11-06T21:35:00", trace="oldsha")       # 本镜没被导入改 → 留
    hb = env.run("record", events=ev)
    assert hb["unknown"]["first"] == 3 and env.regens == []
    TS._cache.clear()
    hb = env.run("enforce", events=ev)
    assert hb["regen"] == ["ep01-S1"]
    why = {k["obj"]: k["why"] for e, k in env.logs if e == "sig_unknown_left"}
    assert why == {"first:ep01-S2": "编译提示词没变", "first:ep01-S3": "不早于本镜最后一次导入"}


def test_unknown_unrecoverable_switch_and_legacy_tz(env):
    ev = env.root / "imports.jsonl"
    # 旧事件只有无时区 at（笔记本美东写的 07:53 = 21:53 JST）：按最晚解读，21:35 JST 的版本算“早于导入”
    ev.write_text(json.dumps({"at": "2026-11-06T07:53:45", "run_id": RUN, "episodes": [1], "changed_shots": ["ep01-S1"]}) + "\n",
                  encoding="utf-8")
    env.mk("ep01-S1", sig=False, created="2026-11-06T21:35:00")       # 没有 compile_trace = 不可恢复
    hb = env.run("enforce", events=ev)
    assert hb["regen"] == []                                           # 默认 leave
    TS._cache.clear()
    hb = env.run("enforce", events=ev, c={"unknown_unrecoverable": "predates"})
    assert hb["regen"] == ["ep01-S1"]


def test_cfg_defaults(tmp_path):
    assert TS.cfg(tmp_path)["mode"] == "record"
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / TS.STATE_CFG).write_text(json.dumps({"take_sig": {"mode": "bogus"}}), encoding="utf-8")
    assert TS.cfg(tmp_path)["mode"] == "record"
    assert TS.cfg(ROOT)["mode"] == "record"                            # 仓库默认 record


def test_producer_tick_wiring(tmp_path, monkeypatch):
    """producer.take_sig_tick：读开关 / runs.json 状态 → check_run；心跳字段 sig_stale；off 不跑；关闭的集不换代"""
    import producer as PR
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / "config" / "pipeline" / "runs.json").write_text(json.dumps({"runs": {RUN: {"status": "frozen"}}}), encoding="utf-8")
    pr = object.__new__(PR.Producer)
    pr.p = type("P", (), {"root": tmp_path, "run_id": RUN, "pd": tmp_path / "pd", "rejects": tmp_path / "rj.json"})()
    logs, seen, regen_calls = [], {}, []
    pr.logf = lambda ev, **k: logs.append(ev)
    pr.ep_closed_skip = lambda oid, actor: oid == "first:ep01-S2"
    monkeypatch.setattr(PR, "shots_of_all", lambda p: ["ep01-S1", "ep01-S2"])
    monkeypatch.setattr(PR, "regen_shots", lambda p, shots, why, by: (regen_calls.append(shots), {"regen": shots})[1])

    def fake(root, run, shots, lt, **k):
        seen.update(k)
        k["regen_fn"](shots, "x")
        return {"mode": k["mode"], "stale": {"first": 1, "last": 0, "video": 0}, "unknown": {"first": 0, "last": 0, "video": 0}}
    monkeypatch.setattr(TS, "check_run", fake)
    assert pr.take_sig_tick()["mode"] == "record"
    assert seen["run_status"] == "frozen" and pr._take_sig_hb["sig_stale"]["first"] == 1
    assert regen_calls == [["ep01-S1"]]                                 # 关闭的集（S2）被滤掉
    assert pr.take_sig_tick() is None                                    # every_s 节流
    (tmp_path / TS.STATE_CFG).write_text(json.dumps({"take_sig": {"mode": "off"}}), encoding="utf-8")
    pr._take_sig_chk = 0
    assert pr.take_sig_tick() is None


def test_cfg_bad_numbers_fall_back_and_rule_fp_record_only(tmp_path):
    """复审 11-07：state.json 数值写错不抛错（按默认）；rule_fp 默认只记录"""
    import json
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / "config" / "pipeline" / "state.json").write_text(json.dumps({"take_sig": {"mode": "enforce", "max_regen_per_tick": "x", "every_s": None}}), encoding="utf-8")
    c = TS.cfg(tmp_path)
    assert c["mode"] == "enforce" and c["max_regen_per_tick"] == 2 and c["every_s"] == 60.0 and c["rule_fp_enforce"] is False

def test_rule_fp_only_change_is_record_only(env):
    """复审 11-07：只是规则配置变了（rule_fp）→ 默认不换代（只记录）"""
    env.mk("ep01-S1")
    (env.root / TS.RULE_FILES[1]).write_text('{"v": 10}', encoding="utf-8")
    hb = env.run("enforce", c={"max_regen_per_tick": 2, "max_pending": 6})
    assert hb["regen"] == [] and "rule_fp" in hb["skipped"]["ep01-S1"]
