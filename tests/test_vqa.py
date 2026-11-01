"""VQA（K-REV-V01…V04、K-REN-V05、K-WRT-V06、K-EDT-V07）：本地看图复核的确定性部分。不连 gpu36、不调外部 API。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "agent"))

from ns_agent.vqa import cfg, client, contract, judge, rubric  # noqa: E402

CONTRACT_IDS = {f"Q{i}" for i in range(1, 10)} | {f"V{i}" for i in range(1, 10)} | {f"I{i}" for i in range(1, 11)}


# K-REV-V01 ------------------------------------------------------------------
def test_client_refuses_non_local_url(monkeypatch):
    monkeypatch.setenv("VQA_URL", "https://api.example.com")
    with pytest.raises(ValueError, match="K-REV-V01"):
        client._url()
    monkeypatch.setenv("VQA_URL", "http://127.0.0.1:8870")
    assert client._url() == "http://127.0.0.1:8870"


@pytest.mark.parametrize("bad", ["见 data/renders/ep01/S5/takes/image_003.png", "data:image/png;base64,AAAA",
                                 "iVBORw0KGgoAAAANSUhEUg", "片子 clip.mp4"])
def test_text_only_guard_blocks_images(bad):
    with pytest.raises(judge.ImageLeak):
        judge.text_only_guard("正常文字", bad)


def test_judge_messages_are_text_only():
    vlm = {"checks": {"outfit_mismatch": {"s": "defect", "e": "下装是黑色长裤"}}, "defects": ["outfit_mismatch"],
           "people": [{"who": "林晚", "outfit": "黑西裤"}], "people_count": 1}
    contract_res = {"items": [{"id": "Q7", "title": "场景", "status": "pass",
                               "detail": "相似度 0.5 file assets/scenes/x/refs/a.png"}]}
    msgs = judge.build_messages("ep01-S5", "image", 1, "【林晚】近景，深灰铅笔裙", vlm, contract_res, [])
    judge.text_only_guard(*(m["content"] for m in msgs))     # 路径已被抹掉，不抛


# K-REV-V02 / 004 ------------------------------------------------------------
def test_every_check_maps_to_contract_item():
    c = cfg()
    for k, v in (c.get("checks") or {}).items():
        assert v.get("zh") and v.get("severity") in ("hard", "soft"), k
        assert v.get("contract") in CONTRACT_IDS, k
        assert v.get("video") in CONTRACT_IDS, k
    for k, v in (c.get("video_checks") or {}).items():
        assert v.get("contract") in CONTRACT_IDS, k
    assert len(c["checks"]) >= 20
    # 提示词里列的检查项 = config 的检查项
    txt = (ROOT / "config/prompts/vqa_inspect.md").read_text(encoding="utf-8")
    for k in c["checks"]:
        assert f'"{k}"' in txt, k


def test_q9_record_only_and_untested():
    assert contract.q9(None)[0] == "untested"
    assert contract.q9({"error": "busy"})[0] == "untested"
    st, d, ev = contract.q9({"defects": ["shoe_mismatch"], "checks": {"shoe_mismatch": {"s": "defect", "e": "黑短靴"}}})
    assert st == "na" and ev["would_fail"] and ev["maps_to"]["shoe_mismatch"] == "Q2"
    assert contract.q9({"defects": [], "checks": {}})[0] == "pass"


def test_underage_blocks_from_day_one():
    assert cfg()["checks"]["underage_look"]["blocking"] is True
    st, _, _ = contract.q9({"defects": ["underage_look"], "checks": {"underage_look": {"s": "defect", "e": "x"}}})
    assert st == "fail"


def test_parse_loose_json_and_normalise():
    txt = '```json\n{"people_count": 1, "checks": {"extra_limbs": {"s": "defect", "e": "三只手"}, "eye_contact": "pass",' \
          ' "bogus": {"s": "defect"},}}\n```'
    v = rubric.parse(txt)
    assert v["ok_parse"] and v["defects"] == ["extra_limbs"] and v["checks"]["eye_contact"]["s"] == "ok"
    assert "bogus" not in v["checks"]
    assert not rubric.parse("not json")["ok_parse"]


def test_build_request_marks_refs_and_subject(tmp_path):
    a, b = tmp_path / "face.png", tmp_path / "subj.png"
    a.write_bytes(b"x"), b.write_bytes(b"y")
    p = "近景构图（胸部以上），【林晚】站在桌前，林晚本镜造型A要穿全：短款西装外套、钻石水晶甲（造型设定图上有），【场景】名称：深夜写字楼；"
    req = rubric.build_image_request(str(b), p, [str(a).replace("face", "identity_refs/lin_wan/face")],
                                     extra_refs=[(str(a), "参考鞋")])
    assert req["images"][-1]["label"] == "【待检图】" and req["spec"]["size"] == "近景"
    assert "短款西装外套" in req["spec"]["items"] and req["spec"]["cast"] == ["林晚"]
    assert "不允许" in req["spec"]["camera_ok"]


# K-REV-V03 ------------------------------------------------------------------
def test_blocking_only_when_calibrated():
    """K-REV-V03 修订（项目方 11-01 16:10 原话转拦截，D-VQA-01）：不再要求“标定报告过线 + 总调度批准”，
    但每个 blocking 项都必须在 gate._blocking_v1 写明依据（标定 / 点名），且 enforce 关掉时只有 underage_look 能拦"""
    c = cfg()
    if not ((c.get("gate") or {}).get("enforce") and (c.get("judge") or {}).get("enforce")):
        rep = ROOT / "data/vqa/calibration/report.json"
        ok = set()
        if rep.exists():
            ok = {r["check"] for r in json.loads(rep.read_text(encoding="utf-8"))["rows"] if r.get("eligible_for_blocking")}
        for k, v in c["checks"].items():
            if v.get("blocking") and k != "underage_look":
                assert k in ok, f"{k} 设成阻断，但标定报告没过 0.85（K-REV-V03 旧口径）"
        return
    why = (c.get("gate") or {}).get("_blocking_v1") or ""
    for k, v in c["checks"].items():
        if v.get("blocking") and k != "underage_look":
            assert k in why, f"{k} 设成阻断，但 gate._blocking_v1 没写依据（K-REV-V03 修订）"


# K-REN-V05 ------------------------------------------------------------------
def test_judge_loop_with_fake_gateway():
    vlm = {"checks": {"outfit_mismatch": {"s": "defect", "e": "黑长裤"}}, "defects": ["outfit_mismatch"], "people": []}
    fake = lambda msgs: {"content": json.dumps({"verdict": "fail", "confidence": 0.8, "failed_checks": ["outfit_mismatch"],
                                                "reasons": ["下装不对"], "action": "reprompt",
                                                "prompt_delta": {"dimension": "outfit", "append": "下装是深灰铅笔裙（不是长裤）",
                                                                 "replace": [["西装裙", "铅笔裙"]]}}, ensure_ascii=False)}
    rec = judge.review_round("ep01-S5", "image", "x.png", "【林晚】穿深灰西装裙，无字幕、无文字、无水印", [], None,
                             chat=fake, vlm={**vlm, "key": None})
    assert rec["outcome"] == "rerun" and rec["judge"]["verdict"] == "fail"
    assert "铅笔裙" in rec["next_prompt"] and rec["next_prompt"].endswith("无字幕、无文字、无水印")
    assert rec["next_prompt"].index("下装是深灰铅笔裙") < rec["next_prompt"].index("无字幕")


def test_rule_fallback_when_gateway_down():
    def down(msgs):
        raise OSError("网关不可达")
    vlm = {"checks": {"extra_limbs": {"s": "defect", "e": "三只手"}}, "defects": ["extra_limbs"], "people": []}
    j = judge.judge("ep01-S1", "image", "prompt", vlm, chat=down)
    assert j["verdict"] == "fail" and j["prompt_delta"]["dimension"] == "hands" and j["by"].startswith("rule_fallback")
    j2 = judge.judge("ep01-S1", "image", "prompt", {"defects": ["lighting_time"], "checks": {}}, chat=down)
    assert j2["verdict"] == "pass"     # 只有 soft 级 → 不拦


def test_apply_delta_one_dimension():
    p = judge.apply_delta("A，B", {"append": "C", "replace": [["B", "D"]]})
    assert p == "A，D，C"
    assert judge.apply_delta("A", None) == "A"


# K-WRT-V06 ------------------------------------------------------------------
def _script_lint():
    import importlib.util as ilu
    s = ilu.spec_from_file_location("vq_lint", ROOT / "tools/vqa/script_lint.py")
    m = ilu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_vq_w1_shoes_written_when_feet_visible():
    L = _script_lint()
    sh = SimpleNamespace(index=2, cast=[SimpleNamespace(name="林晚", presence="在画")])
    ep = SimpleNamespace(looks=[SimpleNamespace(character="林晚", from_shot=None, slots={"鞋": "12cm 透明侧开细高跟"})])
    assert [i["rule_id"] for i in L.check_shot(sh, ep, "全景，林晚走进办公室", "全景")] == ["VQ-W1"]
    assert L.check_shot(sh, ep, "全景，林晚踩着透明高跟走进", "全景") == []
    assert L.check_shot(sh, ep, "近景，林晚", "近景") == []


# K-EDT-V07 ------------------------------------------------------------------
def test_4k_sop_in_config_and_never_gpu2():
    u = cfg()["upscale_4k"]
    assert u["engine"] == "seedvr2_3b" and u["target"] == [2160, 3840] and "final" in u["only_when"]
    src = (ROOT / "services/post/ns_post/upscale4k.py").read_text(encoding="utf-8")
    assert re.search(r'GPUS\s*=\s*"3"', src)          # gpu33 GPU2 永不用
