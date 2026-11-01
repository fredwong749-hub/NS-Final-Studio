// UIPIXEL 像素级对齐 / 交互细节扫描（只读）。
// 自起无头 Chrome（CDP :9711），CDP Fetch 拦下全部非 GET/HEAD/OPTIONS（不生成、不删除、不改数据）；GET /api 带只读查看令牌 data/auth/viewer_token。
// 遍历 STATES × 尺寸 × 主题：截图 + 注入 check.js 量化 DOM 问题 + 用 CSS.forcePseudoState 量 hover/focus/active + 点展开类控件量跳动。
// 用法：node scan.mjs <round> [--only=id1,id2] [--sizes=1440x900,...] [--themes=dark,light] [--quick]
//   --quick：只跑 1440×900 深色（日常回归，UIAUDIT detect 也走这个）
// 产物：apps/web/e2e/uipixel/<round>/*.png（干净截图 + _mark 标注图）、<round>/scan.json；docs/uipixel/scan_<round>.md
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "../../../..");
const SRC = join(HERE, "../../src");
let PORT = 9711; // 9711 被上一次没退干净的 Chrome 占着时顺延到 9712…9719
const BASE = process.env.UIPX_BASE || "http://127.0.0.1:5173";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const args = process.argv.slice(2);
const round = args.find((a) => !a.startsWith("--")) || "r1";
const opt = (k) => args.find((a) => a.startsWith(`--${k}=`))?.split("=")[1];
const quick = args.includes("--quick");
const ONLY = opt("only")?.split(",");
const KONLY = opt("kinds")?.split(","); // 只统计这些类别（并跳过 hover/focus 与展开收起测量），例 --kinds=overlap
const SIZES = (opt("sizes") ?? (quick ? "1440x900" : "1280x720,1440x900,1920x1080")).split(",").map((s) => s.split("x").map(Number));
const THEMES = (opt("themes") ?? (quick ? "dark" : "dark,light")).split(",");
const CHECK = readFileSync(join(HERE, "check.js"), "utf8");
let VIEWER = "";
try { VIEWER = readFileSync(join(ROOT, "data/auth/viewer_token"), "utf8").trim(); } catch { /* 无登录 */ }

