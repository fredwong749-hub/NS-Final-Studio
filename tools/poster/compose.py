"""把 data/posters/<run>/art.jsonl 里的主图 + content.json 排成成品海报，写 manifest.json 与审片页。
成品：3 尺寸（portrait 2:3 / landscape 16:9 / square 1:1）× 中英 × 构图 A/B/C → data/posters/<run>/<kind>_<comp>_<lang>.jpg
方形图用竖版主图裁切（焦点在脸）。manifest.current = 卡片封面（script_library._poster_cover 读）。
用法：.venv/Scripts/python.exe tools/poster/compose.py [--current s1=A s2=A]"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import layout as Lo  # noqa: E402
from common import poster_runs, season_of, write_json_atomic, write_text_atomic  # noqa: E402

FOCUS = {"portrait": (0.5, 0.40), "landscape": (0.6, 0.40), "square": (0.5, 0.30)}


def arts(run):
    """每个 (comp, kind) 取最后一张；--pick 可指定别的"""
    f = ROOT / "data" / "posters" / run / "art.jsonl"
    out = {}
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                out[(r["comp"], r["kind"])] = ROOT / "data" / r["file"]
    picks = ROOT / "data" / "posters" / run / "picks.json"   # {"A_portrait": "posters/.../x.png"} 人工 / 总调度指定
    if picks.exists():
        for k, v in json.loads(picks.read_text(encoding="utf-8")).items():
            c, kd = k.split("_")
            out[(c, kd)] = ROOT / "data" / v
    return out


def build(run, current_comp):
    d = ROOT / "data" / "posters" / run
    content = json.loads((d / "content.json").read_text(encoding="utf-8"))
    A = arts(run)
    items = []
    for comp in "ABC":
        for kind in ("portrait", "landscape", "square"):
            src = A.get((comp, "portrait" if kind == "square" else kind))
            if not src or not src.exists():
                continue
            for lang in ("zh", "en"):
                f = d / f"{kind}_{comp}_{lang}.jpg"
                Lo.render(src, kind, lang, comp, content, run, f, focus=FOCUS[kind])
                items.append({"id": f"{kind}_{comp}_{lang}", "kind": kind, "comp": comp, "lang": lang,
                              "file": f"data/posters/{run}/{f.name}", "art": str(src.relative_to(ROOT / "data")).replace("\\", "/")})
    cur = next((i for i in items if i["id"] == f"portrait_{current_comp}_zh"), None)
    man = {"run": run, "title": content["zh"]["title"], "title_en": content["en"]["title"], "posters": items,
           "current": cur, "source": content.get("source")}
    write_json_atomic(d / "manifest.json", man)
    return man


def page(mans):
    out = ["<!doctype html><meta charset=utf-8><title>剧集海报审片</title><style>body{background:#111;color:#eee;font:14px system-ui;margin:20px}"
           "h2{margin:30px 0 6px}.row{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}figure{margin:0}"
           "img{display:block;border:1px solid #333}figcaption{font-size:12px;color:#aaa;margin-top:3px}.cur{outline:3px solid #e8c;}"
           ".p img{height:560px}.l img{height:300px}.s img{height:380px}</style><h1>海报审片（本地）</h1>"
           "<p>每季：竖版 2:3 / 横版 16:9 / 方形 1:1 × 中英 × 构图 A（林晚居前、顾沉在后）/ B（双人对视）/ C（林晚单人）。红框 = 现为剧本库卡片封面。</p>"]
    for m in mans:
        out.append(f"<h2>{html.escape(m['title'])} / {html.escape(m['title_en'])}  ({m['run']})</h2>")
        for kind, cls in (("portrait", "p"), ("landscape", "l"), ("square", "s")):
            out.append(f"<h3>{kind}</h3><div class='row {cls}'>")
            for i in m["posters"]:
                if i["kind"] != kind:
                    continue
                cur = " cur" if m["current"] and m["current"]["id"] == i["id"] else ""
                out.append(f"<figure class='{cur}'><a href='../../{i['file'][5:]}'><img src='../../{i['file'][5:]}'></a>"
                           f"<figcaption>{i['comp']} · {i['lang']}{' · CURRENT' if cur else ''}</figcaption></figure>")
            out.append("</div>")
    p = ROOT / "data" / "review_pages" / "posters" / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(p, "\n".join(out))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", nargs="*", default=[], help="sN=A：第 N 季卡片封面用哪个构图，默认 A")
    a = ap.parse_args()
    cc = dict(x.split("=") for x in a.current)
    mans = [build(run, cc.get(f"s{season_of(run)}", "A")) for run in poster_runs()]
    print(page(mans))


if __name__ == "__main__":
    main()
