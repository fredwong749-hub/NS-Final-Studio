"""内容缺陷猎捕（ITERAUDIT 11-01，K-OPS-Q13，项目方 R11-11）：类目齐、检测器能跑、状态可续跑。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "qa"))
import defect_hunt as DH  # noqa: E402


def test_taxonomy_has_40_plus_classes_with_owner_and_stage():
    assert len(DH.CLASSES) >= 40
    ids = [c[0] for c in DH.CLASSES]
    assert len(ids) == len(set(ids))
    stages = {c[1] for c in DH.CLASSES}
    assert {"剧本", "首帧", "视频", "声音", "合成"} <= stages
    assert all(c[6] for c in DH.CLASSES) and all(c[4] in ("auto", "partial", "vlm") for c in DH.CLASSES)


def test_gaze_regex_and_negation():
    assert DH.GAZE_CAM.search("视线=镜头")
    assert DH.GAZE_CAM.search("she looks directly into the camera")
    assert not DH.GAZE_CAM.search(DH.NEG_CTX.sub("", "视线=屏幕"))


def test_beats_parse_and_static_detection(monkeypatch):
    sh = NS(id="ep99-S1", extras=[], duration=6, cast=[NS(name="林晚", presence="在画", x="中")])
    monkeypatch.setitem(DH._cache, "fields", {"ep99-S1": {"分拍": "0–2秒｜保持坐姿｜视线=—；2–4秒｜定住；4–6秒｜静止"}})
    b = DH.beats(sh)
    assert [x["t1"] for x in b] == [2.0, 4.0, 6.0] and b[0]["视线"] == "—"
    monkeypatch.setattr(DH, "shots", lambda: [(None, sh)])
    assert DH.d_static_beats() and DH.d_opening_stare()


def test_run_is_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(DH, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(DH, "VLMQ", tmp_path / "vlm.json")
    calls = []
    monkeypatch.setattr(DH, "CLASSES", [("DH-T1", "剧本", "t", "-", "auto", lambda: calls.append(1) or [("a", "b")], "X", "-"),
                                        ("DH-T2", "首帧", "v", "-", "vlm", DH.vlm("x"), "VQA", "-")])
    DH.run()
    DH.run()                               # 已跑过的类跳过
    assert calls == [1]
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert st["classes"]["DH-T1"]["hits"] == 1 and st["classes"]["DH-T2"]["status"] == "vlm"
    assert json.loads((tmp_path / "vlm.json").read_text(encoding="utf-8"))[0]["class"] == "DH-T2"
    DH.run(force=True)
    assert calls == [1, 1]


# ---- RSI 第 2 轮（fredw-2b 派 11-01 下午）：K-REV-Q03…Q06、K-OPS-Q14、K-OPS-Q15
def _vs(monkeypatch, rows, cur=None):
    monkeypatch.setitem(DH._cache, "vs", rows)
    monkeypatch.setitem(DH._cache, "cur", set(cur or []))


def test_v7_untested_is_not_a_lip_defect(monkeypatch):            # K-REV-Q04
    _vs(monkeypatch, [{"name": "ep99-S1__v1", "v7": {"status": "未测", "why": "脸只在 20% 帧"}},
                      {"name": "ep99-S2__v1", "v7": {"status": "不通过", "why": "corr 0.1"}}])
    v10 = next(c for c in DH.CLASSES if c[0] == "DH-V10")[5]
    assert [a for a, _ in v10()] == ["ep99-S2__v1"]
    assert [a for a, _ in DH.d_v_untested()] == ["ep99-S1__v1"]


def test_null_threshold_is_surfaced(monkeypatch):                 # K-REV-Q05
    _vs(monkeypatch, [{"name": "a__v1", "v6": {"bad_finger_frac": 0.44, "th": {"bad_finger_frac": None, "extra_hand_frac": 0.05}}}])
    out = DH.d_v_null_threshold()
    assert len(out) == 1 and out[0][0] == "V6.bad_finger_frac" and "1 条 >0.2" in out[0][1]


def test_current_version_counts(tmp_path, monkeypatch):           # K-REV-Q03
    monkeypatch.setattr(DH, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(DH, "VLMQ", tmp_path / "vlm.json")
    monkeypatch.setitem(DH._cache, "cur", {"ep99-S1__s2"})
    monkeypatch.setattr(DH, "CLASSES", [("DH-T3", "视频", "t", "-", "auto",
                                         lambda: [("ep99-S1__v1", "x"), ("ep99-S1__s2", "y")], "X", "-")])
    st = DH.run()
    r = st["classes"]["DH-T3"]
    assert r["hits"] == 2 and r["hits_current"] == 1 and r["examples_current"] == ["ep99-S1__s2｜y"]


def test_shipped_defect_detected(monkeypatch):                    # K-REV-Q06
    _vs(monkeypatch, [{"name": "ep99-S2__mot", "gate": {"pass": True}, "v6": {"hands_max": 3, "people": 1}}])
    monkeypatch.setattr(DH, "timelines", lambda: [("ep99_v2.timeline.json", {"shots": [
        {"shot": "ep99-S2", "origin": "VIDEO10 ep99-S2 mot i2va_pdd2 seed 1（540×960 代理）"},
        {"shot": "ep99-S3", "origin": "VIDEO10 ep99-S3 v1 i2va_pdd2 seed 2"}]})])
    out = DH.d_x_shipped_defect()
    assert any("ep99-S2（mot）进了成片" in b and "手最多 3 只" in b for _, b in out)
    assert any("ep99-S3 版本 v1 没有评分记录" in b for _, b in out)


def test_gaze_labels_counted(tmp_path, monkeypatch):              # K-OPS-Q14
    f = tmp_path / "labels.json"
    f.write_text(json.dumps({"img:a.jpg#0": "看镜头", "img:b.jpg#0": "没看镜头", "clip:x__v1.mp4": "开头定格+看镜头",
                             "clip:y__v1.mp4": "开头在动且没看镜头", "clip:z__v1.mp4": "开头定格"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(DH, "GAZE_LABELS", f)
    assert [a for a, _ in DH.d_f_gaze_labeled()] == ["a.jpg#0"]
    assert [a for a, _ in DH.d_v_gaze_labeled()] == ["x__v1", "z__v1"]


def test_vqa_bridge_partial_not_zero(tmp_path, monkeypatch):      # 看图类：没判的不冒充 0 命中
    monkeypatch.setitem(DH._cache, "frames", [{"shot": "ep99-S1", "file": Path("D:/NS-Final Studio/data/renders/ep99/S1/a.png")},
                                              {"shot": "ep99-S2", "file": Path("D:/NS-Final Studio/data/renders/ep99/S2/b.png")}])
    monkeypatch.setattr(DH, "VQA_INDEX", tmp_path / "missing.json")
    assert DH.vqa_bridge("eye_contact")() == {"hits": [], "tested": 0, "total": 2}


def test_every_rule_lint_runs_in_writer_chain():                  # K-OPS-Q15
    import importlib.util as ilu
    import yaml
    for p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
        sys.path.insert(0, str(p))
    spec = ilu.spec_from_file_location("ns_validate_for_q15", ROOT / "tools" / "validate_qwen_script.py")
    V = ilu.module_from_spec(spec)
    spec.loader.exec_module(V)
    compiler = "".join((ROOT / f).read_text(encoding="utf-8") for f in
                       ("packages/schema/ns_schema/h3_lint.py", "services/recipes/ns_recipes/lint.py"))
    missing = []
    for f in sorted((ROOT / "knowledge" / "rules").glob("*.yaml")):
        for r in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("rules") or []:
            for lid in r.get("lint") or []:
                if lid not in V.RULES and f'"{lid}"' not in compiler:
                    missing.append(f"{r['id']}:{lid}")
    assert not missing, f"规则里的 lint 号写作链路不会跑：{missing}"
    assert "VQ-W1" in V.RULES
