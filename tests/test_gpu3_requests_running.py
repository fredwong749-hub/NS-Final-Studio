"""封板修复：runner 事件写 running（不是 started），镜像回退和桥路径都显示为渲染中"""
import json

from ns_api import gpu3_requests as G


def test_running_event_mirror_and_bridge(tmp_path):
    (tmp_path / "rerender_queue.jsonl").write_text(json.dumps({"id": "r1", "shot": "ep2-S1", "stage": "image"}) + "\n", encoding="utf-8")
    (tmp_path / "rerender_events.jsonl").write_text(json.dumps({"id": "r1", "state": "running"}) + "\n", encoding="utf-8")
    [x] = G.from_mirror(tmp_path, G.PJC.DEFAULT_SLUG)
    assert x["shot"] == "ep02-S1" and x["state"] == "started"
    assert G._unfold("running", [{"stage": "image"}]) == "image_done"
