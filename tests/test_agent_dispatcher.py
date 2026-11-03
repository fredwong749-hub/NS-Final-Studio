"""EPCHAIN-O 11-03：派单器（tools/factory/agent_dispatcher.py）。假 claude 可执行文件做夹具（python 脚本），覆盖：
白名单参数、超时杀进程 + 作废 + 重排、累计 3 次登记卡点、模型分工（写 / 评不同模型）、并发上限、.claimed 跳过、
.done 第 2 行写实际模型 id、计量 by=agent:<模型>(dispatcher)、开关默认关。"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
log = os.environ["FAKE_ARGS_LOG"]
with open(log, "a", encoding="utf-8") as f:   # 假 claude 按 UTF-8 读 stdin（与真 claude 一致；不随系统代码页 cp1252）
    f.write(json.dumps({"args": args, "stdin": sys.stdin.buffer.read().decode("utf-8")[:200], "cwd": os.getcwd()}) + "\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "hang":
    time.sleep(120)
if mode == "fail":
    sys.exit(1)
i = args.index("--allowedTools")
writes = [a[5:-1] for a in args[i + 1:] if a.startswith("Edit(")]
out, done = writes
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w", encoding="utf-8").write('{"ok": true}')
open(done, "w", encoding="utf-8").write("agent_dispatcher\nmodel: fable\n")
print(json.dumps({"type": "result", "result": "已交稿", "modelUsage": {"claude-fable-5-1": {"outputTokens": 1200}}}))
'''


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def env(tmp_path, monkeypatch):
    AD = _load("agent_dispatcher_t", "tools/factory/agent_dispatcher.py")
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE, encoding="utf-8")
    inbox = tmp_path / "inbox"
    monkeypatch.setenv("NSFS_INBOX_DIR", str(inbox))
    monkeypatch.setenv("FAKE_ARGS_LOG", str(tmp_path / "fake_args.jsonl"))
    rd = tmp_path / "data/pipeline/runs/rx"
    (rd / "writer_tasks").mkdir(parents=True)
    cfg = {**AD.DEFAULTS, "enabled": True, "claude_cmd": [sys.executable, str(fake)], "timeout_s": 60, "max_concurrent": 2}
    issues = []

    def add(step, kind, model, ep=2, at="2026-11-03T03:00:00"):
        pk = rd / "writer_tasks" / f"{step}_a1.json"
        pk.write_text(json.dumps({"status": "open", "step": step}), encoding="utf-8")
        rel = lambda p: p.relative_to(tmp_path).as_posix()  # noqa: E731
        req = {"schema": "nsfs.dispatch_request/1", "at": at, "run": "rx", "id": f"{step}_a1", "kind": kind, "episode": ep, "step": step,
               "attempt": 1, "packet": rel(pk), "output": rel(rd / "writer_out" / f"{step}_a1.json"),
               "done_marker": rel(rd / "writer_out" / f"{step}_a1.json.done"), "suggested_model": model,
               "must_differ_from": "fable" if kind == "reviewer" else None}
        (inbox / "requests").mkdir(parents=True, exist_ok=True)
        (inbox / "requests" / f"rx__{step}_a1.json").write_text(json.dumps(req), encoding="utf-8")
        return req

    def tick(**kw):
        return AD.tick(root=tmp_path, cfg=kw.pop("cfg", cfg), report=lambda *a, **k: issues.append(a), **kw)

    def wait_all(timeout=60):
        t0 = time.time()
        st = json.loads((tmp_path / AD.STATE_DIR / "state.json").read_text(encoding="utf-8"))
        for r in st["requests"].values():
            if r.get("running"):
                while AD.alive(r["running"]["pid"], r["running"]["sig"]) and time.time() - t0 < timeout:
                    time.sleep(0.2)
    return {"AD": AD, "root": tmp_path, "rd": rd, "inbox": inbox, "cfg": cfg, "add": add, "tick": tick, "wait": wait_all, "issues": issues,
            "args": lambda: [json.loads(x) for x in (tmp_path / "fake_args.jsonl").read_text(encoding="utf-8").splitlines()]}


def test_default_off():
    AD = _load("agent_dispatcher_t0", "tools/factory/agent_dispatcher.py")
    assert AD.DEFAULTS["enabled"] is False                                   # 配置读不到 = 关（L-138 后真实配置已开）
    assert AD.tick(cfg={**AD.DEFAULTS, "enabled": False}) == {"enabled": False}


def test_whitelist_args_and_done_model_and_metrics(env):
    env["add"]("P3_ep02", "writer", "fable")
    r = env["tick"]()
    assert r["started"] == ["rx__P3_ep02_a1:fable"]
    env["wait"]()
    r = env["tick"]()
    assert r["finished"] == ["rx__P3_ep02_a1:done"]
    a = env["args"]()[0]
    args = a["args"]
    assert Path(a["cwd"]).resolve() == env["root"].resolve()
    assert "-p" in args and args[args.index("--model") + 1] == "fable"
    assert args[args.index("--tools") + 1] == "Read,Write" and "--restricted" in args and "--strict-mcp-config" in args
    assert args[args.index("--permission-mode") + 1] == "dontAsk" and args[args.index("--permission-prompts") + 1] == "none"
    i, j = args.index("--allowedTools"), args.index("--disallowedTools")
    assert args[i + 1:j] == ["Read", "Edit(data/pipeline/runs/rx/writer_out/P3_ep02_a1.json)",
                             "Edit(data/pipeline/runs/rx/writer_out/P3_ep02_a1.json.done)"]
    deny = args[j + 1:args.index("--permission-mode")]
    assert {"Bash", "PowerShell", "WebFetch", "WebSearch", "Read(data/master/**)"} <= set(deny) and "Edit" not in deny
    assert "Bash" not in args[i + 1:j] and "P3_ep02" in a["stdin"]          # 提示词走 stdin，由请求生成
    done = (env["rd"] / "writer_out" / "P3_ep02_a1.json.done").read_text(encoding="utf-8").splitlines()
    assert done == ["agent_dispatcher", "model: claude-fable-5-1"]           # 第 2 行 = 实际模型 id（取自 claude -p 的 modelUsage）
    m = [json.loads(x) for x in (env["rd"] / "metrics" / "ep02.jsonl").read_text(encoding="utf-8").splitlines()]
    assert m[-1]["by"] == "agent:claude-fable-5-1(dispatcher)" and m[-1]["model_source"] == "cli" and m[-1]["result"] == "done"
    AF = _load("autoflow_t_dm", "tools/script_rsi/autoflow.py")
    assert AF.done_model(env["rd"], "P3_ep02") == "claude-fable-5-1(dispatcher)"
    assert env["tick"]()["started"] == []                                     # 交了稿不再派


def test_model_split(env):
    env["add"]("facts_ep02", "reviewer", "sonnet")
    env["add"]("factcheck_ep02", "reviewer", "fable", at="2026-11-03T03:00:01")   # 评审用写手模型 → 不派、登记
    env["add"]("P4_ep02", "writer", "sonnet", at="2026-11-03T03:00:02")           # 写手不是 fable → 不派、登记
    r = env["tick"]()
    assert r["started"] == ["rx__facts_ep02_a1:sonnet"]
    assert sorted(r["failed"]) == ["rx__P4_ep02_a1", "rx__factcheck_ep02_a1"] and len(env["issues"]) == 2
    env["wait"]()
    env["tick"]()
    args = env["args"]()[0]["args"]
    assert args[args.index("--model") + 1] == "sonnet"


def test_concurrency_cap(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    for k in range(3):
        env["add"](f"P{k}_ep02", "writer", "fable", at=f"2026-11-03T03:00:0{k}")
    r = env["tick"]()
    assert len(r["started"]) == 2 and r["skipped"] == ["rx__P2_ep02_a1:concurrency"]
    assert env["tick"]()["started"] == []
    env["tick"](now=lambda: time.time() + 3600)                                   # 收尾：杀掉挂着的进程


def test_timeout_kill_requeue_then_issue(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    env["add"]("P3_ep02", "writer", "fable")
    AD, T = env["AD"], [time.time()]
    r = env["tick"](now=lambda: T[0])
    assert r["started"] == ["rx__P3_ep02_a1:fable"]
    for n in range(1, 4):
        st = json.loads((env["root"] / AD.STATE_DIR / "state.json").read_text(encoding="utf-8"))
        run = st["requests"]["rx__P3_ep02_a1"]["running"]
        assert run["n"] == n
        (env["rd"] / "writer_out").mkdir(exist_ok=True)
        (env["rd"] / "writer_out" / "P3_ep02_a1.json").write_text("半截", encoding="utf-8")
        T[0] += 3600                                                               # 超过 30 分钟
        r = env["tick"](now=lambda: T[0])
        assert r["finished"] == ["rx__P3_ep02_a1:timeout"]
        assert r["started"] == (["rx__P3_ep02_a1:fable"] if n < 3 else [])        # 作废后同一拍重新排队，满 3 次不再派
        t0 = time.time()
        while AD.alive(run["pid"], run["sig"]) and time.time() - t0 < 30:
            time.sleep(0.2)
        assert not AD.alive(run["pid"], run["sig"])                               # 只杀了自己起的那个 pid
        assert not (env["rd"] / "writer_out" / "P3_ep02_a1.json").exists()        # 半截产物作废（移走，不删）
        assert list((env["rd"] / "writer_out_void").glob("P3_ep02_a1.json.dispatch*"))
    assert r["failed"] == ["rx__P3_ep02_a1"] and len(env["issues"]) == 1          # 累计 3 次 → 登记卡点
    assert env["tick"]()["started"] == []                                         # 不再派
    m = [json.loads(x) for x in (env["rd"] / "metrics" / "ep02.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["result"] for x in m] == ["timeout"] * 3 and [x["attempts"] for x in m] == [1, 2, 3]


def test_claimed_by_owner_skipped(env):
    env["add"]("P3_ep02", "writer", "fable")
    (env["inbox"] / "requests" / "P3_ep02_a1.claimed").write_text("总调度手工派", encoding="utf-8")
    r = env["tick"]()
    assert r["started"] == [] and r["skipped"] == ["rx__P3_ep02_a1:claimed"]


def test_void_marker_or_missing_packet_not_dispatched(env):
    """TIMELINE-O 11-03：P4_ep01_a3 隔离前已被领走白跑一次 → 作废标记 / 作业包已隔离 = 不派"""
    env["add"]("P3_ep02", "writer", "fable")
    (env["inbox"] / "requests" / "rx__P3_ep02_a1.void").write_text("{}", encoding="utf-8")
    r = env["tick"]()
    assert r["started"] == [] and r["skipped"] == ["rx__P3_ep02_a1:void"]
    env["add"]("P2_ep03", "writer", "fable")
    (env["rd"] / "writer_tasks" / "P2_ep03_a1.json").unlink()          # 作业包被隔离
    r = env["tick"]()
    assert r["started"] == []                                          # 包不在：pending_requests 不列为待派 / 派单器判 void


def test_running_job_killed_when_voided(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    env["add"]("P3_ep02", "writer", "fable")
    AD = env["AD"]
    assert env["tick"]()["started"] == ["rx__P3_ep02_a1:fable"]
    st = json.loads((env["root"] / AD.STATE_DIR / "state.json").read_text(encoding="utf-8"))
    run = st["requests"]["rx__P3_ep02_a1"]["running"]
    (env["inbox"] / "requests" / "rx__P3_ep02_a1.void").write_text("{}", encoding="utf-8")
    r = env["tick"]()
    assert r["finished"] == ["rx__P3_ep02_a1:voided"] and r["started"] == []      # 杀掉、不重排
    t0 = time.time()
    while AD.alive(run["pid"], run["sig"]) and time.time() - t0 < 30:
        time.sleep(0.2)
    assert not AD.alive(run["pid"], run["sig"])
    assert env["tick"]()["started"] == []


RESIDENT = r'''
import importlib.util, json, sys, time
from pathlib import Path
a = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sp = importlib.util.spec_from_file_location("ad_res", a["ad"]); AD = importlib.util.module_from_spec(sp); sp.loader.exec_module(AD)
print(json.dumps(AD.tick(root=Path(a["root"]), cfg=a["cfg"], report=lambda *x: None)), flush=True)
time.sleep(120)
'''


def test_resident_restart_does_not_kill_or_requeue_writer(env, monkeypatch, tmp_path):
    """ISS-1103-033131-1efe：resident 被 taskkill /T /F（ops/restart_autoflow.ps1 的做法）后，派单器起的写手还活着；
    新 resident 按 state.json 的 pid + 创建时间接回，不重新排队、不算新尝试"""
    import subprocess
    monkeypatch.setenv("FAKE_MODE", "hang")
    AD = env["AD"]
    env["add"]("P3_ep02", "writer", "fable")
    spec = tmp_path / "res.json"
    spec.write_text(json.dumps({"ad": str(ROOT / "tools/factory/agent_dispatcher.py"), "root": str(env["root"]), "cfg": env["cfg"]}), encoding="utf-8")
    (tmp_path / "res.py").write_text(RESIDENT, encoding="utf-8")
    res = subprocess.Popen([sys.executable, str(tmp_path / "res.py"), str(spec)], stdout=subprocess.PIPE)
    line = res.stdout.readline().decode("utf-8")
    assert json.loads(line)["started"] == ["rx__P3_ep02_a1:fable"]
    st = json.loads((env["root"] / AD.STATE_DIR / "state.json").read_text(encoding="utf-8"))
    run = st["requests"]["rx__P3_ep02_a1"]["running"]
    assert run["sig"] and run["launch"] in ("breakaway", "detached", "setsid")
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(res.pid), "/T", "/F"], capture_output=True, timeout=60)
    else:
        res.kill()
    res.wait(timeout=30)
    time.sleep(1)
    assert AD.alive(run["pid"], run["sig"])                                       # 写手没被 resident 的进程树带走
    r = env["tick"]()                                                             # “新 resident”的第一拍
    assert r["started"] == [] and r["finished"] == []                             # 接回：不重排、不新起
    st2 = json.loads((env["root"] / AD.STATE_DIR / "state.json").read_text(encoding="utf-8"))
    assert st2["requests"]["rx__P3_ep02_a1"]["running"]["pid"] == run["pid"] and st2["requests"]["rx__P3_ep02_a1"]["attempts"] == 1
    env["tick"](now=lambda: time.time() + 3600)                                   # 收尾：超时杀掉
    t0 = time.time()
    while AD.alive(run["pid"], run["sig"]) and time.time() - t0 < 30:
        time.sleep(0.2)
    assert not AD.alive(run["pid"], run["sig"])
