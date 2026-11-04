"""tools/pipeline/look_metrics.py：合成图验证确定性指标。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("look_metrics_t", ROOT / "tools/pipeline/look_metrics.py")
LM = importlib.util.module_from_spec(sp)
sp.loader.exec_module(LM)


def _save(tmp_path, name, img):
    p = tmp_path / name
    assert cv2.imwrite(str(p), img)
    return p


def _textured(h=400, w=600, seed=1):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (h // 8, w // 8, 3), dtype=np.uint8)
    return cv2.resize(base, (w, h), interpolation=cv2.INTER_NEAREST)


def test_white_clip(tmp_path):
    m = LM.measure(_save(tmp_path, "w.png", np.full((200, 300, 3), 255, np.uint8)))
    assert m["clip_hi"] > 0.99 and m["clip_lo"] == 0


def test_black_clip(tmp_path):
    m = LM.measure(_save(tmp_path, "b.png", np.zeros((200, 300, 3), np.uint8)))
    assert m["clip_lo"] > 0.99


def test_dof_ratio(tmp_path):
    sharp = _textured()
    blur = cv2.GaussianBlur(sharp, (0, 0), 6)
    img = blur.copy()
    h, w = img.shape[:2]
    img[int(h * .3):int(h * .7), int(w * .3):int(w * .7)] = sharp[int(h * .3):int(h * .7), int(w * .3):int(w * .7)]
    assert LM.measure(_save(tmp_path, "d.png", img))["dof_ratio"] > 1.5
    assert LM.measure(_save(tmp_path, "flat.png", sharp))["dof_ratio"] < 1.5


def test_halo_grows_with_usm(tmp_path):
    img = np.full((300, 400, 3), 60, np.uint8)
    img[:, 200:] = 200
    img = cv2.GaussianBlur(img, (0, 0), 1.5)
    usm = cv2.addWeighted(img, 2.2, cv2.GaussianBlur(img, (0, 0), 3), -1.2, 0)
    a = LM.measure(_save(tmp_path, "a.png", img))["halo"]
    b = LM.measure(_save(tmp_path, "b2.png", usm))["halo"]
    assert b > a + 1.0
