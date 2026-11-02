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
    (tmp_path / "assets_v2" / "manifest.json").write_text(json.dumps({"characters": {"lead_f": {"looks": {   # OVERSIGHT-F 第 4 轮：只读 manifest.json
        "O1": {"name": "a", "items": {"x": {"file": "f"}}}, "O2": {"name": "b", "items": {"y": {"file": "g"}}}}}}}), encoding="utf-8")
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
    monkeypatch.setattr(SA, "run_status", lambda run_id: {"series10_v1": "archived", "series10_s2": "paused"}.get(run_id))
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
    assert cfg["min_mean"] == 34 and cfg["max_rounds"] == 4          # 总调度 20:0x M-V2-P1-R4：只此一次改成 4
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


def _token(AG, tmp_path):
    """测试用令牌：摘要写进临时 escalate.sha256，AG.ESCALATE_DIGEST 指过去（不碰真实 data/master、config/master）"""
    import hashlib
    tok = tmp_path / "escalate.token"
    tok.write_text("test-token-123", encoding="utf-8")
    dg = tmp_path / "escalate.sha256"
    dg.write_text(hashlib.sha256(b"test-token-123").hexdigest() + "\n", encoding="utf-8")
    AG.ESCALATE_DIGEST = str(dg)
    return str(tok)


def _od_run(api, tmp_path, name):
    import hashlib
    api.brief(name, api.BriefBody(theme="主题"))
    d = tmp_path / name
    (d / "P1_storyline.json").write_text('{"title": "t"}', encoding="utf-8")
    (d / "judge_p1").mkdir()
    sha = hashlib.sha256('{"title": "t"}'.encode("utf-8")).hexdigest()[:16]
    (d / "judge_p1" / "STATE.json").write_text(json.dumps({"rounds": [{"n": 4, "sha": sha, "passed": False,
                                                                       "result": {"mean": 32.0, "totals": [34, 32, 30]}}]}), encoding="utf-8")
    return d


def test_owner_direction_flow(api, tmp_path):
    """总调度 11-02：没 escalate 时 approve 仍 409；只有总调度能 escalate；escalate 后项目方（登录）能 approve 并记“低于门槛、项目方放行”；未登录 403"""
    from fastapi import HTTPException
    AG = _load("autoflow_agent_t8", "tools/script_rsi/autoflow_agent.py")
    d = _od_run(api, tmp_path, "od1")
    with pytest.raises(HTTPException) as e:
        api.gate("od1", api.GateBody(key="P1", action="approve"), LOGGED_IN)
    assert e.value.status_code == 409
    tok = _token(AG, tmp_path)
    AG.live_note = lambda text: None
    with pytest.raises(PermissionError):
        AG.review_escalate_owner(d, by="HOLLYWOOD", token_file=tok)            # 不是总调度
    with pytest.raises(PermissionError):
        AG.review_escalate_owner(d, by="总调度 fredw-2b")                       # 只写 --by 总调度、没令牌：拒绝（P1-4a）
    bad = tmp_path / "bad.token"
    bad.write_text("wrong", encoding="utf-8")
    with pytest.raises(PermissionError):
        AG.review_escalate_owner(d, by="总调度 fredw-2b", token_file=str(bad))  # 令牌不对：拒绝
    od = AG.review_escalate_owner(d, by="总调度 fredw-2b", why="第 4 轮仍 32", token_file=tok)
    assert od["mean"] == 32.0 and OG.owner_direction(d) and len(od["token_digest8"]) == 8 and od["pid"]
    assert api.status("od1")["p1_review"]["owner_direction"]["round"] == 4
    with pytest.raises(HTTPException) as e:
        api.gate("od1", api.GateBody(key="P1", action="approve"), None)
    assert e.value.status_code == 403
    g = api.gate("od1", api.GateBody(key="P1", action="approve"), LOGGED_IN)["gate"]
    assert g["status"] == "approved" and g["below_threshold"] and g["released_by_owner"]
    hist = OG.summary(d)["history"][-1]
    assert hist["audit"] == "低于门槛、项目方放行" and hist["by"] == "owner"


