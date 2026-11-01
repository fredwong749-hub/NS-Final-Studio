"""fredw-92/F4：真浏览器端到端测出的三个后端问题。
1) 画布新出的版本（指令改图 / 由定稿首帧做的尾帧 / H3 视频）刚出来就被标「过期」→ 刚出 stale/stale_global 都为空；
   剧本真改了照样过期。
2) /api/render-backend 与 /api/render/endpoints 共用探测（见 test_render_backend_offline.py）。
3) 任务预计耗时按最近同类同卡完成任务的中位数，没有历史：视频 840 s、出图 70 s。"""
import json
import time

import pytest

from ns_api import app as app_mod
from ns_api import jobs as J
from ns_render import frame_edit as FE
from ns_render import pipeline as P

from test_frame_jobs_w2 import SHOT, _job, env  # noqa: F401  复用 W2 夹具（假 ComfyUI、临时 data）


def _stale(c, stage, n):
    shot = c.get(f"/api/shots/{SHOT}").json()
    t = next(t for t in shot["takes"]["takes"] if t["stage"] == stage and t["n"] == n)
    return t["stale"], t["stale_global"], shot


def test_fresh_canvas_takes_not_stale_and_script_change_still_stales(env, monkeypatch):
    c, data, clients = env
    t1 = _job(c, {"stage": "first", "mode": "regen", "seed": 7})["take"]
    assert _stale(c, "image", t1["n"])[:2] == ([], [])
    # 指令改图：prompt 是项目方原话，基准沿修改链取父版本的编译提示词
    j2 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "保持构图，提高画面清晰度", "strength": "small"})
    t2 = j2["take"]
    assert t2["prompt"] == "保持构图，提高画面清晰度" and t2["basis_prompt"] == t1["prompt"]
    assert t2["look_hash"] and t2["inputs_sha"] == t1["inputs_sha"]
    st, sg, shot = _stale(c, "image", t2["n"])
    assert (st, sg) == ([], []) and shot["summary"]["stale"]["image"] == [] and shot["summary"]["stale_global"]["image"] == []
    # 指令改图链上再改一次：仍沿链取最早整张出图的基准
    t3 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "再亮一点"})["take"]
    assert t3["basis_prompt"] == t1["prompt"] and _stale(c, "image", t3["n"])[:2] == ([], [])
    # G3（项目方 11-01，PRODUCER）：契约没有结果（测试里 postflight 默认 ok=None）的编辑版本不设为当前
    assert P.load_takes(SHOT)["active"]["image"] not in (t2["n"], t3["n"])
    # 定稿 v2 → 由定稿首帧做尾帧（渲染时在第一句后插了身份底板说明）→ 不过期
    assert c.post(f"/api/shots/{SHOT}/takes/first/{t2['n']}/lock").status_code == 200
    l1 = _job(c, {"stage": "last", "mode": "regen"})["take"]
    assert l1["from_first"] == t2["n"] and l1["look_hash"]
    st, sg, shot = _stale(c, "last", l1["n"])
    assert (st, sg) == ([], []) and shot["summary"]["stale"]["last"] == [] and shot["summary"]["stale_global"]["last"] == []
    # 尾帧上指令改图 → 也不过期
    l2 = _job(c, {"stage": "last", "mode": "instruct", "instruction": "表情更慌乱"})["take"]
    assert _stale(c, "last", l2["n"])[:2] == ([], [])
    # 定稿后又在首帧上改了一版（当前 ≠ 定稿）：尾帧由定稿首帧得到 → 不算「首帧已换」
    # G3：t4 过了契约，但 v2 是项目方定稿 → 不被自动挤掉，当前仍是 v2；尾帧由定稿首帧得到 → 不算「首帧已换」
    from ns_render import unified_frame as UF
    monkeypatch.setattr(UF, "_postflight", lambda final_rel, job, host: {"ok": True, "items": [], "blocking": []})
    t4 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "换个角度", "parent": t2["n"]})["take"]
    t4d = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "image" and t["n"] == t4["n"])
    assert (t4d.get("contract") or {}).get("postflight", {}).get("ok") is True          # 编辑链的契约真的跑了
    assert P.load_takes(SHOT)["active"]["image"] == t2["n"] and _stale(c, "last", l2["n"])[0] == []
    # 换定稿首帧 → 尾帧过期（本镜原因）
    c.post(f"/api/shots/{SHOT}/takes/first/{t4['n']}/lock")
    assert "首帧已换" in _stale(c, "last", l2["n"])[0]
    c.post(f"/api/shots/{SHOT}/takes/first/{t2['n']}/lock")

    # 剧本真改了 → 首帧（含改图版本）过期「剧本已改」；尾帧按出图时的本镜输入哈希判为本镜原因
    _ep, s = P.find_shot(app_mod._script, SHOT)
    monkeypatch.setattr(s, "img_prompt", "全新的剧本画面：雨夜天台上她独自撑伞远眺城市灯火")
    monkeypatch.setattr(s, "motion_prompt", "全新的剧本动作：她转身走下天台楼梯，伞面滴水")
    from ns_agent import state_timeline as ST
    monkeypatch.setattr(ST, "shot_inputs_sha", lambda shot_id, root=None: "changed-inputs")
    for n in (t1["n"], t2["n"], t3["n"]):
        assert "剧本已改" in _stale(c, "image", n)[0], n
    for n in (l1["n"], l2["n"]):
        assert "本镜输入已改" in _stale(c, "last", n)[0], n
    # G3 正向：解除定稿后，过了契约的编辑版本自动成为当前；契约不过的不设
    c.post(f"/api/shots/{SHOT}/takes/first/{t2['n']}/unlock")
    t5 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "再暖一点", "parent": t2["n"]})["take"]
    assert P.load_takes(SHOT)["active"]["image"] == t5["n"]
    monkeypatch.setattr(UF, "_postflight", lambda final_rel, job, host: {"ok": False, "items": [], "blocking": ["Q1"]})
    t6 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "再冷一点", "parent": t2["n"]})["take"]
    assert P.load_takes(SHOT)["active"]["image"] == t5["n"] != t6["n"]


