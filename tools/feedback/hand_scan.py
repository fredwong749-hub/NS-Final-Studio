"""FEEDBACK fb-0001 同类扫描：视频里的手是否畸形（并指 / 手指融化 / 手和镜中倒影或物体粘连 / 多指 / 糊成一团）。

为什么要单独一项：V6（tools/series10_video/v6_limbs.py）用 MediaPipe 数手、量 21 点骨长比例——MediaPipe 对畸形手照样
拟合出“正常”的 21 点骨架，所以形状类缺陷（粘连、融化、手和倒影合成一只）它原理上测不到；V9 本地看图只均匀抽 6 帧且
hand_malformed 不阻断。这里：每条视频均匀抽 16 帧拼成 4×4 印样（一张图、一次请求），只问手，交本地看图模型（gpu36 /
笔记本 Qwen3-VL，K-REV-V01：帧不出本地）。
实测（11-02）：已知正例 ep02/S3 印样和 4 张局部放大都被 Qwen3-VL-8B nf4 判“无缺陷、置信 1.0”→ 看图这一路对该类召回 0/1，
不能当闸门，只留作对照；文字层风险扫描（--prompts，prompt_risk）是当前唯一可靠的前置拦截。检测器交 VQAGATE 另做。

    .venv/Scripts/python.exe tools/feedback/hand_scan.py [--only ep02/S3] [--out data/feedback/scans/hand_scan.json]
"""
from __future__ import annotations

import argparse
import re
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))
from ns_agent.vqa import client as VC  # noqa: E402

N = 16
SYSTEM = "你是短剧视频质检员，只检查画面里人物的手，按事实回答，只输出 JSON。"
PROMPT = """这是一条 8 秒竖屏视频按时间顺序均匀抽的 16 帧，拼成 4×4 印样（从左到右、从上到下，第 1 帧在左上，第 16 帧在右下）。
只看人物的手（包括镜子里倒影的手），逐帧检查有没有以下缺陷：
- fused：手和镜中倒影 / 另一只手 / 物体 / 衣服粘连融合成一团，分不清哪只是哪只
- melted：手指融化、糊成一片、形状不成手
- finger_count：明显多指或少指（不是被遮挡）
- deformed：手指扭曲反关节、手腕断裂、手掌比例离谱
- mirror_wrong：手的倒影和真手对不上（倒影的手在别处 / 姿势不同）
看不清手或手被正常遮挡不算缺陷。
只输出 JSON：{"hands_visible": true/false, "defect": true/false, "kinds": ["fused"...], "frames": [出问题的帧号 1-16], "confidence": 0-1, "why": "一句话说哪一帧哪只手怎么不对"}"""


