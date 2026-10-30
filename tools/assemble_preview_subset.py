"""
预览成片：只装配一集里的部分镜头（fredw-92/D1，2026-10-31）。

用途：某些镜头还在等补出（如 ep02 的 S8、S11 等长镜头方案）时，先用其余镜头合一版预览，检查装配 / 校色 / 混音流程。
跳过的镜头连同它们的台词 / 独白一起去掉；输出文件名带“预览·<镜头> 待补”，永远不叫 final、不建 epXX.mp4 别名。
其余与 tools/assemble_episode.py 相同（ns_post.assemble.assemble_episode；Kokoro 配音、H3 原声、-14 LUFS）。

    .venv\\Scripts\\python.exe tools/assemble_preview_subset.py ep02 --skip 8 11 --color-match
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.assemble import Settings, assemble_episode, load_episode  # noqa: E402
from ns_post.tts import KokoroBackend, SenseVoiceAsr, load_voice_config  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode")
    ap.add_argument("--skip", nargs="+", type=int, required=True, help="镜头序号（S 后面的数字）")
    ap.add_argument("--script", default=str(ROOT / "data" / "import" / "script_v2.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "episodes"))
    ap.add_argument("--color-match", dest="cm", action="store_true", default=None)
    ap.add_argument("--no-color-match", dest="cm", action="store_false")
    ap.add_argument("--no-asr", action="store_true")
    a = ap.parse_args()
    ep = int(a.episode.lower().removeprefix("ep"))
    episode = load_episode(Path(a.script), ep)
    keep = [s for s in episode["shots"] if int(s["index"]) not in set(a.skip)]
    if len(keep) == len(episode["shots"]):
        raise SystemExit("--skip 没有命中任何镜头")
    # 装配器按“第几镜 = index”定位台词与片段：保留的镜头重编号 1..n，片段按原序号先找好（sources 参数）
    from ns_post.assemble import find_source
    sources, renum = {}, []
    for pos, s in enumerate(keep, 1):
        sources[pos] = find_source(ep, int(s["index"]), allow_laptop_video=True)
        renum.append({**s, "index": pos, "orig_index": int(s["index"])})
    print("镜头对应（新序号 → 原镜头）：", ", ".join(f"{s['index']}→S{s['orig_index']}" for s in renum))
    episode = {**episode, "shots": renum}
    cfg = load_voice_config()
    tts = KokoroBackend(cfg, num_threads=4)
    asr = None if a.no_asr else SenseVoiceAsr(cfg, num_threads=4)
    out = Path(a.out)
    work_out = out / f"_subset_ep{ep:02d}"
    work_out.mkdir(parents=True, exist_ok=True)
    tl = assemble_episode(episode, work_out, tts=tts, asr=asr, settings=Settings(color_match=a.cm),
                          voices_cfg=cfg, allow_laptop_video=True, sources=sources)
    tag = f"ep{ep:02d}_预览·{' '.join(f'S{i}' for i in sorted(a.skip))} 待补"
    src = Path(tl["deliveries"]["1080p"]["file"])
    src = src if src.is_absolute() else ROOT / "data" / src if not (ROOT / src).exists() else ROOT / src
    dst = out / f"{tag}.mp4"
    shutil.move(str(src), dst)
    tl["deliveries"]["1080p"]["file"] = str(dst.relative_to(ROOT)).replace("\\", "/")
    tl["preview_subset"] = {"skipped": sorted(a.skip), "note": "预览：跳过的镜头待补出后再合正式版"}
    (out / f"{tag}.timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in work_out.glob("*"):
        p.unlink() if p.is_file() else shutil.rmtree(p)
    work_out.rmdir()
    print(json.dumps({"file": str(dst), "duration_s": tl["duration_s"], "loudness": tl["loudness"]["measured"],
                      "color_match": [(s["index"], bool((s.get("color_match") or {}))) for s in tl["shots"]]},
                     ensure_ascii=False, indent=1))
    for w in tl["warnings"]:
        print("WARN", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
