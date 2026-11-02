"""anomaly.py --scan --raw res.json 的结果 → data/review_pages/anomaly/index.html（命中分布 + 命中样本拼图 + 放行的镜像样本，给总调度亲审）。

    python tools/vqa/anomaly_page.py [raw.json]
"""
from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "review_pages" / "anomaly"


def _thumb(src: Path, dst: Path, boxes, side=420):
    import cv2
    import numpy as np
    im = cv2.imdecode(np.fromfile(str(src), dtype="uint8"), 1)
    h, w = im.shape[:2]
    s = side / max(h, w)
    for b in boxes:
        cv2.rectangle(im, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 0, 255), max(2, int(2 / s)))
    im = cv2.resize(im, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 85])
    tmp = dst.with_suffix(".tmp")
    tmp.write_bytes(buf.tobytes())
    os.replace(tmp, dst)


def build(raw: dict, files: dict[str, Path]) -> Path:
    (OUT / "t").mkdir(parents=True, exist_ok=True)
    cnt = Counter()
    hit, mir, err = [], [], []
    for k, r in raw.items():
        if r.get("verdict") == "error":
            err.append(k)
            continue
        codes = {d["code"] for d in r["defects"]}
        cnt.update(codes)
        if any(d["conf"] != "low" for d in r["defects"]):
            hit.append(k)
        elif (r.get("metrics") or {}).get("heads_mirror"):
            mir.append(k)
    sections = []

    def cards(keys, title):
        rows = []
        for k in keys:
            r = raw[k]
            p = files.get(k) or next((v for kk, v in files.items() if kk == k), None)
            if not p or not Path(p).exists():
                continue
            name = k.replace("|", "_") + ".jpg"
            _thumb(Path(p), OUT / "t" / name, [f["box"] for f in r.get("feat_summary", {}).get("faces", [])])
            ds = "<br>".join(html.escape(f"[{d['conf']}] {d['code']}：{d['detail']}") for d in r["defects"]) or "（无）"
            m = r.get("metrics") or {}
            rows.append(f"<div class=c><img src='t/{html.escape(name)}'><b>{html.escape(k)}</b><br>"
                        f"头 {m.get('heads_real')}（镜中 {m.get('heads_mirror')}）/ cast 在画 {m.get('expected_faced')}；手框 {m.get('hands')}<br>{ds}</div>")
        sections.append(f"<h2>{title}（{len(rows)}）</h2><div class=g>{''.join(rows)}</div>")

    # 人工标注表：每个命中一行，label 留空由总调度填 true_issue / false_positive；标好后用来标定阈值
    labels = {k: {"codes": [d["code"] for d in raw[k]["defects"] if d["conf"] != "low"], "label": ""} for k in sorted(hit)}
    lp = OUT / "labels.json"
    if not lp.exists():                       # 已有标注不覆盖
        tmpl = lp.with_suffix(".tmp")
        tmpl.write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmpl, lp)
    rows_t = "".join(f"<tr><td>{i + 1}</td><td>{html.escape(k)}</td><td>{html.escape(', '.join(v['codes']))}</td><td>{html.escape('; '.join(d['detail'] for d in raw[k]['defects'] if d['conf'] != 'low'))}</td><td>真问题 / 误报：____</td></tr>"
                     for i, (k, v) in enumerate(labels.items()))
    sections.append(f"<h2>人工标注表（{len(labels)} 行；labels.json 同款）</h2><table border=1 cellpadding=4>{rows_t}</table>")
    cards(sorted(hit), "命中（人数 / 头数 / 重复人 / 手框，不含仅记录项）")
    cards(sorted(mir), "放行的镜像样本（镜面区域里有头，判为在场者镜像）")
    low = sorted(k for k, r in raw.items() if r.get("verdict") == "clean" and r["defects"])
    dist = "".join(f"<li>{html.escape(c)}：{n}</li>" for c, n in cnt.most_common())
    seg = Counter(r.get("mirror_seg") for r in raw.values())
    head = (f"<h1>本地异常检测 P1（只记录，未拦截）</h1><p>扫描 {len(raw)} 张当前版本首 / 尾帧；命中 {len(hit)}；镜像放行 {len(mir)}；"
            f"仅记录项（finger_ratio / feet_dup）{len(low)}；出错 {len(err)}。镜面分割：{dict(seg)}</p><ul>{dist}</ul>")
    page = ("<!doctype html><meta charset=utf-8><style>body{font:13px sans-serif;background:#111;color:#ddd}.g{display:flex;flex-wrap:wrap;gap:8px}"
            ".c{width:430px;background:#222;padding:6px}.c img{width:420px;display:block}</style>" + head + "".join(sections))
    out = OUT / "index.html"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, out)
    return out


def main(argv):
    sys.path.insert(0, str(ROOT))
    from tools.vqa import anomaly as A
    rawp = Path(argv[0]) if argv else OUT / "raw.json"
    raw = json.loads(rawp.read_text(encoding="utf-8"))
    files = {f"{sid}|{st}": p for sid, st, p in A.current_images()}
    print(build(raw, files))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
