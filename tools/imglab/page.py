"""IMGLAB 对比页（总调度亲审）：data/review_pages/imglab/index.html。只读数据，不出图。

段落：
  1. F1 / F3 根因与修复：受影响镜头的“修前 / 修后”提示词（差异高亮）+ 生产版本对照（修复上线前最后一版 vs 上线后第一版，带 postflight 逐人数字）
  2. 冒烟（data/ab/imglab/smoke/）
  3. A/B 轮次（data/ab/imglab/<round>/takes.jsonl + scores.json）
  4. 出图线分数轨迹（data/rsi/scores.jsonl line=image）

    .venv/Scripts/python.exe tools/imglab/page.py [--fix-at 2026-11-02T04:00:00]
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "data/review_pages/imglab/index.html"
AB = ROOT / "data/ab/imglab"
CSS = """body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;background:#111;color:#ddd}h1,h2{color:#fff}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #444;padding:6px;vertical-align:top;font-size:13px}
img{max-height:420px;display:block}.ok{color:#6c6}.bad{color:#f66}.del{background:#5a1d1d;text-decoration:line-through}
.ins{background:#1d4a24}.small{font-size:12px;color:#aaa}.grid{display:flex;gap:8px;flex-wrap:wrap}.card{border:1px solid #333;padding:6px}"""


def rel(p: str | Path) -> str:
    p = Path(p)
    p = p if p.is_absolute() else ROOT / p
    return Path(os.path.relpath(p, PAGE.parent)).as_posix()


def esc(s) -> str:
    return html.escape(str(s))


def diff_html(a: str, b: str) -> str:
    A, B = a.replace("。", "，").split("，"), b.replace("。", "，").split("，")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=A, b=B, autojunk=False).get_opcodes():
        if op == "equal":
            seg = A[i1:i2]
            out.append(esc("，".join(seg[:2] + (["…"] if len(seg) > 4 else []) + seg[-2:] if len(seg) > 4 else seg)))
        if op in ("delete", "replace"):
            out.append(f"<span class=del>{esc('，'.join(A[i1:i2]))}</span>")
        if op in ("insert", "replace"):
            out.append(f"<span class=ins>{esc('，'.join(B[j1:j2]))}</span>")
    return "，".join(out)


def pf_cell(t: dict | None) -> str:
    if not t:
        return "<span class=small>暂无</span>"
    items = {i["id"]: i for i in ((t.get("postflight") or {}).get("items") or [])}
    rows = []
    for k in ("Q1", "Q2", "Q3", "Q5", "Q9"):
        it = items.get(k)
        if it:
            c = "ok" if it["status"] == "pass" else "bad" if it["status"] == "fail" else "small"
            rows.append(f"<div class={c}>{k} {esc(it['status'])}：{esc(it['detail'][:90])}</div>")
    sims = ((items.get("Q1") or {}).get("evidence") or {}).get("sims")
    if sims:
        rows.append(f"<div class=small>逐人 ArcFace：{esc(sims)}</div>")
    outer = ((items.get("Q2") or {}).get("evidence") or {}).get("outer") or []
    for o in outer:
        rows.append(f"<div class=small>外层探针 {esc(o.get('character'))} {esc(o.get('label'))} p={o.get('p')}</div>")
    return "".join(rows) or "<span class=small>无 postflight</span>"


def takes_of(sid: str) -> list[dict]:
    ep, sh = sid.split("-")
    p = ROOT / "data/renders" / ep / sh / "takes.json"
    if not p.exists():
        return []
    try:
        return [t for t in json.loads(p.read_text(encoding="utf-8")).get("takes") or [] if t.get("stage") == "image"]
    except ValueError:   # arch-ok: 正在写的 takes.json 本轮不展示，下次生成页面再读
        return []


def section_fix(fix_at: str) -> str:
    dp = ROOT / "docs/research/imglab/data/prompt_diff_F1F3.json"
    if not dp.exists():
        return ""
    rows = []
    for o in json.loads(dp.read_text(encoding="utf-8")):
        if not o["changed"]:
            continue
        ts = takes_of(o["shot"])
        before = [t for t in ts if (t.get("created_at") or "") < fix_at]
        after = [t for t in ts if (t.get("created_at") or "") >= fix_at]
        b, a = (before[-1] if before else None), (after[0] if after else None)

        def img(t):
            return f"<img src='{esc(rel(ROOT / 'data' / t['file']))}'>" if t and t.get("file") else "<span class=small>未出</span>"
        rows.append(f"<tr><td><b>{esc(o['shot'])}</b></td><td style='max-width:520px'>{diff_html(o['old'], o['new'])}</td>"
                    f"<td>{img(b)}{pf_cell(b)}</td><td>{img(a)}{pf_cell(a)}</td></tr>")
    return ("<h2>1. 双人串扰根因修复（K-REN-901 删句保主语 / K-REN-902 双人特写改近景，sv-20261102-05）</h2>"
            "<p class=small>根因：脸部特写 / 按景别删句时把带人名的分句整句删掉，剩下的描写没有主语，紧跟在最后一个【角色】锁后面，"
            "属性就归给了那个人（ep06-S2 v6 顾沉长出林晚的蓝色长直发）。102 镜旧编译小句归属错 23 镜 236 句 → 新编译 0；"
            "提示词变化 29 镜（红 = 删，绿 = 加），其余 73 镜逐字不变。右两列：修复前最后一版 vs 修复后第一版（生产按新提示词重出，"
            f"修复时间 {esc(fix_at)}）。详见 docs/research/imglab/05_ep06S2_bleeding_rca.md。</p>"
            "<table><tr><th>镜</th><th>提示词差异</th><th>修复前</th><th>修复后</th></tr>" + "".join(rows) + "</table>")


def section_smoke() -> str:
    p = AB / "smoke/smoke.jsonl"
    if not p.exists():
        return "<h2>2. 冒烟</h2><p class=small>未跑</p>"
    cards = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(ln)
        for f in r["files"]:
            cards.append(f"<div class=card><img src='{esc(rel(f))}'><div class=small>{esc(r['tag'])} · {r['secs']} s · {esc(r['lane'])}</div></div>")
    return "<h2>2. 冒烟（P0 新装节点各 1 张，非成人镜）</h2><div class=grid>" + "".join(cards) + "</div>"


def section_rounds() -> str:
    out = []
    for d in sorted(x for x in AB.iterdir() if x.is_dir() and (x / "takes.jsonl").exists() and x.name != "smoke"):
        recs = [json.loads(ln) for ln in (d / "takes.jsonl").read_text(encoding="utf-8").splitlines()]
        sc = json.loads((d / "scores.json").read_text(encoding="utf-8")) if (d / "scores.json").exists() else {}
        arms = sorted({r["arm"] for r in recs}, key=lambda a: (a != "A0", a))
        keys = sorted({(r["shot"], r["seed"]) for r in recs})
        head = "".join(f"<th>{esc(a)}</th>" for a in arms)
        rows = []
        for sid, seed in keys:
            cells = []
            for a in arms:
                r = next((x for x in recs if x["shot"] == sid and x["seed"] == seed and x["arm"] == a), None)
                if not r:
                    cells.append("<td></td>")
                    continue
                s = sc.get(f"{sid}|{a}|{seed}")
                look = (s or {}).get("look_vs_A0")
                cells.append(f"<td><img src='{esc(rel(r['file']))}'><div class=small>{r['comfy_s']} s"
                             + (f" · 观感 ΔL {look['dL']} Δa {look['da']} Δb {look['db']} 清晰度×{look['sharp_ratio']}" if look else "")
                             + f"</div>{pf_cell({'postflight': s} if s else None)}</td>")
            rows.append(f"<tr><td>{esc(sid)}<br><span class=small>seed {seed}</span></td>{''.join(cells)}</tr>")
        out.append(f"<h3>{esc(d.name)}</h3><table><tr><th>镜</th>{head}</tr>{''.join(rows)}</table>")
    return "<h2>3. A/B 轮次</h2>" + ("".join(out) or "<p class=small>未跑</p>")


def section_scores() -> str:
    p = ROOT / "data/rsi/scores.jsonl"
    rows = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:   # arch-ok: 别的线写坏一行不影响本页
                continue
            if r.get("line") == "image":
                rows.append(f"<tr><td>{esc(r['at'])}</td><td>{r['score']}</td><td>{esc(r.get('parts_pct'))}</td>"
                            f"<td>{esc(r.get('lowest'))}</td><td>{esc(list((r.get('missing') or {}).keys()))}</td><td>{esc(r.get('version'))}</td></tr>")
    return ("<h2>4. 出图线分数（tools/imglab/score.py）</h2><table><tr><th>时间</th><th>分</th><th>分项 %</th><th>最低项</th><th>缺</th><th>版本</th></tr>"
            + "".join(rows) + "</table>")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix-at", default="2026-11-02T04:00:00")
    a = ap.parse_args(argv)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    body = section_fix(a.fix_at) + section_smoke() + section_rounds() + section_scores()
    doc = f"<!doctype html><meta charset=utf-8><title>IMGLAB 出图对比</title><style>{CSS}</style><h1>IMGLAB 出图对比（总调度亲审）</h1>{body}"
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(doc, encoding="utf-8")
    os.replace(tmp, PAGE)
    print(PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
