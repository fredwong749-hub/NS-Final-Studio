"""VIDEO-RCA：景别退档 × 提示词里有无画外下半身部件（鞋 / 高跟 / 脚 / 腿）——现有生产打分的分组统计（不另出片）。
景别实测 = score_clip face_h_med 档位（K-REN-122）；“退档”= 实测比要求远 ≥1 档（更远）。
提示词 = video/prompts/<镜>.<变体>.txt（build_jobs 写的系统编译稿；旧变体缺稿则跳过）。
    .venv/Scripts/python.exe tools/video_rca/size_vs_prompt.py
"""
import collections, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/video_rca"))
import rates as RT
VID = ROOT / "data/pipeline/runs/series10_v1/video"
LOWER = re.compile(r"\b(heels?|stilettos?|shoes?|feet|foot|toes?|ankles?|legs?|calf|calves|knees?|hem)\b", re.I)
CLOSE = {"极近特写", "大特写", "特写", "近景", "中近景", "中景"}

def main():
    tab = collections.Counter(); ex = collections.defaultdict(list)
    for r in RT.load_renders():
        s = r["score"]; want = RT.SIZE_IDX.get(s.get("size_wanted") or ""); fh = s.get("face_h_med")
        if want is None or fh is None or s.get("size_wanted") not in CLOSE:
            continue
        p = VID / "prompts" / f"{r['shot']}.{r['variant']}.txt"
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        body = txt.split("integrated_multimodal_description:")[-1].split("overall_soundscape:")[0]
        hits = sorted({m.group(0).lower() for m in LOWER.finditer(body)})
        k = "提到画外下半身" if hits else "没提"
        farther = RT.size_class(fh) - want >= 1
        tab[(k, farther)] += 1
        if farther: ex[k].append(f"{r['shot']}__{r['variant']} 要{s['size_wanted']} 测{s.get('size_measured')} {hits}")
    out = {k: {"退档": tab[(k, True)], "总": tab[(k, True)] + tab[(k, False)]} for k in ("提到画外下半身", "没提")}
    print(json.dumps(out, ensure_ascii=False)); print(json.dumps({k: v[:8] for k, v in ex.items()}, ensure_ascii=False, indent=1))
main()
