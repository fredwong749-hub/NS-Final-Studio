"""缺陷猎捕的看图类（vlm_queue）实跑：把现行首帧 / 进了成片的可疑视频交 VQA 的本地看图服务（RSI 11-01，R11-11 续）。

只调 ns_agent.vqa.client（gpu36 自建服务，图片不出本机，K-REV-V01）；服务自己等空闲卡（need_free_mib），不抢 ComfyUI。
结果：
  - 首帧：VQ.remember 写进 data/vqa/index.json + verdicts（VQA 的共享缓存入口，postflight 的 cached_for 能复用）
  - 全部：追加 data/qa/defect_hunt/vlm_results.jsonl；defect_hunt 的 vqa_bridge 读 index 把看图类从“交 VQA”变成“部分已判”
顺序（影响大的先跑）：多人镜首帧（DH-F13 第二人表情）→ 进了成片的多手视频（DH-X03 / DH-V07）→ 其余现行首帧。

    .venv/Scripts/python.exe tools/qa/defect_vlm.py --limit 20 --budget-min 40
    .venv/Scripts/python.exe tools/qa/defect_vlm.py --dry          # 只列目标
只读剧本 / 不改出图 / 不触发重出；不评价剧情。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import defect_hunt as DH  # noqa: E402

OUT = ROOT / "data" / "qa" / "defect_hunt" / "vlm_results.jsonl"


def _take(shot: str) -> dict:
    ep, s = shot.split("-")
    try:
        d = json.loads((ROOT / "data" / "renders" / ep / s / "takes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    n = (d.get("active") or {}).get("image")
    return next((t for t in d.get("takes") or [] if t.get("stage") == "image" and str(t.get("n")) == str(n)), {}) or {}


def targets() -> list[dict]:
    multi = {sh.id for _, sh in DH.shots() if len(DH.on_screen(sh)) >= 2}
    st = DH._load_state()
    out, seen = [], set()
    frs = sorted(DH.frames(), key=lambda fr: (fr["shot"] not in multi, fr["shot"]))
    for fr in frs[:len([f for f in frs if f["shot"] in multi])]:
        out.append({"kind": "image", "shot": fr["shot"], "file": str(fr["file"]), "why": "多人镜首帧（DH-F13）"})
        seen.add(fr["shot"])
    for ex in (st.get("classes", {}).get("DH-X03") or {}).get("examples") or []:
        m = DH.ORIGIN_RE.search("VIDEO10 " + ex.split("｜", 1)[1].split("进了成片")[0].replace("（", " ").replace("）", " ") + " x")
        if m:
            # 本机只有预览（clips 原片在出片服务器上）：_preview/<shot>__<版本>.mp4
            clip = next(iter(sorted((DH.RUN / "video" / "_preview").glob(f"{m.group(1)}__{m.group(2)}.mp4"))), None)
            if clip and str(clip) not in seen:
                out.append({"kind": "video", "shot": m.group(1), "file": str(clip), "why": "进了成片的可疑视频（DH-X03）"})
                seen.add(str(clip))
    for fr in frs:
        if fr["shot"] not in seen:
            out.append({"kind": "image", "shot": fr["shot"], "file": str(fr["file"]), "why": "现行首帧"})
    return [t for t in out if t["kind"] == "video"] + [t for t in out if t["kind"] == "image"]   # 进了成片的先判


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--budget-min", type=float, default=40)
    ap.add_argument("--wait-s", type=float, default=600)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tg = targets()[:a.limit]
    if a.dry:
        for t in tg:
            print(t["kind"], t["shot"], t["why"], t["file"])
        return 0
    from ns_agent.vqa import client
    from ns_agent.vqa import contract as VQ
    t_end = time.time() + a.budget_min * 60
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    for t in tg:
        if time.time() > t_end:
            print("预算用完，停（剩下的下次续跑；已判的有缓存）")
            break
        tk = _take(t["shot"])
        prompt, refs = tk.get("prompt") or "", tk.get("references") or []
        refs = [str(ROOT / r) if not Path(str(r)).is_absolute() else str(r) for r in refs if isinstance(r, str)]
        try:
            v = (client.inspect_image(t["file"], prompt, refs, wait_s=a.wait_s, label=f"RSI-{t['shot']}") if t["kind"] == "image"
                 else client.inspect_video(t["file"], prompt, refs, wait_s=a.wait_s, label=f"RSI-{t['shot']}"))
        except Exception as e:  # noqa: BLE001
            v = {"error": f"{type(e).__name__}: {e}"}
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **t, "error": v.get("error"), "defects": v.get("defects"),
               "unsure": v.get("unsure"), "key": v.get("key"), "seconds": v.get("seconds"),
               "evidence": {k: (v.get("checks") or {}).get(k, {}).get("e") for k in (v.get("defects") or [])}}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(t["shot"], t["kind"], rec["error"] or rec["defects"])
        if v.get("error"):
            if any(w in str(v["error"]) for w in ("空闲卡", "Timeout", "OutOfMemory", "out of memory")):
                # 11-01 16:07 实测：看图模型 7 GB 装上 GPU0 后 ComfyUI 涨到 16 GB，看图请求 OOM——一出现就停，不和生产抢卡
                print("看图服务等不到空闲卡 / 显存不够，停（不抢 ComfyUI）")
                break
            continue
        if t["kind"] == "image":
            VQ.remember(t["file"], v)
        done += 1
    print(f"完成 {done} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
