"""VIDEO-RCA 本地审片页：data/review_pages/video_rca/index.html（前后对比，控制变量组并排）。
每组 = 同首帧、同 seed、只改一个因素的几条片；每条显示 5 帧抽帧条（第 0/12/48/96/150 帧，原片 768×1344 缩到 384×672）、
360p 预览、打分要点（score_clip 同生产口径）和清晰度（sharp.py）。图片臂显示原图。
    .venv/Scripts/python.exe tools/video_rca/page.py
"""
import html
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AB = ROOT / "data/ab/video_rca"
OUT = ROOT / "data/review_pages/video_rca"
GROUPS = json.loads((Path(__file__).parent / "groups.json").read_text(encoding="utf-8"))


def load(exp):
    p = AB / exp / "results.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def fmt(sc):
    if not sc:
        return "<i>未出 / 未打分</i>"
    if sc.get("error"):
        return f"<i>打分出错：{html.escape(str(sc['error'])[:120])}</i>"
    g = sc.get("gate") or {}
    v6 = sc.get("v6") or {}
    sh = sc.get("sharp") or {}
    ac = sc.get("acting") or {}
    ids = "；".join(f"{k} {v.get('sface_med')}/{v.get('sface_p10')}" for k, v in (sc.get("identity") or {}).items())
    rows = [
        ("闸门", "通过" if g.get("pass") else "不过：" + "、".join(g.get("fails") or [])),
        ("动作 mean / 静止", f"{sc.get('mean')} / {sc.get('still')}"),
        ("开头 / 结尾定住 s", f"{sc.get('head_s')} / {sc.get('tail_s')}"),
        ("J4（z）", f"{sc.get('J4')}（{sc.get('J4_z')}）"),
        ("景别 要 / 测", f"{sc.get('size_wanted')} / {sc.get('size_measured')}（脸高 {sc.get('face_h_med')}）"),
        ("身份 中位/p10", ids or "—"),
        ("手 最多 / 人", f"{v6.get('hands_max')} / {v6.get('people')}；坏手指 {v6.get('bad_finger_frac')}"),
        ("泛红 cheek_red", sc.get("cheek_red_max")),
        ("清晰度 中段/首帧", f"{sh.get('ratio_mid')}（lap 中段 {sh.get('lap_mid')}）"),
        ("首秒 / 看镜头（像素检测，旁证）", f"{(ac.get('first_sec') or {}).get('status')} / {(ac.get('camera_gaze') or {}).get('status')}"),
    ]
    return "<table>" + "".join(f"<tr><th>{a}</th><td>{html.escape(str(b))}</td></tr>" for a, b in rows) + "</table>"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "media").mkdir(exist_ok=True)
    parts = []
    for grp in GROUPS:
        cells = []
        for arm in grp["arms"]:
            exp, aid = arm["exp"], arm["id"]
            rec = load(exp).get(aid) or {}
            label = html.escape(arm.get("label", aid))
            media = ""
            if rec.get("kind") == "image" and rec.get("file"):
                src = AB / exp / rec["file"]
                if src.exists():
                    dst = OUT / "media" / f"{exp}__{src.name}"
                    shutil.copy2(src, dst)
                    media = f'<a href="media/{dst.name}"><img src="media/{dst.name}" style="max-width:300px"></a>'
            else:
                stem = f"{rec.get('shot') or arm.get('shot')}__rca_{aid}"
                for suf, tag in (("_strip.jpg", "img"), ("_prev.mp4", "video")):
                    src = AB / exp / f"{stem}{suf}"
                    if src.exists():
                        dst = OUT / "media" / f"{exp}__{src.name}"
                        shutil.copy2(src, dst)
                        media += (f'<a href="media/{dst.name}"><img src="media/{dst.name}" class="strip"></a>' if tag == "img"
                                  else f'<video src="media/{dst.name}" controls preload="none" width="216"></video>')
            body = "" if rec.get("kind") == "image" else fmt(rec.get("score"))
            gen = rec.get("gen") or {}
            cells.append(f'<div class="cell"><h4>{label}</h4><div class="sub">{html.escape(exp)} · {html.escape(str(rec.get("recipe") or ""))}'
                         f' · seed {rec.get("seed")} · {gen.get("gpu_s")} s</div>{media}{body}</div>')
        parts.append(f'<section><h2>{html.escape(grp["title"])}</h2><p class="q">{html.escape(grp.get("question", ""))}</p>'
                     f'<p class="v">{html.escape(grp.get("verdict", "（待看）"))}</p><div class="row">{"".join(cells)}</div></section>')
    page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>视频根因对比</title><style>
body{{font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;margin:16px;background:#fafafa;color:#222}}
section{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;margin:0 0 18px}}
.row{{display:flex;gap:12px;overflow-x:auto}} .cell{{min-width:330px;max-width:760px}}
.strip{{width:100%;max-width:760px;display:block;margin:4px 0}} table{{border-collapse:collapse;font-size:12px}}
th{{text-align:left;padding:1px 8px 1px 0;color:#555;font-weight:500;white-space:nowrap}} td{{padding:1px 0}}
.sub{{color:#777;font-size:12px}} .q{{color:#444}} .v{{background:#f3f7ee;border-left:3px solid #6a5;padding:6px 10px}}
h4{{margin:4px 0}}</style></head><body><h1>视频问题根因 · 控制变量对比（VIDEO-RCA）</h1>
<p>每组同一张首帧、同一 seed、同一编译器，只改一个因素。抽帧条 = 第 0 / 12 / 48 / 96 / 150 帧（原片）。数字口径 = 生产 score_clip.py；清晰度 = tools/video_rca/sharp.py（原片，不经代理）。</p>
{''.join(parts)}</body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(OUT / "index.html")


if __name__ == "__main__":
    main()
