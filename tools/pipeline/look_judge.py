"""画面对比裁判（H3c，PLAN_HOLLYWOOD_LOOK）：本地看图模型有位置偏置（9 对全选“图 2”），所以

  compare(a, b)       两图等高拼成一张（中间 16px 灰条，左上角标“左”“右”），问“左右哪张更像好莱坞院线剧照”；
                      再左右交换问一次；两次指向同一张才记胜者，否则 uncertain。
                      mode="triple" 为三问（背景更暗 / 主体分离更好 / 更像胶片）各自双向，取多数。
  deterministic(a, b) 不用模型：背景亮度 bg_lum 低者倾向胜（差 < 0.02 记 tie），附主体 / 背景亮度比。
看图只走 vlm_pool.generate（本机 8870 / 隧道 8871，K-REV-V01，图不出外网）。

    python tools/pipeline/look_judge.py compare A.png B.png [--mode single|triple]
    python tools/pipeline/look_judge.py calibrate [--mode single|triple]   # data/ab/look_v2/results.json 的 a/c/e/f/g 全部两两
"""
from __future__ import annotations

import itertools
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

BAR = 16
HEIGHT = 720
SYSTEM = "你是电影摄影指导，评判画面的院线质感。只看画面，不管剧情与人物像不像。"
_HEAD = "这是一张拼图：左边一张、右边一张（左上角分别标有“左”“右”）。"
QUESTIONS = {
    "overall": _HEAD + "哪一张更像好莱坞院线电影剧照（光线层次、背景压暗、景深、调色、去 AI 感）？",
    "dark": _HEAD + "哪一张的背景更暗、更有压暗的层次？",
    "sep": _HEAD + "哪一张的主体与背景分离得更好（景深、光线勾边、背景虚化）？",
    "film": _HEAD + "哪一张更像电影胶片拍的（颗粒、柔和高光、调色），而不是数码 AI 出图？",
}
SUFFIX = "只答“左”“右”或“一样”，第一行只写这一个字，第二行给一句理由。"
MODES = {"single": ["overall"], "triple": ["dark", "sep", "film"]}


def stitch(a, b, height: int = HEIGHT, bar: int = BAR):
    """a 在左 b 在右，等高缩放，中间灰条，左上角各标“左”“右”（白底红字）。返回 PIL.Image"""
    from PIL import Image, ImageDraw, ImageFont
    ims = []
    for p in (a, b):
        im = Image.open(p).convert("RGB")
        ims.append(im.resize((max(1, round(im.width * height / im.height)), height), Image.LANCZOS))
    out = Image.new("RGB", (ims[0].width + bar + ims[1].width, height), (128, 128, 128))
    out.paste(ims[0], (0, 0))
    out.paste(ims[1], (ims[0].width + bar, 0))
    font = None
    for f in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            font = ImageFont.truetype(f, 72)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    d = ImageDraw.Draw(out)
    for x, t in ((0, "左"), (ims[0].width + bar, "右")):
        d.rectangle([x + 10, 10, x + 100, 100], fill=(255, 255, 255))
        d.text((x + 18, 14), t, fill=(220, 0, 0), font=font)
    return out


def parse_side(text: str) -> str | None:
    """left / right / tie / None。优先第一行，其次全文第一次出现"""
    t = (text or "").strip()
    first = t.splitlines()[0] if t else ""
    for s in (first, t):
        m = re.search(r"一样|相同|左|右", s)
        if m:
            return {"左": "left", "右": "right"}.get(m.group(0), "tie")
    return None


def combine(side1: str | None, side2: str | None) -> str:
    """side1：a 在左的结果；side2：b 在左（a 在右）的结果。同指 a→a，同指 b→b，都 tie→tie，其余 uncertain"""
    pick1 = {"left": "a", "right": "b", "tie": "tie"}.get(side1 or "")
    pick2 = {"left": "b", "right": "a", "tie": "tie"}.get(side2 or "")
    if pick1 is None or pick2 is None:
        return "uncertain"
    return pick1 if pick1 == pick2 else "uncertain"


def majority(votes: list[str]) -> str:
    na, nb = votes.count("a"), votes.count("b")
    if na > nb and na >= 2:
        return "a"
    if nb > na and nb >= 2:
        return "b"
    return "tie" if votes.count("tie") >= 2 else "uncertain"


def _ask(q: str, a, b, ask, tmp: Path) -> tuple[str, list[dict]]:
    sides, raws = [], []
    for order, (x, y) in (("ab", (a, b)), ("ba", (b, a))):
        f = tmp / f"st_{q}_{order}.jpg"
        stitch(x, y).save(f, quality=92)
        res = ask({"system": SYSTEM, "text": QUESTIONS[q] + SUFFIX, "images": [{"path": str(f), "max_pixels": 2200000}]})
        txt = res.get("text") or ""
        sides.append(parse_side(txt) if not res.get("error") else None)
        raws.append({"q": q, "order": order, "side": sides[-1], "text": txt[:200], "error": res.get("error")})
    return combine(*sides), raws


