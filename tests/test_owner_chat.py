"""W30 PLAN_OWNER_CHAT 分期 2：chat 只读助手（桩模型，不花钱）。
list_todo 与 /api/owner/queue 同源；explain / 送模型的载荷不带图；执行类输出被拦；digest 一句话；请求 / 回复落日志。"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import auth
from ns_api import owner_chat as OC
from ns_api import owner_queue as OQ

ITEMS = [
    {"id": "req-1", "kind": "pick", "category": "pick", "category_label": "挑一张", "title": "第 1 集 S3 首帧请你挑",
     "detail": "两张都过了契约", "media": [{"url": "/api/file?p=data/renders/series10_v2/ep01/S3/v2.png", "kind": "image"}],
     "candidates": [{"key": "1", "label": "1 号", "url": "/api/file?p=a.png", "thumb": "/api/file?p=a_t.png", "full": "x.png", "score": 7.1},
                    {"key": "2", "label": "2 号", "url": "/api/file?p=b.png", "thumb": "/api/file?p=b_t.png", "full": "y.png", "score": 8.6}],
     "options": [{"key": "1", "label": "1 号"}, {"key": "2", "label": "2 号"}],
     "recommend": {"choice": "2", "why": "契约分最高"},
     "scores": [{"id": "Q1", "title": "人物脸一致", "status": "pass", "detail": ""},
                {"id": "Q9", "title": "本地看图", "status": "fail", "detail": "手部畸形 见 D:/x/ep01/S3/v2.png"}]},
    {"id": "dec-1", "kind": "decide", "category": "spend", "category_label": "花钱", "title": "批准租一台 4090 一晚", "detail": "约 30 元",
     "options": [{"key": "approve", "label": "批准"}, {"key": "reject", "label": "不批准"}], "recommend": None, "scores": [], "media": []},
]


def _queue(items):
    return {"schema": "nsfs.owner_queue/1", "count": len(items), "counts": {"decide": 1, "spot": 0, "pick": 1}, "items": items,
            "auto_today": {"total": 73}, "master_waits": {"n": 51, "title": "总调度在定 51 项（等总调度，不需要你）"}, "status": "ok"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    box = {"q": _queue(ITEMS), "calls": 0}

    def fake_build(root=None, now=None):
        box["calls"] += 1
        return box["q"]

    monkeypatch.setattr(OQ, "build", fake_build)
    return tmp_path, box


def _stub(replies, seen):
    it = iter(replies)

    def fn(system, messages):
        seen.append(json.dumps(messages, ensure_ascii=False))
        return next(it)
    return fn


def test_list_todo_same_source_as_queue(env, monkeypatch):
    root, box = env
    app = FastAPI()
    app.include_router(OQ.router)
    app.include_router(OC.router)
    c = TestClient(app)
    q = c.get("/api/owner/queue").json()
    todo = OC.list_todo(root)
    assert todo["count"] == q["count"] == 2
    assert [x["id"] for x in todo["items"]] == [x["id"] for x in q["items"]]
    assert box["calls"] == 2        # 两边都走 owner_queue.build，同一个函数，不另起状态


def test_explain_has_no_images(env):
    root, _ = env
    e = OC.explain("req-1", root)
    s = json.dumps(e, ensure_ascii=False)
    assert e["found"] and "契约分最高" in s and "本地看图：没过" in s and "手部畸形" in s
    for bad in (".png", "/api/", "D:/x", "url", "thumb"):
        assert bad not in s
    assert OC.explain("nope", root)["found"] is False


def test_model_payload_text_only_and_read_tools(env):
    root, _ = env
    seen = []
    fn = _stub(['{"tool_calls":[{"tool":"explain","args":{"item_id":"req-1"}}]}',
                '```json\n{"say":"挑 S3 首帧，推荐 2 号。","need":"挑第 1 集 S3 首帧","proposed_actions":[{"tool":"pick","args":{"item_id":"req-1","choice":"2"},"label":"用推荐的 2 号"}]}\n```'],
               seen)
    r = OC.chat("现在要我做什么", [{"role": "user", "content": "看 http://x/y.jpg"}], root, "owner", model_fn=fn)
    assert len(seen) == 2 and r["tools_used"] == ["list_todo", "explain"]
    for payload in seen:
        for bad in (".png", ".jpg", "/api/file", "http://", "D:/x"):
            assert bad not in payload
    assert r["need"] == "挑第 1 集 S3 首帧" and r["reply"].startswith("挑 S3")
    assert r["proposed_actions"] == [{"tool": "pick", "args": {"item_id": "req-1", "choice": "2"}, "label": "用推荐的 2 号",
                                      "executable": False, "phase": "下一期"}]


def test_exec_outputs_blocked_never_executed(env, monkeypatch):
    root, _ = env
    hit = []
    monkeypatch.setattr(OQ, "decide", lambda *a, **k: hit.append(a))
    fn = _stub(['{"tool_calls":[{"tool":"decide","args":{"item_id":"dec-1","choice":"approve"}},{"tool":"bash","args":{"cmd":"rm -rf"}}],'
                '"execute":"approve dec-1"}',
                '{"say":"需要你批准租卡","need":"批准或不批准租 4090","proposed_actions":[{"tool":"shell","args":{}},'
                '{"tool":"decide","args":{"item_id":"dec-1","choice":"approve"},"label":"批准"}]}'], [])
    r = OC.chat("帮我批准", [], root, "owner", model_fn=fn)
    assert hit == []                                                     # 后端决定入口一次都没被调
    tools = {b["tool"] for b in r["blocked"]}
    assert {"decide", "bash", "execute", "shell"} <= tools
    assert [a["tool"] for a in r["proposed_actions"]] == ["decide"] and r["proposed_actions"][0]["executable"] is False


def test_model_failure_falls_back_and_logs(env):
    root, _ = env

    def boom(system, messages):
        raise TimeoutError("180s")
    r = OC.chat("现在要我做什么", [], root, "owner", model_fn=boom)
    assert "error" in r and r["need"].startswith("现在要你做 2 件事")
    rows = [json.loads(x) for x in (root / OC.LOG_REL).read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["message"] == "现在要我做什么" and rows[-1]["user"] == "owner" and rows[-1]["error"]


def test_digest_one_sentence(env):
    root, box = env
    s = OC.digest(root)["sentence"]
    assert s.count("。") == 1 and s.endswith("。") and "2 件事" in s and "批准租一台 4090" in s   # 拍板在前
    assert ".png" not in s
    box["q"] = _queue([])
    s = OC.digest(root)["sentence"]
    assert s == "现在没有要你做的事；今天系统已自动处理 73 项，另有 51 项由总调度在处理。"
    box["q"] = {**_queue([]), "status": "error", "status_label": "队列读取失败：requests.json"}
    assert "读取不全" in OC.digest(root)["sentence"]


def test_endpoint_owner_only_and_digest_get(env, monkeypatch):
    root, _ = env
    monkeypatch.setattr(OC, "REPO", root)
    monkeypatch.setattr(OC, "call_model", lambda system, messages, root=None: '{"say":"好","need":"挑图"}')
    app = FastAPI()
    app.include_router(OC.router)
    c = TestClient(app)
    monkeypatch.setattr(auth, "user_of", lambda req: None)
    assert c.post("/api/owner/chat", json={"message": "hi"}).status_code == 403
    monkeypatch.setattr(auth, "user_of", lambda req: {"name": "fred", "role": "owner"})
    r = c.post("/api/owner/chat", json={"message": "hi", "history": []}).json()
    assert r["need"] == "挑图" and r["proposed_actions"] == []
    assert c.get("/api/owner/chat/digest").json()["sentence"].startswith("现在要你做 2 件事")


def test_config_purpose_present_and_switchable():
    pc = OC.purpose_cfg(OC.REPO)
    assert pc["provider"] == "claude_cli" and pc["model"] == "fable"
    assert pc["switch_to"] == {"provider": "abliteration", "model": "abliterated-model-large-flash"}
