"""fredw-92/QCV：视频运动量质检（ns_render.motion_qc）、出片前首尾帧差、只给首帧的对齐句、整集出片不自动定稿静止视频、
合成器警告。阈值按 ep02 现有版本校准（docs/QC_ep02_20261031.md §6）。不碰 GPU。"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ns_render import h3_video as HV
from ns_render import motion_qc as MQ

from test_episode_produce_eb import FakeHooks, run_until_idle  # noqa: F401  复用假道
from ns_api import episode_produce as EPR
from test_frame_jobs_w2 import SHOT, env  # noqa: F401,E402

TH = dict(MQ.DEFAULTS)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "post"))


def _frames(n, step):
    """n 帧 96×168；每帧整体亮度 +step（相邻帧平均差 = step）"""
    base = np.full((MQ.H, MQ.W), 100.0, np.float32)
    return np.stack([base + i * step for i in range(n)])


def test_mid_clip_cut_warns():
    """RR：中途跳切（只给首帧时 H3 偶尔自己切镜）→ “中途跳切 Ns”，warn；平滑运动不误报"""
    fr = _frames(96, 1.5)
    assert MQ.motion_metrics(fr, 24.0, TH)["cut_s"] == []
    cut = fr.copy()
    cut[30:] = 30.0 + (cut[30:] - cut[30])      # 第 30 帧整体跳 ~115 灰度
    m = MQ.motion_metrics(cut, 24.0, TH)
    assert m["cut_s"] == [pytest.approx(30 / 24, abs=0.01)]
    j = MQ.judge(m, TH)
    assert j["verdict"] == "warn" and "中途跳切 1.2s" in j["labels"]


def test_static_clip_fails():
    m = MQ.motion_metrics(_frames(48, 0.1), 24.0, TH)
    assert m["mean_diff"] == pytest.approx(0.1, abs=1e-3) and m["still_frac"] == 1.0
    j = MQ.judge(m, TH)
    assert j["verdict"] == "fail" and "静止·不合格" in j["labels"]


def test_moving_clip_passes_and_frozen_tail_warns():
    fr = _frames(96, 1.5)
    assert MQ.judge(MQ.motion_metrics(fr, 24.0, TH), TH)["verdict"] == "pass"
    tail = np.concatenate([fr[:72], np.repeat(fr[71:72], 24, axis=0)])     # 最后 1 s 定住
    m = MQ.motion_metrics(tail, 24.0, TH)
    assert m["frozen_tail_s"] == pytest.approx(1.0, abs=0.05)
    j = MQ.judge(m, TH)
    assert j["verdict"] == "warn" and any(x.startswith("结尾定住") for x in j["labels"])


def test_ep02_calibration_numbers():
    """docs/QC_ep02_20261031.md §6 的实测：S1 通过；S7 / S4 静止不合格；S5 中段大动作只算提示；S9 偏弱"""
    s1 = {"mean_diff": 3.744, "p90_diff": 7.816, "still_frac": 0.147, "frozen_tail_s": 0.88, "frozen_head_s": 0.0}
    s7 = {"mean_diff": 0.151, "p90_diff": 0.297, "still_frac": 0.953, "frozen_tail_s": 6.5, "frozen_head_s": 0.71}
    s4 = {"mean_diff": 0.223, "p90_diff": 0.362, "still_frac": 0.86, "frozen_tail_s": 1.04, "frozen_head_s": 0.71}
    s3 = {"mean_diff": 0.324, "p90_diff": 0.489, "still_frac": 0.561, "frozen_tail_s": 0.67, "frozen_head_s": 0.71}
    s5 = {"mean_diff": 1.083, "p90_diff": 2.158, "still_frac": 0.817, "frozen_tail_s": 2.79, "frozen_head_s": 2.79}
    s9 = {"mean_diff": 0.788, "p90_diff": 1.473, "still_frac": 0.242, "frozen_tail_s": 0.83, "frozen_head_s": 0.0}
    assert MQ.judge(s1, TH)["verdict"] == "pass"
    for m in (s7, s4, s3):
        assert MQ.judge(m, TH)["verdict"] == "fail"
    assert MQ.judge(s5, TH)["verdict"] == "warn"
    assert MQ.judge(s9, TH)["labels"] == ["动作偏弱"]
    assert "结尾定住 6.5s" in MQ.judge(s7, TH)["labels"]
    # 对照实验 S4 只给首帧：一直在小幅动（静止帧 38%）→ 偏弱，不判不合格；S8 v2 静止帧 48.5% 同理
    s4a = {"mean_diff": 0.42, "p90_diff": 0.64, "still_frac": 0.376, "frozen_tail_s": 0.33, "frozen_head_s": 0.0}
    s8 = {"mean_diff": 0.402, "p90_diff": 0.805, "still_frac": 0.485, "frozen_tail_s": 1.58, "frozen_head_s": 0.0}
    assert MQ.judge(s4a, TH)["labels"] == ["动作偏弱"]
    assert MQ.judge(s8, TH)["labels"] == ["动作偏弱", "结尾定住 1.6s"]


def test_keyframe_check(tmp_path):
    from PIL import Image
    a = np.full((1344, 768, 3), 120, np.uint8)
    Image.fromarray(a).save(tmp_path / "a.png")
    Image.fromarray(a + 4).save(tmp_path / "b.png")
    b2 = a.copy()
    b2[:672] = 250
    Image.fromarray(b2).save(tmp_path / "c.png")
    near = MQ.keyframe_check(tmp_path / "a.png", tmp_path / "b.png", TH)
    assert near["warn"] and near["first_last_diff"] == pytest.approx(4, abs=0.5) and "几乎一样" in near["message"]
    far = MQ.keyframe_check(tmp_path / "a.png", tmp_path / "c.png", TH)
    assert not far["warn"] and far["message"] is None
    assert MQ.keyframe_check(tmp_path / "x.png", tmp_path / "b.png", TH)["error"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="没有 ffmpeg")
def test_video_motion_on_real_file(tmp_path):
    still, moving = tmp_path / "still.mp4", tmp_path / "moving.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=96x168:d=2:r=24",
                    "-pix_fmt", "yuv420p", str(still)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "nullsrc=s=96x168:d=2:r=24,geq=lum='mod(X*3+T*240,255)':cb=128:cr=128",
                    "-pix_fmt", "yuv420p", str(moving)], check=True)
    assert MQ.video_motion(still)["verdict"] == "fail"
    mo = MQ.video_motion(moving)
    assert mo["metrics"]["mean_diff"] > 1 and mo["verdict"] in ("pass", "warn") and mo["version"] == MQ.VERSION
    assert MQ.video_motion(tmp_path / "missing.mp4")["verdict"] == "unknown"


def test_thresholds_override(tmp_path):
    p = tmp_path / "q.json"
    p.write_text('{"motion_qc": {"fail_mean": 0.8, "keyframe_warn": "x", "still_diff": true}}', encoding="utf-8")
    th = MQ.thresholds(p)
    assert th["fail_mean"] == 0.8 and th["keyframe_warn"] == MQ.DEFAULTS["keyframe_warn"] \
        and th["still_diff"] == MQ.DEFAULTS["still_diff"]


def test_last_frame_mode_and_alignment():
    prompt = HV.realign("How the reference pictures align with the target video — x\n\nintegrated_multimodal_description: 原文",
                        192)
    one = HV.align_first_only(prompt)
    assert one.split("\n")[0] == HV.I2V_ALIGN_LINE and one.split("\n", 1)[1] == prompt.split("\n", 1)[1]
    assert HV.align_first_only("自由文本\n第二行") == "自由文本\n第二行"
    assert HV.use_last_frame("use", {"warn": True}) is True
    assert HV.use_last_frame(None, {"warn": True}) is True
    assert HV.use_last_frame("none", {"warn": False}) is False
    assert HV.use_last_frame("auto", {"warn": True}) is False
    assert HV.use_last_frame("auto", {"warn": False}) is True
    with pytest.raises(ValueError):
        HV.use_last_frame("maybe", None)


def test_h3_graph_without_last_frame():
    wf = HV.build("p", "first.png", None, 158, 1, "x")
    assert "201" not in wf and "last_frame" not in wf["131"]["inputs"]
    wf2 = HV.build("p", "first.png", "last.png", 158, 1, "x")
    assert wf2["201"]["inputs"]["image"] == "last.png"


# ---------------------------------------------------------------- 整集出片

class QcHooks(FakeHooks):
    """视频出完带 qc.motion；static_shots 里的镜头出的视频 verdict = fail"""

    def __init__(self, static_shots=(), **kw):
        super().__init__(**kw)
        self.static = set(static_shots)
        self.submit_kw = []

    def submit(self, shot_id, stage, step, gpu, parent=None, **kw):
        self.submit_kw.append(kw)
        return super().submit(shot_id, stage, step, gpu, parent)

    def finish(self, jid):
        super().finish(jid)
        j = self.jobs[jid]
        if j["stage"] == "video":
            t = self.data[j["shot"]]["takes"][-1]
            t["qc"] = {"motion": {"verdict": "fail" if j["shot"] in self.static else "pass",
                                  "labels": ["静止·不合格"] if j["shot"] in self.static else []}}


@pytest.fixture
def mkq(tmp_path):
    def make(**kw):
        h = QcHooks(**kw)
        pr = EPR.Producer(hooks=h, root=tmp_path / "episodes")
        pr.ensure_thread = lambda: None
        return h, pr
    return make


def test_auto_lock_skips_static_video(mkq):
    h, pr = mkq(static_shots=("ep09-S2",))
    pr.start(9, stages=["first", "last", "video"], mode="auto_lock", last_frame_mode="auto")
    run_until_idle(h, pr)
    locked_videos = {(s, n) for s, st, n, by in h.locks if st == "video"}
    assert ("ep09-S1", 1) in locked_videos and not any(s == "ep09-S2" for s, _ in locked_videos)
    v = pr.view(9)
    row = next(r for r in v["shots"] if r["shot_id"] == "ep09-S2")["stages"]["video"]
    assert row["state"] == "failed" and "静止·不合格" in row["qc_fail"] and "需重出" in row["reason"]
    assert any(f["shot_id"] == "ep09-S2" for f in v["failures"])
    assert v["last_frame_mode"] == "auto"
    assert {"last_frame_mode": "auto"} in h.submit_kw and all(
        k == {} or k == {"last_frame_mode": "auto"} for k in h.submit_kw)
    assert sum(1 for o in h.order if o[0] == "ep09-S2" and o[1] == "video") == 1     # 本次出的不合格不再自动重出


def test_auto_lock_rerenders_old_static_video_once(mkq):
    h, pr = mkq(static_shots=("ep09-S1",), shots=("ep09-S1",))
    h.data["ep09-S1"] = {"takes": [{"stage": "image", "n": 1}, {"stage": "last", "n": 1},
                                   {"stage": "video", "n": 1, "qc": {"motion": {"verdict": "fail", "labels": ["静止·不合格"]}}}],
                         "active": {"image": 1, "last": 1, "video": 1}, "locked": {"image": 1, "last": 1}}
    h.fresh_map["ep09-S1"] = {"image": True, "last": True, "video": True}
    pr.start(9, stages=["video"], mode="auto_lock")
    run_until_idle(h, pr)
    assert [o[1] for o in h.order] == ["video"]                  # 旧的不合格视频 → 重出一次
    row = pr.view(9)["shots"][0]["stages"]["video"]
    assert row["state"] == "failed" and row["qc_fail"]           # 新的仍不合格 → 不定稿、不再重出


def test_review_mode_only_flags(mkq):
    h, pr = mkq(shots=("ep09-S1",))
    h.data["ep09-S1"] = {"takes": [{"stage": "video", "n": 1, "qc": {"motion": {"verdict": "fail", "labels": ["静止·不合格"]}}}],
                         "active": {"video": 1}, "locked": {"image": 1, "last": 1}}
    h.fresh_map["ep09-S1"] = {"image": True, "last": True, "video": True}
    pr.start(9, stages=["video"], mode="review")
    run_until_idle(h, pr)
    assert h.order == []
    row = pr.view(9)["shots"][0]["stages"]["video"]
    assert row["state"] == "skipped" and row["qc_fail"]


def test_owner_passed_video_not_flagged(mkq):
    h, pr = mkq(shots=("ep09-S1",))
    h.data["ep09-S1"] = {"takes": [{"stage": "video", "n": 1, "qc": {"motion": {"verdict": "fail", "labels": ["静止·不合格"]}}}],
                         "active": {"video": 1}, "locked": {"image": 1, "last": 1}}
    h.fresh_map["ep09-S1"] = {"image": True, "last": True, "video": True, "video_passed": True}
    pr.start(9, stages=["video"], mode="auto_lock")
    run_until_idle(h, pr)
    assert h.order == [] and pr.view(9)["shots"][0]["stages"]["video"]["qc_fail"] is None


def test_produce_rejects_bad_last_frame_mode(mkq):
    from fastapi import HTTPException
    h, pr = mkq()
    with pytest.raises(HTTPException):
        pr.start(9, stages=["video"], mode="auto_lock", last_frame_mode="maybe")


# ---------------------------------------------------------------- 合成器

def test_assembler_warning():
    from ns_post import assemble as AS
    src = {"kind": "video", "path": None, "motion_qc": {"verdict": "fail", "labels": ["静止·不合格", "结尾定住 6.5s"]}}
    w = AS.motion_qc_warning(7, src)
    assert w.startswith("S7: 运动质检不合格") and "结尾定住 6.5s" in w
    assert AS.motion_qc_warning(1, {"kind": "video", "motion_qc": {"verdict": "pass"}}) is None
    assert AS.motion_qc_warning(1, {"kind": "still", "motion_qc": {"verdict": "fail"}}) is None
    assert AS.motion_qc_warning(1, {"kind": "video"}) is None


# ---------------------------------------------------------------- video-jobs 出片前提示

def test_video_job_precheck_warns_not_blocks(env, monkeypatch):   # noqa: F811  W2 夹具：假 ComfyUI、临时 data
    from ns_api import jobs as J
    from ns_api import video_jobs as VJ
    monkeypatch.setattr(VJ.FE, "frames_ready", lambda shot_id: (True, ""))
    monkeypatch.setattr(VJ.HV, "locked_frames", lambda shot_id: {"first": {"n": 1, "file": "a.png"},
                                                                 "last": {"n": 1, "file": "b.png"}})
    near = {"first_last_diff": 4.8, "threshold": 10.0, "warn": True, "message": "尾帧和首帧几乎一样（平均差 4.8），视频大概率不动"}
    monkeypatch.setattr(VJ.HV, "keyframe_precheck", lambda fr: near)
    got = []
    monkeypatch.setattr(J, "submit", lambda kind, shot_id, gpu, run, params=None, eta_s=None, **m:
                        got.append(params) or {"job_id": "j1", "eta_s": eta_s})
    c, _, _ = env
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_turbo", "gpu": 3})
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == [near["message"]] and r.json()["keyframe_check"]["warn"]
    assert got[-1]["last_frame_mode"] == "use" and got[-1]["last_frame_used"] is True
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_turbo", "gpu": 3, "last_frame_mode": "auto"})
    assert r.status_code == 200 and r.json()["warnings"] == [] and got[-1]["last_frame_used"] is False
    assert c.post(f"/api/shots/{SHOT}/video-jobs", json={"gpu": 3, "last_frame_mode": "x"}).status_code == 422
