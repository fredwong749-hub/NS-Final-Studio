"""IMGFIX 审片页：data/review_pages/imgfix/index.html（本地打开）。数据 = data/ab/imgfix/takes.jsonl（tools/imgfix/ab.py）。

    .venv/Scripts/python.exe tools/imgfix/page.py
"""
from __future__ import annotations

import html
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "data/ab/imgfix/takes.jsonl"
PAGE = ROOT / "data/review_pages/imgfix"
Q2_MIN = 0.3   # config/gen_contract.json Q2_outfit.outer_min
SFACE_MIN = 0.8

ARM_TITLE = {
    "A0": "A0 现行作业（对照）",
    "P1": "P1 “平视”→“平视机位（镜头与眼睛同高）”",
    "F2": "F2 视线正向落点句放最前",
    "T3": "T3 四分之三侧脸句放最前",
    "R4": "R4 图1 只取五官身份、不取视线朝向",
    "O1": "O1 造型图换 v2_s202（画了外套）",
    "O2": "O2 设定图缺外套 → 以参考板为准",
    "T5": "T5 轻侧脸（约三十度）",
    "O2+T3": "O2+T3",
    "O2+R4+T3": "O2+R4+T3",
    "O2+T5": "O2+T5",
    "ACC": "ACC 验收①：朝向句放在身份脸句后（作废）",
    "ACC2": "ACC2 验收②：朝向句放最前（= O2+T3）",
    "F2acc": "F2acc = 现行生产（K-REN-704 终版：落点句+朝向句+K-AST-262）",
    "ACC3": "ACC3 = 现行生产（同 F2acc，S3 / S6）",
    "ACC4": "ACC4 = 换回 v2_s202 后的生产（S1 特写，特写只补可见单品）",
    "ACC5": "ACC5 = 换回 v2_s202 后的生产（S2 / S3 / S6）",
    "M1": "M1 折中：四分之三侧脸句 → 脸微微侧向",
}

# 人工目检（IMGFIX 本人看图；键 = 文件相对路径）：True = 看镜头
MANUAL = ROOT / "data/ab/imgfix/manual_gaze.json"


def rows() -> list[dict]:
    return [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]


def summary(rs: list[dict], manual: dict) -> "OrderedDict[str, dict]":
    out: OrderedDict[str, dict] = OrderedDict()
    for r in rs:
        a = out.setdefault(r["arm"], {"n": 0, "gaze_hit": 0, "gaze_meas": 0, "manual_cam": 0, "manual_n": 0,
                                      "q2_pass": 0, "q2_n": 0, "sface": []})
        m = r["metrics"]
        a["n"] += 1
        if m["gaze_mp_measured"]:
            a["gaze_meas"] += 1
            a["gaze_hit"] += int(m["gaze_mp_hit"])
        if r["file"] in manual:
            a["manual_n"] += 1
            a["manual_cam"] += int(bool(manual[r["file"]]))
        if m.get("q2_jacket") is not None:
            a["q2_n"] += 1
            a["q2_pass"] += int(m["q2_jacket"] >= Q2_MIN)
        if m.get("sface_vs_face_A") is not None:
            a["sface"].append(m["sface_vs_face_A"])
    for a in out.values():
        s = a.pop("sface")
        a["sface_mean"] = round(sum(s) / len(s), 3) if s else None
        a["sface_min"] = min(s) if s else None
    for k, a in out.items():
        q = [r["metrics"].get("q1_arcface") for r in rs if r["arm"] == k and r["metrics"].get("q1_arcface") is not None]
        a["q1"] = f"{round(sum(q) / len(q), 3)} / {min(q)} / {sum(x < 0.7 for x in q)}" if q else "未测"
    return out


