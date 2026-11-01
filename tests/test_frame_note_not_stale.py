"""K-REN-136（DATAALIGN 11-01）：frame_v9 正文里系统加的固定句（槽位不足说明，frame_job.with_note）不能让刚出的图被判过期。
走遍 with_note 的每条路径：无说明 / 一人 / 多人 / 正文带风格后缀 / 不带后缀 / 画布整段替换正文（prompt_override），
以及 first_frame_jobs.json 里真实带说明的作业——unified_stale.match_target 都必须还原出版本提示词里的正文。"""
import itertools
import json
from pathlib import Path

import pytest

from ns_agent import asset_refs as AR
from ns_agent import frame_job as FJ
from ns_agent.gen_contract import style as ST
from ns_api import unified_stale as UST

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["林晚", "顾沉", "陈宇", "阿岚"]
PREFIX = "图1是林晚的脸部参考（只取脸和发型）。"
BODIES = [f"中景构图（膝盖以上），【林晚】22岁中国成年女性，她站在窗边，{ST.image_suffix()}",   # 带系统风格后缀
          "近景构图（胸部以上），林晚回头看向镜头"]                                         # 不带后缀（兜底分支）


def _notes():
    yield ""
    for k in (1, 2, 3):
        for names in itertools.permutations(NAMES, k):
            yield "".join(AR.TEXT_FALLBACK_NOTE.format(name=n) for n in names)


@pytest.mark.parametrize("body", BODIES)
def test_every_with_note_path_matches(body):
    for note in _notes():
        full = FJ.with_note(body, note)
        prompt = PREFIX + full
        assert UST.match_target(prompt, body) == full, note
        assert prompt.endswith(UST.match_target(prompt, body))


def test_prompt_override_path_matches():
    """画布整段替换：build_first 把说明同样用 with_note 加在替换正文上"""
    ov = f"林晚坐在床边，{ST.image_suffix()}"
    note = AR.TEXT_FALLBACK_NOTE.format(name="顾沉")
    full = FJ.with_note(ov, note)
    assert UST.match_target(PREFIX + full, ov) == full


def test_changed_body_still_stale():
    note = AR.TEXT_FALLBACK_NOTE.format(name="顾沉")
    old = FJ.with_note(BODIES[0].replace("窗边", "门边"), note)
    assert not (PREFIX + old).endswith(UST.match_target(PREFIX + old, BODIES[0]))


def test_real_jobs_with_note_not_stale():
    jp = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"
    if not jp.exists():
        pytest.skip("没有 series10 作业文件")
    jobs = [j for j in json.loads(jp.read_text(encoding="utf-8"))["jobs"] if AR.TEXT_FALLBACK_RE.search(j.get("prompt") or "")]
    assert jobs, "作业文件里应有槽位不足的镜（双人镜）"
    import re
    notes = re.compile(r"(?:(?:" + "|".join(rx.pattern for rx in AR.TEXT_NOTE_RES) + r")[。，])+")   # 全部系统说明（含 K-REN-101 外层单品）
    for j in jobs:
        p = j["prompt"]
        body = re.sub(r"^(图\d+是[^。]*。)*", "", p)          # 去掉参考标注
        bare = notes.sub("", body, count=1)                   # 现在的编译器正文（不带说明）
        assert UST.match_target(p, bare) == body, j["shot"]
