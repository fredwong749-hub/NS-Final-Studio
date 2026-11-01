"""ASSETMASTER 资产盘点：抽取、归一、造型匹配与矛盾判定（只用内存数据，不读资产库图片）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "assetmaster"))
import scan as S  # noqa: E402


def names(text):
    return [d["name"] for d in S.extract(text)]


def test_extract_strips_action_residue():
    assert "黑色漆皮长风衣" in names("双手捏住黑色漆皮长风衣前襟")
    assert "九串铁珠" in names("九串铁珠垂在腿侧")
    assert "旧银戒" in names("左手无名指旧银戒反着光")


def test_canon_nails_variants_merge():
    a = S.canon({"name": "为5厘米超长透明水晶甲", "cls": "nails_hand", "slot": "nails", "attrs": []})
    b = S.canon({"name": "钻石水晶甲", "cls": "nails_hand", "slot": "nails", "attrs": []})
    assert a["name"] == b["name"]


def test_same_item_shoe_conflict():
    clear = S.extract("透明12cm细高跟")[0]
    sneaker = S.extract("白球鞋")[0]
    side = S.extract("12cm侧开透明细高跟")[0]
    assert S.same_item(clear, side)
    assert not S.same_item(clear, sneaker)


def test_color_conflict_not_same():
    assert not S.same_item(S.extract("米白衬衫")[0], S.extract("黑色衬衫")[0])


def test_look_fields_items():
    f = S.parse_look_fields("服装=米白衬衫配深灰西装裙，外罩短款西装外套｜鞋=透明12cm细高跟｜饰品=细银链、钻石水晶甲")
    got = {d["name"] for d in S.items_of_fields(f)}
    assert {"米白衬衫", "深灰西装裙", "短款西装外套", "细银链"} <= got
