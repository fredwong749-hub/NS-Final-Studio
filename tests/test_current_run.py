"""当前剧唯一来源（WORKFLOW 11-02，总调度 P1 / UIAUDIT N1；K-OPS-W20）+ runs.py strict（K-OPS-W17 修订 / K-OPS-F09）。
- 真实配置：人物中心当前剧 = runs.json primary（series10_s2 目录比第一季新也不变），林晚人物页 200；
- 临时目录：第二季目录 mtime 更新时 current_project 仍取 primary；order_runs 主剧在前、不看 mtime；
- strict：runs.json 缺失 / 无 primary 时抛 RunRegistryMissing，默认回退不变；
- 静态扫描：services/api/ns_api 里不得再出现“按修改时间排序 run 目录”的写法。"""
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "packages/schema", "services/render_router", "tools/autopilot"):
    sys.path.insert(0, str(ROOT / p))
import runs as RUNS  # noqa: E402


def test_runs_strict(tmp_path):
    with pytest.raises(RUNS.RunRegistryMissing):
        RUNS.primary_run(tmp_path, strict=True)
    assert RUNS.primary_run(tmp_path) == RUNS.DEFAULT_PRIMARY            # 笔记本侧默认回退不变
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"runs": {"x": {}}}), encoding="utf-8")
    with pytest.raises(RUNS.RunRegistryMissing):
        RUNS.primary_run(tmp_path, strict=True)                          # 有 runs 但没写 primary
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": "x", "legacy_unprefixed_run": "x", "runs": {"x": {}}}), encoding="utf-8")
    assert RUNS.primary_run(tmp_path, strict=True) == "x"


def test_order_runs_ignores_mtime(tmp_path):
    from ns_api import current_run as CR
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": "s1", "legacy_unprefixed_run": "s1", "runs": {"s1": {"priority": 0}, "s2": {"priority": 10}}}), encoding="utf-8")
    d = tmp_path / "runs"
    for n in ("s1", "s2", "zz"):
        (d / n).mkdir(parents=True)
    t = time.time()
    os.utime(d / "s2", (t + 100, t + 100))
    assert [x.name for x in CR.order_runs([d / "zz", d / "s2", d / "s1"], tmp_path)] == ["s1", "s2", "zz"]
    assert CR.primary_run(tmp_path) == "s1"


def test_character_hub_current_project_is_primary(monkeypatch, tmp_path):
    from ns_agent import asset_refs as R
    from ns_api import character_hub as H
    cfg = tmp_path / "config/recipes/asset_refs.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"projects": {"s1": {"run_dir": "data/pipeline/runs/s1"},
                                            "s2": {"inherits": "s1", "run_dir": "data/pipeline/runs/s2"}}}), encoding="utf-8")
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": "s1", "legacy_unprefixed_run": "s1", "runs": {"s1": {}, "s2": {}}}), encoding="utf-8")
    for n in ("s1", "s2"):
        (tmp_path / "data/pipeline/runs" / n).mkdir(parents=True)
    t = time.time()
    os.utime(tmp_path / "data/pipeline/runs/s2", (t + 100, t + 100))      # 第二季目录更新（旧写法会猜成 s2）
    monkeypatch.setattr(R, "ROOT", tmp_path)
    monkeypatch.setattr(R, "CFG", cfg)
    assert H.current_project() == "s1"
    assert H.current_project("s2") == "s2"                                  # 明确参数照样能切


def test_real_character_hub_lin_wan():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_api import character_hub as H
    assert H.current_project() == RUNS.primary_run()
    app = FastAPI()
    app.include_router(H.router)
    r = TestClient(app).get("/api/character-hub/lin_wan")
    assert r.status_code == 200, r.text[:300]


MTIME_RUN_GUESS = re.compile(r"(?:runs?|RUNS|run_dir|root)\b[^\n]{0,120}key=lambda [a-z_]+: -?\(?[a-z_]+(?: / \"[a-z_]+\")?\)?\.stat\(\)\.st_mtime"
                             r"|def mt\(p: str\) -> float")


# 只做“列表显示新的在前”、不决定当前剧的排序（写作链运行列表 /api/story-runs）
ALLOW = ('ds = sorted((p for p in RUNS.iterdir() if p.is_dir() and not p.name.startswith("_")), key=lambda p: -p.stat().st_mtime)',)


def test_no_mtime_run_guess_in_api():
    bad = []
    for f in (ROOT / "services/api/ns_api").glob("*.py"):
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if any(a in ln for a in ALLOW):
                continue
            if "iterdir()" in ln and "st_mtime" in ln:                       # 目录（剧）按修改时间排
                bad.append(f"{f.name}:{i}")
            elif "def mt(p: str) -> float" in ln or (MTIME_RUN_GUESS.search(ln) and "runs" in ln.lower()):
                bad.append(f"{f.name}:{i}")
    assert bad == [], f"按修改时间猜当前剧（K-OPS-W20）：{bad}"


def test_real_character_hub_child_season_inherits_cast():
    """?project=series10_s2：子季没写人物表也继承父季（K-OPS-W18 / W19）；林晚身份脸 = L-086"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_api import character_hub as H
    app = FastAPI()
    app.include_router(H.router)
    r = TestClient(app).get("/api/character-hub/lin_wan", params={"project": "series10_s2"})
    assert r.status_code == 200, r.text[:300]
    assert {c["cid"] for c in H._cast("series10_v1")} <= {c["cid"] for c in H._cast("series10_s2")}
