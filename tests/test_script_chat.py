"""T58 剧本创作对话框：写作模型用假 urlopen 代替（不连 abliteration）。
覆盖：整集切分、缺 key / 限流 / 超时 / 流式中断都以 SSE error 事件返回（界面不白屏）、成功回复并入草稿并做格式校验。"""
import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from ns_api import script_chat as S
from ns_api.app import app

c = TestClient(app)

EP = """## ep03《测试集》

**剧情**：占位

**配乐**：占位；【BGM】Soft piano at 70 BPM.

**镜1｜img**：中景，林晚
**motion**：lnwan01，static camera，她抬眼——她看向镜头
**时长**：5秒
"""


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def sse(*chunks, finish="stop"):
    lines = [{"choices": [{"delta": {"reasoning": "想一想"}}]}]
    lines += [{"choices": [{"delta": {"content": x}}]} for x in chunks]
    if finish:
        lines.append({"choices": [{"delta": {}, "finish_reason": finish}], "usage": {"completion_tokens": 9}})
    body = "".join(f"data: {json.dumps(x, ensure_ascii=False)}\n\n" for x in lines)
    return FakeResp((body + ("data: [DONE]\n\n" if finish else "")).encode("utf-8"))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STORE", tmp_path)
    monkeypatch.setenv("ABLITERATION_API_KEY", "test-key")
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text))   # 不连 gpu3 /tokenize
    return tmp_path


def events(resp):
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def chat(sid, text="写一集"):
    return events(c.post(f"/api/script-chat/sessions/{sid}/chat", json={"content": text}))


def test_split_and_unwrap():
    reply = "```markdown\n" + EP + "\n---\n\n" + EP.replace("ep03", "ep04") + "\n---\n```"
    eps = S.split_episodes(reply)
    assert sorted(eps) == [3, 4]
    assert eps[3].startswith("## ep03《") and not eps[3].rstrip().endswith("---")


def test_success_merges_into_draft_and_validates(store, monkeypatch):
    monkeypatch.setattr(S.urllib.request, "urlopen", lambda req, timeout=0: sse(EP[:40], EP[40:]))
    sid = c.post("/api/script-chat/sessions", json={}).json()["id"]
    ev = chat(sid)
    kinds = [e["t"] for e in ev]
    assert kinds[-1] == "done", ev[-1]
    assert kinds[0] == "start" and "reasoning" in kinds and kinds[-1] == "done"
    assert ev[-1]["episodes"] == [3]
    s = c.get(f"/api/script-chat/sessions/{sid}").json()
    assert s["messages"][-1]["content"] == EP and s["messages"][-1]["reasoning"] == "想一想"
    draft = (store / sid / "script.md").read_text(encoding="utf-8")
    assert "## ep03《测试集》" in draft and "**每条prompt统一前缀" in draft   # 全局头 + 这一集
    assert s["validation"]["episodes"][0]["number"] == 3                     # 格式校验跑过（内容不判断）


def test_missing_key(store, monkeypatch):
    monkeypatch.delenv("ABLITERATION_API_KEY")
    real = S.provider
    monkeypatch.setattr(S, "provider", lambda cfg=None: {**real(cfg), "name": "abliteration", "api_key": None})
    monkeypatch.setattr(S, "load_config", lambda: {**json.loads(S.CONFIG.read_text(encoding="utf-8")),
                                                   "provider": "abliteration"})
    sid = S.new_session()["id"]
    ev = chat(sid)
    assert ev[-1]["t"] == "error" and "API key" in ev[-1]["d"]


@pytest.mark.parametrize("code,word", [(429, "限流"), (401, "key"), (503, "不可用")])
def test_http_errors(store, monkeypatch, code, word):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b'{"error":"x"}'))
    monkeypatch.setattr(S.urllib.request, "urlopen", boom)
    ev = chat(S.new_session()["id"])
    assert ev[-1]["t"] == "error" and str(code) in ev[-1]["d"] and word in ev[-1]["d"]


def test_timeout(store, monkeypatch):
    def slow(req, timeout=0):
        raise TimeoutError("timed out")
    monkeypatch.setattr(S.urllib.request, "urlopen", slow)
    ev = chat(S.new_session()["id"])
    assert ev[-1]["t"] == "error" and "超时" in ev[-1]["d"]


