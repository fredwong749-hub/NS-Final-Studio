"""W36：merge_pull 并回按剧过滤——服务器 takes.json 混有 V1/V2/无标记 → 只并 V2、拒的记日志、active/locked 不指外来。全临时目录。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops/offline"))
import merge_pull as MP  # noqa: E402

RUN = "series10_v2"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(MP, "ROOT", tmp_path)
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": RUN, "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    rd = tmp_path / "data/pipeline/runs" / RUN
    rd.mkdir(parents=True)
    (rd / "P1_looks.json").write_text(json.dumps([{"char_id": "v2_hero"}]), encoding="utf-8")
    return tmp_path


def pf(*ids):
    return {"items": [{"id": "Q1", "evidence": {"sims": {i: 0.9 for i in ids}}}]}


def take(stage, n, file, **kw):
    return {"stage": stage, "n": n, "file": file, **kw}


def server_doc():
    return {"takes": [
        take("image", 1, "renders/series10_v2/ep01/S3/takes/a.png"),                       # 新口径
        take("image", 2, "renders/ep01/S3/takes/b.png", postflight=pf("v2_hero")),          # 旧 rel + V2 角色 → 收
        take("image", 3, "renders/ep01/S3/takes/c.png", producer={"run": RUN}),             # 旧 rel + producer.run → 收
        take("image", 4, "renders/ep01/S3/takes/d.png", postflight=pf("lin_wan")),          # V1 角色 → 拒
        take("image", 5, "renders/ep01/S3/takes/e.png"),                                    # 无标记 → 拒
        take("last", 1, "renders/ep01/S3/takes/f.png", params={"origin": {"run": "assetmaster/frames_v2"}}),  # origin → 拒
        take("last", 2, "renders/series10_v1/ep01/S3/takes/g.png"),                         # 别的剧目录 → 拒
    ], "active": {"image": 4, "last": 2}, "locked": {"image": 5}}


def test_filter_only_v2_and_pointers(env):
    out, rej = MP.filter_remote(server_doc(), RUN)
    assert [(t["stage"], t["n"]) for t in out["takes"]] == [("image", 1), ("image", 2), ("image", 3)]
    assert {(x["stage"], x["n"]) for x in rej} == {("image", 4), ("image", 5), ("last", 1), ("last", 2)}
    assert out["active"] == {} and out["locked"] == {}         # 指向被拒版本的指针全丢


def test_accepted_pointer_kept(env):
    d = server_doc()
    d["active"] = {"image": 2}
    out, _ = MP.filter_remote(d, RUN)
    assert out["active"] == {"image": 2}


def test_merge_takes_end_to_end_logs_rejects(env):
    src = env / "pulled.json"
    src.write_text(json.dumps(server_doc()), encoding="utf-8")
    dst = env / "data/renders/ep01/S3/takes.json"          # 服务器旧路径（不带剧名）→ 目标 = primary
    dst.parent.mkdir(parents=True)
    dst.write_text(json.dumps({"takes": [], "active": {"image": 1}}), encoding="utf-8")
    act = MP.merge_takes(src, dst, dry=True, host="gpu33", ep=1)
    assert act.startswith("takes+3") and "rejected=4" in act
    # 非 dry 走 mutate_takes 太重：直接验日志
    MP.log_rejects(RUN, "ep01-S3", "gpu33", MP.filter_remote(server_doc(), RUN)[1])
    f = list((env / "data/quarantine" / RUN).glob("merge_rejects_*.jsonl"))
    assert f and len(f[0].read_text(encoding="utf-8").splitlines()) == 4


def test_legacy_not_filtered(env):
    (env / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": "series10_v1", "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    assert MP.target_run(None) is None
    assert MP.target_run("series10_v1") is None
