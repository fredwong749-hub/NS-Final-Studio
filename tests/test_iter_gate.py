"""tools/qa/iter_gate.py：O1 owner 授权（LOCKS.md CONSENT 行）与 R1 取最新 detect（ITERAUDIT 2026-11-01）"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/qa"))
import iter_gate as IG  # noqa: E402

LOCKS_TXT = """# 文件锁
| apps/web/src/ds/live.css（说明里提到 CONSENT 不算） | UIRSI → UIPIXEL | 同上 |

## 授权（CONSENT）
`CONSENT: <文件 owner> -> <被授权 agent> : <路径或 glob> | <原话 / 日期>`
- CONSENT: UIPIXEL -> UIRSI : apps/web/src/ds/live.css | UIPIXEL 11-01 同意
CONSENT: UIRSI → ASSETUX : apps/web/src/v3/pages/** | 测试用
"""


def test_parse_consents_format():
    c = IG.parse_consents(LOCKS_TXT)
    assert {"owner": "UIPIXEL", "agent": "UIRSI", "glob": "apps/web/src/ds/live.css"} in c
    assert {"owner": "UIRSI", "agent": "ASSETUX", "glob": "apps/web/src/v3/pages/**"} in c
    assert len(c) == 2      # 格式说明行（<文件 owner>）和表格行不算授权


def _gate(tmp_path, loop, changed, monkeypatch):
    locks = tmp_path / "LOCKS.md"
    locks.write_text(LOCKS_TXT, encoding="utf-8")
    monkeypatch.setattr(IG, "LOCKS", locks)
    a = types.SimpleNamespace(loop=loop, changed=[",".join(changed)], ui=False)
    g = IG.Gate(a)
    g.o1_ownership(IG.load_own())
    return g.rows[-1]


def test_o1_consent_allows_specific_agent_and_file(tmp_path, monkeypatch):
    row = _gate(tmp_path, "UIRSI", ["apps/web/src/ds/live.css"], monkeypatch)
    assert row["status"] == "pass" and "owner 授权 1" in row["detail"]


def test_o1_without_consent_still_fails(tmp_path, monkeypatch):
    # 授权只给 UIRSI、只给 live.css：别的 CSS、别的 agent 仍然越界
    assert _gate(tmp_path, "UIRSI", ["apps/web/src/ds/zoom.css"], monkeypatch)["status"] == "fail"
    assert _gate(tmp_path, "EDITDEL", ["apps/web/src/ds/live.css"], monkeypatch)["status"] == "fail"


def test_r1_picks_newest_detect_not_fixed_round(tmp_path):
    for name, t in (("r8g_detect.json", 1000), ("r10g_detect.json", 3000), ("r9g_detect.json", 2000),
                    ("gv2_detect.json", 9000), ("rg_detect.json", 9000)):
        p = tmp_path / name
        p.write_text("[]", encoding="utf-8")
        os.utime(p, (t, t))
    assert IG.newest_regress_detect(tmp_path).name == "r10g_detect.json"
    # 同一修改时间 → 轮号大的
    for name in ("r11g_detect.json", "r12g_detect.json"):
        p = tmp_path / name
        p.write_text("[]", encoding="utf-8")
        os.utime(p, (5000, 5000))
    assert IG.newest_regress_detect(tmp_path).name == "r12g_detect.json"
    (tmp_path / "empty").mkdir()
    assert IG.newest_regress_detect(tmp_path / "empty") is None


def test_rl_writer_rule_needs_writer_text_and_lint():
    """项目方 11-01：写作相关的新规则要同时有 writer_prompt + writer_text + lint（K-OPS-Q12）"""
    full = {"domain": "writer", "link": "P3-P4", "targets": [{"kind": "writer_prompt", "section": "镜头字段"}],
            "writer_text": "x", "lint": ["QW-W1"]}
    assert IG.writer_gaps(full) == ""
    assert "缺 lint" in IG.writer_gaps({**full, "lint": []})
    assert "缺 writer_prompt" in IG.writer_gaps({**full, "targets": []})
    assert "找不到" in IG.writer_gaps({**full, "lint": ["QW-NOPE9"]})
    assert IG.writer_gaps({"domain": "render", "link": "P7-P8"}) == ""      # 只影响系统层的不要求


def test_g0_propagation_fails_only_for_files_changed_this_round(monkeypatch):
    """K-OPS-D02：本轮改过的文件里留着过期口径 → G0 不通过；别人的残留只提示（RSI r3）"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("ns_iter_gate_g0_t", ROOT / "tools" / "qa" / "iter_gate.py")
    G = ilu.module_from_spec(spec)
    spec.loader.exec_module(G)
    monkeypatch.setattr(G, "propagation_results",
                        lambda: [{"id": "D-T", "stale": [{"file": "docs/a.md", "line": 3, "text": "x"}], "unsynced": []}])
    monkeypatch.setattr(G, "load_own", lambda: {"owners": {"VQAGATE": ["docs/c.md"]}, "override": [], "shared": []})
    g = G.Gate.__new__(G.Gate)
    g.loop, g.loops, g.rows, g.changed = "RSI", {"RSI"}, [], ["docs/a.md"]
    g.g0_propagation()
    assert g.rows[-1]["id"] == "G0" and g.rows[-1]["status"] == "fail"
    g.changed = ["docs/b.md"]
    g.g0_propagation()
    assert g.rows[-1]["status"] == "warn" and g.rows[-1]["required"] is False
    monkeypatch.setattr(G, "propagation_results",
                        lambda: [{"id": "D-T", "stale": [{"file": "docs/c.md", "line": 1, "text": "x"}], "unsynced": []}])
    g.loop, g.loops = "VQAGATE", {"VQAGATE"}
    g.g0_propagation()
    assert g.rows[-1]["status"] == "fail"          # 归 VQAGATE 的文件，VQAGATE 收轮时不通过



def test_k1_names_rule_files_newer_than_generated(tmp_path, monkeypatch):
    """总调度 11-01：改了规则不编译 → K1 记到规则文件的 owner 名下（RSI r3）"""
    import importlib.util as ilu
    import os
    spec = ilu.spec_from_file_location("ns_iter_gate_k1_t", ROOT / "tools" / "qa" / "iter_gate.py")
    G = ilu.module_from_spec(spec)
    spec.loader.exec_module(G)
    (tmp_path / "knowledge/generated").mkdir(parents=True)
    (tmp_path / "knowledge/rules").mkdir(parents=True)
    gen = tmp_path / "knowledge/generated/index.json"
    gen.write_text("{}", encoding="utf-8")
    old, new = tmp_path / "knowledge/rules/a.yaml", tmp_path / "knowledge/rules/b.yaml"
    old.write_text("rules: []", encoding="utf-8")
    new.write_text("rules: []", encoding="utf-8")
    t = gen.stat().st_mtime
    os.utime(old, (t - 100, t - 100))
    os.utime(new, (t + 100, t + 100))
    monkeypatch.setattr(G, "ROOT", tmp_path)
    monkeypatch.setattr(G, "load_own", lambda: {"rule_owners": {"by_file": {"b.yaml": "VOICE10"}}})
    assert G.uncompiled_rule_files() == [("knowledge/rules/b.yaml", "VOICE10")]


def _bare_gate(G, loop, **a):
    from types import SimpleNamespace as NS
    g = G.Gate.__new__(G.Gate)
    g.loop, g.rows, g.changed, g.gen = loop, [], a.pop("changed", ["x.py"]), loop in G.GEN_LOOPS
    g.loops = G.LOOP_GROUPS.get(loop, set()) | {loop}
    g.a = NS(contract=None, task=a.pop("task", "OT9"))
    return g


def test_c1_not_applicable_for_rule_loop_and_o1_needs_registration(monkeypatch):
    """总调度 11-01 晚：RSI / ITERAUDIT 的 C1 判不适用；K-OPS-Q22：loop 没在 ownership.yaml 登记 → O1 不通过"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("ns_iter_gate_c1_t", ROOT / "tools" / "qa" / "iter_gate.py")
    G = ilu.module_from_spec(spec)
    spec.loader.exec_module(G)
    g = _bare_gate(G, "ITERAUDIT")
    g.c1_contract()
    assert g.rows[-1]["status"] == "na" and g.rows[-1]["required"] is False
    g = _bare_gate(G, "VIDEO10")
    g.c1_contract()
    assert g.rows[-1]["status"] == "untested"
    g = _bare_gate(G, "NEWLOOP")
    g.o1_ownership({"owners": {"ITERAUDIT": ["tools/qa/**"]}, "override": [], "shared": []})
    assert g.rows[-1]["status"] == "fail" and "K-OPS-Q22" in g.rows[-1]["detail"]


def test_specific_shared_entry_beats_owner_wildcard():
    """docs/uimaster/LOCKS.md：写 CONSENT 的共享入口，不能因为 docs/uimaster/** 归 UIMASTER 就判越界（RSI r4）"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("ns_iter_gate_sh_t", ROOT / "tools" / "qa" / "iter_gate.py")
    G = ilu.module_from_spec(spec)
    spec.loader.exec_module(G)
    own = {"owners": {"UIMASTER": ["docs/uimaster/**"], "ITERAUDIT": ["knowledge/rules/ops_iteration.yaml"]}, "override": [],
           "shared": [{"glob": "docs/uimaster/LOCKS.md", "via": "加 / 删自己的临时锁行"}, {"glob": "knowledge/rules/**", "via": "只追加"}]}
    assert G.owner_of("docs/uimaster/LOCKS.md", own) == (None, "加 / 删自己的临时锁行")
    assert G.owner_of("docs/uimaster/issues.json", own)[0] == "UIMASTER"
    assert G.owner_of("knowledge/rules/ops_iteration.yaml", own) == ("ITERAUDIT", "只追加")


def test_prod_group_owns_video10_and_producer_files():
    """总调度 11-01 晚：PROD = VIDEO10 + PRODUCER；WORKFLOW = AUTOPILOT（RSI r5）"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("ns_iter_gate_grp_t", ROOT / "tools" / "qa" / "iter_gate.py")
    G = ilu.module_from_spec(spec)
    spec.loader.exec_module(G)
    own = {"owners": {"VIDEO10": ["tools/series10_video/**"], "PRODUCER": ["tools/autopilot/producer.py"]}, "override": [], "shared": []}
    g = _bare_gate(G, "PROD", changed=["tools/series10_video/night.py", "tools/autopilot/producer.py"])
    g.o1_ownership(own)
    assert g.rows[-1]["status"] == "pass", g.rows[-1]
    assert G.LOOP_ALIASES["WORKFLOW"] == "AUTOPILOT"
