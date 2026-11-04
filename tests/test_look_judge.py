"""tools/pipeline/look_judge.py：拼图尺寸 / 标记、双向一致逻辑（打桩看图模型）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/pipeline"))
sp = importlib.util.spec_from_file_location("look_judge_t", ROOT / "tools/pipeline/look_judge.py")
LJ = importlib.util.module_from_spec(sp)
sp.loader.exec_module(LJ)


def _img(tmp_path, name, w, h, v):
    p = tmp_path / name
    Image.new("RGB", (w, h), (v, v, v)).save(p)
    return p


def test_stitch_size_and_marks(tmp_path):
    a, b = _img(tmp_path, "a.png", 400, 200, 20), _img(tmp_path, "b.png", 200, 200, 200)
    s = LJ.stitch(a, b, height=100, bar=16)
    assert s.size == (200 + 16 + 100, 100)
    assert s.getpixel((200 + 8, 50)) == (128, 128, 128)        # 中间灰条
    assert s.getpixel((12, 12)) == (255, 255, 255)             # 左标白底
    assert s.getpixel((200 + 16 + 12, 12)) == (255, 255, 255)  # 右标白底


def test_parse_and_combine():
    assert LJ.parse_side("左\n因为……右边太亮") == "left"
    assert LJ.parse_side("右") == "right"
    assert LJ.parse_side("一样\n左右差不多") == "tie"
    assert LJ.parse_side("无法判断") is None
    assert LJ.combine("left", "right") == "a"
    assert LJ.combine("right", "left") == "b"
    assert LJ.combine("right", "right") == "uncertain"    # 位置偏置：永远选右
    assert LJ.combine("left", "left") == "uncertain"
    assert LJ.combine("tie", "tie") == "tie"
    assert LJ.combine(None, "left") == "uncertain"
    assert LJ.majority(["a", "a", "b"]) == "a"
    assert LJ.majority(["a", "b", "uncertain"]) == "uncertain"


def test_compare_with_stub(tmp_path):
    a, b = _img(tmp_path, "a.png", 100, 100, 20), _img(tmp_path, "b.png", 100, 100, 200)
    assert LJ.compare(a, b, ask=lambda req: {"text": "右\n理由"})["winner"] == "uncertain"
    calls = []

    def ask(req):      # 恒选 a：先 a 在左，再 a 在右
        calls.append(1)
        return {"text": "左" if len(calls) % 2 == 1 else "右"}
    r = LJ.compare(a, b, ask=ask)
    assert r["winner"] == "a" and len(r["raw"]) == 2
    calls.clear()
    assert LJ.compare(a, b, mode="triple", ask=ask)["winner"] == "a" and len(calls) == 6


def test_deterministic_darker_bg_wins(tmp_path):
    a, b = _img(tmp_path, "a.png", 100, 100, 30), _img(tmp_path, "b.png", 100, 100, 200)
    assert LJ.deterministic(a, b)["winner"] == "a"
