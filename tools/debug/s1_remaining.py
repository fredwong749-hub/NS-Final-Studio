"""第一季剩余采集（只读；总调度 FOCUS #5）：在服务器 repo 目录跑（经 rsh 从 stdin 喂给 python3 -），打印一行 JSON：
  {host, at, control:{only_n, hold_lanes, paused, reason_kind}, holds:{文件: [对象]}, shots:{sid: {first, last, video}}}
first / last 取 producer registry.json 的对象（status / reason / waiting_for / take），video 取 vidgen state（video10_srv）。
用法：python3 s1_remaining.py <producer repo> <video repo> <host>
"""
import glob
import json
import os
import sys
import time

repo, vrepo, host = sys.argv[1], sys.argv[2], sys.argv[3]


def jl(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return d


out = {"host": host, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "shots": {}, "holds": {}}
c = jl(os.path.join(repo, "data/producer/control.json"), {}) or {}
out["control"] = {"only_n": len(c.get("only") or []), "hold_lanes": c.get("hold_lanes"), "paused": c.get("paused"),
                  "reason_kind": c.get("reason_kind"), "expires_at": c.get("expires_at")}
for f in glob.glob(os.path.join(repo, "data/autopilot/*_hold.json")):
    d = jl(f, {}) or {}
    if d.get("active") is False:
        continue
    objs = list(d.get("objects") or [])
    for it in d.get("shots") or []:
        if str(it.get("expires_at") or "9999") > out["at"]:
            objs += it.get("objects") or [f"first:{it.get('shot')}"]
    for sid, it in (d.get("items") or {}).items():
        if str(it.get("expires_at") or "9999") > out["at"]:
            objs.append(f"video:{sid}" if "video_hold" in f else sid)
    if objs:
        out["holds"][os.path.basename(f)] = {"objects": objs, "expires_at": d.get("expires_at"), "reason_kind": d.get("reason_kind")}
reg = jl(os.path.join(repo, "data/producer/registry.json"), {}) or {}
for E in reg.get("episodes") or []:
    for S in E.get("shots") or []:
        rec = {}
        for k in ("assets", "first", "last"):
            o = (S.get("objects") or {}).get(k) or {}
            rec[k] = {x: o.get(x) for x in ("status", "reason", "waiting_for", "take", "gate") if o.get(x) not in (None, "")}
        out["shots"][S["shot"]] = rec
RUN = (jl(os.path.join(repo, "config/pipeline/runs.json"), {}) or {}).get("primary")   # 总调度 11-02：不写死剧名（arch_scan hard_run）
st = jl(os.path.join(vrepo, f"data/pipeline/runs/{RUN}/video", f"state_{host}.json"), {}) or {}
jobs = jl(os.path.join(vrepo, f"data/pipeline/runs/{RUN}/video/jobs.json"), {}) or {}
mine = {m["shot"]: m for m in jobs.get("shots") or [] if m.get("host") == host}
for sid, m in mine.items():
    r = (st.get("shots") or {}).get(sid) or {}
    v = {"status": r.get("status") or "not_started", "renders": len(r.get("renders") or []),
         "busy": any(x.get("state") in ("submitted", "fetched", "scoring") for x in r.get("renders") or []),
         "variants": len(m.get("variants") or {}), "route": m.get("route"), "hold": m.get("hold")}
    out["shots"].setdefault(sid, {})["video"] = v
print(json.dumps(out, ensure_ascii=False))