// ---------------------------------------------------------------- 页面与状态
// steps：{click:"文字"|["文字",…], within?} | {js} | {wait} | {key}
const STATES = [
  { id: "projects", title: "项目首页", path: "/#/projects" },
  { id: "script_new", title: "新建剧本", path: "/#/script-create" },
  { id: "script_read", title: "剧本阅读模式", path: "/#/script-create", steps: [{ click: "漆皮之下", within: ".v3-page" }, { wait: 2500 }, { click: "故障电梯", within: ".v3-page" }, { wait: 2500 }] },
  { id: "overview", title: "全剧总览", path: "/#/overview" },
  { id: "review", title: "画布·审片", path: "/#ep02", wait: 7000 },
  { id: "review_ep01", title: "画布·审片（第 1 集，有图）", path: "/#ep01", wait: 7000 },
  { id: "review_ep01_scroll", title: "画布·审片（第 1 集，往下滚）", path: "/#ep01", wait: 7000, steps: [{ js: "const s=[...document.querySelectorAll('*')].find(e=>{const c=getComputedStyle(e);return /(auto|scroll)/.test(c.overflowY)&&e.scrollHeight>e.clientHeight+200}); if(!s) return 'none'; s.scrollTop=900; return s.className" }, { wait: 1500 }] },
  { id: "edit_ep01", title: "画布·精修（第 1 集）", path: "/#ep01", wait: 7000, steps: [{ click: "=精修" }, { wait: 3000 }] },
  { id: "edit", title: "画布·精修（提示词）", path: "/#ep02", wait: 7000, steps: [{ click: "=精修" }, { wait: 3000 }] },
  { id: "edit_params", title: "精修·参数", path: "/#ep02", wait: 7000, steps: [{ click: "=精修" }, { wait: 2500 }, { click: "=参数" }, { wait: 1500 }] },
  { id: "edit_versions", title: "精修·版本", path: "/#ep02", wait: 7000, steps: [{ click: "=精修" }, { wait: 2500 }, { click: "=版本" }, { wait: 1500 }] },
  { id: "edit_assets", title: "精修·资产", path: "/#ep02", wait: 7000, steps: [{ click: "=精修" }, { wait: 2500 }, { click: "=资产", within: ".v3e-right, .v3e-tabs, [role=tablist]" }, { wait: 1500 }] },
  { id: "edit_sound", title: "精修·声音", path: "/#ep02", wait: 7000, steps: [{ click: "=精修" }, { wait: 2500 }, { click: "=声音", within: ".v3e-right, .v3e-tabs, [role=tablist]" }, { wait: 1500 }] },
  { id: "edit_rules", title: "精修·规则", path: "/#ep02", wait: 7000, steps: [{ click: "=精修" }, { wait: 2500 }, { click: "=规则" }, { wait: 1500 }] },
  { id: "assets", title: "资产中心", path: "/#/assets" },
  { id: "a_character", title: "资产·人物", path: "/#/assets?type=character" },
  { id: "a_linwan", title: "资产·人物页（林晚）", path: "/#/assets?type=character&char=lin_wan", wait: 6000 },
  { id: "a_look", title: "资产·形象", path: "/#/assets?type=look" },
  { id: "a_item", title: "资产·单品", path: "/#/assets?type=item" },
  { id: "a_scene", title: "资产·场景", path: "/#/assets?type=scene" },
  { id: "a_scene_open", title: "资产·场景弹框", path: "/#/assets?type=scene", steps: [{ js: "const c=document.querySelector('.v3-page [class*=card], .v3-page [class*=tile]'); if(!c) return 'none'; c.click(); return c.innerText.slice(0,30)" }, { wait: 1800 }] },
  { id: "a_voice", title: "资产·音色", path: "/#/assets?type=voice" },
  { id: "a_sheets", title: "资产·设定图", path: "/#/assets?type=sheets" },
  { id: "a_preset", title: "资产·预设", path: "/#/assets?type=preset" },
  { id: "a_loras", title: "资产·LoRA", path: "/#/assets?type=loras" },
  { id: "a_template", title: "资产·模板", path: "/#/assets?type=template" },
  { id: "sound", title: "声音页", path: "/#/sound" },
  { id: "cut", title: "成片页", path: "/#/cut" },
  { id: "trash", title: "回收站", path: "/#/trash" },
  { id: "audit", title: "操作记录", path: "/#/audit" },
  { id: "models", title: "设置 / 模型", path: "/#/models" },
];