def test_owner_direction_revise_options_and_redirect(api, tmp_path):
    AG = _load("autoflow_agent_t9", "tools/script_rsi/autoflow_agent.py")
    AG.live_note = lambda text: None
    d = _od_run(api, tmp_path, "od2")
    with pytest.raises(Exception):
        OG.act(d, "P1", "redirect", "新方向")              # 没转项目方之前不能换方向
    AG.review_escalate_owner(d, by="总调度", token_file=_token(AG, tmp_path))
    g = api.gate("od2", api.GateBody(key="P1", action="revise", options=["因果不清", "节奏拖"], note="第 9 集再狠一点"), LOGGED_IN)["gate"]
    assert g["status"] == "revise_requested" and g["note"].startswith("因果不清；节奏拖。第 9 集再狠一点")
    g2 = api.gate("od2", api.GateBody(key="P1", action="redirect", note="改成悬疑方向"), LOGGED_IN)["gate"]
    assert g2["status"] == "redirect_requested"



def test_owner_revise_new_draft_reviewed_reference_only(tmp_path, monkeypatch):
    """OVERSIGHT-F P1-4b：项目方接手后改稿，新稿照样出评审包、三评委评分（只作参考、不拦）；
    没到 34 → 自动停在 owner_direction（新稿 sha，带评分，不用再 escalate、不出返修包）；过了 34 → 走正常闸门"""
    import hashlib
    AG = _load("autoflow_agent_t10", "tools/script_rsi/autoflow_agent.py")
    monkeypatch.setattr(AG, "live_note", lambda text: None)
    rd = tmp_path / "run"
    (rd / "writer_tasks").mkdir(parents=True)
    (rd / "writer_out").mkdir()
    (rd / "judge_p1").mkdir()
    (rd / "CLEAN_CUT.json").write_text("{}", encoding="utf-8")
    canon = rd / "P1_storyline.json"
    canon.write_text('{"title": "new"}', encoding="utf-8")
    old_sha = "0000000000000000"
    (rd / "judge_p1" / "STATE.json").write_text(json.dumps({
        "rounds": [{"n": 4, "sha": old_sha, "dir": str(rd / "judge_p1"), "passed": False, "result": {"mean": 32}}],
        "owner_direction": {"sha": old_sha, "round": 4, "mean": 32}, "owner_took_over": {"at": "x"}}), encoding="utf-8")

    class St:
        def __init__(self):
            self.d = {"stages": []}

        def set(self, **k):
            self.d.update(k)

        def stage(self, sid, name, status, decider, **k):
            self.d["stages"].append({"id": sid, "status": status})

        def save(self):
            pass
    JA = _load("judge_agent_t2", "tools/script_rsi/judge_agent.py")
    monkeypatch.setattr(AG, "_load", lambda name, rel: JA if name == "judge_agent" else _load(name + "_y", rel))
    monkeypatch.setattr(JA, "p1_pack", lambda run_dir, judges, out=None: [])
    # 第 5 轮（超过 max_rounds=4）：项目方已接手 → 照样出包，不 escalate
    monkeypatch.setattr(JA, "p1_collect", lambda run_dir, out=None: {"n": 0})
    st = St()
    assert AG._p1_review(None, rd, 1, st, {}, canon, {}) is False and st.d.get("verdict") == "awaiting_p1_judges"
    # 评完没到 34 → 自动 owner_direction（新稿 sha）
    monkeypatch.setattr(JA, "p1_collect", lambda run_dir, out=None: {"n": 3, "totals": [33, 32, 31], "mean": 32.0, "sigma": 0.8, "stable": True,
                                                                     "single_judge": False, "item_mean": {"men": 3.5}, "top_fixes": []})
    st = St()
    assert AG._p1_review(None, rd, 1, st, {}, canon, {}) is False and st.d["verdict"] == "owner_direction"
    od = json.loads((rd / "judge_p1" / "STATE.json").read_text(encoding="utf-8"))["owner_direction"]
    assert od["sha"] == hashlib.sha256('{"title": "new"}'.encode("utf-8")).hexdigest()[:16] and od["mean"] == 32.0 and od["auto_after_owner_revise"]
    assert not list((rd / "writer_tasks").glob("P1_a*.json"))         # 不出返修包
    assert OG.p1_review_ok(rd)[0]                                     # 项目方可以直接“用这版”