def test_interrupted_stream_saves_partial(store, monkeypatch):
    monkeypatch.setattr(S.urllib.request, "urlopen", lambda req, timeout=0: sse("## ep05《半", finish=None))
    sid = S.new_session()["id"]
    ev = chat(sid)
    assert ev[-1]["t"] == "error" and "中断" in ev[-1]["d"]
    last = S.load_session(sid)["messages"][-1]
    assert last["partial"] is True and last["content"] == "## ep05《半"


def test_busy_session_rejected(store):
    sid = S.new_session()["id"]
    S._lock(sid).acquire()
    try:
        assert c.post(f"/api/script-chat/sessions/{sid}/chat", json={"content": "x"}).status_code == 409
    finally:
        S._lock(sid).release()


def test_bad_session_id():
    assert c.get("/api/script-chat/sessions/..%2F..%2Fetc").status_code in (400, 404)


def test_appendix_selected_by_context(tmp_path, monkeypatch):
    ap = tmp_path / "appx.md"
    ap.write_text("## [总则]\n> 触发：全部\nAAA\n\n## [亲密镜]\n> 触发：【亲密声】、pose_\nBBB\n", encoding="utf-8")
    cfg = {**S.load_config(), "appendix": str(ap)}
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text))
    plain, _ = S.build_system_prompt(cfg, context="普通对话镜")
    hot, parts = S.build_system_prompt(cfg, context="sound：…；【亲密声】…")
    assert "AAA" in plain and "BBB" not in plain and "BBB" in hot
    assert any(p["name"] == "附录·亲密镜" for p in parts)


def test_appendix_priority_hit_before_always(tmp_path, monkeypatch):
    """空间不够时先丢“全部”类通用节，命中本集触发词的节保留；命中的也放不下时标 dropped=hit（调用方拆半）"""
    ap = tmp_path / "appx.md"
    ap.write_text("## [通用]\n> 触发：全部\n" + "G" * 50 + "\n\n## [亲密镜]\n> 触发：【亲密声】\n" + "H" * 50 + "\n",
                  encoding="utf-8")
    cfg = {**S.load_config(), "appendix": str(ap)}
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text))
    t, parts = S.build_system_prompt(cfg, context="【亲密声】", appendix_budget=80)
    assert "H" * 50 in t and "G" * 50 not in t
    assert [p["dropped"] for p in parts if p.get("dropped")] == ["always"]
    _, parts = S.build_system_prompt(cfg, context="【亲密声】", appendix_budget=10)
    assert sorted(p["dropped"] for p in parts if p.get("dropped")) == ["always", "hit"]


def test_context_budget_drops_history_then_errors(monkeypatch):
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text))
    monkeypatch.setattr(S, "provider", lambda cfg=None: {"name": "qwen", "ctx": 10000, "max_tokens": 5000})
    sys_m, old, new = ({"role": "system", "content": "s" * 100}, {"role": "user", "content": "o" * 3000},
                       {"role": "user", "content": "n" * 3000})
    msgs, mt = S.fit_messages([sys_m, old, {"role": "assistant", "content": "a" * 3000}, new])
    assert msgs[0] is sys_m and msgs[-1] is new and old not in msgs and mt == 5000
    with pytest.raises(S.ChatError):
        S.fit_messages([sys_m, {"role": "user", "content": "x" * 9000}])


def test_shot_split_merge_roundtrip():
    ep = EP + "\n**镜2｜img**：近景\n**motion**：static camera，她笑——她看向窗外很久很久\n"
    head, shots, _ = S.split_shots(ep)
    assert sorted(shots) == [1, 2]
    new = S.merge_shot(ep, 2, "**镜2｜img**：特写\n**motion**：static camera，她笑——她低头看手里的杯子\n")
    assert "特写" in S.split_shots(new)[1][2] and S.split_shots(new)[1][1] == shots[1]


