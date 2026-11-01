"""HOLLYWOOD r5（D-SCR-09 / L-096 / L-097，K-WRT-H04–H05）：剧情事实不变量（代码部分）、清单评审解析、回复整集 / 部分判定。不调网关。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def R():
    spec = importlib.util.spec_from_file_location("hollywood_r5", ROOT / "tools" / "script_rsi" / "hollywood_r5.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def ep04(R):
    text, _ = R.RC.assemble(R.RL, [4], R.RC.episode_sources())
    pre, chunks = R.RL.split_doc(text)
    return pre, chunks[0]


def test_rubric_is_checklist_5x10(R):
    d = json.loads(R.RUBRIC_JSON.read_text(encoding="utf-8"))
    assert sorted(d) == sorted(k for k, _ in R.H.DIMS)
    assert all(len(v) == 5 for v in d.values())
    j = R.H.JUDGE_MD.read_text(encoding="utf-8")
    assert "## 三、可核对清单" in j and "## 五、刁钻评审" in j and "原有标准" not in j.split("## 三、")[0][-1:]


def test_parse_checklist_counts_met_and_never_loosens(R):
    ch = {k: {"met": [1, 2, 3, 4, 5], "unmet": []} for k, _ in R.H.DIMS}
    ch["hook5s"] = {"met": [1, 2, 3, 4], "unmet": [{"id": 4, "shots": [1], "why": "x"}]}   # 4 既 met 又 unmet → 不满足
    ch["turns"] = {"met": [1, 2], "unmet": []}                                              # 3–5 没给 → 不满足
    sc, err = R.parse_checklist("```json\n" + json.dumps({"checks": ch}) + "\n```")
    assert not err
    assert sc["scores"]["hook5s"]["score"] == 3 and sc["scores"]["turns"]["score"] == 2
    assert R.H._sum(sc) == 45


def test_gate5_speaker_order_code_check(R, ep04, tmp_path, monkeypatch):
    import p4_adapter
    monkeypatch.setattr(p4_adapter, "TMP", tmp_path)
    pre, orig = ep04
    R.H.ZERO_CODES[:] = ["QW-W11"]
    base = R.H.lint(orig, 4)
    g = R.gate5(pre, orig, orig, 4, base, tmp_path)
    ok = {c["id"]: c["ok"] for c in g["checks"]}
    assert ok["F1"] and "I1" not in ok                      # r5：I1 台词逐字 → F1 说话人顺序 + F2 事实核对
    obj = R.H.episode_obj(pre, orig, 4, tmp_path)
    seq = R.speaker_seq(obj)
    assert seq and all(isinstance(x, str) for x in seq)


def test_apply_reply_full_vs_partial(R, ep04):
    pre, orig = ep04
    blk = R.RL.block_text(orig, 0)
    c, p, chg, err = R.apply_reply('```json\n{"shots": []}\n```\n\n' + blk, orig, orig, 9, {})
    assert not err and chg == [1]                            # 只给镜1 → 部分镜
    allb = "\n\n".join(R.RL.block_text(orig, k) for k in range(9))
    c, p, chg, err = R.apply_reply('```json\n{"logline": "x", "shots": []}\n```\n\n' + allb, orig, orig, 9, {})
    assert not err and chg == "全集"


def test_d_scr_09_recorded():
    od = (ROOT / "config/owner_decisions.yaml").read_text(encoding="utf-8")
    mp = (ROOT / "docs/master/MASTER_PICTURE.md").read_text(encoding="utf-8")
    assert "id: D-SCR-09" in od and "| L-096 |" in mp and "| L-097 |" in mp
    assert "50 over 50" in mp


def test_k_wrt_h06_fact_drift_lint(R, ep04):
    pre, orig = ep04
    assert R.fact_drift_lint(orig, orig) == []
    blk = R.RL.block_text(orig, 0)
    bad = orig.replace(blk, blk + "\n**分拍**：0–2秒｜手机屏幕亮起“明晚八点，别迟到”｜视线=屏幕", 1)
    hits = R.fact_drift_lint(orig, bad)
    assert any("明晚八点" in h for h in hits) and any("明晚" in h for h in hits)


def test_patch_mode_line_patches(R, ep04):
    pre, orig = ep04
    nl = R.numbered_lines(orig)
    c, ch, err = R.apply_patches(orig, [{"line": 3, "new": nl[2][2] + "（改）"}], nl)
    assert not err and len(ch) == 1 and c.count("（改）") == orig.count("（改）") + 1
    assert R.apply_patches(orig, [{"line": 1, "new": "**镜9｜img**：x"}], nl)[2]          # 镜号不能改
    assert R.apply_patches(orig, [{"line": 99999, "new": "x"}], nl)[2]


def test_ruler_evidence_must_be_verbatim(R):
    body = R._norm_txt("**镜1｜img**：特写，林晚扶碗的手指停在碗沿，视线落在白瓷碗上")
    assert R.evidence_found("镜1｜**img**：……扶碗的手指停在碗沿……", body)
    assert not R.evidence_found("镜1｜**img**：她很紧张地看着他", body)


def test_r6_rubric_code_share_and_parsers():
    import importlib.util as iu
    spec = iu.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
    RC = iu.module_from_spec(spec)
    spec.loader.exec_module(RC)
    sh = RC.share()
    assert (sh["code"], sh["mixed"], sh["llm"]) == (24, 3, 23)
    assert all(sorted(RC.CODE_ITEMS.get(d, []) + list(RC.MIXED_ITEMS.get(d, {})) + RC.LLM_ITEMS[d]) == [1, 2, 3, 4, 5] for d in RC.DIMS)
    assert RC.accessory_tokens({"饰品": "2件（九串铁珠、钻石水晶甲（5 厘米超长透明水晶甲、镶满钻石饰品，与现有定妆一致））"}) == ["串铁珠", "水晶甲"]
    looks = RC.parse_looks("**造型｜林晚**：服装=雾蓝针织长裙，柔软贴身｜发=雾霾天蓝色及腰直发（略深），齐刘海\n"
                           "**造型｜林晚｜镜4起**：服装=黑色漆皮束腰配黑色漆皮短裙，露出长腿")
    assert RC.garment_tokens(RC.look_at(looks, "林晚", 2)) == ["雾蓝针织长裙"]
    assert RC.garment_tokens(RC.look_at(looks, "林晚", 5)) == ["黑色漆皮束腰", "黑色漆皮短裙"]
    assert RC.hair_core(RC.look_at(looks, "林晚", 5)) == "雾霾天蓝色及腰直发"          # 换装行继承发型


def test_r6_code_checks_deterministic(R, ep04, tmp_path, monkeypatch):
    import p4_adapter
    monkeypatch.setattr(p4_adapter, "TMP", tmp_path)
    pre, orig = ep04
    obj = R.H.episode_obj(pre, orig, 4, tmp_path)
    shots = sorted(obj.shots, key=lambda s: s.index)
    blocks = [R.RL.block_text(orig, k) for k in range(len(shots))]
    codes = R.H.lint(orig, 4)["codes"]
    a = R.RC6.code_checks(orig, shots, blocks, R.RL.block_text(orig, "head"), codes)
    b = R.RC6.code_checks(orig, shots, blocks, R.RL.block_text(orig, "head"), codes)
    assert a == b and sum(len(v) for v in a.values()) == 27


def test_r7_rubric_gate_runs_offline(tmp_path, monkeypatch):
    import importlib.util as iu
    import p4_adapter
    monkeypatch.setattr(p4_adapter, "TMP", tmp_path)
    spec = iu.spec_from_file_location("rubric_audit", ROOT / "tools" / "script_rsi" / "rubric_audit.py")
    RA = iu.module_from_spec(spec)
    spec.loader.exec_module(RA)
    monkeypatch.setattr(RA, "OUT", tmp_path)
    text, _ = RA.H.RC.assemble(RA.RL, [4], RA.H.RC.episode_sources())
    f = tmp_path / "ep04.md"
    f.write_text(text, encoding="utf-8")
    r = RA.gate(f)
    assert 4 in r["eps"] and r["eps"][4]["total"] == 27
    assert r["ok"] == (not r["eps"][4]["fails"])


def test_r7_compiled_prompt_parsing():
    import importlib.util as iu
    spec = iu.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
    RC = iu.module_from_spec(spec)
    spec.loader.exec_module(RC)
    comp = "林晚的眼睛看着他，眼睛不看镜头。图1是林晚的脸部参考（只取脸和发型）。中景构图（膝盖以上），林晚坐着"
    assert RC._size(comp) == "中景"
    assert not RC.LOOK_CAMERA.search("眼睛不看镜头，脸不正对镜头")
    assert RC.LOOK_CAMERA.search("她回头看向门口")


def test_k_wrt_h10_wardrobe_not_fact(R):
    keep = {"kind": "setting", "ref": "林晚发色雾霾天蓝", "found": "镜3 发色改为黑色"}
    drop = {"kind": "setting", "ref": "林晚造型（漆皮束腰配短裙）", "found": "改为米白色针织上衣与铅笔裙，水晶甲保留"}
    face = {"kind": "setting", "ref": "林晚造型与水晶甲", "found": "换成黑色长裙，水晶甲未出现"}
    out = R.drop_wardrobe([keep, drop, face])
    assert keep in out and drop not in out and face in out
    assert "K-WRT-H10" in (ROOT / "config/prompts/hollywood_facts.md").read_text(encoding="utf-8")
