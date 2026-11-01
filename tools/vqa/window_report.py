r"""VQAGATE 11-01：最短看图窗口的效果账（总调度要求实测出图吞吐降多少）。
读 D:\ns_vqa\logs\switch.jsonl（ev=vqa_window 开 / 关、yield）和 data/producer/log.jsonl（laptop 道的 rendered），
按时间段算：窗口个数、每个窗口判了几条、出图方等了多少秒、laptop 道每小时出图张数（窗口启用前后各一段）。
    .venv/Scripts/python.exe tools/vqa/window_report.py --since 2026-11-01T21:00 [--before 2026-11-01T18:30..2026-11-01T19:30]
→ data/vqa/window_report.json"""
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SWITCH = Path(r"D:\ns_vqa\logs\switch.jsonl")


def rows(p):
    out = []
    for ln in Path(p).read_text(encoding="utf-8", errors="replace").splitlines() if Path(p).exists() else []:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def per_hour(evs, a, b):
    n = sum(1 for e in evs if a <= (e.get("ts") or "") < b)
    h = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    return {"from": a, "to": b, "rendered": n, "per_hour": round(n / h, 1) if h > 0 else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    ap.add_argument("--before", default="")
    a = ap.parse_args()
    sw = [e for e in rows(SWITCH) if (e.get("at") or "") >= a.since]
    opens = [e for e in sw if e.get("ev") == "vqa_window" and e.get("phase") == "open"]
    closes = [e for e in sw if e.get("ev") == "vqa_window" and e.get("phase") == "close"]
    rend = [e for e in rows(ROOT / "data/producer/log.jsonl") if e.get("ev") == "rendered" and str(e.get("lane", "")).startswith("laptop")]
    out = {"windows": len(opens), "judged": sum(int(c.get("served") or 0) for c in closes),
           "draw_waited_s": round(sum(float(c.get("draw_waited_s") or 0) for c in closes), 1),
           "with_windows": per_hour(rend, a.since, a.until)}
    if a.before and ".." in a.before:
        b0, b1 = a.before.split("..")
        out["before_windows"] = per_hour(rend, b0, b1)
        if out["before_windows"]["per_hour"] and out["with_windows"]["per_hour"] is not None:
            out["throughput_drop"] = round(1 - out["with_windows"]["per_hour"] / out["before_windows"]["per_hour"], 3)
    (ROOT / "data/vqa/window_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
