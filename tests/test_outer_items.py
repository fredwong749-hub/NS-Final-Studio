"""K-REN-101 外层单品（总调度 11-01 07:35；VIDEO10 查出 ep01 首帧丢了造型 A 的短款西装外套）：
本镜景别可见的造型单品，正文没写到的要用固定说明补进出图正文；剧本原文不改；ns_api.unified_stale.match_target 认得出这句，
新出的版本不被误标过期。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "services/api"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import frame_job as FJ  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402

pytestmark = pytest.mark.skipif(not (ROOT / "data" / "import" / "script_v2.json").exists(), reason="系统剧本不在本机")


def _job(sid, img=None):
    s = P.load_script()
    ep, sh = P.find_shot(s, sid)
    if img is not None:
        sh = sh.model_copy(update={"img_prompt": img})
    return FJ.build_first(UF.project_for(s), ep, sh, s.globals), sh


def test_blazer_named_when_img_omits_it():
    j, sh = _job("ep01-S1")
    assert "短款西装外套" not in (sh.img_prompt or "")                       # 剧本原文确实没写
    notes = FJ.OUTER_NOTE_RE.findall(j["prompt"])
    assert notes and "短款西装外套" in notes[0] and notes[0].startswith("林晚本镜造型A")
    i_note, i_suffix = j["prompt"].find(notes[0]), j["prompt"].rfind("。") 
    assert i_note > j["prompt"].find("图1")                                  # 在槽位标注之后（正文末尾、风格后缀之前）


def test_no_note_when_img_already_names_item():
    j0, sh = _job("ep01-S1")
    j, _ = _job("ep01-S1", img=(sh.img_prompt or "") + "，外罩短款西装外套")
    notes = FJ.OUTER_NOTE_RE.findall(j["prompt"])
    assert not any("短款西装外套" in n for n in notes)
    assert P.load_script().episodes[0].shots[0].img_prompt == sh.img_prompt   # 不改剧本


def test_unified_stale_recognises_note():
    from ns_api import unified_stale as US
    j, sh = _job("ep01-S1")
    s = P.load_script()
    ep, _ = P.find_shot(s, "ep01-S1")
    body = US.unified_bodies(s, ep, sh)["image"]
    assert US.match_target(j["prompt"], body) and j["prompt"].endswith(US.match_target(j["prompt"], body))
