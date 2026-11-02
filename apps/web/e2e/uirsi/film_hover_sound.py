# FILMUI r6 · FEEDBACK aa80a9645bcd66cb3（项目方 12:5x：“视频 · 静音……不是说过要播放声音吗？没有声音啊”）
# e2e：电影胶片总览（?ui=film）悬停在有当前视频的帧上必须出声——video 元素 muted=false 且 paused=false。
# 只读：无头 Chrome，非 GET 全拦；用本机只读查看令牌（data/auth/viewer_token，x-ns-viewer-token）打开界面。
# 用法：python apps/web/e2e/uirsi/film_hover_sound.py [证据截图目录]   → 退出码 0 = 出声；1 = 静音 / 没播 / 找不到有视频的帧
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
tok = (ROOT / "data/auth/viewer_token").read_text(encoding="utf-8").strip()

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    logs = []
    pg.on("console", lambda m: "[film]" in m.text and logs.append(m.text))

    def route(r):
        if r.request.method != "GET":
            return r.abort()
        if "127.0.0.1" in r.request.url or "localhost" in r.request.url:
            return r.continue_(headers={**r.request.headers, "x-ns-viewer-token": tok})
        r.continue_()

    pg.route("**/*", route)
    pg.goto("http://127.0.0.1:5173/?ui=film#/overview")
    pg.wait_for_function("document.querySelectorAll('.fs-fr').length > 10", timeout=120000)
    pg.wait_for_timeout(3000)
    # 一次真实的用户手势（点页面标题，不触发任何导航）= 浏览器允许出声
    pg.mouse.click(60, 92)
    box = pg.evaluate("""() => { for (const e of document.querySelectorAll('.fs-fr')) {
        if (![...e.querySelectorAll('.fs-mi path')].some((x) => (x.getAttribute('d') || '').startsWith('M2 1.2'))) continue;
        e.scrollIntoView({ block: 'center', inline: 'center' }); const r = e.getBoundingClientRect();
        if (r.width > 50) return { x: r.x, y: r.y, w: r.width, h: r.height, cap: e.title }; } return null; }""")
    if not box:
        print("✗ 找不到有当前视频的帧（可能视频还没拉回本机）")
        sys.exit(1)
    pg.wait_for_timeout(600)
    box = pg.evaluate("""(cap) => { const e = [...document.querySelectorAll('.fs-fr')].find((x) => x.title === cap); const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, cap }; }""", box["cap"])
    pg.mouse.move(box["x"] + box["w"] * 0.5, box["y"] + box["h"] * 0.5)
    pg.wait_for_timeout(2500)
    st = pg.evaluate("""() => { const v = document.querySelector('.fs-hv'); if (!v) return null;
        return { muted: v.muted, paused: v.paused, t: +v.currentTime.toFixed(2), audioBytes: v.webkitAudioDecodedByteCount ?? null,
                 src: (v.currentSrc || '').split('/').pop(), tc: (document.querySelector('.fs-tc') || {}).textContent || '' }; }""")
    if OUT:
        OUT.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(OUT / "film_hover_sound_evidence.png"),
                      clip={"x": max(0, box["x"] - 10), "y": max(0, box["y"] - 30), "width": box["w"] + 20, "height": box["h"] + 60})
    ok = bool(st) and st["muted"] is False and st["paused"] is False
    print(json.dumps({"frame": box["cap"], "video": st, "console": logs[-3:]}, ensure_ascii=False))
    print("✓ 悬停出声" if ok else "✗ 悬停没有出声")
    b.close()
    sys.exit(0 if ok else 1)