def contact(video: Path, out: Path) -> Path:
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    tiles = []
    for i in range(N):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i * (total - 1) / (N - 1)))
        ok, fr = cap.read()
        if not ok:
            fr = tiles[-1] if tiles else np.zeros((640, 360, 3), np.uint8)
        fr = cv2.resize(fr, (270, int(270 * fr.shape[0] / fr.shape[1])))
        cv2.putText(fr, str(i + 1), (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        tiles.append(fr)
    cap.release()
    rows = [np.hstack(tiles[r * 4:(r + 1) * 4]) for r in range(4)]
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out


def scan_one(video: Path) -> dict:
    sid = f"{video.parent.parent.name}/{video.parent.name}"
    sheet = contact(video, ROOT / "data" / "feedback" / "scans" / "hand_sheets" / f"{sid.replace('/', '-')}.jpg")
    req = {"system": SYSTEM, "text": PROMPT, "images": [{"path": str(sheet), "label": "【印样】", "max_pixels": 1200000}]}
    t0 = time.time()
    res = VC.generate(req, wait_s=900, label=f"feedback-hand {sid}")
    v = VC.rubric._loads_loose(res.get("text", "")) if "error" not in res else None
    return {"shot": sid, "video": str(video.relative_to(ROOT)).replace("\\", "/"), "sheet": str(sheet.relative_to(ROOT)).replace("\\", "/"),
            "verdict": v, "error": res.get("error") or (None if v else "输出不是 JSON"), "raw": (res.get("text") or "")[:600],
            "seconds": round(time.time() - t0, 1), "cached": res.get("cached")}


MIRROR_RE = re.compile(r"mirror|reflection|reflective|glass|镜", re.I)
# 中英都认：英文给编译后的 H3，中文给剧本 / 分拍（K-WRT-211 写作层 lint 复用）
HAND_CONTACT_RE = re.compile(
    r"(hand|palm|fingertips?|knuckles?)[^.]{0,60}\b(on|against|to)\b (the )?(mirror|glass|window|panel)"
    r"|(掌心|手掌|手|指尖|指节|手指)[^。；｜]{0,12}(贴|按|扶|抵|撑|压)[^。；｜]{0,6}(镜面|镜子|玻璃|落地窗|反光)", re.I)
HAND_RE = re.compile(r"\b(hand|hands|palm|fingers|fingertips|knuckles)\b|掌心|手掌|指尖|指节|手指|(?<![一二三四五六七八九十对双])手(?![机表帕套段法艺术])", re.I)


def prompt_risk(prompt: str) -> dict:
    """fb-0001 规则（文字层，编译 / 写作 lint 可直接复用）：镜面场景里写“手按 / 贴镜面”= 高风险（生成模型把真手和倒影
    画成合掌粘连，倒影姿势跟不上真手）；镜面场景 + 任何手部动作 = 中风险；8 s 内手部动作 ≥3 处 = 中风险。"""
    mirror = bool(MIRROR_RE.search(prompt))
    contact = bool(HAND_CONTACT_RE.search(prompt))
    n_hand = len(HAND_RE.findall(prompt))
    level = "high" if mirror and contact else "mid" if (mirror and n_hand) or n_hand >= 3 else "low"
    return {"level": level, "mirror": mirror, "hand_on_mirror": contact, "hand_mentions": n_hand}


def scan_prompts() -> list[dict]:
    out = []
    for p in sorted((ROOT / "data" / "renders").glob("ep*/S*/video.mp4")):
        if p.parts[-3].startswith("_"):
            continue
        t = json.loads((p.parent / "takes.json").read_text(encoding="utf-8")) if (p.parent / "takes.json").exists() else {}
        vt = [x for x in t.get("takes", []) if x.get("stage") == "video"]
        pr = (vt[-1].get("prompt") if vt else "") or ""
        out.append({"shot": f"{p.parent.parent.name}/{p.parent.name}", **prompt_risk(pr)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="如 ep02/S3")
    ap.add_argument("--out", default="data/feedback/scans/hand_scan.json")
    ap.add_argument("--prompts", action="store_true", help="只做文字层风险扫描（不调看图模型）")
    a = ap.parse_args(argv)
    if a.prompts:
        rows = scan_prompts()
        o = ROOT / "data" / "feedback" / "scans" / "prompt_hand_risk.json"
        o.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(o, json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}, ensure_ascii=False, indent=1))
        for lv in ("high", "mid"):
            print(lv, [r["shot"] for r in rows if r["level"] == lv])
        return rows
    vids = sorted(p for p in (ROOT / "data" / "renders").glob("ep*/S*/video.mp4") if not p.parts[-3].startswith("_"))
    if a.only:
        vids = [p for p in vids if f"{p.parent.parent.name}/{p.parent.name}" in a.only]
    out = ROOT / a.out
    done = {}
    if out.exists() and not a.only:
        done = {r["shot"]: r for r in json.loads(out.read_text(encoding="utf-8")).get("rows", []) if not r.get("error")}
    rows = []
    for p in vids:
        sid = f"{p.parent.parent.name}/{p.parent.name}"
        r = done.get(sid) or scan_one(p)
        rows.append(r)
        print(sid, json.dumps(r.get("verdict"), ensure_ascii=False) if r.get("verdict") else r.get("error"), flush=True)
        if not a.only:
            hits = [x["shot"] for x in rows if (x.get("verdict") or {}).get("defect")]
            out.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(out, json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "scanned": len(rows), "hits": hits, "rows": rows},
                                          ensure_ascii=False, indent=1))
    return rows


def _atomic_write(path, text: str) -> None:
    """原子写：先写同目录临时文件再 os.replace（总调度 11-02 14:0x，arch_scan nonatomic_json）。"""
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
