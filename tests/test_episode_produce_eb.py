"""fredw-92/EB 整集出片：假道 / 假任务 / 假版本，不碰 GPU、不碰真实 data。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from ns_api import episode_produce as EPR


class FakeHooks(EPR.Hooks):
    """内存里的镜头版本 + 任务；任务由测试调用 finish()/fail() 结束"""

    def __init__(self, shots=("ep09-S1", "ep09-S2", "ep09-S3"), lanes=None, frames=None, final=False):
        self.shot_ids = list(shots)
        self._lanes = lanes or [
            {"gpu": 0, "label": "gpu33 GPU0", "image_pref": True, "max_frames": 192, "ok": True},
            {"gpu": 1, "label": "gpu33 GPU1", "image_pref": False, "max_frames": 192, "ok": True},
            {"gpu": 3, "label": "gpu33 GPU3", "image_pref": False, "max_frames": 192, "ok": True},
        ]
        self.frames = frames or {}
        self.final = final
        self.data = {s: {"takes": [], "active": {}, "locked": {}} for s in shots}
        self.fresh_map = {s: {"image": False, "last": False, "video": False} for s in shots}
        self.jobs: dict[str, dict] = {}
        self.order: list[tuple] = []          # (shot, stage, step, gpu)
        self.locks: list[tuple] = []
        self.marks: list[tuple] = []
        self.n = 0
        self.t = 0.0

    def lanes(self):
        return [dict(x) for x in self._lanes]

    def busy(self, gpu):
        return any(j["gpu"] == gpu and j["state"] in ("queued", "running") for j in self.jobs.values())

    def submit(self, shot_id, stage, step, gpu, parent=None):
        if stage == "last" and self.data[shot_id]["locked"].get("image") is None:
            raise EPR.Blocked("首帧还没定稿")
        self.n += 1
        jid = f"j{self.n}"
        self.jobs[jid] = {"id": jid, "job_id": jid, "gpu": gpu, "state": "queued", "shot": shot_id, "stage": stage,
                          "step": step, "parent": parent}
        self.order.append((shot_id, stage, step, gpu))
        return dict(self.jobs[jid])

    def job(self, jid):
        j = self.jobs.get(jid)
        return dict(j) if j else None

    def cancel(self, jid):
        self.jobs[jid]["state"] = "cancelled"

    def pending(self, shot_id, kind):
        return []

    def takes(self, shot_id):
        return self.data[shot_id]

    def lock(self, shot_id, stage, n, by, run_id):
        self.data[shot_id]["locked"][EPR.ST[stage]] = n
        self.locks.append((shot_id, stage, n, by))

    def mark(self, shot_id, stage, n, by, run_id):
        self.marks.append((shot_id, stage, n, by))

    def fresh(self, shot_id):
        return dict(self.fresh_map[shot_id])

    def video_frames(self, shot_id):
        return self.frames.get(shot_id, 125)

    def final_wanted(self, tier_first):
        return tier_first == "final" if tier_first else self.final

    def episode_shots(self, n):
        return self.shot_ids if n == 9 else None

    def recent(self, kind, gpus):
        return []

    def now(self):
        return self.t

    # ---- 测试辅助
    def running(self):
        return [j for j in self.jobs.values() if j["state"] in ("queued", "running")]

    def finish(self, jid):
        j = self.jobs[jid]
        st = EPR.ST[j["stage"]]
        n = 1 + max([t["n"] for t in self.data[j["shot"]]["takes"] if t["stage"] == st] or [0])
        take = {"stage": st, "n": n, "file": f"{st}{n}.png"}
        if j["step"] == "final":
            take.update(mode="final", parent=j["parent"])
            if self.data[j["shot"]]["locked"].get(st) == j["parent"]:
                self.data[j["shot"]]["locked"][st] = n          # 定稿档接替定稿（final_tier.render_final）
        self.data[j["shot"]]["takes"].append(take)
        self.data[j["shot"]]["active"][st] = n
        j.update(state="done", take_n=n, wall_s=10.0)

    def fail(self, jid, error):
        self.jobs[jid].update(state="failed", error=error)

    def finish_all(self):
        for j in list(self.running()):
            self.finish(j["id"])


@pytest.fixture
def mk(tmp_path):
    def make(**kw):
        h = FakeHooks(**kw)
        return h, EPR.Producer(hooks=h, root=tmp_path / "episodes")
    return make


def run_until_idle(h, pr, limit=50):
    for _ in range(limit):
        pr.tick()
        if not h.running():
            pr.tick()
            if not h.running():
                return
        h.finish_all()


def test_dag_order_and_auto_lock(mk):
    h, pr = mk()
    pr.start(9, stages=["first", "last", "video"], mode="auto_lock")
    pr.tick()
    # 三个镜头的首帧同时铺到三条道（image 道先接一个，其余空闲道也可接出图）
    assert sorted(o[3] for o in h.order) == [0, 1, 3]
    assert all(o[1] == "first" for o in h.order)
    run_until_idle(h, pr)
    for sid in h.shot_ids:
        stages = [o[1] for o in h.order if o[0] == sid]
        assert stages == ["first", "last", "video"]
        assert [x[1] for x in h.locks if x[0] == sid] == ["first", "last", "video"]
        assert all(x[3] == "auto" for x in h.locks)
    v = pr.view(9)
    assert v["state"] == "done"
    assert all(s["stages"][st]["state"] == "done" for s in v["shots"] for st in ("first", "last", "video"))


def test_final_tier_inserted_after_lock(mk):
    h, pr = mk(shots=("ep09-S1",), final=True)
    pr.start(9, stages=["first", "last"], mode="auto_lock")
    run_until_idle(h, pr)
    assert [(o[1], o[2]) for o in h.order] == [("first", "gen"), ("first", "final"), ("last", "gen"), ("last", "final")]
    lk = h.data["ep09-S1"]["locked"]
    assert lk == {"image": 2, "last": 2}                # 定稿档接替定稿
    assert ("ep09-S1", "first", 2, "auto") in h.marks   # 接替的版本也记 by auto


def test_review_mode_waits_for_owner_lock(mk):
    h, pr = mk(shots=("ep09-S1",))
    pr.start(9, stages=["first", "last", "video"], mode="review")
    pr.tick()
    h.finish_all()
    pr.tick()
    pr.tick()
    v = pr.view(9)
    assert v["shots"][0]["stages"]["first"]["state"] == "review"
    assert len(h.order) == 1 and not h.locks
    h.data["ep09-S1"]["locked"]["image"] = 1            # 项目方在画布定稿
    pr.tick()
    assert h.order[-1][1] == "last"
    h.finish_all()
    pr.tick()
    assert pr.view(9)["shots"][0]["stages"]["last"]["state"] == "review"
    h.data["ep09-S1"]["locked"]["last"] = 1
    pr.tick()
    assert h.order[-1][1] == "video"
    h.finish_all()
    pr.tick()
    assert pr.view(9)["state"] == "done"
    assert not h.locks                                  # review 模式不自动定稿


def test_skip_fresh_and_force(mk):
    h, pr = mk(shots=("ep09-S1", "ep09-S2"))
    for s in h.shot_ids:
        h.data[s]["takes"] = [{"stage": "image", "n": 1, "file": "a"}, {"stage": "last", "n": 1, "file": "b"},
                              {"stage": "video", "n": 1, "file": "c"}]
        h.data[s]["locked"] = {"image": 1, "last": 1}
        h.data[s]["active"] = {"image": 1, "last": 1, "video": 1}
    h.fresh_map["ep09-S1"] = {"image": True, "last": True, "video": True}
    h.fresh_map["ep09-S2"] = {"image": True, "last": True, "video": False}
    pr.start(9, stages=["first", "last", "video"], mode="auto_lock")
    pr.tick()
    assert h.order == [("ep09-S2", "video", "video", 1)] or [o[:3] for o in h.order] == [("ep09-S2", "video", "video")]
    v = pr.view(9)
    assert v["shots"][0]["stages"]["first"]["state"] == "skipped"
    assert v["shots"][0]["stages"]["video"]["state"] == "skipped"
    run_until_idle(h, pr)
    # force：只重出视频阶段
    h2, pr2 = mk(shots=("ep09-S1",))
    h2.data = {"ep09-S1": h.data["ep09-S1"]}
    h2.fresh_map = {"ep09-S1": {"image": True, "last": True, "video": True}}
    pr2.start(9, stages=["video"], mode="auto_lock", force=True)
    run_until_idle(h2, pr2)
    assert [o[1] for o in h2.order] == ["video"]
    assert pr2.view(9)["shots"][0]["stages"]["video"]["state"] == "done"


def test_video_only_spreads_over_lanes(mk):
    h, pr = mk(shots=("ep09-S1", "ep09-S2", "ep09-S3", "ep09-S4"))
    for s in h.shot_ids:
        h.fresh_map[s] = {"image": True, "last": True, "video": True}
        h.data[s]["locked"] = {"image": 1, "last": 1}
        h.data[s]["takes"] = [{"stage": "image", "n": 1, "file": "a"}, {"stage": "last", "n": 1, "file": "b"}]
    pr.start(9, stages=["video"], mode="auto_lock", force=True)
    pr.tick()
    assert sorted(o[3] for o in h.order) == [0, 1, 3]   # 三条道各一个，第 4 个等空闲
    assert len({o[0] for o in h.order}) == 3
    lanes = {ln["gpu"]: ln["busy_with"] for ln in pr.view(9)["lanes"]}
    assert all(len(v) == 1 for v in lanes.values())
    h.finish(h.running()[0]["id"])
    pr.tick()
    assert len(h.order) == 4


def test_frames_prefer_image_lane(mk):
    h, pr = mk(shots=("ep09-S1",))
    pr.start(9, stages=["first"], mode="auto_lock")
    pr.tick()
    assert h.order == [("ep09-S1", "first", "gen", 0)]


def test_long_shot_waits_never_truncated(mk):
    h, pr = mk(shots=("ep09-S1", "ep09-S2"), frames={"ep09-S1": 294})
    for s in h.shot_ids:
        h.fresh_map[s] = {"image": True, "last": True, "video": False}
        h.data[s]["locked"] = {"image": 1, "last": 1}
        h.data[s]["takes"] = [{"stage": "image", "n": 1, "file": "a"}, {"stage": "last", "n": 1, "file": "b"}]
    pr.start(9, stages=["video"], mode="auto_lock")
    pr.tick()
    assert [o[0] for o in h.order] == ["ep09-S2"]
    st = pr.view(9)["shots"][0]["stages"]["video"]
    assert st["state"] == "waiting" and "294" in st["reason"] and "不截短" in st["reason"]
    h.finish_all()
    pr.tick()
    assert pr.view(9)["state"] == "waiting"
    # LS 落地：某道上限提高 → 自动派出
    h._lanes[2]["max_frames"] = 362
    pr.tick()
    assert h.order[-1] == ("ep09-S1", "video", "video", 3)


def test_oom_waits_and_transient_retries(mk):
    h, pr = mk(shots=("ep09-S1", "ep09-S2"))
    for s in h.shot_ids:
        h.fresh_map[s] = {"image": True, "last": True, "video": False}
        h.data[s]["locked"] = {"image": 1, "last": 1}
        h.data[s]["takes"] = [{"stage": "image", "n": 1, "file": "a"}, {"stage": "last", "n": 1, "file": "b"}]
    pr.start(9, stages=["video"], mode="auto_lock")
    pr.tick()
    j1, j2 = [j["id"] for j in h.running()]
    h.fail(j1, "执行失败: Allocation on device torch.OutOfMemoryError: CUDA out of memory")
    h.fail(j2, "超时 3600s")
    pr.tick()
    v = {s["shot_id"]: s["stages"]["video"] for s in pr.view(9)["shots"]}
    assert v["ep09-S1"]["state"] == "waiting" and "OOM" in v["ep09-S1"]["reason"]
    assert v["ep09-S2"]["state"] == "queued"            # 可恢复：已重提
    h.fail(h.running()[0]["id"], "ComfyUnavailable: 连不上")
    pr.tick()
    assert pr.view(9)["shots"][1]["stages"]["video"]["state"] == "queued"   # 第 3 次提交（重试 2 次）
    h.fail(h.running()[0]["id"], "ComfyUnavailable: 连不上")
    pr.tick()
    assert pr.view(9)["shots"][1]["stages"]["video"]["state"] == "failed"   # 重试 2 次后放弃
    assert [o[0] for o in h.order].count("ep09-S1") == 1                     # OOM 不重试
    assert len(pr.view(9)["failures"]) == 2


def test_resume_after_restart(mk, tmp_path):
    h, pr = mk(shots=("ep09-S1", "ep09-S2"))
    pr.start(9, stages=["first", "last"], mode="auto_lock")
    pr.tick()
    assert len(h.running()) == 2
    # API 重启：jobs.restore 把没跑完的任务标 failed “API 重启中断”；新进程从盘上读回
    for j in h.running():
        h.fail(j["id"], "API 重启中断")
    pr2 = EPR.Producer(hooks=h, root=tmp_path / "episodes")
    pr2.ensure_thread = lambda: None
    assert pr2.resume() == [9]
    pr2.tick()
    assert len(h.running()) == 2                        # 重新提交
    run_until_idle(h, pr2)
    assert pr2.view(9)["state"] == "done"
    assert [o[1] for o in h.order if o[0] == "ep09-S1"] == ["first", "first", "last"]


def test_cancel_and_validation(mk):
    h, pr = mk()
    with pytest.raises(HTTPException) as e:
        pr.start(9, stages=["bogus"], mode="auto_lock")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        pr.start(9, stages=["first"], mode="nope")
    with pytest.raises(HTTPException) as e:
        pr.start(4, stages=["first"], mode="auto_lock")
    assert e.value.status_code == 404
    pr.start(9, stages=["first"], mode="auto_lock", shots=["ep09-S2"])
    with pytest.raises(HTTPException) as e:
        pr.start(9, stages=["first"], mode="auto_lock")
    assert e.value.status_code == 409
    pr.tick()
    out = pr.cancel(9)
    assert out["state"] == "cancelled"
    assert all(j["state"] == "cancelled" for j in h.jobs.values())
    assert [s["shot_id"] for s in out["shots"]] == ["ep09-S2"]


def test_error_classes():
    assert EPR.is_oom("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 4.97 GiB")
    assert not EPR.is_oom("room for improvement")
    assert EPR.is_transient("超时 1800s") and EPR.is_transient("API 重启中断")
    assert not EPR.is_transient("执行失败: KeyError 'clip'")


def test_routes_registered(mk, monkeypatch):
    from fastapi.testclient import TestClient
    from ns_api import app as A
    h, pr = mk()
    monkeypatch.setattr(EPR, "PRODUCER", pr)
    pr.ensure_thread = lambda: None
    c = TestClient(A.app)
    assert c.get("/api/episodes/9/produce").json()["state"] == "none"
    r = c.post("/api/episodes/9/produce", json={"stages": ["first"], "mode": "review"})
    assert r.status_code == 200 and r.json()["mode"] == "review"
    assert c.post("/api/episodes/9/produce", json={"stages": ["first"]}).status_code == 409
    assert c.post("/api/episodes/9/produce/cancel").json()["state"] == "cancelled"
