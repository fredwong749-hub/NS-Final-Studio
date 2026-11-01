"""VIDEO-RCA 服务器端实验执行器（在 gpu36 本机跑，不依赖笔记本隧道；笔记本只负责编译和取回）。

目录：/root/work/fredw/video_rca/<exp>/  jobs.json（lab.py export 写：每臂 graph + inputs 文件名 + score_meta）、inputs/、
      results.json、run.log、<镜>__rca_<臂>.mp4 / _sheet.jpg / _strip.jpg / _prev.mp4 / .score.txt / .sharp.json
让道（生产优先）：提交前 gpu36:2（:8190）队列必须为空，且 longshot 模式 = normal；一次只挂 1 个。
图片臂（kind=image）：输出 PNG 拷到实验目录。

    nohup /root/work/fredw/venv_idm/bin/python srv_run.py <exp_dir> [adopt_arm=prompt_id ...] &
"""
import concurrent.futures as cf
import json
import os
import threading
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

# r3（总调度 22:05）：空档可用 gpu36 三道；VRCA_PORT / VRCA_OUT 指定道（默认 gpu36:2 长镜头道）
PORT = int(os.environ.get("VRCA_PORT", "8190"))
OUT = os.environ.get("VRCA_OUT", "/root/work/fredw/comfy/output/gpu2")
PROD_JOBS = Path("/root/work/fredw/video10_srv/data/pipeline/runs/series10_v1/video/jobs.json")
REPO = "/root/work/fredw/video10_srv"
PY = "/root/work/fredw/venv_idm/bin/python"
FF = os.environ.get("VRCA_FF", "/root/work/fredw/tools_bin/ffmpeg")
MODE = Path("/root/work/fredw/longshot/run/mode")
CLIENT = "videorca-"
# 总调度 11-02 00:3x：服务器上的分析一律限线程 + nice（v7_lipsync 曾占 74–90 核拖垮 sshd）→ 所有子进程绑 4 个核（taskset，子孙进程继承）
CORES = os.environ.get("VRCA_CORES", "44-47")
LIMIT = ["taskset", "-c", CORES, "nice", "-n", "15"]
THREAD_ENV = {k: "4" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                               "ORT_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}
lock = threading.Lock()
pool = cf.ThreadPoolExecutor(max_workers=2)


def api(path, data=None, ctype="application/json", timeout=60):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def log(d, *a):
    line = time.strftime("%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(d / "run.log", "a") as f:
        f.write(line + "\n")


def prod_ready() -> bool:
    """生产有可派的 Pika 变体（jobs.json 任一镜 variants 里 status=ready）→ 非长镜头道立即退让（总调度 22:05 规则）"""
    try:
        d = json.loads(PROD_JOBS.read_text())
        return any((v or {}).get("status") == "ready" for s in d.get("shots", []) for v in (s.get("variants") or {}).values())
    except Exception:  # noqa: BLE001
        return False


def lane_free():
    if PORT != 8190 and prod_ready():
        return False, "生产有 ready 变体：非 gpu36:2 道退让"
    q = json.loads(api("/queue", timeout=20))
    n = len(q["queue_running"]) + len(q["queue_pending"])
    if n:
        return False, f"队列 {n}"
    m = MODE.read_text().strip() if MODE.exists() else "normal"
    return (m == "normal"), f"longshot {m}"


def upload(p: Path, mime):
    b = "----rca" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"rca_{p.name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + p.read_bytes() + \
        (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nvideo_rca\r\n"
         f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n").encode()
    r = json.loads(api("/upload/image", body, f"multipart/form-data; boundary={b}", timeout=300))
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


def submit(d, exp, j):
    g = json.loads(json.dumps(j["graph"]))
    for n in g.values():
        for k, v in list((n.get("inputs") or {}).items()):
            if isinstance(v, str) and v.startswith("@"):
                fn = j["inputs"][v]
                n["inputs"][k] = upload(d / "inputs" / fn, "image/png" if fn.endswith(".png") else "image/jpeg")
        if n["class_type"] in ("SaveVideo", "SaveImage"):
            n["inputs"]["filename_prefix"] = f"video_rca/{exp}/{j['id']}"
    body = {"prompt": g, "client_id": CLIENT + uuid.uuid4().hex[:8],
            "extra_data": {"ns_tag": {"agent": "VIDEO-RCA", "kind": j.get("kind", "video"), "v": 1,
                                      "label": f"实验 {exp}/{j['id']}", "t": round(time.time(), 1)}}}
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
                return {"path": "/".join(x for x in (OUT, im.get("subfolder"), im["filename"]) if x), "gpu_s": gpu_s}
    return {"error": "no_output", "gpu_s": gpu_s} if st.get("completed") else None


def score(d, j, src):
    stem = f"{j['shot']}__rca_{j['id']}"
    mp4 = d / f"{stem}.mp4"
    subprocess.run(["cp", src, str(mp4)])
    env = dict(os.environ, PATH=str(Path(FF).parent) + ":" + os.environ.get("PATH", ""), PYTHONUTF8="1", **THREAD_ENV)
    r = subprocess.run([*LIMIT, PY, f"{REPO}/tools/series10_video/score_clip.py", str(mp4), str(d / f"{stem}_sheet.jpg"),
                        json.dumps(j["score_meta"], ensure_ascii=False)], capture_output=True, text=True, env=env, cwd=REPO,
                       timeout=2400)
    (d / f"{stem}.score.txt").write_text(r.stdout)
    (d / f"{stem}.score.err").write_text(r.stderr[-4000:])
    ff = d / "inputs" / j["inputs"].get("@first_frame", "none")
    r2 = subprocess.run([*LIMIT, PY, str(Path(__file__).parent / "sharp.py"), str(mp4)] + ([str(ff)] if ff.exists() else []),
                        capture_output=True, text=True, timeout=600)
    (d / f"{stem}.sharp.json").write_text(r2.stdout)
    subprocess.run([*LIMIT, FF, "-v", "error", "-threads", "4", "-y", "-i", str(mp4), "-vf", "scale=360:640", "-c:v", "libx264", "-crf", "28", "-c:a", "aac",
                    "-b:a", "64k", str(d / f"{stem}_prev.mp4")])
    sel = "+".join(f"eq(n\\,{i})" for i in (0, 12, 48, 96, 150))
    subprocess.run([*LIMIT, FF, "-v", "error", "-threads", "4", "-y", "-i", str(mp4), "-vf", f"select='{sel}',scale=384:672,tile=5x1", "-frames:v", "1",
                    str(d / f"{stem}_strip.jpg")])
    s = {}
    ln = [x for x in r.stdout.splitlines() if x.startswith("{")]
    s = json.loads(ln[-1]) if ln else {"error": r.stderr[-500:]}
    if j.get("v67_meta") and not s.get("error"):
        # 剧本 18:24 重导入后镜号变了（旧 S4 = 新 S5…），score_clip 按镜号读 jobs.json 会拿错人数 / 对白 →
        # 用实验自带的旧镜头信息重跑 V6 / V7（同生产脚本、同阈值），并按新结果改 gate 的 多肢 / 口型 两项
        for key, py, script in (("v6", "/root/work/fredw/venv_hand/bin/python", "v6_limbs.py"),
                                ("v7", PY, "v7_lipsync.py")):
            rr = subprocess.run([*LIMIT, py, f"{REPO}/tools/series10_video/{script}", str(mp4),
                                 json.dumps(j["v67_meta"], ensure_ascii=False)], capture_output=True, text=True, env=env,
                                cwd=REPO, timeout=1800)
            l2 = [x for x in rr.stdout.splitlines() if x.startswith("{")]
            if l2:
                s.update(json.loads(l2[-1]))
        g = s.get("gate") or {}
        f = [x for x in g.get("fails") or [] if x not in ("多肢", "口型不合")]
        if (s.get("v6") or {}).get("status") == "不通过":
            f.append("多肢")
        if (s.get("v7") or {}).get("status") == "不通过":
            f.append("口型不合")
        s["gate"] = {**g, "fails": f, "pass": not f, "v67_meta": "实验自带（旧镜号）"}
    try:
        s["sharp"] = json.loads(r2.stdout)
    except ValueError:
        s["sharp"] = {"error": r2.stderr[-300:]}
    return s


def main(d, adopt):
    d = Path(d)
    exp = d.name
    jobs = json.loads((d / "jobs.json").read_text())
    res_p = d / "results.json"
    res = json.loads(res_p.read_text()) if res_p.exists() else {}
    futs = []
    for j in jobs:
        a = j["id"]
        if res.get(a, {}).get("done"):
            continue
        if a in adopt:
            pid = adopt[a]
            log(d, "ADOPT", a, pid)
        else:
            while True:
                try:
                    ok, why = lane_free()
                except Exception as e:  # noqa: BLE001
                    ok, why = False, str(e)
                if ok:
                    break
                log(d, "让道", why)
                time.sleep(90)
            pid = submit(d, exp, j)
            log(d, "SUBMIT", a, j.get("recipe"), j.get("seed"), pid)
        t0 = time.time()
        while True:
            time.sleep(15)
            try:
                r = result(pid)
            except Exception as e:  # noqa: BLE001
                log(d, "poll err", e)
                r = None
            if r:
                break
            if time.time() - t0 > 3 * 3600:
                r = {"error": "超时"}
                break
        log(d, "DONE", a, json.dumps(r)[:300])
        rec = {"id": a, "gen": r, "done": True, "recipe": j.get("recipe"), "seed": j.get("seed"), "shot": j["shot"],
               "kind": j.get("kind", "video")}
        if r.get("path") and rec["kind"] == "image":
            subprocess.run(["cp", r["path"], str(d / f"{a}.png")])
            rec["file"] = f"{a}.png"
        with lock:
            res[a] = rec
            res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        if r.get("path") and rec["kind"] != "image":   # 打分放后台线程，GPU 不等打分（VLM 复核最长 600 s）
            futs.append(pool.submit(score_bg, d, j, r["path"], a, res, res_p))
    for f in futs:
        f.result()
    log(d, "ALL_DONE")


def score_bg(d, j, path, a, res, res_p):
    try:
        sc = score(d, j, path)
    except Exception as e:  # noqa: BLE001
        sc = {"error": f"打分失败 {e}"}
    log(d, "SCORE", a, json.dumps({k: sc.get(k) for k in ("mean", "J4", "cheek_red_max", "face_h_med")}
                                  | {"fails": (sc.get("gate") or {}).get("fails"),
                                     "hands": (sc.get("v6") or {}).get("hands_max"),
                                     "sharp": (sc.get("sharp") or {}).get("ratio_mid")}, ensure_ascii=False))
    with lock:
        res[a]["score"] = sc
        res[a]["scored"] = True
        res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], dict(x.split("=", 1) for x in sys.argv[2:]))
