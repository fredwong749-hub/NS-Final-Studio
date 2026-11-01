"""GPUVIEW 同一时刻核对：面板接口（/api/gpu/live、/api/render-tasks）vs 直接读 ComfyUI /queue + ssh nvidia-smi + /api/jobs。
只读。用法：.venv/Scripts/python.exe apps/web/e2e/gpuview/crosscheck.py [api_base] → 打印 Markdown 表，并写 crosscheck.json"""
import json
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8800"
TOK = (ROOT / "data" / "auth" / "viewer_token").read_text(encoding="utf-8").strip()
LANES = {"gpu33:0": 18188, "gpu33:1": 18189, "gpu33:3": 18191, "gpu36:0": 18288, "gpu36:1": 18289, "gpu36:2": 18290}
Q = "nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit --format=csv,noheader,nounits"


def get(url, tok=False, timeout=60):
    req = urllib.request.Request(url, headers={"x-ns-viewer-token": TOK} if tok else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def smi(host):
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, Q], capture_output=True, text=True, timeout=60)
    out = {}
    for ln in p.stdout.strip().splitlines():
        f = [x.strip() for x in ln.split(",")]
        out[int(f[0])] = {"util": f[1], "mem": f[2], "temp": f[4], "pw": f[5], "pl": f[6]}
    return out


def queue(port):
    d = get(f"http://127.0.0.1:{port}/queue", timeout=15)
    run = d["queue_running"]
    ed = (run[0][3] if run and len(run[0]) > 3 else {}) or {}
    pre = [n["inputs"].get("filename_prefix") for n in (run[0][2].values() if run else []) if "filename_prefix" in n.get("inputs", {})]
    return {"running": len(run), "pending": len(d["queue_pending"]), "client_id": ed.get("client_id"),
            "ns_tag": (ed.get("ns_tag") or {}).get("agent"), "prefix": pre[:1], "prompt_id": run[0][1] if run else None}


t0 = time.strftime("%Y-%m-%d %H:%M:%S")
with ThreadPoolExecutor(10) as ex:
    f_live = ex.submit(get, f"{API}/api/gpu/live", True)
    f_rt = ex.submit(get, f"{API}/api/render-tasks", True)
    f_jobs = ex.submit(get, f"{API}/api/jobs", True)
    f_q = {k: ex.submit(queue, p) for k, p in LANES.items()}
    f_s = {h: ex.submit(smi, h) for h in ("gpu33", "gpu36")}
    live, rt, jobs = f_live.result(), f_rt.result(), f_jobs.result()
    qs = {k: v.result() for k, v in f_q.items()}
    sm = {h: v.result() for h, v in f_s.items()}
t1 = time.strftime("%H:%M:%S")
rows = []
print(f"同一时刻（{t0} – {t1}）核对，面板接口 {API}\n")
print("| 卡 | 面板：在做什么 | 面板：队列 | 面板：利用率/显存/温度/功耗 | 直接 /queue（运行·排队 · client_id · ns_tag · 输出前缀） | 直接 nvidia-smi | 一致 |")
print("|---|---|---|---|---|---|---|")
for c in live["cards"]:
    hw = c.get("hw") or {}
    q = qs.get(c["lane"]) if c["lane"] else None
    s = sm.get(c["server"], {}).get(c["idx"], {})
    run0 = c["running"][0]["prompt_id"] if c["running"] else None
    ok_q = q is None or ((q["prompt_id"] == run0) and q["pending"] == c["queue_len"])
    ok_s = bool(s) and abs(float(s["mem"]) - float(hw.get("vram_used_mb") or 0)) < 1500
    rows.append({"card": c["id"], "who": c["who"], "q": q, "smi": s, "ok_queue": ok_q, "ok_smi": ok_s})
    qtxt = "—（无渲染道）" if q is None else f"{q['running']}·{q['pending']} · {q['client_id']} · {q['ns_tag'] or '无'} · {q['prefix']}"
    print(f"| {c['id']} | {c['who']}{(' · ' + c['agent']) if c.get('agent') else ''} | 排队 {c['queue_len']} | "
          f"{hw.get('util')}% · {round((hw.get('vram_used_mb') or 0) / 1024, 1)} GB · {hw.get('temp_c')}°C · {hw.get('power_w')}/{hw.get('power_limit_w')} W"
          f"{' · ' + c['throttle']['text'] if c.get('throttle') else ''} | {qtxt} | "
          f"{s.get('util')}% · {round(float(s.get('mem', 0)) / 1024, 1)} GB · {s.get('temp')}°C · {s.get('pw')}/{s.get('pl')} W | "
          f"{'✓' if ok_q and ok_s else '✗ 队列' if not ok_q else '✗ 硬件'} |")
c = rt["counts"]
active_jobs = sum(1 for j in jobs if j.get("state") in ("queued", "running"))
print(f"\n渲染任务：全部 {c['all']} = 等待 {c['pending']} + 渲染中 {c['rendering']} + 失败 {c['failed']} + 已完成 {c['done']}"
      f"（{'对得上' if c['all'] == c['pending'] + c['rendering'] + c['failed'] + c['done'] else '对不上'}）；来源 {rt['sources']}")
print(f"直接 /api/jobs（前 50 条）排队+运行 {active_jobs}；ComfyUI 各道运行+排队合计 {sum(q['running'] + q['pending'] for q in qs.values())}")
(HERE / "crosscheck.json").write_text(json.dumps({"at": t0, "api": API, "rows": rows, "counts": c, "sources": rt["sources"],
                                                  "jobs_active": active_jobs, "queues": qs, "smi": sm}, ensure_ascii=False, indent=1), encoding="utf-8")
