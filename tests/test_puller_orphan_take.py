"""ORPHAN-TAKE（11-06）：puller 并回 takes.json 后，本台负责 stage 里“当前版 / 已打分通过”的版本原图笔记本还没有 → 排进按需拉取队列；
打分没结论（running / orphan）、没通过的不拉（只给项目方看通过的图；它们打完分才经 outbox 过来）。不连服务器。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/netfix"))
import puller as PU  # noqa: E402

REL = "data/renders/series10_v2/ep01/S5/takes.json"


def _t(n, stage, pf=None, **kw):
    return {"n": n, "stage": stage, "file": f"renders/series10_v2/ep01/S5/takes/{stage}_{n:03d}.png",
            **({"postflight": pf} if pf is not None else {}), **kw}


def test_takes_to_fetch_only_scored_or_active_and_missing():
    td = {"active": {"last": 8, "image": 2},
          "takes": [_t(2, "image", {"ok": True}), _t(8, "last", {"ok": True}), _t(12, "last", {"state": "running", "ok": None}),
                    _t(13, "last", {"ok": False, "blocking": ["Q9"]}), _t(14, "last", {"ok": True}),
                    _t(15, "last", {"state": "orphan", "ok": False}), _t(16, "last", {"ok": True}, quarantined={"at": "x"}),
                    _t(1, "video", {"ok": True})]}
    have = {"data/renders/series10_v2/ep01/S5/takes/image_002.png"}
    out = PU.takes_to_fetch("gpu33", REL, td, {"image", "last"}, exists=lambda r: r in have)
    assert [(q["rel"].rsplit("/", 1)[1], q["stage"]) for q in out] == [("last_008.png", "last"), ("last_014.png", "last")]
    assert all(q["host"] == "gpu33" and q["shot_rel"] == REL and q["why"] == "orphan_take:scored_missing" for q in out)
    # 不归这台的 stage（视频）不拉；没有 stage 归属 → 空
    assert PU.takes_to_fetch("gpu33", REL, td, set(), exists=lambda r: False) == []
    assert [q["stage"] for q in PU.takes_to_fetch("gpu36", REL, td, {"video"}, exists=lambda r: False)] == ["video"]


def test_enqueue_fetch_dedupes(tmp_path):
    q = tmp_path / "fetch_queue.jsonl"
    items = [{"host": "gpu33", "rel": "data/a.png", "stage": "last"}, {"host": "gpu33", "rel": "data/b.png", "stage": "last"}]
    assert PU.enqueue_fetch(items, q) == 2
    assert PU.enqueue_fetch(items + [{"host": "gpu33", "rel": "data/c.png", "stage": "last"}], q) == 1
    rels = [json.loads(x)["rel"] for x in q.read_text(encoding="utf-8").splitlines()]
    assert rels == ["data/a.png", "data/b.png", "data/c.png"]


def test_queue_missing_takes_reads_local_takes_and_owner_stages(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "ops/offline"))
    import merge_pull as MP
    monkeypatch.setattr(PU, "ROOT", tmp_path)
    monkeypatch.setattr(MP, "own_stages", lambda host, ep: {"image", "last"} if host == "gpu33" else set())
    tj = tmp_path / REL
    tj.parent.mkdir(parents=True)
    tj.write_text(json.dumps({"active": {"last": 8}, "takes": [_t(8, "last", {"ok": True}), _t(12, "last", {"state": "running", "ok": None})]}),
                  encoding="utf-8")
    q = tmp_path / "fetch_queue.jsonl"
    assert PU.queue_missing_takes("gpu33", REL, q) == 1
    assert json.loads(q.read_text(encoding="utf-8").splitlines()[0])["rel"] == "data/renders/series10_v2/ep01/S5/takes/last_008.png"
    assert PU.queue_missing_takes("gpu36", REL, q) == 0            # 不归这台
    assert PU.queue_missing_takes("gpu33", "data/renders/x/takes.json", q) == 0   # 没集号
    (tmp_path / "data/renders/series10_v2/ep01/S5/takes").mkdir(parents=True)
    (tmp_path / "data/renders/series10_v2/ep01/S5/takes/last_008.png").write_bytes(b"x")
    assert PU.queue_missing_takes("gpu33", REL, tmp_path / "q2.jsonl") == 0      # 本地已有不排


def test_takes_scan_calls_queue_after_merge():
    src = (ROOT / "tools" / "netfix" / "puller.py").read_text(encoding="utf-8")
    body = src.split("def takes_scan(", 1)[1].split("\nFETCH_QUEUE", 1)[0]
    assert "queue_missing_takes(host, m.name)" in body and "MP.merge_file(host, m.name, dst)" in body
