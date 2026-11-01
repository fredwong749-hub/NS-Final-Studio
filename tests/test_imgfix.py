"""IMGFIX 11-01（总调度 fredw-2b 派）：出图两个系统性根因的规则检查。

- K-AST-262：现行设定图没过单品一致性检查（K-AST-260）→ 设定图句明说缺的外层单品以参考板为准；
  中枢设定图候选含 ASSETMASTER adopted v2，现行那张永远在候选里，每张标单品检查状态。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/schema", "services/agent", "services/api", "services/render_router"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))


def test_sheet_item_check_by_file_or_v2_seed(tmp_path, monkeypatch):
    from ns_agent import asset_refs as AR
    (tmp_path / "data/assetmaster").mkdir(parents=True)
    (tmp_path / AR.SHEET_CHECKS).write_text(json.dumps({
        "lin_wan_lookA": {"seed": "202", "verdict": "pass"},
        "lin_wan_lookB": {"seed": "505", "verdict": "pass", "file": "x/lin_wan_lookB_special.png"},
        "lin_wan_lookC": {"seed": "202", "verdict": "fail"}}), encoding="utf-8")
    monkeypatch.setattr(AR, "ROOT", tmp_path)
    assert AR.sheet_item_check("lin_wan", "A", "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png")
    assert AR.sheet_item_check("lin_wan", "A", "refcrops/lin_wan_lookA_v2_s202_half_nohead.png")
    # 同 seed 的 v1 候选（10-31，画外套之前）不算——事故那张就是 s101 / s202 v1
    assert not AR.sheet_item_check("lin_wan", "A", "images/sheets/lin_wan/lin_wan_lookA_s202.png")
    assert not AR.sheet_item_check("lin_wan", "A", "images/sheets/lin_wan/lin_wan_lookA_s101.png")
    assert AR.sheet_item_check("lin_wan", "B", "x/lin_wan_lookB_special.png")
    assert not AR.sheet_item_check("lin_wan", "B", "x/lin_wan_lookB_v2_s505.png")
    assert not AR.sheet_item_check("lin_wan", "C", "x/lin_wan_lookC_v2_s202.png")


def test_unchecked_sheet_yields_outer_gap_clause(monkeypatch):
    from ns_agent import asset_refs as AR
    monkeypatch.setattr(AR, "sheet_of", lambda p, c, l: "images/sheets/lin_wan/lin_wan_lookA_s101.png")
    monkeypatch.setattr(AR, "sheet_outer_gaps", lambda p, c, l, f: [] if "_v2_" in f else ["短款西装外套"])
    sheet = AR.Slot(2, "sheet", "c/lin_wan_lookA_s101_half_nohead.png", "lin_wan", ["造型A设定图"],
                    [{"look_id": "A", "secondary": False}], line="图2是林晚本镜造型A的设定图（已去头，只看服装）——……背景与姿势不取。")
    board = AR.Slot(3, "board", "b.png", "lin_wan", ["服装：短款西装外套", "指甲：冰川满钻尖甲"], [{}], line="图3是参考板。")
    AR._apply_sheet_gaps("series10_v1", [sheet, board])
    assert sheet.line.endswith("背景与姿势不取；图2上没有画短款西装外套——短款西装外套以图3为准，穿在最外层。")
    assert board.line == "图3是参考板。"
    # 外层单品不在任何参考槽里 → 以文字为准
    sheet.line = "图2是…背景与姿势不取。"
    AR._apply_sheet_gaps("series10_v1", [sheet])
    assert "短款西装外套以文字为准" in sheet.line
    # 检查过的 v2 设定图 → 不加
    monkeypatch.setattr(AR, "sheet_of", lambda p, c, l: "adopted/lin_wan_lookA_v2_s202.png")
    sheet.line = "图2是…背景与姿势不取。"
    AR._apply_sheet_gaps("series10_v1", [sheet, board])
    assert sheet.line == "图2是…背景与姿势不取。"


def test_real_look_a_outer_items_and_current_sheet_unchecked():
    """现行数据：林晚造型 A 的外层单品 = 短款西装外套；sheets_chosen 现行 s101 没有检查记录 → 有缺口（不改项目方挑的图）"""
    from ns_agent import asset_refs as AR
    pj = "series10_v1"
    cur = AR.sheet_of(pj, "lin_wan", "A")
    if cur is None:
        return
    gaps = AR.sheet_outer_gaps(pj, "lin_wan", "A", cur)
    if AR.sheet_item_check("lin_wan", "A", cur):
        assert gaps == []
    else:
        assert "短款西装外套" in gaps
    assert AR.sheet_outer_gaps(pj, "lin_wan", "A", "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png") == []


def test_hub_sheet_candidates_include_adopted_v2_and_current():
    """中枢候选（真实数据只读）：ASSETMASTER adopted v2 在候选里且标 pass；现行那张在候选里"""
    from ns_agent import asset_refs as AR
    from ns_api import character_hub as H
    pj = "series10_v1"
    ad = ROOT / "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png"
    if not ad.is_file():
        return
    cands = H._sheet_candidates(pj, "lin_wan", "A")
    by = {c["file"]: c for c in cands}
    v2 = by.get("data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png")
    assert v2 and v2.get("adopted") and v2["item_check"] == "pass"
    cur = AR.sheet_of(pj, "lin_wan", "A")
    assert cur in by
    s101 = by.get("data/pipeline/runs/series10_v1/images/sheets/lin_wan/lin_wan_lookA_s101.png")
    if s101:
        assert s101["item_check"] == "unchecked" and "短款西装外套" in s101.get("item_check_note", "")


def _sr(chars, subject=None):
    from types import SimpleNamespace
    return SimpleNamespace(subject=subject, characters=chars)


def test_single_turn_line_only_for_single_person_face_shots():
    """K-REN-704：单人在画 → 身份脸那一句后面加“四分之三侧脸，脸转向<剧本落点>一侧，脸和身体都不正对镜头”"""
    from ns_agent import asset_refs as AR
    shot = {"img_prompt": "特写，平视，林晚坐着，视线落在屏幕下方，嘴角轻轻抿着", "extras": []}
    one = [{"character": "lin_wan", "name": "林晚", "presence": "在画"}]
    line = AR.single_turn_line(_sr(one), shot)
    assert line == "林晚的眼睛看着屏幕下方，头和视线都朝向屏幕下方，眼睛不看镜头。林晚四分之三侧脸，脸转向屏幕下方一侧，脸和身体都不正对镜头。"
    assert AR.SINGLE_TURN_RE.fullmatch(line)
    assert not re.search(r"看着镜头|朝向镜头|toward the camera", line)
    two = one + [{"character": "gu_chen", "name": "顾沉", "presence": "在画"}]
    assert AR.single_turn_line(_sr(two), shot) == ""                       # 双人镜走 K-REN-703
    assert AR.single_turn_line(_sr(one, "part"), shot) == ""               # 局部特写不加
    assert AR.single_turn_line(_sr(one), {"img_prompt": "全景，林晚的背影", "extras": []}) == ""
    # 剧本没写落点 → 固定兜底，不编剧情
    assert "画面里的人或物" in AR.single_turn_line(_sr(one), {"img_prompt": "近景，林晚站着", "extras": []})


def test_single_turn_goes_first_in_prefix():
    from ns_agent import asset_refs as AR
    face = AR.Slot(1, "face", "f.png", "lin_wan", ["脸"], [{}], line="图1是林晚的脸部参考（只取脸和发型）。")
    sheet = AR.Slot(2, "sheet", "s.png", "lin_wan", ["设定图"], [{}], line="图2是设定图。")
    plan = AR.SlotPlan("ep01-S1", "qwen_image_2.1", 3, [face, sheet], [], face.line + sheet.line, False, [], [])
    AR._apply_single_turn(plan, "林晚四分之三侧脸，脸转向屏幕一侧，脸和身体都不正对镜头。")
    assert plan.prompt_prefix == "林晚四分之三侧脸，脸转向屏幕一侧，脸和身体都不正对镜头。图1是林晚的脸部参考（只取脸和发型）。图2是设定图。"


def test_compiled_jobs_single_person_have_turn_line_two_person_dont():
    """重编后的作业（real data 只读）：ep01-S1/S2 单人镜带朝向句；双人镜不带"""
    from ns_agent import asset_refs as AR
    jp = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"
    jobs = {j["shot"]: j for j in json.loads(jp.read_text(encoding="utf-8"))["jobs"]}
    if not AR.SINGLE_TURN_RE.search(jobs["ep01-S1"]["prompt"]):
        import pytest
        pytest.skip("作业尚未按 K-REN-704 重编")
    for sid in ("ep01-S1", "ep01-S2", "ep01-S6"):
        assert AR.SINGLE_TURN_RE.search(jobs[sid]["prompt"]), sid
    for j in jobs.values():
        if len(j.get("on_screen") or []) >= 2:
            assert not AR.SINGLE_TURN_RE.search(j["prompt"]), j["shot"]


def test_closeup_outer_items_only_visible_zone():
    """IMGFIX 21:5x：特写只补景别内看得到的单品（不补下装，免得把特写拉成中景）；近景照旧补全部服装件"""
    from types import SimpleNamespace
    from ns_agent import frame_job as FJ
    sr = SimpleNamespace(characters=[{"character": "lin_wan", "look": "A", "name": "林晚", "presence": "在画"}])
    ep = {"number": 1}
    close = {"img_prompt": "特写，平视，林晚坐在桌前，细银链贴在锁骨上，视线落在屏幕下方，嘴角轻轻抿着"}
    near = {"img_prompt": "近景，平视，林晚站在桌前，细银链在锁骨，视线落在画面右侧的桌沿"}
    c = [x for _n, _l, xs in FJ.outer_items("series10_v1", ep, close, sr, body=close["img_prompt"]) for x in xs]
    n = [x for _n, _l, xs in FJ.outer_items("series10_v1", ep, near, sr, body=near["img_prompt"]) for x in xs]
    assert not any("裙" in x for x in c), c
    assert any("裙" in x for x in n), n
