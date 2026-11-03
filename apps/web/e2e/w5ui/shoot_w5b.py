# W5b UIUX-FIX 11-03（A5 审计 P0 条件）证据截图：
#   prod：正式 vite → 正式 :8800（还没有 /api/sop/stepbar）→ 必须看到“后台接口未更新，卡点读不到（旧接口口径）”横幅，且全页不出现“没有卡住”；
#   new ：新接口下“卡在哪”显示最新一条阻断；格子详情按时间降序；拍板类待办“要求修改”的输入框长相（演示数据，标了【演示数据】）。
# 只读：无头 Chrome，非 GET 全拦；本机只读查看令牌（data/auth/viewer_token）。
# 用法：python apps/web/e2e/w5ui/shoot_w5b.py prod|new BASE [OUT=data/review_pages/ui_20261103_b]
#   退出码 0 = 断言全过 + 截图全出；1 = 断言没过；2 = 参数 / 目录问题
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
if len(sys.argv) < 3 or sys.argv[1] not in ("prod", "new"):
    print(__doc__ or "用法：shoot_w5b.py prod|new BASE [OUT]", file=sys.stderr)
    sys.exit(2)
MODE, BASE = sys.argv[1], sys.argv[2].rstrip("/")
OUT = (Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "data/review_pages/ui_20261103_b").resolve()
try:
    OUT.mkdir(parents=True, exist_ok=True)
except OSError as e:
    print(f"✗ 截图目录建不出来：{OUT}（{e}）", file=sys.stderr)
    sys.exit(2)
tok = (ROOT / "data/auth/viewer_token").read_text(encoding="utf-8").strip()
BANNER = "后台接口未更新，卡点读不到（旧接口口径）"

DEMO = {"count": 1, "counts": {"decide": 1}, "status": "ok", "status_label": "", "source_errors": [], "auto_today": {}, "master_waits": {"n": 0, "title": ""},
        "machine_signed": {}, "autosign_mode": "auto",
        "items": [{"id": "decide:demo", "kind": "decide", "kind_label": "必须你拍板", "category": "spend", "category_label": "花钱",
                   "title": "【演示数据】第 1 集视频要用付费线路出 11 条", "detail": "预计花费 ¥120；免费线路排队要 9 小时；都过了出图契约和 OCR。",
                   "source": "总调度", "media": [], "scores": [], "recommend": {"choice": "approve", "why": "明早能看到整集"},
                   "options": [{"key": "approve", "label": "同意"}, {"key": "reject", "label": "不同意"}, {"key": "later", "label": "稍后"}]}]}

bad: list[str] = []
facts: dict = {"mode": MODE, "base": BASE}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    demo = {"on": False}
    blocked: list[str] = []

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

    def shot(name):
        f = OUT / name
        pg.screenshot(path=str(f))
        return str(f).replace("\\", "/")

    pg.goto(f"{BASE}/#/overview")
    pg.wait_for_selector(".now-q", timeout=180000)
    pg.wait_for_timeout(7000)
    body = pg.inner_text("body")
    facts["no_mei_you_ka_zhu"] = "没有卡住" not in body
    if "没有卡住" in body:
        bad.append("页面出现了“没有卡住”")
    stuck = pg.inner_text(".now-q:nth-child(3)")
    facts["now_stuck_cell"] = stuck
    nb = pg.locator(".sb-banner").count()
    facts["banners"] = nb
    shots = []
    if MODE == "prod":
        if nb < 3 or BANNER not in body or BANNER not in stuck:
            bad.append(f"fallback 横幅不够醒目：横幅 {nb} 条（要顶栏 + 现在 + 进度表 = 3）")
        shots.append(shot("01_prod_fallback_home.png"))
        pg.evaluate("document.querySelector('.pm2')?.scrollIntoView({block:'start'})")
        pg.wait_for_timeout(600)
        shots.append(shot("02_prod_fallback_matrix.png"))
    else:
        raw = pg.evaluate("fetch('/api/sop/stepbar').then(r => r.json())")
        if nb:
            bad.append("新接口下不该有“读不到”横幅")
        nb0 = (raw.get("now") or {}).get("blocked") or []
        facts["api_now_blocked"] = [{k: x.get(k) for k in ("episode", "step", "block", "owner")} for x in nb0[:3]]
        # 最新一条阻断：每个卡住格的 block = 它 issues 里最新的阻断那条
        for e in raw.get("episodes") or []:
            for sid, c in (e.get("cells") or {}).items():
                blk = [x for x in c.get("issues") or [] if x.get("blocking")]
                if c.get("state") == "blocked" and blk:
                    ats = [x.get("at") or "" for x in blk]
                    if ats != sorted(ats, reverse=True):
                        bad.append(f"第{e['episode']}集 {sid} 卡点不是降序：{ats}")
                if c.get("state") == "done" and blk:
                    bad.append(f"第{e['episode']}集 {sid} 已完成还挂挡路")
        shots.append(shot("03_new_home_latest_block.png"))
        cell = pg.locator(".pm-cell2.s-blocked").first
        if cell.count():
            cell.click()
            pg.wait_for_timeout(800)
            facts["detail"] = pg.inner_text(".pm-detail")
        shots.append(shot("04_new_matrix_detail_desc.png"))
        # 词典前后对照：API 原文（后端只删 id）vs 页面上显示的
        pairs = []
        for e in raw.get("episodes") or []:
            for sid, c in (e.get("cells") or {}).items():
                for x in c.get("issues") or []:
                    pairs.append((e["episode"], sid, x.get("text") or "", x.get("owner") or ""))
        facts["raw_issue_texts"] = pairs
        shown = []
        for btn in pg.locator(".pm-cell2").all():
            t = btn.get_attribute("title") or ""
            shown.append(t)
        facts["shown_cell_titles"] = shown
        # 拍板类待办：要求修改
        demo["on"] = True
        pg.close()
        pg = ctx.new_page()
        pg.goto(f"{BASE}/#/queue")
        pg.wait_for_selector(".oq-two", timeout=120000)
        pg.wait_for_timeout(2500)
        btn = pg.locator('.oq-two [data-act="edit"]').first
        facts["decide_edit_label"] = btn.inner_text()
        if "要求修改" not in facts["decide_edit_label"]:
            bad.append(f"拍板类第二个按钮不是“要求修改”：{facts['decide_edit_label']}")
        btn.click()
        pg.wait_for_timeout(500)
        inp = pg.locator(".oq-rev input").first
        facts["decide_edit_placeholder"] = inp.get_attribute("placeholder") if inp.count() else None
        if inp.count():
            inp.fill("先用免费线路，明早 9 点前出不完再用付费")
        facts["decide_edit_submit"] = pg.locator('.oq-rev [data-act="edit"]').first.inner_text()
        facts["queue_card_text"] = pg.inner_text(".oq-two >> xpath=ancestor::*[contains(@class,'oq-card') or self::article][1]") if pg.locator(".oq-card").count() else ""
        shots.append(shot("05_new_queue_decide_request_change.png"))
    b.close()

facts["shots"] = shots
facts["blocked_non_get"] = len(blocked)
facts["bad"] = bad
(OUT / f"facts_{MODE}.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in facts.items() if k not in ("raw_issue_texts", "shown_cell_titles")}, ensure_ascii=False, indent=1))
print("✓ 全过" if not bad else f"✗ {len(bad)} 处不对")
sys.exit(1 if bad else 0)
