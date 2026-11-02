"""五条 RSI 线分数（总调度 11-02 03:5x，L-112，docs/master/RSI_PROGRAM.md；规则 K-OPS-S08）。

牵头人每轮往 data/rsi/scores.jsonl 追加一行：{"at": ISO 时间, "line": 线, "score": 0–100, "parts": {分项: 分}, "sv": 版本号, "target"?: 目标}
  （字段名也认 ts / t / time、components / items、version；line 认 config/policies/sentinel.yaml S14_rsi_lines.lines 的 id 或 aliases）
本模块：读分数 → 按线整理（summary）→ 判“2 小时没新分数 / 连续 3 轮不升”（judges.j_rsi）→ 生成每晚报告 data/review_pages/rsi/index.html。
  .venv/Scripts/python.exe tools/sentinel/rsi.py report      # 立即生成报告
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.sentinel import judges as J  # noqa: E402


def cfg() -> dict:
    from tools.autopilot import policy
    return policy.load()["sentinel"]["S14_rsi_lines"]["value"]


def load(c: dict, path: Path | None = None) -> tuple[list[dict], list[str]]:
    """→ (规范化记录, 坏行说明)。坏行不丢弃静默：返回给调用方记 UNKNOWN / 报告里列出"""
    p = path or ROOT / c["scores_file"]
    alias = {str(a).lower(): lid for lid, ln in c["lines"].items() for a in [lid, *(ln.get("aliases") or [])]}
    recs, bad = [], []
    if not p.exists():
        return [], []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except ValueError:  # arch-ok: 坏行写进 bad 返回（报告与 S0 都会显示），不当正常
            bad.append(f"第 {i} 行不是 JSON")
            continue
        t = J.ts(d.get("at") or d.get("ts") or d.get("time") or d.get("t"))
        lid = alias.get(str(d.get("line", "")).lower())
        if t is None or lid is None or d.get("score") is None:
            bad.append(f"第 {i} 行缺时间 / 线名不认识 / 无 score：{ln[:80]}")
            continue
        recs.append({"t": t, "line": lid, "score": float(d["score"]), "parts": d.get("parts") or d.get("components") or d.get("items") or {},
                     "sv": _sv(d.get("sv") or d.get("version")), "target": d.get("target"), "by": d.get("by")})
    recs.sort(key=lambda r: r["t"])
    return recs, bad


def _sv(v) -> str | None:
    """版本号：字符串原样；写成对象（{"id": "sv-…", "commit": …}）时取 id"""
    return (v.get("id") or v.get("sv")) if isinstance(v, dict) else v


def summary(c: dict, recs: list[dict], now: float) -> dict:
    out = {}
    for lid, ln in c["lines"].items():
        rs = [r for r in recs if r["line"] == lid]
        tgt = next((r["target"] for r in reversed(rs) if r.get("target") is not None), ln.get("target"))
        last = rs[-1] if rs else None
        out[lid] = {"name": ln["name"], "lead": ln["lead"], "target": tgt, "n": len(rs),
                    "score": last["score"] if last else None, "at": J.iso(last["t"]) if last else None,
                    "age_s": round(now - last["t"]) if last else None, "sv": last["sv"] if last else None,
                    "parts": last["parts"] if last else {}, "track": [[round(r["t"]), r["score"]] for r in rs[-40:]]}
    return out


# ------------------------------------------------------------------ 报告（每晚：SENTINEL S14 每 5 分钟重写一次，当晚最后一版即晚报）
def _spark(track: list, w: int = 360, h: int = 70, lo: float = 0, hi: float = 100) -> str:
    """单序列小图：中性灰 2px 线 + 末点 8px 圆点；每个点带 <title> 悬停提示；纵轴固定 0–100（各线可比）"""
    if not track:
        return f'<svg width="{w}" height="{h}" role="img" aria-label="还没有分数"><text x="8" y="{h // 2}" fill="#8b919c" font-size="12">还没有分数</text></svg>'
    t0, t1 = track[0][0], max(track[-1][0], track[0][0] + 1)
    X = lambda t: 6 + (w - 12) * (t - t0) / (t1 - t0)  # noqa: E731
    Y = lambda s: h - 6 - (h - 12) * (min(hi, max(lo, s)) - lo) / (hi - lo)  # noqa: E731
    pts = " ".join(f"{X(t):.1f},{Y(s):.1f}" for t, s in track)
    dots = "".join(f'<circle cx="{X(t):.1f}" cy="{Y(s):.1f}" r="{4 if i == len(track) - 1 else 2.5}" fill="#c9ced6"><title>{J.iso(t)[5:16]}  {s:g}</title></circle>'
                   for i, (t, s) in enumerate(track))
    grid = "".join(f'<line x1="6" x2="{w - 6}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#2a2f38" stroke-width="1"/>' for v in (0, 50, 100))
    return (f'<svg width="{w}" height="{h}" role="img" aria-label="分数轨迹">{grid}'
            f'<polyline points="{pts}" fill="none" stroke="#c9ced6" stroke-width="2" stroke-linejoin="round"/>{dots}</svg>')


def report(now: float | None = None, c: dict | None = None, out: Path | None = None, open_keys: set | None = None) -> Path:
    c = c or cfg()
    now = now or time.time()
    recs, bad = load(c)
    sm = summary(c, recs, now)
    open_keys = open_keys if open_keys is not None else _open_keys()
    e = html.escape
    rows = []
    for lid, s in sm.items():
        st = "未开始" if s["score"] is None else ("有工单" if any(k.startswith(f"S14:{lid}:") for k in open_keys) else "正常")
        dot = {"未开始": "#8b919c", "有工单": "#d98a1c", "正常": "#3fae6a"}[st]
        parts = "；".join(f"{e(str(k))} {e(str(v))}" for k, v in (s["parts"] or {}).items()) or "—"
        rows.append(f'<tr><td><span style="color:{dot}">●</span> {e(st)}</td><td><b>{e(s["name"])}</b><div class="m">{e(lid)} · 牵头 {e(s["lead"])}</div></td>'
                    f'<td class="n">{"—" if s["score"] is None else f"{s["score"]:g}"}</td><td class="n">{"未定" if s["target"] is None else e(str(s["target"]))}</td>'
                    f'<td>{_spark(s["track"])}</td><td class="m">{e(s["at"] or "—")}<br>{e(str(s["sv"] or ""))} · {s["n"]} 轮</td><td class="m">{parts}</td></tr>')
    table = "".join(f'<tr><td>{e(J.iso(r["t"]))}</td><td>{e(c["lines"][r["line"]]["name"])}</td><td class="n">{r["score"]:g}</td>'
                    f'<td>{e(str(r["sv"] or ""))}</td><td class="m">{e(json.dumps(r["parts"], ensure_ascii=False))[:200]}</td></tr>' for r in reversed(recs[-200:]))
    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>RSI 晚报</title>
<style>body{{background:#111317;color:#e8eaee;font:14px/1.5 system-ui,"Microsoft YaHei";margin:24px}}h1{{font-size:20px}}h2{{font-size:16px;margin-top:28px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #2a2f38;padding:8px;vertical-align:top;text-align:left}}th{{color:#8b919c;font-weight:normal}}
.n{{font-variant-numeric:tabular-nums;text-align:right}}.m{{color:#8b919c;font-size:12px}}</style></head><body>
<h1>五条 RSI 线 · 晚报</h1><div class="m">生成 {e(J.iso(now))} · 数据 {e(c["scores_file"])} · 标准 docs/master/RSI_PROGRAM.md（L-112）·
工单规则：{c["stale_s"] // 3600} 小时没有新分数，或连续 {c["flat_rounds"]} 轮不升 → 派牵头人（K-OPS-S08）· 圆点颜色只表示状态（灰 = 未开始，橙 = 有工单，绿 = 正常）</div>
<table><tr><th>状态</th><th>线</th><th class="n">当前分</th><th class="n">目标</th><th>轨迹（0–100）</th><th>最近一轮</th><th>分项</th></tr>{''.join(rows)}</table>
{f'<h2>读不懂的行（{len(bad)}）</h2><div class="m">' + '<br>'.join(e(b) for b in bad[:30]) + '</div>' if bad else ''}
{gpu_board(now)}
<h2>全部记录（表格视图，最近 200 条）</h2><table><tr><th>时间</th><th>线</th><th class="n">分</th><th>版本</th><th>分项</th></tr>{table}</table></body></html>"""
    out = out or ROOT / c["report"]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".html.tmp")
    tmp.write_text(doc, encoding="utf-8")
    os.replace(tmp, out)
    return out


