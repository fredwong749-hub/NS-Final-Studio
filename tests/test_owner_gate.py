"""写作链项目方闸门（tools/script_rsi/owner_gate.py + autoflow_agent.p1_gate / ep_gate）与网页接口（ns_api.script_autoflow：tasks / gate / brief / import）。
总调度 11-02：缺口 1 → 3 → 2 → 5 → 4。不调网关、不写真实数据。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
LT = _load("looks_table", "tools/script_rsi/looks_table.py")


def test_gate_actions(tmp_path):
    assert not OG.enabled(tmp_path)
    OG.enable(tmp_path)
    assert OG.get(tmp_path, "P1")["status"] == "pending" and OG.get(tmp_path, "ep03")["status"] == "approved"
    with pytest.raises(ValueError):
        OG.act(tmp_path, "P1", "reject")                 # L-123：没有“不要”
    with pytest.raises(ValueError):
        OG.act(tmp_path, "P1", "revise", "")             # “修改”要一句话
    g = OG.act(tmp_path, "P1", "revise", "第三集节奏太慢")
    assert g["status"] == "revise_requested" and not g["handled"]
    (tmp_path / "P1_storyline.json").write_text("{}", encoding="utf-8")       # 旧 run（非完全切割）没有评审状态：有故事线即可
    assert OG.act(tmp_path, "P1", "approve")["status"] == "approved"
    assert len(OG.summary(tmp_path)["history"]) >= 3


def test_looks_parse_list_and_closed(tmp_path):
    looks, err = LT.parse('```json\n[{"name": "x", "char_id": "lead_f", "looks": [{"id": "O1"}]}]\n```')
    assert looks and not err                             # 列表回稿（hollywood._json_block 会截坏）
    (tmp_path / "assets_v2").mkdir()
    (tmp_path / "assets_v2" / "owner_inputs.json").write_text(json.dumps({"items": [
        {"kind": "outfit", "outfit_id": "O1", "name": "a", "file": "f"}, {"kind": "outfit", "outfit_id": "O2", "name": "b", "file": "g"}]}), encoding="utf-8")
    assert any("少了清单里的造型" in p for p in LT.closed_check(looks, tmp_path))
    looks[0]["looks"].append({"id": "O9"})
    assert any("清单外" in p for p in LT.closed_check(looks, tmp_path))


def test_agent_gate_wiring():
    ag = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    assert ag.count("p1_gate(RCH, run_dir, ep, st, ctx, canon)") == 2       # P1 复用 / 新收稿两条路都过闸
    assert "if not ep_gate(run_dir, ep, st):" in ag and "awaiting_owner_p1" in ag


@pytest.fixture()
def api(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "services" / "api"))
    SA = _load("script_autoflow_t", "services/api/ns_api/script_autoflow.py")
    monkeypatch.setattr(SA, "RUNS", tmp_path)
    monkeypatch.setattr(SA, "_spawn", lambda run_id, body, owner_ok=False: {"started": True, "episode": body.episode, "mode": body.import_mode})
    monkeypatch.setattr(SA, "_actor", lambda request: "owner" if request is not None else "未登录")
    return SA


class _Req:                     # 已登录请求的替身（_actor 被替换成：非 None = owner）
    pass


LOGGED_IN = _Req()


def test_brief_tasks_gate_import(api, tmp_path):
    r = api.brief("demo_run", api.BriefBody(theme="上海时尚模特的幻想和现实", assets=["assets_v2/owner_inputs.json"], style="杂志大片", clean_cut=True))
    assert r["ok"] and r["owner_gates"] and r["clean_cut"] and (tmp_path / "demo_run" / "P0_brief.json").exists()
    d = tmp_path / "demo_run"
    (d / "writer_tasks").mkdir()
    (d / "writer_out").mkdir()
    (d / "writer_tasks" / "P1_a1.json").write_text(json.dumps({"step": "P1", "role": "writer", "attempt": 1,
                                                               "output": {"path": str(d / "writer_out" / "P1_a1.json")}}), encoding="utf-8")
    t = api.tasks("demo_run")
    assert t["tasks"][0]["step"] == "P1" and t["tasks"][0]["answered"] is False and t["owner_gates"]["enabled"]
    g = api.gate("demo_run", api.GateBody(key="P1", action="revise", note="男二动机不清楚", by="伪造的人"), LOGGED_IN)
    assert g["accepted"] and g["gate"]["status"] == "revise_requested" and g["started"]["episode"] == 1
    assert g["gate"]["by"] != "伪造的人"      # by 取登录会话，不信前端传的值（OVERSIGHT-F）
    (d / "autoflow.json").write_text(json.dumps({"verdict": "imported"}), encoding="utf-8")
    assert api.owner_import("demo_run", api.StartBody(episode=1))["mode"] == "live"      # imported 也能再覆盖导入


def test_p1_review_threshold_from_config():
    """W-19：门槛读 config/prompts/hollywood_p1_review.yaml；均分 < 门槛、条目均分 ≤ 2、评委重复都不过"""
    AG = _load("autoflow_agent_t", "tools/script_rsi/autoflow_agent.py")
    cfg = AG.review_cfg()
    assert cfg["min_mean"] == 34 and cfg["max_rounds"] == 3
    base = {"n": 3, "single_judge": False, "stable": True, "mean": 35, "item_mean": {"men": 4.0, "arc": 4.3}}
    assert AG.review_passed(base, cfg)[0]
    assert not AG.review_passed(dict(base, mean=27.33), cfg)[0]
    assert not AG.review_passed(dict(base, item_mean={"men": 2.0}), cfg)[0]
    assert not AG.review_passed(dict(base, single_judge=True), cfg)[0]
    ag = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    assert "_p1_review(RCH, run_dir, ep, st, ctx, canon, sl)" in ag and "storyline_sha" in ag


def test_failing_p1_never_reaches_owner_gate(tmp_path, monkeypatch):
    """总调度 11-02：没过门槛的 P1 绝不会进项目方闸门——三家交齐、均分 27.3 → 出返修包、verdict 不是 awaiting_owner_p1"""
    AG = _load("autoflow_agent_t2", "tools/script_rsi/autoflow_agent.py")
    rd = tmp_path / "run"
    (rd / "writer_tasks").mkdir(parents=True)
    (rd / "writer_out").mkdir()
    canon = rd / "P1_storyline.json"
    canon.write_text('{"title": "t"}', encoding="utf-8")
    OG.enable(rd)

    class St:
        def __init__(self):
            self.d = {"stages": []}

        def set(self, **k):
            self.d.update(k)

        def stage(self, sid, name, status, decider, **k):
            self.d["stages"].append({"id": sid, "status": status, **k})

        def save(self):
            pass

    class RCH:
        class WP:
            @staticmethod
            def build(link, ctx):
                return {"system": "s", "user": "u"}
    monkeypatch.setattr(AG, "live_note", lambda text: None)
    monkeypatch.setattr(AG, "_looks_step", lambda *a, **k: True)
    JA = _load("judge_agent_t", "tools/script_rsi/judge_agent.py")
    monkeypatch.setattr(AG, "_load", lambda name, rel: JA if name == "judge_agent" else _load(name + "_x", rel))
    monkeypatch.setattr(JA, "p1_collect", lambda run_dir, out=None: {"n": 3, "totals": [28, 28, 26], "mean": 27.33, "sigma": 0.94, "stable": True,
                                                                     "single_judge": False, "item_mean": {"men": 2.67}, "top_fixes": ["写清动机"]})
    st = St()
    ok = AG.p1_gate(RCH, rd, 1, st, {"storyline": {"title": "t"}}, canon)
    assert ok is False and st.d.get("verdict") != "awaiting_owner_p1"
    assert "返修中（第 1 轮，评审 27.33/40）" in st.d.get("next_action", "")
    assert (rd / "writer_tasks" / "P1_a1.json").exists() and not canon.exists()       # 旧稿改名留档、出返修包


def test_no_p2_packet_before_p1_approved(tmp_path):
    """总调度 11-02（19:17 事故）：P1 没过项目方闸门，不出任何 P2 / P3 / P4 包；完全切割 run 没有 owner_gates.json 也算有闸门"""
    AG = _load("autoflow_agent_t3", "tools/script_rsi/autoflow_agent.py")
    rd = tmp_path / "run"
    (rd / "writer_tasks").mkdir(parents=True)
    (rd / "writer_out").mkdir()
    (rd / "CLEAN_CUT.json").write_text("{}", encoding="utf-8")

    class St:
        d = {}

        def set(self, **k):
            self.d.update(k)
    assert OG.enabled(rd) and not OG.p1_approved(rd)
    with pytest.raises(RuntimeError):
        AG.packet(rd, St(), "P2_ep01", "writer", 1, "P1-P2", "s", "u", "json", [], 1)
    import hashlib
    (rd / "P1_storyline.json").write_text('{"title": "t"}', encoding="utf-8")
    (rd / "judge_p1").mkdir()
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 1, "passed": True,
        "sha": hashlib.sha256('{"title": "t"}'.encode("utf-8")).hexdigest()[:16]}]}), encoding="utf-8")
    OG.act(rd, "P1", "approve")
    AG.packet(rd, St(), "P2_ep01", "writer", 1, "P1-P2", "s", "u", "json", [], 1)
    assert (rd / "writer_tasks" / "P2_ep01_a1.json").exists()


def test_packets_have_no_advance_cmd_and_cli_logs(tmp_path, monkeypatch):
    """总调度 11-02（根因模式 1 双入口）：写作包不含 advance_cmd，只有“交稿后只建 .done”的提示；命令行推进也记 autoflow.log（来源 cli）"""
    AG = _load("autoflow_agent_t4", "tools/script_rsi/autoflow_agent.py")
    rd = tmp_path / "run"
    (rd / "writer_tasks").mkdir(parents=True)
    (rd / "writer_out").mkdir()

    class St:
        d = {}

        def set(self, **k):
            self.d.update(k)
    pk = AG.packet(rd, St(), "P1", "writer", 1, "P0-P1", "s", "u", "json", [], 1)
    assert "advance_cmd" not in pk and "只建 .done" in pk["next"]
    src = "".join(p.read_text(encoding="utf-8") for p in list((ROOT / "tools/script_rsi").glob("*.py")) + [ROOT / "tools/autopilot/flow.py"])
    assert '"advance_cmd"' not in src and "autoflow.py run --run-dir {_rel" not in src      # OVERSIGHT-F H4：flow.py 也不读 / 不拼推进命令
    AF = _load("autoflow_t", "tools/script_rsi/autoflow.py")
    monkeypatch.setattr(AF, "_load", lambda name, rel: type("AG", (), {"backend": staticmethod(lambda: "claude_agent"),
                                                                      "run": staticmethod(lambda run_dir, ep, mode: {"verdict": "awaiting_writer"})}))
    AF.main(["run", "--run-dir", str(rd), "--episode", "1"])
    log = [json.loads(x) for x in (rd / "autoflow.log").read_text(encoding="utf-8").splitlines()]
    assert log[0]["source"] == "cli" and log[-1]["verdict"] == "awaiting_writer"
    api = (ROOT / "services/api/ns_api/script_autoflow.py").read_text(encoding="utf-8")
    assert '"--source", "web"' in api


def test_pending_done_detection(tmp_path, monkeypatch):
    """生产里 awaiting.output 是仓库相对路径：按这个分支测（OVERSIGHT-F H4）"""
    AF = _load("autoflow_t2", "tools/script_rsi/autoflow.py")
    monkeypatch.setattr(AF, "ROOT", tmp_path)
    rd = tmp_path / "data" / "pipeline" / "runs" / "r1"
    (rd / "writer_out").mkdir(parents=True)
    rel = "data/pipeline/runs/r1/writer_out/P1_a2.json"
    (rd / "autoflow_ep01.json").write_text(json.dumps({"episode": 1, "awaiting": {"output": rel}}), encoding="utf-8")
    assert AF.pending_done(rd) == []
    (tmp_path / rel).write_text("{}", encoding="utf-8")
    (tmp_path / (rel + ".done")).write_text("", encoding="utf-8")
    assert AF.pending_done(rd) == [1]


def test_void_downstream_moves_looks_and_p2(tmp_path):
    """OVERSIGHT-F 11-02：P1 返修出新稿时，造型包 / P2–P4 包和回稿一并移进 void（不删），P1 包不动"""
    AG = _load("autoflow_agent_t5", "tools/script_rsi/autoflow_agent.py")
    rd = tmp_path / "run"
    for sub in ("writer_tasks", "writer_out"):
        (rd / sub).mkdir(parents=True)
    for n in ("P1_a1.json", "P1_looks_a1.json", "P2_ep01_a1.json"):
        (rd / "writer_tasks" / n).write_text("{}", encoding="utf-8")
    (rd / "writer_out" / "P1_looks_a1.json").write_text("[]", encoding="utf-8")
    moved = AG.void_downstream(rd, "测试")
    assert sorted(p.name for p in (rd / "writer_tasks").iterdir()) == ["P1_a1.json"]
    assert len(moved) == 3 and len(list((rd / "writer_tasks_void").glob("P2_ep01_a1.void*.json"))) == 1
    assert (rd / "writer_tasks_void" / "VOID_LOG.jsonl").exists()


def test_review_state_written_by_tool_only(tmp_path):
    AG = _load("autoflow_agent_t6", "tools/script_rsi/autoflow_agent.py")
    rd = tmp_path / "run"
    (rd / "judge_p1").mkdir(parents=True)
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 1, "sha": "x", "dir": str(rd / "judge_p1"), "packed_at": "19:5x"}]}), encoding="utf-8")
    cur = AG.review_add_fixes(rd, ["写清动机"], by="总调度")
    assert cur["extra_fixes"] == ["写清动机"] and cur["extra_by"][0]["by"] == "总调度"


def test_brief_clean_cut_default_true(api, tmp_path):
    r = api.brief("demo2", api.BriefBody(theme="主题"))
    assert r["clean_cut"] is True and (tmp_path / "demo2" / "CLEAN_CUT.json").exists()



def test_p1_approve_refused_until_review_passed(api, tmp_path):
    """V2-WALK W-25：P1 的“用这版”只有三评委过门槛、且评的就是当前故事线时才收，否则 409；“修改”照常收"""
    import hashlib
    from fastapi import HTTPException
    api.brief("demo3", api.BriefBody(theme="主题"))
    d = tmp_path / "demo3"
    (d / "P1_storyline.json").write_text('{"title": "t"}', encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        api.gate("demo3", api.GateBody(key="P1", action="approve"), LOGGED_IN)
    assert e.value.status_code == 409 and "评审" in e.value.detail
    assert api.gate("demo3", api.GateBody(key="P1", action="revise", note="改一下"), LOGGED_IN)["accepted"]
    sha = hashlib.sha256('{"title": "t"}'.encode("utf-8")).hexdigest()[:16]
    (d / "judge_p1").mkdir()
    (d / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 1, "sha": sha, "passed": False, "why": ["均分 27"]}]}), encoding="utf-8")
    with pytest.raises(HTTPException):
        api.gate("demo3", api.GateBody(key="P1", action="approve"), LOGGED_IN)
    (d / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 2, "sha": sha, "passed": True}]}), encoding="utf-8")
    assert api.gate("demo3", api.GateBody(key="P1", action="approve"), LOGGED_IN)["gate"]["status"] == "approved"
    assert OG.p1_approved(d)



def test_single_advance_entry_flow_tick_reports_only(tmp_path):
    """W-23：autopilot 的 autoflow_tick 不再执行推进命令（只报告），全系统推进只走 autoflow.py（网页 /repair、.done 守护）"""
    FL = _load("flow_t", "tools/autopilot/flow.py")
    r = FL.autoflow_tick(tmp_path, apply=True)
    assert r["ran"] == [] and "只报告" in r["note"]


def test_watch_detects_all_judges_done(tmp_path):
    """W-20：三评委的 .done 都在 → watch 的 pending_done 要报这一集（自动 p1_collect + 分流）；少一家不报"""
    AF = _load("autoflow_t3", "tools/script_rsi/autoflow.py")
    rd = tmp_path / "run"
    jd = rd / "judge_p1" / "r2"
    for j in (1, 2, 3):
        (jd / f"judge_{j}" / "out").mkdir(parents=True)
        (jd / f"judge_{j}" / "p1_review_task.json").write_text("{}", encoding="utf-8")
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 2, "dir": str(jd)}]}), encoding="utf-8")
    (rd / "autoflow_ep01.json").write_text(json.dumps({"episode": 1, "verdict": "awaiting_p1_judges", "awaiting": None}), encoding="utf-8")
    for j in (1, 2):
        (jd / f"judge_{j}" / "out" / "p1_review.json.done").write_text("", encoding="utf-8")
    assert AF.pending_done(rd) == []
    (jd / "judge_3" / "out" / "p1_review.json.done").write_text("", encoding="utf-8")
    assert AF.pending_done(rd) == [1]


def test_advance_lock_cross_process(tmp_path):
    """OVERSIGHT-F P1-a：同一集只能一个入口在推进；锁主进程已死 / 陈旧可接管"""
    import os as _os
    AF = _load("autoflow_t4", "tools/script_rsi/autoflow.py")
    rd = tmp_path / "run"
    lk = AF.acquire_advance_lock(rd, 1, "web")
    assert lk is not None and AF.acquire_advance_lock(rd, 1, "daemon") is None
    lk.write_text(json.dumps({"pid": 999999, "source": "web", "at": 0}), encoding="utf-8")      # 死进程 + 陈旧
    assert AF.acquire_advance_lock(rd, 1, "daemon") is not None



def test_two_processes_only_one_advances(tmp_path):
    """OVERSIGHT-F H2 / P1-3b：两个进程同时推进同一集，只有一个拿到锁。用文件信号保证同时起跑：
    两个进程各自写 ready_<i>、等 go 文件出现再抢锁；拿到锁的进程等 release 文件才放锁，保证另一个一定在持锁期间抢"""
    import subprocess
    sig = tmp_path / "sig"
    sig.mkdir()
    code = ("import importlib.util,sys,time;from pathlib import Path;sp=importlib.util.spec_from_file_location('af',r'" + str(ROOT / "tools/script_rsi/autoflow.py") + "');"
            "m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);s=Path(sys.argv[2]);(s/('ready_'+sys.argv[3])).write_text('');"
            "t=time.time()\nwhile not (s/'go').exists() and time.time()-t<60: time.sleep(0.01)\n"
            "lk=m.acquire_advance_lock(Path(sys.argv[1]),1,'t');print('GOT' if lk else 'LOCKED',flush=True);(s/('done_'+sys.argv[3])).write_text('')\n"
            "t=time.time()\nwhile lk and not (s/'release').exists() and time.time()-t<60: time.sleep(0.01)\n"
            "lk and lk.unlink()")
    ps = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path / "run"), str(sig), str(i)], stdout=subprocess.PIPE, text=True) for i in (1, 2)]
    import time as _t
    t0 = _t.time()
    while not ((sig / "ready_1").exists() and (sig / "ready_2").exists()) and _t.time() - t0 < 60:
        _t.sleep(0.01)
    (sig / "go").write_text("", encoding="utf-8")
    while not ((sig / "done_1").exists() and (sig / "done_2").exists()) and _t.time() - t0 < 120:
        _t.sleep(0.01)
    (sig / "release").write_text("", encoding="utf-8")
    outs = sorted(p.communicate(timeout=60)[0].strip() for p in ps)
    assert outs == ["GOT", "LOCKED"]


def test_ep_gate_uses_single_packet_exit():
    """OVERSIGHT-F H4：集返修包也走 packet()，没有第二个出包口"""
    ag = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    assert 'AF.write_json(run_dir / WT / f"revise_ep' not in ag and "output_path=op)" in ag


def test_approve_reason_during_revise(tmp_path):
    """总调度 11-02：返修期间点“用这版”的 409 原因要说“第 N 轮均分 X、在返修第 N+1 稿”，不是“没有故事线”"""
    rd = tmp_path / "run"
    (rd / "judge_p1").mkdir(parents=True)
    (rd / "CLEAN_CUT.json").write_text("{}", encoding="utf-8")
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 2, "passed": False, "revise_issued": True,
                                                                         "result": {"mean": 31.67}}]}), encoding="utf-8")
    ok, why = OG.p1_review_ok(rd)
    assert not ok and "31.67" in why and "返修第 3 稿" in why and "没有 P1 故事线" not in why
    with pytest.raises(PermissionError) as e:
        OG.act(rd, "P1", "approve")
    assert "返修" in str(e.value)



def test_gate_requires_login(api, tmp_path):
    """OVERSIGHT-F 第 3 轮 P1-3a：未登录点闸门回 403，不写任何状态"""
    from fastapi import HTTPException
    api.brief("demo4", api.BriefBody(theme="主题"))
    with pytest.raises(HTTPException) as e:
        api.gate("demo4", api.GateBody(key="P1", action="revise", note="x"), None)
    assert e.value.status_code == 403
    assert OG.summary(tmp_path / "demo4")["gates"] == {}


def test_pending_done_no_spin_when_collect_short(tmp_path):
    """三家 .done 都在但 p1_collect 收不齐（坏稿）：记下这组 .done 的签名，watch 不再每 30 秒空转"""
    AF = _load("autoflow_t5", "tools/script_rsi/autoflow.py")
    AG = _load("autoflow_agent_t7", "tools/script_rsi/autoflow_agent.py")
    rd = tmp_path / "run"
    jd = rd / "judge_p1" / "r3"
    for j in (1, 2, 3):
        (jd / f"judge_{j}" / "out").mkdir(parents=True)
        (jd / f"judge_{j}" / "p1_review_task.json").write_text("{}", encoding="utf-8")
        (jd / f"judge_{j}" / "out" / "p1_review.json").write_text("坏稿", encoding="utf-8")
        (jd / f"judge_{j}" / "out" / "p1_review.json.done").write_text("", encoding="utf-8")
    st = {"rounds": [{"n": 3, "dir": str(jd)}]}
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps(st), encoding="utf-8")
    (rd / "autoflow_ep01.json").write_text(json.dumps({"episode": 1, "verdict": "awaiting_p1_judges", "awaiting": None}), encoding="utf-8")
    assert AF.pending_done(rd) == [1]
    st["rounds"][0]["collected_sig"] = AG.judge_done_sig(jd)
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps(st), encoding="utf-8")
    assert AF.pending_done(rd) == []
    (jd / "judge_2" / "out" / "p1_review.json").write_text("评委重交了一份更长的稿", encoding="utf-8")
    assert AF.pending_done(rd) == [1]
