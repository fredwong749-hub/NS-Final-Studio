"""W-SCORE（11-07 00:xx JST）：gpu36 producer 上 first:ep02-S10 take 3 / first:ep02-S11 take 1 从 11-06 22:02 起
rescore_dispatch → score_infra 循环 6–8 轮（error 全是 ""），退避到 1800–3600 s，S10 拿不到结论。

根因（gpu36 只读复现：缓存命中的提示词核对 pass；人数检测 URLError Errno 104 Connection reset by peer）：
  1. config/gen_contract.json Q10_accept.count_host = http://10.0.0.36:8893 是 gpu36 自己的内网入口（lan_proxy --allow 10.0.0.33），
     gpu36 上的 producer 连自己被拒 → Q10 count 永远 untested → tools/vqa/accept.apply 标 score_infra。
  2. accept.apply 只标 score_infra、不带原因 → producer 日志 error=""；还被当成“审图位没结论”触发 review_fallback，
     把看图挪回 gpu36 本机 8870（出图卡 GPU1 上、等不到空闲卡）→ 之后看图也超时（00:00 后 S11）。
修：anomaly._measure_http 把本机自己的内网入口改走 127.0.0.1；score_infra 永远带原因（infra_error）；只有看图没结论才推 review_fallback。
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/autopilot", "services/agent", "services/render_router", "packages/schema", "packages/qc", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))
import producer as PR  # noqa: E402
from tools.vqa import accept as VACC  # noqa: E402
from tools.vqa import anomaly as AN  # noqa: E402


# ------------------------------------------------------------------ 1. 本机内网入口 → 127.0.0.1
def test_self_loopback_rewrites_own_lan_ip_only():
    mine = {"10.0.0.36"}
    is_self = lambda ip: ip in mine  # noqa: E731
    assert AN.self_loopback("http://10.0.0.36:8893", is_self) == "http://127.0.0.1:8893"
    assert AN.self_loopback("http://10.0.0.36:8893/", is_self) == "http://127.0.0.1:8893/"
    assert AN.self_loopback("http://10.0.0.33:8893", is_self) == "http://10.0.0.33:8893"     # 别台（gpu33 → gpu36）照旧走内网入口
    assert AN.self_loopback("http://127.0.0.1:8893", is_self) == "http://127.0.0.1:8893"


def test_is_self_ip_real_socket():
    assert AN._is_self_ip("127.0.0.1") is True
    assert AN._is_self_ip("203.0.113.7") is False        # TEST-NET-3：不会在本机网卡上


def test_measure_http_uses_loopback_and_error_names_url(monkeypatch, tmp_path):
    import urllib.request
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.full_url)
        raise ConnectionResetError(104, "Connection reset by peer")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(AN, "_jpeg_b64", lambda p, side=1536: "")
    monkeypatch.setitem(AN._SELF_IP, "10.0.0.36", True)
    out = AN._measure_http({"x": tmp_path / "a.png"}, "http://10.0.0.36:8893", 8, {})
    assert seen == ["http://127.0.0.1:8893/measure"]
    assert "127.0.0.1:8893" in out["x"]["error"] and "ConnectionResetError" in out["x"]["error"]


# ------------------------------------------------------------------ 2. score_infra 永远带原因
def _lab_count_untested():
    return {"identity": {"status": "na"}, "outfit": {"status": "na", "skipped": "skipped_nonblocking"},
            "prompt": {"status": "pass"},
            "count": {"status": "untested", "infra": True,
                      "why": "检测器没跑成：常驻检测服务不可用：URLError: <urlopen error [Errno 104] Connection reset by peer>"},
            "ok": "untested"}


def test_q10_apply_count_untested_carries_infra_error():
    pf = {"ok": True, "blocking": [], "items": []}
    VACC.apply(pf, _lab_count_untested())
    assert pf["score_infra"] is True
    assert pf["infra_error"].startswith("Q10 未测 count：") and "Errno 104" in pf["infra_error"]
    assert PR.infra_error(pf).startswith("infra_error: Q10 未测 count")
    assert PR.infra_is_vlm(pf) is False                    # 人数检测出错 ≠ 审图位没结论


def test_q10_prompt_untested_is_vlm():
    lab = _lab_count_untested()
    lab["count"] = {"status": "pass"}
    lab["prompt"] = {"status": "untested", "why": "本地看图没跑成：看图未测：超时"}
    pf = {"ok": True, "blocking": [], "items": []}
    VACC.apply(pf, lab)
    assert "prompt：本地看图没跑成" in pf["infra_error"] and PR.infra_is_vlm(pf) is True


def test_qb_retry_carries_infra_error():
    from ns_agent.gen_contract import accept as GA
    pf = GA.apply({"ok": True, "items": []}, {"status": "retry", "reasons": ["没拿到结论（看图排队）"]})
    assert pf["score_infra"] and pf["accept_retry"] and "QB 共用验收 retry" in pf["infra_error"]
    pf2 = GA.apply({"ok": True, "items": []}, {"status": "retry", "reasons": []})
    assert pf2["infra_error"]


@pytest.mark.parametrize("pf", [
    {"score_infra": True},
    {"score_infra": True, "remote_error": "", "error": None},
    {"score_infra": True, "items": [{"id": "Q10", "status": "untested", "detail": "count untested（检测器没跑成）"}]},
    {"score_infra": True, "accept_retry": True},
])
def test_infra_error_never_empty(pf):
    e = PR.infra_error(pf)
    assert e and e.strip() and ":" in e                    # 类型前缀 + 内容


def test_producer_log_sites_use_infra_error():
    src = (ROOT / "tools" / "autopilot" / "producer.py").read_text(encoding="utf-8")
    assert src.count('"score_infra", obj=') == 3
    for line in [ln for ln in src.splitlines() if '"score_infra", obj=' in ln]:
        assert "infra_error(" in line, line
    assert 'error=str(pf.get("remote_error") or pf.get("error") or "")' not in src


# ------------------------------------------------------------------ 3. _rescore_one：人数检测出错不推 review_fallback，日志带原因
def test_rescore_one_count_infra_logs_reason_and_no_review_fallback(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    from ns_agent import frame_job as FJ
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True, exist_ok=True)
    paths.ledger.write_text(json.dumps({"first:ep02-S10": {"rescore_take": 3, "rescore_infra": 4}}), encoding="utf-8")
    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    pr._lr_cfg = {"enabled": True}
    monkeypatch.setattr(P, "find_shot", lambda s, sid: ("ep", "shot"))
    monkeypatch.setattr(P, "load_takes", lambda sid: {"takes": [{"stage": "image", "n": 3, "file": "x.png"}]})
    monkeypatch.setattr(UF, "project_for", lambda s: "proj")
    monkeypatch.setattr(FJ, "build_first", lambda *a, **k: {"cast": [], "asset_refs": {}})
    pr.script = lambda: types.SimpleNamespace(globals={})

    def fake_pf(*a, **k):
        pf = {"ok": True, "blocking": [], "items": []}
        VACC.apply(pf, _lab_count_untested())
        return pf
    pr.frames = types.SimpleNamespace(_postflight=fake_pf)
    calls = []
    pr.review_fallback = lambda ki, oid="": calls.append(ki)
    monkeypatch.delenv("VQA_REVIEW_FALLBACK", raising=False)
    pr._rescore_one({"id": "first:ep02-S10", "shot": "ep02-S10", "kind": "first"}, 3)
    evs = [json.loads(x) for x in paths.log.read_text(encoding="utf-8").splitlines() if x.strip()]
    si = [e for e in evs if e["ev"] == "score_infra"]
    assert si and "Q10 未测 count" in si[-1]["error"] and "Errno 104" in si[-1]["error"]
    assert calls == []                                      # 不再误判审图位不通 → 不把看图挪回出图卡
    assert pr.ledger()["first:ep02-S10"]["rescore_infra"] == 5
