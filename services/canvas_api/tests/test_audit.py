"""逐镜 H3 / 审计数据、h3_edit（只写 edits.json + lint，不渲染）、豁免请求（写 edits.json，不写 status.json）。"""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_canvas.app import create_app
from ns_canvas.config import RootCfg, Settings

P = "/api/gpu3"
REPO = Path(__file__).resolve().parents[3]
REAL_LINT = next((p for p in (REPO / "packages/schema/ns_schema/h3_lint.py",
                              Path("/root/claude-kimi-ns-studio-v1/nsfs_mirror/packages/schema/ns_schema/h3_lint.py"))
                  if p.exists()), None)
sha = lambda t: hashlib.sha256(t.encode()).hexdigest()

STUB_LINT = '''
def lint_h3(prompt, frames=None, intimate=False, **kw):
    return [{"rule_id": "H3-A7", "ok": "中" not in prompt, "level": "block", "detail": "cjk"},
            {"rule_id": "H3-A12", "ok": len(prompt) < 20, "level": "warn", "detail": "len"},
            {"rule_id": "P-B1", "ok": frames == 243, "level": "block", "detail": str(frames)}]
def lint_ok(results, overrides=frozenset()):
    return all(r["ok"] or r["level"] != "block" or r["rule_id"] in overrides for r in results)
def failed_rules(results, overrides=frozenset(), level="block"):
    return [r["rule_id"] for r in results if not r["ok"] and r["level"] == level and r["rule_id"] not in overrides]
'''
RULES = """# 逐镜审计规则编号表
| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| H3-A1 | 对齐句 | 正则 | block | §9A.1 #1 |
| H3-A5 | 不写否定句 | 正则 | block | §9A.1 #8 |
| H3-A7 | 英文正文 | CJK | block | §9A.1 #7 |
| H3-A99 | 旧规则（作废） | — | — | — |
| P-B1 | 帧数 | 计算 | block | §6 |
"""
H3 = "How the reference pictures align…\n\nintegrated_multimodal_description: [Shot 1] Live-action…"


@pytest.fixture
def env(tmp_path: Path):
    base = tmp_path / "data" / "renders_gpu3"
    def shot(n, status=None, compiled=None, takes=None):
        d = base / "ep01" / f"S{n}"
        d.mkdir(parents=True)
        if status is not None:
            (d / "status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        if compiled is not None:
            (d / "compiled.json").write_text(json.dumps(compiled, ensure_ascii=False), encoding="utf-8")
        if takes is not None:
            (d / "takes.json").write_text(json.dumps(takes, ensure_ascii=False), encoding="utf-8")
        return d
    s1 = shot(1, status={"state": "audited", "owner": "weita-series", "scene_id": "SC-01", "segment_id": "G1",
                         "continuity": {"from": None}, "bible_version": "vb/3", "video": {"frames": 243},
                         "audit": {"version": "shot_audit/1", "verdict": "fail", "prompt_sha": sha(H3),
                                   "failures": [{"rule_id": "H3-A5", "sop_ref": "§9A.1 #8", "detail": "not"},
                                                {"rule_id": "H3-A1", "sop_ref": "§9A.1 #1", "detail": "x"}],
                                   "warnings": [{"rule_id": "H3-A12"}], "not_checked": ["H3-A9"],
                                   "overrides": [{"rule_id": "P-B1", "owner_quote": "这镜就要 8 秒", "by": "owner"}],
                                   "invalid_overrides": [], "h3_edit": None}},
              compiled={"h3_prompt": H3, "h3_prompt_sha256": sha(H3), "h3_prompt_source": "compiler", "h3_prompt_base_sha256": "b0"},
              takes={"takes": [{"n": 1, "stage": "video", "file": "renders_gpu3/ep01/S1/takes/video_001.mp4", "prompt": "old"},
                               {"n": 2, "stage": "video", "file": "renders_gpu3/ep01/S1/takes/video_002.mp4", "prompt": H3,
                                "reference": "refs/REF-LW-01.face.png", "last_target": "renders_gpu3/ep01/S1/last_target.png",
                                "frames": 243}], "active": {"video": 2}})
    shot(2, status={"state": "blocked", "blocked": "explicit_content_not_supported"})
    shot(3, status={"audit": {"verdict": "pass", "prompt_sha": sha(H3), "failures": []}},
         compiled={"h3_prompt": H3, "h3_prompt_sha256": sha(H3)})
    shot(4, status={"audit": {"verdict": "fail", "failures": [{"rule_id": "H3-A5"}, {"rule_id": "H3-D3"}]}})
    shot(5)
    lint = tmp_path / "stub_lint.py"
    lint.write_text(STUB_LINT, encoding="utf-8")
    rules = tmp_path / "rule_ids.md"
    rules.write_text(RULES, encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"episodes": [{"number": 1, "shots": [{"index": i} for i in range(1, 7)]}]}))
    s = Settings(queue_dir=base, roots=[RootCfg("renders_gpu3", "takes", base)], cache_dir=tmp_path / "c",
                 script_json=script, renders_base=base, h3_lint=lint, rule_ids=rules)
    return TestClient(create_app(s)), base, s


