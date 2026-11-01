#!/usr/bin/env python3
"""BAKEOFF：输出是否“照抄了参考图 / 参考板”（总调度 11-01：#05 = krea2_ref 契约组把参考板拼图原样出成了首帧）。

做法（只看像素，不看内容）。实际起作用的是前两条，后两条在本轮从来没触发过：
  ① gutters：画面内部贯穿的近白分隔线（参考板的栅格）——本轮 4 张命中全靠它，加上 score_srv 的文字框 ≥5 / 同一人两次；
  ② score_srv 里的文字框数、重复人脸；
  ③ cell_hits：切格后格子≈某张参考（本轮 0 次命中）；
  ④ 整图 NCC ≥0.85（本轮被判拼图的 NCC 只有 0.13–0.31，这条线抓不到拼图，只防“整图原样抄一张参考”）。
seams（笔直断层）只记录不判：会把门框、柜格误报。参考库 = ComfyUI input/bakeoff/ 下的参考（不含编辑源图、imgfix、第 2 轮的第一段与掩码）。
定线与验证用的是同一批图（第 1 轮），置信度低，见 K-REV-B07。
score_srv.py 引用 ref_copy_score()；单独运行时打印分布，用来定线：
    /root/work/fredw/venv_idm/bin/python refcopy.py            # 在 srv/ 目录
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

INP = Path("/root/work/fredw/comfy/ComfyUI/input/bakeoff")
COPY_LINE = 0.85          # 整图 NCC 线：只防“整图原样抄一张参考”，本轮从没触发；0.60 会误伤（B4 qwen21 契约组对场景参考 0.72）


def _read(p):
    im = cv2.imread(str(p))
    if im is None:
        from PIL import Image
        im = cv2.cvtColor(np.array(Image.open(p).convert("RGB")), cv2.COLOR_RGB2BGR)
    return im


def feat(im):
    g = cv2.cvtColor(cv2.resize(im, (48, 84), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = (g - g.mean()) / (g.std() + 1e-6)
    return g.ravel() / np.sqrt(g.size)


_REF = {}


def ref_bank():
    if not _REF and INP.is_dir():
        for q in sorted(INP.iterdir()):
            # 只比“参考”：编辑源图（frames）、IMGGEN 参照（imgfix）、第 2 轮的第一段首帧和掩码（r2src / r2mask）都不是参考
            if "__images__frames__" in q.name or "__imgfix__" in q.name or q.name.startswith(("r2src__", "r2mask__")):
                continue
            try:
                _REF[q.name] = feat(_read(q))
            except Exception:  # noqa: BLE001
                pass
    return _REF


def gutters(img) -> int:
    """拼图检测：画面内部（离边 8% 以上）贯穿 ≥85% 宽 / 高、几乎纯色的分隔线条数（参考板的白色栅格）"""
    g = cv2.cvtColor(cv2.resize(img, (192, 336), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = g.shape
    n = 0
    for axis, L in ((1, H), (0, W)):          # axis=1：每一行沿宽方向；axis=0：每一列沿高方向
        sd = g.std(axis=axis)
        mn = g.mean(axis=axis)
        flat = (sd < 6) & (mn > 200)            # 近乎纯白的整行 / 整列
        lo, hi = int(L * 0.08), int(L * 0.92)
        run, k = 0, lo
        while k < hi:
            if flat[k]:
                run += 1
            elif run:
                n += 1
                run = 0
            k += 1
        n += 1 if run else 0
    return n


def seams(img, jump=25, frac=0.85) -> int:
    """拼图检测（补白线漏的：灰底 / 场景格）：画面内部贯穿 ≥85% 宽或高的笔直亮度断层条数（相邻两行 / 两列亮度差 >25 的像素占比）"""
    g = cv2.cvtColor(cv2.resize(img, (192, 336), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    n = 0
    for d in (np.abs(np.diff(g, axis=0)), np.abs(np.diff(g, axis=1)).T):     # 行间差（横向断层）、列间差（竖向断层）
        L = d.shape[0]
        hit = (d > jump).mean(axis=1) >= frac
        hit[: int(L * 0.08)] = False
        hit[int(L * 0.92):] = False
        n += int(np.sum(hit[1:] & ~hit[:-1]) + (1 if hit[0] else 0))
    return n


def cell_hits(img, thr=0.75) -> int:
    """把输出切成 2×2、2×3、3×2 格，每格对参考库做 NCC；返回最多的“格子 ≈ 某张参考”个数"""
    best = 0
    H, W = img.shape[:2]
    for r, c in ((2, 2), (3, 2), (2, 3)):
        hits = 0
        for i in range(r):
            for j in range(c):
                cell = img[i * H // r:(i + 1) * H // r, j * W // c:(j + 1) * W // c]
                f = feat(cell)
                if max((float(f @ v) for v in ref_bank().values()), default=0) >= thr:
                    hits += 1
        best = max(best, hits)
    return best


def ref_copy_score(img) -> dict:
    f = feat(img)
    best, name = -1.0, None
    for n, v in ref_bank().items():
        s = float(f @ v)
        if s > best:
            best, name = s, n
    gu, se, ch = gutters(img), seams(img), cell_hits(img)
    return {"ncc": round(best, 4), "ref": (name or "").split("__")[-1], "gutters": gu, "seams": se, "cell_hits": ch,
            # seams 只记录不判：顾沉衣帽间的门框、柜格也是贯穿的笔直断层，会误报（B5 qwen21 契约组 / face 组）
            "copied": best >= COPY_LINE or gu >= 1 or ch >= 2}


def main():
    here = Path(__file__).resolve().parent
    plan = json.loads((here / "plan.json").read_text(encoding="utf-8"))
    rows, agg = [], defaultdict(list)
    for it in plan["items"]:
        p = here / "out" / f"{it['id']}.png"
        if not p.exists() or it["kind"] == "edit":
            continue
        r = ref_copy_score(_read(p))
        rows.append((int(r["copied"]), r["gutters"], r["seams"], r["cell_hits"], r["ncc"], it["id"]))
        agg[(it["model"], it["mode"])].append(r)
    for x in sorted(rows, reverse=True)[:24]:
        print(*x)
    for k, v in sorted(agg.items()):
        print(k, len(v), "copied:", sum(x["copied"] for x in v), "gutter:", sum(x["gutters"] >= 1 for x in v),
              "seams≥2:", sum(x["seams"] >= 2 for x in v), "cell≥2:", sum(x["cell_hits"] >= 2 for x in v))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
