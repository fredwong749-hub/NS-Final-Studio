"""SENTINEL 服务器端只读采样脚本（经 rssh 常驻主连接 stdin 送到服务器，用 python3 跑；不落盘、不改任何文件）。
每台每拍只跑这一次（合并调用，K-OPS-N09）；调用方包 `timeout 30 nice -n 19`，本脚本自己限线程（K-OPS-V13）。
argv：<服务器仓库根> <sha 文件列表，逗号分隔> <是否查 :8870 0/1> <comfy 端口> <坏卡> <LAN url> <各剧 producer 目录 run=dir,…>
stdout：一行 JSON。
"""
import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):   # K-OPS-V13
    os.environ[_k] = "1"

import hashlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

R = sys.argv[1]
FILES = [f for f in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if f]
VQA = len(sys.argv) > 3 and sys.argv[3] == "1"
COMFY = [int(x) for x in (sys.argv[4] if len(sys.argv) > 4 else "").split(",") if x.strip().isdigit()]
BROKEN = [int(x) for x in (sys.argv[5] if len(sys.argv) > 5 else "").split(",") if x.strip().isdigit()]
LAN = [u for u in (sys.argv[6] if len(sys.argv) > 6 else "").split(",") if u.startswith("http")]
# MERGE-OPS-O（carryover 第 14 项，L-137）：各剧 producer 目录 "run=data/producer/runs/<run>,…"（legacy 剧 = data/producer，总在）
PDIRS = [("", "data/producer")] + [tuple(x.split("=", 1)) for x in (sys.argv[7] if len(sys.argv) > 7 else "").split(",")
                                   if "=" in x and x.split("=", 1)[1].startswith("data/producer/runs/")]
HUMAN = ("等总调度", "等项目方", "总调度复核", "项目方点选", "总调度定")
EVS = ('"contract_s"', '"score_backlog"', '"redo_fail"', '"pause"', '"resume"', '"dispatch"', '"rendered"', '"passed"', '"content_fail"',
       '"redo_auto_approved"', '"redo_candidate"', '"score_infra"', '"content_error"', '"best_effort"')
out = {"t": time.time()}


