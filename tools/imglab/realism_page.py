"""写实 / 时尚大片对比页：data/review_pages/realism/index.html（总调度亲审后给项目方挑）。只读数据，不出图。
每轮 = data/ab/imglab/realism/<round>/takes.jsonl + scores.json；每个方案标参数（arms.json 的 note + 关键参数）与数字
（Q1 对 L-086 锚分 / top-k、皮肤高频能量 skin_hf、肤色 a* 标准差 skin_a_std、镜面高光占比 spec_ratio、出图秒数）。

    .venv/Scripts/python.exe tools/imglab/realism_page.py
"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/ab/imglab/realism"
PAGE = ROOT / "data/review_pages/realism/index.html"
TITLES = {"fashion_r1": "时尚大片（W 杂志式：饱和背景纸 + 硬光 + 色片轮廓光）——林晚造型 F",
          "moss_id_r1": "MOSS-Image 身份保持与速度（官方 edit LoRA + L-086 身份脸）",
          "r1": "写实 / 去塑料感——林晚造型 D 设定图"}
CSS = """body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;background:#111;color:#ddd}h1,h2{color:#fff}
.grid{display:flex;gap:10px;flex-wrap:wrap}.card{border:1px solid #333;padding:8px;width:300px}.card img{width:100%;display:block}
.small{font-size:12px;color:#aaa}.ok{color:#6c6}.bad{color:#f66}"""


def esc(s) -> str:
    return html.escape(str(s))


def rel(p: str) -> str:
    return Path(os.path.relpath(ROOT / p, PAGE.parent)).as_posix()


def card(file: str, title: str, note: str, sc: dict | None, secs=None) -> str:
    q = (sc or {}).get("q1_lin_wan")
    qk = (sc or {}).get("q1_topk")
    qc = "ok" if (q or 0) >= 0.6 else "bad"
    nums = (f"<div class={qc}>Q1 {q} / top-k {qk}（线 0.60）</div>" if q is not None else "<div class=small>Q1 未测</div>") + \
        (f"<div class=small>皮肤高频 {sc.get('skin_hf')}　肤色 a*σ {sc.get('skin_a_std')}　高光占比 {sc.get('spec_ratio')}</div>" if sc and sc.get("skin_hf") is not None else "")
    return (f"<div class=card><a href='{esc(rel(file))}'><img src='{esc(rel(file))}'></a><b>{esc(title)}</b>"
            f"<div class=small>{esc(note)}</div>{nums}" + (f"<div class=small>出图 {secs} s</div>" if secs else "") + "</div>")


def main() -> int:
    arms = json.loads((BASE / "arms.json").read_text(encoding="utf-8")) if (BASE / "arms.json").exists() else {}
    body = []
    for d in sorted((x for x in BASE.iterdir() if x.is_dir() and (x / "takes.jsonl").exists()), key=lambda x: x.name):
        recs = [json.loads(ln) for ln in (d / "takes.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        sc = json.loads((d / "scores.json").read_text(encoding="utf-8")) if (d / "scores.json").exists() else {}
        cards = []
        cur = next((k for k in sc if "|S0_current|" in k), None)
        if cur:
            cards.append(card(sc[cur]["file"], "现行（S★ R0 设定图，对照）", "现行登记的设定图", sc[cur]))
        for r in recs:
            a = arms.get(r["arm"], {})
            cards.append(card(r["file"], r["arm"], a.get("note", ""), sc.get(f"{r['key']}|{r['arm']}|{r['seed']}"), r.get("comfy_s")))
        body.append(f"<h2>{esc(TITLES.get(d.name, d.name))}</h2><div class=grid>{''.join(cards)}</div>")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    doc = (f"<!doctype html><meta charset=utf-8><title>写实 / 时尚大片对比</title><style>{CSS}</style>"
           "<h1>写实 / 时尚大片对比（IMGLAB → 总调度亲审 → 项目方挑）</h1>"
           "<p class=small>S★ R0 是项目方定的剧集观感（L-087），这里的方案只作新预设候选（设定图 / 宣传图 / 图像工坊）。"
           "Q1 = ArcFace 对 L-086 身份脸；皮肤指标只作相对比较（阈值未标定）。研究依据：docs/research/imglab/07_realism_skin.md。</p>"
           + "".join(body))
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(doc, encoding="utf-8")
    os.replace(tmp, PAGE)
    print(PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
