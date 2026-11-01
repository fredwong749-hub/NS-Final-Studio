"""G18（docs/master/MASTER_PICTURE.md §4）：旧出图路径只隔离、不删（WORKFLOW 11-01，规则 K-OPS-W01）。

- 登记了资产的项目（config/recipes/asset_refs.json，例 series10_v1）调 pipeline.render_image / render_last_frame
  （两段式换脸 qwen_two_stage + plates/master.png 母版脸裁切缓存 master_face_*）一律 LegacyPathBlocked；
- 没登记的旧项目不受影响（判定返回 None）；
- 唯一出图路径的配置 / 作业清单里不得出现母版脸缓存或母版底板。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "services/render_router", "packages/schema"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def _script(path: str):
    return SimpleNamespace(sources=[SimpleNamespace(path=path)])


def test_registered_project_blocks_legacy_render():
    from ns_render import pipeline as P
    s = _script("data/staging_v3/merged/x_series10_v1_ep01-10.md")
    with pytest.raises(P.LegacyPathBlocked):
        P.render_image(None, s, "ep01-S1")
    with pytest.raises(P.LegacyPathBlocked):
        P.render_last_frame(None, s, "ep01-S1")
    assert issubclass(P.LegacyPathBlocked, P.ComfyError)      # API 任务 / 画布按普通出图失败处理（写人话原因）


def test_unregistered_project_not_blocked():
    from ns_render import pipeline as P
    P.check_not_legacy_project(_script("data/import/old_60ep.md"), "ep01-S1")   # 不抛


def test_unified_config_has_no_master_face():
    cfg = json.loads((ROOT / "config/recipes/asset_refs.json").read_text(encoding="utf-8"))
    for name, proj in (cfg.get("projects") or {}).items():
        for cid, faces in (proj.get("faces") or {}).items():
            for f in faces:
                assert "master_face" not in f and "plates/master" not in f, (name, cid, f)


def test_first_frame_jobs_have_no_master_face_or_banned_lora():
    p = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"
    if not p.exists():
        pytest.skip("没有 series10 首帧作业清单")
    txt = p.read_text(encoding="utf-8")
    assert "master_face_" not in txt and "plates/master.png" not in txt
    assert "lin_wan_qi_v1" not in txt          # G7：作业清单只挂 frame_v9，不挂已禁的身份 LoRA
