"""BRAIN-FW：tools/brain/brain_api.py——离线模式（不需要 anthropic / 不联网）、提示词含规则、响应解析（含 refusal）、一轮闭环（fake ask）、
预算封顶、strict 工具定义、凭据缺失判断。全 fake。"""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/brain"))


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


B = _load("brain_api_t", "tools/brain/brain_api.py")
TT = _load("test_brain_telemetry_helpers", "tests/test_brain_telemetry.py")
TA = _load("test_brain_actions_helpers", "tests/test_brain_actions.py")
NOW = TT.NOW


def _root(tmp_path):
    TT._root(tmp_path)
    (tmp_path / "tools/brain").mkdir(parents=True)
    (tmp_path / "tools/brain/prompt.md").write_text((ROOT / "tools/brain/prompt.md").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "config/brain").mkdir(parents=True)
    (tmp_path / "config/brain/brain.json").write_text(json.dumps({"enabled": False, "dry_run": True, "model": "claude-fable-5-1", "interval_s": 180,
                                                                  "budget_usd_day": 1.0}), encoding="utf-8")
    return tmp_path


def msg(blocks, stop="end_turn", usage=None, refusal=None):
    u = NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=800, cache_creation_input_tokens=0, **(usage or {}))
    return NS(content=blocks, stop_reason=stop, usage=u, model="claude-fable-5-1",
              stop_details=NS(category=refusal, explanation="x") if refusal else None)


def test_prompt_contains_rules_and_boundaries():
    p = (ROOT / "tools/brain/prompt.md").read_text(encoding="utf-8")
    for must in ("gpu33:2", "50 分钟", "L-205", "L-202", "L-207", "L-204", "永不删除", "成人", "lane_roles", "no_action", "reason", "expected_effect", "check_after_s"):
        assert must in p, must
    sb = B.system_blocks(ROOT)
    assert sb[-1]["cache_control"] == {"type": "ephemeral"} and "producer_retry" in sb[-1]["text"] and "动作目录" in sb[-1]["text"]
    assert "cache_control" not in sb[0]
    assert B.system_blocks(ROOT) == sb                      # 稳定前缀（可缓存）


