"""L-188 L1：平光禁用词（QW-L1）/ 多人三层构图（QW-L2）代码判定（K-WRT-807 / 808）"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


RC = _load("rubric_code_l1t", "tools/script_rsi/rubric_code.py")
WL = _load("writer_lints_l1t", "tools/qa/writer_lints.py")


def shot(i, names=("林晚",), pres="在画"):
    return NS(index=i, cast=[NS(name=n, presence=pres) for n in names])


GOOD_COMP = "**构图**：前景=顾沉的肩略在焦外｜中景=林晚在焦点上｜背景=白幕与灯架"
GOOD_LIGHT = "**灯光**：动机光源=左侧大窗，光比 3:1，右侧黑旗负补光，背景比人物低一档"


def test_flat_light_phrases_blocked_in_light_scene_lines():
    for phrase in ("正面高亮", "把影子打平", "白幕反射补脸"):
        r = RC.l1_checks([shot(1)], [f"**镜1｜img**：x\n**灯光**：{phrase}，3:1"])
        assert "flat#1" in r and not r["flat#1"][0], phrase
    assert "flat#1" in RC.l1_checks([shot(1)], ["**镜1｜img**：x\n**场景**：白幕影棚，正面高亮"])
    assert "flat#1" in RC.l1_checks([shot(1)], ["**镜1｜img**：x\n**光线**：把影子打平"])


def test_motivated_light_passes_and_other_lines_not_scanned():
    assert RC.l1_checks([shot(1)], ["**镜1｜img**：x\n" + GOOD_LIGHT]) == {}
    assert RC.l1_checks([shot(1)], ["**镜1｜img**：正面高亮的白幕\n**灯光**：窗外冷光从左侧来 3:1"]) == {}   # 只扫灯光 / 光线 / 场景行


def test_multi_person_needs_three_layers():
    two = ("林晚", "顾沉")
    assert RC.l1_checks([shot(1, two)], ["**镜1｜img**：x\n" + GOOD_COMP]) == {}
    bad = RC.l1_checks([shot(1, two)], ["**镜1｜img**：x\n**构图**：前景=顾沉的肩｜中景=林晚"])
    assert "layers#1" in bad and "背景" in bad["layers#1"][1]
    assert "layers#1" in RC.l1_checks([shot(1, two)], ["**镜1｜img**：x"])           # 没写构图
    assert RC.l1_checks([shot(1)], ["**镜1｜img**：x\n**构图**：中景"]) == {}            # 单人不要求
    assert RC.l1_checks([shot(1, two, pres="局部")], ["**镜1｜img**：x"]) == {}         # 局部不算在画
    assert RC.l1_checks([shot(1, two)], ["**镜1｜img**：x\n**构图**：前景=甲｜中景=乙｜后景=丙"]) == {}


def test_writer_lint_check_l1(monkeypatch):
    text = "# t\n## ep01《a》\n**镜1｜img**：x\n**灯光**：正面高亮\n"
    ep = NS(number=1, shots=[shot(1)])
    out = WL.check_l1(ep, text)
    assert [i["rule_id"] for i in out] == ["QW-L1"]
    WL.WRITER_LINT_LEVEL = "block"
    try:
        assert WL.check_l1(ep, text)[0]["level"] == "block"
    finally:
        WL.WRITER_LINT_LEVEL = "warn"
