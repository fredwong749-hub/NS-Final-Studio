"""VIDEO10：每集审阅（契约逐项表 + 问题归因）→ docs/series10_video/epNN_review.md、data/review_pages/series10_video/epNN/index.html。
不自动打开页面（交总调度亲审）。归因只按测得的技术指标，不评剧本内容。

    python tools/series10_video/episode_report.py <ep> <host>
"""
from __future__ import annotations

import html
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from report import contract  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ctx as RC  # noqa: E402

RUN_ID = RC.resolve()                    # MERGE-VID-O：按剧（night 传 NS_RUN）
VID = RC.vid_dir(RUN_ID)
_SUB = "" if RC.is_legacy(RUN_ID) else f"{RUN_ID}/"     # 非 V1 的审阅文档 / 页面放本剧子目录，不覆盖 V1
# K-REV-302：项目方授权的是“预览”不是“成片”。闸门全过的镜只能叫“预览·V6/V7 未测”，不得写“契约通过”
LABEL = {"done": "预览", "best_effort": "未达契约（尽力版，用尽采用最好一版进合成，L-196）", "waiting_frame": "等首帧", "blocked": "阻断"}
CAUSE = {"身份偏离": "身份：首帧路线跟首帧身份走（K-REN-R04）/ Ref2VA 男角弱（K-REN-301）→ 阶梯 r24 → alt",
         "景别不符": "景别：Ref2VA / 两段式构图来自提示词（K-REV-301）→ 阶梯 i2v / 换 seed",
         "脸部泛红": "泛红：提示词脸红词 + 只给首帧随时间加重（lab_recipes 批 1）→ 阶梯 r24",
         "动作不足": "静止：seed 相关（lab_recipes 批 2）→ 换 seed",
         "镜内硬切": "硬切：seed 相关（K-REV-R05）→ 换 seed"}


def placeholder_lines(man: dict) -> list[str]:
    """manifest 里没有代理（不进合成）的镜 → 报告行：阻断原因 / 过期片 / 状态"""
    out = []
    for s in man.get("shots") or []:
        if s.get("proxy"):
            continue
        why = s.get("block_reason") or s.get("excluded") or LABEL.get(s.get("status"), s.get("status")) or "没出片"
        out.append(f"- {s.get('shot')}{'（阻断）' if s.get('status') == 'blocked' else '（过期片）' if s.get('stale') else ''}：{why}")
    return out


