"""BRAIN-FW：tools/brain/actions.py 白名单执行器——schema、护栏（gpu33:2 / 删除 / 成人 / 到期）、速率、幂等、dry-run、审计日志、
lane_roles 阶段覆盖读方（全 fake，不碰网络 / 服务器）。"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


A = _load("brain_actions_t", "tools/brain/actions.py")
NOW = 1_800_000_000.0


class FakeEnv(A.Env):
    def __init__(self, root, now=NOW, adult=("ep03-S5",)):
        super().__init__(root)
        self._now, self._adult = now, set(adult)
        self.remote_calls, self.local_calls, self.rq, self.requeued, self.issues, self.live = [], [], [], [], [], []
        self.pending = []

    def now(self):
        return self._now

    def primary_run(self):
        return "run_t"

    def server_root(self, host):
        return "/srv/repo"

    def producer_cmd(self, host, run, args):
        return f"PRODUCER {host} {run} " + " ".join(args)

    def night_once_cmd(self, host, run):
        return f"NIGHT_ONCE {host} {run}"

    def remote(self, host, cmd, timeout, input=None):
        self.remote_calls.append((host, cmd, timeout, (input or b"").decode("utf-8")))
        return 0, "ok"

    def local_python(self, args, timeout):
        self.local_calls.append(args)
        return 0, "tick ok"

    def rq_pending(self, host):
        return self.pending

    def rq_request(self, host, reason, mode, urgent):
        self.rq.append((host, mode, urgent))
        return {"id": "rq1"}

    def asset_requeue(self, run, jid, why):
        self.requeued.append(jid)
        return {"id": jid, "state": "pending"}

    def report(self, run, episode, step, what, fix_hint, blocking):
        self.issues.append((episode, step, what, blocking))
        return "ISS-x"

    def insert_live(self, line):
        self.live.append(line)

    def adult_ids(self, run):
        return self._adult


def act(kind, **kw):
    return {"kind": kind, "reason": "快照证据", "expected_effect": "下轮变化", "check_after_s": 300, **kw}


def decisions(root):
    return [json.loads(x) for x in (root / "data/brain/decisions.jsonl").read_text(encoding="utf-8").splitlines()]


def test_catalog_schemas_are_strict_ready():
    for k, v in A.CATALOG.items():
        s = v["schema"]
        assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"]), k
        assert {"reason", "expected_effect", "check_after_s"} <= set(s["properties"])
    tools = A.tool_defs()
    assert all(t["strict"] is True and t["input_schema"]["additionalProperties"] is False for t in tools)
    assert {t["name"] for t in tools} == set(A.CATALOG)
    assert "gpu33:2" not in json.dumps(tools)


def test_guardrail_never_gpu33_2(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("set_night_control", host="gpu33", yield_s=None, video_lanes=["gpu33:2"], hold_lanes=None, expires_min=30)], env, dry=False)
    assert r[0]["rejected"] and ("gpu33:2" in r[0]["rejected"] or "schema" in r[0]["rejected"])
    r = A.run([act("producer_retry", host="gpu33", obj="first:ep02-S3 gpu33:2")], env, dry=False)
    assert "禁区" in r[0]["rejected"]
    assert env.remote_calls == []


def test_guardrail_never_delete_and_unknown_kind(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("producer_retry", host="gpu33", obj="rm -rf first:ep02-S3"), {"kind": "delete_takes", "reason": "x"},
               act("note_to_owner", text="please delete old versions", level="green")], env, dry=False)
    assert "删除" in r[0]["rejected"] and "未登记" in r[1]["rejected"]
    assert not r[2]["rejected"], r[2]          # 给人看的文案（text / what / reason）里的字不算命令参数
    assert env.remote_calls == []


def test_guardrail_never_adult(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("producer_retry", host="gpu36", obj="first:ep03-S5"),
               act("producer_regen", host="gpu36", episode=3, shots=["S5", "S6"]),
               act("producer_reset_best_effort", host="gpu36", shots=["ep03-S6"])], env, dry=False)
    assert "成人" in r[0]["rejected"] and "成人" in r[1]["rejected"] and not r[2]["rejected"]
    assert len(env.remote_calls) == 1 and "reset-best-effort" in env.remote_calls[0][1]


def test_schema_validation_rejects_bad_params(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("producer_retry", host="gpu99", obj="first:ep02-S3"), act("producer_retry", host="gpu33"),
               act("producer_uncap", host="gpu33", obj="first:ep02-S3", n=9), act("restart_queue_request", host="gpu33", mode="reboot", urgent=True),
               {"kind": "no_action", "reason": "x"}], env, dry=False)
    assert all(x["rejected"] and x["rejected"].startswith("schema") for x in r), [x["rejected"] for x in r]


def test_dry_run_executes_nothing_but_logs(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("producer_retry", host="gpu33", obj="first:ep02-S3"), act("night_once", host="gpu36")], env, dry=True, snapshot_hash="abc123")
    assert [x["result"] for x in r] == ["dry-run（没动手）"] * 2 and env.remote_calls == []
    d = decisions(tmp_path)
    assert len(d) == 2 and d[0]["snapshot_hash"] == "abc123" and d[0]["dry"] is True and d[0]["params"]["reason"] == "快照证据"
    assert not (tmp_path / "data/brain/state.json").exists()        # dry 不计速率 / 幂等
    r2 = A.run([act("producer_retry", host="gpu33", obj="first:ep02-S3")], env, dry=False)
    assert not r2[0]["rejected"]


def test_real_run_calls_producer_cli_and_logs(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("producer_retry", host="gpu33", obj="first:ep02-S3"), act("producer_review_adopt", host="gpu36", obj="last:ep02-S4", n=None),
               act("producer_uncap", host="gpu33", obj="first:ep02-S7", n=2)], env, dry=False, snapshot_hash="h1")
    assert all(not x["rejected"] for x in r)
    cmds = [c[1] for c in env.remote_calls]
    assert cmds[0].startswith("PRODUCER gpu33 run_t retry --obj first:ep02-S3 --by BRAIN")
    assert "review-adopt --obj last:ep02-S4 --by BRAIN" in cmds[1] and "--n" not in cmds[1]
    assert "uncap --obj first:ep02-S7 --n 2" in cmds[2]
    st = json.loads((tmp_path / "data/brain/state.json").read_text(encoding="utf-8"))
    assert len(st["rate"]["producer_retry"]) == 1 and st["idem"]


def test_idempotency_and_rate_limit(tmp_path, monkeypatch):
    env = FakeEnv(tmp_path)
    a = act("producer_retry", host="gpu33", obj="first:ep02-S3")
    r = A.run([a, dict(a)], env, dry=False)
    assert not r[0]["rejected"] and "幂等" in r[1]["rejected"]
    env._now = NOW + 700                                               # 幂等窗口过了可以再提
    r = A.run([a], env, dry=False)
    assert not r[0]["rejected"]
    monkeypatch.setitem(A.CATALOG["producer_retry"], "rate", (2, 3600))
    env._now = NOW + 1400
    r = A.run([act("producer_retry", host="gpu33", obj="first:ep02-S8")], env, dry=False)
    assert "速率上限" in r[0]["rejected"]
    env._now = NOW + 4000                                               # 窗口滑过
    r = A.run([act("producer_retry", host="gpu33", obj="first:ep02-S9")], env, dry=False)
    assert not r[0]["rejected"]


def test_restart_request_gap_and_pending(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("restart_queue_request", host="gpu36", mode="night-only", urgent=True)], env, dry=False)
    assert r[0]["result"] == "request rq1" and env.rq == [("gpu36", "night-only", True)]
    env._now = NOW + 900
    r = A.run([act("restart_queue_request", host="gpu36", mode="all", urgent=False)], env, dry=False)
    assert "30 分钟内" in r[0]["rejected"]
    env._now = NOW + 1900
    env.pending = [{"id": "p"}]
    r = A.run([act("restart_queue_request", host="gpu36", mode="all", urgent=False)], env, dry=False)
    assert r[0]["result"].startswith("已有待办") and len(env.rq) == 1


def test_night_control_requires_expiry_and_writes_remote(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("set_night_control", host="gpu33", yield_s=None, video_lanes=None, hold_lanes=["gpu33:0"], expires_min=0),
               act("set_night_control", host="gpu33", yield_s=60, video_lanes=["gpu33:3"], hold_lanes=None, expires_min=30)], env, dry=False)
    assert r[0]["rejected"] and not r[1]["rejected"]
    host, cmd, _, code = env.remote_calls[-1]
    assert host == "gpu33" and "python3 -" in cmd and '"yield_s": 60' in code and "gpu33:3" in code and chr(92) not in code
    compile(code, "night_ctrl", "exec")


def test_clear_rejects_and_asset_requeue_and_reports(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("clear_stale_master_rejects", host="gpu36", older_than_h=6), act("asset_jobs_requeue", job_ids=["j1", "j2"], tick=True),
               act("report_issue", episode=2, step="视频", what="gpu36:2 空 12 min", fix_hint="night_once", blocking=False),
               act("note_to_owner", text="ep02 首尾帧全定", level="green"), act("no_action")], env, dry=False)
    assert all(not x["rejected"] for x in r), [x["rejected"] for x in r]
    code = env.remote_calls[0][3]
    assert "master_rejects.json" in code and "shutil.copyfile" in code and chr(92) not in code
    compile(code, "clear_rejects", "exec")
    assert env.requeued == ["j1", "j2"] and env.local_calls == [["tools/pipeline/asset_worker.py", "tick"]]
    assert env.issues == [(2, "视频", "gpu36:2 空 12 min", False)]
    assert "🟢 BRAIN：ep02 首尾帧全定" in env.live[0]
    assert "ep02 首尾帧全定" in (tmp_path / "data/brain/owner_notes.md").read_text(encoding="utf-8")
    assert r[4]["result"] == "ok"


def test_lane_roles_override_written_and_honored(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("lane_roles_phase_override", episode=2, phase="videos", expires_min=20)], env, dry=False)
    assert not r[0]["rejected"] and r[0]["result"].startswith("override local")
    p = tmp_path / "data/pipeline/lane_roles_override.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["run_t"]["2"]["phase"] == "videos" and d["run_t"]["2"]["by"] == "BRAIN"
    assert len([c for c in env.remote_calls if "lane_roles_override" in c[3]]) == 2
    LRO = _load("lane_roles_producer_for_brain_t", "tools/autopilot/lane_roles_producer.py")
    assert LRO.read_override("run_t", tmp_path, NOW) == {2: "videos"}
    assert LRO.read_override("run_t", tmp_path, NOW + 21 * 60) == {}                      # 到期失效
    assert LRO.apply_override({2: "frames", 3: "frames"}, "run_t", NOW, tmp_path) == {2: "videos", 3: "frames"}
    assert LRO.apply_override({3: "frames"}, "run_t", NOW, tmp_path) == {3: "frames"}        # 只覆盖已有的集
    r = A.run([act("lane_roles_phase_override", episode=2, phase="videos", expires_min=999)], env, dry=False)
    assert r[0]["rejected"]


def test_max_actions_per_cycle(tmp_path):
    env = FakeEnv(tmp_path)
    r = A.run([act("no_action")] * 3, env, dry=True, max_actions=2)
    assert not r[0]["rejected"] and not r[1]["rejected"] and "上限" in r[2]["rejected"]
