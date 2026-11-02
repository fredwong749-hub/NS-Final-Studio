"""IMGLAB 结构化控制 A/B 实验台（scope=ab：图只进 data/ab/imglab/<round>/，不写 takes.json / 契约账本 / 生产作业）。

出图走生产唯一出图路径 ns_render.unified_frame.build_graph（frame_v9 = S★ R0，参数不动），臂只在图上**加**结构化控制节点：
  A0      现行（作业原样）
  P<s>    + Qwen-Image 2.1 Fun ControlNet Union（服务器已有 model_patches/qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors，
            sha256 07aa9615…，与 HF Comfy-Org/Qwen-Image-2.1 一致）喂姿势骨架（tools/imglab/pose_templates.py），strength = s/10
            例：P06 = 0.6，P10 = 1.0；P06e5 = 0.6 且只在前 50% 步数生效
不抢生产：每条道整条空闲 ≥ idle_s 才交（首张），之后连着交但每张前仍要求队列空。只出单镜判定为非成人的镜头（总调度 11-02）。
打分：tools/gen_contract/remote_score.postflight_full（与生产 postflight 同一套 Q1–Q9），另记 S★ 观感漂移（LAB 均值差、裁脸清晰度）。

    .venv/Scripts/python.exe tools/imglab/ab.py run --round r2_pose --shots ep03-S1,ep01-S1 --arms A0,P06,P10 --seeds job,job+100 --lanes http://127.0.0.1:18188
    .venv/Scripts/python.exe tools/imglab/ab.py score --round r2_pose
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/prompt_v2", "tools/pipeline", "tools/gen_contract",
          "tools/autopilot", "tools/imglab"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

FUN_CN = "qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors"
# 可选基座臂：KLEIN / MOSS = 官方模板默认；带后缀的臂改参数（调参 A/B 在这里登记，臂名即配方变体）
BASE_ARM_PARAMS = {
    "KLEIN_s8": {"steps": 8}, "KLEIN_s24": {"steps": 24}, "KLEIN_noref": {"max_refs": 0},
    "MOSS_s15": {"steps": 15}, "MOSS_cfg4": {"cfg": 4.0}, "MOSS_edit": {"use_edit_lora": True},
}
POSE_DIR = ROOT / "data/ab/imglab/pose"


def out_dir(rnd: str) -> Path:
    d = ROOT / "data/ab/imglab" / rnd
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_name() -> str:
    import runs as RN
    return RN.primary_run(ROOT)


def load_job(sid: str) -> dict:
    jp = ROOT / "data/pipeline/runs" / run_name() / "assets/first_frame_jobs.json"
    return next(j for j in json.loads(jp.read_text(encoding="utf-8"))["jobs"] if j["shot"] == sid)


def is_adult(sid: str) -> bool:
    """单镜判定（总调度 11-02：不用整集标记豁免）：编译器给的理由里只要有“整集🔴”以外的理由就算成人；
    只有“整集🔴”也不出（等 classify_adult 改逐镜后再说）——即：任何理由都不出"""
    import image_jobs as IJ
    si = IJ.load_import()
    for ep in si.episodes:
        for sh in ep.shots:
            if sh.id == sid:
                _p, c, _sr, _pl = IJ.frame_prompt_full(ep, sh, si.globals, [], run_name())
                return bool(c.adult)
    raise SystemExit(f"镜头不存在：{sid}")


def seeds_for(job: dict, spec: str) -> list[int]:
    out = []
    for s in spec.split(","):
        s = s.strip()
        m = re.fullmatch(r"job(?:\+(\d+))?", s)
        out.append(int(job["seed"]) + int(m.group(1) or 0) if m else int(s))
    return out


def pose_file(sid: str, job: dict) -> Path:
    """镜头的姿势骨架：data/ab/imglab/pose/<sid>.png 有就用（手工指定的多人站位），否则按景别取单人模板"""
    import pose_templates as T
    import cv2
    f = POSE_DIR / f"{sid}.png"
    if f.exists():
        return f
    from ns_agent import framing as FR
    size = FR.size_of(job.get("prompt") or "") or "中景"
    size = size if size in T.SIZES else "中景"
    f = POSE_DIR / f"_{size}.png"
    if not f.exists():
        POSE_DIR.mkdir(parents=True, exist_ok=True)
        f.write_bytes(cv2.imencode(".png", cv2.cvtColor(T.render([T.person(size)]), cv2.COLOR_RGB2BGR))[1].tobytes())   # 中文路径不能用 imwrite
    return f


def arm_graph(wf: dict, arm: str, pose_name: str | None) -> dict:
    """在生产图上加控制节点（不改任何已有参数）。生产图模型链：10 UNET → 60 LoRA → 13 QwenImage21Cache → 38 CFGGuider"""
    if arm == "A0":
        return wf
    m = re.fullmatch(r"P(\d\d)(?:e(\d))?", arm)
    if not m:
        raise SystemExit(f"未知臂 {arm}")
    strength = int(m.group(1)) / 10
    end = int(m.group(2)) / 10 if m.group(2) else 1.0
    src = wf["13"]["inputs"]["model"]
    wf["200"] = {"class_type": "ModelPatchLoader", "inputs": {"name": FUN_CN}}
    wf["201"] = {"class_type": "LoadImage", "inputs": {"image": pose_name}}
    wf["202"] = {"class_type": "ZImageFunControlnet", "inputs": {"model": src, "model_patch": ["200", 0], "vae": ["12", 0],
                                                               "strength": strength, "image": ["201", 0],
                                                               "start_percent": 0.0, "end_percent": end}}
    wf["13"]["inputs"]["model"] = ["202", 0]
    return wf


def lane_idle(url: str, need_s: float, state: dict) -> bool:
    try:
        q = json.loads(urllib.request.urlopen(url + "/queue", timeout=10).read())
        busy = bool(q["queue_running"] or q["queue_pending"])
    except Exception:  # noqa: BLE001
        busy = True
    now = time.time()
    if busy:
        state.pop(url, None)
        return False
    state.setdefault(url, now)
    return now - state[url] >= need_s


def run(rnd: str, shots: list[str], arms: list[str], seed_spec: str, lanes: list[str], idle_s: float) -> None:
    from ns_render import image_params as IP
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    d = out_dir(rnd)
    log = d / "takes.jsonl"
    done = set()
    if log.exists():
        for ln in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            done.add((r["shot"], r["arm"], r["seed"]))
    state: dict = {}
    warm = False
    for sid in shots:
        if is_adult(sid):
            print(f"跳过 {sid}：单镜判定为成人镜头（不出）", flush=True)
            continue
        job = load_job(sid)
        pf = pose_file(sid, job)
        for seed in seeds_for(job, seed_spec):
            for arm in arms:
                if (sid, arm, seed) in done:
                    continue
                url = None
                while url is None:
                    for u in lanes:
                        if lane_idle(u, 3 if warm else idle_s, state):
                            url = u
                            break
                    else:
                        time.sleep(5)
                client = ComfyClient(url)
                up = lambda p: client.upload_image(p, subfolder="ns_ab/imglab")  # noqa: E731
                wf, eff, sent = UF.build_graph({"prompt": job["prompt"], "refs": job["refs"]}, seed, up,
                                               f"ns_ab/imglab/{rnd}/{sid}_{arm}_s{seed}")
                if arm.split("_")[0] in ("KLEIN", "MOSS"):      # 可选基座（tools/imglab/bases.py）；S★ 后期（缩回 768×1344 + 锐化）照用，便于同口径打分
                    import bases as BS
                    base = arm.split("_")[0].lower()
                    names = [up(ROOT / r) for r in job["refs"]] if BS.BASES[base]["max_refs"] or "edit" in arm.lower() else []
                    wf = BS.build(base, job["prompt"], names, seed, f"ns_ab/imglab/{rnd}/{sid}_{arm}_s{seed}",
                                  BASE_ARM_PARAMS.get(arm, {}))
                    pose_name = None
                else:
                    pose_name = up(pf) if arm != "A0" else None
                    wf = arm_graph(wf, arm, pose_name)
                t0 = time.time()
                entry, secs = client.run(wf, timeout_s=1800)
                warm = True
                state[url] = time.time() - idle_s
                item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
                raw = d / f"{sid}_{arm}_s{seed}_raw.png"
                client.download(item, raw)
                post = IP.post_file(raw, eff)
                rec = {"scope": "ab", "experiment": "imglab", "round": rnd, "shot": sid, "arm": arm, "seed": seed, "lane": url,
                       "file": Path(post["path"]).relative_to(ROOT).as_posix(), "raw": raw.relative_to(ROOT).as_posix(),
                       "pose": pf.relative_to(ROOT).as_posix() if arm != "A0" else None, "comfy_s": round(secs, 1),
                       "wall_s": round(time.time() - t0, 1), "prompt": sent, "refs": job["refs"],
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(json.dumps({k: rec[k] for k in ("shot", "arm", "seed", "comfy_s", "lane")}, ensure_ascii=False), flush=True)


def look_drift(a: Path, b: Path) -> dict:
    """S★ 观感漂移旁证：全图 LAB 均值差（ΔL / Δa / Δb）与全图清晰度比（Laplacian 方差）"""
    import cv2
    import numpy as np
    A, B = cv2.imread(str(a)), cv2.imread(str(b))
    la, lb = cv2.cvtColor(A, cv2.COLOR_BGR2LAB).reshape(-1, 3).mean(0), cv2.cvtColor(B, cv2.COLOR_BGR2LAB).reshape(-1, 3).mean(0)
    sa = cv2.Laplacian(cv2.cvtColor(A, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    sb = cv2.Laplacian(cv2.cvtColor(B, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    d = (lb - la).tolist()
    return {"dL": round(d[0], 1), "da": round(d[1], 1), "db": round(d[2], 1), "sharp_ratio": round(float(sb / max(sa, 1e-6)), 2)}


def score(rnd: str, host: str = "gpu33") -> None:
    import image_jobs as IJ
    import remote_score as RS
    d = out_dir(rnd)
    recs = [json.loads(ln) for ln in (d / "takes.jsonl").read_text(encoding="utf-8").splitlines()]
    sp = d / "scores.json"
    have = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    todo = [r for r in recs if f"{r['shot']}|{r['arm']}|{r['seed']}" not in have]
    for i in range(0, len(todo), 8):
        batch = todo[i:i + 8]
        js = []
        for r in batch:
            job = load_job(r["shot"])
            req = IJ.contract_request({**job, "prompt": r["prompt"], "graph": None})
            js.append({"id": f"{r['shot']}|{r['arm']}|{r['seed']}", "file": r["file"], "post": None, "request": req})
        res = RS.postflight_full(host, js, label=f"imglab_{rnd}")
        for r in batch:
            k = f"{r['shot']}|{r['arm']}|{r['seed']}"
            base = next((x for x in recs if x["shot"] == r["shot"] and x["seed"] == r["seed"] and x["arm"] == "A0"), None)
            res[k]["look_vs_A0"] = look_drift(ROOT / base["file"], ROOT / r["file"]) if base and r["arm"] != "A0" else None
        have.update(res)
        tmp = sp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(have, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, sp)
        print("已打分", len(have), flush=True)


def main(argv=None) -> int:
    os.chdir(ROOT)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--round", required=True)
    ap.add_argument("--shots", default="")
    ap.add_argument("--arms", default="A0")
    ap.add_argument("--seeds", default="job,job+100")
    ap.add_argument("--lanes", default="http://127.0.0.1:18188")
    ap.add_argument("--idle-s", type=float, default=120)
    ap.add_argument("--host", default="gpu33")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.round, [s for s in a.shots.split(",") if s], a.arms.split(","), a.seeds, a.lanes.split(","), a.idle_s)
    else:
        score(a.round, a.host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