def compare(a, b, mode: str = "single", ask=None) -> dict:
    """{winner: a|b|tie|uncertain, votes, raw}；ask(req)->{text} 默认走 vlm_pool（测试可打桩）"""
    if ask is None:
        import vlm_pool as VP
        ask = lambda req: VP.generate(req, wait_s=900, label="look_judge")   # noqa: E731
    votes, raw = [], []
    with tempfile.TemporaryDirectory() as td:
        for q in MODES[mode]:
            v, r = _ask(q, a, b, ask, Path(td))
            votes.append(v)
            raw += r
    return {"winner": votes[0] if mode == "single" else majority(votes), "votes": votes, "raw": raw}


def deterministic(a, b, margin: float = 0.02) -> dict:
    """不用模型：背景更暗者倾向胜（bg_lum 差 < margin = tie）"""
    import look_metrics as LM
    ma, mb = LM.measure(a), LM.measure(b)
    d = ma["bg_lum"] - mb["bg_lum"]
    return {"winner": "tie" if abs(d) < margin else ("a" if d < 0 else "b"),
            "bg_lum": [ma["bg_lum"], mb["bg_lum"]], "subj_bg_ratio": [ma["subj_bg_ratio"], mb["subj_bg_ratio"]]}


# 参考排序（PS-MASTER 亲看）：值大者更好；同值 = 持平不计；没列的档不参与（S4 的 G 因剧情违背排除）
REF = {
    "ep01-S4": {"f": 3, "e": 2, "c": 1, "a": 0},
    "ep01-S13": {"g": 3, "e": 3, "f": 2, "c": 1, "a": 0},
    "ep01-S1": {"f": 3, "e": 3, "c": 1, "a": 0},
}
TIERS = ("a", "c", "e", "f", "g")


def _pick_files(root: Path) -> dict[str, dict[str, Path]]:
    recs = json.loads((root / "data/ab/look_v2/results.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, Path]] = {}
    for r in recs:
        if r["tier"] not in TIERS:
            continue
        cur = out.setdefault(r["shot"], {}).get(r["tier"])
        if cur is None or r["file"].endswith("_film.png"):
            out[r["shot"]][r["tier"]] = root / "data" / r["file"]
    return out


def calibrate(root: Path = ROOT, mode: str = "single", out: Path | None = None, ask=None) -> dict:
    out = out or root / ("data/ab/look_v2/pairwise_v2.jsonl" if mode == "single" else f"data/ab/look_v2/pairwise_v2_{mode}.jsonl")
    rows = []
    with open(out, "w", encoding="utf-8") as fh:
        for shot, tiers in _pick_files(root).items():
            for ta, tb in itertools.combinations([t for t in TIERS if t in tiers], 2):
                j = compare(tiers[ta], tiers[tb], mode, ask)
                d = deterministic(tiers[ta], tiers[tb])
                ref = REF.get(shot, {})
                rv = "excluded" if ta not in ref or tb not in ref else ("tie" if ref[ta] == ref[tb] else ta if ref[ta] > ref[tb] else tb)
                m = {"a": ta, "b": tb}
                rec = {"shot": shot, "a": ta, "b": tb, "mode": mode, "winner": m.get(j["winner"], j["winner"]), "votes": j["votes"],
                       "det": m.get(d["winner"], d["winner"]), "bg_lum": d["bg_lum"], "ref": rv, "raw": j["raw"]}
                rows.append(rec)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
    return stats(rows)


def stats(rows: list[dict]) -> dict:
    n = len(rows)
    unc = sum(r["winner"] == "uncertain" for r in rows)
    dec = [r for r in rows if r["winner"] not in ("uncertain", "tie")]
    det = [r for r in dec if r["det"] != "tie"]
    ref = [r for r in dec if r["ref"] not in ("tie", "excluded")]
    rate = lambda k, m: round(k / m, 3) if m else None   # noqa: E731
    ka, kr = sum(r["winner"] == r["det"] for r in det), sum(r["winner"] == r["ref"] for r in ref)
    dr = [r for r in rows if r["ref"] not in ("tie", "excluded") and r["det"] != "tie"]
    return {"pairs": n, "uncertain": unc, "uncertain_rate": rate(unc, n), "decided": len(dec),
            "det_agree": f"{ka}/{len(det)}", "det_agree_rate": rate(ka, len(det)),
            "ref_agree": f"{kr}/{len(ref)}", "ref_agree_rate": rate(kr, len(ref)),
            "det_vs_ref": f"{sum(r['det'] == r['ref'] for r in dr)}/{len(dr)}"}


def main(argv=None) -> int:
    av = list(argv if argv is not None else sys.argv[1:])
    mode = "single"
    if "--mode" in av:
        i = av.index("--mode")
        mode = av[i + 1]
        del av[i:i + 2]
    if av[:1] == ["compare"] and len(av) == 3:
        print(json.dumps({**compare(av[1], av[2], mode), "det": deterministic(av[1], av[2])}, ensure_ascii=False, indent=1))
        return 0
    if av[:1] == ["calibrate"]:
        print(json.dumps(calibrate(mode=mode), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
