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
    meta = CC.render(Path(ff), c["move"], int(v["frames"]), CTL_DIR / e["name"] / name, float(c.get("amp", 1.0)),
                     int(c.get("dilate", 25)))
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
        for cls, key, val in v["arm"].get("graph_set") or []:
            hit = 0
            for n in v["graph"].values():
                if n.get("class_type") == cls and key in (n.get("inputs") or {}):
                    n["inputs"][key] = val
                    hit += 1
            if not hit:
                raise SystemExit(f"{v['arm']['id']}：图里没有 {cls}.{key}")
            v["prompt_notes"] = v["prompt_notes"] + [f"graph_set {cls}.{key} = {val}"]
            if cls == "MiniMaxH3ImageToVideo" and key == "length":
                v["frames"] = int(val)
                v["score_meta"]["frames"] = int(val)
        if v["arm"].get("camctl"):          # 在 graph_set 之后：控制视频帧数跟改过的 length 走
            add_camctl(e, v)
    return vs


def src_v67(arm: dict) -> dict | None:
    """from_job 臂沿用源实验的 v67_meta（人数 / 对白 / 说话人）：剧本重导入后镜号会变，按新 jobs.json 取会拿错说话人（vl_r1 S5 教训）"""
    if not arm.get("from_job"):
        return None
    f = LAB.AB / arm["from_job"][0] / "jobs_local.json"
    return next((j.get("v67_meta") for j in VIO.read_json(f) if j["id"] == arm["from_job"][1]), None)


def jobs_of(e: dict, vs: list[dict]) -> list[dict]:
    return [{"id": v["arm"]["id"], "shot": v["shot"], "recipe": v["recipe"], "seed": v["seed"], "kind": "video",
             "v67_meta": v["arm"].get("v67_meta") or e.get("v67_meta", {}).get(v["shot"]) or src_v67(v["arm"]),
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
        if "--runner" in argv and argv[argv.index("--runner") + 1] == "ab":
            # 借道专用执行器：已部署的 tools/director/ab_runner.py（只往 borrowed_lanes 里的道交单，client 前缀 vidlab-），
            # 配置随实验放服务器 <exp>/ab_runner.json；借道起止由 DEBUG-RSI 登记，本工具只在拿到确认后用
            port = lane or 8189
            sys.path.insert(0, str(ROOT / "tools" / "factory"))
            import hosts as HOSTS   # 车道表唯一来源 config/factory/hosts.json（SYSARCH 4-2）
            ln = next(k for k, rec in HOSTS.lanes(LAB.HOST, enabled=None).items() if int(rec.get("comfy_port") or 0) == port)
            gi = ln.split(":")[1]
            cfg = {"lane": f"{LAB.HOST}:{gi}", "port": port, "out": HOSTS.comfy_output(ln),
                   "client_prefix": "vidlab-", "dedicated": True, "borrowed_lanes": [f"{LAB.HOST}:{gi}"],
                   "borrowed_by": "DEBUG-RSI 窗口（总调度批）", "exp": e["name"]}
            dsrv = f"{LAB.SRV}/{e['name']}"
            r = rssh.run_retry(LAB.HOST, f"mkdir -p {dsrv} && cat > {dsrv}/ab_runner.json",
                               input=json.dumps(cfg, ensure_ascii=False).encode(), timeout=120)
            if r.returncode:
                raise RuntimeError(f"上传 ab_runner 配置失败 rc={r.returncode}")
            repo = HOSTS.server_root(LAB.HOST)   # 服务器仓库根目录（hosts.json）
            orig = LAB.ssh

            def ssh_ab(c, timeout=1800):
                if "setsid nohup" in c and "srv_run.py" in c:
                    c = (f"cd {repo} || exit 1; setsid nohup {LAB.SRV_PY} tools/director/ab_runner.py --config {dsrv}/ab_runner.json "
                         f"{dsrv} > {dsrv}/nohup.out 2>&1 < /dev/null & echo $! > {dsrv}/run.pid; cat {dsrv}/run.pid")
                return orig(c, timeout=timeout)
            LAB.ssh = ssh_ab
            LAB.export(e["name"], jobs, [], None)   # lane=None → 走 LANES_ENV 分支（命令整条被 ssh_ab 换掉）
            LAB.ssh = orig
        else:
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
