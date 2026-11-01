"""VIDEO10：从同步回来的 scores / state 生成 S10V-1 对照报告（契约 V1–V8 逐项表）和审片页（不自动打开，先交总调度亲审）。

    python tools/series10_video/report.py            # → docs/series10_video/S10V1_report.md + data/review_pages/series10_video/index.html
"""
from __future__ import annotations

import html
import json
import statistics as stt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID = ROOT / "data/pipeline/runs/series10_v1/video"
DOC = ROOT / "docs/series10_video/S10V1_report.md"
PAGE = ROOT / "data/review_pages/series10_video/index.html"
ARM = {"pdd": "Ref2VA + PDD Ref2VA-Acc 8 步两段式", "b24": "纯 Ref2VA 24 步（单段 768×1344）"}
SHOT_KIND = {"ep01-S5": "单人近景", "ep01-S6": "双人对白", "ep10-S5": "走动全身"}


def renders():
    out = []
    for h in ("gpu33", "gpu36"):
        sp = VID / f"state_{h}_validate.json"
        st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        for sid, r in (st.get("shots") or {}).items():
            for x in r["renders"]:
                sp = VID / "scores" / f"{sid}__{x['variant']}.json"
                s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else (x.get("score") or {})
                out.append({"host": h, "shot": sid, **x, "score": s})
    return out


def contract(s: dict) -> list[tuple[str, str, str, str]]:
    """→ [(id, 项, 结果, 数字)]：GEN_CONTRACT §3 视频质检，阈值 = config/gen_contract.json video_thresholds（同 score_clip.GATE）"""
    if not s or s.get("error"):
        return [("V*", "打分", "不通过", (s or {}).get("error", "无打分")[:80])]
    ids = s.get("identity") or {}
    v1 = all((it or {}).get("sface_med") is not None and it["sface_med"] >= 0.30 and (it.get("seen") or 0) >= 0.15
             for it in ids.values())
    rows = [("V1", "身份（逐帧中位 / 最低）", "通过" if v1 else "不通过",
             "；".join(f"{k} 中位 {(it or {}).get('sface_med')} 最低 {(it or {}).get('sface_min')} 检出 {(it or {}).get('seen')}"
                      for k, it in ids.items())),
            ("V2", "脸颊泛红", "通过" if (s.get("cheek_red_max") or 0) <= 0.25 else "不通过", f"cheek_red_max {s.get('cheek_red_max')}"),
            ("V3", "J4 抖动", "通过" if (s.get("J4") or 0) <= 1.3 else "不通过", f"J4 {s.get('J4')}（z {s.get('J4_z')}）"),
            ("V4", "动作量 / 静止", "通过" if (s.get("mean") or 0) >= 0.5 else "不通过",
             f"mean {s.get('mean')}，静止占比 {s.get('still')}，头 / 尾定住 {s.get('head_s')}/{s.get('tail_s')} s"),
            ("V5", "镜内硬切", "通过" if not s.get("cuts") and not s.get("jump_cut_s") else "不通过",
             f"HSV 切点 {s.get('cuts')}，跳切 {s.get('jump_cut_s')}"),
            ("V6", "多肢 / 手指", (s.get("v6") or {}).get("status", "未测"),
             (s.get("v6") or {}).get("why") or "；".join(f"{k} {(s.get('v6') or {}).get(k)}" for k in ("extra_hand_frac", "dup_side_frac", "flicker", "bad_finger_frac")) if s.get("v6") else "未跑检测器"),
            ("V7", "口型", (s.get("v7") or {}).get("status", "未测"),
             (s.get("v7") or {}).get("why") or "；".join(f"{k} {(s.get('v7') or {}).get(k)}" for k in ("mode", "corr", "open_frac", "seen")) if s.get("v7") else "未跑检测器"),
            ("V9", "本地看图复核（只记录）", "未测" if (s.get("vlm") or {}).get("error") or not s.get("vlm") else
             ("通过" if (s.get("vlm") or {}).get("pass", (s.get("vlm") or {}).get("ok")) else "记录"),
             ((s.get("vlm") or {}).get("error") or json.dumps({k: v for k, v in (s.get("vlm") or {}).items()
                                                              if k in ("pass", "ok", "defects", "summary")}, ensure_ascii=False))[:160]),
            ("V8", "与首帧 / 造型一致（景别）", "通过" if "景别不符" not in ((s.get("gate") or {}).get("fails") or []) else "不通过",
             f"要求 {s.get('size_wanted')}，实测 {s.get('size_measured')}（脸高 {s.get('face_h_med')}，K-REN-122）；造型未测")]
    return rows


