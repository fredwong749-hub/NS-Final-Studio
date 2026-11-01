"""Qwen Image 2.1 出图提示词 lint（tools/bakeoff/qwen21_lint.py）：knowledge/rules/render_qwen21.yaml 的检查。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bakeoff_qwen21_lint", ROOT / "tools" / "bakeoff" / "qwen21_lint.py")
QL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(QL)


def ids(p, **kw):
    return {x["id"] for x in QL.lint(p, **kw)}


def test_close_up_with_lower_garments_is_flagged():
    p = "特写构图：只拍头部与肩颈，胸口以下不入画，林晚穿米白衬衫，跟高12厘米，林晚本镜造型A要穿全：深灰铅笔裙——及膝裙"
    assert "QL01" in ids(p, size="特写")
    assert "QL01" not in ids("中全景构图，林晚坐在转椅上，深灰铅笔裙，透明细高跟", size="中全景")


def test_part_close_up_with_identity_block_is_flagged():
    p = "大特写构图：只拍手这一局部，手占画面大半，不出现完整人物全身，【林晚】22岁中国成年女性，阿岚的手按在林晚肩头"
    assert "QL02" in ids(p, size="大特写")


def test_negations_raw_ids_and_weights():
    r = ids("近景构图，林晚不看镜头，sk_studio 器械台边，(skin texture:1.3)，【场景】名称：工作室")
    assert {"QL03", "QL05", "QL12"} <= r


def test_two_faces_clear_but_one_blurred_foreground():
    assert "QL06" in ids("近景构图，两人同框，两张脸都清晰入画，顾沉在前景虚化")
    assert "QL06" not in ids("近景构图，两人同框，两张脸都清晰入画，各自至少四分之三侧脸朝向镜头，不背对镜头")


def test_official_reference_tag_and_face_description():
    p = "图1是林晚的脸部参考（只取脸和发型）。近景构图，【林晚】22岁中国成年女性，冷白皮肤，自然深棕色眼睛，焦点锐利"
    r = ids(p)
    assert {"QL11", "QL13", "QL14", "QL15"} <= r
    assert "QL11" not in ids("<image1>是林晚的脸部参考。近景构图，林晚低头看手机")
