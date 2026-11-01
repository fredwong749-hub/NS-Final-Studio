"""ARCH Autopilot：知识库校验 / 生成物最新 / 写作知识包接入 / 写作自检回路 / 审片 JSON / 全链路 dry-run（不出片、不调外部 API）。"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "services" / "recipes", ROOT / "tools" / "iterate_loop", ROOT / "tools" / "autopilot",
          ROOT / "tools" / "knowledge"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import compile as KC  # noqa: E402
import director as DR  # noqa: E402
import writer as WR  # noqa: E402


# ---- 知识库 ----
def test_knowledge_valid_consistent_and_generated_up_to_date():
    files, errs, ver = KC.build()
    assert errs == [], errs
    assert ver.startswith("kb-")
    stale = [str(p) for p, txt in files.items() if not p.exists() or p.read_text(encoding="utf-8") != txt]
    assert stale == [], f"生成物过期，运行 tools/knowledge/compile.py：{stale}"


def test_validate_catches_bad_entries():
    rules = KC.load_rules(KC.KB / "rules")
    bad = copy.deepcopy(rules[0])
    bad["id"] = "K-REN-999"
    bad["link"] = "P99-P100"
    bad["evidence"] = [{"src": "docs/nope.md"}]
    errs = KC.validate(rules + [bad])
    assert any("P99-P100" in e for e in errs) and any("nope.md" in e for e in errs)
    dup = copy.deepcopy(rules[0])
    assert any("重复" in e for e in KC.validate(rules + [dup]))
    wrong = copy.deepcopy(next(e for e in rules if any(t.get("kind") == "recipe" for t in e.get("targets") or [])))
    t = next(t for t in wrong["targets"] if t["kind"] == "recipe")
    t["value"] = "__not_this__"
    assert any("知识库写的是" in e for e in KC.consistency([wrong]))


def test_every_rule_has_link_and_loop_rules_generated():
    rules = KC.load_rules(KC.KB / "rules")
    assert all(e.get("link") for e in rules)
    import yaml
    gen = yaml.safe_load((ROOT / "tools" / "iterate_loop" / "rules.yaml").read_text(encoding="utf-8"))
    loop_ids = [e["loop"]["rule_id"] for e in rules if e["domain"] == "loop"]
    assert [r["id"] for r in gen["rules"]] == loop_ids and all(r.get("kid") for r in gen["rules"])
    assert gen["kb_version"].startswith("kb-")


def test_writer_pack_loaded_by_writer_model():
    from ns_api import script_chat as SC
    cfg = SC.load_config()
    assert "config/recipes/writer_knowledge.md" in cfg["system_parts"]
    system, parts = SC.build_system_prompt(cfg, context=None, appendix_budget=None)
    assert "writer_knowledge_version: kb-" in system
    assert "系统知识包" in system and "[K-PRM-002]" in system
    assert "偏慢" not in (ROOT / "config" / "recipes" / "writer_knowledge.md").read_text(encoding="utf-8")


def test_director_prompt_generated():
    t = DR.system_prompt()
    assert "director_prompt_version: kb-" in t and '"verdict"' in t and "[K-REV-008]" in t


# ---- 写作自检回路 ----
def test_writer_selfcheck_loop_with_mock():
    llm = WR.MockWriter(["## ep09《x》\nBAD\n---", "## ep09《x》\nGOOD\n---"])
    check = lambda t: [] if "GOOD" in t else [{"rule": "SS-H1", "shot": "ep09-S1", "message": "缺 H3"}]  # noqa: E731
    r = WR.write_with_selfcheck([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], 9,
                                llm=llm, check=check, log=lambda *a: None)
    assert r["ok"] and r["rounds"] == 1 and len(llm.calls) == 2
    assert "【格式返修】" in llm.calls[1][-1]["content"] and "SS-H1" in llm.calls[1][-1]["content"]
    stuck = WR.write_with_selfcheck([{"role": "user", "content": "u"}], 9, llm=WR.MockWriter(["BAD"]), check=check,
                                    max_rounds=2, log=lambda *a: None)
    assert not stuck["ok"] and stuck["rounds"] == 2


def test_writer_selfcheck_real_checks_on_fixture():
    text = (ROOT / "tests" / "fixtures" / "recipes_min_script.md").read_text(encoding="utf-8")
    issues = WR.selfcheck(text, 9, strict=False)
    rules = {i["rule"] for i in issues}
    assert "SS-P4" in rules and "SS-A1" in rules                  # 人物表缺 EN / VOICE → 交写作方


# ---- 审片 ----
def test_parse_verdict_strict():
    good = '{"shot":"x","verdict":"fail","scores":{"motion":3},"issues":["静止"],"action":"reseed","confidence":0.8}'
    v, err = DR.parse_verdict("```json\n" + good + "\n```", "x")
    assert err is None and v["action"] == "reseed" and v["scores"]["motion"] == 3.0
    assert DR.parse_verdict('{"verdict":"maybe"}', "x")[0] is None
    assert DR.parse_verdict("没有 JSON", "x")[0] is None
    v, _ = DR.parse_verdict('{"verdict":"pass","action":"reseed","confidence":0.9}', "x")
    assert v["action"] == "none"                                 # pass 不带动作


def test_judge_falls_back_to_rules():
    calls = []

    def garbage(sid, sh, plan=None, retry_note=None):
        calls.append(retry_note)
        return "我觉得还行"
    v = DR.judge("s1", {"renders": 1, "last_failures": [{"metric": "still_frac", "value": 0.8, "threshold": 0.5}]}, garbage)
    assert len(calls) == 2 and calls[1] and v["by"].startswith("rule_fallback")
    assert v["verdict"] == "fail" and v["action"] == "reseed"


# ---- 全链路 dry-run ----
@pytest.fixture
def ap(tmp_path, monkeypatch):
    import run as RUN
    import store as ST
    monkeypatch.setattr(RUN, "BASE", tmp_path / "autopilot")
    monkeypatch.setattr(RUN, "PAGES", tmp_path / "pages")
    monkeypatch.setattr(ST, "BASE", tmp_path / "loops")
    # 测试内置数据（SERIES 2026-10-31）：ep02 / ep03 原来读生产剧本 data/import/script_v2.json；生产剧本已整份替换为
    # 新 10 集（series10_v1），这两条 dry-run 改用固定的替换前原文（tests/fixtures/autopilot_ep02_ep03_pre_series10.md），
    # 放进 run 目录的 P3_script.md（run._episode_text 优先读它），不再依赖生产剧本
    fx = (ROOT / "tests" / "fixtures" / "autopilot_ep02_ep03_pre_series10.md").read_text(encoding="utf-8")
    for rid in ("t_ep02", "t_ep03"):
        d = tmp_path / "autopilot" / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "P3_script.md").write_text(fx, encoding="utf-8")
    # 同理：替换前生产 data/renders/ep02 的 11 镜都有定稿首帧锁（P5-P6 闸门据此放行）；那批旧版本已归档
    # （data/renders/_archive_60ep_20261031/），这里用内置数据模拟“每镜首帧已定稿”，不读生产渲染目录
    from ns_recipes import spec_import as SI
    monkeypatch.setattr(SI, "locked_keyframes", lambda shot_id, root=None: {
        "first": SI.IdentityRef(path=f"tests/fixtures/locked/{shot_id}_first.png", sha=None, version="image#1")})
    return RUN


def test_autopilot_dry_run_ep02_gates_and_resume(ap, tmp_path):
    rc = ap.main(["start", "--episode", "2", "--from", "P3", "--dry-run", "--no-open", "--run-id", "t_ep02"])
    assert rc == ap.EXIT_GATE                                  # 不自动批：停在交付闸门
    st = json.loads((tmp_path / "autopilot" / "t_ep02" / "state.json").read_text(encoding="utf-8"))
    assert st["stages"]["P11-P12"]["status"] == "waiting_owner"
    assert st["stages"]["P6-P10"]["result"]["passed"] >= 1
    assert (tmp_path / "pages" / "ep02" / "index.html").exists()
    assert ap.main(["approve", "--run-id", "t_ep02", "--gate", "delivery"]) == 0
    assert ap.main(["run", "--run-id", "t_ep02", "--no-open"]) == 0
    st = json.loads((tmp_path / "autopilot" / "t_ep02" / "state.json").read_text(encoding="utf-8"))
    assert st["status"] == "done" and st["gates"]["delivery"]["by"] == "owner"
    kinds = {json.loads(x)["kind"] for x in (tmp_path / "autopilot" / "t_ep02" / "events.jsonl").read_text(
        encoding="utf-8").splitlines()}
    assert {"stage_done", "gate_wait", "gate_approved"} <= kinds


def test_autopilot_dry_run_ep03_stops_for_writer(ap, tmp_path):
    rc = ap.main(["start", "--episode", "3", "--from", "P3", "--dry-run", "--auto-approve", "--no-open",
                  "--run-id", "t_ep03"])
    assert rc == ap.EXIT_WRITER
    d = tmp_path / "autopilot" / "t_ep03"
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert st["stages"]["P3-P4"]["result"]["rounds"] == 2      # 写作自检回路跑满 2 轮（mock 写作方不改稿）
    assert st["stages"]["P6-P10"]["status"] == "needs_writer"
    assert (d / "writer_requests.md").exists()


def test_per_shot_repair_only_replaces_flagged_shot():
    from ns_api import script_chat as SC
    ep = (ROOT / "tests" / "fixtures" / "recipes_min_script.md").read_text(encoding="utf-8").split("\n---")[0]
    two = ep + "\n\n" + SC.split_shots(ep)[1][1].replace("**镜1｜img**", "**镜2｜img**")
    seen = []

    def llm(msgs):
        seen.append(msgs[-1]["content"])
        return "**镜2｜img**：近景，FIXED\n**时长**：6秒\n"
    issues = [{"rule": "SS-C1", "shot": "ep09-S2", "message": "景别"}]
    text, notes = WR.repair_round(two, issues, 9, [{"role": "system", "content": "s"}], llm)
    _, shots, _ = SC.split_shots(text)
    assert "FIXED" in shots[2] and "FIXED" not in shots[1] and len(seen) == 1
    assert "只输出这一镜" in seen[0] and "镜2" in notes[0]


def test_registry_change_marks_dependents_stale(tmp_path):
    from ns_agent import asset_revs as AR
    (tmp_path / "data" / "import").mkdir(parents=True)
    sj = tmp_path / "data" / "import" / "script_v2.json"
    reg = {"globals": {"character_registry": [{"name": "林晚", "char_id": "lin_wan", "en": "a young woman", "voice": "v1"}]}}
    sj.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    r1 = AR.current_rev("registry:lin_wan", tmp_path)
    assert r1 and "registry" in AR.TYPES
    take = {"stage": "video", "deps": {"registry:lin_wan": r1}}
    assert AR.stale_deps(take, tmp_path, ledger={}) == []
    reg["globals"]["character_registry"][0]["voice"] = "a natural-paced young urban voice"
    sj.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    st = AR.stale_deps(take, tmp_path, ledger={})
    assert st and "人物表登记" in st[0]["text"]


def test_roles_playbooks_and_entries_exist():
    import re as _re
    import roles as RL
    conns = KC.connections()
    for rid, r in RL.ROLES.items():
        assert (ROOT / "docs" / "playbooks" / f"{rid}.md").exists(), rid
        assert set(r["links"]) <= conns, (rid, r["links"])
        for s in r["steps"]:
            assert s["how"] in ("code", "prompt", "owner")
            for path in _re.findall(r"(?:tools|services|packages|config)/[\w./-]+\.(?:py|md|yaml|json)", s["entry"]):
                assert (ROOT / path).exists(), (rid, path)
    table = RL.table_md()
    assert table.count("\n") > 20 and "项目方闸门" in table
    doc = (ROOT / "docs" / "AUTOPILOT.md").read_text(encoding="utf-8")
    assert "总表" in doc and "P11-RETRY" in doc


def test_rsi_ledger_references_checked(tmp_path):
    rules = KC.load_rules(KC.KB / "rules")
    assert KC.ledger_check(rules) == []
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "RSI_LEDGER.md").write_text(
        "| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |\n|---|---|---|---|---|---|---|\n"
        "| X1 | a | b | c | ✅ | K-REN-999 | d |\n| X2 | a | b | c | 不知道 | K-REN-002 | d |\n", encoding="utf-8")
    errs = KC.ledger_check(rules, tmp_path)
    assert any("K-REN-999" in e for e in errs) and any("缺结论" in e for e in errs)


def test_scene_alias_check(tmp_path):
    assert KC.scene_alias_check() == []
    (tmp_path / "config").mkdir()
    (tmp_path / "assets" / "scenes" / "sk_x").mkdir(parents=True)
    (tmp_path / "data" / "import").mkdir(parents=True)
    (tmp_path / "data" / "import" / "script_v2.json").write_text(
        json.dumps({"globals": {"scene_library": [{"scene_id": "sk_x_night"}]}}), encoding="utf-8")
    (tmp_path / "config" / "scene_aliases.json").write_text(json.dumps({"scenes": {}}), encoding="utf-8")
    errs = KC.scene_alias_check(tmp_path)
    assert any("sk_x_night" in e for e in errs) and any("sk_x" in e and "目录" in e for e in errs)
