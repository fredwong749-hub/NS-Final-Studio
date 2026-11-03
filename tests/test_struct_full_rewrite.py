"""STRUCT-O 11-03（L-158，CHANNEL 07:04 / 09:56）：补丁环诊断出结构项（整段字段缺失 / 镜数 / 镜长 / 确认补丁不可修）→ daemon 自动出整集返修包，
不再一轮轮出补丁白跑；结构项第一次出现就转（不等补丁预算用满）；包里 brief 列全未过项原文 + 原因、必须保留、L-141 写法、段落标记规则、
每种结构项的改法；写 report_issue + agent_history；交回照常 intake_full_p4 → adopt_full_p4。
ep02 实测：v2#1 缺段（镜1/镜2 缺 机位与景别 / 构图 / 运镜 / 表演节拍 整段）a11–a13 三轮补丁不动，daemon 只出诊断停在 not_importable。
全部夹具在 tmp_path，派人请求写 NSFS_INBOX_DIR，卡点写临时 issues / V2_LIVE，不碰真实数据。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


AG = _load("autoflow_agent_struct_t", "tools/script_rsi/autoflow_agent.py")
AF = AG.AF
RI = _load("report_issue_struct_t", "tools/master/report_issue.py")

V2_WHY = "代码判定：缺段：['镜1缺机位与景别', '镜1缺构图', '镜2缺运镜', '镜2缺表演节拍']；段顺序不对的镜：无"
FAILS = [("v2", {"id": 1, "shots": [1, 2], "why": V2_WHY}),
         ("p4", {"id": "TL-3", "shots": [3], "why": "ep01-S3.timeline：[TL-3] 镜3 时间轴不全"})]
CUR = ("## ep01《测试》\n**剧情**：测试\n\n**镜1｜img**：中景，女主 A 在左\n**镜头运动**：固定\n**对白**：女主 A：「我不会去。」\n"
       "**时长**：5\n\n**镜2｜img**：近景\n**机位与景别**：近景平视\n🎙 男主 B（画外）：「别去。」\n\n---\n")
FACTS = {"lines": [{"id": "F-KEY", "text": "邀请卡塞进鞋尖"}]}


def _env(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    rd = tmp_path / "series10_t"
    for sub in ("writer_tasks", "writer_out"):
        (rd / sub).mkdir(parents=True)
    issues, live = tmp_path / "issues.jsonl", tmp_path / "V2_LIVE.md"
    live.write_text("# live\n", encoding="utf-8")
    monkeypatch.setenv("NSFS_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setattr(RI, "ISSUES", issues)
    monkeypatch.setattr(RI, "LIVE", live)
    real = AG._load
    monkeypatch.setattr(AG, "_load", lambda n, r: RI if n == "report_issue" else
                        SimpleNamespace(p1_approved=lambda rd_: True, enabled=lambda rd_: False) if n == "owner_gate" else real(n, r))
    return rd, issues


def _st(rd: Path, **ag):
    st = AF.Status(rd, 1, 0.0)
    st.d["agent"] = {"processed": [], "used": {}, "fact_devs": None, **ag}
    st.save()
    return st


def test_structural_items_classification():
    fails = [("v2", {"id": 1, "why": V2_WHY}),
             ("v2", {"id": 1, "why": "代码判定：缺段：无；段顺序不对的镜：[3]"}),        # 只是顺序不对：补丁能改，不算
             ("p4", {"id": "QW-T1", "why": "镜6 时长 7 秒"}), ("turns", {"id": 1, "why": "镜数 8"}),
             ("p4", {"id": "QW-C1", "why": "运镜不在词表"}), ("p4", {"id": "TL-2", "why": "时间轴"}),
             ("k211", {"id": 2, "why": "手部 3 拍"})]
    got = [(f"{d}#{u['id']}", k) for d, u, k in AG.structural_items(fails, {"unpatchable": ["k211#2"]})]
    assert got == [("v2#1", "missing_segment"), ("p4#QW-T1", "shot_length"), ("turns#1", "shot_count"), ("k211#2", "unpatchable")]
    assert AG.structural_items([("p4", {"id": "TL-2", "why": "x"})], {}) == []


def test_first_structural_goes_full_rewrite_without_spending_patch_budget(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd)
    out = AG.structural_rewrite(rd, 1, st, CUR, FAILS, FACTS)
    # 出的是整集返修包（step P4_ep01，产物 writer_out/P4_ep01_a1.md，intake_full_p4 认这个名字），不是补丁包
    assert out["ok"] and (rd / "writer_tasks" / "P4_ep01_a1.json").exists() and not list((rd / "writer_tasks").glob("patch_*"))
    pk = json.loads((rd / "writer_tasks" / "P4_ep01_a1.json").read_text(encoding="utf-8"))
    assert pk["output"]["path"].endswith("writer_out/P4_ep01_a1.md") and pk["link"] == "P3-P4" and pk["full_rewrite"] == "L-158"
    assert pk["targets"] == ["v2#1"] and pk["structural"] == ["missing_segment"]
    req = json.loads((tmp_path / "inbox" / "requests" / "series10_t__P4_ep01_a1.json").read_text(encoding="utf-8"))
    assert req["kind"] == "writer" and req["id"] == "P4_ep01_a1"                         # 派单器领这个请求
    assert AG.patch_budget_used(rd, 1, st.d["agent"]) == 0                                # 补丁预算一个没花
    # 卡点（非阻断，系统已处理）+ agent_history 留痕 + 状态等写手
    recs = [json.loads(x) for x in issues.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["step"] == "5" and not recs[0]["blocking"] and "P4_ep01_a1" in recs[0]["what"]
    s = json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))
    h = s["agent_history"][-1]
    assert h["step"] == "P4_ep01_a1" and h["by"] == "structural_rewrite" and recs[0]["id"] in h["note"]
    assert s["verdict"] == "awaiting_writer" and s["awaiting"]["output"].endswith("P4_ep01_a1.md")
    assert s["structural_rewrites"][0]["issue"] == recs[0]["id"]
    # daemon 再跑一拍（没交稿）：等着，不重出包、不重登记
    st2 = AF.Status(rd, 1, 0.0)
    assert AG.structural_rewrite(rd, 1, st2, CUR, FAILS, FACTS)["waiting"].endswith("P4_ep01_a1.md")
    assert len(list((rd / "writer_tasks").glob("P4_ep01_a*.json"))) == 1 and len(issues.read_text(encoding="utf-8").splitlines()) == 1


def test_brief_lists_everything(tmp_path, monkeypatch):
    rd, _ = _env(tmp_path, monkeypatch)
    st = _st(rd)
    AG.structural_rewrite(rd, 1, st, CUR, FAILS, FACTS)
    user = json.loads((rd / "writer_tasks" / "P4_ep01_a1.json").read_text(encoding="utf-8"))["user"]
    assert "v2#1" in user and V2_WHY in user and "p4#TL-3" in user and "[TL-3] 镜3 时间轴不全" in user       # 所有未过项原文 + 原因
    assert "缺段 → 在点名的镜里补全整段字段" in user and "镜1缺机位与景别、镜1缺构图、镜2缺运镜、镜2缺表演节拍" in user
    for lab in ("**机位与景别**：", "**构图**：", "**运镜**：", "**表演节拍**："):                       # 字段格式（shot_spec_v2 单一来源）
        assert any(ln.strip().startswith(lab) and ln.endswith("（必填）") for ln in user.splitlines()), lab
    assert "**对白**：女主 A：「我不会去。」" in user and "🎙 男主 B（画外）：「别去。」" in user                # 台词逐字
    assert "邀请卡塞进鞋尖" in user and "未点名的镜和行逐字保持" in user                                     # 已过的事实 / 未点名内容
    assert "In the first" in user and "At" in user                                                           # L-141 写法
    assert "【幻想段】" in user and "K-WRT-213" in user                                                      # 段落标记规则
    assert user.rstrip().endswith("---") and "【现稿（整集返修的底稿）】" in user


def test_rejected_draft_reissued_with_reason_then_capped(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd)
    AG.structural_rewrite(rd, 1, st, CUR, FAILS, FACTS)
    # 写手交了，intake_full_p4 拒收（阻断太多）：记 full_p4_done + accepted False
    st.d["agent"]["full_p4_done"] = ["P4_ep01_a1.md"]
    st.d["agent_history"].append({"step": "P4_ep01_a1.md", "accepted": False, "note": "整集稿 P4 阻断 9"})
    out = AG.structural_rewrite(rd, 1, st, CUR, FAILS, FACTS)
    assert out["ok"] and out["output"].endswith("P4_ep01_a2.md")
    assert "上一次整集返修稿没有被采用：整集稿 P4 阻断 9" in json.loads((rd / "writer_tasks" / "P4_ep01_a2.json").read_text(encoding="utf-8"))["user"]
    st.d["agent"]["full_p4_done"].append("P4_ep01_a2.md")
    capped = AG.structural_rewrite(rd, 1, st, CUR, FAILS, FACTS)
    assert capped == {"ok": False, "why": f"整集返修包已出 {AG.FULL_REWRITE_MAX} 次（上限 {AG.FULL_REWRITE_MAX}）仍有结构项 v2#1"}
    assert len(list((rd / "writer_tasks").glob("P4_ep01_a*.json"))) == AG.FULL_REWRITE_MAX
    # 总调度 reopen：整集返修次数按新基线算，又能出包
    AG.reopen(rd, 1, "测试", by="STRUCT-O")
    st3 = AF.Status(rd, 1, 0.0)
    st3.d["agent"]["full_p4_done"] = ["P4_ep01_a1.md", "P4_ep01_a2.md"]
    assert AG.structural_rewrite(rd, 1, st3, CUR, FAILS, FACTS)["output"].endswith("P4_ep01_a3.md")


def test_no_structural_keeps_patch_loop(tmp_path, monkeypatch):
    rd, issues = _env(tmp_path, monkeypatch)
    st = _st(rd)
    assert AG.structural_rewrite(rd, 1, st, CUR, [FAILS[1]], FACTS) is None
    assert not list((rd / "writer_tasks").glob("*.json")) and not issues.exists()


def test_uses_p3p4_writer_packet_when_ctx_given(tmp_path, monkeypatch):
    rd, _ = _env(tmp_path, monkeypatch)
    st = _st(rd)
    rch = SimpleNamespace(WP=SimpleNamespace(build=lambda link, ctx: {"system": f"SYS {link}", "user": "写第 1 集。P3 台词逐字照抄"}))
    AG.structural_rewrite(rd, 1, st, CUR, FAILS, FACTS, rch, {"screenplay": {}})
    pk = json.loads((rd / "writer_tasks" / "P4_ep01_a1.json").read_text(encoding="utf-8"))
    assert pk["system"].startswith("SYS P3-P4") and pk["user"].startswith("写第 1 集。P3 台词逐字照抄")


def test_post_step_checks_structural_before_patch_budget():
    src = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    post = src.split("def post_step(")[1].split("\ndef ")[0]
    i_sr, i_budget = post.find("structural_rewrite(run_dir, ep, st, cur, fails, facts, RCH, ctx)"), post.find("patch_budget_used(run_dir, ep, ag) >= PATCH_MAX")
    assert 0 < i_sr < i_budget                                            # 结构项第一次出现就转，不先耗满 PATCH_MAX
    assert "return post_step(run_dir, ep, st, import_mode, RCH=RCH, ctx=ctx)" in src


def test_segment_format_passes_v1_guard():
    """11-03 11:58 ep02 L-159 重开即 halted_error：整集返修包字段格式带了 shot_spec_v2 写手说明里的中文“徕卡”（V1 S★ 标记）。
    字段格式必须过真实的 assert_no_v1（series10_v2 = 完全切割剧）"""
    from ns_api import script_chat as SC
    text = "\n".join(AG._segment_format())
    assert "徕卡" not in text and "summilux_35_f14" in text
    SC.assert_no_v1(text, run="series10_v2", what="整集返修包字段格式")
