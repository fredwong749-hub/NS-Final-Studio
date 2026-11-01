"""VIDEO-RCA（fredw-2b 派，2026-11-01）：视频问题控制变量实验台。

一次只改一个因素（配方 / 提示词系统句 / seed / 尾帧），其余全部同生产：
  Shot Spec（data/import/script_v2.json）→ ns_recipes.compiler.compile_shot（同 build_jobs.compile_variant）→ ComfyUI 图
首帧 = 生产 jobs.json 该镜当前 first_frame（与 ep01_v2 / 夜间出片同一张）。

只用 gpu36:2 长镜头道（笔记本隧道 127.0.0.1:18290 → gpu36:8190），让道规则：
  提交前 /queue 必须为空（任何人的任务都算），且 longshot 模式 = normal（生产长镜头时为 long）→ 否则等；一次只挂 1 个。
出完：ssh gpu36 把成片拷到 /root/work/fredw/video_rca/<exp>/，在服务器上用生产同一个 score_clip.py（venv_idm）打分 +
tools/video_rca/sharp.py 测清晰度；拉回 score / 印样 / 预览 / 抽帧到 data/ab/video_rca/<exp>/。

    .venv/Scripts/python.exe tools/video_rca/lab.py plan <exp.json>     # 只编译，写 data/ab/video_rca/<exp>/jobs.json
    .venv/Scripts/python.exe tools/video_rca/lab.py run  <exp.json>     # 编译 + 逐个提交 + 打分（已完成的跳过）

exp.json：{"name": "...", "arms": [{"id": "S3_pika", "shot": "ep01-S3", "recipe": "i2va_pika_flex", "seed": 20261101,
           "overrides": {"prompt.eyeline_cue": ""}}, ...]}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/series10_video"))
import build_jobs as BJ  # noqa: E402  （同生产编译：sys.path、KITCHEN、preflight）

HOST = "gpu36"                        # r3：--host gpu33 时服务器端在 gpu33 本机跑
# r5：出图道由 producer 派单 → 默认“多道 + 连续空闲 ≥5 分钟才交”（srv_run VRCA_LANES / VRCA_IDLE_S）
LANES_ENV = "VRCA_LANES=8188:/root/work/fredw/comfy/output/gpu0,8189:/root/work/fredw/comfy/output/gpu1 VRCA_IDLE_S=300 "
PORT = 18290                         # gpu36:2
SRV = "/root/work/fredw/video_rca"   # 服务器上本 loop 的目录
SRV_REPO = "/root/work/fredw/video10_srv"
OUT_GPU2 = "/root/work/fredw/comfy/output/gpu2"
CLIENT = "videorca-"
AB = ROOT / "data/ab/video_rca"
JOBS = ROOT / "data/pipeline/runs/series10_v1/video/jobs.json"


def api(path, data=None, ctype="application/json", timeout=60):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


RSH = [sys.executable, str(ROOT / "tools/netfix/rsh.py")]   # NETFIX 11-02（K-OPS-N07/N08）：远程命令一律走常驻主连接


def ssh(cmd, timeout=1800):
    for k in range(4):
        r = subprocess.run([*RSH, HOST, cmd], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        if r.returncode != 255:
            return r
        time.sleep(10 * (k + 1))
    return r


def scp(src, dst, timeout=1800):
    """传文件（经 rsh.py 的 stdin / stdout 直通，不新开 scp 握手）：src 或 dst 之一写成 “gpu36:/path”"""
    src, dst = str(src), str(dst)
    for k in range(6):
        if dst.startswith(("gpu36:", "gpu33:")):
            host, path = dst.split(":", 1)
            with open(src if os.path.isabs(src) else ROOT / src, "rb") as f:
                r = subprocess.run([*RSH, host, f"mkdir -p $(dirname {path}) && cat > {path}"], stdin=f,
                                   capture_output=True, timeout=timeout)
        else:
            host, path = src.split(":", 1)
            r = subprocess.run([*RSH, host, f"cat {path}"], capture_output=True, timeout=timeout)
            if r.returncode == 0:
                out = Path(dst if os.path.isabs(dst) else ROOT / dst)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(r.stdout)
        if r.returncode == 0:
            return True
        time.sleep(10 * (k + 1))
    raise RuntimeError(f"传输失败 {src} -> {dst}: {r.stderr[-200:]}")


def log(exp, *a):
    line = time.strftime("%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(AB / exp / "lab.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def prod_first_frames() -> dict:
    d = json.loads(JOBS.read_text(encoding="utf-8"))
    return {s["shot"]: {"file": s["first_frame"], "meta": s} for s in d["shots"] if s.get("first_frame")}


def plan(exp: dict) -> list[dict]:
    from ns_recipes import registry as R
    reg = R.load()
    specs = BJ.load_specs(eps=sorted({int(a["shot"][2:4]) for a in exp["arms"]}))
    ffs = prod_first_frames()
    out = []
    for a in exp["arms"]:
        ff = {a["shot"]: {"file": a.get("first_frame") or (ffs.get(a["shot"]) or {}).get("file")}}
        if a.get("from_job"):      # 复用旧实验的编译稿（剧本重导入后镜头文本变了，仍要和旧臂严格同条件）
            src = next(x for x in json.loads((AB / a["from_job"][0] / "jobs_local.json").read_text(encoding="utf-8"))
                       if x["id"] == a["from_job"][1])
            v = json.loads(json.dumps({k: src[k] for k in ("graph", "prompt", "prompt_notes", "recipe", "seed")}))
            v.update({"mode": "i2va", "frames": src["score_meta"]["frames"],
                      "inputs": {"@first_frame": a["first_frame"]} if a.get("first_frame") else dict(src["inputs"]),
                      "plan_hash": None, "arm": a})
            if a.get("seed"):
                for n in v["graph"].values():
                    for k in ("noise_seed", "seed"):
                        if k in (n.get("inputs") or {}) and isinstance(n["inputs"][k], int):
                            n["inputs"][k] = int(a["seed"])
                v["seed"] = int(a["seed"])
        else:
            spec = specs[a["shot"]]
            v = BJ.compile_variant(spec, reg, a["recipe"], a.get("attempt", 1), a["id"], ff, seed=a.get("seed"),
                                   extra=a.get("overrides") or {})
        if "graph" not in v:
            raise SystemExit(f"{a['id']} 编译失败：{v}")
        if a.get("hide_size"):      # 对复用的旧编译稿按生产函数 hide_offframe_parts 处理正文（K-REN-701 的同条件 A/B）
            from ns_recipes.prompt import hide_offframe_parts
            head, _, rest = v["prompt"].partition("integrated_multimodal_description: ")
            body, _, tail = rest.partition(chr(10) + chr(10) + "overall_soundscape:")
            nb, gone = hide_offframe_parts(body, a["hide_size"])
            a = {**a, "prompt_replace": [[body, nb]] + list(a.get("prompt_replace") or [])} if gone else a
            v["arm"] = a
            if not gone:
                raise SystemExit(f"{a['id']}：hide_offframe_parts 没删任何分句")
        for o, nw in a.get("prompt_replace") or []:      # 诊断用（只在 scope=ab 实验里）：证明机理，不进生产编译
            if o not in v["prompt"]:
                raise SystemExit(f"{a['id']}：提示词里没有 {o!r}")
            v["prompt"] = v["prompt"].replace(o, nw)
            for n in v["graph"].values():
                if isinstance((n.get("inputs") or {}).get("prompt"), str):
                    n["inputs"]["prompt"] = n["inputs"]["prompt"].replace(o, nw)
            v["prompt_notes"] = v["prompt_notes"] + [f"诊断替换：{o} → {nw}"]
        meta = (ffs.get(a["shot"]) or {}).get("meta") or {}
        if a.get("from_job"):
            v.update({"arm": a, "shot": a["shot"], "score_meta": {**src["score_meta"], "prompt": v["prompt"]}})
            out.append(v)
            continue
        v.update({"arm": a, "shot": a["shot"], "score_meta": {
            "refs": meta.get("score_refs") or {}, "prompt": v["prompt"], "frames": v["frames"], "size": meta.get("size"),
            "first_frame": ff[a["shot"]]["file"]}})
        out.append(v)
    return out


def lane_free() -> tuple[bool, str]:
    d = json.loads(api("/queue", timeout=20))
    n = len(d["queue_running"]) + len(d["queue_pending"])
    if n:
        return False, f"gpu36:2 队列有 {n} 个任务"
    r = ssh("cat /root/work/fredw/longshot/run/mode 2>/dev/null", timeout=60)
    mode = (r.stdout or "").strip() or "normal"
    if mode != "normal":
        return False, f"longshot 模式 {mode}（生产长镜头）"
    return True, ""


def upload(rel: str) -> str:
    p = ROOT / rel
    b = "----rca" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"rca_{p.name}\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + p.read_bytes() + \
        (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nvideo_rca\r\n"
         f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
    r = json.loads(api("/upload/image", body, f"multipart/form-data; boundary={b}", timeout=300))
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


def submit(v: dict, exp: str) -> str:
    g = json.loads(json.dumps(v["graph"]))
    for n in g.values():
        for k, x in list((n.get("inputs") or {}).items()):
            if isinstance(x, str) and x.startswith("@"):
                n["inputs"][k] = upload(v["inputs"][x])
        if n["class_type"] == "SaveVideo":
            n["inputs"]["filename_prefix"] = f"video_rca/{exp}/{v['arm']['id']}"
    body = {"prompt": g, "client_id": CLIENT + uuid.uuid4().hex[:8],
            "extra_data": {"ns_tag": {"agent": "VIDEO-RCA", "kind": "video", "v": 1, "label": f"实验 {exp}/{v['arm']['id']}",
                                      "t": round(time.time(), 1)}}}
    r = json.loads(api("/prompt", json.dumps(body).encode(), timeout=120))
    if r.get("node_errors"):
        raise RuntimeError(json.dumps(r["node_errors"], ensure_ascii=False)[:600])
    return r["prompt_id"]


def result(pid):
    h = json.loads(api(f"/history/{pid}", timeout=30))
    if pid not in h:
        return None
    st = h[pid].get("status", {})
    t0 = t1 = None
    for m in st.get("messages") or []:
        if m[0] == "execution_start":
            t0 = m[1].get("timestamp")
        if m[0] in ("execution_success", "execution_error", "execution_interrupted"):
            t1 = m[1].get("timestamp")
    gpu_s = round((t1 - t0) / 1000.0, 1) if t0 and t1 else None
    if st.get("status_str") == "error":
        return {"error": json.dumps(st.get("messages"), ensure_ascii=False)[-600:], "gpu_s": gpu_s}
    for node in h[pid].get("outputs", {}).values():
        for key in ("images", "videos", "gifs"):
            for im in node.get(key, []) or []:
                if str(im.get("filename", "")).endswith(".mp4"):
                    return {"path": "/".join(x for x in (OUT_GPU2, im.get("subfolder"), im["filename"]) if x), "gpu_s": gpu_s}
    return {"error": "no_output", "gpu_s": gpu_s} if st.get("completed") else None


def score_remote(exp: str, v: dict, src: str) -> dict:
    arm = v["arm"]["id"]
    stem = f"{v['shot']}__rca_{arm}"
    d = f"{SRV}/{exp}"
    meta = json.dumps(v["score_meta"], ensure_ascii=False).replace("'", "'\"'\"'")
    cmd = (f"mkdir -p {d} && cp {src} {d}/{stem}.mp4 && cd {SRV_REPO} || exit 1; "
           f"export PATH=/root/work/fredw/tools_bin:$PATH OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 PYTHONUTF8=1; "
           f"nice -n 10 /root/work/fredw/venv_idm/bin/python tools/series10_video/score_clip.py {d}/{stem}.mp4 {d}/{stem}_sheet.jpg "
           f"'{meta}' > {d}/{stem}.score.txt 2> {d}/{stem}.score.err; "
           f"nice -n 10 /root/work/fredw/venv_idm/bin/python {SRV}/sharp.py {d}/{stem}.mp4 > {d}/{stem}.sharp.json 2>> {d}/{stem}.score.err; "
           f"/root/work/fredw/tools_bin/ffmpeg -v error -y -i {d}/{stem}.mp4 -vf scale=360:640 -c:v libx264 -crf 28 -c:a aac -b:a 64k "
           f"{d}/{stem}_prev.mp4; "
           f"/root/work/fredw/tools_bin/ffmpeg -v error -y -i {d}/{stem}.mp4 -vf \"select='eq(n,0)+eq(n,12)+eq(n,48)+eq(n,96)+eq(n,150)',scale=384:672,tile=5x1\" "
           f"-frames:v 1 {d}/{stem}_strip.jpg; echo OK")
    r = ssh(cmd, timeout=2400)
    loc = AB / exp
    for suf in ("_sheet.jpg", "_prev.mp4", "_strip.jpg", ".score.txt", ".sharp.json", ".score.err"):
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"gpu36:{d}/{stem}{suf}", str(loc / f"{stem}{suf}")],
                       capture_output=True, timeout=600)
    s = {}
    try:
        ln = [x for x in (loc / f"{stem}.score.txt").read_text(encoding="utf-8").splitlines() if x.startswith("{")]
        s = json.loads(ln[-1]) if ln else {"error": "无打分输出"}
    except OSError as e:
        s = {"error": str(e)}
    try:
        s["sharp"] = json.loads((loc / f"{stem}.sharp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s["sharp"] = {"error": "未测"}
    s["_ssh_rc"] = r.returncode
    return s


def run(exp_p: Path):
    exp = json.loads(exp_p.read_text(encoding="utf-8"))
    name = exp["name"]
    (AB / name).mkdir(parents=True, exist_ok=True)
    # sharp.py 推到服务器（小文件）
    ssh(f"mkdir -p {SRV}", timeout=60)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(ROOT / "tools/video_rca/sharp.py"), f"gpu36:{SRV}/sharp.py"],
                   check=False, timeout=300)
    vs = plan(exp)
    res_p = AB / name / "results.json"
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else {}
    jobs_p = AB / name / "jobs.json"
    jobs_p.write_text(json.dumps([{k: v[k] for k in ("arm", "shot", "recipe", "mode", "seed", "frames", "prompt",
                                                     "prompt_notes", "inputs", "plan_hash", "graph")} for v in vs],
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    for v in vs:
        arm = v["arm"]["id"]
        if res.get(arm, {}).get("score") and not res[arm]["score"].get("error"):
            continue
        while True:
            ok, why = lane_free()
            if ok:
                break
            log(name, "让道：", why)
            time.sleep(120)
        pid = submit(v, name)
        log(name, "SUBMIT", arm, v["recipe"], v["seed"], pid)
        t0 = time.time()
        while True:
            time.sleep(20)
            try:
                r = result(pid)
            except Exception as e:  # noqa: BLE001
                log(name, "poll err", e)
                r = None
            if r:
                break
            if time.time() - t0 > 3 * 3600:
                r = {"error": "超时"}
                break
        log(name, "DONE", arm, json.dumps(r, ensure_ascii=False)[:300])
        rec = {"recipe": v["recipe"], "seed": v["seed"], "shot": v["shot"], "overrides": v["arm"].get("overrides"),
               "gen": r, "prompt_notes": v["prompt_notes"]}
        if r.get("path"):
            rec["score"] = score_remote(name, v, r["path"])
            sc = rec["score"]
            log(name, "SCORE", arm, json.dumps({k: sc.get(k) for k in ("mean", "J4", "cheek_red_max", "face_h_med", "size_measured")}
                                               | {"gate": (sc.get("gate") or {}).get("fails"),
                                                  "v6": (sc.get("v6") or {}).get("hands_max"),
                                                  "acting": {k: (sc.get("acting") or {}).get(k, {}).get("status")
                                                             for k in ("first_sec", "camera_gaze")},
                                                  "sharp": (sc.get("sharp") or {}).get("ratio_mid")}, ensure_ascii=False))
        res[arm] = rec
        res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def export(name: str, jobs: list[dict], adopt: list[str] | None = None, lane: int | None = None):
    """服务器端执行（隧道不稳时的正路）：jobs → data/ab/video_rca/<exp>/srv/（jobs.json + inputs/）→ scp → nohup srv_run.py"""
    import shutil
    loc = AB / name / "srv"
    (loc / "inputs").mkdir(parents=True, exist_ok=True)
    srv_cp = []
    for j in jobs:
        for k, rel in list(j["inputs"].items()):
            if str(rel).startswith("/root/"):        # 服务器上已有的图（如出图 A/B 的结果）：服务器端复制，不经笔记本
                srv_cp.append((rel, Path(rel).name))
                j["inputs"][k] = Path(rel).name
                continue
            src = ROOT / rel
            shutil.copy2(src, loc / "inputs" / src.name)
            j["inputs"][k] = src.name
        if "@first_frame" in j["inputs"] and "score_meta" in j:
            j["score_meta"]["first_frame"] = f"{SRV}/{name}/inputs/{j['inputs']['@first_frame']}"
    (loc / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    d = f"{SRV}/{name}"
    ssh(f"mkdir -p {d}/inputs", timeout=60)
    for f in (ROOT / "tools/video_rca/srv_run.py", ROOT / "tools/video_rca/sharp.py"):
        scp(str(f), f"{HOST}:{SRV}/{f.name}")
    scp(str(loc / "jobs.json"), f"{HOST}:{d}/jobs.json")
    for src, nm in srv_cp:
        ssh(f"cp {src} {d}/inputs/{nm}", timeout=120)
    have = set((ssh(f"ls {d}/inputs", timeout=60).stdout or "").split())
    for f in (loc / "inputs").iterdir():
        if f.name not in have:
            scp(str(f), f"{HOST}:{d}/inputs/{f.name}")
    ad = " ".join(adopt or [])
    if lane is None and LANES_ENV:
        envp = LANES_ENV
    elif HOST == "gpu33":
        envp = (f"VRCA_PORT={lane} VRCA_OUT=/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu{ {8188: 0, 8189: 1, 8191: 3}[lane] } "
                "VRCA_FF=/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin/ffmpeg ")
    else:
        envp = f"VRCA_PORT={lane} VRCA_OUT=/root/work/fredw/comfy/output/gpu{ {8188: 0, 8189: 1, 8190: 2}[lane] } " if lane else ""
    r = ssh(f"cd {SRV} || exit 1; {envp}setsid nohup {SRV_PY} {SRV}/srv_run.py {d} {ad} > {d}/nohup.out 2>&1 < /dev/null & echo $! > {d}/run.pid; cat {d}/run.pid",
            timeout=120)
    print("started pid", r.stdout.strip())


def pull(name: str):
    d = f"{SRV}/{name}"
    loc = AB / name
    loc.mkdir(parents=True, exist_ok=True)
    have = {f.name for f in loc.iterdir()}
    ls = (ssh(f"cd {d} && ls", timeout=60).stdout or "").split()
    want = [f for f in ls if f.endswith((".json", ".jpg", ".png", ".txt", ".log", "_prev.mp4", ".err"))
            and (f not in have or f in ("results.json", "run.log"))]
    for f in want:
        try:
            scp(f"{HOST}:{d}/{f}", loc / f, timeout=900)
        except RuntimeError as e:
            print(e)
    print(f"pulled {len(want)}")


SRV_PY = "/root/work/fredw/venv_idm/bin/python"


if __name__ == "__main__":
    cmd, p = sys.argv[1], Path(sys.argv[2])
    if "--host" in sys.argv:
        HOST = sys.argv[sys.argv.index("--host") + 1]
        k = sys.argv.index("--host")
        del sys.argv[k:k + 2]
    if cmd == "export":
        e = json.loads(p.read_text(encoding="utf-8"))
        vs = plan(e)
        jobs = [{"id": v["arm"]["id"], "shot": v["shot"], "recipe": v["recipe"], "seed": v["seed"], "kind": "video",
                 "v67_meta": v["arm"].get("v67_meta") or e.get("v67_meta", {}).get(v["shot"]),
                 "graph": v["graph"], "inputs": dict(v["inputs"]), "score_meta": {**v["score_meta"],
                 "first_frame": None}, "prompt": v["prompt"], "prompt_notes": v["prompt_notes"],
                 "overrides": v["arm"].get("overrides")} for v in vs]
        (AB / e["name"]).mkdir(parents=True, exist_ok=True)
        (AB / e["name"] / "jobs_local.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
        lane = int(sys.argv[sys.argv.index("--lane") + 1]) if "--lane" in sys.argv else None
        rest = [x for i, x in enumerate(sys.argv[3:]) if x != "--lane" and (i == 0 or sys.argv[3:][i - 1] != "--lane")]
        export(e["name"], jobs, rest, lane)
        raise SystemExit(0)
    if cmd == "pull":
        pull(p.name if not p.suffix else json.loads(p.read_text(encoding="utf-8"))["name"])
        raise SystemExit(0)
    if cmd == "plan":
        e = json.loads(p.read_text(encoding="utf-8"))
        for v in plan(e):
            print(v["arm"]["id"], v["recipe"], v["mode"], v["seed"], v["frames"], v["prompt_notes"])
    else:
        run(p)
