"""VIDLAB A/B 出片（线 2；复用 VIDEO-RCA 实验台 tools/video_rca/lab.py 的 plan / export / pull，不另写执行器）。

在 lab.py 臂定义之外只多一个键：
  "graph_set": [["LoraLoaderModelOnly", "strength_model", 0.8], ...]   # 按节点类型改输入（LoRA 强度等运动 / 表演参数）
  "camctl": {"move": "truck_right", "strength": 0.6, "end_percent": 0.5, "amp": 1.0}       # 结构化运镜：Fun ControlNet 控制视频
     （tools/vidlab/camctl.py 本地渲染 → 上传到服务器 <exp>/inputs/ → VHS_LoadVideoPath → MiniMaxH3FunControlNetApply，插在 LoRA 之后）
其余（from_job 复用旧编译稿 + prompt_replace 同 seed 只换一处）与 lab.py 完全一致；服务器执行器 = srv_run.py（生产有 ready 单让路）。

  python tools/vidlab/ab_run.py plan   <exp.json>
  python tools/vidlab/ab_run.py export <exp.json> --lane 8189 [--host gpu36]
  python tools/vidlab/ab_run.py pull   <exp.json>          # 拉 results.json + 成片（mp4 放 data/rsi/vidlab/ab_clips/<exp>/）
判定：python tools/vidlab/score.py ab --a "<基线 glob>" --b "data/rsi/vidlab/ab_clips/<exp>/*<臂>*.mp4" --name <exp>_<臂>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "video_rca"))
import lab as LAB  # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "netfix"))
sys.path.insert(0, str(ROOT / "tools" / "vidlab"))
import rssh  # noqa: E402
import vio as VIO  # noqa: E402


PATCH = "minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors"   # Comfy-Org/MiniMax-H3（sha256 9c645c0a…）
CTL_DIR = ROOT / "data" / "rsi" / "vidlab" / "camctl"


def add_camctl(e: dict, v: dict) -> None:
    import camctl as CC
    c = v["arm"]["camctl"]
    ff = v["inputs"].get("@first_frame") or v["score_meta"].get("first_frame")
    ff = ff if Path(ff).is_absolute() else ROOT / ff
    name = f"{v['arm']['id']}_ctl.mp4"
    meta = CC.render(Path(ff), c["move"], int(v["frames"]), CTL_DIR / e["name"] / name, float(c.get("amp", 1.0)))
    g = v["graph"]
    lora = next(k for k, n in g.items() if n["class_type"] == "LoraLoaderModelOnly")
    vae = next(k for k, n in g.items() if n["class_type"] == "MiniMaxH3ImageToVideo")
    vae = g[vae]["inputs"]["vae"]
    g["901"] = {"class_type": "ModelPatchLoader", "inputs": {"name": c.get("patch", PATCH)}}
    g["902"] = {"class_type": "VHS_LoadVideoPath", "inputs": {
        "video": f"{LAB.SRV}/{e['name']}/inputs/{name}", "force_rate": 0, "custom_width": 768, "custom_height": 1344,
        "frame_load_cap": int(v["frames"]), "skip_first_frames": 0, "select_every_nth": 1, "format": "None"}}
    g["903"] = {"class_type": "MiniMaxH3FunControlNetApply", "inputs": {
        "model": [lora, 0], "model_patch": ["901", 0], "vae": vae, "strength": float(c.get("strength", 0.6)),
        "start_percent": 0.0, "end_percent": float(c.get("end_percent", 0.5)), "control_video": ["902", 0]}}
    hit = 0
    for k, n in g.items():
        if k != "903" and (n.get("inputs") or {}).get("model") == [lora, 0]:
            n["inputs"]["model"] = ["903", 0]
            hit += 1
    if not hit:
        raise SystemExit(f"{v['arm']['id']}：找不到 LoRA 下游节点")
    v["camctl_file"] = str(CTL_DIR / e["name"] / name)
    v["prompt_notes"] = v["prompt_notes"] + [f"camctl {meta}"]


def plan(e: dict) -> list[dict]:
    vs = LAB.plan(e)
    for v in vs:
        if v["arm"].get("camctl"):
            add_camctl(e, v)
        for cls, key, val in v["arm"].get("graph_set") or []:
            hit = 0
            for n in v["graph"].values():
                if n.get("class_type") == cls and key in (n.get("inputs") or {}):
                    n["inputs"][key] = val
                    hit += 1
            if not hit:
                raise SystemExit(f"{v['arm']['id']}：图里没有 {cls}.{key}")
            v["prompt_notes"] = v["prompt_notes"] + [f"graph_set {cls}.{key} = {val}"]
    return vs


def jobs_of(e: dict, vs: list[dict]) -> list[dict]:
    return [{"id": v["arm"]["id"], "shot": v["shot"], "recipe": v["recipe"], "seed": v["seed"], "kind": "video",
             "v67_meta": v["arm"].get("v67_meta") or e.get("v67_meta", {}).get(v["shot"]),
             "graph": v["graph"], "inputs": dict(v["inputs"]), "score_meta": {**v["score_meta"], "first_frame": None},
             "prompt": v["prompt"], "prompt_notes": v["prompt_notes"], "overrides": v["arm"].get("overrides"),
             "graph_set": v["arm"].get("graph_set")} for v in vs]


def main(argv):
    cmd, p = argv[0], Path(argv[1])
    if "--host" in argv:
        LAB.HOST = argv[argv.index("--host") + 1]
    e = json.loads(p.read_text(encoding="utf-8"))
    if cmd == "plan":
        for v in plan(e):
            print(v["arm"]["id"], v["seed"], v["frames"], v["prompt_notes"][-3:])
    elif cmd == "export":
        vs = plan(e)
        jobs = jobs_of(e, vs)
        d = LAB.AB / e["name"]
        d.mkdir(parents=True, exist_ok=True)
        VIO.write_json(d / "jobs_local.json", jobs, indent=1)
        lane = int(argv[argv.index("--lane") + 1]) if "--lane" in argv else None
        for v in vs:                       # 控制视频先传上去（srv_run 只上传 @ 图片输入）
            if v.get("camctl_file"):
                f = Path(v["camctl_file"])
                r = rssh.run_retry(LAB.HOST, f"mkdir -p {LAB.SRV}/{e['name']}/inputs && cat > {LAB.SRV}/{e['name']}/inputs/{f.name}",
                                   input=f.read_bytes(), timeout=600)
                if r.returncode:
                    raise RuntimeError(f"上传控制视频失败 {f.name} rc={r.returncode}")
        LAB.export(e["name"], jobs, [], lane)
    elif cmd == "pull":
        LAB.pull(e["name"])
        dst = ROOT / "data" / "rsi" / "vidlab" / "ab_clips" / e["name"]
        dst.mkdir(parents=True, exist_ok=True)
        r = rssh.run_retry(LAB.HOST, f"cd {LAB.SRV}/{e['name']} && ls *.mp4 2>/dev/null | grep -v _prev | tar cf - -T -",
                           timeout=1800)
        if r.returncode:
            raise RuntimeError(f"拉片失败 rc={r.returncode}: {(r.stderr or b'')[:200]!r}")
        subprocess.run(["tar", "xf", "-", "-C", str(dst)], input=r.stdout, timeout=600, check=True)
        res = LAB.AB / e["name"] / "results.json"
        if res.is_file():
            (dst / "results.json").write_bytes(res.read_bytes())
        print("clips", len(list(dst.glob("*.mp4"))))


if __name__ == "__main__":
    main(sys.argv[1:])
