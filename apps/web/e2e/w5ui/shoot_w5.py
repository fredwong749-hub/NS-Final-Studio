# W5 UIUX 11-03（项目方 L-155）e2e：① 20 个旧路由逐个打开，确认没落到 404、每页顶部有一句话；② 6 张证据截图。
# 只读：无头 Chrome，非 GET 全拦；本机只读查看令牌（data/auth/viewer_token，x-ns-viewer-token）。
# 用法：python apps/web/e2e/w5ui/shoot_w5.py [BASE=http://127.0.0.1:5173] [OUT=data/review_pages/ui_20261103]
#   退出码 0 = 路由全通 + 截图全出；1 = 有路由落到 404 / 没有页头说明 / 截图失败
# “03b_queue_demo.png” 用的是假数据（标了“演示数据”），只为看清卡片长相；真实待办见 03_queue.png。
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5173"
OUT = (Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/review_pages/ui_20261103").resolve()
try:   # W5b（A5 P2-4）：OUT 可以在仓库外；建不出来 = 退出码 2（参数 / 环境问题，不是页面问题）
    OUT.mkdir(parents=True, exist_ok=True)
except OSError as e:
    print(f"✗ 截图目录建不出来：{OUT}（{e}）", file=sys.stderr)
    sys.exit(2)


def _rel(f: Path) -> str:
    """仓库内写相对路径；仓库外写绝对路径（以前 relative_to 会 ValueError 崩掉）"""
    try:
        return str(f.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(f.resolve()).replace("\\", "/")


tok = (ROOT / "data/auth/viewer_token").read_text(encoding="utf-8").strip()

ROUTES = ["#/script-create", "#/assets", "#ep01", "#/frames", "#/videos", "#/cut", "#/queue", "#/overview", "#/settings", "#/sound",
          "#/image-edit", "#/script-chat", "#/models", "#/script-ab", "#/audit", "#/trash", "#/v1-library", "#/assets-v1",
          "#/inbox", "#/projects"]

DEMO = {"count": 4, "counts": {"gate": 1, "decide": 1, "spot": 1, "pick": 1}, "status": "ok", "status_label": "", "source_errors": [],
        "auto_today": {"passed": 0, "rejected": 0, "signed": 12, "policy": 0, "redo": 3, "n_image": 40, "n_last": 9, "n_video": 6, "total": 58},
        "master_waits": {"n": 0, "title": ""}, "machine_signed": {}, "autosign_mode": "auto",
        "items": [
            {"id": "gate:demo:P1", "kind": "gate", "kind_label": "要你看", "category": "gate", "category_label": "写作闸门",
             "title": "【演示数据】《新剧》故事线写好了，等你看", "detail": "三位评委打了 38，过了 34 分的门槛。你点“用这版”才会接着写各集大纲。",
             "source": "写作流程", "media": [], "scores": [], "options": [], "recommend": None, "link": "#/script-create?run=demo"},
            {"id": "decide:demo", "kind": "decide", "kind_label": "必须你拍板", "category": "spend", "category_label": "花钱",
             "title": "【演示数据】第 1 集视频要用付费线路出 11 条", "detail": "预计花费 ¥120；免费线路排队要 9 小时。",
             "source": "总调度", "media": [], "scores": [], "recommend": {"choice": "approve", "why": "明早能看到整集"},
             "options": [{"key": "approve", "label": "同意"}, {"key": "reject", "label": "不同意"}, {"key": "later", "label": "稍后"}]},
            {"id": "spot:demo", "kind": "spot", "kind_label": "机签抽检", "category": "spot", "category_label": "机签抽检",
             "title": "【演示数据】第 1 集 镜3 · 第 2 版首帧（系统已通过）", "detail": "每 10 张抽 1 张给你看一眼。", "source": "抽检",
             "sid": "ep01-S03", "media": [], "scores": [], "recommend": {"choice": "pass", "why": "检查全过"},
             "options": [{"key": "pass", "label": "同意"}, {"key": "fail", "label": "不同意"}, {"key": "later", "label": "稍后"}], "link": "#ep01"},
            {"id": "pick:demo", "kind": "pick", "kind_label": "审美挑选", "category": "pick", "category_label": "挑一张",
             "title": "【演示数据】江予白的身份脸：挑一张", "detail": "4 张候选都过了系统检查。", "source": "资产", "media": [], "scores": [],
             "recommend": {"choice": "c2", "why": "最像参考照片"}, "link": "#/assets?type=people",
             "options": [{"key": "c1", "label": "候选 1"}, {"key": "c2", "label": "候选 2"}, {"key": "later", "label": "稍后"}]},
        ]}

bad = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    demo = {"on": False}
    blocked = []

    def route(r):
        if r.request.method not in ("GET", "HEAD"):
            blocked.append(r.request.url)
            return r.abort()
        if demo["on"] and "/api/owner/inbox" in r.request.url:
            return r.fulfill(status=200, content_type="application/json", headers={"cache-control": "no-store"}, body=json.dumps(DEMO, ensure_ascii=False))
        if "127.0.0.1" in r.request.url or "localhost" in r.request.url:
            return r.continue_(headers={**r.request.headers, "x-ns-viewer-token": tok})
        r.continue_()

    ctx.route("**/*", route)
    pg = ctx.new_page()

    # ---------------- ① 路由可达
    pg.goto(f"{BASE}/")
    pg.wait_for_selector(".v3-top", timeout=180000)
    pg.wait_for_timeout(1500)
    home = pg.evaluate("location.hash")
    rows = [{"route": "/", "landed": home, "ok": home == "#/overview"}]
    for r in ROUTES:
        pg.goto(f"{BASE}/{r}")
        try:
            pg.wait_for_selector(".v3-top", timeout=60000)
        except Exception:  # noqa: BLE001
            pass
        pg.wait_for_timeout(1800)
        st = pg.evaluate("""() => ({hash: location.hash, nf: !!document.querySelector('.pg-404'),
            intro: (document.querySelector('.pg-intro b') || {}).textContent || '', top: !!document.querySelector('.v3-top')})""")
        ok = st["top"] and not st["nf"] and bool(st["intro"])
        rows.append({"route": r, "landed": st["hash"], "intro": st["intro"], "ok": ok})
        if not ok:
            bad.append(r)
    pg.goto(f"{BASE}/#/no-such-page")
    pg.wait_for_timeout(1500)
    nf = pg.evaluate("!!document.querySelector('.pg-404')")
    rows.append({"route": "#/no-such-page", "landed": "404", "ok": nf})
    if not nf:
        bad.append("#/no-such-page 没显示 404")

    # ---------------- ② 截图
    def shot(name, path, wait_sel=None, js=None, full=False, wait=3500):
        pg.goto(f"{BASE}/{path}")
        if wait_sel:
            try:
                pg.wait_for_selector(wait_sel, timeout=120000)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{name}: 等不到 {wait_sel}（{type(e).__name__}）")
        pg.wait_for_timeout(wait)
        if js:
            pg.evaluate(js)
            pg.wait_for_timeout(800)
        f = OUT / name
        pg.screenshot(path=str(f), full_page=full)
        return _rel(f)

    shots = []
    shots.append(shot("01_home_stepbar.png", "", ".now-q", wait=6000))
    shots.append(shot("02_overview_matrix.png", "#/overview", ".pm2 .pm-cell2", wait=4000,
                      js="""(() => { const c = document.querySelector('.pm-cell2.s-blocked') || document.querySelector('.pm-cell2'); c && c.click();
                            const m = document.querySelector('.pm2'); m && m.scrollIntoView({block: 'start'}); })()"""))
    shots.append(shot("03_queue.png", "#/queue", ".oq-page"))
    demo["on"] = True
    shots.append(shot("03b_queue_demo.png", "#/queue", ".oq-two"))
    demo["on"] = False
    ctx.clear_cookies()
    pg.close()
    pg = ctx.new_page()   # 新页：演示数据不留在内存缓存里
    shots.append(shot("04_storyboard_ep01.png", "#ep01", ".v3-top", wait=8000))
    shots.append(shot("05_empty_frames_ep10.png", "#/frames?ep=10", ".pg-intro", wait=6000))
    shots.append(shot("06_404.png", "#/no-such-page", ".pg-404", wait=1500))
    b.close()

print(json.dumps({"routes": rows, "shots": shots, "blocked_non_get": len(blocked), "bad": bad}, ensure_ascii=False, indent=1))
print("✓ 路由全通、截图全出" if not bad else f"✗ {len(bad)} 处不对")
sys.exit(1 if bad else 0)
