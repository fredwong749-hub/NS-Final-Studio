"""postflight 的远端测量（Q1 身份 / Q3 景别 / Q6 文字 / Q5 坏手）：在出图那台机器上原地跑（K-OPS-122）。

    from remote_score import score
    m = score("gpu33", {"<id>": "<机器上的 png 绝对路径>", ...})        # 出图机器上的 ComfyUI 输出路径
    m["items"][id] → postflight 的 remote；m["hands"][id] → hands；m["cross"] → cross
本机文件（没有机器路径）用 score_local_files(host, {id: 本地 png})：先 scp 到 /root/work/fredw/imggen/in/<批>/ 再打分。
参考名 = 角色 id；身份脸 = asset_refs.face_of（与出图同一张，见 face_refs）。
"""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path

R = "/root/work/fredw/imggen"
IDM = "/root/work/fredw/venv_idm/bin/python"
HAND = "/root/work/fredw/venv_hand/bin/python"
# 身份脸：出图用哪张、打分就对哪张（BAKEOFF P1 11-01：每个角色只有一张身份脸）。不再手写机器路径——由 asset_refs.face_of
# （资产中心“设为当前身份脸”覆盖 > config/recipes/asset_refs.json faces）解析出本机文件，按内容哈希放到机器上 refs/id_<sha16>.png。
# 原来的 lin_wan@master（10-31 旧母版裁切）作废：总调度 P0 已把林晚改回 A-s202 face_ref2va，打分再对旧母版取高者会放过不像的图。
FACE_CHARS = ("lin_wan", "gu_chen", "chen_yu", "ch_a_lan")
FACE_PROJECT = "series10_v1"


def local_faces(project: str = FACE_PROJECT) -> dict[str, str]:
    """{角色 id: 出图用的身份脸（仓库相对路径）}——与 asset_refs.plan_for 同一个函数解析"""
    import sys as _s
    root = Path(__file__).resolve().parents[2]
    if str(root / "services/agent") not in _s.path:
        _s.path.insert(0, str(root / "services/agent"))
    from ns_agent import asset_refs as AR
    out = {}
    for cid in FACE_CHARS:
        f = AR.face_of(project, cid)
        if f:
            out[cid] = f
    return out


_FACE_UP = r'''
import base64, json, os, sys
d = sys.argv[1]
os.makedirs(d, exist_ok=True)
for k, v in json.load(sys.stdin).items():
    p = os.path.join(d, "id_" + k + ".png")
    os.path.exists(p) or open(p, "wb").write(base64.b64decode(v))
print("ok")
'''