def test_shot_payload(env):
    c, _, _ = env
    for url in (f"{P}/projects/weita/shots/ep01-S1", f"{P}/shots/ep01-S1"):
        d = c.get(url).json()
        a = d["audit"]
        assert a["verdict"] == "fail" and a["prompt_sha"] == sha(H3) and a["not_checked"] == ["H3-A9"]
        assert [f["rule_id"] for f in a["failures"]] == ["H3-A5", "H3-A1"] and a["overrides"][0]["rule_id"] == "P-B1"
        assert a["override_requests"] == []
        assert d["h3"]["h3_prompt"] == H3 and d["h3"]["h3_prompt_source"] == "compiler" and d["h3"]["effective_sha256"] == sha(H3)
        assert d["shot_state"] == {"state": "audited", "blocked": None, "owner": "weita-series", "scene_id": "SC-01",
                                   "segment_id": "G1", "continuity": {"from": None}, "bible_version": "vb/3"}
        v = d["active_video"]
        assert v["n"] == 2 and v["prompt"] == H3 and v["prompt_sha256"] == sha(H3)
        assert v["reference"] == "refs/REF-LW-01.face.png" and v["last_target"].endswith("last_target.png")
        assert d["video_gate"]["video_ok"] is False                     # verdict = fail
    g3 = c.get(f"{P}/projects/weita/shots/ep01-S3").json()["video_gate"]
    assert g3["video_ok"] is True
    assert c.get(f"{P}/projects/weita/shots/ep01-S2").json()["shot_state"]["blocked"] == "explicit_content_not_supported"
    assert c.get(f"{P}/projects/weita/shots/ep01-S5").json()["audit"] is None


def test_episode_summary(env):
    c, _, _ = env
    d = c.get(f"{P}/projects/weita/episodes/1").json()
    assert [x["shot"] for x in d["shots"]] == [f"ep01-S{i}" for i in range(1, 7)]
    s = d["audit_summary"]
    assert (s["pass"], s["fail"], s["blocked"], s["none"]) == (1, 2, 1, 1)   # S6 没有目录，不计
    assert s["top_failures"][0] == {"rule_id": "H3-A5", "count": 2} and len(s["top_failures"]) == 3


