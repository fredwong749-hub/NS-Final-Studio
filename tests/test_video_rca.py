"""VIDEO-RCA（fredw-2b 派，2026-11-01）规则检查：K-REN-701 / 702 / 703、K-REV-704，见 knowledge/rules/render_video_rca.yaml。"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/recipes", "packages/schema", "services/agent", "tools/video_rca"):
    sys.path.insert(0, str(ROOT / p))

from ns_recipes import prompt as PR  # noqa: E402
from ns_recipes.lint import SYS_CAMERA_FACING_RE, lint_people_eyeline  # noqa: E402

CAM = re.compile(r"camera|lens|viewer|镜头", re.I)
BODY = ("[Shot 1] Live-action, cinematic, shallow depth of field, a close shot at eye level begins in the position, framing "
        "and lighting established by <Picture 1>, featuring a 22-year-old Chinese woman with waist-length misty sky-blue "
        "straight hair with a blunt fringe, cool pale skin and a tall slender build, wearing an ivory blouse with a dark grey "
        "pencil skirt and a cropped blazer, transparent 12cm stiletto heels, a thin silver necklace, standing at a desk. "
        "The camera pushes in as her toe shifts on the carpet.")


def test_v02_anchor_facing_never_says_camera():
    """K-REN-702：重试锚点句的站位词表不得把“朝镜头”译成 facing the camera"""
    for k, v in PR.FACING_EN.items():
        if k in ("背对",):
            continue
        assert not SYS_CAMERA_FACING_RE.search(v), (k, v)


def test_v02_lint_flags_system_camera_facing():
    txt = ("integrated_multimodal_description: [Shot 1] The frame keeps a woman in the center of the frame, facing the camera. "
           "She smiles.\n\noverall_soundscape: x")
    issues = lint_people_eyeline(txt, None, {})
    assert any(i["code"] == "RL-E3" and i["level"] == "error" for i in issues)
    ok = txt.replace("facing the camera", PR.FACING_EN["镜头"])
    assert not any(i["code"] == "RL-E3" for i in lint_people_eyeline(ok, None, {}))


def test_v01_hide_offframe_parts_by_size():
    """K-REN-701：近景删下装和鞋、中景只删鞋、中全景不动；只动第一句，分拍动作句不动"""
    b, gone = PR.hide_offframe_parts(BODY, "近景")
    assert "skirt" not in b.split(". ")[0] and "heels" not in b.split(". ")[0]
    assert "an ivory blouse and a cropped blazer" in b and "toe shifts" in b
    assert set(gone) == {"a dark grey pencil skirt", "transparent 12cm stiletto heels"}
    b, gone = PR.hide_offframe_parts(BODY, "中景")
    assert "pencil skirt" in b and "heels" not in b and gone == ["transparent 12cm stiletto heels"]
    assert PR.hide_offframe_parts(BODY, "中全景") == (BODY, [])
    assert PR.hide_offframe_parts(BODY, None) == (BODY, [])


def test_v01_flag_declared_with_provenance():
    import yaml
    base = yaml.safe_load((ROOT / "services/recipes/recipes/_base.yaml").read_text(encoding="utf-8"))
    assert "hide_offframe_parts" in base["prompt"]
    assert "prompt.hide_offframe_parts" in base["provenance"]


# K-REN-703：SCRIPT-RSI 11-01 已改 framing.two_shot_clause（D-SCR-07），去掉 xfail
def test_v03_two_shot_clause_no_camera_facing():
    from ns_agent.framing import two_shot_clause
    s = two_shot_clause(2, None)
    assert not re.search(r"朝向镜头|toward the camera", s), s


def test_rates_classes_untested_is_none():
    import rates as RT
    c = RT.classes({"mean": 0.3, "v6": {}, "identity": {}})
    assert c["动作不足/站桩(mean<0.5)"] is True
    assert c["多手(hands_max>2×人数)"] is None and c["身份漂移(p10<0.5)"] is None


# K-REV-705：WORKFLOW 11-01 已把 dejudder.j4_gt 改 1.2（VIDEO-RCA r2），去掉 xfail
def test_v05_dejudder_threshold_covers_pika_lowmotion():
    import json
    d = json.loads((ROOT / "config/pipeline/video_policy.json").read_text(encoding="utf-8"))["dejudder"]
    assert d["enabled"] and "i2va_pika_flex" in d["recipes"]
    assert float(d["j4_gt"]) <= 1.2 and float(d["j4_z_ge"]) <= 3.0


def test_v06_compile_flags_pose_change_in_outerwear():
    """K-WRT-704 编译层 RL-P1：穿外套 + 坐→站 → warn（不改镜头结构）"""
    txt = ("integrated_multimodal_description: [Shot 1] Live-action, a medium full shot, featuring a woman wearing an ivory blouse "
           "and a cropped blazer, at a desk. At 00:02.000, she rises from the chair.\n\noverall_soundscape: x")
    assert any(i["code"] == "RL-P1" for i in lint_people_eyeline(txt, None, {}))
    assert not any(i["code"] == "RL-P1" for i in lint_people_eyeline(txt.replace("she rises from the chair", "she shifts her weight"), None, {}))
    assert not any(i["code"] == "RL-P1" for i in lint_people_eyeline(txt.replace("and a cropped blazer", "and a pencil skirt"), None, {}))
