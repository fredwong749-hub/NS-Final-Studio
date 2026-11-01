"""IMGGEN（2026-10-31 夜，GEN_CONTRACT I3/I9）：造型参考图工具。

- look_crops(char, look)：从该造型暂定设定图（registered_refs.json role=item）按“非白列分栏”裁出第二栏正面全身（full），
  以及上 58%（half，头顶到大腿中部；与 identity_refs ep02_outfit 同法），存 images/refs/<char>_look<X>_{full,half}.png
- look_of(char, prompt)：按 P1_looks 造型“服装=”里的单品词在本镜首帧提示词里出现的个数判本镜造型（只读文字，不改内容）
不做内容检测。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data/pipeline/runs/series10_v1"
REFS = RUN / "images/refs"
NAME2ID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}


def _registered():
    return json.loads((RUN / "assets/registered_refs.json").read_text(encoding="utf-8"))


def sheet_of(char: str, look: str) -> Path | None:
    for r in _registered():
        if r["asset"] == char and r.get("look") == look and r.get("role") == "item":
            return ROOT / r["src"]
    if char == "ch_a_lan":                                   # 阿岚 A 登记为 identity；B/C 用暂定设定图
        st = json.loads((RUN / "images/state.json").read_text(encoding="utf-8"))
        j = st["jobs"].get(f"sheet:ch_a_lan_look{look}")
        if j and j.get("chosen"):
            a = next(x for x in j["attempts"] if x["id"] == j["chosen"])
            return ROOT / a["file"]
    return None


def panels(im: Image.Image, thr: int = 235, min_w: int = 40) -> list[tuple[int, int]]:
    a = np.asarray(im.convert("L"))
    cols = (a < thr).any(axis=0)
    segs, start = [], None
    for x, v in enumerate(list(cols) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if x - start >= min_w:
                segs.append((start, x))
            start = None
    return segs


def look_crops(char: str, look: str) -> dict:
    out = {"full": REFS / f"{char}_look{look}_full.png", "half": REFS / f"{char}_look{look}_half.png"}
    if out["full"].exists() and out["half"].exists():
        return out
    src = sheet_of(char, look)
    if not src or not src.exists():
        return {}
    im = Image.open(src).convert("RGB")
    segs = panels(im)
    if len(segs) < 2:
        return {}
    x1, x2 = segs[1]
    x1, x2 = max(0, x1 - 24), min(im.width, x2 + 24)
    col = im.crop((x1, 0, x2, im.height))
    rows = np.where((np.asarray(col.convert("L")) < 235).any(axis=1))[0]
    y1, y2 = max(0, int(rows[0]) - 24), min(im.height, int(rows[-1]) + 24)
    full = col.crop((0, y1, col.width, y2))
    half = full.crop((0, 0, full.width, int(full.height * 0.58)))
    REFS.mkdir(parents=True, exist_ok=True)
    full.save(out["full"])
    half.save(out["half"])
    return out


def looks_table() -> dict:
    d = json.loads((RUN / "P1_looks.json").read_text(encoding="utf-8"))
    return {c["char_id"]: c["looks"] for c in d}


def look_of(char: str, prompt: str) -> str | None:
    looks = looks_table().get(char) or []
    best = (0, None)
    for lk in looks:
        wear = lk["zh"].split("｜")[0].replace("服装=", "")
        words = [w for w in re.split(r"[配与，、外罩]+", wear) if len(w) >= 2]
        n = sum(1 for w in words if w in prompt)
        if n > best[0]:
            best = (n, lk["id"])
    return best[1]


def look_for_shot(char: str, prompt: str, ep: int) -> str | None:
    """本镜造型：提示词里点了单品就按单品；没点 → 该集 P1 用途里列了的造型（只列一个就用它，多个取第一个）"""
    lk = look_of(char, prompt)
    if lk:
        return lk
    cands = [x["id"] for x in looks_table().get(char, []) if re.search(rf"ep0?{ep}\b|ep{ep:02d}", x.get("use", ""))]
    return cands[0] if cands else None


SIZE_FULL = ("中景", "中全景", "全身", "全景", "远景", "大远景")


def look_ref(char: str, look: str | None, size: str) -> Path | None:
    if not look:
        return None
    c = look_crops(char, look)
    return c.get("full" if size in SIZE_FULL else "half")


def look_ref_nohead(char: str, look: str | None, size: str) -> Path | None:
    """造型图去头版（只留服装 / 鞋 / 饰品）：设定图的脸本身偏娃娃感，避免把脸也带进来（imgfix v10 验证）"""
    src = look_ref(char, look, size)
    if not src:
        return None
    dst = src.with_name(src.stem + "_nohead.png")
    if not dst.exists():
        im = Image.open(src).convert("RGB")
        a = np.asarray(im.convert("L"))
        rows = np.where((a < 235).any(axis=1))[0]
        top = int(rows[0]) if len(rows) else 0
        fig_h = (im.height - top) if "full" in src.stem else (im.height - top) / 0.58
        cut = int(top + fig_h * 0.15)                    # 站姿全身约 7.5 头身：头 + 颈 ≈ 身高 15%
        im.crop((0, cut, im.width, im.height)).save(dst)
    return dst
