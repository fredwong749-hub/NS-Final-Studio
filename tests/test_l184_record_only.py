"""L-184（总调度 11-04 05:0x）：共用验收只记录范围按行标签扩——场景陈设（道具）子句、非点选配饰首尾帧只记录；
项目方点选 O1–O4 / SH1–SH2 首帧阻断、尾帧只记录；身份 / 主服装 / 人数 / 文字 / 手指仍阻断。标签取自 LookPart.slot +
owner_inputs + shot.scene_detail 字段，不从文字猜。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
for _p in ("services/agent", "services/render_router", "packages/schema"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from ns_agent.gen_contract import accept as A  # noqa: E402

LOOKS = {
    "lead_f": {"O4": NS(zh="服装=日常全身装", parts=[
        NS(label="日常全身装：黑色漆皮抹胸紧身短裙 + 透明尖头细高跟", slot="outfit", zone="body", item_id="O4_garment", extra=False),
        NS(label="透明尖头细高跟（PVC 鞋面）", slot="shoes", zone="feet", item_id="SH1", extra=False)])},
    "ch_j": {"A": NS(zh="服装=驼色皮夹克、黑色工装裤", parts=[
        NS(label="黑色短靴", slot="shoes", zone="feet", item_id="A_shoes1", extra=False),
        NS(label="右手腕缠两圈的黑色相机皮带", slot="accessory", zone="hand", item_id="A_acc1", extra=False)])},
    "ch_z": {"A": NS(zh="服装=酒红色西装套装", parts=[
        NS(label="金色细链手包", slot="accessory", zone="hand", item_id="A_acc1", extra=False),
        NS(label="鲜红色长指甲", slot="nails", zone="hand", item_id="A_nails1", extra=False),
        NS(label="酒红色西装套装、黑色丝质吊带衫", slot="outfit", zone="upper", item_id="A_outfit1", extra=False)])},
}
PICKS = {("lead_f", "O4"), ("lead_f", "SH1"), ("lead_f", "SH2")}
SHOT = {"scene_id": "sk_white_cyc", "scene_detail": "【现实段】环形灯架后的相机位，相机包敞开在灯架横杆上",
        "img_prompt": "江予白左肘撑在横杆上"}


def _job(cast, stage=None, zones=("face", "upper", "hand", "feet")):
    j = {"asset_refs": {"size": "中景", "zones": list(zones),
                        "characters": [{"character": c, "name": n, "presence": "在画", "look": l} for c, n, l in cast]}}
    if stage:
        j["stage"] = stage
    return j


def _bundle(rows, bad):
    return {"status": "fail" if bad else "pass", "items": [{"n": i, "ok": i not in bad, "text": "不符合" if i in bad else "符合"}
                                                         for i in range(1, len(rows) + 1)]}


def _judge(rows, bad, stage=None):
    items, tags = [t for t, _ in rows], [g for _, g in rows]
    b = A.description_record_only(_bundle(rows, bad), items, tags, stage)
    return b, A.verdict({}, {"identity": "pass", "prompt": b["status"]}, b)[0]


def _n(rows, tag):
    return [i + 1 for i, (_, g) in enumerate(rows) if g == tag]


def test_rows_tagged_from_slots_and_fields():
    rows = A.check_rows(_job([("ch_j", "江予白", "A"), ("ch_z", "卓琳", "A")]), SHOT, LOOKS, "r", PICKS)
    tags = [g for _, g in rows]
    assert tags == ["count", "outfit", "accessory", "outfit", "accessory", "scene", "props", "size", "desc", "text", "hands"]
    t = dict((g + str(i), x) for i, (x, g) in enumerate(rows))
    assert "黑色短靴" in t["outfit1"] and "相机皮带" in t["accessory2"] and "相机皮带" not in t["outfit1"]
    assert "酒红色西装套装" in t["outfit3"] and "金色细链手包" in t["accessory4"] and "鲜红色长指甲" in t["accessory4"]
    assert t["scene5"] == "场景是 sk_white_cyc" and "相机包敞开" in t["props6"] and "相机包" not in t["scene5"]
    # 没有服装单品的造型（V2 清单只登记了鞋 / 配饰）：主服装行用造型名，照样阻断
    rows2 = A.check_rows(_job([("ch_j", "江予白", "A")], zones=("face", "upper", "hand")), SHOT, LOOKS, "r", PICKS)
    assert [g for _, g in rows2][1:3] == ["outfit", "accessory"] and "驼色皮夹克" in rows2[1][0]


def test_props_and_accessory_record_only_both_stages():
    """S7 尾帧原样：相机皮带（配饰）+ 相机包（陈设）+ 描述 不符合 → 只记录、通过；首帧同样"""
    for stage in (None, "last"):
        rows = A.check_rows(_job([("ch_j", "江予白", "A"), ("ch_z", "卓琳", "A")], stage), SHOT, LOOKS, "r", PICKS)
        bad = set(_n(rows, "accessory") + _n(rows, "props") + _n(rows, "desc"))
        b, v = _judge(rows, bad, stage)
        assert b["status"] == "pass" and v == "pass", (stage, b)
        assert all(r["record_only"] for r in b["items"] if r["n"] in bad)


def test_main_outfit_scene_count_text_still_block():
    rows = A.check_rows(_job([("ch_j", "江予白", "A"), ("ch_z", "卓琳", "A")], "last"), SHOT, LOOKS, "r", PICKS)
    for tag in ("count", "outfit", "scene", "size", "text", "hands"):
        b, v = _judge(rows, {_n(rows, tag)[0]}, "last")
        assert b["status"] == "fail" and v == "reject", tag


def test_owner_pick_blocks_first_record_only_last():
    """S8 原样：祁念 O4（项目方点选）不符合 → 首帧阻断，尾帧只记录"""
    rows = A.check_rows(_job([("lead_f", "祁念", "O4")]), SHOT, LOOKS, "r", PICKS)
    assert [g for _, g in rows][:3] == ["count", "owner_pick", "scene"]
    assert "透明尖头细高跟（PVC 鞋面）" in rows[1][0] and "项目方指定造型 O4" in rows[1][0]
    k = _n(rows, "owner_pick")[0]
    b, v = _judge(rows, {k}, None)
    assert b["status"] == "fail" and v == "reject"
    rows_l = A.check_rows(_job([("lead_f", "祁念", "O4")], "last"), SHOT, LOOKS, "r", PICKS)
    b, v = _judge(rows_l, {k}, "last")
    assert b["status"] == "pass" and v == "pass" and b["items"][k - 1]["record_only"]
    # judge_bundle：Q2 未判时取第 2 条，尾帧只记录 = 不算 fail
    lab, _ = A.judge_bundle({"items": [{"id": "Q2", "status": "na"}]}, {"status": "pass"}, b)
    assert lab["outfit"] == "pass"


def test_unpicked_look_of_lead_not_relaxed_and_no_tags_keeps_l183():
    """没登记点选（picks 空）→ 主服装照样阻断；旧调用不带标签 = 只认描述行（L-183 原口径）"""
    rows = A.check_rows(_job([("lead_f", "祁念", "O4")], "last"), SHOT, LOOKS, "r", set())
    assert [g for _, g in rows][1] == "outfit"
    b, _ = _judge(rows, {2}, "last")
    assert b["status"] == "fail"
    items = [t for t, _ in rows]
    bad = set(_n(rows, "props")) | set(_n(rows, "desc"))
    old = A.description_record_only(_bundle(rows, bad), items)
    assert old["status"] == "fail" and old["record_only_rows"] == _n(rows, "desc")


def test_owner_picks_from_v2_manifest():
    p = A.owner_picks("series10_v2")
    assert {("lead_f", "O1"), ("lead_f", "O4"), ("lead_f", "SH1"), ("lead_f", "SH2")} <= p
    assert not any(c != "lead_f" for c, _ in p)
    assert A.owner_picks(None) == set()
