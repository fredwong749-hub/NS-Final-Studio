"""K-PRM-310（VIDLAB 11-02）：分拍微表情编译规则的守护测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "recipes"))
sys.path.insert(0, str(ROOT / "tools" / "vidlab"))

from ns_recipes import acting as A  # noqa: E402

BODY = ("[Shot 1] A close shot. At 00:02.000, she says: <d>[Chinese] 好。</d> her lips parting softly. "
        "At 00:04.000, her shoulders ease. At 00:06.000, her fingertips tighten as the shot ends.")


def test_micro_beats_each_beat():
    out, notes = A.micro_beats(BODY)
    assert len(notes) == 3
    assert "her brows lifting slightly as she blinks." in out
    assert ", her brows drawing together for a moment as she blinks twice, as the shot ends." in out


def test_scope_closeup_single_only():
    assert A.in_scope("closeup_single", "近景", 1)
    assert not A.in_scope("closeup_single", "中景", 1)
    assert not A.in_scope("closeup_single", "近景", 2)


def test_rules_same_as_lab_copy():
    import acting as LAB
    assert LAB.MICRO == A.MICRO and LAB.PRON == A.PRON and LAB.BEAT.pattern == A.BEAT.pattern


def test_recipe_default_off():
    import yaml
    y = yaml.safe_load((ROOT / "services/recipes/recipes/i2va_pika_flex.yaml").read_text(encoding="utf-8"))
    assert y["prompt"]["acting_micro_beats"] is False
    assert y["prompt"]["acting_scope"] == "closeup_single"