def test_offline_mode_writes_next_prompt_without_api(tmp_path, monkeypatch):
    root = _root(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", None)       # 离线模式不得 import anthropic
    env = TT.FakeEnv(root)
    p = B.offline(root, env)
    assert p == root / "data/brain/next_prompt.md" and p.is_file()
    txt = p.read_text(encoding="utf-8")
    snap = json.loads((root / "data/brain/snapshot.json").read_text(encoding="utf-8"))
    assert "永不碰 gpu33:2" in txt and "actions.py run" in txt and snap["hash"] in txt and '"schema": "nsfs.brain_snapshot/1"' in txt
    st = (root / "data/brain/STATUS.md").read_text(encoding="utf-8")
    assert "BRAIN 状态页" in st and "快照摘要" in st and "KPI" in st


def test_parse_response_actions_text_refusal():
    m = msg([NS(type="text", text="🟢 正常"), NS(type="tool_use", id="t1", name="producer_retry",
                                               input={"host": "gpu33", "obj": "first:ep02-S3", "reason": "r", "expected_effect": "e", "check_after_s": 300})])
    pr = B.parse_response(m)
    assert pr["actions"] == [{"kind": "producer_retry", "host": "gpu33", "obj": "first:ep02-S3", "reason": "r", "expected_effect": "e", "check_after_s": 300}]
    assert pr["text"] == "🟢 正常" and pr["usage"] == {"input": 1000, "output": 200, "cache_read": 800, "cache_write": 0}
    r = B.parse_response(msg([NS(type="tool_use", id="t", name="night_once", input={})], stop="refusal", refusal="cyber"))
    assert r["refusal"] == {"category": "cyber", "explanation": "x"} and r["actions"] == []
    assert B.usd(pr["usage"], B.DEFAULT_CFG["price_per_mtok"]) == round(1000 * 10 / 1e6 + 200 * 50 / 1e6 + 800 * 0.25 / 1e6, 4)


def test_cycle_closed_loop_dry_with_fake_ask(tmp_path):
    root = _root(tmp_path)
    cfg = B.load_cfg(root)
    env_t, env_a = TT.FakeEnv(root), TA.FakeEnv(root)
    seen = {}

    def ask(client, cfg_, snap, root_):
        seen["snap"] = snap
        return msg([NS(type="tool_use", id="1", name="producer_retry",
                       input={"host": "gpu33", "obj": "first:ep02-S3", "reason": "attention wait 14 min", "expected_effect": "running", "check_after_s": 300}),
                    NS(type="tool_use", id="2", name="producer_retry",
                       input={"host": "gpu36", "obj": "first:ep03-S5", "reason": "x", "expected_effect": "y", "check_after_s": 1}),
                    NS(type="text", text="🟡 一条重派")])

    r = B.cycle(cfg, client=None, env_t=env_t, env_a=env_a, root=root, ask_fn=ask)
    assert r["snapshot_hash"] == seen["snap"]["hash"] and r["n_actions"] == 2 and r["n_rejected"] == 1 and r["dry"] is True
    assert r["text"] == "🟡 一条重派" and r["usd"] > 0 and r["usd_day"] == r["usd"] and r["cache_read"] == 800
    assert env_a.remote_calls == []                                  # dry_run：没动手
    d = TA.decisions(root)
    assert d[0]["by"] == "BRAIN-API" and d[0]["snapshot_hash"] == r["snapshot_hash"] and "成人" in d[1]["result"]
    cyc = [json.loads(x) for x in (root / "data/brain/cycles.jsonl").read_text(encoding="utf-8").splitlines()]
    assert cyc[-1]["actions"][0]["kind"] == "producer_retry"
    st = (root / "data/brain/STATUS.md").read_text(encoding="utf-8")
    assert "producer_retry" in st and "attention wait 14 min" in st and "🟡 一条重派" in st
    # 再跑一轮：预算（1.0）没到顶继续；把预算压到 0 → 不调用
    cfg["budget_usd_day"] = 0.0
    r2 = B.cycle(cfg, client=None, env_t=env_t, env_a=env_a, root=root, ask_fn=ask)
    assert "预算" in r2["error"] and r2["n_actions"] == 0


def test_cycle_api_error_is_recorded_not_raised(tmp_path):
    root = _root(tmp_path)

    def boom(*a):
        raise RuntimeError("connection reset")

    r = B.cycle(B.load_cfg(root), None, TT.FakeEnv(root), TA.FakeEnv(root), root=root, ask_fn=boom)
    assert r["error"].startswith("API 失败 RuntimeError") and r["n_actions"] == 0
    assert (root / "data/brain/STATUS.md").is_file()


def test_ask_request_shape(monkeypatch):
    """stream(...) 的参数：fable 不传 thinking；tool_choice auto；strict 工具；system 带 cache_control；fallbacks default + beta 头"""
    calls = {}

    class FakeStream:
        def __init__(self, **kw):
            calls.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return msg([NS(type="text", text="ok")])

    client = NS(beta=NS(messages=NS(stream=lambda **kw: FakeStream(**kw))))
    cfg = dict(B.DEFAULT_CFG)
    m = B.ask(client, cfg, {"at": "x", "kpi": {}, "lanes": {}, "hosts": {}}, ROOT)
    assert m.content[0].text == "ok"
    assert calls["model"] == "claude-fable-5-1" and "thinking" not in calls and calls["tool_choice"] == {"type": "auto"}
    assert calls["output_config"] == {"effort": "high"} and calls["betas"] == [B.FALLBACK_BETA] and calls["fallbacks"] == "default"
    assert all(t["strict"] for t in calls["tools"]) and calls["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert calls["messages"][0]["role"] == "user" and "快照" in calls["messages"][0]["content"]


def test_credentials_present_false_when_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    import types
    fake = types.ModuleType("anthropic.lib.credentials._constants")
    fake._has_auto_discoverable_credentials = lambda: False
    monkeypatch.setitem(sys.modules, "anthropic.lib.credentials._constants", fake)
    assert B.credentials_present() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert B.credentials_present() is True


def test_loop_sleeps_when_disabled(monkeypatch):
    slept, logs = [], []
    import threading
    stop = threading.Event()

    def sleep(s):
        slept.append(s)
        stop.set()

    B.loop(cfg_fn=lambda: {"enabled": False, "interval_s": 180}, sleep=sleep, stop=stop, log=logs.append)
    assert slept and slept[0] >= 170 and logs == []
