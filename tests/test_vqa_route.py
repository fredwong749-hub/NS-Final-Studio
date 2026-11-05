"""W23 VQA-ROUTE：看图客户端路由（本机 8870 优先 → 8871 隧道 → 未测）、超时 = 未测、route.jsonl。全用桩，不连真服务。"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "agent"))

from ns_agent.vqa import client as C  # noqa: E402
from ns_agent.vqa import contract  # noqa: E402

REQ = {"system": "s", "text": "t", "images": [{"path": "nope.png", "max_pixels": 1000}]}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    monkeypatch.delenv("VQA_LAN", raising=False)
    monkeypatch.delenv("VQA_URL", raising=False)
    monkeypatch.setattr(C, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(C, "ROUTE_LOG", tmp_path / "route.jsonl")
    monkeypatch.setattr(C, "_rcfg", lambda: {"queue_max": 3, "busy_wait_s": 0.3, "poll_s": 0.1,
                                             "timeouts": {"image": 240, "ask": 30}})
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    st = {"health": {}, "posts": []}

    def up(u):
        h = st["health"].get(u.rsplit(":", 1)[1])
        C._HEALTH.pop(u, None)
        if h is None:
            return False
        C._HEALTH[u] = h() if callable(h) else h
        return True

    def post(u, body, t):
        st["posts"].append((u, t, body))
        r = st.get("post")
        if isinstance(r, BaseException):
            raise r
        return r or {"text": "{}", "model": "m"}

    monkeypatch.setattr(C, "_local_up", up)
    monkeypatch.setattr(C, "_post_local", post)
    st["log"] = lambda: [json.loads(x) for x in (tmp_path / "route.jsonl").read_text(encoding="utf-8").splitlines()]
    return st


def test_local_up_only_local(env):
    env["health"] = {"8870": {"loaded": True, "queue": 1}, "8871": {"loaded": True, "queue": 0}}
    r = C.generate(dict(REQ), refresh=True, kind="image")
    assert "error" not in r and r["route"] == "local"
    assert [u for u, _, _ in env["posts"]] == ["http://127.0.0.1:8870"]
    assert env["posts"][0][1] == 240 * 2                   # 超时 = timeouts[image] ×（排队+1）
    row = env["log"]()[-1]
    assert row["route"] == "local" and row["ok"] is True and row["kind"] == "image" and {"at", "ms"} <= set(row)


def test_local_down_uses_tunnel(env):
    env["health"] = {"8871": {}}
    r = C.generate(dict(REQ), refresh=True)
    assert "error" not in r and env["posts"][0][0].endswith(":8871")
    assert env["log"]()[-1]["route"] == "tunnel"


def test_local_not_loaded_uses_tunnel(env):
    env["health"] = {"8870": {"loaded": False, "queue": 0}, "8871": {"queue": 0}}
    C.generate(dict(REQ), refresh=True)
    assert env["posts"][0][0].endswith(":8871")


def test_both_down_untested(env):
    r = C.generate(dict(REQ), refresh=True)
    assert r["status"] == "untested" and r["reason"] == "服务不可用" and not env["posts"]
    assert env["log"]()[-1] == {**env["log"]()[-1], "route": "none", "ok": False}
    v = C._finish(REQ, r, "image", "x.png")
    st, _, ev = contract._item(v, False)
    assert st == "untested" and not ev.get("model")         # accept.q9_timeout 口径：evidence 无 model → retry 不判 fail


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), socket.timeout("timed out")])
def test_timeout_untested(env, exc):
    env["health"] = {"8870": {"loaded": True, "queue": 0}}
    env["post"] = exc
    r = C.generate(dict(REQ), refresh=True, kind="ask")
    assert r["status"] == "untested" and r["reason"] == "超时"
    assert env["posts"][0][1] == 60                         # 至少 60 s（配置 30 也抬到 60）
    row = env["log"]()[-1]
    assert row["route"] == "local" and row["ok"] is False and row["reason"] == "超时"


def test_connection_drop_untested(env):
    env["health"] = {"8870": {"loaded": True, "queue": 0}}
    env["post"] = ConnectionResetError("reset")
    assert C.generate(dict(REQ), refresh=True)["reason"] == "服务不可用"


def test_local_busy_waits_not_tunnel(env):
    env["health"] = {"8870": {"loaded": True, "queue": 9}, "8871": {"queue": 0}}
    r = C.generate(dict(REQ), refresh=True)
    assert r["status"] == "untested" and r["reason"] == "本机忙" and not env["posts"]   # 不切隧道


def test_local_busy_then_frees(env):
    qs = iter([5, 5, 1])
    env["health"] = {"8870": lambda: {"loaded": True, "queue": next(qs)}, "8871": {"queue": 0}}
    r = C.generate(dict(REQ), refresh=True)
    assert "error" not in r and env["posts"][0][0].endswith(":8870")


def test_timeout_capped_by_wait_s(env):
    env["health"] = {"8870": {"loaded": True, "queue": 2}}
    C.generate(dict(REQ), refresh=True, kind="image", wait_s=60)
    assert env["posts"][0][1] == 180


def test_cache_hit_no_route(env):
    env["health"] = {"8870": {"loaded": True, "queue": 0}}
    C.generate(dict(REQ), refresh=True)
    n = len(env["log"]())
    assert C.generate(dict(REQ))["cached"] and len(env["log"]()) == n and len(env["posts"]) == 1


def test_route_cfg_present():
    rc = json.loads((ROOT / "config" / "vqa.json").read_text(encoding="utf-8"))["route"]
    assert all(v >= 60 for v in rc["timeouts"].values()) and rc["queue_max"] > 0 and rc["busy_wait_s"] > 0


def test_w38_server_sends_to_unloaded_local(monkeypatch):
    """W38：服务器上本机 8870 空闲卸模型（loaded=false）仍算可用（服务端按需加载）；笔记本上 loaded=false 照旧不算"""
    from ns_agent.vqa import client as C
    monkeypatch.setattr(C, "_local_up", lambda url: C._HEALTH.__setitem__(url, {"loaded": False, "queue": 1}) or True)
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert C._ready("http://127.0.0.1:8870") == (True, 1)
    monkeypatch.delenv("OFFLINE_SELF")
    assert C._ready("http://127.0.0.1:8870") == (False, 0)


# ---- B1（11-05）服务器侧多实例分发：route.balance，默认关
def _bal(monkeypatch, env, extra=(), lan=True, **rc):
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    base = {"queue_max": 3, "busy_wait_s": 0.3, "poll_s": 0.1, "timeouts": {"image": 240, "ask": 30},
            "balance": True, "extra_local_ports": list(extra), **rc}
    monkeypatch.setattr(C, "_rcfg", lambda: base)
    monkeypatch.setattr(C, "cfg", lambda: {"model": {"port": 8870, "host": "gpu36", "lan_url": "http://10.0.0.36:8870"}})
    if not lan:
        env["health"].pop("8870x", None)


def test_balance_prefers_local_on_tie_and_least_queue(env, monkeypatch):
    _bal(monkeypatch, env, extra=[8880])
    env["health"] = {"8870": {"loaded": True, "queue": 2}, "8880": {"loaded": True, "queue": 0}}
    r = C.generate(dict(REQ), refresh=True, kind="ask")
    assert r["route"] == "local" and env["posts"][0][0] == "http://127.0.0.1:8880"
    env["posts"].clear()
    env["health"] = {"8870": {"loaded": True, "queue": 1}, "8880": {"loaded": True, "queue": 1}}
    C.generate(dict(REQ), refresh=True, kind="ask")
    assert env["posts"][0][0] == "http://127.0.0.1:8870"          # 并列 = 本机主实例优先


def test_balance_spills_to_lan_when_local_busy(env, monkeypatch):
    _bal(monkeypatch, env)
    # lan 与主端口同为 8870（不同主机）：桩按端口区分不了，改用 _ready 桩
    ready = {"http://127.0.0.1:8870": (True, 3), "http://10.0.0.36:8870": (True, 1)}
    monkeypatch.setattr(C, "_lan_url", lambda: "http://10.0.0.36:8870")
    monkeypatch.setattr(C, "_ready", lambda u: ready.get(u, (False, 0)))
    r = C.generate(dict(REQ), refresh=True, kind="ask")
    assert r["route"] == "lan" and env["posts"][0][0] == "http://10.0.0.36:8870"


def test_balance_all_busy_untested_and_off_by_default(env, monkeypatch):
    _bal(monkeypatch, env)
    monkeypatch.setattr(C, "_lan_url", lambda: None)
    monkeypatch.setattr(C, "_ready", lambda u: (True, 9))
    r = C.generate(dict(REQ), refresh=True, kind="ask")
    assert r["status"] == "untested" and r["reason"] == "本机忙" and not env["posts"]
    # 关闭（默认）：不走 balance 分支
    monkeypatch.setattr(C, "_rcfg", lambda: {"queue_max": 3})
    assert C._balance_cands("http://127.0.0.1:8870") == []


def test_balance_cfg_state():   # 11-05 CODER-I：gpu33:3 本机看图实例健康（:8870 loaded，文本 0.5 s）→ route.balance 开；Q10 parallel 11-05 PS-MASTER 按 AUDIT-PERF 开
    d = json.loads((ROOT / "config" / "vqa.json").read_text(encoding="utf-8"))["route"]
    assert d["balance"] is True and d["extra_local_ports"] == [] and d["balance_lan"] is True
    g = json.loads((ROOT / "config" / "gen_contract.json").read_text(encoding="utf-8"))
    assert g["image_thresholds"]["Q10_accept"]["parallel"] is True


def test_q10_parallel_label_same_result(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from tools.vqa import accept as A
    monkeypatch.setattr(A, "prompt_check", lambda *a, **k: {"status": "pass"})
    monkeypatch.setattr(A, "count_check", lambda *a, **k: {"status": "pass"})
    monkeypatch.setattr(A, "outfit", lambda *a, **k: {"status": "pass"})
    monkeypatch.setattr(A, "identity", lambda pf: {"status": "pass"})
    res = []
    for on in (False, True):
        monkeypatch.setattr(A, "_parallel_on", lambda on=on: on)
        res.append(A.label("ep01-S1", "first", "x.png", {}, host="h"))
    for r in res:
        r.pop("at")
    assert res[0] == res[1] and res[0]["ok"] == "pass"
