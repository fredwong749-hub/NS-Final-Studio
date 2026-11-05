"""L-196（项目方 11-05“我需要你全自动，不要检测那么多了”）：闸门只留 Q1 / count / text / adult，其余只记录；用尽自动采用最高分版。"""
import copy
import json
from pathlib import Path

from ns_agent.gen_contract import blocking as BL

ROOT = Path(__file__).resolve().parents[1]
CONF = {"blocking_items": ["Q1", "count", "text", "adult"]}


def _pf(*items):
    return {"ok": False, "blocking": [i["id"] for i in items], "items": list(items), "reasons": []}


def _it(i, st="fail", **ev):
    return {"id": i, "status": st, "detail": "x", "evidence": ev}


def test_config_lists_hard_items():
    d = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    assert d["blocking_items"] == ["Q1", "count", "text", "adult"]
    p = json.loads((ROOT / "config/pipeline/producer.json").read_text(encoding="utf-8"))
    assert p["review_adopt_auto"] is True and p["accept"]["run_qb"] is False


def test_soft_items_never_block():
    pf = BL.apply(_pf(_it("Q2"), _it("Q9", defects=["eye_contact"]), _it("Q10", identity={"status": "pass"}, count={"status": "pass"}),
                      _it("QB", label={"identity": "pass", "count": "pass", "age": "pass", "ocr": "pass", "prompt": "fail"})), copy.deepcopy(CONF))
    assert pf["ok"] is True and pf["blocking"] == [] and "score_infra" not in pf
    assert all(i["status"] == "na" and i["record_only"] for i in pf["items"])


def test_hard_items_still_block():
    assert BL.apply(_pf(_it("Q1")), CONF)["blocking"] == ["Q1"]
    assert BL.apply(_pf(_it("Q6")), CONF)["blocking"] == ["Q6"]
    assert BL.apply(_pf(_it("Q9", defects=["underage_look"])), CONF)["blocking"] == ["Q9"]
    assert BL.apply(_pf(_it("Q9", defects=["extra_person"])), CONF)["ok"] is False
    assert BL.apply(_pf(_it("Q10", count={"status": "fail"})), CONF)["blocking"] == ["Q10"]
    assert BL.apply(_pf(_it("QB", label={"count": "fail"})), CONF)["blocking"] == ["QB"]
    assert BL.apply(_pf(_it("QB", label={"age": "fail"})), CONF)["ok"] is False


def test_no_key_keeps_old_behaviour():
    pf = _pf(_it("Q2"))
    assert BL.apply(pf, {})["blocking"] == ["Q2"]
