"""
RR（fredw-92 派，2026-10-31）：ep02 新配方（基模 24 步 + 只给首帧）整集重出后的逐镜质检 + 去抖 + 装配来源表。
只看像素，不看内容；不改 takes、不定稿。

用法：python tools/rr_ep02_newrecipe_qc.py SUBMIT_JSON OLD_TIMELINE OUT_DIR
  SUBMIT_JSON  = data/ab/motion_fix/rr_submit_ep02.json（各镜 job_id）
  OLD_TIMELINE = data/episodes/ep02_PREVIEW_未完成_H3原声.timeline.json（旧版各镜视频）
输出 OUT_DIR/：metrics.json（旧 / 新 / 去抖后 J4、节奏、jerk、结尾定住、鬼影筛查）、
  sources.timeline.json（装配用：J4 > 1.25 的镜用去抖副本，其他用新 take 原片）、
  dejudder/*.mp4、legs/<shot>_old_vs_new_legs_strip.jpg（腿部条带，人工看重影）
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "services" / "render_router"))
import motion_judder as MJ  # noqa: E402
from ns_render import motion_qc as MQ  # noqa: E402

J4_MAX = 1.25
PY = sys.executable


def job(jid: str) -> dict:
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:8800/api/jobs/{jid}", timeout=60))


def main(a):
    sub = json.loads(Path(a[0]).read_text(encoding="utf-8"))
    old_tl = json.loads(Path(a[1]).read_text(encoding="utf-8"))
    out = Path(a[2]).resolve()
    (out / "dejudder").mkdir(parents=True, exist_ok=True)
    (out / "legs").mkdir(parents=True, exist_ok=True)
    old = {sh["shot"]: sh for sh in old_tl["shots"] if sh.get("kind") == "video"}
    res, srcs = {}, []
    for s in sorted(sub, key=lambda x: int(x["shot"].split("S")[-1])):
        shot = s["shot"]
        takes = json.loads((ROOT / "data" / "renders" / "ep02" / shot.split("-")[1] / "takes.json").read_text(encoding="utf-8"))
        # 候选 = 首次 + 重出（中途跳切时换种子再出）；优先没有跳切的，其次 J4 低的
        cands = []
        for jid in [s["job_id"], *s.get("rerolls", [])]:
            # 以 takes.json 为准（API 重启中断、由 tools/rr_recover_video_takes.py 取回的 take 也算）
            t = next((t for t in takes["takes"] if t["stage"] == "video" and t.get("job_id") == jid), None)
            if t is None:
                j = job(jid)
                cands.append({"job_id": jid, "state": j.get("state"), "error": str(j.get("error"))[:200]})
                continue
            j = {"take": t["n"], "take_params": t.get("params") or {}}
            p = ROOT / "data" / t["file"]
            q = MQ.video_motion(p)          # 重算（含新的跳切检测）
            m, ser = MJ.analyze(p)
            cands.append({"job_id": jid, "state": "done", "take": j["take"], "file": t["file"], "j": j, "t": t, "p": p,
                          "q": q, "m": m, "ser": ser, "cut_s": (q.get("metrics") or {}).get("cut_s") or []})
        done = [c for c in cands if c["state"] == "done"]
        if not done:
            res[shot] = {"state": "not_done", "candidates": cands}
            continue
        # 先挑没跳切的，再挑运动质检不是“静止·不合格”的，再挑动作多的（静止镜头）/ J4 低的
        best = min(done, key=lambda c: (bool(c["cut_s"]), c["q"].get("verdict") == "fail",
                                        -(c["m"].get("pace_px_per_frame") or 0) if c["q"].get("verdict") == "fail"
                                        else c["m"].get("J4") or 9))
        j, t, new_p, q_new, m_new, ser_new = best["j"], best["t"], best["p"], best["q"], best["m"], best["ser"]
        r, tp = j, j.get("take_params") or {}
        old_p = ROOT / old[shot]["file"] if shot in old else None
        m_old, _ = MJ.analyze(old_p) if old_p and old_p.is_file() else ({}, None)
        q_old = MQ.video_motion(old_p) if old_p and old_p.is_file() else {}
        rec = {"candidates": [{"job_id": c["job_id"], "state": c["state"], "take": c.get("take"),
                               "cut_s": c.get("cut_s"), "J4": (c.get("m") or {}).get("J4")} for c in cands],
               "take": r["take"], "file": t["file"], "lane": t.get("gpu"), "render_s": tp.get("render_s"),
               "base": tp.get("base"), "steps": tp.get("steps"), "last_frame_used": tp.get("last_frame_used"),
               "new": {k: m_new.get(k) for k in ("J4", "J4_z", "pace_px_per_frame", "jerk", "ghost_low_p95", "frames")},
               "old": {k: m_old.get(k) for k in ("J4", "J4_z", "pace_px_per_frame", "jerk", "ghost_low_p95", "frames")},
               "old_file": old[shot]["file"] if shot in old else None,
               "new_qc": {"verdict": q_new.get("verdict"), "labels": q_new.get("labels"),
                          "frozen_tail_s": (q_new.get("metrics") or {}).get("frozen_tail_s"),
                          "cut_s": (q_new.get("metrics") or {}).get("cut_s")},
               "old_qc": {"verdict": q_old.get("verdict"), "labels": q_old.get("labels"),
                          "frozen_tail_s": (q_old.get("metrics") or {}).get("frozen_tail_s"),
                          "cut_s": (q_old.get("metrics") or {}).get("cut_s")}}
        use = new_p
        if (m_new.get("J4") or 0) > J4_MAX and not best["cut_s"]:   # 有跳切时 J4 被那一下突变拉高，补帧会把两个镜头糊在一起 → 不去抖
            dj = out / "dejudder" / f"{shot}_take{r['take']:03d}_dj.mp4"
            if not dj.is_file():
                subprocess.run([PY, str(ROOT / "tools" / "dejudder.py"), str(new_p), str(dj)], check=True)
            m_dj, _ = MJ.analyze(dj)
            rec["dejudder"] = {"file": dj.relative_to(ROOT).as_posix(),
                               **{k: m_dj.get(k) for k in ("J4", "J4_z", "pace_px_per_frame", "jerk")}}
            use = dj
        rec["assembly_file"] = use.relative_to(ROOT).as_posix()
        if old_p and old_p.is_file():   # 腿部条带（画面下 42%），人工看重影
            stem = out / "legs" / f"{shot}_old_vs_new"
            n = min(m_new.get("frames") or 0, m_old.get("frames") or 0)
            ld = ser_new["lowdiff"][: max(1, n - 33)]   # 下半身动得最多的 32 帧段（脚在动的地方）
            win = [sum(ld[i:i + 32]) for i in range(max(1, len(ld) - 31))]
            mid = max(0, min(win.index(max(win)), n - 33)) if win else 0
            rec["legs_range"] = [mid, mid + 32]
            subprocess.run([PY, str(ROOT / "tools" / "ab_motion_compare.py"), str(stem), f"old={old_p}", f"new={new_p}",
                            "--crop", "768:560:0:784", "--range", f"{mid}:{mid + 32}"], check=False)
            rec["legs_strip"] = f"{stem.relative_to(ROOT).as_posix()}_legs_strip.jpg"
        res[shot] = rec
        srcs.append({"shot": shot, "index": int(shot.split("S")[-1]), "kind": "video", "origin": "laptop",
                     "file": rec["assembly_file"]})
        print(shot, json.dumps({"new": rec["new"], "old": rec["old"], "dj": rec.get("dejudder", {}).get("J4"),
                                "qc": rec["new_qc"]}, ensure_ascii=False), flush=True)
    (out / "metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "sources.timeline.json").write_text(json.dumps({"shots": srcs}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