def test_h3_edit(env):
    c, base, _ = env
    d = base / "ep01" / "S1"
    st_before = (d / "status.json").read_text(encoding="utf-8")
    assert c.post(f"{P}/projects/weita/shots/ep01-S1/h3_edit", json={"text": "x", "by": "fredw-d9"}).status_code == 403
    assert c.post(f"{P}/projects/weita/shots/ep01-S1/h3_edit", json={"text": " ", "by": "owner"}).status_code == 422
    assert c.post(f"{P}/projects/weita/shots/ep01-S1/h3_edit", json={"text": "x", "by": "owner", "base_sha": "stale"}).status_code == 409
    r = c.post(f"{P}/projects/weita/shots/ep01-S1/h3_edit", json={"text": "含中文的提示词", "by": "owner", "base_sha": sha(H3)}).json()
    assert r["rendered"] is False and r["saved"]["sha256"] == sha("含中文的提示词")
    assert r["lint"]["ok"] is False and r["lint"]["failed"] == ["H3-A7"]        # P-B1 有豁免，帧数 243 取自 status.video
    assert r["lint"]["frames"] == 243
    e = json.loads((d / "edits.json").read_text(encoding="utf-8"))
    assert e["h3_prompt_override"]["text"] == "含中文的提示词" and e["h3_prompt_override"]["base_sha"] == sha(H3)
    # 再改：base_sha 要用新的 effective_sha256
    s = c.get(f"{P}/projects/weita/shots/ep01-S1").json()
    assert s["h3"]["effective_sha256"] == sha("含中文的提示词") and s["video_gate"]["video_ok"] is False
    r2 = c.post(f"{P}/projects/weita/shots/ep01-S1/h3_edit", json={"text": "ok", "by": "owner", "base_sha": sha("含中文的提示词")}).json()
    assert r2["lint"]["ok"] is True and r2["lint"]["warnings"] == []
    hist = (d / "edits_history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(hist) == 2 and json.loads(hist[0])["field"] == "h3_prompt_override"
    assert (d / "status.json").read_text(encoding="utf-8") == st_before        # 不碰 status.json
    assert not list(base.glob("rerender_queue.jsonl"))                          # 不排渲染
    assert c.post(f"{P}/projects/weita/shots/ep01-S6/h3_edit", json={"text": "x", "by": "owner"}).status_code == 404


def test_override_requests(env):
    c, base, _ = env
    d = base / "ep01" / "S4"
    st_before = (d / "status.json").read_text(encoding="utf-8")
    u = f"{P}/projects/weita/shots/ep01-S4/override"
    assert c.post(u, json={"rule_id": "H3-ZZ1", "owner_quote": "可以", "by": "owner"}).status_code == 422
    assert c.post(u, json={"rule_id": "H3-A99", "owner_quote": "可以", "by": "owner"}).status_code == 422   # 作废
    assert c.post(u, json={"rule_id": "H3-A5", "owner_quote": "  ", "by": "owner"}).status_code == 422
    assert c.post(u, json={"rule_id": "H3-A5", "owner_quote": "可以", "by": "fredw-d9"}).status_code == 403
    r = c.post(u, json={"rule_id": "H3-A5", "owner_quote": "这句否定是台词需要，保留", "by": "owner"}).json()
    assert r["request"]["rule_id"] == "H3-A5" and r["request"]["by"] == "owner" and r["request"]["at"]
    c.post(u, json={"rule_id": "H3-A1", "owner_quote": "对齐句我改过了", "by": "owner"})
    e = json.loads((d / "edits.json").read_text(encoding="utf-8"))
    assert [x["rule_id"] for x in e["audit_override_requests"]] == ["H3-A5", "H3-A1"]
    assert (d / "status.json").read_text(encoding="utf-8") == st_before        # 不写 status.json
    s = c.get(f"{P}/projects/weita/shots/ep01-S4").json()
    assert [x["rule_id"] for x in s["audit"]["override_requests"]] == ["H3-A5", "H3-A1"]
    s5 = c.post(f"{P}/projects/weita/shots/ep01-S5/override", json={"rule_id": "P-B1", "owner_quote": "行", "by": "owner"})
    assert s5.status_code == 200
    assert c.get(f"{P}/projects/weita/shots/ep01-S5").json()["audit"] == {"override_requests": [s5.json()["request"]]}


@pytest.mark.skipif(REAL_LINT is None, reason="没有同步过来的 ns_schema/h3_lint.py")
def test_real_h3_lint(env):
    c, _, s = env
    s.h3_lint = REAL_LINT
    r = c.post(f"{P}/projects/weita/shots/ep01-S3/h3_edit", json={"text": "这不是合格的 H3 提示词", "by": "owner"}).json()
    assert r["lint"]["ok"] is False and "H3-A1" in r["lint"]["failed"]
    assert all({"rule_id", "ok", "level"} <= set(x) for x in r["lint"]["results"])
