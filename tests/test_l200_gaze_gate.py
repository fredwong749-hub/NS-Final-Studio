"""L-200（项目方 11-06 看 ep01 总览：S1 三人正面排排站看镜头被“用尽采用最好一版”采用）：首帧硬闸加“视线 / 排排站”——
Q9 看图 eye_contact / lineup、G1 YuNet 看镜头 = 挡、换种子重出；看图与 G1 都有结论时以看图为准；这类版本任何采用路径都不收。"""
import copy
import json
import sys
from pathlib import Path

from ns_agent.gen_contract import blocking as BL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import producer as PR  # noqa: E402

CONF = {"blocking_items": ["Q1", "count", "text", "adult", "gaze"]}
OLD = {"blocking_items": ["Q1", "count", "text", "adult"]}


def _pf(*items):
    return {"ok": False, "blocking": [i["id"] for i in items], "items": list(items), "reasons": []}


def _it(i, st="fail", **ev):
    return {"id": i, "status": st, "detail": "x", "evidence": ev}


def _q9(defects, st="fail", model="qwen3-vl"):
    return _it("Q9", st, defects=list(defects), model=model)


# ---------------------------------------------------------------- 配置
def test_config_has_gaze_hard_item_and_lineup_check():
    gc = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    assert gc["blocking_items"] == ["Q1", "count", "text", "adult", "gaze", "FL"] and "L-200" in gc["_blocking_items"]   # L-203 加 FL
    vq = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    assert vq["checks"]["eye_contact"]["blocking"] is True
    assert vq["checks"]["lineup"]["blocking"] is True and vq["checks"]["lineup"]["contract"] == "Q9"
    tpl = (ROOT / "config/prompts/vqa_inspect.md").read_text(encoding="utf-8")
    assert '"lineup":' in tpl and tpl.count("- lineup：") == 1        # 同一次看图调用多一项
    assert BL.Q9_HARD["gaze"] == BL.GAZE_DEFECTS == {"eye_contact", "lineup"}
    assert set(PR.GAZE_DEFECTS) == BL.GAZE_DEFECTS


# ---------------------------------------------------------------- blocking
def test_q9_gaze_defects_block():
    assert BL.apply(_pf(_q9(["eye_contact"])), CONF)["blocking"] == ["Q9"]
    assert BL.apply(_pf(_q9(["lineup"])), CONF)["blocking"] == ["Q9"]
    pf = BL.apply(_pf(_q9(["eye_contact"])), copy.deepcopy(OLD))            # L-196 旧清单：照旧只记录
    assert pf["ok"] is True and pf["items"][0]["record_only"]


def test_g1_blocks_when_vqa_has_no_verdict():
    pf = BL.apply(_pf(_it("G1", gaze="疑似看镜头")), CONF)
    assert pf["blocking"] == ["G1"] and pf["ok"] is False
    pf = BL.apply(_pf(_it("G1", gaze="疑似看镜头"), _q9([], "untested", model=None)), CONF)   # 看图没跑成 → G1 自己挡
    assert "G1" in pf["blocking"]
    assert BL.apply(_pf(_it("G1")), copy.deepcopy(OLD))["ok"] is True                        # 旧清单不挡 G1


def test_vqa_verdict_overrides_yunet():
    pf = BL.apply(_pf(_it("G1", gaze="疑似看镜头"), _q9([], "pass")), CONF)                  # 看图真看过、没报视线缺陷
    assert pf["ok"] is True and pf["blocking"] == []
    g1 = next(i for i in pf["items"] if i["id"] == "G1")
    assert g1["status"] == "na" and g1["record_only"] and g1["status_recorded"] == "fail"
    pf = BL.apply(_pf(_it("G1", gaze="疑似看镜头"), _q9(["eye_contact"])), CONF)             # 两边都说看镜头 → 都挡
    assert pf["blocking"] == ["G1", "Q9"]


