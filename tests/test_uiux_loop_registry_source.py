"""UIUX-LOOP r1（11-06）：网页状态标签 / 修改队列必须读当前剧那份活的 producer 登记表。
现场：全局 data/producer/registry.json 停在 11-03（V1 / 早期 V2 的 redo / master_reject），而出图机同步回来的是
data/producer/runs/series10_v2/registry.json（心跳几分钟前）；全剧总览把 ep01 每一镜都标成“已重置 / 驳回待重出 / 过期”、板块“过期”。
规则：单一来源 = run_paths.producer_registry()（K-OPS-F24）；legacy 剧才是旧位置。全部临时目录。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import frame_edit_queue as FEQ  # noqa: E402
from ns_api import run_paths as RP  # noqa: E402
from ns_api import shot_status as SS  # noqa: E402


def _root(tmp_path: Path, primary: str, legacy: str = "series10_v1") -> Path:
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": primary, "legacy_unprefixed_run": legacy, "runs": {primary: {"status": "producing"}}}), encoding="utf-8")
    return tmp_path


def test_producer_registry_is_per_run_for_v2_and_global_for_legacy(tmp_path):
    r = _root(tmp_path / "a", "series10_v2")
    assert RP.producer_registry(r) == r / "data/producer/runs/series10_v2/registry.json"
    r2 = _root(tmp_path / "b", "series10_v1")
    assert RP.producer_registry(r2) == r2 / "data/producer/registry.json"


def test_shot_status_reads_live_registry_not_default(monkeypatch, tmp_path):
    """默认（没改 REGISTRY）走 run_paths.producer_registry；改了 REGISTRY（测试）就读改的那份"""
    monkeypatch.setattr(SS, "_reg", {"mt": None, "val": {}})
    monkeypatch.setattr(SS, "_REG_EP", {"mt": None, "val": {}})
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"episodes": [{"ep": 1, "shots": [
        {"shot": "ep01-S1", "index": 1, "objects": {"first": {"status": "passed"}, "last": {"status": "passed"}, "video": {"status": "passed"}}}]}]}), encoding="utf-8")
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"episodes": [{"ep": 1, "shots": [
        {"shot": "ep01-S1", "index": 1, "objects": {"first": {"status": "pending", "redo": True, "master_reject": "x"}}}]}]}), encoding="utf-8")
    monkeypatch.setattr(RP, "producer_registry", lambda root=None, run=None: live)
    assert SS.registry_path() == live
    t = SS.tags_for("ep01-S1", None, {"active": {"image": 3, "last": 7, "video": 2}})
    assert t["main"] == "ok" and all(x["kind"] == "ok" for x in t["tags"])
    assert SS.episode_blocks(1, [{"id": "ep01-S1", "status": t}])["state"] != "stale"
    # 测试覆盖 REGISTRY → 读旧表；缓存键带路径，换文件立刻生效（不靠 mtime 不同）
    monkeypatch.setattr(SS, "REGISTRY", stale)
    assert SS.registry_path() == stale
    t2 = SS.tags_for("ep01-S1", None, {"active": {"image": 3}})
    assert t2["main"] == "redo"


def test_frame_edit_queue_reads_live_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(FEQ, "_reg", {"mt": None, "val": []})
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"episodes": [{"ep": 2, "shots": [
        {"shot": "ep02-S1", "index": 1, "objects": {"first": {"id": "first:ep02-S1", "status": "ready"}, "last": {"status": "pending"}}}]}]}), encoding="utf-8")
    monkeypatch.setattr(RP, "producer_registry", lambda root=None, run=None: live)
    rows = FEQ.registry_objects()
    assert [(r["shot"], r["kind"], r["status"]) for r in rows] == [("ep02-S1", "first", "ready"), ("ep02-S1", "last", "pending")]
    monkeypatch.setattr(FEQ, "REGISTRY", tmp_path / "none.json")   # 测试覆盖：文件不在 = 空表
    assert FEQ.registry_objects() == []


def test_real_repo_default_points_to_primary_run_registry():
    """真实仓库：primary 不是 legacy → 默认读 data/producer/runs/<primary>/registry.json（不是全局旧表）"""
    p = SS.registry_path()
    assert p == RP.producer_registry(ROOT)
    run = RP.current_run(ROOT)
    legacy = json.loads((ROOT / "config/pipeline/runs.json").read_text(encoding="utf-8")).get("legacy_unprefixed_run")
    if run != legacy:
        assert p == ROOT / "data/producer/runs" / run / "registry.json"