def summary(rs):
    arms = {}
    for x in rs:
        if x.get("state") != "scored":
            continue
        arm = x["variant"].split("_")[0]
        arms.setdefault(arm, []).append(x)
    lines = ["| 组 | 条数 | GPU 秒（中位） | mean 中位 | J4 中位 | cheek_red 最大 | 硬切条数 | 林晚 SFace 中位 | 男角 SFace 中位 | 景别符合 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, xs in arms.items():
        def med(f):
            v = [f(x) for x in xs if f(x) is not None]
            return round(stt.median(v), 3) if v else None
        lw = [x["score"]["identity"]["林晚"]["sface_med"] for x in xs if (x["score"].get("identity") or {}).get("林晚", {}).get("sface_med") is not None]
        men = [it["sface_med"] for x in xs for k, it in (x["score"].get("identity") or {}).items() if k != "林晚" and it.get("sface_med") is not None]
        lines.append(f"| {ARM.get(arm, arm)} | {len(xs)} | {med(lambda x: x.get('gpu_s'))} | {med(lambda x: x['score'].get('mean'))} | "
                     f"{med(lambda x: x['score'].get('J4'))} | {max((x['score'].get('cheek_red_max') or 0) for x in xs)} | "
                     f"{sum(1 for x in xs if x['score'].get('cuts'))} | {round(stt.median(lw), 3) if lw else None} | "
                     f"{round(stt.median(men), 3) if men else None} | "
                     f"{sum(1 for x in xs if '景别不符' not in (x['score'].get('gate') or {}).get('fails', []))}/{len(xs)} |")
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rs = sorted(renders(), key=lambda x: (x["shot"], x["variant"]))
    L = ["# S10V-1：混合配方验证（Ref2VA + PDD 两段式 vs 纯 Ref2VA 24 步）", "",
         "自动生成：tools/series10_video/report.py。只评技术指标，不评剧本内容。契约项见 docs/GEN_CONTRACT.md §3。", "",
         "## 汇总", "", summary(rs), "", "## 逐条（契约 V1–V8）", ""]
    cards = []
    for x in rs:
        s = x["score"]
        L.append(f"### {x['shot']}（{SHOT_KIND.get(x['shot'], '')}）· {x['variant']} · {ARM.get(x['variant'].split('_')[0], '')} · seed {x.get('seed')} · {x['host']} {x.get('lane')}")
        L.append("")
        if x.get("state") != "scored":
            L.append(f"未出片：{x.get('state')} {str(x.get('error') or '')[:120]}（gpu33 让卡时按 prompt_id 中断）")
            L.append("")
            continue
        L.append(f"GPU 秒 {x.get('gpu_s')}；印样 `{x.get('thumb')}`；预览 `{x.get('preview')}`；闸门 {'通过' if (s.get('gate') or {}).get('pass') else '/'.join((s.get('gate') or {}).get('fails') or [])}")
        L.append("")
        L.append("| 项 | 内容 | 结果 | 数字 |")
        L.append("|---|---|---|---|")
        for r in contract(s):
            L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
        L.append("")
        th = Path(ROOT / (x.get("thumb") or "")).relative_to(ROOT) if x.get("thumb") else None
        cards.append((x, s, th))
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(L) + "\n", encoding="utf-8")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    rel = lambda p: "../../../" + str(p).replace("\\", "/")  # noqa: E731
    items = []
    for x, s, th in cards:
        rows = "".join(f"<tr><td>{a}</td><td>{html.escape(b)}</td><td class='{'ok' if c == '通过' else 'bad' if c == '不通过' else 'na'}'>{c}</td><td>{html.escape(str(d))}</td></tr>"
                       for a, b, c, d in contract(s))
        pv = x.get("preview")
        items.append(f"<section><h3>{x['shot']} {SHOT_KIND.get(x['shot'], '')} · {x['variant']} · seed {x.get('seed')} · GPU {x.get('gpu_s')} s</h3>"
                     f"<div class='row'>{f'<video controls preload=none src={rel(pv)!r}></video>' if pv else ''}"
                     f"{f'<img src={rel(th)!r}>' if th else ''}</div><table>{rows}</table></section>")
    PAGE.write_text(f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>series10 视频审片</title>
<style>body{{font-family:system-ui,'Microsoft YaHei';margin:16px;background:#111;color:#eee}}section{{margin:18px 0;border-top:1px solid #333}}
.row{{display:flex;gap:12px;flex-wrap:wrap}}video{{width:240px}}img{{max-width:820px;width:100%}}table{{border-collapse:collapse;margin-top:8px}}
td{{border:1px solid #333;padding:3px 8px;font-size:13px}}.ok{{color:#6c6}}.bad{{color:#f66}}.na{{color:#aa8}}</style>
<h1>series10 视频 · S10V-1 混合配方验证（待总调度亲审，未给项目方）</h1><p>技术指标 + 契约 V1–V8；报告 docs/series10_video/S10V1_report.md</p>
{''.join(items)}</html>""", encoding="utf-8")
    print(DOC)
    print(PAGE)


if __name__ == "__main__":
    main()
