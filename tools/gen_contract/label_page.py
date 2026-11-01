"""契约门槛复核用的小标注集（总调度 11-01：放宽任何门槛前要有留出证据或总调度标过的小样本）。

从 data/renders/**/takes.json 挑：
  Q7 场景：0.30–0.40 没过的（多为特写 / 近景）+ 0.40–0.46 刚过的对照 —— 标“场景对 / 场景不对”
  Q5 手：判“手型可疑”的 —— 标“手正常 / 手坏了”
  Q6 文字：判有文字的 —— 标“确实有多余文字 / 没有”
生成本地审阅页 data/review_pages/contract_labels_r1/index.html（点选，最后一键下载 labels.json，不用打字）。

    .venv/Scripts/python.exe tools/gen_contract/label_page.py
"""
from __future__ import annotations

import glob
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ("services/agent", "packages/schema", "tools/gen_contract")]
OUT = ROOT / "data/review_pages/contract_labels_r1"
SHOTS = {"ep02-S2", "ep05-S3", "ep05-S5", "ep06-S2", "ep08-S1", "ep08-S6", "ep09-S7", "ep09-S8", "ep02-S8", "ep07-S9",
         "ep08-S7", "ep08-S2", "ep08-S4", "ep02-S1", "ep03-S1", "ep10-S1", "ep10-S8"}


def _item(pf, qid):
    return next((i for i in (pf or {}).get("items") or [] if i.get("id") == qid), None)


def _q7(it) -> float | None:
    try:
        return float(str(it.get("detail")).split("场景相似度 ")[1].split(" ")[0])
    except (IndexError, ValueError, AttributeError):
        return None


def collect():
    import rescore_takes as RT
    from ns_agent.gen_contract import postflight as PO
    q7, q5, q6 = [], [], []
    for f in sorted(glob.glob(str(ROOT / "data/renders/ep*/S*/takes.json"))):
        sid = "-".join(Path(f).parent.parts[-2:])
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        scene = None
        for t in d.get("takes") or []:
            if t.get("stage") not in ("image", "last") or not (ROOT / "data" / t["file"]).exists():
                continue
            pf = t.get("postflight") or (t.get("contract") or {}).get("postflight") or {}
            key = f"{sid}|{t['stage']}|{t['n']}"
            i7, i5, i6 = _item(pf, "Q7"), _item(pf, "Q5"), _item(pf, "Q6")
            v = _q7(i7) if i7 else None
            if v is not None and ((sid in SHOTS and 0.30 <= v < 0.40) or (0.40 <= v < 0.46 and pf.get("ok"))):
                if scene is None:
                    rec = (t.get("contract") or {}).get("asset_refs") or RT.current_rec(sid) or {}
                    scene = PO.scene_file(rec) or ""
                q7.append({"key": key, "file": "data/" + t["file"], "v": v, "scene": scene, "passed": v >= 0.40})
            if sid in SHOTS and i5 and i5.get("status") == "fail" and "手型可疑" in str(i5.get("detail")):
                q5.append({"key": key, "file": "data/" + t["file"], "detail": i5["detail"][:120]})
            if sid in SHOTS and i6 and i6.get("status") == "fail":
                q6.append({"key": key, "file": "data/" + t["file"], "detail": str(i6.get("detail"))[:80]})
    ctrl = [x for x in q7 if x["passed"]][:12]
    return [x for x in q7 if not x["passed"]] + ctrl, q5, q6


def page(q7, q5, q6) -> str:
    def rel(p):
        return os.path.relpath(ROOT / p, OUT).replace("\\", "/") if p else ""

    def card(sec, x, opts, extra=""):
        k = html.escape(x["key"])
        radios = "".join(f'<label><input type="radio" name="{sec}|{k}" value="{v}"> {t}</label>' for v, t in opts)
        return (f'<div class="c"><img src="{rel(x["file"])}" loading="lazy">{extra}'
                f'<div class="k">{k}</div><div class="d">{html.escape(x.get("detail") or "")}</div>{radios}</div>')
    import random
    random.seed(7)
    random.shuffle(q7)                          # 打乱：不按分数排，避免看分标注（分数藏在 key 后面，标完才导出）
    s7 = "".join(card("Q7", x, [("ok", "场景对"), ("bad", "场景不对")],
                      f'<img class="ref" src="{rel(x["scene"])}" loading="lazy">' if x["scene"] else "") for x in q7)
    s5 = "".join(card("Q5", x, [("ok", "手正常"), ("bad", "手坏了")]) for x in q5)
    s6 = "".join(card("Q6", x, [("bad", "确实有多余文字 / 水印"), ("ok", "没有")]) for x in q6)
    meta = json.dumps({"Q7": {x["key"]: x["v"] for x in q7}}, ensure_ascii=False)
    return f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>契约门槛小标注集</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}}h2{{margin-top:28px}}
.g{{display:flex;flex-wrap:wrap;gap:12px}}.c{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px;width:300px}}
.c img{{width:100%;border-radius:4px}}.c img.ref{{width:45%;opacity:.9;margin-top:4px}}.k{{font-size:12px;color:#666}}
.d{{font-size:12px;color:#a33}}label{{display:block;margin:3px 0;cursor:pointer}}
button{{position:sticky;top:8px;font-size:16px;padding:8px 18px;background:#1a73e8;color:#fff;border:0;border-radius:6px;cursor:pointer}}</style>
<h1>契约门槛小标注集（REFLOCK）</h1>
<p>每张点一个选项；标完点下方按钮下载 labels.json（存到“下载”文件夹即可，REFLOCK 会去读）。分数不显示，避免影响判断。</p>
<button onclick="dl()">下载标注 labels.json</button>
<h2>Q7 场景：生成图（大）与本镜场景参考（小）是不是同一个地方？（{len(q7)} 张）</h2><div class="g">{s7}</div>
<h2>Q5 手：手 / 手指是否画坏（多指、断指、畸形；长甲本身不算坏）（{len(q5)} 张）</h2><div class="g">{s5}</div>
<h2>Q6 文字：画面里是否有多余的字幕 / 水印 / 乱码（{len(q6)} 张）</h2><div class="g">{s6}</div>
<script>const META={meta};
function dl(){{const o={{at:new Date().toISOString(),labels:{{}},meta:META}};
document.querySelectorAll('input[type=radio]:checked').forEach(r=>o.labels[r.name]=r.value);
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(o,null,1)],{{type:'application/json'}}));
a.download='labels.json';a.click();}}</script></html>"""


def main():
    q7, q5, q6 = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page(q7, q5, q6), encoding="utf-8")
    (OUT / "items.json").write_text(json.dumps({"Q7": q7, "Q5": q5, "Q6": q6}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(q7), len(q5), len(q6), OUT / "index.html")


if __name__ == "__main__":
    main()