def build() -> Path:
    rs = rows()
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    PAGE.mkdir(parents=True, exist_ok=True)
    e = html.escape
    rel = lambda p: "../../../" + p  # noqa: E731
    S = summary(rs, manual)
    (PAGE / "summary.json").write_text(json.dumps({"summary": S, "n_rows": len(rs)}, ensure_ascii=False, indent=1), encoding="utf-8")
    srow = "".join(
        f"<tr><th>{e(ARM_TITLE.get(k, k))}</th><td>{v['n']}</td><td>{v['gaze_hit']} / {v['gaze_meas']}</td>"
        f"<td>{v['manual_cam']} / {v['manual_n']}</td><td>{v['q2_pass']} / {v['q2_n']}</td>"
        f"<td>{v['sface_mean']}（最低 {v['sface_min']}）</td><td>{v.get('q1')}</td></tr>" for k, v in S.items())
    grid: OrderedDict = OrderedDict()
    for r in rs:
        grid.setdefault((r["shot"], r["seed"]), OrderedDict())[r["arm"]] = r
    arms = list(S.keys())

    def cell(r):
        if not r:
            return "<td>—</td>"
        m = r["metrics"]
        hit = "<span class=bad>看镜头</span>" if m["gaze_mp_hit"] else ("不看" if m["gaze_mp_measured"] else "未测")
        man = manual.get(r["file"])
        mtxt = "—" if man is None else ("<span class=bad>看镜头</span>" if man else "不看")
        q2 = m.get("q2_jacket")
        q2t = "未测" if q2 is None else (f"<span class=ok>{q2}</span>" if q2 >= Q2_MIN else f"<span class=bad>{q2}</span>")
        sf = m.get("sface_vs_face_A")
        sft = "未测" if sf is None else (f"{sf}" if sf >= SFACE_MIN else f"<span class=bad>{sf}</span>")
        return (f"<td><a href='{rel(r['file'])}'><img src='{rel(r['file'])}' loading=lazy></a><div class=m>"
                f"gaze_mp：{hit}（{m['gaze_mp_score']}）· 目检：{mtxt}<br>Q2 外套：{q2t} · sface：{sft}</div></td>")
    head = "".join(f"<th>{e(ARM_TITLE.get(a, a))}</th>" for a in arms)
    trs = "".join(f"<tr><th>{e(k[0])}<br>seed {k[1]}</th>" + "".join(cell(v.get(a)) for a in arms) + "</tr>"
                  for k, v in grid.items())
    refs = ["data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png",
            "data/pipeline/runs/series10_v1/images/refcrops/lin_wan_lookA_s101_half_nohead.png",
            "data/pipeline/runs/series10_v1/images/refcrops/lin_wan_lookA_v2_s202_half_nohead.png",
            "data/pipeline/runs/series10_v1/images/refboards/board_09a34ea5c95f.png"]
    rl = ["图1 身份脸（L-086，不改）", "现行图2：造型 A s101（没画外套）", "v2_s202（ASSETMASTER 单品检查通过，画了外套）", "图3 参考板"]
    rimg = "".join(f"<figure><img src='{rel(f)}'><figcaption>{e(t)}</figcaption></figure>" for f, t in zip(refs, rl))
    doc = f"""<!doctype html><meta charset="utf-8"><title>IMGFIX：外套缺失 + 单人看镜头</title>
<style>body{{font:14px/1.5 system-ui,"Microsoft YaHei";margin:20px;background:#111;color:#ddd}}
img{{width:210px;display:block}}table{{border-collapse:collapse;margin-bottom:18px}}td,th{{border:1px solid #444;padding:5px;vertical-align:top}}
.m{{font-size:12px;max-width:210px}}.bad{{color:#ff6b6b;font-weight:bold}}.ok{{color:#7bd88f;font-weight:bold}}
figure{{display:inline-block;margin:0 12px 0 0}}figure img{{width:180px}}figcaption{{font-size:12px;max-width:180px}}</style>
<h2>IMGFIX：出图两个系统性根因（本机道 laptop:0 · scope=ab · S★ / frame_v9 参数不动 · 身份脸不动）</h2>
<p>每臂只改一个因素，同镜同 seed。度量：gaze_mp = Q9 MediaPipe 旁证（命中 = 正对镜头）；目检 = IMGFIX 本人看图；
Q2 外套 = 契约同一探针（outer_presence，线 {Q2_MIN}）；sface = 对现行身份脸（验收线 {SFACE_MIN}）。</p>
<div>{rimg}</div>
<h3>汇总</h3><table><tr><th>臂</th><th>张数</th><th>gaze_mp 看镜头 / 测到</th><th>目检看镜头 / 看过</th><th>Q2 外套通过 / 测到</th><th>sface 均值</th><th>契约 Q1（ArcFace）均值 / 最低 / &lt;0.7</th></tr>{srow}</table>
<h3>逐张（点图看原尺寸）</h3><table><tr><th></th>{head}</tr>{trs}</table>
<p>数据：data/ab/imgfix/takes.jsonl；脚本：tools/imgfix/ab.py、tools/imgfix/page.py</p>"""
    (PAGE / "index.html").write_text(doc, encoding="utf-8")
    return PAGE / "index.html"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(build())