def test_vqa_gaze_verdict_helper():
    assert BL.vqa_gaze_verdict(_pf(_q9([], "pass"))) is True
    assert BL.vqa_gaze_verdict(_pf(_q9(["lineup"]))) is False
    assert BL.vqa_gaze_verdict(_pf(_q9([], "untested", model=None))) is None
    assert BL.vqa_gaze_verdict(_pf(_it("Q1"))) is None


# ---------------------------------------------------------------- 采用排除
def test_gaze_bad_detects_vqa_and_yunet():
    assert PR.gaze_bad(_pf(_q9(["eye_contact"])))
    assert PR.gaze_bad(_pf(_q9(["lineup"], "na")))                                          # 只记录的旧判定也算
    assert PR.gaze_bad(_pf(_it("G1")))
    assert not PR.gaze_bad(_pf(_it("G1", "na", would_fail=True)))                           # YuNet 只记录（未标定）不算
    assert not PR.gaze_bad(_pf({**_it("G1"), "record_only": True}))                         # 被看图否掉的 G1
    assert not PR.gaze_bad(_pf(_it("Q9", "fail", defects=["eye_contact"], ignored_defects=["eye_contact"])))   # asset 阶段豁免
    assert not PR.gaze_bad(_pf(_q9([], "pass"), _it("Q1")))


def _take(n, pf, **kw):
    return {"stage": "image", "n": n, "file": f"v{n}.png", "postflight": pf, **kw}


def _ok_pf(q1=0.8, *extra):
    items = [_it("Q1", "pass", value=q1), _q9([], "pass")] + list(extra)
    return {"ok": not any(i["status"] == "fail" for i in items), "blocking": [i["id"] for i in items if i["status"] == "fail"], "items": items}


def test_pick_and_relaxed_pick_exclude_gaze():
    td = {"takes": [_take(1, _ok_pf(0.9, _q9(["lineup"]))),                              # 分最高但排排站
                    _take(2, _ok_pf(0.7)),                                                # 干净
                    _take(3, {**_ok_pf(0.95), "items": [_it("Q1", "pass", value=0.95), _q9([], "pass"), _it("G1")], "ok": False})]}
    assert PR.review_pick(td, "image") == 2
    assert PR.review_pick_relaxed(td, "image") == 2
    only_bad = {"takes": [_take(1, _ok_pf(0.9, _q9(["eye_contact"]))), _take(2, {"ok": False, "blocking": ["G1"], "items": [_it("Q1", "pass", value=0.8), _it("G1")]})]}
    assert PR.review_pick(only_bad, "image") is None and PR.review_pick_relaxed(only_bad, "image") is None   # 全看镜头 → 不采用（停在 best_effort）
    assert PR.safe_take(_ok_pf(0.9, _q9(["lineup"]))) is False and PR.safe_take(_ok_pf(0.5, _it("Q1"))) is True


def test_review_adopt_refuses_gaze_take_even_when_named(tmp_path, monkeypatch):
    import types
    td = {"takes": [_take(4, _ok_pf(0.9, _q9(["eye_contact"])))]}
    calls = []
    fake = types.SimpleNamespace(load_takes=lambda sid: td, mutate_takes=lambda *a, **k: calls.append(("mutate", a, k)),
                                 set_active=lambda *a, **k: calls.append(("active", a, k)), find_shot=lambda *a: None)
    monkeypatch.setitem(sys.modules, "ns_render.pipeline", fake)
    monkeypatch.setitem(sys.modules, "ns_render", types.SimpleNamespace(pipeline=fake))
    events = []
    monkeypatch.setattr(PR, "log_event", lambda paths, ev, **k: events.append((ev, k)))
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    assert PR.review_adopt(paths, "first:ep01-S1", n=4, by="t", relaxed=True) is None
    assert PR.review_adopt(paths, "first:ep01-S1", by="t", relaxed=True) is None
    assert calls == [] and any(e == "review_adopt_refused" and k.get("rule") == "L-200" for e, k in events)
