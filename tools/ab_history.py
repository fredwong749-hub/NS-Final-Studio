"""
从版本历史做 旧做法 vs 新做法 对比表（不出新图）：旧 = 用项目方成品定妆图（lin_wan.png）锁脸的版本（没有就用最早的版本），
新 = 当前版本（2026-10-30 重出：两段式 + 母版身份 + 调色 + 多候选评分）。旧版本用同一个评分器补打分。

    uv run python tools/ab_history.py --shots ep01-S3 ep01-S5 ep01-S6 ep02-S1 ep04-S6 ep06-S5 --out golden/quality_v2
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ab_quality import _lines, label, sheet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", nargs="*", default=["ep01-S3", "ep01-S5", "ep01-S6", "ep02-S1", "ep04-S6", "ep06-S5"])
    ap.add_argument("--out", default="golden/quality_v2")
    args = ap.parse_args()
    client, script = ComfyClient(), P.load_script()
    rows, totals = [], {"old": [], "new": []}
    for sid in args.shots:
        data = P.load_takes(sid)
        imgs = [t for t in data["takes"] if t["stage"] == "image" and not (t.get("qc") or {}).get("nudity")]
        old = next((t for t in imgs if "lin_wan.png" in (t.get("reference") or "")), imgs[0] if imgs else None)
        new = next((t for t in imgs if t["n"] == data["active"].get("image")), None)
        if not old or not new or old is new:
            print(sid, "缺旧版本或新版本，跳过")
            continue
        c = P.compile_with_edits(script, sid, P.available_loras(client))
        plan = P._ref_plan(c, sid)
        score_fn = P._default_score(client, c, plan.face.path if plan.face else None)
        old_sc = score_fn(P.DATA / old["file"], old.get("qc"))
        totals["old"].append(old_sc["total"])
        totals["new"].append((new.get("score") or {}).get("total") or 0)
        rows.append([label(Image.open(P.DATA / old["file"]), [f"旧 v{old['n']} {old.get('workflow')}",
                                                              *_lines(old_sc, old.get("seconds"))]),
                     label(Image.open(P.DATA / new["file"]), [f"新 v{new['n']} {new.get('workflow')}",
                                                              *_lines(new.get("score"), new.get("seconds"))])])
        print(sid, "旧", old_sc["total"], "新", (new.get("score") or {}).get("total"), flush=True)
    out = ROOT / args.out / "sheet_old_vs_new.jpg"
    sheet(rows, ["旧：定妆图锁脸（Turbo 单张）", "新：两段式 + 母版 + 调色 + 多候选"], out, args.shots[:len(rows)])
    avg = {k: round(sum(v) / len(v), 3) if v else None for k, v in totals.items()}
    print("平均分", avg, "对比表", out)


if __name__ == "__main__":
    sys.exit(main())
