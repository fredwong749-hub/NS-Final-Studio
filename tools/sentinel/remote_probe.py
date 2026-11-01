"""SENTINEL 服务器端只读采样脚本（经 rssh 常驻主连接 stdin 送到服务器，用 python3 跑；不落盘、不改任何文件）。
每台每拍只跑这一次（合并调用，K-OPS-N09）；调用方包 `timeout 30 nice -n 19`，本脚本自己限线程（K-OPS-V13）。
argv：<服务器仓库根> <sha 文件列表，逗号分隔> <是否查 :8870 0/1>
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
HUMAN = ("等总调度", "等项目方", "总调度复核", "项目方点选", "总调度定")
EVS = ('"contract_s"', '"score_backlog"', '"redo_fail"', '"pause"', '"resume"', '"dispatch"', '"rendered"')
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
reg = jl("data/producer/registry.json")
cnt, waits = {}, {}
for E in (reg or {}).get("episodes") or []:
    for S in E.get("shots") or []:
        for o in (S.get("objects") or {}).values():
            st = o.get("status")
            cnt[st] = cnt.get(st, 0) + 1
            w = str(o.get("waiting_for") or "")
            if st != "passed" and any(x in w for x in HUMAN):
                waits[o.get("id")] = w[:40]
out["registry"] = {"counts": cnt, "waits": waits, "updated": (reg or {}).get("updated")} if reg else None
ev = []
try:
    p = os.path.join(R, "data/producer/log.jsonl")
    with open(p, "rb") as fh:
        fh.seek(max(0, os.path.getsize(p) - 600_000))
        for ln in fh.read().decode("utf-8", "replace").splitlines():
            if any(e in ln for e in EVS):
                try:
                    d = json.loads(ln)
                except ValueError:  # arch-ok: 坏行跳过
                    continue
                if d.get("t", 0) >= time.time() - 3 * 3600:
                    ev.append({k: d.get(k) for k in ("t", "ev", "obj", "lane", "contract_s", "by", "n", "max")})
except OSError as e:  # arch-ok: 回传 log_err，笔记本记未测
    out["log_err"] = repr(e)[:120]
out["events"] = ev[-600:]
if VQA:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8870/v1/models", timeout=4) as r:
            out["vqa_models"] = r.read(400).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        out["vqa_models"] = "ERR " + repr(e)[:160]
    out["vqa_listener"] = sh(["ss", "-ltnpH", "sport = :8870"], 8)[:400]
print(json.dumps(out, ensure_ascii=False))
