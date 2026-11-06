"""W-REFS 11-06：重试阶梯各档的派生参考图（refboards / refcrops）在笔记本预生成、进推送清单；服务器上本档缺图 → 退回默认参考、不烧尝试。

起因：gpu36 23:36 ep02-S13 第 3 次“退到 两张脸 + 参考板（B）”→ DerivedRefMissing board_1394f5efddbd.png（只在笔记本生成、按 sha 推，
K-OPS-F23；笔记本只编默认档 → 这张板从没生成过）→ content_error，第 3 次白烧、标“尽力”。
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/autopilot", "tools/pipeline", "services/agent", "services/render_router", "packages/schema", "services/api"):
    sys.path.insert(0, str(ROOT / p))
import preflight_deps as PD  # noqa: E402
import producer as PR  # noqa: E402
from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402

BOARD_RUNG = {"name": "第 3 次：退到 两张脸 + 参考板（B）", "seed": 1, "plan_kw": {"two_person": "both_faces"},
              "board": True, "variant": "faces_board"}


def _key(r: dict) -> tuple:
    return (tuple(sorted((r.get("plan_kw") or {}).items())), r.get("variant"), bool(r.get("board")))


# ------------------------------------------------------------------ ② 服务器上本档缺图 → 退回默认参考
def test_board_rung_missing_falls_back_to_default(monkeypatch):
    calls = []

    def core(project, ep, shot, g, rung, kind, run_id):
        calls.append(dict(rung))
        if rung.get("board"):
            raise AR.DerivedRefMissing("资产缺图：派生参考图 data/x/refboards/board_1394f5efddbd.png 服务器上没有")
        return {"prompt": "p", "refs": ["data/face.png"]}

    monkeypatch.setattr(PR, "_rung_core", core)
    rung = dict(BOARD_RUNG)
    job = PR.first_job_for_rung("r", None, None, None, rung, "first", "r")
    assert job["refs"] == ["data/face.png"]
    assert len(calls) == 2 and not calls[1].get("board") and not calls[1].get("plan_kw")
    assert rung["rung_skip"]["variant"] == "faces_board" and "board_1394f5efddbd" in rung["rung_skip"]["error"]
    assert rung["variant"] == "derived_missing_default" and "退回默认参考" in rung["name"]


def test_default_rung_missing_still_raises(monkeypatch):
    def core(*a, **k):
        raise AR.DerivedRefMissing("资产缺图")
    monkeypatch.setattr(PR, "_rung_core", core)
    with pytest.raises(AR.DerivedRefMissing):
        PR.first_job_for_rung("r", None, None, None, {"name": "第 1 次", "seed": 1}, "first", "r")


def test_last_rung_missing_falls_back(monkeypatch):
    seen = []

    def bl(first_job, first_file, *, project=None, ep=None, shot=None, g=None, plan_kw=None, **k):
        seen.append(plan_kw)
        if plan_kw:
            raise AR.DerivedRefMissing("资产缺图：fl")
        return {"refs": [first_file]}

    monkeypatch.setattr(FJ, "build_last", bl)
    rung = {"name": "第 2 次：首尾太像", "plan_kw": {"fl_escalate": 1}}
    job = PR.last_job_for_rung("r", None, None, None, {}, "data/f.png", rung)
    assert job == {"refs": ["data/f.png"]} and seen == [{"fl_escalate": 1}, {}]
    assert rung["rung_skip"]["stage"] == "last_job"


# ------------------------------------------------------------------ ① 预生成覆盖阶梯能选到的每一档
def test_prebuild_rungs_cover_ladder():
    fake = types.SimpleNamespace(two_person=lambda sid: True, seed_pick=lambda o, a, *x: (7, {}),
                                 fl_escalate_level=lambda o, a: 0, script=lambda: None)
    o = {"id": "first:ep02-S13", "kind": "first", "shot": "ep02-S13"}
    want = set()
    for a in (1, 2, 3):
        want.add(_key(PR.Producer.rung_ab(fake, o, a)))
        for stg in ("A", "B"):
            want.add(_key(PR.Producer.rung_strategy(fake, o, a, {"strategy": stg})))
    want.add(_key({"plan_kw": {"two_person": "both_faces"}}))          # rung() 第 3 次双人镜
    have = {_key(r) for r in PR.prebuild_rungs("first", True)}
    assert want <= have, want - have
    assert ((("two_person", "both_faces"),), "faces_board", True) in have
    last = {_key(r) for r in PR.prebuild_rungs("last", True)}
    assert {((("fl_escalate", 1),), None, False), ((("fl_escalate", 2),), None, False), ((), None, False)} <= last


# ------------------------------------------------------------------ 只在笔记本生成；冻结的剧不写；缓存命中不重编
def test_rung_deps_never_on_server(monkeypatch):
    monkeypatch.setattr(AR, "_on_server", lambda: True)
    r = PD.rung_deps(types.SimpleNamespace(episodes=[]), "series10_v2", {})
    assert r["files"] == [] and "服务器" in r["skipped"]


def test_rung_deps_respects_frozen_run(monkeypatch):
    monkeypatch.setattr(AR, "_on_server", lambda: False)
    monkeypatch.setattr(AR, "derived_writable", lambda run: False)
    r = PD.rung_deps(types.SimpleNamespace(episodes=[]), "series10_v1", {})
    assert r["files"] == [] and "不在制作中" in r["skipped"]


def test_rung_deps_builds_once_then_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(PD, "shot_triggered", lambda run, sid: False)   # L-216：线上已触发成人镜，本测只验“未触发的成人镜不做”
    asset = next(iter(sorted((ROOT / "assets").rglob("*.png"))), None)
    if asset is None:
        pytest.skip("仓库里没有 assets/*.png")
    rel = asset.relative_to(ROOT).as_posix()
    monkeypatch.setattr(AR, "_on_server", lambda: False)
    monkeypatch.setattr(AR, "derived_writable", lambda run: True)
    monkeypatch.setattr(AR, "DERIVED_OUT", tmp_path)
    monkeypatch.setattr(PD, "_passed_import_eps", lambda run: {2})
    n = {"first": 0}

    def fj(project, ep, shot, g, rung, kind, run_id):
        n["first"] += 1
        return {"prompt": "p", "refs": [rel], "last_prompt": "l"}

    monkeypatch.setattr(PR, "first_job_for_rung", fj)
    monkeypatch.setattr(PR, "last_job_for_rung", lambda *a, **k: {"refs": [rel]})
    monkeypatch.setattr(PR, "active_take", lambda td, stage: None)
    two = [types.SimpleNamespace(presence="在画"), types.SimpleNamespace(presence="在画")]
    shots = [types.SimpleNamespace(id="ep02-S13", cast=two), types.SimpleNamespace(id="ep02-S6", cast=two, adult=True),
             types.SimpleNamespace(id="ep05-S1", cast=two)]
    sc = types.SimpleNamespace(episodes=[types.SimpleNamespace(shots=shots)], globals=None)
    jobs = {s.id: {"prompt": "p", "refs": [rel]} for s in shots}
    r1 = PD.rung_deps(sc, "series10_v2", jobs)
    assert r1["built"] == 1 and r1["cached"] == 0 and r1["files"] == [rel] and not r1["errors"]   # 成人镜、没过导入闸门的集不做
    assert n["first"] == len(PR.prebuild_rungs("first", True)) + len(PR.prebuild_rungs("last", True))
    r2 = PD.rung_deps(sc, "series10_v2", jobs)
    assert r2["built"] == 0 and r2["cached"] == 1 and r2["files"] == [rel]
    assert n["first"] == len(PR.prebuild_rungs("first", True)) + len(PR.prebuild_rungs("last", True))   # 命中：不再编


def test_adult_filter_matches_sop_gate_per_shot(monkeypatch, tmp_path):
    """混合集：只有 shot.adult 的镜跳过（与 sop_gate.adult_shots_of / compile_preflight 同一口径），其余镜照做；
    不按集、不按默认作业里的资产 adult 标记一刀切"""
    sys.path.insert(0, str(ROOT / "tools" / "master"))
    import sop_gate as SG
    asset = next(iter(sorted((ROOT / "assets").rglob("*.png"))), None)
    if asset is None:
        pytest.skip("仓库里没有 assets/*.png")
    rel = asset.relative_to(ROOT).as_posix()
    raw = [{"index": i, "adult": i >= 8} for i in range(1, 12)]            # ep03 式混合：S8–S11 成人
    monkeypatch.setattr(SG, "_ep_shots", lambda run, ep, root: raw)
    monkeypatch.setattr(SG, "triggered_adult_shots", lambda run, ep, root=None: set())   # 本测只验口径，不读线上触发清单（L-216 已触发的另测）
    want_adult = SG.adult_shots_of("series10_v2", 3)
    assert want_adult == {8, 9, 10, 11}
    assert {r["index"] for r in raw if PD.adult_shot(r)} == want_adult
    monkeypatch.setattr(AR, "_on_server", lambda: False)
    monkeypatch.setattr(AR, "derived_writable", lambda run: True)
    monkeypatch.setattr(AR, "DERIVED_OUT", tmp_path)
    monkeypatch.setattr(PD, "_passed_import_eps", lambda run: {3})
    monkeypatch.setattr(PR, "first_job_for_rung", lambda *a, **k: {"prompt": "p", "refs": [rel]})
    monkeypatch.setattr(PR, "active_take", lambda td, stage: None)
    shots = [types.SimpleNamespace(id=f"ep03-S{r['index']}", cast=[], adult=r["adult"]) for r in raw]
    sc = types.SimpleNamespace(episodes=[types.SimpleNamespace(shots=shots)], globals=None)
    jobs = {s.id: {"prompt": "p", "refs": [rel], "adult": s.id == "ep03-S3"} for s in shots}   # 资产 adult 标记不参与判定
    r = PD.rung_deps(sc, "series10_v2", jobs)
    assert sorted(r["per_shot"], key=lambda s: int(s.split("S")[1])) == [f"ep03-S{i}" for i in range(1, 8)]


def test_preflight_deps_survives_rung_deps_error(monkeypatch):
    """复审 11-06：rung_deps 抛错不能拖垮 preflight_deps（resident_sync 推送清单），默认档照出、错误进 errors"""
    import preflight_deps as PD
    def boom(*a, **k):
        raise ValueError("corrupt _derived_index.json")
    monkeypatch.setattr(PD, "rung_deps", boom)
    try:
        r = PD.preflight_deps(include_rungs=True)
    except ValueError:
        raise AssertionError("rung_deps 的异常漏出了 preflight_deps")
    assert isinstance(r.get("files"), list)
    errs = r.get("errors") or {}
    assert "_rungs" not in errs or "corrupt" in errs["_rungs"]


def test_triggered_adult_shot_is_prebuilt(monkeypatch):
    """L-216：项目方已触发的成人镜照常预建参考板（未触发的仍跳过）"""
    sh = types.SimpleNamespace(id="ep03-S2", adult=True, cast=[])
    monkeypatch.setattr(PD, "shot_triggered", lambda run, sid: sid == "ep03-S2")
    assert PD.adult_shot(sh) and PD.shot_triggered("series10_v2", sh.id)
    monkeypatch.setattr(PD, "shot_triggered", lambda run, sid: False)
    assert not PD.shot_triggered("series10_v2", sh.id)
