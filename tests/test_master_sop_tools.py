"""tools/master：report_issue（卡点登记）+ episode_ready（第 8 步资产就绪检查）+ autoflow 接线。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RI = _load("report_issue", "tools/master/report_issue.py")
ER = _load("episode_ready", "tools/master/episode_ready.py")


def test_report_list_close(tmp_path):
    iss, live = tmp_path / "issues.jsonl", tmp_path / "V2_LIVE.md"
    live.write_text("标题行\n旧的一行\n", encoding="utf-8")
    rec = RI.report("series10_v2", 1, "8", "TESTER", "卓琳没有身份脸", True, "找项目方挑", issues=iss, live=live)
    lines = live.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "标题行" and "⚠ 卡点（TESTER）" in lines[1] and lines[2] == "旧的一行"
    assert [i["id"] for i in RI.load(iss) if i["status"] == "open"] == [rec["id"]]
    ok, msg = RI.close(rec["id"], False, iss)
    assert ok and "还没写进 PIPELINE_SOP_V2.md" in msg
    assert RI.load(iss)[0]["status"] == "closed"
    rec2 = RI.report("r", 2, "3", "T", "x", False, issues=iss, live=None)
    ok, msg = RI.close(rec2["id"], True, iss)
    assert ok and "还没写进" not in msg
    assert RI.close("ISS-nope", True, iss)[0] is False


def _er_fixture(monkeypatch, tmp_path, *, faces=(), names=(), unvoiced=(), scene_missing=True, looks=False, look_missing=()):
    """episode_ready 夹具（总调度 11-03 裁定：不写死真实数据）：两镜假导入稿 + 假清单 / 身份脸 / 音色，缺口由参数决定"""
    import types
    from ns_agent import asset_refs as AR
    from ns_agent import cast_table as CT
    from ns_agent import run_paths as RP
    from ns_post import run_media as RM
    doc = {"episodes": [{"number": 1, "shots": [
        {"index": 1, "adult": False, "cast": [{"name": "甲"}], "dialogue": [{"speaker": "甲", "text": "x"}]},
        {"index": 2, "adult": True, "adult_reasons": ["r"], "cast": [{"name": "乙"}], "dialogue": [{"speaker": "乙", "text": "y"}]}]}]}
    sp = tmp_path / "script.json"
    sp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    ids = {"甲": "ch_a", "乙": "ch_b"}
    monkeypatch.setattr(RP, "runs_module", lambda root=None: types.SimpleNamespace(script_path=lambda run, root=None: sp))

    def resolve_shot(run, ep, s):
        n = s["cast"][0]["name"]
        miss = [{"kind": "场景缺图", "detail": "sk_fx 没有参考底图"}] if scene_missing else []
        miss += [{"kind": "造型未登记", "character": n, "detail": f"{n} 本镜造型对不上 P1 登记"} for m in look_missing if m == n]
        return types.SimpleNamespace(characters=[{"character": ids[n], "name": n, "look": "L1" if looks else None}],
                                     scene_id="sk_fx", missing=miss)
    monkeypatch.setattr(AR, "resolve_shot", resolve_shot)
    lk = {"L1": {"items": {"L1_garment": {"name": "外套"}}}} if looks else {}       # 有造型、没有 sheet（设定图）
    monkeypatch.setattr(AR, "manifest", lambda run: {"characters": {ids[n]: {"display_name": n, "looks": lk} for n in names}})
    monkeypatch.setattr(AR, "face_of", lambda run, cid: "f.png" if cid in {ids[n] for n in faces} else None)
    monkeypatch.setattr(AR, "episode_look_override", lambda run, cid, ep: "L1" if looks else None)
    monkeypatch.setattr(CT, "speaker_cast", lambda run: {"names": ids})
    un = {ids[n]: True for n in unvoiced}
    monkeypatch.setattr(RM, "voice_config", lambda run, root=None: {
        "unvoiced": un, "characters": {c: {"voice": c + "/a"} for c in ids.values() if c not in un}})
    return ER.check("fx_run", 1, root=tmp_path)


def test_episode_ready_fixture_lists_all_gaps(monkeypatch, tmp_path):
    """缺口一次列全：脸 / display_name / 场景 / 音色，每个缺口带负责方和镜号"""
    res = _er_fixture(monkeypatch, tmp_path, faces=("乙",), names=("乙",), unvoiced=("甲",))
    kinds = {(g["kind"], g["who"].split("（")[0]) for g in res["gaps"]}
    assert kinds == {("scene", "sk_fx"), ("face", "甲"), ("name", "甲"), ("voice", "甲")}
    assert next(g for g in res["gaps"] if g["kind"] == "scene")["shots"] == [1, 2]
    assert all(g["owner"] for g in res["gaps"])
    assert res["ready"] is False and [s["index"] for s in res["shots"]] == [1, 2]
    assert [s["adult"] for s in res["shots"]] == [False, True] and res["shots"][1]["reasons"] == ["r"]
    assert res["voices"] == {"乙": "ch_b/a"}


def test_episode_ready_fixture_gap_disappears_when_asset_added(monkeypatch, tmp_path):
    """资产补上 → 对应缺口消失（11-03 卓琳音色补上后旧测试写死的“缺音色”断言失败，就是这条要防的）"""
    res = _er_fixture(monkeypatch, tmp_path, faces=("甲", "乙"), names=("甲", "乙"), unvoiced=(), scene_missing=False)
    assert res["gaps"] == [] and res["ready"] is True
    res = _er_fixture(monkeypatch, tmp_path, faces=("甲", "乙"), names=("甲", "乙"), unvoiced=("乙",), scene_missing=False)
    assert [(g["kind"], g["who"]) for g in res["gaps"]] == [("voice", "乙（ch_b）")]


def test_episode_ready_series10_v2_ep1_matches_data():
    """真实数据冒烟：期望值从数据源现场推算（导入稿镜数、face_of、清单 display_name、voice_config），不写死哪个人缺什么"""
    from ns_agent import asset_refs as AR
    from ns_agent import cast_table as CT
    from ns_agent import run_paths as RP
    from ns_post import run_media as RM
    src = Path(RP.runs_module(ROOT).script_path("series10_v2", ROOT))
    if not src.is_file():
        import pytest
        pytest.skip("没有 series10_v2 导入稿")
    ep = next(e for e in json.loads(src.read_text(encoding="utf-8"))["episodes"] if int(e.get("number") or 0) == 1)
    res = ER.check("series10_v2", 1)
    assert len(res["shots"]) == len(ep["shots"]) and all("adult" in s and "reasons" in s for s in res["shots"])
    assert res["ready"] is (not res["gaps"]) and all(g["owner"] for g in res["gaps"])
    got = {(g["kind"], g["who"]) for g in res["gaps"]}
    mchars = (AR.manifest("series10_v2") or {}).get("characters") or {}
    for cid, d in res["cast"].items():
        rc = ER.resolve_cid("series10_v2", cid, d["name"])
        who = f"{d['name']}（{rc}）"
        assert (("face", who) in got) is (not AR.face_of("series10_v2", rc))
        assert (("name", who) in got) is (not (mchars.get(rc) or {}).get("display_name"))
    names = (CT.speaker_cast("series10_v2") or {}).get("names") or {}
    try:
        cfg = RM.voice_config("series10_v2", ROOT)
    except Exception:
        return                                  # 配置读不出来时 check 报一条“音色配置读不出来”，上面已断言 ready 口径
    spk = {dl["speaker"] for s in ep["shots"] for dl in s.get("dialogue") or [] if dl.get("speaker")}
    for sp in spk:
        cid = names.get(sp)
        if cid in (cfg.get("unvoiced") or {}):
            assert ("voice", f"{sp}（{cid}）") in got
        elif cid in (cfg.get("characters") or {}):
            assert not any(k == "voice" and w.startswith(sp + "（") for k, w in got)


def test_episode_ready_missing_script_is_gap():
    res = ER.check("no_such_run", 1)
    assert res["ready"] is False and res["gaps"][0]["kind"] == "script"


def test_episode_ready_exit_code(monkeypatch):
    monkeypatch.setattr(ER, "check", lambda run, ep: {"run": run, "episode": ep, "ready": True, "gaps": [], "shots": []})
    assert ER.main(["--run", "x", "--episode", "1"]) == 0
    monkeypatch.setattr(ER, "check", lambda run, ep: {"run": run, "episode": ep, "ready": False, "shots": [],
                                                      "gaps": [{"kind": "face", "who": "a", "what": "b", "owner": "c", "shots": [1]}]})
    assert ER.main(["--run", "x", "--episode", "1"]) == 1


def test_autoflow_hook_reports_each_gap(monkeypatch, tmp_path):
    AF = _load("autoflow_hook_t", "tools/script_rsi/autoflow.py")
    calls = []
    fake = {"ready": False, "gaps": [{"kind": "face", "who": "卓琳", "what": "没有身份脸", "owner": "资产线", "shots": [1]},
                                     {"kind": "scene", "who": "sk_white_cyc", "what": "没有底图", "owner": "资产线", "shots": [1, 2]}]}
    monkeypatch.setattr(ER, "check", lambda run, ep: fake)
    monkeypatch.setattr(RI, "report", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(AF, "_load", lambda name, rel: ER if "episode_ready" in rel else RI)

    class St:
        def __init__(self): self.d = {}; self.stages = []
        def stage(self, *a, **k): self.stages.append(a)
        def set(self, **k): self.d.update(k)
    st = St()
    AF.ready_after_import("series10_v2", 1, st)
    assert len(calls) == 2 and all(c[5] is True for c in calls)       # blocking=True
    assert "卓琳" in st.d["next_action"] and "sk_white_cyc" in st.d["next_action"]


def test_no_look_gap_when_preflight_i3_i4_pass(monkeypatch, tmp_path):
    """造型没有 sheet 但 preflight I3 / I4 过（resolve_shot 没有造型 / 资产缺图）→ episode_ready 不能报造型缺口；
    resolve_shot 报“造型未登记”时才报（夹具，不写死真实数据；总调度 11-03）"""
    full = dict(faces=("甲", "乙"), names=("甲", "乙"), scene_missing=False, looks=True)
    res = _er_fixture(monkeypatch, tmp_path, **full)
    assert not ({"look", "item", "sheet"} & {g["kind"] for g in res["gaps"]}) and res["ready"] is True
    res = _er_fixture(monkeypatch, tmp_path, **full, look_missing=("乙",))
    assert [(g["kind"], g["who"], g["shots"]) for g in res["gaps"]] == [("look", "乙", [2])]