def test_closed_runs_refused(api, tmp_path):
    """W-37：已归档 / 冻结 / 暂停的剧，/brief 和 /start 都回 409；clean_cut=false 续写时源剧不能是已归档的剧（选 series10_v1 续写被拒）"""
    from fastapi import HTTPException
    for rid in ("series10_v1", "series10_s2"):
        with pytest.raises(HTTPException) as e:
            api.brief(rid, api.BriefBody(theme="主题"))
        assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        api.brief("new_run", api.BriefBody(theme="续写", clean_cut=False, source_run="series10_v1"))
    assert e.value.status_code == 409 and "series10_v1" in e.value.detail
    with pytest.raises(HTTPException) as e:
        api.brief("new_run2", api.BriefBody(brief={"schema": "nsfs.brief/1", "outline": "x", "episodes": {"from": 1, "to": 1},
                                                   "registry_from": ["series10_v1"]}, clean_cut=False))
    assert e.value.status_code == 409
    assert api.brief("new_run3", api.BriefBody(theme="全新的剧"))["ok"]


def test_spawn_refuses_closed_run():
    import importlib.util
    src = (ROOT / "services/api/ns_api/script_autoflow.py").read_text(encoding="utf-8")
    assert '_refuse_closed(run_id, "开写或推进")' in src          # /start /repair /import /gate 都经 _spawn



def test_escalate_missing_token_file_is_permission_error(tmp_path):
    AG = _load("autoflow_agent_t12", "tools/script_rsi/autoflow_agent.py")
    _token(AG, tmp_path)
    with pytest.raises(PermissionError) as e:
        AG._check_escalate_token(str(tmp_path / "nope.token"))
    assert "不存在" in str(e.value)


def test_escalate_advances_immediately(api, tmp_path):
    """W-38：escalate 之后 /tasks 的 verdict 立刻就是 owner_direction（同一把推进锁里推进一次，source=escalate；escalate 自己不写 verdict）"""
    AG = _load("autoflow_agent_t13", "tools/script_rsi/autoflow_agent.py")
    AF = _load("autoflow_t13", "tools/script_rsi/autoflow.py")
    AG.live_note = lambda text: None
    d = _od_run(api, tmp_path, "od5")
    tok = _token(AG, tmp_path)
    seen = {}

    def fake_run(run_dir, ep, import_mode):           # 真实 _p1_review 的 owner_direction 分支写状态（不跑整条链）
        seen["locked"] = (run_dir / f"work_ep{ep:02d}" / "advance.lock").exists()
        st = AF.Status(run_dir, ep, 0.0)
        AG._p1_review(None, run_dir, ep, st, {}, run_dir / "P1_storyline.json", {})
        return st.d
    AG.run = fake_run
    r = AF.escalate_and_advance(d, "总调度", "第 4 轮 32", tok, AG=AG)
    assert r["verdict"] == "owner_direction" and seen["locked"]
    assert api.tasks("od5")["episodes"]["autoflow_ep01"]["verdict"] == "owner_direction"
    assert not (d / "work_ep01" / "advance.lock").exists()
    log = [json.loads(x) for x in (d / "autoflow.log").read_text(encoding="utf-8").splitlines()]
    assert [x["source"] for x in log] == ["escalate", "escalate"] and log[-1]["verdict"] == "owner_direction"


