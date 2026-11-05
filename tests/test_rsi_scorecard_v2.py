"""RSI 尺子 v2（L-189）：版本号 / 画面指数 / 项目方封顶 / 视频线 stale"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.imglab import picture_index as PI  # noqa: E402
from tools.sentinel import scorecard as SC  # noqa: E402


def test_owner_cap_and_combine():
    s, info = PI.combine(89.0, 90.0, {"verdict": "不合格", "at": "x"})
    assert s == 60.0 and "capped_by" in info
    s2, _ = PI.combine(89.0, 90.0, {"verdict": "合格"})
    assert s2 == round(0.35 * 89 + 0.65 * 90, 1)
    assert PI.combine(80.0, None, None)[0] == 80.0


def test_lineup_and_blank_bg(tmp_path):
    cv2 = pytest.importorskip("cv2")
    h, w = 640, 480
    white = np.full((h, w, 3), 245, np.uint8)
    p = tmp_path / "w.png"
    cv2.imwrite(str(p), white)
    line = [{"bbox": [60 + i * 150, 300, 140 + i * 150, 400], "h_ratio": 100 / h} for i in range(3)]
    m = PI.measure(p, line, 3)
    assert m["parts"]["lineup"] < 0.2          # 一排同大小
    assert m["parts"]["bg"] < 0.2              # 空白亮背景
    depth = [{"bbox": [60, 200, 160, 340], "h_ratio": 140 / h}, {"bbox": [300, 330, 360, 400], "h_ratio": 70 / h}]
    assert PI.measure(p, depth, 3)["parts"]["lineup"] > m["parts"]["lineup"]


def test_current_sv_not_stale_file():
    sv = SC.current_sv()
    stale = (SC.jl("data/system_version.txt") or {}).get("id")
    assert sv and sv >= (stale or "")


def test_stale_video_not_null(monkeypatch, tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({"line": "video", "score": 72.5, "at": "2026-11-02T20:00:00", "parts": {"cam": 46.4}, "sv": "sv-x"}) + "\n"
                 + json.dumps({"line": "video", "score": 72.5, "at": "2026-11-05T00:00:00", "evidence": {"stale": True}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(SC, "SCORES", f)
    r = SC.stale_video("run", "S1")
    assert r["score"] == 72.5 and r["evidence"]["stale"] and r["evidence"]["scored_at"] == "2026-11-02T20:00:00"
    f.write_text("", encoding="utf-8")
    assert SC.stale_video("run", "S1")["score"] is None


def test_sanity_set_t35_above_t8():
    d = ROOT / "data/ab/adherence_img"
    if not (d / "scores.json").exists():
        pytest.skip("无 A/B 数据")
    sc = json.loads((d / "scores.json").read_text(encoding="utf-8"))
    res = json.loads((d / "results.json").read_text(encoding="utf-8"))
    acc = {"t8": [], "t35": []}
    for x in res:
        t = {"postflight": sc[x["file"]]["postflight"]}
        acc[x["t"]].append(PI.measure(ROOT / "data" / x["file"], PI.faces_from_take(t) or None, PI.band_from_take(t))["index"])
    assert np.mean(acc["t35"]) > np.mean(acc["t8"])
