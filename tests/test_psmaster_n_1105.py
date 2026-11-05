"""PS-MASTER 11-05 cut N：ep01 psm7 重跑卡点修复（项目方“处理这个拖慢逻辑”）"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "tools", "tools/script_rsi"):
    sys.path.insert(0, str(ROOT / p))


def test_back_view_not_triggered_by_bare_back_words():
    from ns_agent import asset_refs as AR
    # “光落在祁念的背脊上”不是背影（S16 因此丢了身份脸参考槽，整集被 L-140 挡）
    assert AR.back_in_text("祁念", "天花顶灯从上侧 45° 落在祁念的背脊与透明鞋面上", ["祁念"]) is False
    assert AR.back_in_text("顾沉", "林晚看着顾沉的背影", ["林晚", "顾沉"]) is True


def test_h16_tight_pair_ignores_ots_foreground_hidden_face():
    import staging as S
    ots = "中近景，卓琳背对镜头，只以右肩与后脑入画，蹲在祁念左前方，祁念站着低头看腰间软尺，手扶椅背"
    assert S.check_shot(ots, [("卓琳", "在画"), ("祁念", "在画")])["tight_pair"] == []
    both = "中近景，卓琳看着祁念，祁念站着低头看腰间软尺，手扶椅背"
    assert S.check_shot(both, [("卓琳", "在画"), ("祁念", "在画")])["tight_pair"] == ["卓琳", "祁念"]