def test_shot_only_repair_reply_merged(monkeypatch):
    """fredw-92/D2：【格式返修】回复只有 `**镜N｜img` 块（没有 `## ep`）时并入被点名的那一集，不静默丢失"""
    monkeypatch.setattr(S, "provider", lambda cfg=None: {"name": "x", "model": "m"})
    ep = EP + "\n**镜2｜img**：近景\n**motion**：static camera，她笑——她看向窗外很久很久\n"
    s = {"messages": [{"role": "user", "content": "【格式返修】ep03 镜2：…请输出 ep03 镜2 的完整 Markdown"}],
         "episodes": {"3": ep}}
    got = S.record_reply(s, "**镜2｜img**：特写\n**motion**：static camera，她笑——她低头看手里的杯子\n",
                         "", None, "stop", 0)
    assert got == [3] and "特写" in S.split_shots(s["episodes"]["3"])[1][2]
    assert S.split_shots(s["episodes"]["3"])[1][1] == S.split_shots(ep)[1][1]
    # 没点名集 / 镜号不在草稿里：不并入
    s2 = {"messages": [{"role": "user", "content": "改一下"}], "episodes": {"3": ep}}
    assert S.record_reply(s2, "**镜2｜img**：特写\n", "", None, "stop", 0) == [] and s2["episodes"]["3"] == ep
    s3 = {"messages": [{"role": "user", "content": "ep03"}], "episodes": {"3": ep}}
    assert S.record_reply(s3, "**镜9｜img**：特写\n", "", None, "stop", 0) == [] and s3["episodes"]["3"] == ep


def test_repair_uses_strict_block_hints():
    """fredw-92/D2：关口 warn、严格 block 的条目另列为 block 级提示；/repair 在关口没有返修时用严格返修原文"""
    i_warn = {"rule_id": "QW-C3", "field": "motion", "detail": "x", "level": "warn"}
    assert S._hint_new({**i_warn, "level": "block"}, {S._ikey(i_warn): "warn"})
    assert not S._hint_new(i_warn, {S._ikey(i_warn): "warn"})
    s = {"validation": {"episodes": [{"number": 3, "repair": "", "hint_repair": "",
                                      "shots": [{"repair": "", "hint_repair": "【格式返修】ep03 镜6"},
                                                {"repair": "", "hint_repair": ""}]}]}}
    msg = S.repair_message(s)
    assert "ep03 镜6" in msg and "请重新输出完整的 ep03" in msg


def test_registry_inherited_into_header(tmp_path, monkeypatch):
    """fredw-92 2026-10-31 定：人物表 / 场景表全剧一份、逐集继承——登记来源草稿的表原样并进全局头（全剧表），先登记为准"""
    monkeypatch.setattr(S, "PRODUCTION_SCRIPT", tmp_path / "none.json")
    src = tmp_path / "src.md"
    src.write_text("## ep03《占位》\n**剧情**：占位\n\n**本集人物表**：\n| 角色 | 角色id | 中文外貌句 | EN外貌短语 | VOICE声线短语 |\n"
                   "|---|---|---|---|---|\n| 甲 | ch_a | 系统锁 | placeholder identity A | placeholder voice A |\n\n"
                   "**本集场景表**：\n| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |\n|---|---|---|---|---|---|\n"
                   "| sk_x | 名X | 空X | 时X | 光X | 陈X |\n\n---\n", encoding="utf-8")
    chars, scenes, used = S.registry_tables({"from": [str(src)]})
    assert [(c["name"], c["en"], c["voice"]) for c in chars] == [("甲", "placeholder identity A", "placeholder voice A")]
    assert [e["scene_id"] for e in scenes] == ["sk_x"] and used == [str(src)]
    head, _ = S.script_header(registry={"from": [str(src)]})
    assert "**全剧人物表**：" in head and "| 甲 | ch_a | 系统锁 | placeholder identity A | placeholder voice A |" in head
    assert "| sk_x | 名X | 空X | 时X | 光X | 陈X |" in head
    out = S.compact_header(head)
    assert "placeholder voice A" in out and "| sk_x |" in out
    assert S.script_header(registry={})[0] == S.script_header(registry={"from": []})[0]   # 不给来源 = 原全局头
    with pytest.raises(S.ChatError):
        S.resolve_draft(str(tmp_path / "missing.md"))