def sh(cmd, t=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout
    except Exception as e:  # noqa: BLE001
        return "ERR " + repr(e)


def jl(p):
    try:
        with open(os.path.join(R, p), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001  # arch-ok: None 回传给笔记本，judges 视为未测
        return None


smi = []
for ln in sh(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used", "--format=csv,noheader,nounits"]).splitlines():
    p = [x.strip() for x in ln.split(",")]
    if len(p) == 3 and p[0].isdigit():
        smi.append([int(p[0]), int(p[1]) if p[1].isdigit() else -1, int(p[2]) if p[2].isdigit() else -1])
out["smi"] = smi
out["heartbeat"] = jl("data/producer/heartbeat.json")
out["control"] = jl("data/producer/control.json")
sv = jl("data/system_version.txt")
out["sv"] = (sv or {}).get("id")
sha = {}
for f in FILES:
    try:
        with open(os.path.join(R, f), "rb") as fh:
            sha[f] = hashlib.sha256(fh.read()).hexdigest()
    except OSError:  # arch-ok: 缺文件 = sha None（与笔记本同缺视为一致）
        sha[f] = None
out["sha"] = sha
cnt, waits, ready_by_run, any_reg, updated = {}, {}, {}, False, None
ev = []
out["runs"] = {}
for run_name, pdir in PDIRS:
    reg = jl(pdir + "/registry.json")
    if run_name:
        out["runs"][run_name] = {"heartbeat": jl(pdir + "/heartbeat.json"), "control": jl(pdir + "/control.json"), "registry": None}
    if reg:
        any_reg = True
        updated = updated if run_name else reg.get("updated")
        rc = {}
        for E in reg.get("episodes") or []:
            for S in E.get("shots") or []:
                for o in (S.get("objects") or {}).values():
                    st = o.get("status")
                    cnt[st] = cnt.get(st, 0) + 1
                    rc[st] = rc.get(st, 0) + 1
                    if st == "ready":
                        rid = str(o.get("id") or "")
                        rk = rid.split("/", 1)[0] if "/" in rid else run_name
                        ready_by_run[rk] = ready_by_run.get(rk, 0) + 1
                    w = str(o.get("waiting_for") or "")
                    if st != "passed" and any(x in w for x in HUMAN):
                        waits[(run_name + "/" if run_name else "") + str(o.get("id"))] = w[:40]
        if run_name:
            out["runs"][run_name]["registry"] = rc
    try:
        p = os.path.join(R, pdir, "log.jsonl")
        with open(p, "rb") as fh:
            fh.seek(max(0, os.path.getsize(p) - 600_000))
            for ln in fh.read().decode("utf-8", "replace").splitlines():
                if any(e in ln for e in EVS):
                    try:
                        d = json.loads(ln)
                    except ValueError:  # arch-ok: 坏行跳过
                        continue
                    if d.get("t", 0) >= time.time() - 3 * 3600:
                        e_ = {k: d.get(k) for k in ("t", "ev", "obj", "lane", "take", "contract_s", "by", "n", "max")}
                        if run_name:
                            e_["run"] = run_name
                        ev.append(e_)
    except OSError as e:  # arch-ok: 回传 log_err，笔记本记未测（只报 legacy 目录；别的剧没起 = 没有日志）
        if not run_name:
            out["log_err"] = repr(e)[:120]
out["registry"] = {"counts": cnt, "waits": waits, "ready_by_run": ready_by_run, "updated": updated} if any_reg else None
ev.sort(key=lambda d: d.get("t") or 0)
out["events"] = ev[-600:]
comfy = {}
for port in COMFY:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/system_stats" % port, timeout=4) as r:
            comfy[str(port)] = r.status == 200
    except Exception as e:  # noqa: BLE001  # arch-ok: 回传 False + 原因，笔记本开 S2 comfy 工单
        comfy[str(port)] = "ERR " + repr(e)[:80]
out["comfy"] = comfy
# G26：每个声明端口 → 监听进程 pid → 命令行 --cuda-device / nvidia-smi 计算进程所在 GPU；system_stats 的 devices
uuid2idx = {}
for ln in sh(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"]).splitlines():
    p_ = [x.strip() for x in ln.split(",")]
    if len(p_) == 2 and p_[0].isdigit():
        uuid2idx[p_[1]] = int(p_[0])
apps = {}
for ln in sh(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader"]).splitlines():
    p_ = [x.strip() for x in ln.split(",")]
    if len(p_) == 2 and p_[1].isdigit() and p_[0] in uuid2idx:
        apps.setdefault(int(p_[1]), set()).add(uuid2idx[p_[0]])
lanes = {}
for port in COMFY:
    rec = {"port": port}
    lst = sh(["ss", "-ltnpH", "sport = :%d" % port], 8)
    pid = None
    if "pid=" in lst:
        try:
            pid = int(lst.split("pid=", 1)[1].split(",", 1)[0])
        except ValueError:  # arch-ok: pid 解析不出 = 不判 GPU 序号
            pid = None
    rec["pid"] = pid
    if pid:
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as fh:
                cl = fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:  # arch-ok: 读不到命令行 = 只用 nvidia-smi
            cl = ""
        rec["cuda_arg"] = int(cl.split("--cuda-device", 1)[1].split()[0]) if "--cuda-device" in cl and cl.split("--cuda-device", 1)[1].split()[0].isdigit() else None
        try:
            env = open("/proc/%d/environ" % pid, "rb").read().split(b"\0")
            cvd = [e.split(b"=", 1)[1].decode() for e in env if e.startswith(b"CUDA_VISIBLE_DEVICES=")]
        except OSError:  # arch-ok: 读不到环境 = 不用 CUDA_VISIBLE_DEVICES 判
            cvd = []
        rec["cvd"] = cvd[0] if cvd else None
        rec["smi_gpus"] = sorted(apps.get(pid, set()))
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/system_stats" % port, timeout=4) as r:
            st = json.loads(r.read(4000))
        rec["stats_ok"] = True
        rec["devices"] = [d.get("name") for d in st.get("devices") or []]
    except Exception as e:  # noqa: BLE001  # arch-ok: 回传原因，笔记本开 G26 工单
        rec["stats_ok"] = False
        rec["err"] = repr(e)[:100]
    lanes[str(port)] = rec
out["g26_lanes"] = lanes
lan = {}
for u in LAN:                                        # S28：Q10 人数检测服务（gpu36 内网 :8893）从本机测
    try:
        with urllib.request.urlopen(u, timeout=4) as r:
            body = r.read(2000).decode("utf-8", "replace")
        try:
            loaded = json.loads(body).get("loaded")
        except ValueError:  # arch-ok: 回不是 JSON = loaded 未知（按失败算）
            loaded = None
        lan[u] = {"ok": True, "loaded": loaded}
    except Exception as e:  # noqa: BLE001  # arch-ok: 回传失败原因，笔记本按连续失败开单
        lan[u] = {"ok": False, "err": repr(e)[:100]}
out["lan_health"] = lan
out["broken_apps"] = {str(i): sorted(pid for pid, gs in apps.items() if i in gs) for i in BROKEN}
if VQA:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8870/v1/models", timeout=4) as r:
            out["vqa_models"] = r.read(400).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        out["vqa_models"] = "ERR " + repr(e)[:160]
    try:
        with urllib.request.urlopen("http://127.0.0.1:8870/health", timeout=4) as r:
            out["vqa_health"] = r.read(600).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        out["vqa_health"] = "ERR " + repr(e)[:160]
    out["vqa_listener"] = sh(["ss", "-ltnpH", "sport = :8870"], 8)[:400]
print(json.dumps(out, ensure_ascii=False))
