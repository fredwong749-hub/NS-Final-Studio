"""封板修复回归（2026-10-30 后端审计 P2）：剧本对话锁必放、坏会话不拖垮列表、集摘要缓存代数、草稿并发保存、
readiness 未知集 404、上游非对象 JSON、每镜锁（并发上传版本号不重复、渲染线程撞号顺延）"""
import io
import json
import threading

import pytest
from fastapi.testclient import TestClient

from ns_api import app as APP
from ns_api import episodes_fast as EF
from ns_api import gpu_monitor as G
from ns_api import qwen_mailbox as QM
from ns_api import script_chat as S
from ns_api import script_inbox as SI
from ns_api import script_input as SIN
from ns_render import pipeline as P
from ns_schema.edits import Take

c = TestClient(APP.app)


# ---------------------------------------------------------------- 1 剧本对话

@pytest.fixture
def chat_store(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STORE", tmp_path)
    monkeypatch.setenv("ABLITERATION_API_KEY", "test-key")
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text))
    return tmp_path


def test_chat_lock_released_when_partial_save_raises(chat_store, monkeypatch):
    sid = S.new_session()["id"]

    def broken_stream(msgs, *a, **k):
        yield "content", "半截"
        raise S.ChatError("断了")
    monkeypatch.setattr(S, "stream_completion", broken_stream)
    real = S.update_session
    calls = []

    def flaky(sid_, fn):
        calls.append(1)
        if len(calls) > 1:               # 第一次（加用户消息）正常；中途存档时跨进程锁超时
            raise TimeoutError("lock timeout")
        return real(sid_, fn)
    monkeypatch.setattr(S, "update_session", flaky)
    try:
        c.post(f"/api/script-chat/sessions/{sid}/chat", json={"content": "写一集"})
    except TimeoutError:
        pass
    lk = S._lock(sid)
    assert lk.acquire(blocking=False), "存档抛错后会话锁没放 → 会话一直 409"
    lk.release()


def test_list_sessions_skips_corrupt(chat_store):
    good = S.new_session()["id"]
    (chat_store / "bad").mkdir()
    (chat_store / "bad" / "session.json").write_text("{坏的", encoding="utf-8")
    (chat_store / "bad2").mkdir()
    (chat_store / "bad2" / "session.json").write_text("[1, 2]", encoding="utf-8")
    r = c.get("/api/script-chat/sessions")
    assert r.status_code == 200 and [x["id"] for x in r.json()] == [good]


# ---------------------------------------------------------------- 2 集摘要缓存

def test_summary_cache_discards_build_started_before_invalidate():
    box = {"v": "old"}
    started, go = threading.Event(), threading.Event()

    def build():
        v = box["v"]
        if v == "old":
            started.set()
            go.wait(5)
        return [{"number": 1, "title": v, "shots": []}]
    cache = EF.SummaryCache(build, ttl_s=999)
    cache._data, cache._at = [{"number": 1, "title": "older"}], 1.0
    cache._kick()                       # 后台开始算（读到 old）
    assert started.wait(5)
    box["v"] = "new"
    cache.invalidate()                  # 算的过程中换剧本 / 写入
    go.set()
    for _ in range(200):
        with cache._lock:
            if cache._data and cache._data[0]["title"] == "new" and not cache._refreshing:
                break
        threading.Event().wait(0.02)
    assert cache._data[0]["title"] == "new", "开始于失效之前的重算结果不能写回"


def test_write_endpoints_invalidate_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    called = []
    monkeypatch.setattr(APP._summary_cache, "invalidate", lambda: called.append(1))
    sid = APP._script.episodes[0].shots[0].id
    assert c.put(f"/api/shots/{sid}/edit", json={}).status_code == 200
    assert called, "put_edit 之后集摘要没失效"


# ---------------------------------------------------------------- 3 草稿保存

def test_draft_lone_cr_and_concurrent_same_name(monkeypatch, tmp_path):
    monkeypatch.setattr(SI, "REPO", tmp_path)
    monkeypatch.setattr(SI, "DATA", tmp_path / "data")
    out = SIN._write_draft("一", "a\rb\r\nc", False)
    assert (SIN.drafts_dir() / out["name"]).read_bytes() == b"a\nb\nc"
    codes, errs = [], []

    def save():
        try:
            SIN._write_draft("并发", "x" * 1000, False)
            codes.append(200)
        except Exception as e:  # noqa: BLE001
            codes.append(getattr(e, "status_code", None) or errs.append(e))
    ts = [threading.Thread(target=save) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs and codes.count(200) == 1 and codes.count(409) == 7
    assert not list(SIN.drafts_dir().glob("*.tmp"))
    SIN._write_draft("并发", "y", True)
    assert (SIN.drafts_dir() / "并发.md").read_bytes() == b"y"


# ---------------------------------------------------------------- 4 readiness

def test_readiness_unknown_episode_404():
    assert c.get("/api/readiness", params={"ep": 99999}).status_code == 404


# ---------------------------------------------------------------- 5 上游非对象 JSON

def test_merge_upstream_non_object():
    rec = {"id": "t1", "status": "queued"}
    assert QM._merge_upstream(rec, ["x"]) == rec
    assert QM._merge_upstream(rec, "oops")["status"] == "queued"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_gpu_monitor_qwen_tasks_object(monkeypatch):
    monkeypatch.setattr(G.urllib.request, "urlopen", lambda *a, **k: _Resp(json.dumps({"tasks": []}).encode()))
    assert G._qwen()["reachable"] is False
    monkeypatch.setattr(G.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(json.dumps(["x", {"status": "running", "id": 1}]).encode()))
    assert G._qwen()["running"] == 1


# ---------------------------------------------------------------- 6 每镜锁

def test_concurrent_first_frame_uploads_get_distinct_n(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    sid = APP._script.episodes[0].shots[0].id
    res = []

    def up(i):
        r = c.post(f"/api/shots/{sid}/first-frame", files={"file": (f"{i}.png", b"\x89PNG" + bytes([i]), "image/png")})
        res.append(r.status_code)
    ts = [threading.Thread(target=up, args=(i,)) for i in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert res == [200] * 6
    ns = [t["n"] for t in P.load_takes(sid)["takes"] if t["stage"] == "image"]
    assert sorted(ns) == [1, 2, 3, 4, 5, 6]


def test_add_take_renumbers_on_collision(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "stamp_versions", lambda sid, t: t)
    sid = "ep01-S1"
    n = P._next_n(sid, "image")          # 渲染线程开工时取号
    P._add_take(sid, Take(n=n, stage="image", file="u.png", seed=0, prompt="", created_at="x", source="upload"),
                activate=False)          # 出图期间上传占了这个号
    t = Take(n=n, stage="image", file="w.png", seed=1, prompt="", created_at="x")
    P._add_take(sid, t, activate=False)
    assert t.n == 2 and sorted(x["n"] for x in P.load_takes(sid)["takes"]) == [1, 2]
    assert isinstance(P.shot_lock(sid), type(threading.RLock())) and P.shot_lock(sid) is P.shot_lock(sid)
