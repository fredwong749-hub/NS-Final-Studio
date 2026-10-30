"""Draft unit tests for tools/gpu3_tunnels.py. healthy/spawn are mocked; subprocess.Popen is booby-trapped so no
real ssh can start. Run from the repo root:  uv run python -m pytest -q <this file>"""
import http.client
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(r"D:\NS-Final Studio")
spec = importlib.util.spec_from_file_location("gpu3_tunnels_ut", REPO / "tools" / "gpu3_tunnels.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


class FakeProc:
    n = 0

    def __init__(self, events, name, hang=False):
        FakeProc.n += 1
        self.pid, self.events, self.name, self.alive, self.hang = 9000 + FakeProc.n, events, name, True, hang

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.events.append(("terminate", self.pid))
        if not self.hang:
            self.alive = False

    def wait(self, timeout=None):
        if self.alive:
            raise subprocess.TimeoutExpired("ssh", timeout)
        return 0

    def kill(self):
        self.events.append(("kill", self.pid))
        self.alive = False


@pytest.fixture
def env(monkeypatch):
    def no_real_ssh(*a, **k):
        raise AssertionError(f"real Popen called: {a}")
    monkeypatch.setattr(T.subprocess, "Popen", no_real_ssh)
    monkeypatch.setattr(sys, "argv", ["gpu3_tunnels.py"])
    st = {"events": [], "procs": [], "iters": 0, "max_iters": 1, "health": lambda port, path, it: True,
          "hang": False}

    def fake_spawn(local, remote):
        name = next(n for n, lp, *_ in T.TUNNELS if lp == local)
        p = FakeProc(st["events"], name, st["hang"])
        st["procs"].append(p)
        st["events"].append(("spawn", name, p.pid))
        return p

    def fake_sleep(s):
        st["iters"] += 1
        if st["iters"] >= st["max_iters"]:
            raise KeyboardInterrupt

    monkeypatch.setattr(T, "spawn", fake_spawn)
    monkeypatch.setattr(T, "healthy", lambda port, path: st["health"](port, path, st["iters"]))
    monkeypatch.setattr(T.time, "sleep", fake_sleep)
    return st


def spawns(st):
    return [e[1] for e in st["events"] if e[0] == "spawn"]


def test_healthy_never_spawns(env):
    env["max_iters"] = 5
    assert T.main() == 0
    assert spawns(env) == []


def test_one_failure_no_spawn_two_failures_spawn(env):
    env["health"] = lambda port, path, it: port != 15180
    env["max_iters"] = 1
    T.main()
    assert spawns(env) == []          # 1 failure: wait
    env.update(events=[], procs=[], iters=0, max_iters=2)
    T.main()
    assert spawns(env) == ["bridge"]  # 2nd consecutive failure: (re)open only that tunnel


def test_recovery_resets_counter(env):
    # fail, ok, fail, ok ... never two in a row -> never spawn
    env["health"] = lambda port, path, it: port != 15180 or it % 2 == 1
    env["max_iters"] = 6
    T.main()
    assert spawns(env) == []


def test_own_process_terminated_before_respawn(env):
    env["health"] = lambda port, path, it: port != 18098
    env["max_iters"] = 4              # spawn at iter 2, again at iter 4
    T.main()
    ev = [e for e in env["events"] if e[0] in ("spawn", "terminate")]
    p1, p2 = env["procs"]
    assert ev[:3] == [("spawn", "qwen-llm", p1.pid), ("terminate", p1.pid), ("spawn", "qwen-llm", p2.pid)]


def test_terminate_timeout_then_kill(env):
    env["health"] = lambda port, path, it: port != 18099
    env["hang"] = True
    env["max_iters"] = 4
    T.main()
    p1 = env["procs"][0]
    assert ("kill", p1.pid) in env["events"]
    assert env["events"].index(("terminate", p1.pid)) < env["events"].index(("kill", p1.pid))


def test_keyboard_interrupt_cleans_up_only_live_own(env):
    env["health"] = lambda port, path, it: False
    env["max_iters"] = 2
    assert T.main() == 0
    assert sorted(spawns(env)) == ["bridge", "mailbox", "qwen-llm"]
    assert sorted(e[1] for e in env["events"] if e[0] == "terminate") == sorted(p.pid for p in env["procs"])
    assert all(not p.alive for p in env["procs"])


def test_dead_own_process_not_terminated(env):
    env["health"] = lambda port, path, it: port != 15180
    env["max_iters"] = 4
    orig = T.spawn

    def spawn_dead(local, remote):
        p = orig(local, remote)
        p.alive = False               # ssh exited at once (e.g. port held by another tunnel)
        return p
    T.spawn = spawn_dead
    try:
        T.main()
    finally:
        T.spawn = orig
    assert not [e for e in env["events"] if e[0] == "terminate"]
    assert spawns(env) == ["bridge", "bridge"]   # respawn churn every 2 intervals, no backoff


def test_check_mode(env, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gpu3_tunnels.py", "--check"])
    env["health"] = lambda port, path, it: port != 18099
    assert T.main() == 1
    env["health"] = lambda port, path, it: True
    assert T.main() == 0
    assert spawns(env) == []


# ---- real healthy() with urlopen mocked
@pytest.mark.parametrize("exc", [ConnectionRefusedError(), socket.timeout(), http.client.RemoteDisconnected("x")])
def test_healthy_oserrors_are_false(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(T.urllib.request, "urlopen", boom)
    assert T.healthy(1, "/h") is False


def test_healthy_non_oserror_http_exception(monkeypatch):
    """http.client.HTTPException that is not an OSError (e.g. BadStatusLine from a half-open tunnel) escapes
    healthy() and, since main() only catches KeyboardInterrupt, ends the supervisor."""
    def boom(*a, **k):
        raise http.client.BadStatusLine("garbage")
    monkeypatch.setattr(T.urllib.request, "urlopen", boom)
    assert T.healthy(1, "/h") is False
