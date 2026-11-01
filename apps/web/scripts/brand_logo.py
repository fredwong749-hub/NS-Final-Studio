"""momoso 品牌标识生成器（UIRSI 2026-10-31，项目方原话：“momoso是我们平台名字，给个好看logo，momoso的字也改成平台名字风格”）。

原创几何字形：momoso 只用到 m / o / s 三个小写字母，全部按同一套 x-height（10 单位）、同一笔宽、圆头圆角手工构造，
不依赖字体文件，小尺寸也清楚。三个方向各有一个图形标记 + 字标处理：
  1 竖幕：9:16 竖屏画框里一个双拱 m（幕布 / 竖屏短剧），上方一点“录制灯”；字标末尾 o 用品牌渐变
  2 双环：两个相扣的圆环（momoso 里的 oo、两个人、镜头）；字标里三个 o 都用品牌渐变、笔画更重
  3 播放 m：m 的第三条腿变成播放三角；字标右倾 10°（时尚刊物感），s 用品牌渐变

运行：.venv/Scripts/python.exe apps/web/scripts/brand_logo.py
输出：apps/web/src/ds/brand_art.ts（Brand 组件用）、apps/web/public/favicon.svg（当前候选）、
      data/review_pages/brand_logo/index.html（挑选页，深浅底各一遍 + 顶栏截图示意）
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
CURRENT = 2   # 项目方 2026-10-31 原话：“候选 2 · 双环”（Brand.tsx 里的 CANDIDATE 同步）

ROSE, VIOLET, CORAL = "#FF4F8B", "#7B61FF", "#FF7A45"
GRADS = {1: (ROSE, VIOLET), 2: (ROSE, VIOLET), 3: (CORAL, ROSE)}


def grad(gid: str, a: str, b: str) -> str:
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>')


# ------------------------------------------------------------------ 字标：m / o / s 几何字形（中心线，x-height 0..10）
def g_m(x: float) -> tuple[str, float]:
    a, b, c = x + 0.8, x + 5.6, x + 10.4
    d = (f"M{a:.2f} 10 V0.9 M{a:.2f} 3.7 A2.4 2.8 0 0 1 {b:.2f} 3.7 V10 "
         f"M{b:.2f} 3.7 A2.4 2.8 0 0 1 {c:.2f} 3.7 V10")
    return d, 11.2


def g_o(x: float) -> tuple[tuple[float, float, float], float]:
    return (x + 4.8, 5.0, 4.15), 9.6


def g_s(x: float) -> tuple[str, float]:
    p = [(6.0, 2.0), (5.3, 1.0), (4.4, 0.85), (3.5, 0.85), (2.0, 0.85), (1.0, 1.7), (1.0, 2.8),
         (1.0, 5.3), (6.3, 4.4), (6.3, 7.1), (6.3, 8.5), (5.1, 9.15), (3.5, 9.15), (2.2, 9.15), (1.1, 8.6), (0.7, 7.7)]
    q = [(x + px, py) for px, py in p]
    d = f"M{q[0][0]:.2f} {q[0][1]:.2f} " + " ".join(
        f"C{q[i][0]:.2f} {q[i][1]:.2f} {q[i+1][0]:.2f} {q[i+1][1]:.2f} {q[i+2][0]:.2f} {q[i+2][1]:.2f}" for i in range(1, 16, 3))
    return d, 7.0


def wordmark(sw: float, accent: str, track: float = 1.25, skew: float = 0.0) -> tuple[str, float]:
    """→ (svg 内部片段, 宽)。accent ∈ last_o | all_o | s：哪些字形用渐变（其余 currentColor）。渐变 id 占位 __G__"""
    x, parts = 0.0, []
    idx_o = 0
    for ch in "momoso":
        if ch == "m":
            d, w = g_m(x)
            parts.append(("text", f'<path d="{d}"/>'))
        elif ch == "o":
            (cx, cy, r), w = g_o(x)
            idx_o += 1
            hot = accent == "all_o" or (accent == "last_o" and idx_o == 3)
            parts.append(("hot" if hot else "text", f'<circle cx="{cx:.2f}" cy="{cy}" r="{r}"/>'))
        else:
            d, w = g_s(x)
            parts.append(("hot" if accent == "s" else "text", f'<path d="{d}"/>'))
        x += w + track
    width = x - track
    common = f'fill="none" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"'
    text = "".join(p for k, p in parts if k == "text")
    hot = "".join(p for k, p in parts if k == "hot")
    g = f'<g {common} stroke="currentColor">{text}</g><g {common} stroke="url(#__G__)">{hot}</g>'
    if skew:
        g = f'<g transform="translate({10 * math.tan(math.radians(-skew)) * -1:.2f} 0) skewX({-skew})">{g}</g>'
    return g, width + sw


WORD = {1: wordmark(1.7, "last_o"), 2: wordmark(2.0, "all_o", track=1.1), 3: wordmark(1.55, "s", track=0.9, skew=10)}


# ------------------------------------------------------------------ 图形标记（viewBox 0 0 32 32）
def mark(n: int) -> str:
    if n == 1:
        return ('<rect x="6.5" y="1.5" width="19" height="29" rx="5.5" fill="url(#__G__)"/>'
                '<circle cx="16" cy="7.4" r="1.5" fill="#fff"/>'
                '<path d="M10.9 22.5 V12.6 M10.9 15 A2.55 2.9 0 0 1 16 15 V22.5 M16 15 A2.55 2.9 0 0 1 21.1 15 V22.5" '
                'fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>')
    if n == 2:
        a, b = GRADS[2]
        # 相扣：先画左环、再画右环，最后把左环在交叠处的一段重画在上面
        ang = math.radians(40)
        x1, y1 = 11.2 + 7.2 * math.cos(-ang), 16 + 7.2 * math.sin(-ang)
        return (f'<circle cx="11.2" cy="16" r="7.2" fill="none" stroke="{a}" stroke-width="3.4"/>'
                f'<circle cx="20.8" cy="16" r="7.2" fill="none" stroke="{b}" stroke-width="3.4"/>'
                f'<path d="M{x1:.2f} {y1:.2f} A7.2 7.2 0 0 1 18.4 16" fill="none" stroke="{a}" stroke-width="3.4" stroke-linecap="butt"/>')
    return ('<rect x="2" y="2" width="28" height="28" rx="8" fill="#14151a"/>'
            '<rect x="2.6" y="2.6" width="26.8" height="26.8" rx="7.4" fill="none" stroke="url(#__G__)" stroke-width="1.2"/>'
            '<path d="M8.6 22.4 V12.4 M8.6 14.6 A2.5 2.9 0 0 1 13.6 14.6 V22.4 M13.6 14.6 A2.5 2.9 0 0 1 18.6 14.6 V16" '
            'fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M18.9 17.2 L25.2 20.1 L18.9 23 Z" fill="url(#__G__)" stroke="url(#__G__)" stroke-width="1" stroke-linejoin="round"/>')


NAMES = {1: ("竖幕", "9:16 竖屏画框里的双拱 m，像拉开的幕布；上方一点是录制灯。字标末尾的 o 点上品牌渐变。"),
         2: ("双环", "两个相扣的圆环：momoso 里的 oo、两个人、镜头。字标里三个 o 都是渐变环，笔画最重，最“醒目”。"),
         3: ("播放 m", "m 的第三条腿变成播放键。字标右倾 10°，像时尚刊物标题；s 用珊瑚→玫红渐变。")}


def svg_mark(n: int, size: int, gid: str) -> str:
    a, b = GRADS[n]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{size}" height="{size}">'
            f'<defs>{grad(gid, a, b)}</defs>{mark(n).replace("__G__", gid)}</svg>')


def svg_word(n: int, h: float, gid: str, color: str) -> str:
    g, w = WORD[n]
    a, b = GRADS[n]
    pad = 1.2
    vw, vh = w + pad * 2, 10 + pad * 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad} {-pad} {vw:.2f} {vh:.2f}" height="{h}" '
            f'width="{h * vw / vh:.1f}" style="color:{color}"><defs>{grad(gid, a, b)}</defs>{g.replace("__G__", gid)}</svg>')


def favicon(n: int) -> str:
    a, b = GRADS[n]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">\n'
            f'  <!-- momoso 图标（候选 {n}「{NAMES[n][0]}」，apps/web/scripts/brand_logo.py 生成） -->\n'
            f'  <defs>{grad("g", a, b)}</defs>\n  {mark(n).replace("__G__", "g")}\n</svg>\n')


def write_ts() -> None:
    data = {n: {"name": NAMES[n][0], "mark": mark(n), "word": WORD[n][0], "wordW": round(WORD[n][1], 2),
                "grad": list(GRADS[n])} for n in (1, 2, 3)}
    (WEB / "src" / "ds" / "brand_art.ts").write_text(
        "// 自动生成（apps/web/scripts/brand_logo.py），勿手改。momoso 原创几何字形 + 三个图形标记候选；__G__ = 渐变 id 占位。\n"
        f"export const BRAND_ART = {json.dumps(data, ensure_ascii=False, indent=1)} as const;\n"
        "export type BrandCandidate = 1 | 2 | 3;\n", encoding="utf-8")


def write_page() -> None:
    out = ROOT / "data" / "review_pages" / "brand_logo"
    out.mkdir(parents=True, exist_ok=True)
    cards = []
    for n in (1, 2, 3):
        rows = []
        for theme, bg, fg, sub in (("深色", "#0c0d10", "#e8eaee", "#8b919c"), ("浅色", "#f6f6f4", "#17181c", "#6f727a")):
            rows.append(f'''
      <div class="pane" style="background:{bg};color:{fg}">
        <div class="lbl" style="color:{sub}">{theme}底</div>
        <div class="row big">{svg_mark(n, 96, f"m{n}{theme}a")}{svg_word(n, 56, f"w{n}{theme}a", fg)}</div>
        <div class="row">
          <div class="lock">{svg_mark(n, 40, f"m{n}{theme}b")}<div><div>{svg_word(n, 24, f"w{n}{theme}b", fg)}</div>
          <div class="subt" style="color:{sub}">AGENTIC DRAMA STUDIO</div></div></div>
        </div>
        <div class="row small">
          <span class="lbl" style="color:{sub}">顶栏 22px</span>{svg_mark(n, 22, f"m{n}{theme}c")}{svg_word(n, 14, f"w{n}{theme}c", fg)}
          <span class="lbl" style="color:{sub}">favicon 32 / 16</span>{svg_mark(n, 32, f"m{n}{theme}d")}{svg_mark(n, 16, f"m{n}{theme}e")}
        </div>
      </div>''')
        star = "已选定：候选 2（项目方 2026-10-31 原话“候选 2 · 双环”），界面已换上" if n == CURRENT else ""
        cards.append(f'''
    <section class="cand{' cur' if n == CURRENT else ''}">
      <h2>候选 {n} · {NAMES[n][0]} <small>{star}</small></h2>
      <p>{NAMES[n][1]}</p>
      <div class="panes">{''.join(rows)}</div>
    </section>''')
    html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>momoso 标识 · 三选一</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font: 14px/1.6 system-ui, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f2f2ef; color: #17181c; }}
  main {{ max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }}
  h1 {{ margin: 0 0 4px; font-size: 24px; }}
  .lead {{ color: #555; margin: 0 0 24px; }}
  .cand {{ background: #fff; border-radius: 16px; padding: 20px 24px; margin: 0 0 24px; box-shadow: 0 1px 2px rgba(0,0,0,.05), 0 8px 24px rgba(0,0,0,.05); }}
  .cand.cur {{ outline: 2px solid #7B61FF; }}
  .cand h2 {{ margin: 0; font-size: 18px; }} .cand h2 small {{ color: #7B61FF; font-weight: 500; font-size: 13px; }}
  .cand p {{ margin: 4px 0 16px; color: #555; }}
  .panes {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .pane {{ border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 20px; }}
  .row {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
  .row.big {{ gap: 24px; }}
  .lock {{ display: flex; align-items: center; gap: 10px; }}
  .subt {{ font-size: 10px; letter-spacing: .22em; font-weight: 600; margin-top: 3px; }}
  .lbl {{ font-size: 12px; }}
  figure {{ margin: 24px 0 0; }} figure img {{ width: 100%; border-radius: 12px; border: 1px solid #ddd; }}
  figcaption {{ color: #555; font-size: 13px; margin-top: 6px; }}
  @media (max-width: 900px) {{ .panes {{ grid-template-columns: 1fr; }} }}
</style></head><body><main>
  <h1>momoso · Agentic Drama Studio 标识：三个方向</h1>
  <p class="lead">都是原创几何字形（momoso 只用 m / o / s 三个字母，同一笔宽、圆头，不依赖字体文件），深浅底各展示一遍，含顶栏 22px 与 favicon 16/32px 实际尺寸。
  挑定后告诉总调度“用候选 N”，界面上换起来只改 <code>apps/web/src/ds/Brand.tsx</code> 里的一个数字。</p>
  {''.join(cards)}
  <section class="cand"><h2>在顶栏的实际位置（候选 {CURRENT}）</h2>
    <figure><img src="topbar_1920_dark.png" alt="顶栏 1920 深色"><figcaption>1920 宽 · 深色：图形 + momoso 字标 + AGENTIC DRAMA STUDIO</figcaption></figure>
    <figure><img src="topbar_1440_light.png" alt="顶栏 1440 浅色"><figcaption>1440 宽 · 浅色：≤1760 宽只留图形 + momoso 字标，≤1440 只留图形；悬停都看全称</figcaption></figure>
  </section>
</main></body></html>
'''
    (out / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    write_ts()
    (WEB / "public" / "favicon.svg").write_text(favicon(CURRENT), encoding="utf-8")
    write_page()
    print("ok")
