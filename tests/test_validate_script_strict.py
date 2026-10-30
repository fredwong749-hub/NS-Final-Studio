"""严格校验（tools/validate_script_strict.py）：Image 2.1 Turbo 格式检查；只查格式"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import validate_script_strict as VS  # noqa: E402


def shot(img="中景，林晚", motion="lnwan01，static camera，她抬眼——她看向镜头，嘴角上扬，双手扶住栏杆"):
    return SimpleNamespace(img_prompt=img, motion_prompt=motion)


def ids(issues):
    return sorted(i["rule_id"] for i in issues)


def test_clean_shot_passes():
    assert VS.image_checks(shot(), {"hh12clear"}) == []


def test_negation_in_img_blocks_but_fixed_phrases_pass():
    assert ids(VS.image_checks(shot(img="中景，林晚没有笑"), set())) == ["IMG-N1"]
    assert VS.image_checks(shot(img="中景，不锈钢小钢珠，自然的轻微不对称，无名指"), set()) == []
    assert ids(VS.image_checks(shot(img="中景，避免反光"), set())) == ["IMG-N1"]


def test_last_frame_required():
    assert ids(VS.image_checks(shot(motion="static camera，她抬眼"), set())) == ["IMG-L1"]
    assert ids(VS.image_checks(shot(motion="static camera，她抬眼——看"), set())) == ["IMG-L1"]
    assert ids(VS.image_checks(shot(motion="static camera，她抬眼——她没有看镜头，双手垂在身侧"), set())) == ["IMG-L2"]


def test_trigger_position_and_table():
    assert VS.image_checks(shot(img="hh12clear，pose_wall，中景，林晚"), {"hh12clear"}) == []
    assert ids(VS.image_checks(shot(img="中景，林晚，hh12clear"), {"hh12clear"})) == ["IMG-T1"]
    assert ids(VS.image_checks(shot(img="zz99x，中景"), {"hh12clear"})) == ["IMG-T1"]


def test_canvas_field_rules_escalated_only_in_strict(monkeypatch):
    warn = [{"rule_id": "QW-C2", "level": "warn", "field": "img", "detail": "x"}]
    monkeypatch.setattr(VS, "_base_check_shot", lambda *a: [dict(i) for i in warn])
    got = VS.strict_check_shot(shot(), None, set(), [])
    assert got[0]["level"] == "block" and VS.V.RULES["QW-C2"][0] == "warn"


def _ep(n_shots, speakers=(), secs=8, mono=0, idx=None):
    """导入器 Episode 的最小替身：镜号、时长、对白说话人、独白"""
    shots = []
    for i in range(n_shots):
        sp = speakers[i] if i < len(speakers) else None
        shots.append(SimpleNamespace(
            index=(idx[i] if idx else i + 1), duration=secs, duration_source="script", extras=[],
            dialogue=[SimpleNamespace(speaker_note=sp)] if sp else [],
            voiceover=SimpleNamespace(text="独白") if i < mono else None))
    return SimpleNamespace(synopsis="x", music="x", music_bgm="Piano.", shots=shots)


def test_episode_shot_count_k1():
    """K1（production_rules_v3 §0）：镜数 6..max(8, 说话轮次+独白段数) block；总时长 50–75 通过、75–90 warn、>90 block；
    严格与导入关口同一判定"""
    talk = ["顾沉", "她", "顾沉", "她", "顾沉", "陈宇", "她", "顾沉"]
    assert VS.shot_cap(_ep(10, talk, mono=2)) == 10
    assert VS.strict_check_episode(_ep(10, talk, secs=7, mono=2)) == []             # 10 镜 70 秒
    got = VS.strict_check_episode(_ep(10, talk, secs=8, mono=2))                    # 80 秒：只提示
    assert [(i["rule_id"], i["level"]) for i in got] == [("QW-E3", "warn")]
    got = VS.strict_check_episode(_ep(11, talk, secs=9, mono=2))                    # 11 镜 99 秒：都 block
    assert {(i["rule_id"], i["level"]) for i in got} == {("QW-E2", "block"), ("QW-E3", "block")}
    bad = VS.strict_check_episode(_ep(6, idx=[1, 2, 4, 5, 6, 7], secs=10))
    assert any(i["rule_id"] == "QW-E2" and i["level"] == "block" for i in bad)


def test_farewell_is_not_negation():
    assert VS.image_checks(shot(motion="static camera，她抬眼——她站在门口，带着告别的笑意望向他"), set()) == []
