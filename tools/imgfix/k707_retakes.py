"""K-REN-707 上线收尾（总调度 11-02）：sv-04 部署前（服务器 producer 还用旧代码现编提示词）这 68 镜出的近景 / 特写首帧版本清单。
契约没过的不管；过了的列给 VQAGATE 复核景别；复核不合格的用 producer reject（counted=false）驳回。

    .venv/Scripts/python.exe tools/imgfix/k707_retakes.py list --until "2026-11-02T03:30:00" [--since "2026-11-02T00:06:00"]
    .venv/Scripts/python.exe tools/imgfix/k707_retakes.py reject --shots ep03-S4:5,ep06-S1:3 --by "<授权>"
输出 data/ab/imgfix/k707_retakes.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPACT = ROOT / "data/ab/imgfix/k706_impact.json"
OUT = ROOT / "data/ab/imgfix/k707_retakes.json"
CLOSE = ("极近特写", "大特写", "特写", "中近景", "近景")


def listing(since: str, until: str) -> dict:
    shots = json.loads(IMPACT.read_text(encoding="utf-8")).get("changed_v2") or json.loads(IMPACT.read_text(encoding="utf-8"))["changed"]
    jobs = {j["shot"]: j for j in json.loads((ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json").read_text(encoding="utf-8"))["jobs"]}
    rows = []
    for sid in shots:
        if (jobs.get(sid) or {}).get("size") not in CLOSE:
            continue
        ep, sh = int(sid[2:4]), sid.split("-")[1]
        tk = ROOT / f"data/renders/ep{ep:02d}/{sh}/takes.json"
        if not tk.exists():
            continue
        d = json.loads(tk.read_text(encoding="utf-8"))
        ts = d.get("takes", [])
        ts = ts if isinstance(ts, list) else list(ts.values())
        act = (d.get("active") or {}).get("image")
        for t in ts:
            if t.get("stage") != "image" or not (since <= str(t.get("created_at") or "") < until):
                continue
            pf = t.get("postflight") or {}
            rows.append({"shot": sid, "n": t.get("n"), "file": t.get("file"), "created_at": t.get("created_at"),
                         "contract_ok": pf.get("ok"), "active": t.get("n") == act, "long_legs_in_prompt": "长腿" in str(t.get("prompt") or ""),
                         "lane": (t.get("producer") or {}).get("lane")})
    res = {"since": since, "until": until, "takes": rows, "to_vqagate": [r for r in rows if r["contract_ok"]],
           "note": "契约没过的不管；to_vqagate = 契约过了、待看图复核景别（Q3 / 景别退档）"}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def reject(pairs: list[str], by: str) -> None:
    for p in pairs:
        sid, n = p.split(":")
        r = subprocess.run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), "reject", "--obj", f"first:{sid}", "--n", n,
                            "--reason", "K-REN-707 上线前旧提示词（近景 / 特写注入下半身描述），看图复核景别不合格（不计次）", "--by", by],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(sid, n, r.returncode, r.stderr[-200:])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv
    if a[1] == "list":
        r = listing(a[a.index("--since") + 1] if "--since" in a else "2026-11-02T00:00:00", a[a.index("--until") + 1])
        print(len(r["takes"]), "takes；契约过的", len(r["to_vqagate"]))
    elif a[1] == "reject":
        reject(a[a.index("--shots") + 1].split(","), a[a.index("--by") + 1] if "--by" in a else "IMGFIX")
