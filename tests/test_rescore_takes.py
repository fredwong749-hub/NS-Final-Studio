"""DATAALIGN 11-01：重打分两步走（先出计划不写、审过 --apply 再写）+ rescore_history 追加不覆盖。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen_contract"))

import rescore_takes as RT  # noqa: E402


@pytest.fixture()
def shot(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    data = tmp_path / "data"
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    d = data / "renders" / "ep09" / "S1"
    d.mkdir(parents=True)
    (data / "renders" / "ep09" / "S1" / "a.png").write_bytes(b"x")
    take = {"n": 1, "stage": "image", "file": "renders/ep09/S1/a.png",
            "postflight": {"ok": True, "items": [], "ts": "t0", "rescored": {"at": "old", "was_ok": None, "now_ok": True}}}
    (d / "takes.json").write_text(json.dumps({"takes": [take], "active": {"image": 1}}), encoding="utf-8")
    import remote_score as RS
    from ns_render import unified_frame as UF
    monkeypatch.setattr(UF, "_ctx_for", lambda sid, t: {"cast": []})
    fail = {"ok": False, "items": [{"id": "Q1", "status": "fail", "detail": "认不出是谁"}], "blocking": ["Q1"]}
    monkeypatch.setattr(RS, "postflight_full", lambda host, jobs, label=None: {j["id"]: fail for j in jobs})
    calls = []
    from ns_render import auto_current as AC
    monkeypatch.setattr(AC, "on_contract", lambda *a: calls.append(a))
    return {"P": P, "path": d / "takes.json", "calls": calls}


def _pf(shot):
    return json.loads(shot["path"].read_text(encoding="utf-8"))["takes"][0]["postflight"]


def test_scoring_run_writes_nothing_until_apply(shot):
    plan = RT.main(["--keys", "ep09-S1|image|1"])
    assert _pf(shot)["ok"] is True and not shot["calls"]                # 只出计划：版本和“当前”都没动
    p = json.loads(Path(plan).read_text(encoding="utf-8"))
    assert [r["key"] for r in RT.flips(p)] == ["ep09-S1|image|1"]
    assert RT.main(["--apply", str(plan)]) == ["ep09-S1|image|1"]
    assert _pf(shot)["ok"] is False and shot["calls"] == [("ep09-S1", "image", 1)]


def test_apply_skips_take_changed_after_plan(shot):
    plan = RT.main(["--keys", "ep09-S1|image|1"])
    d = json.loads(shot["path"].read_text(encoding="utf-8"))
    d["takes"][0]["postflight"]["ts"] = "someone-else"
    shot["path"].write_text(json.dumps(d), encoding="utf-8")
    assert RT.main(["--apply", str(plan)]) == []


def test_rescore_history_appends_and_keeps_was_ok(shot):
    for _ in range(2):
        RT.main(["--apply", str(RT.main(["--keys", "ep09-S1|image|1"]))])
    h = _pf(shot)["rescore_history"]
    assert len(h) == 3 and h[0]["at"] == "old"                         # 旧格式单条并进历史
    assert h[1]["was_ok"] is True and h[1]["now_ok"] is False          # 第一次重打之前曾通过——不丢
    assert h[2]["was_ok"] is False and _pf(shot)["rescored"] == h[2]
