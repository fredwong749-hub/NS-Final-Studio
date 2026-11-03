"""K-WRT-213（K211-F 11-03，REVIEW-B P1-2）：V2 每镜必标【幻想段】/【现实段】，段落从 P2 节拍 / P3 场景确定性推断；
漏标 QW-S1 block、标反 QW-S2；收稿 / 补丁环前自动补标，不派 LLM。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


SF = _load("segment_fix_t", "tools/script_rsi/segment_fix.py")

P2 = {"beats": [{"id": "B1", "summary": "【现实段·开场】卓琳甩开软尺"}, {"id": "B2", "summary": "【幻想段】环形灯亮，风机吹起长发，快门连成一片"},
                {"id": "B3", "summary": "【现实段】环形灯灭，卓琳量尺报数"}, {"id": "B4", "summary": "卓琳拍下邀请卡"}]}
P3 = {"scenes": [
    {"no": 1, "beat_ids": ["B1"], "lines": [{"kind": "action", "text": "卓琳把软尺甩开，两人并排站到白幕中央"}, {"kind": "dialogue", "text": "站好。肩挨肩。"}]},
    {"no": 2, "beat_ids": ["B2"], "lines": [{"kind": "action", "text": "环形灯亮起，风机吹起祁念的雾蓝长发，江予白一连按下快门"}]},
    {"no": 3, "beat_ids": ["B3"], "lines": [{"kind": "action", "text": "环形灯灭，卓琳把软尺绕过祁念的腰"}, {"kind": "dialogue", "text": "五十八。一百零六。"}]},
    {"no": 4, "beat_ids": ["B4"], "lines": [{"kind": "action", "text": "卓琳抽出烫金邀请卡拍在亚克力椅上"}, {"kind": "dialogue", "text": "头牌黎总亲自点。"}]},
]}


def shot(n, scene, dlg=None, extra=""):
    s = f"**镜{n}｜img**：中景，{scene}\n**机位与景别**：中景\n**场景**：sk_white_cyc｜{scene}\n**人物**：祁念（在画｜中｜中）\n"
    if dlg:
        s += f"**对白**：（卓琳，干脆）“{dlg}”\n"
    s += extra + "**时长**：6秒\n**H3提示词**：\n```text\n[Shot 1] 【幻想段】 marks inside code fence do not count\n```\n"
    return s


DOC = "## ep01《量尺》\n**剧情**：x\n\n" + shot(1, "白幕前卓琳甩开软尺", "站好。肩挨肩。") + shot(2, "环形灯架亮起，风机吹起长发，快门连成一片") \
      + shot(3, "环形灯架后江予白按快门") + shot(4, "环形灯灭，软尺绕上腰", "五十八。一百零六。") + shot(5, "亚克力椅上的烫金邀请卡", "头牌黎总亲自点。") + "\n---\n"


def test_upstream_segments_inherit():
    assert SF.beat_segments(P2) == {"B1": "reality", "B2": "fantasy", "B3": "reality", "B4": "reality"}
    assert SF.scene_segments(P2, P3) == {1: "reality", 2: "fantasy", 3: "reality", 4: "reality"}


def test_infer_dialogue_anchor_and_similarity_fill():
    r = {x["shot"]: x for x in SF.infer(DOC, P2, P3)}
    assert r[1]["how"] == "dialogue" and r[1]["scene_no"] == 1 and r[4]["scene_no"] == 3 and r[5]["scene_no"] == 4
    assert r[2]["scene_no"] == 2 and r[2]["segment"] == "fantasy" and r[2]["how"] == "similar"      # 没台词的镜按相似度落到幻想段场景
    assert r[3]["scene_no"] == 2 and r[3]["segment"] == "fantasy"
    assert all(x["marked"] is None for x in r.values())                                               # 代码块里的【幻想段】不算标记


def test_check_missing_and_mismatch():
    iss = SF.check(DOC, P2, P3)
    assert len(iss) == 5 and all(i["code"] == "QW-S1" and i["level"] == "block" for i in iss)
    assert "【幻想段】" in next(i for i in iss if i["shot"] == 2)["detail"]
    wrong = DOC.replace("**场景**：sk_white_cyc｜白幕前卓琳甩开软尺", "**场景**：sk_white_cyc｜【幻想段】白幕前卓琳甩开软尺")
    i1 = [i for i in SF.check(wrong, P2, P3) if i["shot"] == 1][0]
    assert i1["code"] == "QW-S2" and i1["level"] == "block"                                           # 台词锚定的镜标反 → block
    wrong2 = DOC.replace("**场景**：sk_white_cyc｜环形灯架后江予白按快门", "**场景**：sk_white_cyc｜【现实段】环形灯架后江予白按快门")
    i3 = [i for i in SF.check(wrong2, P2, P3) if i["shot"] == 3][0]
    assert i3["code"] == "QW-S2" and i3["level"] == "warn"                                            # 推断的镜标反 → warn


def test_fill_marks_scene_line_and_passes_check():
    new, filled = SF.fill(DOC, P2, P3)
    assert [f["shot"] for f in filled] == [1, 2, 3, 4, 5] and [f["segment"] for f in filled] == ["reality", "fantasy", "fantasy", "reality", "reality"]
    assert "**场景**：sk_white_cyc｜【幻想段】环形灯架亮起，风机吹起长发，快门连成一片" in new
    assert "**场景**：sk_white_cyc｜【现实段】白幕前卓琳甩开软尺" in new
    assert SF.check(new, P2, P3) == [] and SF.fill(new, P2, P3)[1] == []                            # 幂等
    assert new.count("**镜") == DOC.count("**镜") and "对白" in new                                   # 只加标记，不动别的


def test_apply_file_backs_up_and_audits(tmp_path, monkeypatch):
    rd = tmp_path / "series10_t"
    rd.mkdir()
    (rd / "P2_ep01_outline.json").write_text(json.dumps(P2, ensure_ascii=False), encoding="utf-8")
    (rd / "P3_ep01_screenplay.json").write_text(json.dumps(P3, ensure_ascii=False), encoding="utf-8")
    p = rd / "P4_ep01.md"
    p.write_text(DOC, encoding="utf-8")
    monkeypatch.setattr(SF, "ROOT", tmp_path)                       # 隔离区落在临时目录，不碰真实 data/
    r = SF.apply_file(p, rd, by="test")
    assert r["changed"] and len(r["filled"]) == 5 and r["mismatch"] == []
    assert "【幻想段】环形灯架亮起" in p.read_text(encoding="utf-8")
    assert list((tmp_path / "data" / "_quarantine").glob("segment_fix_*/series10_t/P4_ep01.md.*.md"))      # 原稿留档
    rec = json.loads((rd / SF.AUDIT).read_text(encoding="utf-8").splitlines()[-1])
    assert rec["episode"] == 1 and len(rec["filled"]) == 5
    assert SF.apply_file(p, rd, by="test")["changed"] is False     # 第二次没有要补的
    (rd / "P3_ep01_screenplay.json").unlink()
    assert "P2 / P3" in SF.apply_file(p, rd)["error"]


def test_real_ep01_infers_fantasy_shots_2_and_3():
    """真实 V2 ep01：P2 B2 幻想段 → 镜 2 / 3（REVIEW-B P1-2 点名的三镜里能机器推断的两镜；镜 1 有台词锚定现实段）"""
    rd = ROOT / "data/pipeline/runs/series10_v2"
    src = rd / "writer_out" / "P4_ep01_a4.md"
    if not src.exists() or not (rd / "P3_ep01_screenplay.json").exists():
        import pytest
        pytest.skip("V2 ep01 数据不在")
    p2, p3 = SF.load_upstream(rd, 1)
    r = {x["shot"]: x["segment"] for x in SF.infer(src.read_text(encoding="utf-8"), p2, p3)}
    assert r[2] == "fantasy" and r[3] == "fantasy" and r[1] == "reality" and r[4] == "reality"


def test_rule_wired_into_gate_and_autoflow():
    import yaml
    rules = yaml.safe_load((ROOT / "knowledge/rules/writer_series10.yaml").read_text(encoding="utf-8"))["rules"]
    r = next(x for x in rules if x["id"] == "K-WRT-213")
    assert r["enforced"] is True and "tests/test_segment_fix.py" in r["check"]
    idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
    items = idx.get("rules") if isinstance(idx, dict) else idx
    assert next(x for x in items if x.get("id") == "K-WRT-213").get("enforced") is True
    pa = (ROOT / "tools/pipeline/p4_adapter.py").read_text(encoding="utf-8")
    ag = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    assert "segment_issues(ep_md, episode" in pa and "QW-S1" in (ROOT / "tools/script_rsi/segment_fix.py").read_text(encoding="utf-8")
    assert ag.count("segment_fix(run_dir, ") == 3 and 'segment_fix(run_dir, q, st, "intake_full_p4"' in ag       # 收稿 / 写手稿 / 补丁环三处都先补标


def test_mark_with_suffix_is_recognized():
    """L-164：P2 写“【幻想段·开场 5 秒】”（标记带补充说明）——原来认不出、缺省成现实段，ep02 镜1 QW-S2 / factcheck 两头死锁"""
    assert SF.seg_of_text("【幻想段·开场 5 秒】跨年天台") == "fantasy"
    assert SF.seg_of_text("【现实段：楼下街口】") == "reality"
    assert SF.seg_of_text("【幻想段】") == "fantasy" and SF.seg_of_text("段落=现实") == "reality"
    assert SF.seg_of_text("【人物】祁念") is None
    p2 = {"beats": [{"id": "B1", "summary": "【幻想段·开场 5 秒】天台"}, {"id": "B2", "summary": "黎岸递酒"}]}
    assert SF.beat_segments(p2) == {"B1": "fantasy", "B2": "fantasy"}