def test_upload_parent_has_no_basis():
    data = {"takes": [{"stage": "image", "n": 1, "workflow": "upload", "prompt": "", "source": "upload"},
                      {"stage": "image", "n": 2, "mode": "instruct", "parent": 1, "prompt": "原话"},
                      {"stage": "image", "n": 3, "mode": "regen", "prompt": "编译提示词"},
                      {"stage": "image", "n": 4, "mode": "refs", "parent": 3, "prompt": "原话2"}]}
    assert FE.chain_basis(data, data["takes"][1]) == ""
    assert FE.chain_basis(data, data["takes"][3]) == "编译提示词"


def test_strip_last_plate_line():
    plate = P.LAST_ROLE_PLATE.format(i=2, name="林晚")
    target = "lnwan_qi，图1是本镜头的首帧画面。保持图1的场景不变，林晚仰头"
    rendered = P._last_prompt_with_plate(target, plate)
    assert rendered != target and app_mod._strip_plate(rendered) == target


# ------------------------------------------------------------------ 3) 预计耗时

def _write_job(d, jid, kind, gpu, wall, state="done", finished="2026-10-31T00:00:00"):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{jid}.json").write_text(json.dumps({"id": jid, "kind": kind, "gpu": gpu, "state": state, "wall_s": wall,
                                               "finished_at": finished, "created_at": finished}), encoding="utf-8")


def test_eta_median_of_recent_same_kind_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(J, "_jobs", {})
    assert J.estimate("video", 3) == 840.0 and J.estimate("frame", 0) == 70.0
    d = J.jobs_dir()
    for i, w in enumerate([755.7, 826.7, 900.0, 0.0]):           # 0.0：假客户端样本不算
        _write_job(d, f"v{i}", "video", 3, w, finished=f"2026-10-31T00:0{i}:00")
    _write_job(d, "vf", "video", 3, 60.0, state="failed")
    _write_job(d, "v0g", "video", 0, 10.0)                        # 别的卡
    _write_job(d, "f1", "frame", 3, 60.1)
    assert J.recent_durations("video", 3) == [900.0, 826.7, 755.7]
    assert J.estimate("video", 3) == 826.7
    assert J.estimate("frame", 3) == 60.1 and J.estimate("frame", 0) == 70.0
    # 只取最近 ETA_SAMPLES 个
    for i in range(J.ETA_SAMPLES):
        _write_job(d, f"n{i}", "video", 3, 100.0, finished=f"2026-10-31T01:0{i}:00")
    assert J.estimate("video", 3) == 100.0
    # 排在前面的任务 × 单个耗时
    monkeypatch.setattr(J, "_jobs", {"q": {"id": "q", "gpu": 3, "state": "running", "kind": "video"}})
    assert J.estimate("video", 3) == 200.0


def test_video_job_eta_uses_history(env, monkeypatch):
    """视频任务入队时 eta_s 走 jobs.estimate（不再是固定 330）"""
    from ns_api import video_jobs as VJ
    monkeypatch.setattr(J, "estimate", lambda kind, gpu, default=None: {"video": 777.0}.get(kind, 1.0))
    monkeypatch.setattr(VJ.FE, "frames_ready", lambda shot_id: (True, ""))
    monkeypatch.setattr(VJ.HV, "locked_frames", lambda shot_id: {"first": {"n": 1}, "last": {"n": 1}})
    started = []
    monkeypatch.setattr(J, "submit", lambda kind, shot_id, gpu, run, params=None, eta_s=None, **m:
                        started.append(eta_s) or {"eta_s": eta_s})
    c, data, clients = env
    # base 写明：本测只管 eta；默认基底（2026-11-01 起 pika_flex）要求道上有 LoRA，这里的假道没有 LoRA 列表
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_base"})
    assert r.status_code == 200, r.text
    assert started == [777.0] and r.json()["eta_s"] == 777.0
    time.sleep(0)
