"""fredw-92/G36：多服务器渲染道（gpu33 int 道 + gpu36 "gpu36:n" 道）与自动分配。

项目方：“当 gpu 不做 image 的时候也可以转成 rendering video 啊”——卡不固定出图 / 视频，按偏好和空闲分：
出图偏好 gpu33:0，没有就任意空闲道；视频任何空闲道都能接（image 道要等出图队列空）；都忙排最短的队。
"""
from __future__ import annotations

import json

import pytest

from ns_api import jobs as J
from ns_render import endpoints as EP
from ns_render.comfy_client import ComfyClient

CFG = {"image": {"url": "http://127.0.0.1:18188", "gpu": 0}, "video": {"url": "http://127.0.0.1:18191", "gpu": 3},
       "gpus": {"0": "http://127.0.0.1:18188", "1": "http://127.0.0.1:18189", "3": "http://127.0.0.1:18191"},
       "lanes": {"gpu36:0": "http://127.0.0.1:18288", "gpu36:1": {"url": "http://127.0.0.1:18289", "max_frames": 241},
                 "gpu36:2": "http://127.0.0.1:18290"}}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "render_endpoints.json"
    p.write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(EP, "CONFIG", p)
    from ns_api import llm_config as LC
    monkeypatch.setattr(LC, "RENDER_FILE", p)
    for k in ("NS_COMFY_URL", "NS_COMFY_URL_GPU0", "NS_COMFY_URL_GPU1", "NS_COMFY_URL_GPU3", "NS_COMFY_URL_GPU36_0"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(J, "_jobs", {})
    monkeypatch.setattr(J, "reachable_fn", lambda url: {"reachable": True, "running": 0, "pending": 0})
    monkeypatch.setattr(J, "train_lock_fn", lambda server: set())
    monkeypatch.setattr(J, "_train_cache", {})
    yield p
    J._jobs.clear()          # 假任务（没有线程在跑）不要让 conftest 的 drain 等


def _job(gpu, kind="frame", state="running"):
    jid = f"j{len(J._jobs)}"
    J._jobs[jid] = {"id": jid, "gpu": gpu, "kind": kind, "state": state}


def test_lane_ids_and_backward_compat(cfg):
    assert tuple(J.GPUS) == (0, 1, 3, "gpu36:0", "gpu36:1", "gpu36:2")
    assert 0 in J.GPUS and "gpu33:3" in J.GPUS and "3" in J.GPUS and "gpu36:2" in J.GPUS
    assert "gpu36:3" not in J.GPUS and 2 not in J.GPUS and None not in J.GPUS and True not in J.GPUS
    assert EP.norm_lane("gpu33:0") == 0 and EP.norm_lane("gpu36:01") == "gpu36:1"
    assert J.comfy_url("gpu36:1") == "http://127.0.0.1:18289" and J.comfy_url("gpu33:3") == "http://127.0.0.1:18191"
    assert EP.max_frames("gpu36:1") == 241 and EP.max_frames("gpu36:0") == EP.DEFAULT_MAX_FRAMES
    assert EP.server_of(3) == "gpu33" and EP.server_of("gpu36:2") == "gpu36" and EP.lane_name(1) == "gpu33:1"
    with pytest.raises(ValueError):
        EP.url_for_gpu("gpu36:9")


def test_instance_identity_includes_server(cfg):
    c36 = J._make_client("gpu36:0")
    c33 = J._make_client(0)
    argv = {"system": {"argv": ["main.py", "--output-directory", "/x/output/gpu0"]}}
    c36.system_stats = c33.system_stats = lambda: argv
    assert c33.instance() == "out:/x/output/gpu0"                      # gpu33 不变（旧 remote index 仍有效）
    assert c36.instance() == "gpu36|out:/x/output/gpu0"                # 同名目录在另一台服务器上 ≠ 同一实例
    assert isinstance(c36, ComfyClient) and c36.base == "http://127.0.0.1:18288"


def test_image_prefers_gpu33_0_when_idle(cfg):
    assert J.pick_lane("image") == 0


def test_image_lane_takes_video_when_idle_and_no_images_waiting(cfg):
    for g in (1, 3, "gpu36:0", "gpu36:1", "gpu36:2"):
        _job(g, "video")
    assert J.pick_lane("video") == 0                                     # 出图卡空闲、出图队列空 → 接视频
    _job("gpu36:0", "frame", "queued")                                   # 有出图任务在排队 → 出图卡留给出图
    assert J.pick_lane("video") != 0


def test_new_image_rerouted_while_image_lane_renders_video(cfg):
    _job(0, "video")                                                     # gpu33:0 正在出 13 分钟的视频
    assert J.pick_lane("image") == 1                                     # 改派到别的空闲道，不排在视频后面
    for g in (1, 3, "gpu36:0", "gpu36:1"):
        _job(g, "video")
    assert J.pick_lane("image") == "gpu36:2"


def test_all_busy_shortest_queue(cfg):
    for g in (1, 3, "gpu36:0", "gpu36:1", "gpu36:2"):
        _job(g, "video")
    _job(0, "frame")
    _job("gpu36:2", "video", "queued")
    assert J.pick_lane("image") == 0                                     # 出图：出图卡只排着一张图，最短
    assert J.pick_lane("video") == 1                                     # 视频：非出图道里最短（并列取靠前的）
    _job(1, "frame", "queued")
    assert J.pick_lane("video") == 3


def test_video_prefers_non_image_idle_lane_and_respects_max_frames(cfg):
    assert J.pick_lane("video") == 1
    assert J.pick_lane("video", frames=230) == "gpu36:1"                 # 只有 gpu36:1 标了 241 帧


def test_unreachable_lanes_skipped(cfg, monkeypatch):
    monkeypatch.setattr(J, "reachable_fn", lambda url: {"reachable": url.endswith("18290")})
    assert J.pick_lane("image") == "gpu36:2" and J.pick_lane("video") == "gpu36:2"
    monkeypatch.setattr(J, "reachable_fn", lambda url: {"reachable": False})
    assert J.pick_lane("image") == 0 and J.pick_lane("video") == 3     # 全不可达 → 默认道（提交时会报连不上）


def test_external_comfy_queue_counts_as_busy(cfg, monkeypatch):
    monkeypatch.setattr(J, "reachable_fn",
                        lambda url: {"reachable": True, "running": 1 if url.endswith("18188") else 0, "pending": 0})
    assert J.pick_lane("image") == 1                                     # gpu33:0 上有别人直接投的任务


def test_lanes_status_text(cfg):
    _job(0, "frame")
    _job("gpu36:1", "video")
    by = {ln["id"]: ln for ln in J.lanes()}
    assert by["gpu33:0"]["status_text"] == "gpu33:0 · 正在出图" and by["gpu33:0"]["image_pref"] is True
    assert by["gpu36:1"]["status_text"] == "gpu36:1 · 出视频" and by["gpu36:1"]["server"] == "gpu36"
    assert by["gpu36:2"]["activity"] == "idle" and by["gpu36:2"]["status_text"].endswith("空闲")


def test_resolve_lane_and_requests(cfg):
    assert J.resolve_lane(None, "image") == 0 and J.resolve_lane("auto", "video") == 1
    assert J.resolve_lane("gpu36:1", "video") == "gpu36:1" and J.resolve_lane("3", "video") == 3
    with pytest.raises(ValueError):
        J.resolve_lane("gpu99:0", "image")
    from fastapi import HTTPException
    from ns_api import video_jobs as VJ
    VJ._validate(VJ.VideoJobRequest(gpu="gpu36:2"))
    VJ._validate(VJ.VideoJobRequest())
    with pytest.raises(HTTPException):
        VJ._validate(VJ.VideoJobRequest(gpu="gpu36:7"))


def test_submit_runs_on_string_lane(cfg, monkeypatch):
    import threading
    done = threading.Event()
    seen = {}

    class Fake:
        pass
    monkeypatch.setattr(J, "client_factory", lambda gpu: (seen.setdefault("gpu", gpu), Fake())[1])
    monkeypatch.setattr(J, "persist", lambda job: None)

    def run(client, job):
        done.set()
        return {}
    job = J.submit("frame", None, "gpu36:0", run)
    assert job["gpu"] == "gpu36:0"
    assert done.wait(5) and seen["gpu"] == "gpu36:0"


def test_render_endpoints_lists_lanes_and_put_lane(cfg, monkeypatch):
    from ns_api import llm_config as LC
    monkeypatch.setattr(LC, "_probe", lambda url: (True, "ok"))
    rows = LC.get_render_endpoints()
    assert [r["id"] for r in rows][:2] == ["image", "video"]
    lanes = {r["id"]: r for r in rows if r.get("kind") == "lane"}
    assert set(lanes) == {"gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"}
    assert lanes["gpu36:1"]["reachable"] is True and lanes["gpu36:1"]["max_frames"] == 241
    r = LC.put_render_endpoint("gpu36:1", LC.EndpointBody(url="http://127.0.0.1:28289/"))
    assert r["url"] == "http://127.0.0.1:28289"
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["lanes"]["gpu36:1"] == {"url": "http://127.0.0.1:28289", "max_frames": 241}
    assert saved["image"] == CFG["image"] and saved["lanes"]["gpu36:0"] == CFG["lanes"]["gpu36:0"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        LC.put_render_endpoint("gpu36:9", LC.EndpointBody(url="http://a"))


def test_train_lock_skips_lane(cfg, monkeypatch):
    """训练锁：gpu33 的 train.lock.gpu1 / gpu36 的 locks/train.lock.gpu0 → 这两条道不派活（缓存 30 s）"""
    calls = []

    def fake(server):
        calls.append(server)
        return {1} if server == "gpu33" else {0}
    monkeypatch.setattr(J, "train_lock_fn", fake)
    monkeypatch.setattr(J, "_train_cache", {})
    by = {ln["id"]: ln for ln in J.lanes()}
    assert by["gpu33:1"]["train_locked"] and not by["gpu33:1"]["ok"] and by["gpu33:1"]["status_text"].endswith("训练占用")
    assert by["gpu36:0"]["train_locked"] and not by["gpu36:0"]["ok"]
    assert by["gpu33:3"]["ok"] and not by["gpu33:3"]["train_locked"]
    assert J.pick_lane("video") == 3                                     # gpu33:1 锁着 → 跳过
    _job(0, "video")
    _job(3, "video")
    assert J.pick_lane("image") == "gpu36:1"                             # gpu36:0 锁着 → 跳过
    assert sorted(calls) == ["gpu33", "gpu36"]                           # 缓存 30 s：三次选卡只读一次


def test_train_lock_unreadable_counts_as_unlocked(cfg, monkeypatch, caplog):
    def boom(server):
        raise RuntimeError("ssh timeout")
    monkeypatch.setattr(J, "train_lock_fn", boom)
    monkeypatch.setattr(J, "_train_cache", {})
    with caplog.at_level("WARNING"):
        assert J.pick_lane("image") == 0
    assert "按无锁" in caplog.text


def test_parse_train_locks_hidden_files():
    """fredw-92：.train.lock.gpu1（点开头）也算锁；改名带后缀的已释放锁不算"""
    listing = "train.lock.gpu0\n.train.lock.gpu1\n.train.lock.gpu3.released-ep02\ntrain.lock.gpu2.bak\n"
    assert J.parse_train_locks(listing) == {0, 1}


def test_train_lock_unreadable_keeps_last_known(cfg, monkeypatch):
    """fredw-92：读过一次锁之后 ssh 读不到 → 沿用上次的锁，不当作无锁"""
    monkeypatch.setattr(J, "_train_cache", {"gpu33": (0.0, {1})})      # 已过期的上次结果

    def boom(server):
        raise RuntimeError("ssh timeout")
    monkeypatch.setattr(J, "train_lock_fn", boom)
    assert J.lane_train_locked_now(1) and not J.lane_train_locked_now(3)


def test_worker_refuses_lane_locked_at_start(cfg, monkeypatch):
    """fredw-92：选道时锁还没读到、出发前现读到了训练锁 → 任务不跑，失败原因带“训练锁”（EB 当可恢复错误重派）"""
    import time as _t
    from ns_api import episode_produce as E
    monkeypatch.setattr(J, "train_lock_fn", lambda server: {1} if server == "gpu33" else set())
    ran = []
    j = J.submit("video", "ep99-S1", 1, lambda client, job: ran.append(1) or {})
    for _ in range(100):
        if J.get(j["id"])["state"] not in ("queued", "running"):
            break
        _t.sleep(0.02)
    got = J.get(j["id"])
    assert got["state"] == "failed" and J.TRAIN_LOCKED_ERR in got["error"] and not ran
    assert E.is_transient(got["error"])
    ok = J.submit("video", "ep99-S2", 3, lambda client, job: ran.append(3) or {})
    for _ in range(100):
        if J.get(ok["id"])["state"] == "done":
            break
        _t.sleep(0.02)
    assert J.get(ok["id"])["state"] == "done" and ran == [3]
