"""VID-LOOP（11-06）一次性修复：口型重出死循环（K-EDT-805）把一镜打回 N 次后留下的烂状态——
state_<host>.json 里该镜 status=rendering / pending、chosen=None、renders 空或只剩几条、superseded 里堆着几百条同一首帧的作废版本。

做什么（默认只打印，加 --apply 才写）：
  1. 备份 state_<host>.json → state_<host>.json.bak_viloop_<时间>（redo_requests.json 同样备份）
  2. 该镜：没有在出 / 在打分的版本才动；把 rule=K-EDT-805 作废、首帧 = 现首帧（jobs.json 里本镜的 first_frame；本镜不在本机作业时
     取 renders / superseded 里最新一条的首帧）的版本拿回 renders（按 变体+seed 去重，取最新）；lip_redo_n 记成上限（不再作废）、
     lip_redo_capped=true；然后定下：有过门的 → done + penalty 最小；只有没过门的 → best_effort + penalty 最小（L-196）；
     一条打分都没有 → pending（让 vidgen 重新出）
  3. data/director/redo_requests.json：该镜所有 pending 的单改 status=capped（旧版 vidgen 也不会再消费）
先决条件：该机的 vidgen 必须先停（它把 state 放在内存里、每 10 秒整份写回，跑着时改文件会被覆盖）；改完再起。
服务器上跑：cd /root/work/fredw/offline_20261101/repo && <venv>/bin/python tools/series10_video/repair_lip_loop.py --run series10_v2 --host gpu36 --shot ep01-S1 --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ctx as RC  # noqa: E402
import vidgen as VG  # noqa: E402


def current_first_frame(sid: str, rec: dict, jobs: dict) -> str | None:
    for s in jobs.get("shots") or []:
        if s.get("shot") == sid and s.get("first_frame"):
            return s["first_frame"]
    rows = [x for x in (rec.get("renders") or []) + (rec.get("superseded") or []) if x.get("first_frame")]
    if not rows:
        return None
    return max(rows, key=lambda x: float(x.get("t_done") or x.get("t_sub") or 0))["first_frame"]


def repair(rec: dict, first_frame: str | None, cap: int) -> dict:
    """纯函数（可单测）：拿回作废版本 + 标上限 + 定下。返回摘要"""
    before = {"status": rec.get("status"), "chosen": rec.get("chosen"), "renders": len(rec.get("renders") or []),
              "superseded": len(rec.get("superseded") or [])}
    if VG.in_flight(rec):
        return {"skipped": "有在出 / 在打分的版本，不动", "before": before}
    restored = VG.restore_lip_superseded(rec, first_frame)
    rec["lip_redo_n"] = max(VG.lip_redo_count(rec), cap)
    rec["lip_redo_capped"] = True
    if any(x.get("state") == "scored" for x in rec.get("renders") or []):
        status = VG.settle_rec(rec)
    else:
        rec.update(status="pending", chosen=None)
        status = "pending"
    rec["lip_loop_repaired"] = {"t": time.time(), "restored": restored, "first_frame": first_frame, "status": status}
    return {"before": before, "restored": restored, "first_frame": first_frame,
            "after": {"status": status, "chosen": rec.get("chosen"), "renders": len(rec.get("renders") or []),
                      "superseded": len(rec.get("superseded") or []), "lip_redo_n": rec["lip_redo_n"]}}


def cap_requests(req: dict, sid: str) -> int:
    n = 0
    for q in req.get("requests") or []:
        if q.get("shot") == sid and q.get("status", "pending") == "pending":
            q["status"] = "capped"
            n += 1
    return n


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--shot", required=True)
    ap.add_argument("--apply", action="store_true", help="真写（默认只打印将要做的事）")
    a = ap.parse_args(argv)
    vid = RC.vid_dir(a.run)
    state_p = vid / f"state_{a.host}.json"
    st = json.loads(state_p.read_text(encoding="utf-8"))
    rec = (st.get("shots") or {}).get(a.shot)
    if rec is None:
        print(json.dumps({"error": f"{a.shot} 不在 {state_p}"}, ensure_ascii=False))
        return 2
    jobs = VG.jload(vid / "jobs.json", {}) or {}
    ff = current_first_frame(a.shot, rec, jobs)
    res = repair(rec, ff, VG.lip_redo_cap())
    req = VG.jload(VG.LIP_REDO, {}) or {"requests": []}
    res["requests_capped"] = cap_requests(req, a.shot)
    res["apply"] = a.apply
    if a.apply and not res.get("skipped"):
        tag = time.strftime("bak_viloop_%m%d%H%M%S")
        shutil.copy2(state_p, state_p.with_name(state_p.name + "." + tag))
        VG.jsave(state_p, st)
        if VG.LIP_REDO.exists():
            shutil.copy2(VG.LIP_REDO, VG.LIP_REDO.with_name(VG.LIP_REDO.name + "." + tag))
        VG.jsave(VG.LIP_REDO, req)
        res["backup"] = tag
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