def test_escalate_waits_for_lock_and_writes_nothing_if_busy(api, tmp_path):
    import os
    AG = _load("autoflow_agent_t14", "tools/script_rsi/autoflow_agent.py")
    AF = _load("autoflow_t14", "tools/script_rsi/autoflow.py")
    AG.live_note = lambda text: None
    d = _od_run(api, tmp_path, "od6")
    tok = _token(AG, tmp_path)
    lk = d / "work_ep01" / "advance.lock"
    lk.parent.mkdir(parents=True, exist_ok=True)
    lk.write_text(json.dumps({"pid": os.getpid(), "source": "daemon", "at": __import__("time").time()}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        AF.escalate_and_advance(d, "总调度", "", tok, AG=AG, wait_s=0.6)
    assert not OG.owner_direction(d)                  # 没拿到锁：什么都没写


def test_new_rule_does_not_auto_repair_p1_in_owner_hands(api, tmp_path):
    """SL-12 上线时 V2 P1 正在项目方手里（owner_direction）：新规则只挂在状态里给项目方看，不自动出返修包；
    没转项目方时照旧返修；混有别的阻断项也照旧返修"""
    from types import SimpleNamespace as NS
    AG = _load("autoflow_agent_t15", "tools/script_rsi/autoflow_agent.py")
    AF = _load("autoflow_t15", "tools/script_rsi/autoflow.py")
    AG.live_note = lambda text: None
    d = _od_run(api, tmp_path, "od7")
    issues = [NS(rule="SL-12", level="block", field="episodes[2].logline", message="占位词「未提供」")]
    RCH = NS(validate=lambda link, txt, ctx: (NS(issues=issues), {"title": "t"}, ""))
    st = AF.Status(d, 1, 0.0)
    canon = d / "P1_storyline.json"
    assert AG._p1_owner_hold(RCH, d, canon, {}, st) is None              # 还没转项目方：照旧返修
    AG.review_escalate_owner(d, by="总调度", token_file=_token(AG, tmp_path))
    assert AG._p1_owner_hold(RCH, d, canon, {}, st) == {"title": "t"}
    assert "SL-12" in st.d["p1_owner_hold"][0]
    issues.append(NS(rule="SL-02", level="block", field="characters", message="未成年"))
    assert AG._p1_owner_hold(RCH, d, canon, {}, st) is None              # 有别的阻断项：照旧返修



def test_owner_direction_text_plain(api, tmp_path):
    """W-39：给项目方看的文字不带内部编号；两选（用这版 / 修改，换方向在修改里）"""
    import re
    AG = _load("autoflow_agent_t16", "tools/script_rsi/autoflow_agent.py")
    AF = _load("autoflow_t16", "tools/script_rsi/autoflow.py")
    AG.live_note = lambda text: None
    d = _od_run(api, tmp_path, "od8")
    sp = d / "judge_p1" / "STATE.json"
    stt = json.loads(sp.read_text(encoding="utf-8"))
    stt["rounds"] = [{"n": i + 1, "sha": "x", "result": {"mean": m}} for i, m in enumerate((27.33, 31.67, 32))] + stt["rounds"]
    sp.write_text(json.dumps(stt), encoding="utf-8")
    AG.review_escalate_owner(d, by="总调度 fredw-2b（M-V2-P1-R4）", why="按 M-V2-P1-R4 交项目方", token_file=_token(AG, tmp_path))
    assert OG.owner_direction_text(d) == "四轮评审都在 32 分左右，没到 34"
    st = AF.Status(d, 1, 0.0)
    AG._p1_review(None, d, 1, st, {}, d / "P1_storyline.json", {})
    na = st.d["next_action"]
    assert na == "四轮评审都在 32 分左右，没到 34，总调度转给你定方向：用这版 / 修改（修改里可以选换个方向重写）"
    shown = json.dumps({"na": na, "stages": st.d.get("stages"), "od": api.status("od8")["p1_review"]["owner_direction"]}, ensure_ascii=False)
    assert not re.search(r"[A-Z]-[A-Z0-9]+-|fredw", shown) and "换方向 /" not in shown


def _fill_run(api, tmp_path, name):
    """可过 check_storyline 的小故事线，第 1 集 logline 留了占位词；已评 4 轮、低于门槛"""
    import hashlib
    sys.path.insert(0, str(ROOT / "packages" / "schema"))
    from ns_schema import storyline as SL
    d = _od_run(api, tmp_path, name)
    s = {"schema": "nsfs.storyline/1", "title": "T", "premise": "p", "world": {"setting": "s"},
         "characters": [{"name": "甲", "char_id": "ch_a", "role": "主角", "age": 24, "gender": "女", "zh_look": "系统锁",
                         "en_phrase": "a 24-year-old East Asian woman with long black hair", "voice_phrase": "a bright young female voice, brisk pace"}],
         "scenes": [{"scene_id": "sk_room", "name": "房间", "space": "小房间", "time_of_day": "夜", "light": "台灯暖光", "fixtures": "桌子、椅子"}],
         "episodes": [{"episode": 1, "title": "一", "owner_line": "原话", "logline": "原话展开（未提供）", "characters": ["甲"], "scenes": ["sk_room"]}]}
    txt = json.dumps(s, ensure_ascii=False, indent=1)
    (d / "P1_storyline.json").write_text(txt, encoding="utf-8")
    (d / "P1_looks.json").write_text("[]", encoding="utf-8")
    sp = d / "judge_p1" / "STATE.json"
    stt = json.loads(sp.read_text(encoding="utf-8"))
    stt["rounds"][-1]["sha"] = hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]
    sp.write_text(json.dumps(stt), encoding="utf-8")
    ctx = {"brief": SL.Brief.model_validate({"outline": "x", "episodes": {"from": 1, "to": 1}}), "episode": 1,
           "registry_chars": [], "registry_scenes": []}
    return d, s, ctx


def test_approve_triggers_placeholder_fill(api, tmp_path):
    """总调度 11-02：项目方点“用这版”且只剩 SL-12 → 自动出补占位包（只许改含占位词的字段，不进三评委）；
    改了别的字段 → 拒收、重出包；只改那个字段且 check_storyline 过 → 写回正式稿、转交记录跟着新 sha、P1 仍算通过"""
    AG = _load("autoflow_agent_t17", "tools/script_rsi/autoflow_agent.py")
    AF = _load("autoflow_t17", "tools/script_rsi/autoflow.py")
    AG.live_note = lambda text: None
    RCH = AG._load("run_chain", "tools/pipeline/run_chain.py")
    d, s, ctx = _fill_run(api, tmp_path, "fill1")
    canon = d / "P1_storyline.json"
    AG.review_escalate_owner(d, by="总调度", token_file=_token(AG, tmp_path))
    st = AF.Status(d, 1, 0.0)
    obj = AG._p1_owner_hold(RCH, d, canon, ctx, st)
    assert obj is not None and st.d["p1_owner_hold_fields"] == ["episodes[0].logline"]
    ctx["storyline"] = obj
    assert not AG.p1_gate(RCH, d, 1, st, ctx, canon)                    # 还没点“用这版”：等项目方
    assert "第 1 集一句简介还没写完，写手会自动补上，不影响你选的这版" in st.d["next_action"]
    assert not (d / "writer_tasks" / "P1_fill_a1.json").exists()
    api.gate("fill1", api.GateBody(key="P1", action="approve"), LOGGED_IN)
    assert not AG.p1_gate(RCH, d, 1, st, ctx, canon)
    pk = json.loads((d / "writer_tasks" / "P1_fill_a1.json").read_text(encoding="utf-8"))
    assert pk["fields"] == ["episodes[0].logline"] and "原话展开（未提供）" in pk["user"]
    assert not list((d / "judge_p1").glob("r5"))                         # 不进三评委
    # 改了别的字段 → 拒收
    out = d / "writer_out" / "P1_fill_a1.json"
    out.parent.mkdir(exist_ok=True)
    bad = json.loads(json.dumps(s))
    bad["episodes"][0]["logline"] = "原话展开，她把鞋留在门口"
    bad["title"] = "新剧名"
    out.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    out.with_name(out.name + ".done").write_text("", encoding="utf-8")
    assert not AG.p1_gate(RCH, d, 1, st, ctx, canon)
    pk2 = json.loads((d / "writer_tasks" / "P1_fill_a2.json").read_text(encoding="utf-8"))
    assert "改了不许改的字段：title" in pk2["user"] and json.loads(canon.read_text(encoding="utf-8"))["title"] == "T"
    # 只补那个字段 → 收下
    out2 = d / "writer_out" / "P1_fill_a2.json"
    out2.write_text(json.dumps({"fields": {"episodes[0].logline": "原话展开，她把鞋留在门口"}}, ensure_ascii=False), encoding="utf-8")
    out2.with_name(out2.name + ".done").write_text("", encoding="utf-8")
    assert AG.p1_gate(RCH, d, 1, st, ctx, canon)
    new = json.loads(canon.read_text(encoding="utf-8"))
    assert new["episodes"][0]["logline"] == "原话展开，她把鞋留在门口" and new["title"] == "T"
    assert AG.diff_paths(s, new) == ["episodes[0].logline"]
    assert OG.owner_direction(d) and OG.p1_approved(d)                   # 转交记录 / 评审跟着新 sha，P1 仍算通过，不重评
    stt = json.loads((d / "judge_p1" / "STATE.json").read_text(encoding="utf-8"))
    assert stt["placeholder_fills"][-1]["fields"] == ["episodes[0].logline"]
    assert list(d.glob("P1_storyline.prefill*.json"))                   # 旧稿留档


def test_fill_check_rejects_still_placeholder_and_unknown_field(api, tmp_path):
    AG = _load("autoflow_agent_t18", "tools/script_rsi/autoflow_agent.py")
    RCH = AG._load("run_chain", "tools/pipeline/run_chain.py")
    d, s, ctx = _fill_run(api, tmp_path, "fill2")
    f = ["episodes[0].logline"]
    assert AG.fill_check(RCH, s, json.dumps({"fields": {"episodes[0].logline": "她 TODO"}}), f, ctx)[0] is None
    assert AG.fill_check(RCH, s, json.dumps({"fields": {"episodes[0].nope": "x"}}), f, ctx)[1] == ["字段 episodes[0].nope 不存在"]
    assert "episodes[0].logline 没补" in AG.fill_check(RCH, s, json.dumps({"fields": {}}), f, ctx)[1]


def test_writer_packets_carry_placeholder_override(tmp_path):
    """OVERSIGHT-F P1-8a：任何新出的写作包，只要提到“标未提供”，就必须带 SL-12 覆盖说明（P1 包 dry 出一份核对；packet 单一出口兜底）"""
    AG = _load("autoflow_agent_t19", "tools/script_rsi/autoflow_agent.py")
    AF = AG.AF
    sys.path.insert(0, str(ROOT / "packages" / "schema"))
    from ns_schema import storyline as SL
    RCH = AG._load("run_chain", "tools/pipeline/run_chain.py")
    AF.patch_chain(RCH)
    rd = tmp_path / "dry_run"
    rd.mkdir()
    st = AF.Status(rd, 1, 0.0)
    ctx = {"brief": SL.Brief.model_validate({"outline": "上海时尚模特的幻想和现实", "episodes": {"from": 1, "to": 10}}), "episode": 1,
           "registry_chars": [], "registry_scenes": []}
    pr = RCH.WP.build("P0-P1", ctx)
    pk = AG.packet(rd, st, "P1", "writer", 1, "P0-P1", pr["system"], pr["user"], "json", [], 1)
    for k in ("system", "content_rules"):
        assert AF.OVERRIDE_TAG in pk[k] or "正文不留占位词" in pk[k]
    assert pk["system"].count(AF.OVERRIDE_TAG) >= 1 and "缺信息就按 P0 / P1 已有设定写成具体内容" in pk["system"]
    assert AF.OVERRIDE_TAG in AF.HARD_RULES and AF.OVERRIDE_TAG in AG.CONTENT_RULES and AF.OVERRIDE_TAG in AG.CONTENT_RULES_CLEAN
    pk2 = AG.packet(rd, st, "P1_x", "writer", 1, "P0-P1", "缺信息标“未提供”", "u", "json", [], 1)    # 兜底：任何提到“标未提供”的包
    assert AF.OVERRIDE_TAG in pk2["system"]
    for f in (rd / "writer_tasks").glob("*.json"):
        t = f.read_text(encoding="utf-8")
        assert not (("标“未提供”" in t or "标未提供" in t) and AF.OVERRIDE_TAG not in t), f.name


def test_fill_value_must_be_substantial(api, tmp_path):
    """OVERSIGHT-F P2：补占位的值要非空、去空白后 ≥ 6 字、不能只是“无”“。”"""
    AG = _load("autoflow_agent_t20", "tools/script_rsi/autoflow_agent.py")
    RCH = AG._load("run_chain", "tools/pipeline/run_chain.py")
    d, s, ctx = _fill_run(api, tmp_path, "fill3")
    f = ["episodes[0].logline"]
    for v in ("无", "。", "  ", "同上同上", "无。。。。。。", "a b c"):
        new, probs = AG.fill_check(RCH, s, json.dumps({"fields": {"episodes[0].logline": v}}, ensure_ascii=False), f, ctx)
        assert new is None and any("太短或是空话" in p or "没补" in p for p in probs), v
    new, probs = AG.fill_check(RCH, s, json.dumps({"fields": {"episodes[0].logline": "她把鞋留在门口"}}, ensure_ascii=False), f, ctx)
    assert new is not None and probs == []