def main(ep: int, host: str, ver: str = "v1"):
    st = json.loads((VID / f"state_{host}.json").read_text(encoding="utf-8"))
    try:   # 视频按镜分片（默认关）：分片集合并各台 state；关 = 原样
        import video_shard as VS
        if VS.ep_cfg(RUN_ID, ep):
            st = {**st, "shots": VS.merged_shots(VID, ep, VS.ep_hosts(RUN_ID, ep, host), json.loads((VID / "jobs.json").read_text(encoding="utf-8")))}
    except (ImportError, OSError, ValueError):   # arch-ok: 没有分片模块 / jobs 读不到 = 不合并（原行为）
        pass
    man = json.loads((VID / "episodes" / f"ep{ep:02d}" / "manifest.json").read_text(encoding="utf-8")) \
        if (VID / "episodes" / f"ep{ep:02d}" / "manifest.json").exists() else {"shots": []}
    final = RC.episodes_out(RUN_ID) / f"ep{ep:02d}_{ver}.mp4"
    shots = sorted(((sid, r) for sid, r in st["shots"].items() if int(sid[2:4]) == ep), key=lambda kv: int(kv[0].split("-S")[1]))
    fails = Counter()
    n_pass = n_be = n_wait = renders = 0
    gpu = 0.0
    L = [f"# ep{ep:02d} 视频审阅（VIDEO10 自动生成，待总调度亲审；视频不定稿，只是预览）", "",
         f"成片（预览，540×960 代理合成）：`{final.relative_to(ROOT) if final.exists() else '未合成'}`；主机 {host}", ""]
    body = []
    cards = []
    for sid, r in shots:
        xs = [x for x in r["renders"] if x.get("state") == "scored"]
        renders += len(r["renders"])
        gpu += sum(x.get("gpu_s") or 0 for x in r["renders"])
        for x in xs:
            for f in ((x.get("score") or {}).get("gate") or {}).get("fails") or []:
                fails[f] += 1
        st_ = r.get("status")
        n_pass += st_ == "done"
        n_be += st_ == "best_effort"
        n_wait += st_ in ("waiting_frame", "blocked")
        ch = next((x for x in xs if x["variant"] == r.get("chosen")), None)
        chs = (next((x for x in xs if x["variant"] == r.get("chosen")), None) or {}).get("score") or {}
        v67s = [(chs.get(k) or {}).get("status", "未测") for k in ("v6", "v7")]
        tag = "" if st_ != "done" else ("·V6/V7 未测" if "未测" in v67s else "·V6/V7 已测（阈值只用负例标定）")
        body.append(f"## {sid} · {LABEL.get(st_, st_)}{tag} · 入选 {r.get('chosen')} · 共出 {len(r['renders'])} 版")
        body.append("")
        for x in r["renders"]:
            g = (x.get("score") or {}).get("gate") or {}
            body.append(f"- {x['variant']}（{x.get('recipe')}，seed {x.get('seed')}，{x.get('lane')}，{x.get('gpu_s')} s）："
                        f"{'通过' if g.get('pass') else '/'.join(g.get('fails') or [x.get('state', '')])}")
        body.append("")
        if ch:
            body += ["| 项 | 内容 | 结果 | 数字 |", "|---|---|---|---|"]
            body += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in contract(ch["score"])]
            body += ["", f"印样 `{ch.get('thumb')}`；预览 `{ch.get('preview')}`", ""]
            cards.append((sid, st_, ch))
    L += ["> 本集是**预览**，不是成片（K-REV-302）：V6 多肢 / V7 口型检测器 11-01 才接上，阈值只用负例标定；"
          "接上前打分的镜标“V6/V7 未测”，之后的标“V6/V7 已测”，都不是“契约通过”。尽力版不进合成，缺的镜用静帧占位。", "",
          f"- 镜数 {len(shots)}：预览·V6/V7 未测 {n_pass}，未达契约（尽力，不进合成） {n_be}，等首帧 / 阻断 {n_wait}；共出片 {renders} 次，GPU {gpu / 3600:.1f} h",
          f"- 通过率（首版 / 最终）：{sum(1 for _s, r in shots if r['renders'] and ((r['renders'][0].get('score') or {}).get('gate') or {}).get('pass'))}/{len(shots)}"
          f" / {n_pass}/{len(shots)}", "", "## 问题与根因（按不合格项计数）", ""]
    L += [f"- {k} × {v}：{CAUSE.get(k, '—')}" for k, v in fails.most_common()] or ["- 无"]
    L += ["", "## 静帧占位的镜（没进合成的片子：阻断 / 过期 / 等闸门，成片用首帧静帧缓推，FIX-VID D8 / D10）", ""]
    L += placeholder_lines(man) or ["- 无"]
    L += ["", "## 未测项", "", "- V6 / V7：检测器接上前打分的镜为“未测”；V8 只测了景别，造型未测；发色只记录（K-REV-303）", ""]
    doc = ROOT / f"docs/series10_video/{_SUB}ep{ep:02d}_review.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("\n".join(L + body) + "\n", encoding="utf-8")
    page = ROOT / f"data/review_pages/series10_video/{_SUB}ep{ep:02d}/index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        shutil.copy2(final, page.parent / final.name)
    up = "../../../../"
    items = []
    for sid, st_, ch in cards:
        rows = "".join(f"<tr><td>{a}</td><td>{html.escape(b)}</td><td class='{'ok' if c == '通过' else 'bad' if c == '不通过' else 'na'}'>{c}</td>"
                       f"<td>{html.escape(str(d))}</td></tr>" for a, b, c, d in contract(ch["score"]))
        items.append(f"<section><h3>{sid} · {LABEL.get(st_, st_)} · {ch['variant']} {ch.get('recipe')}</h3><div class=row>"
                     f"<video controls preload=none src='{up}{ch.get('preview')}'></video><img src='{up}{ch.get('thumb')}'></div>"
                     f"<table>{rows}</table></section>")
    page.write_text(f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>series10 ep{ep:02d} 视频审阅</title>
<style>body{{font-family:system-ui,'Microsoft YaHei';margin:16px;background:#111;color:#eee}}section{{margin:16px 0;border-top:1px solid #333}}
.row{{display:flex;gap:12px;flex-wrap:wrap}}video{{width:240px}}img{{max-width:820px;width:100%}}table{{border-collapse:collapse}}
td{{border:1px solid #333;padding:3px 8px;font-size:13px}}.ok{{color:#6c6}}.bad{{color:#f66}}.na{{color:#aa8}}</style>
<h1>series10 ep{ep:02d} · 视频预览（待总调度亲审，不定稿）</h1><p>预览 ≠ 成片：V6 多肢 / V7 口型未测，入选镜标“预览·V6/V7 未测”，不是契约通过（K-REV-302）。</p>
{f"<video controls width=360 src='{final.name}'></video>" if final.exists() else "<p>未合成</p>"}
<p>审阅文档：docs/series10_video/ep{ep:02d}_review.md</p>{''.join(items)}</html>""", encoding="utf-8")
    print(doc, page)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(int(sys.argv[1]), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "v1")
