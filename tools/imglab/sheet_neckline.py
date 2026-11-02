"""设定图契约：脸部栏构图必须带到衣服领口（K-AST-901，总调度 11-02 12:3x：F s101 / s202 的脸部栏只到锁骨下，看起来像没穿衣服，不选）。

判法（确定性，只看四栏设定图最左一栏的底边带）：最左 15% 宽、底部 14% 高的条带里，YCrCb 肤色像素占比 > 线（缺省 0.45）
= 脸部栏底边全是皮肤（没带到领口）→ fail。头发（蓝发）不算皮肤。线按 11-02 第二季 8 张标定：
被否的 F s101 / s202 = 0.57；选中的 E s101 = 0.03、F s303（无肩带束腰）= 0.35、D s101 = 0.01、I s303 = 0.24。

    .venv/Scripts/python.exe tools/imglab/sheet_neckline.py <sheet.png>... [--json]     退出码 0 = 全过，1 = 有不过
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LINE = 0.45


def check(path: str | Path, line: float = LINE) -> dict:
    import cv2
    import numpy as np
    data = np.frombuffer(Path(path).read_bytes(), np.uint8)
    im = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if im is None:
        return {"file": str(path), "ok": False, "error": "读不了图"}
    h, w = im.shape[:2]
    band = im[int(h * 0.86):h, 0:int(w * 0.15)]
    ycc = cv2.cvtColor(band, cv2.COLOR_BGR2YCrCb)
    skin = float((cv2.inRange(ycc, (0, 135, 85), (255, 180, 135)) > 0).mean())
    return {"file": str(path), "skin_ratio": round(skin, 3), "line": line, "ok": skin <= line,
            "detail": ("脸部栏底边带到衣服领口" if skin <= line else f"脸部栏底边皮肤占 {skin:.0%}（线 {line:.0%}），像没穿衣服 / 没带到领口")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--line", type=float, default=LINE)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rs = [check(f, a.line) for f in a.files]
    print(json.dumps(rs, ensure_ascii=False, indent=1) if a.json else "\n".join(f"{'✓' if r['ok'] else '✗'} {r['file']} {r.get('detail', r.get('error'))}" for r in rs))
    return 0 if all(r["ok"] for r in rs) else 1


if __name__ == "__main__":
    sys.exit(main())
