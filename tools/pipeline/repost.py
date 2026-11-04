"""重后期（H2a）：按当前 post_film 配置，对每镜当前首帧 / 尾帧的 *_raw.png 重新生成后期图，另存 *_raw_film.png，原图与旧后期图都保留。

  python tools/pipeline/repost.py --run series10_v2 --episode 1 [--dry] [--apply] [--force-on] [--local-raw]
  默认 --dry：只出文件清单 + 指标对比（look_metrics：halo / clip_hi / 背景亮度）。
  --apply：把新图登记为该镜的新版本（ns_render.pipeline.mutate_takes，不设为当前、不动 frame.png）。
  --force-on：配置里 enabled=false 时，仅在本进程内存里按 post_film 其余参数当作 enabled=true（不改配置文件）。
  --local-raw：当前版本的 raw 不在本机时，退而处理该镜 takes/ 下磁盘上有的 *_raw.png（只 dry 用，不登记）。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "packages/schema", "services/agent", "services/recipes", "tools/pipeline"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from ns_render import image_params as IP  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
import look_metrics as LM  # noqa: E402


def _bg_lum(path: Path) -> float:
    """四周背景（外 20%，同 look_metrics 的圈）平均亮度 0-1"""
    import numpy as np
    from PIL import Image
    g = np.asarray(Image.open(path).convert("L"), np.float32) / 255
    h, w = g.shape
    ring = np.ones((h, w), bool)
    ring[int(h * .2):int(h * .8), int(w * .2):int(w * .8)] = False
    return round(float(g[ring].mean()), 3)


def _eff_for(old_post: Path | None, raw: Path, take: dict) -> dict:
    """重建缩回尺寸：优先旧后期图的尺寸（= 交付尺寸）；没有就用 take.params.post.size / 原图尺寸"""
    from PIL import Image
    size = None
    if old_post and old_post.exists():
        size = Image.open(old_post).size
    elif ((take.get("params") or {}).get("post") or {}).get("size"):
        size = tuple(take["params"]["post"]["size"])
    if not size:
        size = Image.open(raw).size
    sh = (((take.get("params") or {}).get("requested") or {}).get("sharpen")) or {}
    return {"tier": "preview", "render_scale": 1.5, "width": int(size[0]), "height": int(size[1]), "sharpen": sh}


def _metrics(p: Path) -> dict:
    m = LM.measure(p)
    return {"halo": m["halo"], "clip_hi": m["clip_hi"], "bg_lum": _bg_lum(p)}


def plan(run: str, ep: int, force_on: bool, local_raw: bool) -> list[dict]:
    rd = P._run_renders(run) / f"ep{ep:02d}"
    cfg = IP.quality().get("post_film") or {}
    if force_on:
        cfg = {**cfg, "enabled": True}
    jobs = []
    for sd in sorted(rd.glob("S*"), key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 0):
        tj = sd / "takes.json"
        if not tj.exists():
            continue
        doc = json.loads(tj.read_text(encoding="utf-8"))
        for stage in ("image", "last"):
            n = (doc.get("active") or {}).get(stage)
            take = next((t for t in doc["takes"] if t["stage"] == stage and t["n"] == n), None)
            if not take:
                continue
            raw_rel = take.get("raw_file") or take["file"]
            cand = [(P.DATA / raw_rel, take, "active")]
            if not cand[0][0].exists() or not raw_rel.endswith("_raw.png"):
                cand = []
                if local_raw:
                    cand = [(f, take, "local-raw") for f in sorted((sd / "takes").glob(f"{'image' if stage == 'image' else 'last'}_*_raw.png"))]
                if not cand:
                    jobs.append({"shot": f"ep{ep:02d}-{sd.name}", "stage": stage, "n": n, "skip": f"raw 不在本机（{raw_rel}）"})
                    continue
            for raw, tk, kind in cand:
                old_post = P.DATA / tk["file"] if kind == "active" else raw.with_name(raw.stem + "_post.png")
                dst = raw.with_name(raw.stem + "_film.png")
                jobs.append({"shot": f"ep{ep:02d}-{sd.name}", "stage": stage, "n": n, "kind": kind, "raw": raw,
                             "old": old_post, "dst": dst, "take": tk, "cfg": cfg, "eff": _eff_for(old_post, raw, tk)})
    return jobs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="repost")
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--dry", action="store_true", help="默认；只出清单和指标")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force-on", action="store_true")
    ap.add_argument("--local-raw", action="store_true")
    a = ap.parse_args(argv)
    if a.apply and a.local_raw:
        print("--local-raw 只能 dry"); return 2
    jobs = plan(a.run, a.episode, a.force_on, a.local_raw)
    if not any("dst" in j for j in jobs) and not jobs:
        print("没有镜头"); return 0
    cfg0 = jobs[0].get("cfg") if jobs and "cfg" in jobs[0] else (IP.quality().get("post_film") or {})
    if not (cfg0.get("enabled") or a.force_on) and not a.local_raw:
        print("post_film.enabled=false；要预演请加 --force-on（不改配置文件）"); 
    done = 0
    for j in jobs:
        if "skip" in j:
            print(json.dumps({k: v for k, v in j.items()}, ensure_ascii=False)); continue
        cfg = {**j["cfg"], "enabled": True} if a.force_on else j["cfg"]
        post = IP.post_file(j["raw"], j["eff"], film_cfg=cfg, dst=j["dst"])
        if not post:
            print(json.dumps({"shot": j["shot"], "stage": j["stage"], "skip": "post_film 未开"}, ensure_ascii=False)); continue
        rec = {"shot": j["shot"], "stage": j["stage"], "kind": j["kind"], "raw": str(j["raw"]), "old": str(j["old"]),
               "new": post["path"], "steps": post["steps"]}
        try:
            rec["before"] = _metrics(j["old"]) if j["old"].exists() else None
            rec["after"] = _metrics(Path(post["path"]))
        except Exception as e:  # noqa: BLE001
            rec["metrics_error"] = repr(e)[:120]
        print(json.dumps(rec, ensure_ascii=False))
        done += 1
        if a.apply and j["kind"] == "active":
            _register(a.run, j, post)
    print(f"# 完成 {done} 张（{'已登记为新版本，未设为当前' if a.apply else 'dry：未登记'}）")
    return 0


def _register(run: str, j: dict, post: dict) -> None:
    sid, stage, src_n = j["shot"], j["stage"], j["n"]
    new_rel = Path(post["path"]).resolve().relative_to(P.DATA.resolve()).as_posix()
    info = {"file": new_rel, "from": j["take"].get("raw_file"), **{k: v for k, v in post.items() if k != "path"}}

    def fn(doc):
        used = {t["n"] for t in doc["takes"] if t["stage"] == stage}
        t = copy.deepcopy(next(x for x in doc["takes"] if x["stage"] == stage and x["n"] == src_n))
        t["n"] = max(used) + 1
        t["file"] = new_rel
        t["params"] = {**(t.get("params") or {}), "post": info, "repost_of": src_n}
        t.pop("postflight", None)
        doc["takes"].append(t)
        return doc
    P.mutate_takes(sid, fn, op="repost_film", by="tools/pipeline/repost.py", run=run)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
