"""UIUX-LOOP-2 第 7 轮（11-06）：出图页 / 视频页与活登记表打架。
① 出图页 / 视频页只列有 takes.json 目录的镜：ep02 登记 16 镜、只有 8 镜出过图 → 页面只见 8 镜，排队中的镜根本不显示
   → 镜的集合 = 目录 ∪ 登记表；没图的格子写登记表状态（排队 / 正在出 / 等上一步），不写“还没出图”。
② 视频页：登记表说 S3 视频尽力版 / S4 已定下，但本机 takes.json 没 active.video → 原来显示“未出”；现在给登记表指的那版
   （没写 take 号就给最新一版通过后检且片子在本机的，并写明），尽力版单独一态 best_effort（“待你看”筛选含它）。
③ 首尾帧还在排队的镜，视频页不写“缺首尾帧 · 去出图”（那是要项目方动手的卡住），写“等首尾帧（排队等空闲的卡）”。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

RUN = "series10_v2"


def _take(n, stage, ok=True, f=None):
    return {"n": n, "stage": stage, "file": f or f"renders/{RUN}/ep01/S1/takes/{stage}_{n:03d}.png", "created_at": "2026-11-06T15:00:00",
            "postflight": {"ok": ok, "items": [{"id": "Q1", "status": "pass" if ok else "fail"}]}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ns_api import frames_index as FI
    from ns_api import shot_status as SS
    from ns_api import video_index as VI
    from ns_render import pipeline as P
    data = tmp_path / "data"
    renders = data / "renders" / RUN
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", renders)
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {})
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {})
    monkeypatch.setattr(FI, "_edits_by_cell", lambda: {})
    monkeypatch.setattr(VI, "_video_jobs", lambda: [])
    monkeypatch.setattr(VI, "_median_s", lambda: 600.0)
    monkeypatch.setattr(SS, "_reviewed", lambda sid, t: None)
    reg = tmp_path / "registry.json"
    monkeypatch.setattr(SS, "REGISTRY", reg)
    SS._reg.update(mt=None, val={})

    def write_reg(shots: dict[str, dict]):
        eps: dict[int, list] = {}
        for sid, objs in shots.items():
            ep = int(sid[2:4])
            eps.setdefault(ep, []).append({"shot": sid, "index": int(sid.split("-S")[1]), "objects": objs})
        reg.write_text(json.dumps({"run": RUN, "episodes": [{"ep": e, "shots": v} for e, v in sorted(eps.items())]}), encoding="utf-8")
        SS._reg.update(mt=None, val={})

    def write_takes(sid: str, takes: dict):
        ep, s = sid.split("-S")
        d = renders / ep / f"S{s}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "takes.json").write_text(json.dumps(takes), encoding="utf-8")
        for t in takes.get("takes") or []:
            f = data / t["file"]
            f.parent.mkdir(parents=True, exist_ok=True)
            if not t.get("_absent"):
                f.write_bytes(b"x")
        return d
    return {"write_reg": write_reg, "write_takes": write_takes, "data": data}


def test_frames_index_lists_ledger_shots_without_takes_dir(env):
    from ns_api import frames_index as FI
    env["write_reg"]({
        "ep02-S1": {"first": {"status": "ready"}, "last": {"status": "pending"}, "video": {"status": "pending"}},
        "ep02-S2": {"first": {"status": "running"}, "last": {"status": "pending"}, "video": {"status": "pending"}},
        "ep02-S3": {"first": {"status": "failed", "last_error": "没出来"}, "last": {"status": "pending"}, "video": {"status": "pending"}},
    })
    env["write_takes"]("ep02-S3", {"active": {}, "takes": []})      # 只有 S3 有目录
    d = FI.build(2)
    shots = {s["id"]: s for e in d["episodes"] for s in e["shots"]}
    assert list(shots) == ["ep02-S1", "ep02-S2", "ep02-S3"] and d["counts"]["shots"] == 3
    assert shots["ep02-S1"]["first"]["state"] == "none" and shots["ep02-S1"]["first"]["ledger"]["word"] == "排队等空闲的卡"
    assert shots["ep02-S1"]["last"]["ledger"]["word"] == "等上一步"
    assert shots["ep02-S2"]["first"]["ledger"]["word"] == "正在出" and shots["ep02-S2"]["main"]["kind"] == "busy"
    assert shots["ep02-S3"]["first"]["ledger"]["state"] == "failed" and "没出来" in shots["ep02-S3"]["first"]["ledger"]["word"]
    # 有当前图的格子不挂 ledger（页面只在没图时写登记表状态）
    env["write_takes"]("ep02-S1", {"active": {"image": 1}, "takes": [_take(1, "image", f=f"renders/{RUN}/ep02/S1/takes/image_001.png")]})
    d = FI.build(2)
    s1 = next(s for e in d["episodes"] for s in e["shots"] if s["id"] == "ep02-S1")
    assert s1["first"]["state"] == "current" and s1["first"]["ledger"] is None


def test_videos_overview_ledger_best_effort_and_passed_without_active(env):
    from ns_api import video_index as VI
    env["write_reg"]({
        "ep01-S3": {"first": {"status": "passed", "take": 8}, "last": {"status": "passed", "take": 9},
                    "video": {"status": "best_effort", "take": None, "reason": "试了 4 次没全过，取罚分最小的一版"}},
        "ep01-S4": {"first": {"status": "passed", "take": 25}, "last": {"status": "passed", "take": 3},
                    "video": {"status": "passed", "take": 1, "reason": "v1 过审片打分"}},
        "ep01-S5": {"first": {"status": "passed", "take": 1}, "last": {"status": "passed", "take": 1},
                    "video": {"status": "passed", "take": 2, "reason": "过审片打分"}},
        "ep02-S1": {"first": {"status": "ready"}, "last": {"status": "pending"}, "video": {"status": "pending"}},
    })
    vf = lambda sid, n: f"renders/{RUN}/{sid.replace('-S', '/S')}/takes/video_{n:03d}.mp4"  # noqa: E731
    env["write_takes"]("ep01-S3", {"active": {"image": 8, "last": 9}, "takes": [
        _take(8, "image", f=f"renders/{RUN}/ep01/S3/takes/image_008.png"), _take(9, "last", f=f"renders/{RUN}/ep01/S3/takes/last_009.png"),
        _take(4, "video", f=vf("ep01-S3", 4)), _take(5, "video", ok=False, f=vf("ep01-S3", 5)), {**_take(6, "video", f=vf("ep01-S3", 6)), "_absent": True}]})
    env["write_takes"]("ep01-S4", {"active": {"image": 25, "last": 3}, "takes": [
        _take(25, "image", f=f"renders/{RUN}/ep01/S4/takes/image_025.png"), _take(3, "last", f=f"renders/{RUN}/ep01/S4/takes/last_003.png"),
        _take(1, "video", f=vf("ep01-S4", 1)), {**_take(2, "video", f=vf("ep01-S4", 2)), "_absent": True}]})
    env["write_takes"]("ep01-S5", {"active": {"image": 1, "last": 1}, "takes": [
        _take(1, "image", f=f"renders/{RUN}/ep01/S5/takes/image_001.png"), _take(1, "last", f=f"renders/{RUN}/ep01/S5/takes/last_001.png"),
        {**_take(2, "video", f=vf("ep01-S5", 2)), "_absent": True}]})
    d = VI.build()
    st = {s["id"]: s for e in d["episodes"] for s in e["shots"]}
    # S3：尽力版，登记表没写哪一版 → 最新一版通过后检且片子在本机的 v4（v6 没拉到本机、v5 没过），并写明
    assert st["ep01-S3"]["state"] == "best_effort" and st["ep01-S3"]["n"] == 4 and st["ep01-S3"]["video_url"].endswith("video_004.mp4")
    assert "v4" in st["ep01-S3"]["ledger"]["note"] and st["ep01-S3"]["ledger"]["word"] == "尽力版"
    # S4：登记表已定下 v1 → 待你看，给 v1
    assert st["ep01-S4"]["state"] == "pending_review" and st["ep01-S4"]["n"] == 1 and st["ep01-S4"]["ledger"]["note"] is None
    # S5：登记表定下 v2 但片子没拉到本机 → 待你看、没地址、写明
    assert st["ep01-S5"]["state"] == "pending_review" and st["ep01-S5"]["video_url"] is None and st["ep01-S5"]["ledger"]["note"] == "片子还没拉到本机"
    # ep02-S1：没目录也列出来；首帧在排队 → 不是“缺首尾帧 · 去出图”，是“等首尾帧”
    assert st["ep02-S1"]["state"] == "todo" and st["ep02-S1"]["ledger"]["word"].startswith("等首尾帧") and st["ep02-S1"]["missing"] == ["first", "last"]
    assert d["summary"]["best_effort"] == 1 and d["summary"]["pending_review"] == 2 and d["summary"]["todo"] == 1 and d["summary"]["need_frames"] == 0
    # “待你看”筛选含尽力版
    ids = [s["id"] for e in VI.build(state="pending_review")["episodes"] for s in e["shots"]]
    assert ids == ["ep01-S3", "ep01-S4", "ep01-S5"]


def test_videos_page_words_for_best_effort_and_ledger():
    root = Path(__file__).resolve().parents[1]
    vp = (root / "apps/web/src/v3/pages/VideosPage.tsx").read_text(encoding="utf-8")
    assert "尽力版 · 待你看" in vp and 'r.state === "todo" && r.ledger?.word' in vp and 's.state === "best_effort"' in vp
    sw = (root / "apps/web/src/v3/shotWord.ts").read_text(encoding="utf-8")
    assert 'best_effort: "review"' in sw
    fp = (root / "apps/web/src/v3/pages/FramesPage.tsx").read_text(encoding="utf-8")
    assert "led ? led.word" in fp and "ledger?: Ledger | null" in fp
