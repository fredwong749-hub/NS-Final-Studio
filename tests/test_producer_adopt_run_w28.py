"""W28（C-14 / L-126，P0）：producer adopt_fv2 跨剧泄漏 + quarantine-foreign。

事故：adopt_fv2 读全局 data/assetmaster/frames_v2/state.json（按镜号、不分剧），把 V1 旧图登记进 smoke_v2 / series10_v2 的 takes。
修法：只认 run == 本剧 或文件在 data/renders/<run>/ 下的条目；已泄漏的版本用 quarantine-foreign 隔离（只移不删）。
全部在临时目录，不碰真实 data/。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import producer as PR  # noqa: E402


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path):
    _w(tmp_path / "config/pipeline/run.json", {"run_id": "series10_v2"})
    _w(tmp_path / "config/pipeline/runs.json", {"primary": "series10_v2", "legacy_unprefixed_run": "series10_v1",
                                                "runs": {"series10_v1": {"status": "archived"},
                                                         "series10_v2": {"status": "producing", "assets_manifest": "assets_v2/manifest.json"},
                                                         "smoke_v2": {"status": "paused"}}})
    _w(tmp_path / "assets_v2/manifest.json", {"characters": {"lead_f": {}, "ch_li_an": {}}})
    _w(tmp_path / "data/pipeline/runs/series10_v2/P1_looks.json", [{"name": "祁念", "char_id": "lead_f"}])
    return tmp_path


def _pf(ok=True, who="lead_f"):
    return {"ok": ok, "items": [{"id": "Q1", "status": "pass", "evidence": {"sims": {who: 0.9}, "ref": {who: who}}}], "reasons": []}


class _Fake:
    """只要 adopt_fv2 用到的面：p、logf"""
    adopt_fv2 = PR.Producer.adopt_fv2
    _adopt_same_run = PR.Producer._adopt_same_run

    def __init__(self, paths):
        self.p = paths
        self.events = []

    def logf(self, ev, **kw):
        self.events.append((ev, kw))


def test_adopt_only_same_run(tmp_path, monkeypatch):
    root = _root(tmp_path)
    paths = PR.Paths(root=root, run_id="series10_v2")
    for f in ("data/assetmaster/frames_v2/ep01/a_v1.png", "data/assetmaster/frames_v2/ep01/b_v2.png",
              "data/assetmaster/frames_v2/ep01/c_smoke.png", "data/renders/series10_v2/ep01/S1/takes/d.png",
              "data/renders/ep01/S1/takes/e_v1path.png"):
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_bytes(b"x")
    atts = [{"file": "data/assetmaster/frames_v2/ep01/a_v1.png", "postflight": _pf(who="lin_wan"), "seed": 1},           # 无剧名（V1 旧图）
            {"file": "data/assetmaster/frames_v2/ep01/b_v2.png", "postflight": _pf(), "seed": 2, "run": "series10_v2"},  # 本剧
            {"file": "data/assetmaster/frames_v2/ep01/c_smoke.png", "postflight": _pf(), "seed": 3, "run": "smoke_v2"},  # 他剧
            {"file": "data/renders/series10_v2/ep01/S1/takes/d.png", "postflight": _pf(), "seed": 4},                   # 本剧目录
            {"file": "data/renders/ep01/S1/takes/e_v1path.png", "postflight": _pf(), "seed": 5}]                        # V1 目录
    _w(paths.frames_v2, {"ep01-S1": {"image": {"attempts": atts}}})
    got, seen_src = [], []

    class RT:
        @staticmethod
        def register(it, label):
            got.append(it["seed"])
            seen_src.append(it["origin"]["src_run"])
            return {"status": "registered", "n": len(got)}
    monkeypatch.setitem(sys.modules, "register_takes", RT)
    fk = _Fake(paths)
    reg = {"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S1", "objects": {"first": {"id": "ep01-S1:first", "status": "ready"},
                                                                            "last": {"id": "ep01-S1:last", "status": "passed"}}}]}]}
    assert fk.adopt_fv2(reg) == 2
    assert sorted(got) == [2, 4]
    assert all(it_run == "series10_v2" for it_run in seen_src)
    skips = [kw for ev, kw in fk.events if ev == "adopt_skip"]
    assert len(skips) == 3 and all(k["counted"] is False for k in skips)
    assert {k["why"] for k in skips} == {"跨剧", "无剧名"}
    fk.adopt_fv2(reg)                                  # 同一条只记一次 adopt_skip（不刷日志）
    assert len([1 for ev, _ in fk.events if ev == "adopt_skip"]) == 3


def test_fv2_attempt_run_ok_legacy_paths(tmp_path):
    root = _root(tmp_path)
    v1 = PR.Paths(root=root, run_id="series10_v1")
    assert PR.fv2_attempt_run_ok(v1, {"file": "data/renders/ep01/S1/takes/x.png"})
    assert not PR.fv2_attempt_run_ok(v1, {"file": "data/renders/series10_v2/ep01/S1/takes/x.png"})
    assert PR.fv2_attempt_run_ok(v1, {"run": "series10_v1", "file": "data/assetmaster/frames_v2/x.png"})
    assert not PR.fv2_attempt_run_ok(v1, {"file": "data/assetmaster/frames_v2/x.png"})


def _takes_fixture(root):
    sd = root / "data/renders/series10_v2/ep01/S1"
    (sd / "takes").mkdir(parents=True, exist_ok=True)
    for n in ("image_001_ok.png", "image_003_badrole.png"):
        (sd / "takes" / n).write_bytes(b"x")
    v1f = root / "data/renders/ep01/S1/takes/image_002_pipeline_v1.png"
    v1f.parent.mkdir(parents=True, exist_ok=True)
    v1f.write_bytes(b"v1")
    doc = {"takes": [
        {"n": 1, "stage": "image", "file": "renders/series10_v2/ep01/S1/takes/image_001_ok.png", "postflight": _pf()},
        {"n": 2, "stage": "image", "file": "renders/ep01/S1/takes/image_002_pipeline_v1.png", "postflight": _pf(who="lin_wan")},
        {"n": 3, "stage": "image", "file": "renders/series10_v2/ep01/S1/takes/image_003_badrole.png", "postflight": _pf(who="lin_wan")},
        {"n": 4, "stage": "image", "file": "renders/series10_v2/ep01/S1/takes/image_004_noface.png", "postflight": {"ok": False, "items": []},
         "params": {"origin": {"run": "assetmaster/frames_v2"}}},
        {"n": 5, "stage": "image", "file": "renders/series10_v2/ep01/S1/takes/image_005_adopt_ok.png", "postflight": _pf(),
         "params": {"origin": {"run": "assetmaster/frames_v2", "src_run": "series10_v2"}}}],
        "active": {"image": 3}, "seq": 4}
    _w(sd / "takes.json", doc)
    return sd, v1f


def test_quarantine_foreign_dry_writes_nothing(tmp_path):
    root = _root(tmp_path)
    sd, v1f = _takes_fixture(root)
    before = (sd / "takes.json").read_text(encoding="utf-8")
    r = PR.quarantine_foreign(PR.Paths(root=root, run_id="series10_v2"), apply=False, ts="T", rules={"path", "role", "origin"})
    assert r["takes"] == 3 and r["shots"] == 1 and r["current"] == 1
    assert r["by_rule"] == {"origin": 1, "path": 1, "role": 2}
    assert {x["n"] for x in r["rows"]} == {2, 3, 4}
    r2 = PR.quarantine_foreign(PR.Paths(root=root, run_id="series10_v2"), apply=False, ts="T")   # 缺省 origin,role
    assert {x["n"] for x in r2["rows"]} == {2, 3, 4} and r2["rules"] == ["origin", "role"]
    assert (sd / "takes.json").read_text(encoding="utf-8") == before
    assert not (root / "data/quarantine").exists()


def test_quarantine_foreign_apply_moves_only_in_run(tmp_path):
    root = _root(tmp_path)
    sd, v1f = _takes_fixture(root)
    calls = []

    def mutate(tj, fn):                                 # 测试替身：同 mutate_takes 的读-改-写
        d = json.loads(tj.read_text(encoding="utf-8"))
        d = fn(d) or d
        tj.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        calls.append(tj)
    r = PR.quarantine_foreign(PR.Paths(root=root, run_id="series10_v2"), apply=True, ts="T", mutate=mutate, by="test")
    d = json.loads((sd / "takes.json").read_text(encoding="utf-8"))
    assert [t["n"] for t in d["takes"]] == [1, 5]
    q = {t["n"]: t for t in d["quarantined"]}
    assert set(q) == {2, 3, 4} and q[3]["postflight"]["ok"] is True          # 保留全部字段
    assert q[3]["quarantine"]["active_cleared"] and "image" not in d["active"]
    assert q[2]["quarantine"]["moved_to"] is None and v1f.is_file()        # 不在本剧目录的文件不动
    moved = root / "data/quarantine/series10_v2/T/files/renders/series10_v2/ep01/S1/takes/image_003_badrole.png"
    assert moved.is_file() and not (sd / "takes/image_003_badrole.png").exists()
    assert (sd / "takes/image_001_ok.png").is_file()
    man = json.loads((root / "data/quarantine/series10_v2/T/manifest.json").read_text(encoding="utf-8"))
    assert man["takes"] == 3 and man["mode"] == "apply" and len(calls) == 1


def test_quarantine_role_rule_off_when_no_table(tmp_path):
    root = _root(tmp_path)
    sd = root / "data/renders/smoke_v2/ep01/S1"
    _w(sd / "takes.json", {"takes": [{"n": 1, "stage": "image", "file": "renders/smoke_v2/ep01/S1/takes/a.png",
                                      "postflight": _pf(who="whoever")}], "active": {}})
    r = PR.quarantine_foreign(PR.Paths(root=root, run_id="smoke_v2"), apply=False)
    assert r["takes"] == 0 and r["role_rule"].startswith("off")
