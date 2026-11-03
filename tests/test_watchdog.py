"""W19 WATCHDOG-CODE：tools/master/watchdog.py 九条规则各一个正例一个反例 + 一轮的登记 / 去重 / 早报 / ⑧ / resident 接入。
全部在临时目录里造数据；真实部件（sop_gate / v1_leak / git / orca / master_check）用 Ctx 方法替换，不读写真实 data/。"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOW = time.mktime(time.strptime("2026-11-03 12:00:00", "%Y-%m-%d %H:%M:%S"))


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


W = _load("watchdog_t", "tools/master/watchdog.py")


def _w(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _root(tmp: Path) -> Path:
    _w(tmp / "config/pipeline/runs.json", {"primary": "v2", "runs": {"v2": {"status": "preparing"}, "v1": {"status": "archived"}}})
    _w(tmp / "config/pipeline/run.json", {"run_id": "v2"})
    _w(tmp / "data/factory/autoflow_resident.json", {"pid": 1, "t": NOW - 30})
    _w(tmp / "data/pipeline/asset_jobs/worker.json", {"at": _iso(NOW - 30)})
    _w(tmp / "data/producer/runs/v2/heartbeat.json", {"t": NOW - 20, "run": "v2"})
    (tmp / "config/prompts").mkdir(parents=True, exist_ok=True)
    return tmp


def _ctx(tmp: Path, **over) -> W.Ctx:
    c = W.Ctx(tmp, NOW, dict(W.DEFAULT_CFG))
    c.sop_status = lambda run: [{"episode": 1, "stage": "提示词", "why": "", "passed": ["剧本", "导入闸门", "资产就绪"]}]
    c.has_images = lambda run, ep: False
    c.has_videos = lambda run, ep: False
    c.v1_vocab = lambda run: (["林晚", "gu_chen"], [])
    c.orca_live = lambda: (0, "fake")
    c.git_dirty = lambda: 10
    c.last_cut = lambda: (NOW - 3600, "abc sv-x")
    c.switch_bad = lambda: []
    for k, v in over.items():
        setattr(c, k, v)
    return c


def _rules(c, n):
    return [f for f in dict(W.RULES)[n](c)]


# ---------------------------------------------------------------- 规则 1
def _log(tmp, rows):
    _w(tmp / "data/pipeline/runs/v2/autoflow.log", "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def test_r1_same_error_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    err = "HeaderMissing('旧剧内容：顾沉')"
    rows = []
    for i in range(3):
        rows += [{"at": _iso(NOW - 3600 + 30 * i), "episode": 2, "verdict": None, "note": "开始"},
                 {"at": _iso(NOW - 3600 + 30 * i + 5), "episode": 2, "verdict": "error", "note": err}]
    _log(tmp, rows)
    f = _rules(_ctx(tmp), 1)
    assert len(f) == 1 and f[0]["episode"] == 2 and f[0]["blocking"] and "autoflow.log" in f[0]["what"] and "连续 3 次" in f[0]["what"]
    # 反例：之后有了别的进展（已被处理）；或停下还不到 30 分钟
    _log(tmp, rows + [{"at": _iso(NOW - 600), "episode": 2, "verdict": "awaiting_writer", "note": "等写手"}])
    assert _rules(_ctx(tmp), 1) == []
    _log(tmp, [dict(r, at=_iso(NOW - 300)) for r in rows])
    assert _rules(_ctx(tmp), 1) == []


# ---------------------------------------------------------------- 规则 2
def _pkt(tmp, name, step, t, done=False):
    out = f"data/pipeline/runs/v2/writer_out/{name}.md"
    _w(tmp / "data/pipeline/runs/v2/writer_tasks" / f"{name}.json",
       {"step": step, "episode": 1, "created_at": _iso(t), "status": "open", "user": "写稿",
        "output": {"path": out, "done_marker": out + ".done"}})
    if done:
        _w(tmp / (out + ".done"), "")


def test_r2_idle_packets_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    _pkt(tmp, "P4_ep01_a2", "P4_ep01", NOW - 300)
    _pkt(tmp, "P4_ep01_a3", "P4_ep01", NOW - 270)
    _pkt(tmp, "P4_ep01_a4", "P4_ep01", NOW - 240)
    f = _rules(_ctx(tmp), 2)
    assert len(f) == 1 and "3 个都没交稿" in f[0]["what"] and "P4_ep01_a2.json" in f[0]["what"]


def test_r2_negative_delivered_or_far_apart(tmp_path):
    tmp = _root(tmp_path)
    _pkt(tmp, "patch_ep02_a1", "patch_ep02", NOW - 300, done=True)     # 交了稿再出下一个 = 正常
    _pkt(tmp, "patch_ep02_a2", "patch_ep02", NOW - 200)
    _pkt(tmp, "P4_ep01_a1", "P4_ep01", NOW - 7200)                    # 隔了 2 小时
    _pkt(tmp, "P4_ep01_a2", "P4_ep01", NOW - 60)
    assert _rules(_ctx(tmp), 2) == []


# ---------------------------------------------------------------- 规则 3
def test_r3_heartbeats_positive(tmp_path):
    tmp = _root(tmp_path)
    _w(tmp / "data/factory/autoflow_resident.json", {"pid": 1, "t": NOW - 1800})
    (tmp / "data/producer/runs/v2/heartbeat.json").unlink()
    c = _ctx(tmp, sop_status=lambda run: [{"episode": 1, "stage": "出图", "why": "0/11 镜有首帧", "passed": []}])
    f = _rules(c, 3)
    keys = {x["key"] for x in f}
    assert "r3:resident" in keys and "r3:producer:v2:gpu_idle" in keys
    p0 = next(x for x in f if x["p0"])
    assert "GPU 空转" in p0["what"] and "heartbeat.json" in p0["what"]


def test_r3_heartbeats_negative(tmp_path):
    tmp = _root(tmp_path)
    assert _rules(_ctx(tmp), 3) == []                                  # 都新鲜
    (tmp / "data/producer/runs/v2/heartbeat.json").unlink()
    assert _rules(_ctx(tmp), 3) == []                                  # producer 不在，但阶段还没到出图 → 不判 GPU 空转


# ---------------------------------------------------------------- 规则 4
def test_r4_jump_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    f = _rules(_ctx(tmp, has_images=lambda r, e: True), 4)
    assert len(f) == 1 and "抢跑" in f[0]["what"] and "提示词" in f[0]["what"]
    ok = [{"episode": 1, "stage": "出图检测", "why": "", "passed": ["剧本", "导入闸门", "资产就绪", "提示词", "出图"]}]
    assert _rules(_ctx(tmp, has_images=lambda r, e: True, sop_status=lambda run: ok), 4) == []
    f = _rules(_ctx(tmp, has_videos=lambda r, e: True, sop_status=lambda run: ok), 4)
    assert len(f) == 1 and "视频片段" in f[0]["what"]


# ---------------------------------------------------------------- 规则 5
def test_r5_v1_leak_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    _w(tmp / "config/prompts/writer.md", "反应镜：林晚抬眼")
    _pkt(tmp, "P4_ep01_a1", "P4_ep01", NOW - 60)
    f = _rules(_ctx(tmp), 5)
    assert len(f) == 1 and "config/prompts/writer.md" in f[0]["what"] and "林晚" in f[0]["what"]
    _w(tmp / "config/prompts/writer.md", "反应镜：女主抬眼，Leica 锐利")              # 画风词不在词表（c.v1_vocab 不含 style）
    _w(tmp / "data/pipeline/runs/v2/writer_tasks/P4_ep01_a0.json",
       {"step": "P4_ep01", "created_at": _iso(NOW - 99999), "user": "gu_chen",          # 已交稿的旧包不扫
        "output": {"done_marker": "data/pipeline/runs/v2/writer_out/a0.done"}})
    _w(tmp / "data/pipeline/runs/v2/writer_out/a0.done", "")
    assert _rules(_ctx(tmp), 5) == []


def test_r5_real_vocab_excludes_style():
    """真实词表口径（只读）：不含 run_style v1_style_phrases 里的画风词"""
    c = W.Ctx(ROOT, NOW)
    words, _ = c.v1_vocab("series10_v2")
    rs = json.loads((ROOT / "config/compile/run_style.json").read_text(encoding="utf-8")).get("v1_style_phrases") or []
    props = json.loads((ROOT / "config/v1_guard.json").read_text(encoding="utf-8")).get("props") or []
    assert words and not (set(rs) - set(props)) & set(words)


# ---------------------------------------------------------------- 规则 6
def test_r6_agents_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    _w(tmp / "data/factory/agent_dispatcher/state.json", {"requests": {"a": {"running": {"pid": 1}}, "b": {"running": None}}})
    f = _rules(_ctx(tmp, orca_live=lambda: (4, "fake")), 6)
    assert len(f) == 1 and "5 > 4" in f[0]["what"]
    assert _rules(_ctx(tmp, orca_live=lambda: (3, "fake")), 6) == []
    assert _rules(_ctx(tmp, orca_live=lambda: (None, "不可见")), 6) == []


def test_r6_orca_snapshot(tmp_path):
    tmp = _root(tmp_path)
    _w(tmp / "data/master/orca_workers.json", {"at": _iso(NOW - 60), "live": 3})
    c = W.Ctx(tmp, NOW, dict(W.DEFAULT_CFG, orca_cmds=[]))
    assert c.orca_live()[0] == 3
    _w(tmp / "data/master/orca_workers.json", {"at": _iso(NOW - 7200), "live": 3})      # 陈旧快照不认
    assert c.orca_live()[0] is None


# ---------------------------------------------------------------- 规则 7
def _issues(tmp, rows):
    _w(tmp / "data/pipeline/issues.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def test_r7_stale_blocking_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    old = time.strftime("%F %T", time.localtime(NOW - 3 * 3600))
    new = time.strftime("%F %T", time.localtime(NOW - 600))
    _issues(tmp, [{"id": "ISS-A", "event": "open", "time": old, "blocking": True, "who": "X", "status": "open"},
                  {"id": "ISS-B", "event": "open", "time": old, "blocking": True, "who": "X", "status": "open"},
                  {"id": "ISS-B", "event": "close", "time": new},
                  {"id": "ISS-C", "event": "open", "time": old, "blocking": False, "who": "X", "status": "open"},
                  {"id": "ISS-D", "event": "open", "time": new, "blocking": True, "who": "X", "status": "open"},
                  {"id": "ISS-E", "event": "open", "time": old, "blocking": True, "who": "X", "status": "open"},
                  {"id": "ISS-E", "event": "note", "time": new}])
    rows, ids = W.r7_stale_blocking(_ctx(tmp), {})
    assert ids == ["ISS-A"]
    assert W.r7_stale_blocking(_ctx(tmp), {"escalated": {"ISS-A": NOW - 60}})[1] == []     # 升级过的不再升


# ---------------------------------------------------------------- 规则 8
def test_r8_switches_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    bad = [{"name": "sop_gate.enabled", "value": False, "ok": False, "op": "eq", "want": True, "why": "C-16"}]
    f = _rules(_ctx(tmp, switch_bad=lambda: bad), 8)
    assert len(f) == 1 and f[0]["p0"] and f[0]["blocking"] and "sop_gate.enabled=False" in f[0]["what"]
    assert _rules(_ctx(tmp), 8) == []


def test_r8_real_switch_rows_readonly():
    MC = _load("master_check_wdt", "tools/master/master_check.py")
    assert isinstance(MC.switch_rows(ROOT), list)


# ---------------------------------------------------------------- 规则 9
def test_r9_release_positive_and_negative(tmp_path):
    tmp = _root(tmp_path)
    f = _rules(_ctx(tmp, git_dirty=lambda: 200, last_cut=lambda: (NOW - 30 * 3600, "abc sv-1")), 9)
    assert len(f) == 1 and "200 个文件未提交" in f[0]["what"]
    assert _rules(_ctx(tmp, git_dirty=lambda: 200, last_cut=lambda: (NOW - 3600, "abc")), 9) == []
    assert _rules(_ctx(tmp, git_dirty=lambda: 100, last_cut=lambda: (NOW - 30 * 3600, "abc")), 9) == []


# ---------------------------------------------------------------- 一轮：登记 / 去重 / ⏫ / 早报 / 无变化
def test_run_registers_dedupes_and_writes_timeline(tmp_path):
    tmp = _root(tmp_path)
    live = _w(tmp / "docs/master/V2_LIVE.md", "# V2_LIVE\n旧行\n")
    _issues(tmp, [{"id": "ISS-OLD", "event": "open", "time": time.strftime("%F %T", time.localtime(NOW - 5 * 3600)),
                   "blocking": True, "who": "X", "status": "open"}])
    got = []

    def rep(**kw):
        got.append(kw)
        rec = {"id": f"ISS-N{len(got)}", "event": "open", "time": time.strftime("%F %T", time.localtime(NOW)), "status": "open", **kw}
        with open(tmp / "data/pipeline/issues.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    c = _ctx(tmp, git_dirty=lambda: 300, last_cut=lambda: (None, ""))
    d = W.run(tmp, NOW, dry=True, ctx=c, reporter=rep, live=live)
    assert d["findings"] == 1 and not got and not (tmp / "data/master/watchdog_last.json").exists()       # dry：不写
    r = W.run(tmp, NOW, ctx=c, reporter=rep, live=live)
    assert r["registered"] == ["ISS-N1"] and got[0]["who"] == "WATCHDOG-CODE" and "〔wd:r9:" in got[0]["what"]
    assert r["escalate"] == ["ISS-OLD"] and "⏫" in live.read_text(encoding="utf-8").splitlines()[1]
    morning = tmp / f"docs/overnight/morning_{time.strftime('%Y%m%d', time.localtime(NOW))}.md"
    assert "规则9×1" in morning.read_text(encoding="utf-8")
    last = json.loads((tmp / "data/master/watchdog_last.json").read_text(encoding="utf-8"))
    assert last["registered"] == ["ISS-N1"] and last["by_rule"] == {"9": 1}
    # 第二轮：同键卡点还开着 → 不重登；ISS-OLD 升级过 → 不再升；结论没变 → “无变化”
    for rel, k, v in (("data/factory/autoflow_resident.json", "t", NOW + 1790), ("data/pipeline/asset_jobs/worker.json", "at", _iso(NOW + 1790)),
                      ("data/producer/runs/v2/heartbeat.json", "t", NOW + 1790)):
        _w(tmp / rel, {k: v})                                          # 心跳照常在跳（只看去重）
    c2 = _ctx(tmp, git_dirty=lambda: 300, last_cut=lambda: (None, ""))
    c2.now = NOW + 1800
    r2 = W.run(tmp, NOW + 1800, ctx=c2, reporter=rep, live=live)
    assert r2["registered"] == [] and r2["held"] and r2["escalate"] == [] and len(got) == 1
    assert morning.read_text(encoding="utf-8").rstrip().endswith("看门狗：无变化")
    assert W.due(tmp, NOW + 1800 + 60) > 0 and W.due(tmp, NOW + 1800 + 1801) <= 0


def test_run_rule_error_does_not_break_round(tmp_path):
    tmp = _root(tmp_path)

    def boom(run):
        raise RuntimeError("sop_gate 坏了")
    c = _ctx(tmp, sop_status=boom)
    r = W.run(tmp, NOW, dry=True, ctx=c)
    assert any("规则4" in e for e in r["errors"]) and "findings" in r


# ---------------------------------------------------------------- master_check ⑧ / resident 接入
def test_master_check_section8(tmp_path):
    MC = _load("master_check_wd8", "tools/master/master_check.py")
    assert "还没跑过" in MC.sec_watchdog(tmp_path, NOW)[0]
    _w(tmp_path / "data/master/watchdog_last.json", {"t": NOW - 120, "by_rule": {"3": 1}, "registered": ["ISS-1"], "escalate": [],
                                                      "held": 2, "errors": ["规则5：x"]})
    s = MC.sec_watchdog(tmp_path, NOW)
    assert "规则3×1" in s[0] and "ISS-1" in s[0] and not s[0].startswith("  ⚠") and "规则5" in s[1]
    assert MC.sec_watchdog(tmp_path, NOW + 7200)[0].startswith("  ⚠")


def test_resident_watchdog_tick_and_streak(tmp_path, monkeypatch):
    RS = _load("autoflow_resident_wdt", "tools/factory/autoflow_resident.py")
    monkeypatch.setattr(RS, "life", lambda *a, **k: None)
    monkeypatch.setattr(RS, "_write_hb", lambda rec: hbs.append(rec))
    hbs, calls = [], []

    class WD:
        @staticmethod
        def due(now=None):
            return 0

        @staticmethod
        def run(now=None):
            calls.append(now)
            return {"findings": 2, "registered": ["ISS-9"], "escalate": [], "errors": []}
    r = RS.watchdog_tick(wd=WD, now=1000.0)
    assert r["ran"] and r["registered"] == ["ISS-9"]
    assert RS.watchdog_tick(wd=WD, now=1100.0) == {} and len(calls) == 1          # 没到 30 分钟不再跑

    class Bad:
        @staticmethod
        def due(now=None):
            return 0

        @staticmethod
        def run(now=None):
            raise ValueError("坏")
    RS._WD["next"] = 0
    assert RS.watchdog_tick(wd=Bad, now=5000.0)["phase"] == "run"
    reported = []
    ticks = iter([{"error": "ValueError('坏')", "phase": "run"}] * 3 + [{"ran": True, "findings": 0}])
    tick_fn = lambda procs: {"runs": ["v2"], "started": [], "assets": {}, "watchdog": next(ticks)}
    RS.run_loop(1, False, tick_fn=tick_fn, sleep=lambda s: None, max_ticks=4,
                reporter=lambda **kw: reported.append(kw) or {"id": "ISS-WD"})
    assert len(reported) == 1 and reported[0]["blocking"] and "看门狗" in reported[0]["what"]
    assert hbs[2]["watchdog_issue"] == "ISS-WD" and "watchdog_error" not in hbs[3] and hbs[3]["watchdog"]["findings"] == 0
