"""DATAALIGN 2026-11-01：VIDEO10 过门的片子登记成视频版本（tools/pipeline/register_takes.py --video10），
画布 / 集摘要 / /api/progress 的 video 才读得到；VIDEO10 片子不和画布 H3 视图比提示词（不误标“剧本已改”）。"""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _rt():
    spec = importlib.util.spec_from_file_location("register_takes", REPO / "tools" / "pipeline" / "register_takes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_items_from_video10_picks_done_chosen_pass(tmp_path, monkeypatch):
    rt = _rt()
    clip = tmp_path / "_preview" / "ep01-S1__v1.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")
    st = {"host": "h1", "shots": {
        "ep01-S1": {"status": "done", "chosen": "v1", "renders": [{"variant": "v1", "state": "scored", "file": "nope.mp4",
                    "preview": str(clip), "seed": 3, "score": {"verdict": "pass", "gate": {"pass": True, "fails": []}}}]},
        "ep01-S2": {"status": "running", "chosen": None, "renders": []}}}
    (tmp_path / "state_h1.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "state_h1_validate.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "jobs.json").write_text(json.dumps({"shots": [{"shot": "ep01-S1", "frames": 107, "variants": {"v1": {"prompt": "P"}}}]}),
                                        encoding="utf-8")
    items = rt.items_from_video10(tmp_path)
    assert [i["shot"] for i in items] == ["ep01-S1"]                 # 跳过 *_validate、没做完的镜头
    it = items[0]
    assert it["stage"] == "video" and it["workflow"] == "video10" and it["origin"]["preview"] is True
    assert it["file"] == str(clip) and it["prompt"] == "P" and it["frames"] == 107 and it["postflight"]["ok"] is True


def test_video10_take_not_compared_to_canvas_prompt():
    from ns_api import unified_stale as UST
    assert UST.is_video10({"stage": "video", "workflow": "video10"})
    assert UST.is_video10({"stage": "video", "params": {"origin": {"run": "series10_v1/video"}}})
    assert not UST.is_video10({"stage": "image", "workflow": "video10"})
