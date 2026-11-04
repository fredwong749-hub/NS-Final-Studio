"""W46（总调度 05:4x 定：S2 / S3 已登记 158 帧 6.58 s，不重出）：已登记为当前的视频超过 6.0 s（C-08）→ 生成 <名>_le6.mp4
（tools/series10_video/clip_trim.py：尾部裁、首帧保留）→ 经 register_takes.register 登记成新视频版本（原 take 保留、不删），
postflight = 原版的门结论 + 时长复核（≤ 6.0 s 才 ok）→ 过了且项目方没定稿别的视频 → 设为当前。
night.loop_once 在 register_takes 之后每轮调（= “登记前先裁”：新登记的超长片同一轮就换成 _le6）。重复调无害（按 sha 去重）。

    python tools/series10_video/trim_takes.py --run series10_v2 [--eps 1,2] [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools/pipeline"))
import clip_trim as CT  # noqa: E402

MAX_S = CT.MAX_S


def active_video(shot: str, P) -> tuple[dict | None, dict]:
    d = P.load_takes(shot)
    n = (d.get("active") or {}).get("video")
    t = next((x for x in d.get("takes") or [] if x.get("stage") == "video" and x.get("n") == n), None)
    return t, d


def fix_shot(shot: str, P, RT, dur=CT.duration, trim=CT.trim_le, dry: bool = False) -> dict:
    t, d = active_video(shot, P)
    if not t or not t.get("file"):
        return {"shot": shot, "status": "no_video"}
    src = P.DATA / t["file"]
    if not src.is_file():
        return {"shot": shot, "status": "missing", "file": t["file"]}
    secs = dur(src)
    if not secs or secs <= MAX_S + CT.TOL_S:
        return {"shot": shot, "status": "ok", "n": t["n"], "secs": round(secs, 3)}
    if (t.get("params") or {}).get("trimmed_from") is not None:
        return {"shot": shot, "status": "already_trimmed_but_long", "n": t["n"], "secs": secs}
    if dry:
        return {"shot": shot, "status": "would_trim", "n": t["n"], "secs": round(secs, 3)}
    out = trim(src)
    new_s = dur(out)
    pf0 = t.get("postflight") or {}
    ok = bool(pf0.get("ok", True)) and 0 < new_s <= MAX_S + CT.TOL_S
    item = {"shot": shot, "stage": "video", "file": str(out), "seed": t.get("seed") or 0, "prompt": t.get("prompt") or "",
            "frames": t.get("frames"), "from_first": t.get("from_first"), "label": f"裁到 ≤6 s（原 v{t['n']}，{secs:.2f}→{new_s:.2f} s）",
            "origin": {"trimmed_from": t["n"], "trimmed_by": "tools/series10_video/trim_takes.py（W46，C-08）",
                       "src_secs": round(secs, 3), "secs": round(new_s, 3)},
            "postflight": {"ok": ok, "items": list(pf0.get("items") or []) + [
                {"id": "C08", "status": "pass" if ok else "fail", "detail": f"时长 {new_s:.3f} s（≤ {MAX_S} s）"}],
                "reasons": list(pf0.get("reasons") or []) + ([] if ok else [f"裁后时长 {new_s:.3f} s 仍不合规或原版门没过"])},
            "activate": True}
    r = RT.register(item, label=item["label"])
    if r.get("status") == "skipped" and r.get("n") is not None and ok:
        # W46（06:16 S3）：裁出来的片与已登记的某版同内容（例：v1 变体原片裁后 == t2）→ register 跳过；当前仍是超长版 →
        # 换回那版（它当初过门 + C08；项目方定稿了别的视频则不动）
        d2 = P.load_takes(shot)
        lock = (d2.get("locked") or {}).get("video")
        dup = next((x for x in d2.get("takes") or [] if x.get("stage") == "video" and x.get("n") == r["n"]), None)
        if dup and (dup.get("postflight") or {}).get("ok") and lock in (None, r["n"]) \
                and (d2.get("active") or {}).get("video") == t["n"]:
            P.set_active(shot, "video", r["n"], reason=f"C-08：当前 v{t['n']} {secs:.2f} s 超 6 s，裁后与 v{r['n']} 同内容 → 换回 v{r['n']}",
                         actor="tools/series10_video/trim_takes.py（W46）")
            return {"shot": shot, "status": "reactivated_dup", "from_n": t["n"], "n": r["n"], "active": True,
                    "secs": round(secs, 3), "new_secs": round(new_s, 3), "file": str(out)}
    if r.get("status") == "registered":
        def _mark(data, _n=r["n"], _src=t["n"]):
            for x in data["takes"]:
                if x["stage"] == "video" and x["n"] == _n:
                    x.setdefault("params", {})["trimmed_from"] = _src
        P.mutate_takes(shot, _mark, op="trim_takes.mark", by="tools/series10_video/trim_takes.py",
                       op_id=f"trim_takes:{shot}:{r['n']}")
    return {"shot": shot, "status": r.get("status"), "from_n": t["n"], "n": r.get("n"), "active": r.get("active"),
            "secs": round(secs, 3), "new_secs": round(new_s, 3), "file": str(out)}


def shots_of(run: str, eps: list[int] | None, P) -> list[str]:
    base = P._run_renders(run)
    out = []
    for tj in sorted(base.glob("ep*/S*/takes.json")):
        ep, s = tj.parent.parent.name, tj.parent.name
        if eps and int(ep[2:]) not in eps:
            continue
        out.append(f"{ep}-{s}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--eps", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    os.environ["NS_RUN"] = a.run
    import register_takes as RT
    from ns_render import pipeline as P
    eps = [int(x) for x in a.eps.split(",") if x.strip()] or None
    rows = [fix_shot(s, P, RT, dry=a.dry) for s in shots_of(a.run, eps, P)]
    changed = [r for r in rows if r["status"] not in ("ok", "no_video")]
    print(json.dumps({"at": time.strftime("%F %T"), "checked": len(rows), "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
