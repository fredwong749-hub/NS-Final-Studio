"""
画质 A/B（research v6 §7，只用非成人镜头）：同一组种子，对比不同出图做法，出带分数的对比表。

    uv run python tools/ab_quality.py --out golden/quality_v2 --shots ep01-S3 ep01-S5 --variants old new
    uv run python tools/ab_quality.py --out golden/visual_spec_pilot --pilot          # ep01–ep03 非成人：script vs spec
    uv run python tools/ab_quality.py --out golden/quality_v2 --last ep01-S3 --last-models turbo base

变体：
  old   旧做法：项目方成品定妆图裁成画布比例做参考 + 剧本透传提示词，不调色
  new   身份底板 + 作用说明 + Leica 措辞 + 调色（色调参考图）
  spec  new + 画面说明层（Frame Spec）拼装的提示词
渲染在沙箱（<out>/work，不动 data/renders 的版本），每张都用 C5 评分器打分；对比表 <out>/sheet_*.jpg + results.json。
成人镜头一律跳过。
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ns_agent.compiler import compile_shot
from ns_render import pipeline as P
from ns_render import score as S
from ns_render.comfy_client import ComfyClient

ROOT = Path(__file__).resolve().parent.parent
FONT = "C:/Windows/Fonts/msyh.ttc"
VARIANTS = {
    "old": {"ref_mode": "portrait", "method": "script", "grade": False},
    "new": {"ref_mode": "plate", "method": "script", "grade": True},
    "spec": {"ref_mode": "plate", "method": "spec", "grade": True},
}
SEEDS = (20261030, 777)


def _font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def sandbox(out: Path, variant: str):
    work = out / "work" / variant
    P.DATA = work
    P.RENDERS = work / "renders"
    P.QC_LOG = work / "renders" / "qc_log.jsonl"
    return work


def non_adult(script, sid) -> bool:
    ep, s = P.find_shot(script, sid)
    return not compile_shot(ep, s, script.globals, set()).adult


def score_take(client, script, sid, take, variant, plate_override=None) -> dict:
    """统一用新评分器给每张图打分（old 变体也按同一 facts 与 M 底板评分，才能横比）"""
    c = P.compile_with_edits(script, sid, P.available_loras(client), method="script")
    plan = P._ref_plan(c, sid)
    fn = P._default_score(client, c, plate_override or (plan.face.path if plan.face else None))
    return fn(P.DATA / take.file, take.qc)


def label(im: Image.Image, lines: list[str], width=360) -> Image.Image:
    im = im.convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)))
    pad = 22 * len(lines) + 8
    out = Image.new("RGB", (im.width, im.height + pad), (20, 20, 20))
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    f = _font(15)
    for i, t in enumerate(lines):
        d.text((6, im.height + 4 + 22 * i), t, fill=(240, 240, 240), font=f)
    return out


def sheet(cells: list[list[Image.Image]], titles: list[str], path: Path, row_titles: list[str]):
    cw = max(c.width for row in cells for c in row if c)
    ch = max(c.height for row in cells for c in row if c)
    head, left = 36, 120
    W_, H_ = left + cw * len(titles), head + ch * len(cells)
    out = Image.new("RGB", (W_, H_), (10, 10, 10))
    d = ImageDraw.Draw(out)
    for j, t in enumerate(titles):
        d.text((left + j * cw + 8, 6), t, fill=(255, 220, 120), font=_font(20))
    for i, row in enumerate(cells):
        d.text((6, head + i * ch + 8), row_titles[i], fill=(255, 220, 120), font=_font(20))
        for j, c in enumerate(row):
            if c:
                out.paste(c, (left + j * cw, head + i * ch))
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, quality=88)
    return path


def _lines(sc: dict | None, secs) -> list[str]:
    if not sc:
        return [f"{secs}s"]
    p = sc.get("parts", {})
    miss = "；".join(sc.get("missing", []))[:22]
    return [f"总 {sc.get('total')}  剧本 {p.get('fidelity', '-')}  脸 {p.get('face', '-')}",
            f"色 {p.get('colour', '-')} 锐 {p.get('sharp', '-')} 焦外 {p.get('bokeh', '-')} {secs}s",
            f"缺：{miss}" if miss else "缺：—"]


def run_first(client, script, out, shots, variants, seeds, results):
    for v in variants:
        cfg = VARIANTS[v]
        sandbox(out, v)
        for sid in shots:
            for seed in seeds:
                if any(r["variant"] == v and r["shot"] == sid and r["seed"] == seed for r in results):
                    continue   # 续跑
                t0 = time.time()
                try:
                    take = P.render_image(client, script, sid, seed=seed, candidates=1, rounds=2, score_fn=None,
                                          grade=cfg["grade"], ref_mode=cfg["ref_mode"], method=cfg["method"],
                                          face_lock=True)
                except P.ComfyError as e:   # 裸露质检两轮都不过等：记下来，继续下一镜
                    print(f"[{v}] {sid} seed {seed}: 失败 {e}", flush=True)
                    continue
                gen = time.time() - t0
                t1 = time.time()
                sc = score_take(client, script, sid, take, v)
                results.append({"variant": v, "shot": sid, "seed": seed, "file": str(P.DATA / take.file),
                                "raw": str(P.DATA / take.raw_file) if take.raw_file else None,
                                "gen_seconds": round(gen, 1), "comfy_seconds": take.seconds,
                                "score_seconds": round(time.time() - t1, 1), "score": sc,
                                "prompt": take.prompt, "references": take.references})
                print(f"[{v}] {sid} seed {seed}: {take.seconds}s 生成，评分 {sc.get('total')} "
                      f"缺 {sc.get('missing')}", flush=True)
                (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def run_last(client, script, out, shots, models, results, base_variant="new"):
    for mname in models:
        model = P.QWEN_TURBO if mname == "turbo" else P.W.QwenModel(unet=P.QWEN_BASE.unet, turbo=False, steps=25,
                                                                         cfg=1.0)
        for sid in shots:
            work = sandbox(out, base_variant)
            takes = P.load_takes(sid)
            first = next(t for t in takes["takes"] if t["stage"] == "image" and t["seed"] == SEEDS[0])
            P.set_active(sid, "image", first["n"])
            t0 = time.time()
            take = P.render_last_frame(client, script, sid, seed=SEEDS[0], candidates=1, rounds=1, model=model)
            results.append({"variant": f"last_{mname}", "shot": sid, "seed": SEEDS[0], "file": str(work / take.file),
                            "first": str(work / first["file"]), "gen_seconds": round(time.time() - t0, 1),
                            "comfy_seconds": take.seconds, "score": take.score, "prompt": take.prompt})
            print(f"[last {mname}] {sid}: {take.seconds}s，评分 {(take.score or {}).get('total')} "
                  f"缺 {(take.score or {}).get('missing')}", flush=True)
            (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def make_sheets(out: Path, results: list[dict], tag: str):
    firsts = [r for r in results if not r["variant"].startswith("last_")]
    variants = list(dict.fromkeys(r["variant"] for r in firsts))
    shots = list(dict.fromkeys(r["shot"] for r in firsts))
    seeds = list(dict.fromkeys(r["seed"] for r in firsts))
    if firsts:
        cols = [(v, s) for v in variants for s in seeds]
        cells = []
        for sid in shots:
            row = []
            for v, s in cols:
                r = next((r for r in firsts if r["shot"] == sid and r["variant"] == v and r["seed"] == s), None)
                row.append(label(Image.open(r["file"]), _lines(r["score"], r["comfy_seconds"])) if r else None)
            cells.append(row)
        p = sheet(cells, [f"{v} · seed {s}" for v, s in cols], out / f"sheet_{tag}_first.jpg", shots)
        print("对比表：", p)
        means = {v: round(sum(r["score"]["total"] for r in firsts if r["variant"] == v) /
                          max(1, sum(1 for r in firsts if r["variant"] == v)), 3) for v in variants}
        print("平均分：", means)
    lasts = [r for r in results if r["variant"].startswith("last_")]
    if lasts:
        models = list(dict.fromkeys(r["variant"] for r in lasts))
        lshots = list(dict.fromkeys(r["shot"] for r in lasts))
        cells = []
        for sid in lshots:
            first = next(r for r in lasts if r["shot"] == sid)["first"]
            row = [label(Image.open(first), ["首帧（new）"])]
            for m in models:
                r = next((r for r in lasts if r["shot"] == sid and r["variant"] == m), None)
                row.append(label(Image.open(r["file"]), _lines(r["score"], r["comfy_seconds"])) if r else None)
            cells.append(row)
        p = sheet(cells, ["首帧", *models], out / f"sheet_{tag}_last.jpg", lshots)
        print("尾帧对比表：", p)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="golden/quality_v2")
    ap.add_argument("--shots", nargs="*", default=[])
    ap.add_argument("--variants", nargs="*", default=["old", "new"])
    ap.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    ap.add_argument("--last", nargs="*", default=[])
    ap.add_argument("--last-models", nargs="*", default=["turbo"])
    ap.add_argument("--pilot", action="store_true", help="ep01–ep03 非成人：script vs spec")
    ap.add_argument("--tag", default="r1")
    ap.add_argument("--sheets-only", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="清空沙箱和 results.json 重新开始")
    args = ap.parse_args()
    out = (ROOT / args.out).resolve()
    script = P.load_script()
    if args.pilot:
        args.shots = [s.id for ep in script.episodes if ep.number <= 3 for s in ep.shots]
        args.variants = args.variants if args.variants != ["old", "new"] else ["new", "spec"]
    shots = [s for s in args.shots if non_adult(script, s)]
    skipped = sorted(set(args.shots) - set(shots))
    if skipped:
        print("跳过成人镜头：", skipped)
    last = [s for s in args.last if non_adult(script, s)]
    res_path = out / "results.json"
    if args.fresh and out.exists():
        shutil.rmtree(out / "work", ignore_errors=True)
        res_path.unlink(missing_ok=True)
    results = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else []
    out.mkdir(parents=True, exist_ok=True)
    if not args.sheets_only:
        client = ComfyClient()
        client.system_stats()
        if shots:
            run_first(client, script, out, shots, args.variants, args.seeds, results)
        if last:
            run_last(client, script, out, last, args.last_models, results)
    make_sheets(out, results, args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