def face_refs(host: str, project: str = FACE_PROJECT) -> dict[str, str]:
    """{角色 id: 机器上的身份脸路径}；机器上没有的先传上去（一次 ssh，之后按哈希记在本机已知清单里不再传）"""
    import base64
    root = Path(__file__).resolve().parents[2]
    faces = {cid: (f, _sha16(root / f)) for cid, f in local_faces(project).items()}
    kp = _known_path(host)
    try:
        known = set(json.loads(kp.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        known = set()
    miss = {sha: f for f, sha in faces.values() if "id_" + sha not in known}
    if miss:
        up = {sha: base64.b64encode((root / f).read_bytes()).decode() for sha, f in miss.items()}
        code = _FACE_UP
        r = ssh(host, f'python3 -c "$(echo {base64.b64encode(code.encode()).decode()} | base64 -d)" {R}/refs', json.dumps(up), timeout=600)
        if "ok" not in (r.stdout or ""):
            raise RuntimeError(f"身份脸上传 {host} 失败：" + (r.stderr or "")[-300:])
        known |= {"id_" + sha for sha in miss}
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_text(json.dumps(sorted(known)), encoding="utf-8")
    return {cid: f"{R}/refs/id_{sha}.png" for cid, (_f, sha) in faces.items()}


def ssh(host, cmd, stdin=None, timeout=900):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd], capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", input=stdin)


def score(host: str, paths: dict[str, str]) -> dict:
    items = [{"id": k, "path": v} for k, v in paths.items()]
    refs = {k: [v] for k, v in face_refs(host).items()}
    r = ssh(host, f"cd {R} && {IDM} score_remote.py - 2>/dev/null", json.dumps({"refs": refs, "items": items}, ensure_ascii=False))
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        raise RuntimeError(f"score_remote@{host}: " + r.stderr[-400:])
    d = json.loads(out[-1])
    for it in d.get("items", {}).values():
        for f in it.get("faces", []):
            f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(d["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = ssh(host, f"cd {R} && {HAND} hands_remote.py 2>/dev/null", json.dumps({"items": hi}))
    ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
    return {"items": d.get("items", {}), "cross": d.get("cross", {}), "hands": json.loads(ho[-1]) if ho else {},
            "refs": list(refs)}


# IMGPERF（11-01）：原 score_local_files = mkdir / scp / ls / score / hands / rm 六次独立 ssh（每次经跳板握手 10–13 s，
# scp 1.3 MB 60 s），实测 130 s。改成一次 ssh：图片 base64 走 stdin，远端一个小脚本落盘 → 打分 → 手 → 删目录 → 打一行 JSON。
_ONE_SHOT = r'''
import base64, json, os, shutil, subprocess, sys
R, IDM, HAND = sys.argv[1], sys.argv[2], sys.argv[3]
req = json.load(sys.stdin)
d = os.path.join(R, "in", req["batch"]); os.makedirs(d, exist_ok=True)
try:
    items = []
    for k, (name, b64) in req["files"].items():
        p = os.path.join(d, name)
        open(p, "wb").write(base64.b64decode(b64))
        items.append({"id": k, "path": p})
    refs = {k: [v] for k, v in req["refs"].items() if os.path.exists(v)}
    r = subprocess.run([IDM, "score_remote.py", "-"], cwd=R, input=json.dumps({"refs": refs, "items": items}),
                       capture_output=True, text=True)
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        print(json.dumps({"error": "score_remote: " + r.stderr[-400:]})); sys.exit(0)
    s = json.loads(out[-1])
    for it in s.get("items", {}).values():
        for f in it.get("faces", []):
            f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(s["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = subprocess.run([HAND, "hands_remote.py"], cwd=R, input=json.dumps({"items": hi}), capture_output=True, text=True)
    ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
    print(json.dumps({"items": s.get("items", {}), "cross": s.get("cross", {}),
                      "hands": json.loads(ho[-1]) if ho else {}, "refs": list(refs)}))
finally:
    shutil.rmtree(d, ignore_errors=True)
'''


def score_local_files(host: str, files: dict[str, str | Path], timeout: float = 900) -> dict:
    """本机图 → 出图机器原地打分：一次 ssh 往返（见 _ONE_SHOT）"""
    import base64
    b = "pf_" + time.strftime("%H%M%S") + uuid.uuid4().hex[:4]
    payload = {"batch": b, "refs": face_refs(host),
               "files": {k: [Path(p).name, base64.b64encode(Path(p).read_bytes()).decode()] for k, p in files.items()}}
    code = base64.b64encode(_ONE_SHOT.encode()).decode()
    cmd = f'python3 -c "$(echo {code} | base64 -d)" {R} {IDM} {HAND}'
    r = ssh(host, cmd, json.dumps(payload), timeout=timeout)
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        raise RuntimeError(f"score_local_files@{host}: " + (r.stderr or "")[-400:])
    d = json.loads(out[-1])
    if d.get("error"):
        raise RuntimeError(d["error"])
    return d


def score_local_files_legacy(host: str, files: dict[str, str | Path]) -> dict:
    """旧实现（六次 ssh + scp，约 130 s）：只留作对照"""
    b = "pf_" + time.strftime("%H%M%S") + uuid.uuid4().hex[:4]
    ssh(host, f"mkdir -p {R}/in/{b}")
    remote = {}
    for k, p in files.items():
        dst = f"{R}/in/{b}/{Path(p).name}"
        r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(p), f"{host}:{dst}"], capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise RuntimeError("scp " + r.stderr[-300:])
        remote[k] = dst
    try:
        return score(host, remote)
    finally:
        ssh(host, f"rm -rf {R}/in/{b}")


# ---------------------------------------------------------------- REFLOCK 11-01：Q2 / Q4 / Q7 也在出图机器上算（GPU）
# 一次 ssh：身份 / 景别 / 文字（score_remote）+ 手（hands_remote）+ 造型 / 质感 / 场景（clip_srv.py，CLIP 在 gpu33 GPU 上）。
# 度量代码 = ns_agent/gen_contract/metrics.py（与笔记本 postflight 同一份，每次随请求下发，保证口径一致）。
# 参考图按内容哈希缓存在机器上（/root/work/fredw/reflock/refs/<sha16>.png）；本机记一份“已在机器上”的清单，缺了机器会报 missing_refs，
# 自动补传一次。
RL = "/root/work/fredw/reflock"
COMFY_PY = "/root/claude-kimi-ns-studio-v1/env/comfy/bin/python"
GPU_EXCLUDE = {"2"}            # gpu33 GPU2 坏（imggen 记录），不用
CLIP_MIN_FREE_MB = 8000        # 卡上空闲显存不到这个数就不放 CLIP（ComfyUI 出图时显存会再涨）；OOM 时 clip_srv 等 20 s 重试一次，再不行 CPU 子进程

_FULL = r'''
import base64, json, os, shutil, subprocess, sys
R, IDM, HAND, RL, CPY, EXCL, MINFREE = sys.argv[1:8]
req = json.load(sys.stdin)
os.makedirs(os.path.join(RL, "refs"), exist_ok=True)
for name, b64 in (req.get("code") or {}).items():
    open(os.path.join(RL, name), "wb").write(base64.b64decode(b64))
for sha, b64 in (req.get("refs_b64") or {}).items():
    open(os.path.join(RL, "refs", sha + ".png"), "wb").write(base64.b64decode(b64))
d = os.path.join(R, "in", req["batch"]); os.makedirs(d, exist_ok=True)
res = {}
try:
    items = []
    for it in req["items"]:
        p = it.get("host_path")
        if not p:
            p = os.path.join(d, it["id"].replace("/", "_").replace(":", "_") + ".png")
            open(p, "wb").write(base64.b64decode(it["b64"]))
        items.append({"id": it["id"], "path": p})
    refs = {k: [v] for k, v in req["face_refs"].items() if os.path.exists(v)}
    r = subprocess.run([IDM, "score_remote.py", "-"], cwd=R, input=json.dumps({"refs": refs, "items": items}), capture_output=True, text=True)
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    s = json.loads(out[-1]) if out else {"items": {}, "cross": {}, "error": "score_remote: " + r.stderr[-300:]}
    for it in s.get("items", {}).values():
        for f in it.get("faces", []):
            f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(s["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = subprocess.run([HAND, "hands_remote.py"], cwd=R, input=json.dumps({"items": hi}), capture_output=True, text=True)
    ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
    res = {"items": s.get("items", {}), "cross": s.get("cross", {}), "hands": json.loads(ho[-1]) if ho else {},
           "refs": list(refs), "score_error": s.get("error")}
    clip_items = []
    by = {i["id"]: i["path"] for i in items}
    for it in req["items"]:
        sc = s.get("items", {}).get(it["id"]) or {}
        fb = None
        if sc.get("faces"):
            lw = sorted(sc["faces"], key=lambda f: -((f.get("sims") or {}).get("lin_wan", -1)))
            fb = list(lw[0]["bbox"])
            post = it.get("post") or {}
            if post.get("size") and sc.get("size"):
                k = post["size"][0] / sc["size"][0]
                fb = [v * k for v in fb]
                for f in sc["faces"]:
                    f["bbox"] = [v * k for v in f["bbox"]]
        outer = []
        for o in it.get("outer") or []:          # 每个角色自己的脸框（总调度 11-01：外层单品查全部在画角色）——像这个角色 ≥0.3 的最像那张脸
            cand = [f for f in sc.get("faces") or [] if ((f.get("sims") or {}).get(o.get("character")) or -1) >= 0.3]
            best = max(cand, key=lambda f: f["sims"][o["character"]], default=None)
            outer.append({**o, "face_bbox": list(best["bbox"]) if best else None})
        clip_items.append({"id": it["id"], "path": by[it["id"]], "post": it.get("post"), "rows": it.get("rows") or [],
                           "face_bbox": fb, "scene": it.get("scene"), "outer": outer})
    q = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True)
    gpus = []
    for ln in q.stdout.strip().splitlines():
        if "," in ln:
            i, f = [x.strip() for x in ln.split(",")]
            if i not in EXCL.split(","):
                gpus.append((int(f), i))
    gpus.sort(reverse=True)
    # 给 ComfyUI 留余量（11-01 04:16–04:20 OOM）：CLIP-L fp32 约 1.7 GB + 滑窗激活；空闲不到 CLIP_MIN_FREE_MB 的卡不用，全不够就用 CPU
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpus[0][1] if gpus and gpus[0][0] >= int(MINFREE) else "",
               NS_CLIP_PATH=os.path.join(RL, "clip-vit-large-patch14"))
    c = subprocess.run([CPY, "clip_srv.py", "-"], cwd=RL, env=env, capture_output=True, text=True,
                       input=json.dumps({"refs_dir": os.path.join(RL, "refs"), "items": clip_items}))
    co = [ln for ln in c.stdout.splitlines() if ln.startswith("{")]
    cl = json.loads(co[-1]) if co else {"items": {}, "missing_refs": [], "error": c.stderr[-400:]}
    res.update(local=cl.get("items", {}), missing_refs=cl.get("missing_refs", []), clip_error=cl.get("error"),
               clip_device=cl.get("device"), clip_gpu=cl.get("gpu"), clip_cuda=env["CUDA_VISIBLE_DEVICES"],
               clip_cpu_fallback=cl.get("cpu_fallback"), clip_gpu_retried=cl.get("gpu_retried"))
finally:
    shutil.rmtree(d, ignore_errors=True)
print(json.dumps(res))
'''


def _sha16(p: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def _data_root() -> Path:
    """数据根跟 ns_render.pipeline.P.DATA 走（测试沙盒会换掉它；ITERAUDIT 11-01 真实数据守卫）；导入不了才用仓库 data/"""
    try:
        from ns_render import pipeline as P
        return Path(P.DATA)
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parents[2] / "data"


def _known_path(host: str) -> Path:
    return _data_root() / "cache" / f"reflock_remote_refs_{host}.json"


def full_score(host: str, items: list[dict], timeout: float = 900, label: str | None = None) -> dict:
    """出图后契约的全部像素度量，一次 ssh（机器上：ArcFace / OCR / mediapipe / CLIP-GPU）。
    items: [{"id", "host_path": 机器上的原始输出 | None, "file": 本机交付图（没有 host_path 时上传），"post": {"size", "usm"} | None
             （host_path 是 1.5× 原始输出时按交付图后处理复现，见 post_of），"rows": postflight.q2_rows(rec), "scene": postflight.scene_file(rec)}]
    → {"items", "cross", "hands", "local": {id: {Q2, Q4, Q7}}}（与 postflight.measure_local 同口径，直接喂 postflight.evaluate）"""
    import base64
    root = Path(__file__).resolve().parents[2]
    faces = face_refs(host)                               # 先同步身份脸（会更新已知清单），再读清单
    kp = _known_path(host)
    try:
        known = set(json.loads(kp.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        known = set()
    sha_of, req_items = {}, []
    for it in items:
        rows = []
        for r in it.get("rows") or []:
            sha_of.setdefault(r["file"], _sha16(root / r["file"]))
            rows.append({**r, "ref": sha_of[r["file"]]})
        sc = it.get("scene")
        if sc and (root / sc).is_file():
            sha_of.setdefault(sc, _sha16(root / sc))
        else:
            sc = None
        e = {"id": it["id"], "host_path": it.get("host_path"), "post": it.get("post"), "rows": rows, "outer": it.get("outer") or [],
             "scene": sha_of[sc] if sc else None}
        if not it.get("host_path"):
            f = Path(it["file"])
            e["b64"] = base64.b64encode((f if f.is_absolute() else root / f).read_bytes()).decode()
        req_items.append(e)
    code = {n: base64.b64encode((root / p).read_bytes()).decode() for n, p in
            (("metrics.py", "services/agent/ns_agent/gen_contract/metrics.py"), ("clip_srv.py", "tools/gen_contract/clip_srv.py"))}
    rev = {v: k for k, v in sha_of.items()}
    send = {s for s in sha_of.values() if s not in known}
    script = base64.b64encode(_FULL.encode()).decode()
    cmd = f'python3 -c "$(echo {script} | base64 -d)" {R} {IDM} {HAND} {RL} {COMFY_PY} {",".join(sorted(GPU_EXCLUDE)) or "-"} {CLIP_MIN_FREE_MB}'
    d = {}
    hb = _hb_start(host, items, label)
    try:
        d = _full_call(host, cmd, req_items, code, rev, send, known, root, timeout, faces)
    finally:
        _hb_done(hb)
    known = d.pop("_known", known)
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_text(json.dumps(sorted(known)), encoding="utf-8")
    for k, v in (d.get("local") or {}).items():          # Q7 的 file 字段补回本机路径
        it = next(x for x in items if x["id"] == k)
        if isinstance(v, dict) and v.get("Q7"):
            v["Q7"]["file"] = it.get("scene")
    return d


def _hb_start(host: str, items: list[dict], label: str | None):
    """GPU 心跳（GPUVIEW / K-OPS-G01）：本机写，面板显示“契约打分 · <镜> …”"""
    try:
        import sys as _s
        root = Path(__file__).resolve().parents[2]
        if str(root / "services/agent") not in _s.path:
            _s.path.insert(0, str(root / "services/agent"))
        from ns_agent import comfy_tag as CT
        shots = sorted({str(it["id"]).split("|")[0].split("/")[0] for it in items})
        hid = f"REFLOCK-clip-{uuid.uuid4().hex[:6]}"
        CT.heartbeat("REFLOCK", f"契约打分 · {label or '、'.join(shots[:3])}{' 等' if len(shots) > 3 else ''}（{len(items)} 张）",
                     kind="other", server=host, gpu=None, steps=len(items), hb_id=hid, ttl=900,
                     shot=shots[0] if len(shots) == 1 else None)
        return (CT, hid)
    except Exception:  # noqa: BLE001
        return None


def _hb_done(hb):
    if hb:
        try:
            hb[0].heartbeat_done("REFLOCK", hb_id=hb[1])
        except Exception:  # noqa: BLE001
            pass


def _full_call(host, cmd, req_items, code, rev, send, known, root, timeout, faces):
    import base64
    d = {}
    for _attempt in range(2):
        payload = {"batch": "fs_" + time.strftime("%H%M%S") + uuid.uuid4().hex[:4], "face_refs": faces, "items": req_items,
                   "code": code, "refs_b64": {s: base64.b64encode((root / rev[s]).read_bytes()).decode() for s in send}}
        r = ssh(host, cmd, json.dumps(payload), timeout=timeout)
        out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
        if not out:
            raise RuntimeError(f"full_score@{host}: " + (r.stderr or "")[-400:])
        d = json.loads(out[-1])
        known |= send
        if d.get("missing_refs"):
            send = set(d["missing_refs"])
            known -= send
            continue
        break
    d["_known"] = known
    return d


def post_of(eff: dict | None) -> dict | None:
    """出图预设的交付后处理（与 ns_render.image_params.post_file 同参数）→ full_score 的 post"""
    if not eff:
        return None
    import sys as _s
    root = Path(__file__).resolve().parents[2]
    if str(root / "services/render_router") not in _s.path:
        _s.path.insert(0, str(root / "services/render_router"))
    from ns_render import image_params as IP
    size = IP.target_size(eff)
    sh = eff.get("sharpen") or {}
    usm = {"radius": float(sh["radius"]), "percent": int(round(float(sh["amount"]) * 100)),
           "threshold": int(sh.get("threshold") or 0)} if sh.get("enabled") else None
    return {"size": list(size) if size else None, "usm": usm}


def postflight_full(host: str, jobs: list[dict], label: str | None = None) -> dict:
    """ASSETMASTER / 画布用：jobs = [{"id", "host_path" | "file", "post", "request": contract_request（含 cast、asset_refs）}]
    → {id: postflight 结果 dict}（一次 ssh 算完全部 Q1–Q7）"""
    import sys as _s
    root = Path(__file__).resolve().parents[2]
    if str(root / "services/agent") not in _s.path:
        _s.path.insert(0, str(root / "services/agent"))
    from ns_agent.gen_contract import postflight as PO
    items = []
    for j in jobs:
        rec = (j.get("request") or {}).get("asset_refs") or {}
        items.append({"id": j["id"], "host_path": j.get("host_path"), "file": j.get("file"), "post": j.get("post"),
                      "rows": PO.q2_rows(rec), "scene": PO.scene_file(rec), "outer": PO.outer_rows(rec)})
    m = full_score(host, items, label=label)
    out = {}
    for j in jobs:
        loc = (m.get("local") or {}).get(j["id"])
        img = j.get("file") or j.get("host_path")
        r = PO.evaluate(img, j.get("request") or {}, remote=(m.get("items") or {}).get(j["id"]), cross=m.get("cross"),
                        hands=(m.get("hands") or {}).get(j["id"]), local=loc if isinstance(loc, dict) and "error" not in loc else None)
        d = r.to_dict()
        d["reasons"] = r.reasons()
        d["measured_on"] = f"{host}（{m.get('clip_gpu') or m.get('clip_device')}）"
        if m.get("clip_error") or (isinstance(loc, dict) and loc.get("error")):
            d["measure_error"] = m.get("clip_error") or loc.get("error")
        out[j["id"]] = d
    return out


def main():
    """CLI：python tools/gen_contract/remote_score.py postflight --host gpu33 --jobs jobs.json
    （jobs.json = [{id, host_path | file, post, request}]，输出 {id: postflight}）"""
    import argparse
    import sys as _s
    _s.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["postflight", "full"])
    ap.add_argument("--host", default="gpu33")
    ap.add_argument("--jobs", required=True)
    a = ap.parse_args()
    jobs = json.loads(Path(a.jobs).read_text(encoding="utf-8"))
    res = postflight_full(a.host, jobs) if a.cmd == "postflight" else full_score(a.host, jobs)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
