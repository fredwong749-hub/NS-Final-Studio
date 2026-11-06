"""postflight 的远端测量（Q1 身份 / Q3 景别 / Q6 文字 / Q5 坏手）：在出图那台机器上原地跑（K-OPS-122）。

    from remote_score import score
    m = score("gpu33", {"<id>": "<机器上的 png 绝对路径>", ...})        # 出图机器上的 ComfyUI 输出路径
    m["items"][id] → postflight 的 remote；m["hands"][id] → hands；m["cross"] → cross
本机文件（没有机器路径）用 score_local_files(host, {id: 本地 png})：先 scp 到 /root/work/fredw/imggen/in/<批>/ 再打分。
参考名 = 角色 id；身份脸 = asset_refs.face_of（与出图同一张，见 face_refs）。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

R = "/root/work/fredw/imggen"     # 只作数据目录（in/ 上传批、refs/ 身份脸缓存）；脚本一律从服务器仓库部署目录跑（K-OPS-F18）


def _hosts_mod():
    import importlib.util as _u
    sp = _u.spec_from_file_location("factory_hosts_rs", Path(__file__).resolve().parents[2] / "tools/factory/hosts.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def srv_repo(host: str) -> str:
    """服务器仓库部署目录（config/factory/hosts.json 唯一来源）。总调度 11-02 16:5x：生产打分原来跑 imggen/ 下 10-31 的旁路拷贝，
    sv-13 的补边修复没生效（L-122 新脸 Q1 失效）——脚本只许来自这里。FIX-SCORE36：按实际执行机取（别名 → 本机）"""
    m = _hosts_mod()
    return m.server_root(m.exec_host(host))


def comfy_py(host: str) -> str:
    """A-07（总调度 19:2x）：CLIP 单次子进程的解释器按主机取 hosts.json comfy_python（原来 resident_prep 在 gpu36 上就地改本文件的 COMFY_PY）。
    FIX-SCORE36（11-06）：按实际执行机取——gpu36 上 full_score("gpu33") 是本机执行，原来拿了 gpu33 的 comfy_python
    （gpu36 上不存在）→ 远端脚本崩 → 退回进程内 CPU 打分 → producer venv 没 torch，ep02-S10 一直 score_infra"""
    m = _hosts_mod()
    return m.load()["hosts"].get(m.exec_host(host), {}).get("comfy_python") or COMFY_PY


def gpu_exclude(host: str) -> set[str]:
    """不放 CLIP 的坏卡：按实际执行机的 hosts.json broken_gpus（原来写死 gpu33 的 {"2"}，gpu36 上把常驻 CLIP 钉的 GPU2 也排除了）"""
    try:
        m = _hosts_mod()
        return set(m.broken_gpus(m.exec_host(host)))
    except Exception:  # noqa: BLE001  # arch-ok: 车道表读不到 → 用旧的写死值（只影响 CLIP 选卡，不影响判分）
        return set(GPU_EXCLUDE)


SCORE_PY = "tools/series10_imggen/score_remote.py"
HANDS_PY = "tools/series10_imggen/hands_remote.py"
CLIP_PY = "tools/gen_contract/clip_srv.py"
METRICS_DIR = "services/agent/ns_agent/gen_contract"
IDM = "/root/work/fredw/venv_idm/bin/python"
HAND = "/root/work/fredw/venv_hand/bin/python"
# 身份脸：出图用哪张、打分就对哪张（BAKEOFF P1 11-01：每个角色只有一张身份脸）。不再手写机器路径——由 asset_refs.face_of
# （资产中心“设为当前身份脸”覆盖 > config/recipes/asset_refs.json faces）解析出本机文件，按内容哈希放到机器上 refs/id_<sha16>.png。
# 原来的 lin_wan@master（10-31 旧母版裁切）作废：总调度 P0 已把林晚改回 A-s202 face_ref2va，打分再对旧母版取高者会放过不像的图。
FACE_CHARS = ("lin_wan", "gu_chen", "chen_yu", "ch_a_lan")
def face_project() -> str:
    """当前打分对哪部剧的身份脸（AUDIT-M I-2，总调度 18:5x：原来写死第一季）：进程环境 NS_RUN_ID（非主剧 producer 设）→ runs.json primary"""
    import os as _o
    v = _o.environ.get("NS_RUN_ID")
    if v:
        return v
    import sys as _s
    root = Path(__file__).resolve().parents[2]
    if str(root) not in _s.path:
        _s.path.insert(0, str(root))
    from tools.autopilot import runs as _RN    # OVERSIGHT-F P2：tools 侧 runs 唯一入口
    return _RN.current_run()


def __getattr__(name):            # 兼容旧读法 RS.FACE_PROJECT（tools/vqa/accept.py、anomaly.py）：每次按当前剧解析
    if name == "FACE_PROJECT":
        return face_project()
    raise AttributeError(name)


def local_faces(project: str | None = None) -> dict[str, str]:
    """{角色 id: 出图用的身份脸（仓库相对路径）}——与 asset_refs.plan_for 同一个函数解析"""
    project = project or face_project()
    import sys as _s
    root = Path(__file__).resolve().parents[2]
    if str(root / "services/agent") not in _s.path:
        _s.path.insert(0, str(root / "services/agent"))
    from ns_agent import asset_refs as AR
    out = {}
    # L-126（总调度 11-02 18:5x）：资产包（清单）模式的剧——角色名单只取清单里的（V2 女主 lead_f 不在 V1 的 FACE_CHARS 里，原来不会上传她的脸）
    chars = list(((AR.manifest(project) or {}).get("characters") or {})) if AR.manifest_rel(project) else list(FACE_CHARS)
    for cid in chars:
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


Q1_MODE: dict = {"mode": "anchor_only", "why": "face_refs 还没跑"}   # 身份库 top-k 是否生效（随打分结果下发到 Q1 证据）


def face_refs(host: str, project: str | None = None) -> dict[str, str]:
    """{角色 id: 机器上的身份脸路径}；机器上没有的先传上去（一次 ssh，之后按哈希记在本机已知清单里不再传）"""
    import base64
    root = Path(__file__).resolve().parents[2]
    faces = {cid: (f, _sha16(root / f)) for cid, f in local_faces(project).items()}
    # 身份库 top-k（VQAGATE 11-02，L-098，CONSENT REFLOCK→VQAGATE）：库里已通过的帧作为 "<cid>@bN" 参照一起打分；
    # top-k 平均 + 对锚（L-086）≥ 复核下限的条件在 postflight Q1 里算（ns_agent.gen_contract.postflight.apply_bank）
    try:
        import sys as _s
        if str(root / "tools" / "identity") not in _s.path:
            _s.path.insert(0, str(root / "tools" / "identity"))
        import bank as _bank
        for cid in list(faces):
            for i, bf in enumerate(_bank.bank_files(cid)):
                faces[f"{cid}@b{i}"] = (bf, _sha16(root / bf))
        Q1_MODE.update(mode="bank", why="")
    except Exception as e:  # noqa: BLE001 — 身份库读不到就只用锚，但要可见（SYSARCH 11-02：降级也要有 decider 和 check）
        Q1_MODE.update(mode="anchor_only", why=repr(e)[:200])
        print(f"[face_refs] 身份库没读到，只用锚：{e!r}"[:200], file=__import__("sys").stderr)
        try:
            ap = root / "data" / "vqa" / "alerts.jsonl"
            ap.parent.mkdir(parents=True, exist_ok=True)
            with ap.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "q1_anchor_only", "host": host,
                                    "why": repr(e)[:200]}, ensure_ascii=False) + chr(10))
        except OSError as e2:
            print(f"[face_refs] 报警写不进 alerts.jsonl：{e2!r}", file=__import__("sys").stderr)
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
    return _rssh().run_retry(host, cmd, input=stdin, timeout=timeout, tries=1, text=True)   # 原来不重试：tries=1；长会话由调用方给足 timeout

def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



def score(host: str, paths: dict[str, str]) -> dict:
    items = [{"id": k, "path": v} for k, v in paths.items()]
    refs = {k: [v] for k, v in face_refs(host).items()}
    src = srv_repo(host)
    r = ssh(host, f"cd {R} && {IDM} {src}/{SCORE_PY} - 2>/dev/null", json.dumps({"refs": refs, "items": items}, ensure_ascii=False))
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        raise RuntimeError(f"score_remote@{host}: " + r.stderr[-400:])
    d = json.loads(out[-1])
    for it in d.get("items", {}).values():
        for f in it.get("faces", []):
            f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(d["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = ssh(host, f"cd {R} && {HAND} {src}/{HANDS_PY} 2>/dev/null", json.dumps({"items": hi}))
    ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
    return {"items": d.get("items", {}), "cross": d.get("cross", {}), "hands": json.loads(ho[-1]) if ho else {},
            "refs": list(refs)}


# IMGPERF（11-01）：原 score_local_files = mkdir / scp / ls / score / hands / rm 六次独立 ssh（每次经跳板握手 10–13 s，
# scp 1.3 MB 60 s），实测 130 s。改成一次 ssh：图片 base64 走 stdin，远端一个小脚本落盘 → 打分 → 手 → 删目录 → 打一行 JSON。
_ONE_SHOT = r'''
import base64, json, os, shutil, subprocess, sys
# 总调度 11-02 15:2x（K-OPS-F17）：gpu33 load 300，score_remote 单进程 412 线程 1452% CPU（onnxruntime 默认按 96 核开线程），
# sshd / 命令通道被饿死（rssh 成功率 41-63%）。打分子进程一律限线程 + nice 10 + 只绑最后 NS_SCORE_CPUS 个核。
NT = os.environ.get("NS_SCORE_THREADS", "8")
SENV = dict(os.environ, OMP_NUM_THREADS=NT, MKL_NUM_THREADS=NT, OPENBLAS_NUM_THREADS=NT, NUMEXPR_NUM_THREADS=NT, ORT_NUM_THREADS=NT)
def _lim():
    try:
        os.nice(10)
        cpus = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, set(cpus[-int(os.environ.get("NS_SCORE_CPUS", "16")):]))
    except Exception:
        pass
R, IDM, HAND, SRC = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
req = json.load(sys.stdin)
d = os.path.join(R, "in", req["batch"]); os.makedirs(d, exist_ok=True)
try:
    items = []
    for k, (name, b64) in req["files"].items():
        p = os.path.join(d, name)
        open(p, "wb").write(base64.b64decode(b64))
        items.append({"id": k, "path": p})
    refs = {k: [v] for k, v in req["refs"].items() if os.path.exists(v)}
    r = subprocess.run([IDM, os.path.join(SRC, "tools/series10_imggen/score_remote.py"), "-"], cwd=R, input=json.dumps({"refs": refs, "items": items}),
                       capture_output=True, text=True, env=SENV, preexec_fn=_lim)
    out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not out:
        print(json.dumps({"error": "score_remote: " + r.stderr[-400:]})); sys.exit(0)
    s = json.loads(out[-1])
    for it in s.get("items", {}).values():
        for f in it.get("faces", []):
            f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(s["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = subprocess.run([HAND, os.path.join(SRC, "tools/series10_imggen/hands_remote.py")], cwd=R, input=json.dumps({"items": hi}), capture_output=True, text=True, env=SENV, preexec_fn=_lim)
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
    cmd = f'python3 -c "$(echo {code} | base64 -d)" {R} {IDM} {HAND} {srv_repo(host)}'
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
# 总调度 11-02 15:2x（K-OPS-F17）：gpu33 load 300，score_remote 单进程 412 线程 1452% CPU（onnxruntime 默认按 96 核开线程），
# sshd / 命令通道被饿死（rssh 成功率 41-63%）。打分子进程一律限线程 + nice 10 + 只绑最后 NS_SCORE_CPUS 个核。
NT = os.environ.get("NS_SCORE_THREADS", "8")
SENV = dict(os.environ, OMP_NUM_THREADS=NT, MKL_NUM_THREADS=NT, OPENBLAS_NUM_THREADS=NT, NUMEXPR_NUM_THREADS=NT, ORT_NUM_THREADS=NT)
def _lim():
    try:
        os.nice(10)
        cpus = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, set(cpus[-int(os.environ.get("NS_SCORE_CPUS", "16")):]))
    except Exception:
        pass
R, IDM, HAND, RL, CPY, EXCL, MINFREE, SRC = sys.argv[1:9]
# AUDIT-PERF 提案 A：常驻打分服务（tools/gen_contract/score_srv.py；idm 8873 / hand 8874，只听 127.0.0.1）。开关 NS_SCORE_RESIDENT=1 才试；
# 任何失败（没起 / 409 代码换了 / 500 / 超时）当次退回旧子进程，原因记 score_resident.<kind>_error
_RES = {}
def _resident(kind, route, obj):
    if os.environ.get("NS_SCORE_RESIDENT") != "1":
        return None
    try:
        import urllib.request
        port = os.environ.get("NS_SCORE_SRV_PORT_" + kind.upper(), {"idm": "8873", "hand": "8874"}[kind])
        rq = urllib.request.Request("http://127.0.0.1:" + port + "/" + route, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(rq, timeout=300).read())
        _RES[kind] = True
        return out
    except Exception as e:
        _RES[kind] = False
        _RES[kind + "_error"] = repr(e)[:160]
        return None
req = json.load(sys.stdin)
os.makedirs(os.path.join(RL, "refs"), exist_ok=True)
# K-OPS-F18：不再把请求方的 metrics.py / clip_srv.py 写进 reflock（旁路拷贝 = 两个入口）；度量代码只用服务器仓库部署目录里的那份
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
    s = _resident("idm", "score", {"refs": refs, "items": items})      # AUDIT-PERF 提案 A：常驻（开关 NS_SCORE_RESIDENT=1）；不在 / 409 / 出错 → 退回旧子进程
    if s is None:
        r = subprocess.run([IDM, os.path.join(SRC, "tools/series10_imggen/score_remote.py"), "-"], cwd=R, input=json.dumps({"refs": refs, "items": items}), capture_output=True, text=True, env=SENV, preexec_fn=_lim)
        out = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
        s = json.loads(out[-1]) if out else {"items": {}, "cross": {}, "error": "score_remote: " + r.stderr[-300:]}
    for it in s.get("items", {}).values():
        for f in it.get("faces", []):
            if (f.get("h_ratio") or 0) >= 0.04 and f.get("emb"):      # Q1x（VQAGATE 11-02）：够大的脸带特征回本机，postflight 落 data/identity/emb/
                f["emb"] = [round(float(x), 4) for x in f["emb"]]
            else:
                f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(s["items"].get(i["id"], {}).get("faces", []))} for i in items]
    hd = _resident("hand", "hands", {"items": hi})
    if hd is None:
        rh = subprocess.run([HAND, os.path.join(SRC, "tools/series10_imggen/hands_remote.py")], cwd=R, input=json.dumps({"items": hi}), capture_output=True, text=True, env=SENV, preexec_fn=_lim)
        ho = [ln for ln in rh.stdout.splitlines() if ln.startswith("{")]
        hd = json.loads(ho[-1]) if ho else {}
    res = {"items": s.get("items", {}), "cross": s.get("cross", {}), "hands": hd,
           "refs": list(refs), "score_error": s.get("error"), "score_resident": dict(_RES)}
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
    q = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, env=SENV, preexec_fn=_lim)
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
    creq = {"refs_dir": os.path.join(RL, "refs"), "items": clip_items}
    cl = None
    try:   # FACTORY D6（K-OPS-F04）：先走本机常驻 CLIP（127.0.0.1，只加载一次；gpu36 钉 GPU2）；不在 / 409 代码已换 → 当次退回单次子进程
        import urllib.request
        _rq = urllib.request.Request("http://127.0.0.1:" + os.environ.get("NS_CLIP_SRV_PORT", "8872") + "/measure",
                                     data=json.dumps(creq).encode(), headers={"Content-Type": "application/json"})
        cl = json.loads(urllib.request.urlopen(_rq, timeout=600).read())
        env["CUDA_VISIBLE_DEVICES"] = "resident"
    except Exception as _e:
        res["clip_resident_error"] = repr(_e)[:160]
    if cl is None:
        c = subprocess.run([CPY, os.path.join(SRC, "tools/gen_contract/clip_srv.py"), "-"], cwd=RL,
                           env={**SENV, **env, "NS_METRICS_DIR": os.path.join(SRC, "services/agent/ns_agent/gen_contract")}, capture_output=True, text=True, input=json.dumps(creq), preexec_fn=_lim)
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


def _resident_env() -> str:
    """AUDIT-PERF 提案 A 开关：config/pipeline/score_resident.json enabled（默认 false；env NS_SCORE_RESIDENT=1/0 覆盖）→ 远端命令前缀"""
    v = os.environ.get("NS_SCORE_RESIDENT")
    if v is None:
        try:
            cfg = json.loads((Path(__file__).resolve().parents[2] / "config/pipeline/score_resident.json").read_text(encoding="utf-8"))
            v = "1" if cfg.get("enabled") else "0"
        except (OSError, ValueError):
            v = "0"
    return "NS_SCORE_RESIDENT=1 " if v == "1" else ""


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
    sha_of, req_items, need_up = {}, [], []
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
            need_up.append((e, f if f.is_absolute() else root / f))
        req_items.append(e)
    up_dir, upload = _bulk_upload(host, need_up)          # W21：本机图走独立连接传（不经命令主连接）；失败 → 原 base64-stdin 路径
    code = {}      # K-OPS-F18：度量代码不随请求下发（服务器只跑部署版；口径一致靠发版，不靠覆盖服务器上的文件）
    rev = {v: k for k, v in sha_of.items()}
    send = {s for s in sha_of.values() if s not in known}
    script = base64.b64encode(_FULL.encode()).decode()
    cmd = (f'{_resident_env()}python3 -c "$(echo {script} | base64 -d)" {R} {IDM} {HAND} {RL} {comfy_py(host)} {",".join(sorted(gpu_exclude(host))) or "-"} {CLIP_MIN_FREE_MB} '
           f'{srv_repo(host)}')
    d = {}
    hb = _hb_start(host, items, label)
    try:
        d = _full_call(host, cmd, req_items, code, rev, send, known, root, timeout, faces)
    finally:
        _hb_done(hb)
        if up_dir:                                        # 传上去的图打完就删（小命令，走主连接；删失败只留垃圾，不影响结果）
            try:
                ssh(host, f"rm -rf {up_dir}", timeout=120)
            except Exception:  # noqa: BLE001   arch-ok: 清理失败不改变打分结果
                pass
    d["upload"] = upload
    known = d.pop("_known", known)
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_text(json.dumps(sorted(known)), encoding="utf-8")
    d["q1_mode"] = dict(Q1_MODE)
    for v in (d.get("items") or {}).values():
        if isinstance(v, dict):
            v["q1_mode"] = Q1_MODE["mode"]
    for k, v in (d.get("local") or {}).items():          # Q7 的 file 字段补回本机路径
        it = next(x for x in items if x["id"] == k)
        if isinstance(v, dict) and v.get("Q7"):
            v["Q7"]["file"] = it.get("scene")
    return d


BULK_MIN_BYTES = 1 << 20      # W21：本机图合计 ≥ 1 MB 才走独立连接（每次 = 一条新跳板连接；~10–27 次 / 时，见 data/netfix/rssh_calls.jsonl 15:xx）


def _bulk_upload(host: str, need: list) -> tuple[str | None, dict]:
    """W21 NETFIX-BULK（ISS-1103-150939，运维 FONG-QUICK：大文件不要走 -t）：full_score 原来把本机图 base64 塞进 ssh stdin，
    走命令主连接（挂在 base-a 一条 TCP 上）→ 几 MB 图把小命令堵住、打分 1800 s 超时。改为先经 rssh.bulk_put（sftp，<host>-hk 单独一条连接）
    传到 R/up/<批>/，请求里只带 host_path；打分命令本身仍走主连接。
    传不了（不在笔记本 / sftp 失败 / 超时）→ 这批全部退回 base64-stdin 原路径，mode 如实记 b64_fallback（不冒充走了独立连接）。
    → (远端目录 | None, {"mode": none|sftp-hk|b64|b64_fallback, ...})"""
    import base64
    if not need:
        return None, {"mode": "none"}
    total = sum(Path(f).stat().st_size for _, f in need)
    if total < int(os.environ.get("NS_BULK_MIN_BYTES", BULK_MIN_BYTES)):   # 小批不值得多一条跳板握手（运维：跳板每小时新建 < 50）
        for e, f in need:
            e["b64"] = base64.b64encode(Path(f).read_bytes()).decode()
        return None, {"mode": "b64", "bytes": total}
    up_dir = f"{R}/up/fsu_{time.strftime('%H%M%S')}{uuid.uuid4().hex[:4]}"
    names = [e["id"].replace("/", "_").replace(":", "_").replace("|", "_") + ".png" for e, _ in need]
    why = None
    try:
        r = _rssh().bulk_put(host, [(f, n) for (_, f), n in zip(need, names)], up_dir,
                             timeout=max(120, 60 + 30 * len(need)))
    except Exception as ex:  # noqa: BLE001   arch-ok: 独立传输出任何错都退回原路径（下面如实记 b64_fallback）
        r, why = None, repr(ex)[:200]
    if r is not None and r.returncode == 0:
        for (e, _), n in zip(need, names):
            e["host_path"] = f"{up_dir}/{n}"
        return up_dir, {"mode": "sftp-hk", "files": len(need), "dir": up_dir}
    if r is not None:
        why = f"rc={r.returncode} " + (r.stderr or b"").decode("utf-8", "replace")[-200:]
    for e, f in need:
        e["b64"] = base64.b64encode(Path(f).read_bytes()).decode()
    return (up_dir if r is not None else None), ({"mode": "b64_fallback", "why": why} if why else {"mode": "b64"})


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
