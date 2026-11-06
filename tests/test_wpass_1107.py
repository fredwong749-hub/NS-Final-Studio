"""W-PASS 11-07（ep02 psm7 21:53 后首帧 19 张只过 4 张的根因修复）：
① Q1 不再要求“在画但不露脸”的人出脸（过肩前景只露肩 / 后脑、背影：作业 cast.face_hidden / asset_refs back_view），
   与编译（不送脸）、预检（K-REN-957）、人数闸（下限不计）同口径；他的脸真露出来照样要认得出；
② Q1 一张脸只认给一个角色（原来祁念那一张脸同时被认成黎岸 0.113 → “黎岸不像”）；
③ 首帧首句只取 **机位与景别** 第三段的起幅（“起幅：…；落幅：…”整段进首帧 → ep02-S8 画成上下两格拼图），尾帧沿用第三段时只取落幅。
全部离线，不碰 GPU / 服务器。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "packages/render", "packages/qc", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent.gen_contract import postflight as PF  # noqa: E402
from ns_schema import prompt_v2 as PV  # noqa: E402

LOC = {"Q2": [], "Q4": None, "Q7": None}
REC = {"size": "中近景", "subject": None, "zones": ["face"], "primary": "lin_wan", "slots": [], "missing": []}


def _q1(req, faces):
    return next(i for i in PF.evaluate("x.png", req, remote={"faces": faces, "text": []}, local=LOC).items if i.id == "Q1")


def _ots_req(hidden_via="cast"):
    cast = [{"name": "林晚", "presence": "在画", "x": "左", "depth": "中"},
            {"name": "顾沉", "presence": "在画", "x": "右", "depth": "前"}]
    rec = dict(REC)
    if hidden_via == "cast":
        cast[1].update(face_hidden=True, hidden_part="右肩与后脑")
    else:
        rec["characters"] = [{"character": "lin_wan", "presence": "在画", "primary": True},
                             {"character": "gu_chen", "presence": "在画", "back_view": True}]
    return {"asset_refs": rec, "cast": cast}


# ep02-S2 v5 实测：只有祁念一张脸（0.841），黎岸是前景只露右肩与后脑
LW = {"h_ratio": 0.158, "bbox": [150, 300, 260, 480], "sims": {"lin_wan": 0.841, "gu_chen": 0.113}}


@pytest.mark.parametrize("via", ["cast", "asset_refs"])
def test_q1_ots_foreground_face_not_required(via):
    q1 = _q1(_ots_req(via), [LW])
    assert q1.status == "pass", q1.detail
    assert "gu_chen" not in (q1.evidence.get("sims") or {})


def test_q1_ots_foreground_face_shown_still_must_be_recognised():
    # ep02-S13 v1：前景男人露出侧脸、谁都不像（0.145）→ 仍按“认不出是谁”不过；像本人 → 放行
    stranger = {"h_ratio": 0.195, "bbox": [600, 200, 760, 460], "sims": {"lin_wan": 0.05, "gu_chen": 0.145}}
    q1 = _q1(_ots_req(), [LW, stranger])
    assert q1.status == "fail" and "认不出是谁" in q1.detail
    him = {**stranger, "sims": {"lin_wan": 0.05, "gu_chen": 0.71}}
    assert _q1(_ots_req(), [LW, him]).status == "pass"


def test_q1_one_face_is_claimed_by_one_character_only():
    # 两人都要露脸、画面只出一张脸：这张脸归最像的林晚，顾沉 = 未出脸（不再拿林晚的脸算成“顾沉 0.113 不像”）
    req = {"asset_refs": REC, "cast": [{"name": "林晚", "presence": "在画"}, {"name": "顾沉", "presence": "在画"}]}
    q1 = _q1(req, [LW])
    assert q1.status == "fail" and "gu_chen 未出脸" in q1.detail and "gu_chen 0.113" not in q1.detail
    pf = q1.evidence["per_face"]
    assert pf[0]["as"] == "lin_wan" and pf[0]["verdict"] == "过"


def test_q1_two_faces_still_matched_each_to_own():
    req = {"asset_refs": REC, "cast": [{"name": "林晚", "presence": "在画"}, {"name": "顾沉", "presence": "在画"}]}
    gc = {"h_ratio": 0.15, "bbox": [500, 300, 600, 480], "sims": {"lin_wan": 0.12, "gu_chen": 0.74}}
    q1 = _q1(req, [gc, LW])
    assert q1.status == "pass", q1.detail
    assert q1.evidence["sims"] == {"lin_wan": 0.841, "gu_chen": 0.74}


def test_q1_described_hidden_person_still_required():
    # 原文写到他的脸（face_described）→ 不按不露脸处理
    req = _ots_req()
    req["asset_refs"] = {**REC, "characters": [{"character": "gu_chen", "presence": "在画", "face_described": True}]}
    assert _q1(req, [LW]).status == "fail"


def test_start_end_split():
    assert PV.start_end("起幅：A 在左，看桌面；落幅：近景（推进一档），B 居中") == ("A 在左，看桌面", "近景（推进一档），B 居中")
    assert PV.start_end("起幅=A → 落幅=B") == ("A", "B")
    assert PV.start_end("双人在画，两张脸都在焦点上") == ("双人在画，两张脸都在焦点上", "")
    assert PV.start_end("") == ("", "")


def test_last_angle_field_fallback_takes_end_part():
    from ns_agent import frame_job as FJ
    shot = {"cast": [], "extras": [{"label": "机位与景别", "text": "中景｜平视｜起幅：手机亮着；落幅：手机扣在方向盘上"}]}
    out = FJ.last_angle_field(shot, "中景，手机扣在方向盘上")
    assert out.endswith("手机扣在方向盘上") and "起幅" not in out and "手机亮着" not in out


SCRIPT = ROOT / "data/import/runs/series10_v2/script_v2.json"


def _ep02_has_start_end() -> bool:
    try:
        return "起幅：" in SCRIPT.read_text(encoding="utf-8") and "ep02" in SCRIPT.read_text(encoding="utf-8")
    except OSError:
        return False


@pytest.mark.skipif(not _ep02_has_start_end(), reason="series10_v2 导入稿（psm7 起幅 / 落幅写法）不在")
def test_first_frame_prompt_has_start_only_real_ep02_s8():
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_schema import script as S
    script = S.ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))
    ep, shot = P.find_shot(script, "ep02-S8")
    angle = next((e.text for e in shot.extras or [] if "机位与景别" in str(e.label)), "")
    if "落幅" not in angle:
        pytest.skip("本镜机位与景别没写起幅 / 落幅")
    job = FJ.build_first("series10_v2", ep, shot, script.globals)
    assert "落幅" not in job["prompt"] and "起幅" not in job["prompt"]
    start, end = PV.start_end(PV.split_field(angle)[2])
    assert start[:12] in job["prompt"] and end[:12] not in job["prompt"]


def test_hidden_person_turned_face_judged_at_identity_line():
    """复审 11-07：背身者（face_hidden）若转身露脸，用身份线判（不是 recognize_floor 0.45）——0.50 不能当“其他脸：可放行”"""
    import inspect
    from ns_agent.gen_contract import postflight as PF
    src = inspect.getsource(PF)
    assert "(c in described or c in hidden_ids) and c not in got" in src
