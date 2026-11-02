"""K-WRT-211（fb-0001）：镜面 / 玻璃场景手不碰反光面；≤8 秒的镜手部动作 ≤2 拍（tools/script_rsi/rubric_code.mirror_hand_checks）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
RC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RC)


class S:
    def __init__(self, i, d=6):
        self.index, self.duration = i, d


def blk(i, img, beats, h3=""):
    return f"**镜{i}｜img**：{img}\n**场景**：sk_elevator｜轿厢\n**分拍**：{beats}\n```text\n{h3}\n```"


def test_hand_on_mirror_flagged_frame_ok():
    bad = blk(1, "中景，林晚靠在轿厢镜面墙前", "0–2秒｜林晚的掌心贴在镜面上｜视线=门；2–4秒｜林晚呼吸｜视线=门；4–6秒｜林晚抬眼｜视线=门")
    ok = blk(2, "中景，林晚站在全身镜前", "0–2秒｜林晚的左手扶着全身镜镜框｜视线=镜；2–4秒｜林晚呼吸｜视线=镜；4–6秒｜林晚抬眼｜视线=镜",
             "her hand resting on the mirror frame")
    en_bad = blk(3, "中景，林晚在镜面墙前", "0–2秒｜林晚呼吸｜视线=门；2–4秒｜林晚呼吸｜视线=门；4–6秒｜林晚抬眼｜视线=门",
                 "her palm pressed against the mirror")
    r = RC.mirror_hand_checks([S(1), S(2), S(3)], [bad, ok, en_bad])
    assert not r[1][0] and "镜1" in r[1][1] and "镜3" in r[1][1] and "镜2" not in r[1][1]


def test_busy_hands_over_two_beats():
    b = blk(1, "近景，林晚坐在桌前", "0–2秒｜林晚的手拿起纸｜视线=纸；2–4秒｜林晚的手把纸对折｜视线=纸；4–6秒｜林晚的手指攥紧纸角｜视线=门")
    r = RC.mirror_hand_checks([S(1)], [b])
    assert not r[2][0] and "3 拍" in r[2][1]
    assert RC.mirror_hand_checks([S(1, 10)], [b])[2][0]          # 镜长 > 8 秒不判


def test_rule_enforced_and_wired():
    """总调度 11-02：K-WRT-211 不能是假强制——规则 enforced:true + check 指向本文件，生成索引一致，检查真的接进补丁环和导入闸门"""
    import json
    import yaml
    rules = yaml.safe_load((ROOT / "knowledge/rules/writer_series10.yaml").read_text(encoding="utf-8"))["rules"]
    r = next(x for x in rules if x["id"] == "K-WRT-211")
    assert r.get("enforced") is True and "tests/test_k211.py" in (r.get("check") or [])
    idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
    items = idx.get("rules") if isinstance(idx, dict) else idx
    g = next(x for x in items if x.get("id") == "K-WRT-211")
    assert g.get("enforced") is True
    af = (ROOT / "tools/script_rsi/autoflow.py").read_text(encoding="utf-8")
    ra = (ROOT / "tools/script_rsi/rubric_audit.py").read_text(encoding="utf-8")
    assert "mirror_hand_checks" in af and "mirror_hand_checks" in ra


def test_v2_clean_cut_run_enforces_v3_and_k211():
    """V2（CLEAN_CUT.json 的 run）不靠逐集 .v3 标记：补丁环和导入闸门整季开 v3 / K-WRT-211"""
    ag = (ROOT / "tools/script_rsi/autoflow_agent.py").read_text(encoding="utf-8")
    ra = (ROOT / "tools/script_rsi/rubric_audit.py").read_text(encoding="utf-8")
    assert 'or clean_cut(run_dir)' in ag and '"CLEAN_CUT.json").exists()' in ra
