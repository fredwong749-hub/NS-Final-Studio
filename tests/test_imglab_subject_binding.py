"""K-REN-901 删句保主语 / K-REN-902 特写双人露脸冲突（IMGLAB 11-02，ep06-S2 v6 顾沉长出林晚的蓝色长发）。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/prompt_v2", "tools/pipeline", "tools/imglab"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import framing as FR  # noqa: E402

EP06_S2 = ("特写，平视，林晚跪坐在深色木地板上，黑色漆皮束腰配黑色漆皮短裙，雾霾天蓝色及腰直发齐刘海，右手抬起接纸；"
           "顾沉站在画面右侧，白衬衫袖口卷起，左手把一页纸递到她面前")
NAMES = ["林晚", "顾沉"]


def test_strip_fullbody_keeps_subjects():
    out = FR.strip_fullbody(EP06_S2, subjects=NAMES)
    assert "跪坐" not in out and "站在" not in out
    # 林晚的发色归林晚、白衬衫归顾沉：名字紧挨在各自描写之前
    assert out.index("林晚") < out.index("雾霾天蓝色") < out.index("顾沉") < out.index("白衬衫")


def test_strip_fullbody_old_behaviour_without_subjects():
    out = FR.strip_fullbody(EP06_S2)
    assert "林晚" not in out and "顾沉" not in out      # 旧行为（不给 subjects）逐字不变


def test_switch_off_restores_old(monkeypatch):
    monkeypatch.setattr(FR, "keep_subject_enabled", lambda: False)
    assert FR.strip_fullbody(EP06_S2, subjects=NAMES) == FR.strip_fullbody(EP06_S2)


def test_object_name_is_not_subject():
    # ep08-S2：“站在林晚侧后方半步”里林晚是宾语，删掉后不能把林晚补成后面描写的主语
    t = "特写，平视，顾沉穿白衬衫，黑色短发向后梳齐，站在林晚侧后方半步，左手无名指旧银戒反着光"
    out = FR.strip_fullbody(t, subjects=NAMES)
    assert "林晚" not in out and out.startswith("特写，平视，顾沉穿白衬衫")


def test_filter_parts_keeps_subject():
    # 中近景隐藏下半身部件：“陈宇穿米色针织衫配卡其裤”被删时，主语陈宇补回（ep09-S7）
    t = "中近景，平视机位，陈宇穿米色针织衫配卡其裤，手腕红绳搭在杯沿；林晚穿黑色漆皮束腰配黑色漆皮短裙，雾霾天蓝色及腰直发"
    size = "中近景"
    if not FR.hidden_words(size):
        pytest.skip("中近景没有隐藏部件配置")
    out = FR.filter_parts(t, size, subjects=["林晚", "陈宇"])
    assert out.index("陈宇") < out.index("手腕红绳") < out.index("林晚") < out.index("雾霾")


def test_no_name_after_generic_clause():
    t = "特写，平视，林晚站在窗前，真实皮肤质感，可见细小毛孔"
    assert FR.strip_fullbody(t, subjects=["林晚"]) == "特写，平视，真实皮肤质感，可见细小毛孔"


def test_two_face_close_conflict_and_clash():
    assert FR.two_face_close_conflict("特写", "face", 2)
    assert not FR.two_face_close_conflict("特写", "face", 1)
    assert not FR.two_face_close_conflict("近景", "face", 2)
    assert not FR.two_face_close_conflict("特写", "part", 2)
    assert FR.framing_clash("特写构图：…脸部占画面约六成…，两人同框，两张脸都清晰入画")
    assert not FR.framing_clash(FR.TWO_FACE_CLOSE_LEAD + "，两人同框，两张脸都清晰入画")


def test_all_shots_zero_orphans_zero_clash():
    """全量导入稿（只读）：每镜编译后正文的每个小句归属人与剧本一致；无构图矛盾"""
    import orphan_check as O
    if not (ROOT / "data/import/script_v2.json").exists():
        pytest.skip("没有导入稿")
    r = O.check()
    assert r["checked"] >= 1
    assert r["orphans"] == 0, [x for x in r["rows"] if x["orphans"]][:3]
    assert r["clash_shots"] == 0


# ---- K-REN-903 全员局部（不露脸）----
def test_narrow_lock_keeps_adult_drops_age_and_hair():
    lk = "【林晚】22岁中国成年女性，蓝发及腰，齐刘海，冷白皮肤，手指甲为5厘米超长透明水晶甲"
    out = FR.narrow_lock(lk, "手与肩颈")
    assert out.startswith("【林晚】成年女性") and "22岁" not in out and "蓝发" not in out and "刘海" not in out
    assert "水晶甲" in out
    assert "蓝发" in FR.narrow_lock(lk, "发梢")          # 局部含“发”时保留发色句


def test_partial_lead_has_chin_top():
    lead = FR.closeup_lead("近景", "part", "阿岚戴皮手套的手按在林晚肩头", partial=True)
    assert lead.startswith("近景构图：画面里只有手与肩颈") and "下颌以下" in lead
    assert FR.closeup_lead("近景", "part", "手") == FR.lead("近景")     # 非全员局部：近景仍走旧首句


def test_partial_only_switch(monkeypatch):
    class C:  # 最小 cast 桩
        def __init__(self, n, p, part=""):
            self.name, self.presence, self.part = n, p, part
    class S:
        img_prompt = "近景（手与肩颈），阿岚戴皮手套的手按在林晚肩头"
        cast = [C("林晚", "局部", "肩头"), C("阿岚", "局部", "手")]
    assert FR.partial_only(S, ["林晚", "阿岚"])
    monkeypatch.setattr(FR, "partial_only_enabled", lambda: False)
    assert not FR.partial_only(S, ["林晚", "阿岚"])


def test_all_shots_noface_terms_zero():
    import orphan_check as O
    if not (ROOT / "data/import/script_v2.json").exists():
        pytest.skip("没有导入稿")
    r = O.check()
    assert r["noface_shots"] == 0, [x for x in r["rows"] if x["noface_terms"]][:3]
