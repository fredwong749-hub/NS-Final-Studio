"""K-OPS-Q24（RSI 11-01，总调度授权）：首帧作业的镜头集合与提示词来源 = 导入稿 data/import/script_v2.json；
P4 写作中间稿不再被生产代码读取；G21 核对镜头集合 + 来源 sha，不比修改时间。只写 tmp_path。"""
import importlib.util as ilu
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = ilu.spec_from_file_location("ns_image_jobs_imp_t", ROOT / "tools" / "pipeline" / "image_jobs.py")
IJ = ilu.module_from_spec(_spec)
_spec.loader.exec_module(IJ)


def _shot(sid, img="中景，林晚坐在桌前"):
    ep, s = sid.split("-")
    return NS(id=sid, index=int(s[1:]), img_prompt=img, cast=[NS(name="林晚", presence="在画")])


def test_sync_job_set_follows_import(tmp_path):
    run = ROOT / "data" / "pipeline" / "runs" / "testproj_q24"
    data = {"jobs": [{"ep": 1, "shot": "ep01-S1", "status": "ready", "framing_project": "p", "intimate_ep": True},
                     {"ep": 1, "shot": "ep01-S3", "status": "ready"}]}
    si = NS(episodes=[NS(number=1, shots=[_shot("ep01-S1"), _shot("ep01-S2")])])
    r = IJ.sync_job_set(data, si, run)
    assert r == {"added": ["ep01-S2"], "removed": ["ep01-S3"], "kept": 1}
    by = {j["shot"]: j for j in data["jobs"]}
    assert by["ep01-S3"]["status"] == "stale:removed_from_import"                       # 标过期，不删
    assert by["ep01-S2"]["seed"] == 20261202 and by["ep01-S2"]["priority"] == "F01" and by["ep01-S2"]["intimate_ep"] is True
    assert by["ep01-S2"]["out"].endswith("images/frames/ep01/ep01-S2_s20261202.png")
    assert [j["shot"] for j in data["jobs"]] == ["ep01-S1", "ep01-S2", "ep01-S3"]


def test_p4_source_is_blocked_in_production(monkeypatch):
    monkeypatch.delenv(IJ.ALLOW_P4_ENV, raising=False)
    with pytest.raises(IJ.LegacySourceError):
        IJ.load_episode(ROOT / "data/pipeline/runs/series10_v1/ep01/P4_ep01.md")


def test_g21_check_compares_shot_set_and_source_sha(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "assets").mkdir(parents=True)
    si = NS(episodes=[NS(number=1, shots=[_shot("ep01-S1"), _shot("ep01-S2")])])
    monkeypatch.setattr(IJ, "load_import", lambda run=None: si)          # image_jobs 02:3x 加了 run 参数（多剧本）
    monkeypatch.setattr(IJ, "import_sha", lambda run=None: "NEW")
    jobs = {"jobs": [{"ep": 1, "shot": "ep01-S1", "prompt_source": {"sha256": "OLD"}},
                     {"ep": 1, "shot": "ep01-S9", "prompt_source": {"sha256": "NEW"}}]}
    (run / "assets" / "first_frame_jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    r = IJ.jobs_vs_import(run)
    assert not r["ok"] and r["missing"] == ["ep01-S2"] and r["extra"] == ["ep01-S9"] and r["stale_sha"] == ["ep01-S1"]


def test_real_jobs_match_current_import():
    """现行 first_frame_jobs.json = 现行导入稿（镜头集合一致、每条来源 sha = script_v2.json）。导入后没重编就会红"""
    jobs = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"
    if not jobs.exists() or not IJ.IMPORT_JSON.exists():
        pytest.skip("series10 不在本机")
    r = IJ.jobs_vs_import()
    assert r["ok"], {k: r[k][:5] for k in ("missing", "extra", "stale_sha")}
