"""IMGGEN（2026-10-31 夜，总调度第 3 步）：series10_v1 六个主场景各出 2 张空镜场景参考底图（同一光线基线），作首帧的场景参考。

场景描述只取 P4 场景表原文（名称 | 空间 | 时段 | 光线 | 主要陈设），系统只加“空镜、无人物、竖构图”的包装句，不改内容。
出图走系统默认预设 leica_sstar（ns_render.image_params：Turbo 8 步 + krea2_film_texture 0.5 + 1.5× 出图 + lanczos 缩回 + USM + S★ 后缀），
768×1344 竖构图，与首帧同画幅。只在 gpu33 三道（gpu36 归 BAKEOFF），每道同时 1 个、front 插队（VIDEO10 约定）。
自动质检：原地 ArcFace 检脸（空镜里不该有人脸）、rapidocr 查字；每个场景按“无人脸、无字、清晰度高”选暂定。
输出：data/pipeline/runs/series10_v1/images/scenes/<scene_id>/plate_s<seed>.png（+ _post.png）、scenes.json
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen"):
    sys.path.insert(0, str(ROOT / p))
from ns_render import image_params as IP  # noqa: E402
from ns_render import workflows as W  # noqa: E402
import imggen as IG  # noqa: E402

RUN = ROOT / "data/pipeline/runs/series10_v1"
OUT = RUN / "images/scenes"
LANES = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191"}
SCENES = ("sk_gu_apartment", "sk_home_kitchen", "sk_alley_ballroom", "sk_office_night", "sk_studio", "sk_elevator")
SEEDS = (701, 702)
ROW = re.compile(r"\|\s*(sk_[a-z_]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")


def scene_table() -> dict:
    out = {}
    # P4 场景表没写全的（sk_office_night）取写作输入 P3-P4.user.md 里的同一张场景表
    import os
    if os.environ.get("NS_ALLOW_P4_SOURCE") != "1":   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：场景表现行来源 = 导入稿 globals；P4 旧稿默认不读
        raise SystemExit("scene_plates 读的是写作中间稿 P4（10-31 一次性出场景底图用）；确需复现请设 NS_ALLOW_P4_SOURCE=1")
    for md in [*sorted(RUN.glob("ep*/P4_ep*.md")), *sorted(RUN.glob("ep*/prompts/P3-P4.user.md"))]:
        for m in ROW.finditer(md.read_text(encoding="utf-8")):
            out.setdefault(m.group(1), {"name": m.group(2), "space": m.group(3), "time": m.group(4), "light": m.group(5),
                                        "props": m.group(6)})
    return out


def prompt_for(row: dict) -> str:
    return (f"场景参考底图，空镜，画面中没有任何人物、没有人影。{row['name']}：{row['space']}。时段：{row['time']}。"
            f"光线：{row['light']}。主要陈设：{row['props']}。竖构图，平视机位，空间完整、陈设清晰可辨，真实摄影")


def main():
    table = scene_table()
    res_p = OUT / "scenes.json"
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else {}
    tasks = [(sid, seed) for sid in SCENES for seed in SEEDS if not (res.get(sid, {}).get(str(seed)) or {}).get("file")]
    eff = IP.resolve("leica_sstar", {"loras": [{"name": "krea2_film_texture_qwen21.safetensors", "strength": 0.5}]})
    lk = threading.Lock()
    print("scenes", len(table), "tasks", len(tasks), flush=True)

    def worker(lane, url):
        c = IG.Lane(lane, url)
        while True:
            with lk:
                if not tasks:
                    return
                sid, seed = tasks.pop(0)
            row = table[sid]
            p = prompt_for(row)
            wf = W.qwen_t2i(p, "", 768, 1344, seed, f"imgfix_scene/{sid}_s{seed}", m=W.QwenModel(), loras=[])
            wf = IP.apply(wf, eff, set())
            try:
                pid = c.submit(wf, front=True)
                dest = OUT / sid / f"plate_s{seed}.png"
                t0 = time.time()
                while True:
                    time.sleep(5)
                    r = c.fetch(pid, dest)
                    if r:
                        break
                rec = {"scene": sid, "seed": seed, "prompt": wf["20"]["inputs"]["prompt"], "lane": lane, "status": r,
                       "secs": round(time.time() - t0, 1), "host_path": c.last_host_path, "preset": "leica_sstar"}
                if r == "ok":
                    post = IP.post_file(dest, eff)
                    rec["raw"] = str(dest.relative_to(ROOT)).replace("\\", "/")
                    rec["file"] = str(Path(post["path"]).relative_to(ROOT)).replace("\\", "/") if post else rec["raw"]
                with lk:
                    res.setdefault(sid, {"row": row})[str(seed)] = rec
                    res_p.parent.mkdir(parents=True, exist_ok=True)
                    res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                print(time.strftime("%H:%M:%S"), lane, sid, seed, r, rec["secs"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, sid, seed, repr(e)[:200], flush=True)

    th = [threading.Thread(target=worker, args=(n, u)) for n, u in LANES.items()]
    for x in th:
        x.start()
    for x in th:
        x.join()
    pick(res)
    res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def pick(res):
    """质检 + 选暂定：无人脸、无字优先，再看清晰度（Laplacian 方差）"""
    files = {f"frame:{sid}/{k}": (None, "gpu33", v["host_path"]) for sid, d in res.items() for k, v in d.items()
             if k != "row" and isinstance(v, dict) and v.get("host_path")}
    out = IG.qc_batch(files) if files else {"items": {}}
    for sid, d in res.items():
        best = None
        for k, v in d.items():
            if k in ("row", "chosen") or not isinstance(v, dict) or not v.get("file"):
                continue
            q = out["items"].get(f"frame:{sid}/{k}") or {}
            v["faces"] = len(q.get("faces", []))
            v["text"] = [t["text"] for t in q.get("text", [])]
            g = cv2.cvtColor(cv2.imread(str(ROOT / v["file"])), cv2.COLOR_BGR2GRAY)
            v["lap_var"] = round(float(cv2.Laplacian(g, cv2.CV_32F).var()), 1)
            v["ok"] = v["faces"] == 0 and not v["text"]
            key = (v["ok"], v["lap_var"])
            if best is None or key > best[0]:
                best = (key, k)
        if best:
            d["chosen"] = {"seed": best[1], "file": d[best[1]]["file"], "tentative": True, "ok": d[best[1]]["ok"]}


if __name__ == "__main__":
    main()