def gpu_board(now: float) -> str:
    """晚报“GPU 漏洞榜”：data/rsi/gpu_24h.json 的空跑 / 借道 / 等待各原因按时长排序，写负责方和比昨天同一时刻变化多少
    （昨天的数取 data/rsi/gpu_24h_daily.jsonl 里约 24 小时前的那一份；每次生成报告顺手追加今天这一份）"""
    p = ROOT / "data/rsi/gpu_24h.json"
    if not p.exists():
        return "<h2>GPU 漏洞榜</h2><div class='m'>还没有 GPU 24 小时统计</div>"
    g = json.loads(p.read_text(encoding="utf-8"))
    wr = g.get("waiting_reasons") or {}
    items = {f"空跑": (g["totals"]["idle_burn"], "DEBUG-RSI"), "借道实验": (g["totals"]["borrowed"], "各借道 loop")}
    for r, s in (wr.get("seconds") or {}).items():
        items[f"等待·{(wr.get('zh') or {}).get(r, r)}"] = (s, (wr.get("owner") or {}).get(r, "总调度"))
    hist = ROOT / "data/rsi/gpu_24h_daily.jsonl"
    prev = None
    rows = [json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines() if x.strip()] if hist.exists() else []
    cands = [r for r in rows if 20 * 3600 <= now - r["t"] <= 28 * 3600]
    if cands:
        prev = min(cands, key=lambda r: abs(now - r["t"] - 86400))["items"]
    if not rows or now - rows[-1]["t"] >= 3000:
        with hist.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(now), "at": J.iso(now), "items": {k: v[0] for k, v in items.items()}}, ensure_ascii=False) + chr(10))
    e = html.escape
    trs = []
    for k, (s, own) in sorted(items.items(), key=lambda x: -x[1][0]):
        if s <= 0:
            continue
        d = "—（没有昨天的数）" if not prev or k not in prev else f"{(s - prev[k]) / 3600:+.1f} h"
        trs.append(f"<tr><td>{e(k)}</td><td class='n'>{s / 3600:.1f} h</td><td>{e(own)}</td><td class='n'>{e(d)}</td></tr>")
    segs = "".join(f"<tr><td>{e(p['label'])}</td><td>{e(p['by'])}</td><td class='n'>{p['hours']:.1f} h</td><td class='m'>{e(p['start'][5:16])} → {e(p['end'][5:16])}</td>"
                   f"<td class='m'>{e(p['note'])}</td></tr>" for p in (g.get("pause_segments") or [])[:12])
    runs_ = "".join(f"<tr><td>{e(r)}</td><td class='n'>{v['renders']}</td><td class='n'>{v['kept']}</td><td class='n'>{v['gpu_h']} h</td><td class='n'>{v['shots']}</td></tr>"
                    for r, v in (g.get("by_run") or {}).items())
    extra = ((f"<h2>暂停段（谁暂停的、为什么）</h2><table><tr><th>暂停</th><th>派单方</th><th class='n'>时长</th><th>起止</th><th>备注</th></tr>{segs}</table>" if segs else "")
             + (f"<h2>按 run（季）出图量 · 24 小时</h2><table><tr><th>run</th><th class='n'>出图次数</th><th class='n'>收下</th><th class='n'>GPU 执行</th><th class='n'>出过图的镜</th></tr>{runs_}</table>" if runs_ else ""))
    return (f"<h2>GPU 漏洞榜（生产 5 卡，{e(g['window'][0])} → {e(g['window'][1])}）</h2>"
            f"<table><tr><th>漏洞</th><th class='n'>时长</th><th>负责方</th><th class='n'>比昨天</th></tr>{''.join(trs)}</table>"
            f"<div class='m'>真正在跑 {g['totals']['pct']['productive']}% · 口径 docs/master/SLO.md“GPU 24 小时”</div>" + extra)


def _open_keys() -> set:
    try:
        return set((json.loads((ROOT / "data/sentinel/state.json").read_text(encoding="utf-8")).get("open") or {}).keys())
    except (OSError, ValueError):  # arch-ok: 报告里只用来标“有工单”，读不到按无工单显示
        return set()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(report())
