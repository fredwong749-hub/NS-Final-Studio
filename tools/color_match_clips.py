"""
逐镜校色（后期，CPU）：把 MiniMax H3 FL2V 片段的颜色拉回到我们自己的调色首帧/尾帧（不是相邻镜头）。
方法与依据见 services/post/ns_post/colormatch.py 与 docs/research/h3_deep/00_summary.md §颜色。

    uv run python tools/color_match_clips.py --shots ep01-S1 ep01-S3 --dry-run    # 只测量：偏差 + 预计校后 dE
    uv run python tools/color_match_clips.py --episode 1                          # 写 <clip>_cc.mp4 + _cc.json
    uv run python tools/color_match_clips.py --episode 1 --all-takes --dry-run    # 本地所有视频版本都测
    uv run python tools/color_match_clips.py --clip x.mp4 --first a.png --last b.png

规则：不改原片（输出 <clip>_cc.mp4，音轨直接复制）；只用 CPU；没有本地匹配的首帧时跳过并说明。
默认只处理装配会用的那条视频（gpu3 当前版本；--allow-laptop-video 时退回本机版本）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.assemble import DATA, find_source  # noqa: E402
from ns_post.colormatch import CC_SUFFIX, CcSettings, correct_clip, measure_clip, short_summary  # noqa: E402
from ns_post.ffmpeg import FFmpeg  # noqa: E402


def _shot(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"ep0*(\d+)-?s0*(\d+)", s.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"not a shot id (ep01-S1): {s}")
    return int(m.group(1)), int(m.group(2))


def _ep(s: str) -> int:
    m = re.fullmatch(r"(?:ep)?0*(\d+)", s.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"not an episode: {s}")
    return int(m.group(1))


def clips_for(ep: int, idx: int, *, all_takes: bool, allow_laptop: bool, data: Path = DATA) -> list[Path]:
    if all_takes:
        out = []
        for tree in ("renders_gpu3", "renders"):
            d = data / tree / f"ep{ep:02d}" / f"S{idx}"
            out += [p for p in sorted((d / "takes").glob("video_*.mp4"))
                    if not p.stem.endswith(CC_SUFFIX) and not p.stem.endswith("_4k")]
        return out
    src = find_source(ep, idx, data=data, allow_laptop_video=allow_laptop)
    return [Path(src["path"])] if src["kind"] == "video" else []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", nargs="*", type=_shot, default=[])
    ap.add_argument("--episode", nargs="*", type=_ep, default=[])
    ap.add_argument("--clip", nargs="*", default=[], help="explicit clip file(s)")
    ap.add_argument("--first", help="first keyframe override (with --clip)")
    ap.add_argument("--last", help="last keyframe override (with --clip)")
    ap.add_argument("--dry-run", action="store_true", help="measure only (drift + predicted after); write nothing")
    ap.add_argument("--all-takes", action="store_true", help="every local takes/video_NNN.mp4, not just the active")
    ap.add_argument("--allow-laptop-video", action="store_true")
    ap.add_argument("--strength", type=float, default=CcSettings.strength)
    ap.add_argument("--region", choices=("centre", "full"), default=CcSettings.region)
    ap.add_argument("--report", help="also write all reports to this json file")
    a = ap.parse_args()

    s = CcSettings(strength=a.strength, region=a.region)
    shots = list(a.shots)
    script = json.loads((DATA / "import" / "script_v2.json").read_text(encoding="utf-8"))
    for ep in a.episode:
        e = next((x for x in script["episodes"] if int(x["number"]) == ep), None)
        shots += [(ep, int(x["index"])) for x in (e or {}).get("shots", [])]
    jobs = [(f"ep{ep:02d}-S{i}", c) for ep, i in shots
            for c in clips_for(ep, i, all_takes=a.all_takes, allow_laptop=a.allow_laptop_video)]
    jobs += [(Path(c).stem, Path(c)) for c in a.clip]
    if not jobs:
        print("no clips found")
        return 1
    ff = FFmpeg.discover()
    reports = []
    for key, clip in jobs:
        print(f"{key}  {clip.relative_to(ROOT) if clip.resolve().is_relative_to(ROOT) else clip}")
        first = a.first if a.clip and clip in map(Path, a.clip) else None
        last = a.last if a.clip and clip in map(Path, a.clip) else None
        if a.dry_run:
            rep = measure_clip(clip, first, last, ff=ff, s=s)
            rep.pop("_plan", None)
            rep.pop("_last_ref", None)
        else:
            rep = correct_clip(clip, first, last, ff=ff, s=s)
        rep["shot"] = key
        reports.append(rep)
        kf = rep["keyframes"]
        print(f"  first keyframe: {kf['first']['file'] or '—'}   last keyframe: {kf['last']['file'] or '—'}")
        if rep.get("plan") is None:
            print(f"  SKIP: {rep.get('error')}")
            continue
        sm = rep["before"]["summary"]
        for p in ("frame0", "mid", "end"):
            d = sm[p]["vs_ref"]
            print(f"  {p:6} f{sm[p]['frame']:<4} dE {d['dE']:5.2f}  dL {d['dL']:+6.2f}  da {d['da']:+5.2f}  "
                  f"db {d['db']:+5.2f}  dChroma {d['dChroma']:+5.2f}  dContrast {d['dContrast']:+5.2f}")
        if "comparable" in sm:
            c = sm["comparable"]
            d = c["at_until"]
            print(f"  same-picture window f0..f{c['until_frame']}: dE at f{c['until_frame']} {d['dE']:.2f}  "
                  f"dL {d['dL']:+.2f}  da {d['da']:+.2f}  db {d['db']:+.2f}  dChroma {d['dChroma']:+.2f}  "
                  f"dContrast {d['dContrast']:+.2f}  (window mean dE {c['mean_dE']:.2f})")
        aft = "after" if "after" in rep else "predicted_after"
        print(f"  plan: end ref = {rep['plan']['end_reference']}, dark = {rep['plan']['dark']}, "
              f"identity = {rep['plan']['identity']}; {'; '.join(rep['plan']['notes'])}")
        print(f"  before {short_summary(rep, 'before')}\n  {aft:15} {short_summary(rep, aft)}")
        if rep.get("output"):
            print(f"  wrote {rep['output']}")
    if a.report:
        Path(a.report).write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
