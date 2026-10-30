"""封板修复（docs/release/debug_api.md）：
- D-1：S1 按集判剧本版本（合并导入后 ep01 = v3、其余 v2）——v3 的集不再被 script_not_v3 拦
- QA4-01：剧本源文件导入后又改过 → SOP 状态里出 warn 级提醒（不拦镜头），重复登记的旧条目不误报
全部在临时目录里。"""
import hashlib
import json
from pathlib import Path

import pytest

from ns_api import sop as SOP
from ns_schema.script import ScriptImport

PINNED = Path(__file__).resolve().parent / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture()
def root(tmp_path):
    lib = tmp_path / "script play lib"
    lib.mkdir()
    v2 = lib / "剧本和镜头 v2.md"
    v2.write_text("v2 原稿", encoding="utf-8")
    chat = tmp_path / "data" / "script_chat" / "x" / "script.md"
    chat.parent.mkdir(parents=True)
    chat.write_text("v3 ep01", encoding="utf-8")
    sc = ScriptImport.model_validate_json(PINNED.read_text(encoding="utf-8")).model_copy(deep=True)
    sc.episodes = sc.episodes[:2]
    sc.sources = ScriptImport.model_validate({"sources": [
        {"path": str(v2), "sha256": _sha(v2)},
        {"path": "data\\script_chat\\x\\script.md", "sha256": "0" * 64},          # 旧条目（被后面同路径条目取代）
        {"path": "data\\script_chat\\x\\script.md", "sha256": _sha(chat), "version": "v3", "episodes": [1]},
    ], "globals": {}, "episodes": []}).sources
    (tmp_path / "data" / "import").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "import" / "script_v2.json").write_text(sc.model_dump_json(), encoding="utf-8")
    tl = {"provisional": True, "source": {"script": "v2"},
          "s1_gate": {"validator_errors": 0, "g3_accepted": True, "g3_ref": "项目方原话（测试）"},
          "episodes": {}, "shots": []}
    (tmp_path / "data" / "state_timeline.json").write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _rows(root):
    sc = ScriptImport.model_validate_json((root / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    return [{"id": s.id, "episode": e.number, "index": s.index} for e in sc.episodes for s in e.shots[:2]]


def _ev(root):
    inp = SOP.Inputs(root, root / "renders_gpu3")
    return inp, SOP.evaluate(inp, _rows(root), project_owner="laptop")


def test_d1_s1_is_judged_per_episode(root):
    inp, ev = _ev(root)
    assert inp.ep_versions == {1: "v3", 2: "v2"}
    codes = {s["episode"]: [b["code"] for b in s["stages"]["S1"]["blockers"]] for s in ev["shots"]}
    assert "script_not_v3" not in codes[1] and codes[1] == []          # ep01 v3 + 校验 0 + G3 → S1 过
    assert "script_not_v3" in codes[2]
    b2 = next(b for s in ev["shots"] if s["episode"] == 2 for b in s["stages"]["S1"]["blockers"])
    assert "第 2 集" in b2["text"] and "v2" in b2["text"]
    assert all(s["stage"] != "S1" for s in ev["shots"] if s["episode"] == 1)
    assert all(s["stage"] == "S1" for s in ev["shots"] if s["episode"] == 2)
    # 项目级：只说“部分集仍是 v2”，G3 不因此等上游
    assert [b["code"] for b in ev["s1"]["blockers"]] == ["script_partial_v3"]
    assert "部分集仍是 v2" in ev["s1"]["blockers"][0]["text"]
    assert ev["gpu_priority"]["order"][0]["pending"] == 1


def test_d1_all_v2_still_blocked_and_no_script_falls_back(root):
    p = root / "data" / "import" / "script_v2.json"
    sc = ScriptImport.model_validate_json(p.read_text(encoding="utf-8"))
    sc.sources = sc.sources[:1]
    p.write_text(sc.model_dump_json(), encoding="utf-8")
    _, ev = _ev(root)
    assert [b["code"] for b in ev["s1"]["blockers"]] == ["script_not_v3"]
    assert all("script_not_v3" in [b["code"] for b in s["stages"]["S1"]["blockers"]] for s in ev["shots"])
    rows = _rows(root)
    p.unlink()                                   # 没有剧本文件 → 退回状态表整份版本（旧行为）
    inp = SOP.Inputs(root, root / "renders_gpu3")
    ev = SOP.evaluate(inp, rows, project_owner="laptop")
    assert inp.ep_versions == {} and [b["code"] for b in ev["s1"]["blockers"]] == ["script_not_v3"]


def test_qa4_01_source_drift_is_warn_only(root):
    inp, ev = _ev(root)
    assert inp.source_drift == [] and ev["s1"]["warnings"] == []      # 重复登记的旧条目不误报
    assert not any(a["gate"] == "source_drift" for a in ev["owner_actions"])
    before = [s["stage"] for s in ev["shots"]]
    (root / "script play lib" / "剧本和镜头 v2.md").write_text("v2 原稿（导入后又改了）", encoding="utf-8")
    inp, ev = _ev(root)
    w = ev["s1"]["warnings"]
    assert len(w) == 1 and w[0]["code"] == "source_drift" and w[0]["level"] == "warn"
    assert "剧本源文件导入后又改过，需重新导入" in w[0]["text"] and "剧本和镜头 v2.md" in w[0]["text"]
    assert w[0]["paths"] == [inp.source_drift[0]["path"]]
    assert "source_drift" not in [b["code"] for b in ev["s1"]["blockers"]]
    assert [s["stage"] for s in ev["shots"]] == before                  # 不拦镜头
    act = next(a for a in ev["owner_actions"] if a["gate"] == "source_drift")
    assert act["level"] == "warn" and act["cli"] is None
    summ = SOP.project_summary("t", "t", ev, inp)
    assert summ["s1"]["warnings"][0]["code"] == "source_drift"


def test_qa4_01_falls_back_to_timeline_changed_sources(tmp_path):
    (tmp_path / "data").mkdir()
    tl = {"source": {"script": "v3", "changed_sources": [{"path": "a.md", "imported_sha": "1", "current_sha": None},
                                                         "junk"]}, "shots": []}
    (tmp_path / "data" / "state_timeline.json").write_text(json.dumps(tl), encoding="utf-8")
    inp = SOP.Inputs(tmp_path, tmp_path / "g")
    w = SOP.source_drift_warning(inp)
    assert w["paths"] == ["a.md"] and "找不到文件" in w["text"]