// ---------------------------------------------------------------- CDP
const udir = join(process.env.TEMP || HERE, `uipixel_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const net = await import("node:net");
const portBusy = (p) => new Promise((res) => { const sv = net.createServer().once("error", () => res(true)).once("listening", () => sv.close(() => res(false))).listen(p, "127.0.0.1"); });
const portBusy6 = (p) => new Promise((res) => { const sv = net.createServer().once("error", () => res(true)).once("listening", () => sv.close(() => res(false))).listen(p, "::1"); });
while (PORT < 9720 && ((await portBusy(PORT)) || (await portBusy6(PORT).catch(() => false)))) PORT++;
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "about:blank"], { stdio: "ignore" });
const killChrome = () => { try { spawn("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" }); } catch { proc.kill(); } };
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => { killChrome(); process.exit(1); });
process.on("uncaughtException", (e) => { console.error(e); killChrome(); process.exit(1); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function targetWs() {
  for (let i = 0; i < 200; i++) {
    try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); const p = l.find((x) => x.type === "page"); if (p) return p.webSocketDebuggerUrl; } catch { /* not yet */ }
    await sleep(200);
  }
  throw new Error("chrome 没起来");
}
const ws = new WebSocket(await targetWs());
await new Promise((r) => (ws.onopen = r));
let mid = 0;
const pending = new Map();
let blocked = [], errs = [];
function send(method, params = {}) {
  const i = ++mid;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((res, rej) => {
    pending.set(i, { res, rej });
    setTimeout(() => pending.has(i) && (pending.delete(i), rej(new Error(`timeout ${method}`))), 30000);
  });
}
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    const u = new URL(request.url);
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) { blocked.push(`${request.method} ${u.pathname}`); return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {}); }
    if (VIEWER && u.pathname.startsWith("/api/")) {
      const headers = Object.entries(request.headers).map(([name, value]) => ({ name, value }));
      headers.push({ name: "x-ns-viewer-token", value: VIEWER });
      return send("Fetch.continueRequest", { requestId, headers }).catch(() => {});
    }
    return send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
  if (m.method === "Runtime.exceptionThrown") errs.push(m.params.exceptionDetails?.exception?.description?.slice(0, 160) ?? "exception");
};
await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable"); await send("CSS.enable");
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
const evalJs = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description?.slice(0, 200) ?? r.exceptionDetails.text);
  return r.result.value;
};
const CLICK = (texts, within) => `(() => {
  const want = ${JSON.stringify(Array.isArray(texts) ? texts : [texts])};
  const roots = ${within ? `[...document.querySelectorAll(${JSON.stringify(within)})]` : "[]"};
  const scope = roots.length ? roots : [document];
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none"; };
  const cands = scope.flatMap((root) => [...root.querySelectorAll("button, a, [role=button], [role=tab], [role=menuitem], summary, label, li, [tabindex], [class*=card], [class*=row], [class*=tile], [class*=chip]")]).filter(vis);
  for (const w of want) {
    const hit = cands.filter((e) => { const t = (e.innerText || e.getAttribute("aria-label") || e.getAttribute("title") || "").trim(); return w.startsWith("=") ? t === w.slice(1) : t.includes(w); }).sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    if (hit[0]) { hit[0].scrollIntoView({ block: "center" }); const r = hit[0].getBoundingClientRect(); return { ok: true, x: r.x + r.width / 2, y: r.y + r.height / 2 }; }
  }
  return { ok: false, want };
})()`;
async function mouseClick(x, y) { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 }); }
async function shot(file) { const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(file, Buffer.from(r.data, "base64")); }

// ---------------------------------------------------------------- hover / focus / active（CSS.forcePseudoState）
const PROPS = ["background-color", "color", "border-top-color", "box-shadow", "outline-style", "outline-color", "opacity", "text-decoration-line", "filter", "transform", "background-image"];
async function stateChecks() {
  await evalJs(`(() => { const st = document.createElement('style'); st.id = 'uipx-notrans'; st.textContent = '*,*::before,*::after{transition:none!important;animation-duration:0s!important}'; document.head.appendChild(st); return 1; })()`);
  const n = await evalJs(`(() => { document.querySelectorAll('[data-uipx-i]').forEach(e => e.removeAttribute('data-uipx-i'));
    const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < innerHeight && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > .05; };
    const els = [...document.querySelectorAll('button, a[href], [role=button], [role=tab], summary, select, [role=menuitem]')].filter(e => vis(e) && !e.disabled);
    // 按 class 签名去重：同一种按钮量一次
    const sig = new Set(); let i = 0;
    for (const e of els) { const k = e.tagName + '.' + [...e.classList].filter(c => !/^(on|active|sel|open)$/.test(c)).sort().join('.'); if (sig.has(k)) continue; sig.add(k); e.setAttribute('data-uipx-i', i++); if (i >= 160) break; }
    return i; })()`);
  const doc = await send("DOM.getDocument", { depth: -1, pierce: false });
  const q = await send("DOM.querySelectorAll", { nodeId: doc.root.nodeId, selector: "[data-uipx-i]" });
  const out = [];
  const style = async (nodeId) => { const r = await send("CSS.getComputedStyleForNode", { nodeId }); const o = {}; for (const p of r.computedStyle) if (PROPS.includes(p.name)) o[p.name] = p.value; return o; };
  const diff = (a, b) => PROPS.filter((p) => a[p] !== b[p]);
  for (const nodeId of q.nodeIds) {
    try {
      const base = await style(nodeId);
      await send("CSS.forcePseudoState", { nodeId, forcedPseudoClasses: ["hover"] });
      const hv = await style(nodeId);
      await send("CSS.forcePseudoState", { nodeId, forcedPseudoClasses: ["focus", "focus-visible"] });
      const fc = await style(nodeId);
      await send("CSS.forcePseudoState", { nodeId, forcedPseudoClasses: ["active", "hover"] });
      const ac = await style(nodeId);
      await send("CSS.forcePseudoState", { nodeId, forcedPseudoClasses: [] });
      const d = { hover: diff(base, hv).length > 0, focus: diff(base, fc).length > 0, active: diff(hv, ac).length > 0 || diff(base, ac).length > 0 };
      if (d.hover && d.focus && d.active) continue;
      const info = await evalJs(`(() => { const e = document.querySelector('[data-uipx-i="' + ${JSON.stringify(String(out.length))} + '"]'); return null; })()`);
      void info;
      const attrs = await send("DOM.getAttributes", { nodeId });
      const a = {}; for (let i = 0; i < attrs.attributes.length; i += 2) a[attrs.attributes[i]] = attrs.attributes[i + 1];
      out.push({ idx: a["data-uipx-i"], ...d });
    } catch { /* 节点在测量中被重渲染掉了 */ }
  }
  await evalJs("document.getElementById('uipx-notrans')?.remove()");
  // 把 idx 换成 selector / class / 文字
  return await evalJs(`(() => { const R = ${JSON.stringify(out)}; const res = [];
    const sel = (e) => { const parts = []; let n = e; for (let i = 0; n && n !== document.body && i < 4; i++, n = n.parentElement) { const c = [...n.classList].slice(0, 2).join('.'); parts.unshift(n.tagName.toLowerCase() + (c ? '.' + c : '')); } return parts.join(' > '); };
    const chain = (e) => { const o = []; for (let n = e, i = 0; n && n !== document.body && i < 6; n = n.parentElement, i++) for (const c of n.classList) if (!o.includes(c)) o.push(c); return o.slice(0, 8); };
    for (const r of R) { const e = document.querySelector('[data-uipx-i="' + r.idx + '"]'); if (!e) continue; const b = e.getBoundingClientRect();
      const miss = [!r.hover && 'hover', !r.focus && 'focus', !r.active && 'active'].filter(Boolean);
      const kind = !r.focus ? 'focus' : !r.hover ? 'hover' : 'active';
      res.push({ kind, sev: kind === 'focus' ? 2 : kind === 'hover' ? 2 : 1, msg: '缺少 ' + miss.map(m => ({hover:'悬停态', focus:'键盘焦点环', active:'按下（点击反馈）'}[m])).join('、'), val: miss.join('+'), sel: sel(e), cls: chain(e), text: (e.innerText || e.getAttribute('aria-label') || e.title || '').replace(/\\s+/g, ' ').trim().slice(0, 40), rect: [b.x, b.y, b.width, b.height].map(Math.round) }); }
    return res; })()`);
}

// ---------------------------------------------------------------- 展开 / 收起后布局跳动
async function toggleChecks() {
  const list = await evalJs(`(() => { const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && r.top > 0 && r.bottom < innerHeight; };
    const t = [...document.querySelectorAll('details > summary, [aria-expanded]')].filter(vis).slice(0, 8);
    return t.map((e, i) => { e.setAttribute('data-uipx-t', i); const r = e.getBoundingClientRect(); return { i, x: r.x + r.width / 2, y: r.y + r.height / 2 }; }); })()`);
  const res = [];
  for (const t of list) {
    const before = await evalJs(`(() => { const e = document.querySelector('[data-uipx-t="${t.i}"]'); if (!e) return null; const r = e.getBoundingClientRect(); const sc = document.scrollingElement.scrollTop; return [r.x, r.y, sc]; })()`);
    if (!before) continue;
    await mouseClick(t.x, t.y); await sleep(450);
    const after = await evalJs(`(() => { const e = document.querySelector('[data-uipx-t="${t.i}"]'); if (!e) return null; const r = e.getBoundingClientRect(); return [r.x, r.y, document.scrollingElement.scrollTop]; })()`);
    const info = await evalJs(`(() => { const e = document.querySelector('[data-uipx-t="${t.i}"]'); if (!e) return null; const sel = (e) => { const parts = []; let n = e; for (let i = 0; n && n !== document.body && i < 4; i++, n = n.parentElement) { const c = [...n.classList].slice(0, 2).join('.'); parts.unshift(n.tagName.toLowerCase() + (c ? '.' + c : '')); } return parts.join(' > '); }; const o = []; for (let n = e, i = 0; n && n !== document.body && i < 6; n = n.parentElement, i++) for (const c of n.classList) if (!o.includes(c)) o.push(c); const r = e.getBoundingClientRect(); return { sel: sel(e), cls: o.slice(0, 8), text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 40), rect: [r.x, r.y, r.width, r.height].map(Math.round) }; })()`);
    // 收回去（再点一次同一位置，按钮如果跳走了就点新位置）
    if (after) { const r2 = await evalJs(`(() => { const e = document.querySelector('[data-uipx-t="${t.i}"]'); const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`).catch(() => null); if (r2) { await mouseClick(r2[0], r2[1]); await sleep(300); } }
    if (!after || !info) continue;
    const dx = after[0] - before[0], dy = after[1] - before[1];
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) res.push({ kind: "jump", sev: 2, msg: `展开 / 收起后触发按钮自己移动了 (${Math.round(dx)}, ${Math.round(dy)})px`, val: `${Math.round(dx)},${Math.round(dy)}`, ...info });
  }
  return res;
}

// ---------------------------------------------------------------- 标注截图
const MARK = (iss) => `(() => { const box = document.createElement('div'); box.id = 'uipx-mark'; box.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647';
  for (const [i, it] of ${JSON.stringify(iss)}.entries()) { const [x, y, w, h] = it.rect; const d = document.createElement('div'); d.style.cssText = 'position:fixed;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px;outline:2px solid ' + (it.sev >= 3 ? '#ff2d55' : '#ffb000') + ';outline-offset:0';
    const l = document.createElement('span'); l.textContent = it.n; l.style.cssText = 'position:absolute;left:-2px;top:-14px;font:10px/12px monospace;background:' + (it.sev >= 3 ? '#ff2d55' : '#ffb000') + ';color:#000;padding:0 2px'; d.appendChild(l); box.appendChild(d); }
  document.body.appendChild(box); return 1; })()`;

// ---------------------------------------------------------------- 主循环
const outDir = join(HERE, round);
mkdirSync(outDir, { recursive: true });
const pages = [];
for (const st of STATES.filter((s) => !ONLY || ONLY.includes(s.id))) {
  for (const [w, h] of SIZES) for (const theme of THEMES) {
    blocked = []; errs = [];
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    const [p, hash = ""] = st.path.split("#");
    const url = `${BASE}${p}${p.includes("?") ? "&" : "?"}theme=${theme}${hash ? `#${hash}` : ""}`;
    await send("Page.navigate", { url: "about:blank" }).catch(() => {});
    await sleep(150);
    await send("Page.navigate", { url }).catch((e) => errs.push(String(e.message)));
    // 等页面真正出来：没有启动画面“加载中…”、正文有内容（共用 dev server 忙时首屏可能要 20 s+）
    let ready = false;
    for (let i = 0; i < 90 && !ready; i++) {
      await sleep(500);
      ready = await evalJs(`(() => !document.querySelector('.boot-load') && !/^\s*加载中/.test(document.body.innerText) && document.body.innerText.trim().length > 80 && !document.querySelector('#root > :only-child .boot-load'))()`).catch(() => false);
    }
    await sleep(st.wait ? st.wait - 2500 : 2500); // 首屏出来后再等数据
    const steps = [];
    for (const s of st.steps ?? []) {
      try {
        if (s.click) { const r = await evalJs(CLICK(s.click, s.within)); steps.push(r.ok); if (r.ok) { await mouseClick(r.x, r.y); await sleep(s.after ?? 1200); } }
        else if (s.js) { steps.push(await evalJs(`(async()=>{${s.js}})()`)); }
        else if (s.wait) await sleep(s.wait);
        else if (s.key) { await send("Input.dispatchKeyEvent", { type: "keyDown", key: s.key, code: s.key, windowsVirtualKeyCode: s.key === "Escape" ? 27 : 0 }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: s.key, code: s.key }); await sleep(500); }
      } catch (e) { steps.push("ERR " + String(e.message).slice(0, 80)); }
    }
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: w - 2, y: h - 2 }); // 鼠标移开，不让 hover 影响截图
    await sleep(300);
    const tag = `${st.id}_${w}_${theme}`;
    const png = join(outDir, `${tag}.png`);
    await shot(png);
    // 悬停才出现的格内按钮（✎ 改 / 🗑 等）：用户把鼠标放上去就会看到，重叠检查按“显示时”算
    await evalJs(`(() => { const st = document.createElement('style'); st.id = 'uipx-reveal'; st.textContent = '.ed-tile-acts, .ds-tilebar-acts { opacity: 1 !important; }'; document.head.appendChild(st); return 1; })()`).catch(() => {});
    let res;
    try { res = await evalJs(CHECK); } catch (e) { res = { issues: [], error: String(e.message) }; }
    const primary = w === SIZES[Math.min(1, SIZES.length - 1)][0] && theme === THEMES[0];
    let extra = [];
    // hover/focus/active 与主题无关、和尺寸关系也小：只在主尺寸深色量一次
    const wantState = !KONLY || KONLY.some((k) => ["hover", "focus", "active"].includes(k));
    if (primary && wantState) {
      try { extra = extra.concat(await stateChecks()); } catch (e) { steps.push("STATE ERR " + String(e.message).slice(0, 80)); }
    }
    const issues = res.issues.concat(extra).filter((x) => !KONLY || KONLY.includes(x.kind));
    issues.forEach((it, i) => (it.n = i + 1));
    if ((primary || KONLY) && issues.length) {
      try { await evalJs(MARK(issues.filter((x) => x.sev >= 2))); await shot(join(outDir, `${tag}_mark.png`)); await evalJs("document.getElementById('uipx-mark')?.remove()"); } catch { /* ignore */ }
    }
    await evalJs("document.getElementById('uipx-reveal')?.remove()").catch(() => {});
    // 展开收起会改页面，最后做
    if (primary && (!KONLY || KONLY.includes("jump"))) { try { const j = await toggleChecks(); j.forEach((it, i) => (it.n = issues.length + i + 1)); issues.push(...j); } catch (e) { steps.push("TOGGLE ERR " + String(e.message).slice(0, 80)); } }
    if (!ready) steps.push("NOT READY");
    pages.push({ id: st.id, ready, title: st.title, path: st.path, w, h, theme, shot: relative(join(HERE, ".."), png).replace(/\\/g, "/"), steps, blocked: [...new Set(blocked)], errors: [...new Set(errs)].slice(0, 5), issues, crashed: /页面出错/.test(await evalJs("document.body.innerText").catch(() => "")) });
    console.log(`${tag}: ${issues.length} issues${errs.length ? " errs=" + errs.length : ""}${steps.some((s) => s === false) ? " (步骤没点到)" : ""}`);
  }
}
ws.close();
killChrome();

// ---------------------------------------------------------------- class → 源码 file:line
const files = [];
(function walk(d) { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) walk(p); else if (/\.(tsx|css)$/.test(f)) files.push(p); } })(SRC);
const srcText = files.map((f) => ({ f, lines: readFileSync(f, "utf8").split("\n") }));
const locCache = new Map();
function locate(classes) {
  for (const c of classes ?? []) {
    if (locCache.has(c)) { const v = locCache.get(c); if (v) return v; continue; }
    const esc = c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const reTsx = new RegExp(`className=[{"'\`][^\\n]*(?<![\\w-])${esc}(?![\\w-])`);
    const reCss = new RegExp(`\\.${esc}(?![\\w-])[^{]*\\{`);
    let tsx = null, css = null;
    for (const { f, lines } of srcText) {
      for (let i = 0; i < lines.length; i++) {
        if (!tsx && f.endsWith(".tsx") && reTsx.test(lines[i])) tsx = `${relative(ROOT, f).replace(/\\/g, "/")}:${i + 1}`;
        if (!css && f.endsWith(".css") && reCss.test(lines[i])) css = `${relative(ROOT, f).replace(/\\/g, "/")}:${i + 1}`;
      }
      if (tsx && css) break;
    }
    const v = tsx || css ? { tsx, css, cls: c } : null;
    locCache.set(c, v);
    if (v) return v;
  }
  return null;
}

// ---------------------------------------------------------------- 汇总：按（种类 + 组件签名 + 量化值）去重，跨尺寸 / 主题合并
const KINDS = {
  clip: "裁切", align: "左对齐", vcenter: "标签/控件垂直居中", spacing: "间距不在刻度", padding: "同类内边距", rowcard: "同行卡片等高顶齐", radius: "圆角不一致",
  ellipsis: "省略无 title", overflow: "文字溢出", hit: "可点区域过小", cursor: "无手型指针", hover: "缺悬停态", focus: "缺焦点环", active: "缺点击反馈",
  jump: "展开收起跳动", ghost: "隐藏仍占位/空白", zindex: "z-index 遮挡", nestscroll: "滚动嵌套", sticky: "吸顶条遮挡", overlap: "文字/按钮重叠", copy: "内部词/路径", logic: "显示自相矛盾",
};
const agg = new Map();
for (const pg of pages) for (const it of pg.issues) {
  const sig = it.kind === "spacing" ? `${it.kind}|${it.sel.split(" > ").pop()}|${it.val}` : `${it.kind}|${it.sel.replace(/:nth[^ ]*/g, "")}|${it.kind === "copy" || it.kind === "logic" ? it.val : ""}`;
  if (!agg.has(sig)) agg.set(sig, { ...it, sig, where: [], loc: locate(it.cls) });
  const a = agg.get(sig);
  a.where.push({ page: pg.id, w: pg.w, theme: pg.theme, shot: pg.shot, n: it.n, val: it.val });
  a.sev = Math.max(a.sev, it.sev);
}
const items = [...agg.values()].sort((a, b) => b.sev - a.sev || b.where.length - a.where.length);
const byKind = {};
for (const it of items) byKind[it.kind] = (byKind[it.kind] ?? 0) + 1;
const summary = { round, at: new Date().toISOString(), states: [...new Set(pages.map((p) => p.id))].length, shots: pages.length, unique: items.length, sev3: items.filter((i) => i.sev >= 3).length, sev2: items.filter((i) => i.sev === 2).length, sev1: items.filter((i) => i.sev <= 1).length, byKind, crashed: pages.filter((p) => p.crashed).map((p) => `${p.id}_${p.w}_${p.theme}`), blocked: [...new Set(pages.flatMap((p) => p.blocked))] };
writeFileSync(join(outDir, "scan.json"), JSON.stringify({ summary, pages, items }, null, 1));

// ---------------------------------------------------------------- 报告
const FIX = {
  clip: "父容器去掉 overflow:hidden 或给子项 min-width:0 / 改用 grid 列宽；负 margin 去掉",
  align: "同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列",
  vcenter: "行容器 align-items:center；标签 line-height 与控件高度一致（ds-field）",
  spacing: "改成 --sp-* token（4/8/12/16/24/32）",
  padding: "同组卡片统一 padding（卡 16 / 紧凑卡 12）",
  rowcard: "行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线",
  radius: "同组卡片统一圆角 --r-m / --r-l",
  ellipsis: "加 title={全文}，或允许换行",
  overflow: "min-width:0 + text-overflow:ellipsis + title，或允许换行",
  hit: "最小 28px 高（主要按钮 32px），或用 ::after 扩点击区",
  cursor: "cursor:pointer（全局 ds.css 规则）",
  hover: "加 :hover 背景（--c-hover）",
  focus: "加 :focus-visible 焦点环（全局 ds.css 规则）",
  active: "加 :active 反馈（全局 ds.css 规则）",
  jump: "展开内容放在触发器下方；触发器不随内容高度改变位置",
  ghost: "隐藏改用条件渲染 / display:none；空元素不渲染",
  zindex: "调整层级或让遮挡层 pointer-events:none",
  sticky: "滚动区 scroll-padding-top = 吸顶条高度；吸顶条不透明底 + z-index",
  nestscroll: "只保留一层滚动（内层改 overflow:visible 或外层固定高度）",
  overlap: "同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute",
  copy: "显示人话（场景名 / 资产名），路径放 title 或隐藏",
  logic: "超出预计后改成“已 X，比预计慢”，不再显示更短的预计",
};
const md = [];
md.push(`# UIPIXEL 扫描 ${round}`, "", `生成：${summary.at} · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）`, "");
md.push(`- 状态 ${summary.states} 个 × 尺寸 ${SIZES.map((s) => s.join("×")).join(" / ")} × 主题 ${THEMES.join(" / ")} = 截图 ${summary.shots} 张（目录 apps/web/e2e/uipixel/${round}/，主尺寸另有 _mark 标注图）`);
md.push(`- **去重后问题 ${summary.unique} 条**：严重 ${summary.sev3} · 一般 ${summary.sev2} · 轻微 ${summary.sev1}`);
md.push(`- 分类：${Object.entries(byKind).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${KINDS[k] ?? k} ${v}`).join(" · ")}`);
if (summary.crashed.length) md.push(`- **页面崩溃**：${summary.crashed.join(", ")}`);
if (summary.blocked.length) md.push(`- 扫描中被拦下的写请求（未发出）：${summary.blocked.slice(0, 10).join(", ")}`);
md.push("", "## 每页问题数", "", "| 状态 | " + SIZES.flatMap(([w]) => THEMES.map((t) => `${w} ${t === "dark" ? "深" : "浅"}`)).join(" | ") + " |", "|---|" + SIZES.flatMap(() => THEMES.map(() => "---")).join("|") + "|");
for (const id of [...new Set(pages.map((p) => p.id))]) {
  const row = SIZES.flatMap(([w]) => THEMES.map((t) => pages.find((p) => p.id === id && p.w === w && p.theme === t)?.issues.length ?? "-"));
  md.push(`| ${id} ${pages.find((p) => p.id === id).title} | ${row.join(" | ")} |`);
}
md.push("", "## 问题清单（按严重度）", "", "| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |", "|---|---|---|---|---|---|---|---|---|");
items.forEach((it, i) => {
  const pagesStr = [...new Set(it.where.map((x) => x.page))].slice(0, 4).join(", ") + (new Set(it.where.map((x) => x.page)).size > 4 ? " …" : "");
  const sizes = [...new Set(it.where.map((x) => `${x.w}${x.theme === "dark" ? "d" : "l"}`))].join(" ");
  const loc = it.loc ? [it.loc.tsx, it.loc.css].filter(Boolean).join("<br>") : "—";
  const shotRef = it.where[0] ? `${it.where[0].shot.replace(/\.png$/, "")}${it.where[0].w === 1440 ? "_mark" : ""}.png #${it.where[0].n}` : "";
  md.push(`| ${i + 1} | ${"●".repeat(it.sev)} | ${KINDS[it.kind] ?? it.kind} | ${pagesStr}（${sizes}） | \`${it.sel.split(" > ").slice(-2).join(" > ").replace(/\|/g, "/")}\`${it.text ? `<br>「${it.text.replace(/\|/g, "/").slice(0, 24)}」` : ""} | ${loc} | ${String(it.val ?? "").replace(/\|/g, "/")} | ${it.msg.replace(/\|/g, "/")}<br><sub>${shotRef}</sub> | ${FIX[it.kind] ?? ""} |`);
});
mkdirSync(join(ROOT, "docs/uipixel"), { recursive: true });
writeFileSync(join(ROOT, `docs/uipixel/scan_${round}.md`), md.join("\n"));
console.log(JSON.stringify(summary));
process.exit(0);
