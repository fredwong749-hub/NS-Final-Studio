"""tools/master/episode_timeline.py 解析器 / 分类 / 关键路径单测（小样例日志）。"""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("episode_timeline", ROOT / "tools/master/episode_timeline.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

PROD = [
    {"ts": "2026-11-04T18:00:00", "ev": "dispatch", "obj": "first:ep01-S1", "lane": "gpu33:0", "attempt": 1},
    {"ts": "2026-11-04T18:01:00", "ev": "rendered", "obj": "first:ep01-S1", "lane": "gpu33:0", "take": 1, "render_s": 50.0},
    {"ts": "2026-11-04T18:04:00", "ev": "content_fail", "obj": "first:ep01-S1", "attempt": 1, "contract_s": 170.0},
    {"ts": "2026-11-04T18:04:10", "ev": "dispatch", "obj": "first:ep01-S1", "lane": "gpu33:0", "attempt": 2},
    {"ts": "2026-11-04T18:05:00", "ev": "rendered", "obj": "first:ep01-S1", "lane": "gpu33:0", "take": 2, "render_s": 40.0},
    {"ts": "2026-11-04T18:07:00", "ev": "passed", "obj": "first:ep01-S1", "attempt": 2, "contract_s": 120.0},
    {"ts": "2026-11-04T18:00:00", "ev": "adult_wait_owner", "obj": "first:ep03-S1"},
]


def test_producer_segments_and_episode_filter():
    r = T.parse_producer(PROD, 1)
    st = [(s["stage"], s.get("attempt")) for s in r["segs"]]
    assert ("首帧出图", 1) in st and ("首帧检测", 1) in st and ("首帧出图", 2) in st
    det = [s for s in r["segs"] if s["stage"] == "首帧检测"]
    assert [round(T.secs(s["start"], s["end"])) for s in det] == [180, 120]
    assert all("ep03" not in e["obj"] for e in r["events"])
    wait2 = [s for s in r["segs"] if s["stage"] == "首帧等待" and s["attempt"] == 2][0]
    assert wait2["start"] == datetime(2026, 11, 4, 18, 4, 0)  # 上次判定 -> 下次派单


def test_video_log_date_rollover():
    lines = ["23:50:00 SUBMIT ep01-S2 v1 i2va_pika_flex 1 gpu36:0 abc",
             "00:01:00 DONE ep01-S2 v1 gpu36:0 660.0s",
             "00:02:00 SCORE ep01-S2 v1 PASS mean 1.0"]
    j = T.parse_video(lines, "2026-11-04")[("ep01-S2", "v1")]
    assert j["submit"] == datetime(2026, 11, 4, 23, 50) and j["done"] == datetime(2026, 11, 5, 0, 1)
    assert j["gen_s"] == 660.0 and j["verdict"] == "PASS"


def test_night_and_route_parse():
    n = T.parse_night(["11-04 22:32:52 REOPEN ep01 x", "garbage"], "2026-11-04")
    assert len(n) == 1 and n[0]["ev"] == "REOPEN"
    r = T.parse_route([{"at": "2026-11-04T01:00:10", "route": "lan", "ms": 10000, "kind": "image"},
                       {"at": "2026-11-04T01:00:10", "route": "lan", "ms": 100, "kind": "ask"}])
    assert len(r) == 1 and T.secs(r[0][0], r[0][1]) == 10


def test_classify_code_error_and_critical_path():
    t0, t1 = datetime(2026, 11, 4, 18, 0), datetime(2026, 11, 4, 19, 0)
    prod = T.parse_producer(PROD, 1)
    night = T.parse_night(["11-04 08:04:52 assemble ep01 1  boom", "11-04 18:30:00 REOPEN ep01 x"], "2026-11-04")
    sl = T.classify((t0, t1), prod["segs"], [], prod["events"], night, [])
    tot = sl["totals"]
    assert tot["计算"] == 90 + 2 or tot["计算"] in range(88, 95)
    assert tot["代码错误"] > 1500  # 18:07 之后到 18:30 REOPEN
    cp = T.critical_path(prod["segs"], t0, sl)
    assert cp[-1]["stage"] == "首帧检测" and any(s["stage"] == "首帧出图" for s in cp)
