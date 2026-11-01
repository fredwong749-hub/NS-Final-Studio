// PAGEWATCH 常驻观察者（只读）：像项目方一样一直开着 #/script-create?run=series10_v1，每 2.5 分钟一轮体检。
// 一个无头 Chrome（CDP 9731），只读查看令牌，非 GET 一律拦下（回 503，不发出）。主标签页长开不刷新；
// 1920 / 浅色快照、点控件都在第二个标签页里做（同一个 Chrome，做完关掉）。
// 输出：apps/web/e2e/pagewatch/cycles/cNNN.json + shots/；控制：写 pagewatch/STOP 文件即干净退出。
// 用法：node watcher.mjs [间隔秒=150]
import { spawn, execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, existsSync, unlinkSync, appendFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..", "..", "..");
const PORT = +(process.env.PW_PORT || 9731);
const BASE = process.env.PW_BASE || "http://localhost:5173";
const API = "http://127.0.0.1:8800";
const HASH = "#/script-create?run=series10_v1";
const INTERVAL = +(process.argv[2] || 150) * 1000;
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const VT = readFileSync(join(ROOT, "data", "auth", "viewer_token"), "utf8").trim();
const INJECT = readFileSync(join(HERE, "inject.js"), "utf8");
const CHECK = readFileSync(join(ROOT, "apps", "web", "e2e", "uipixel", "check.js"), "utf8");
const CYC = join(HERE, "cycles");
const SHOTS = join(HERE, "shots");
mkdirSync(CYC, { recursive: true });
mkdirSync(SHOTS, { recursive: true });
const LOG = join(HERE, "watcher.log");
const log = (s) => { const l = `[${new Date().toISOString().slice(11, 19)}] ${s}`; console.log(l); appendFileSync(LOG, l + "\n"); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const STOPF = join(HERE, "STOP");
if (existsSync(STOPF)) unlinkSync(STOPF);

// ---------------------------------------------------------------- Chrome
const udir = join(process.env.TEMP || HERE, `pagewatch_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--disable-features=IntensiveWakeUpThrottling", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
writeFileSync(join(HERE, "chrome.pid"), String(proc.pid));
let closing = false;
async function shutdown(code = 0) {
  if (closing) return;
  closing = true;
  log("退出：关 Chrome");
  try { await sendB("Browser.close"); } catch { /* */ }
  await sleep(800);
  try { execFileSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* 已关 */ }
  process.exit(code);
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
process.on("uncaughtException", (e) => { log("未捕获异常 " + e.stack); shutdown(1); });

let ver;
for (let i = 0; i < 100 && !ver; i++) { try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch { await sleep(200); } }
const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let mid = 0;
const pending = new Map();
const handlers = new Map(); // sessionId -> fn(method, params)
ws.onmessage = (m0) => {
  const m = JSON.parse(m0.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  const h = handlers.get(m.sessionId);
  if (h) h(m.method, m.params);
};
ws.onclose = () => { if (!closing) { log("CDP 断了"); shutdown(1); } };
const sendB = (method, params = {}, sessionId) => {
  const i = ++mid;
  ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }));
  return new Promise((res, rej) => { pending.set(i, { res, rej }); setTimeout(() => pending.has(i) && (pending.delete(i), rej(new Error(`超时 ${method}`))), 45000); });
};

// 打开一个标签页并装好：拦写、加令牌、记网络 / 控制台
async function openTab(name, { width = 1440, height = 900, theme = "dark", isolated = false } = {}) {
  // 规则（总调度 11-01）：巡检绝不能改项目方的持久偏好。主标签（owner-view）用默认 profile；
  // 快照和点击巡检一律开在独立的 browser context 里（独立 localStorage / cookie，关标签即丢弃）。
  const ctx = isolated ? (await sendB("Target.createBrowserContext", { disposeOnDetach: true })).browserContextId : undefined;
  const { targetId } = await sendB("Target.createTarget", { url: "about:blank", ...(ctx ? { browserContextId: ctx } : {}) });
  const { sessionId } = await sendB("Target.attachToTarget", { targetId, flatten: true });
  const send = (m, p) => sendB(m, p, sessionId);
  const st = { name, targetId, sessionId, send, inflight: new Map(), reqs: [], netErr: [], console: [], blocked: [], sse: { opened: 0, closed: 0, msgs: 0, lastMsg: 0, errors: [] } };
  handlers.set(sessionId, (method, P) => {
    switch (method) {
      case "Fetch.requestPaused": {
        const { requestId, request } = P;
        const u = new URL(request.url);
        if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
          st.blocked.push({ t: Date.now(), method: request.method, path: u.pathname });
          return send("Fetch.fulfillRequest", { requestId, responseCode: 503, responseHeaders: [{ name: "content-type", value: "application/json" }], body: Buffer.from(JSON.stringify({ detail: "（PAGEWATCH 只读：写操作未发送）" })).toString("base64") }).catch(() => {});
        }
        if (u.pathname.startsWith("/api/") || u.pathname.startsWith("/files/")) {
          const headers = Object.entries(request.headers).map(([n, v]) => ({ name: n, value: v }));
          headers.push({ name: "x-ns-viewer-token", value: VT });
          return send("Fetch.continueRequest", { requestId, headers }).catch(() => {});
        }
        return send("Fetch.continueRequest", { requestId }).catch(() => {});
      }
      case "Network.requestWillBeSent":
        st.inflight.set(P.requestId, { t: P.timestamp, wall: Date.now(), url: P.request.url, method: P.request.method, type: P.type });
        try {
          const pth = new URL(P.request.url).pathname;
          if (/^\/api\/shots\/[^/]+$/.test(pth)) {
            st.shotInit = st.shotInit || [];
            const fr = [];
            for (let s = P.initiator?.stack; s && fr.length < 8; s = s.parent) for (const c of s.callFrames || []) if (fr.length < 8) fr.push(`${c.functionName || "?"}@${(c.url || "").split("/").pop().split("?")[0]}:${c.lineNumber + 1}`);
            st.shotInit.push({ t: Date.now(), path: pth, lastLive: null, stack: fr.join(" < ") });
          }
        } catch { /* */ }
        if (P.type === "EventSource") { st.sse.opened++; st.sse.id = P.requestId; st.sse.openedAt = Date.now(); }
        break;
      case "Network.responseReceived": {
        const f = st.inflight.get(P.requestId);
        if (f) { f.status = P.response.status; f.ttfb = P.timestamp - f.t; }
        if (P.type === "EventSource") st.sse.status = P.response.status;
        break;
      }
      case "Network.eventSourceMessageReceived": {
        st.sse.msgs++; st.sse.lastMsg = Date.now(); st.sse.last = (P.data || "").slice(0, 200);
        try {
          const e = JSON.parse(P.data);
          if (e.shot) {
            const now = Date.now();
            st.burst = (st.burst || []).filter((x) => now - x.t < 5000);
            st.burst.push({ t: now, shot: e.shot });
            const n = new Set(st.burst.map((x) => x.shot)).size;
            if (n > (st.burstMax?.n || 0)) st.burstMax = { n, at: new Date(now).toISOString(), eps: [...new Set(st.burst.map((x) => x.shot.slice(0, 4)))].join(",") };
          }
        } catch { /* 非 JSON */ }
        break;
      }
      case "Network.loadingFinished": {
        const f = st.inflight.get(P.requestId);
        st.inflight.delete(P.requestId);
        if (f) {
          const u = new URL(f.url);
          const rec = { t: f.wall, path: u.pathname + u.search, method: f.method, status: f.status, dur: +(P.timestamp - f.t).toFixed(3), bytes: P.encodedDataLength };
          if (u.pathname.startsWith("/api/") || u.pathname.startsWith("/files/")) st.reqs.push(rec);
          if (f.type === "EventSource") { st.sse.closed++; st.sse.errors.push(`结束 ${new Date().toISOString().slice(11, 19)}`); }
          if (f.status >= 400 && f.status !== 503) st.netErr.push({ t: f.wall, what: `${f.status} ${f.method} ${u.pathname}${u.search}` });
        }
        break;
      }
      case "Network.loadingFailed": {
        const f = st.inflight.get(P.requestId);
        st.inflight.delete(P.requestId);
        if (!f) break;
        const u = new URL(f.url);
        if (f.type === "EventSource") { st.sse.closed++; st.sse.errors.push(`失败 ${P.errorText} ${new Date().toISOString().slice(11, 19)}`); }
        if (!P.canceled && !/BlockedByClient/.test(P.errorText)) st.netErr.push({ t: f.wall, what: `失败 ${P.errorText} ${f.method} ${u.pathname}${u.search}` });
        break;
      }
      case "Page.frameNavigated":
        // 主框架换了文档（整页重载）：旧文档的 SSE 浏览器会直接丢掉、不发 loadingFailed，计数从这里重来
        if (!P.frame.parentId) { st.sse.opened = 0; st.sse.closed = 0; for (const [k, f] of st.inflight) if (f.type === "EventSource") st.inflight.delete(k); st.navs = (st.navs || 0) + 1; }
        break;
      case "Runtime.exceptionThrown": st.console.push({ t: Date.now(), msg: "异常 " + (P.exceptionDetails?.exception?.description ?? P.exceptionDetails?.text ?? "").split("\n").slice(0, 2).join(" | ").slice(0, 300) }); break;
      case "Runtime.consoleAPICalled":
        if (P.args?.some((a) => typeof a.value === "string" && a.value.includes("[vite]"))) { st.vite = st.vite || []; st.vite.push({ t: Date.now(), msg: P.args.map((a) => a.value ?? "").join(" ").slice(0, 160) }); }
        if (P.type === "error" || P.type === "warning") st.console.push({ t: Date.now(), lvl: P.type, msg: P.args.map((a) => a.value ?? a.description ?? "").join(" ").split("\n")[0].slice(0, 300) }); break;
      case "Log.entryAdded": if (P.entry.level === "error") st.console.push({ t: Date.now(), lvl: "log", msg: `${P.entry.source}: ${P.entry.text}`.slice(0, 300) + (P.entry.url ? ` @${P.entry.url.slice(-80)}` : "") }); break;
      case "Page.javascriptDialogOpening": st.console.push({ t: Date.now(), lvl: "dialog", msg: `${P.type}: ${P.message}`.slice(0, 200) }); send("Page.handleJavaScriptDialog", { accept: P.type === "beforeunload" }).catch(() => {}); break;
    }
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  if (name === "main") { await send("Debugger.enable").catch(() => {}); await send("Debugger.setAsyncCallStackDepth", { maxDepth: 12 }).catch(() => {}); }
  await send("Network.enable");
  await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
  await send("Page.setInterceptFileChooserDialog", { enabled: true }).catch(() => {});
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
  await send("Page.addScriptToEvaluateOnNewDocument", { source: INJECT });
  st.evalJs = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description?.split("\n")[0] ?? r.exceptionDetails.text);
    return r.result.value;
  };
  st.shot = async (fname, q = 60) => { const r = await send("Page.captureScreenshot", { format: "jpeg", quality: q }); writeFileSync(join(SHOTS, fname), Buffer.from(r.data, "base64")); return `apps/web/e2e/pagewatch/shots/${fname}`; };
  st.goto = async () => {
    await send("Page.navigate", { url: `${BASE}/?theme=${theme}${HASH}` });
    for (let i = 0; i < 80; i++) { await sleep(500); try { if (await st.evalJs(`!!document.querySelector('.ns-page') && !document.querySelector('.ns-main .ds-skel')`)) break; } catch { /* 加载中 */ } }
    await sleep(2500);
  };
  st.close = async () => { handlers.delete(sessionId); await sendB("Target.closeTarget", { targetId }).catch(() => {}); if (ctx) await sendB("Target.disposeBrowserContext", { browserContextId: ctx }).catch(() => {}); };
  return st;
}

// 关掉 Chrome 自带的 about:blank 首页，只留我们的标签
const first = (await sendB("Target.getTargets")).targetInfos.filter((t) => t.type === "page");
const main = await openTab("main");
writeFileSync(join(HERE, "main_target.txt"), main.targetId);
for (const t of first) await sendB("Target.closeTarget", { targetId: t.targetId }).catch(() => {});
await main.goto();
log(`主标签已打开 ${BASE}${HASH}`);

// ---------------------------------------------------------------- 页面内取数
const HEALTH = `(() => {
  const ov = document.querySelector('vite-error-overlay');
  const body = document.body?.innerText?.trim() ?? '';
  const eb = [...document.querySelectorAll('.ds-error, .error-boundary, [role=alert]')].map(e => e.innerText.trim().slice(0,160)).filter(Boolean);
  return { vite: ov ? (ov.shadowRoot?.textContent || 'overlay').slice(0,400) : null, bodyLen: body.length, white: body.length < 30, alerts: eb.slice(0,6), hash: location.hash, theme: document.documentElement.dataset.theme || document.documentElement.className, live: document.querySelector('.live-ind')?.className ?? null, liveText: document.querySelector('.live-ind')?.textContent ?? null, lastLive: (window.__live||[]).slice(-5) };
})()`;
const UISNAP = `(() => {
  const t = (s) => [...document.querySelectorAll(s)].map(e => e.innerText.replace(/\\s+/g,' ').trim());
  const sps = [...document.querySelectorAll('.sp:not(.sp-skel)')].map(sp => {
    const host = sp.closest('.ns-sep') ? 'ep' + (sp.closest('.ns-sep').querySelector('.ns-sep-n')?.textContent.match(/\\d+/)?.[0] ?? '?') : (sp.querySelector('.sp-head b')?.textContent || sp.getAttribute('aria-label') || 'sp');
    return { host, segs: [...sp.querySelectorAll('.sp-seg')].map(s => ({ title: s.getAttribute('title'), fill: s.querySelector('.sp-fill')?.style.width, run: !!s.querySelector('.sp-run'), bad: !!s.querySelector('.sp-bad') })) };
  });
  return {
    runRows: t('.ns-runs > *').slice(0,10),
    seps: [...document.querySelectorAll('.ns-sep')].map(b => ({ n: b.querySelector('.ns-sep-n')?.textContent, t: b.querySelector('.ns-sep-t')?.textContent, cls: b.className })),
    seriesNote: document.querySelector('.ns-series > .ds-small')?.textContent ?? null,
    sps,
    head: t('.ns-main h1, .ns-main h2, .ns-main h3').slice(0,12),
    badges: t('.ns-main .ds-badge, .ns-main .badge').slice(0,20),
    skels: document.querySelectorAll('.ds-skel, .sp-skel').length,
    rows: document.querySelectorAll('.v3-row').length,
    textLen: document.querySelector('.ns-main')?.innerText.length ?? 0,
    mainSig: (document.querySelector('.ns-main')?.innerText ?? '').replace(/\\s+/g,' ').slice(0, 600),
  };
})()`;

const apiGet = async (p) => {
  const t = Date.now();
  try {
    const r = await fetch(API + p, { headers: { "x-ns-viewer-token": VT } });
    const txt = await r.text();
    let j = null; try { j = JSON.parse(txt); } catch { /* 非 JSON */ }
    return { status: r.status, ms: Date.now() - t, j, bytes: txt.length };
  } catch (e) { return { status: 0, ms: Date.now() - t, err: String(e) }; }
};

// ---------------------------------------------------------------- 第二标签：快照 + 点控件
async function sideSnapshots(n) {
  const out = [];
  for (const [w, h, theme] of [[1920, 1080, "dark"], [1440, 900, "light"], [1920, 1080, "light"]]) {
    const tab = await openTab(`side${w}${theme}`, { width: w, height: h, theme, isolated: true });
    try {
      await tab.goto();
      const shot = await tab.shot(`c${n}_${w}_${theme}.jpg`);
      const chk = await tab.evalJs(CHECK).catch((e) => ({ err: String(e) }));
      out.push({ w, theme, shot, health: await tab.evalJs(HEALTH), issues: (chk?.issues ?? []).filter((i) => i.sev !== "info").slice(0, 60), console: tab.console, netErr: tab.netErr, blocked: tab.blocked });
    } catch (e) { out.push({ w, theme, err: String(e) }); }
    await tab.close();
  }
  return out;
}

// 安全控件：标签、集号、展开 / 收起、缩略图放大。按文字 / 类名白名单，写操作按钮跳过（反正也会被拦）。
const CLICK_LIST = `(() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const WRITE = /删除|删掉|导入|开始|重写|返修|保存|接受|打回|继续写|停止|暂停|恢复|确认|提交|发送|上传|还原|清空|生成|重出|采用|换用|定脸|撤销|新建|用这张|不要|🗑|✎|回收站|指出哪里不对|插队|重做/;
  const out = [];
  const els = [...document.querySelectorAll('button, [role=tab], summary, a[href^="#"], .ns-sep, img[data-zoom], .zoomable, [data-zoom]')];
  els.forEach((e, i) => {
    if (!vis(e) || e.closest('.v3-topbar, header, .tb3')) return;
    const txt = (e.innerText || e.getAttribute('aria-label') || e.title || '').replace(/\\s+/g, ' ').trim().slice(0, 50);
    if (WRITE.test(txt) || e.disabled) return;
    e.setAttribute('data-pw', String(i));
    const r = e.getBoundingClientRect();
    out.push({ i, tag: e.tagName.toLowerCase(), cls: e.className?.toString().slice(0, 50), txt, w: Math.round(r.width), h: Math.round(r.height) });
  });
  return out;
})()`;
async function clickPass(n) {
  const tab = await openTab("click", { isolated: true });
  const res = [];
  try {
    await tab.goto();
    const list = await tab.evalJs(CLICK_LIST);
    const seen = {};
    for (const c0 of list.slice(0, 40)) {
      // 每次点之前重新打标（上一下点击可能让节点重建），按“文字 + 第几个同名”找回同一个控件
      const occ = (seen[c0.txt] = (seen[c0.txt] ?? -1) + 1);
      const relist = await tab.evalJs(CLICK_LIST);
      const c = relist.filter((x) => x.txt === c0.txt)[occ];
      if (!c) { res.push({ ...c0, found: false, reacted: false, gone: true }); continue; }
      await tab.evalJs(`window.__pwDrain && window.__pwDrain()`);
      const SIGX = `(() => { const s = (document.querySelector('.sf-page')?.innerText ?? '') + location.hash + [...document.querySelectorAll('[open], .on, [aria-expanded=true], [aria-selected=true], [aria-pressed=true], [role=dialog], .mp-lightbox, .zl-open, .zl-layer, .sel')].map(e => e.tagName + e.className).join(','); let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h + ':' + s.length; })()`;
      const before = await tab.evalJs(SIGX);
      const nErr = tab.console.length + tab.netErr.length;
      const ok = await tab.evalJs(`(() => { const e = document.querySelector('[data-pw="${c.i}"]'); if (!e) return false; e.scrollIntoView({block:'center'}); e.click(); return true; })()`);
      await sleep(1200);
      const after = await tab.evalJs(SIGX);
      const d = await tab.evalJs(`window.__pwDrain ? window.__pwDrain() : null`);
      const health = await tab.evalJs(HEALTH);
      res.push({ ...c, found: ok, reacted: before !== after, before, after, newErr: [...tab.console, ...tab.netErr].slice(nErr - (tab.console.length + tab.netErr.length) || undefined).map((x) => x.msg || x.what), blocked: tab.blocked.length, white: health.white, vite: !!health.vite, shifts: d?.shifts?.filter((s) => !s.input).length ?? 0 });
      // 弹层就 Esc 关掉；跳走了就回来
      await tab.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      await tab.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      if (!(await tab.evalJs(`location.hash`)).startsWith("#/script-create")) { await tab.goto(); await tab.evalJs(CLICK_LIST); }
    }
    res.push({ summary: true, blockedWrites: tab.blocked, shot: await tab.shot(`c${n}_clickend.jpg`) });
    // 点击巡检会改本地偏好（如“阅读模式”存在 localStorage，同一 Chrome 的主标签也会跟着变），巡检完恢复成项目方默认的“每镜完整一行”
    await tab.evalJs(`(() => { try { localStorage.setItem('ns.script.view', 'full'); } catch {} const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === '每镜完整一行'); b && b.click(); return 1; })()`).catch(() => {});
  } catch (e) { res.push({ err: String(e) }); }
  await tab.close();
  return res;
}

// ---------------------------------------------------------------- 一轮
let cycle = existsSync(join(CYC, "latest.txt")) ? +readFileSync(join(CYC, "latest.txt"), "utf8") : 0; // 重启接着编号
let prevSnap = null;
let lsBase = null; // 主标签 localStorage 基线（项目方偏好），巡检不得改变
let prevApi = null;
async function runCycle() {
  cycle++;
  const n = String(cycle).padStart(3, "0");
  const T = Date.now();
  const rec = { cycle, at: new Date().toISOString(), base: BASE };
  try {
    const lsNow = await main.evalJs(`JSON.stringify(Object.fromEntries(Object.keys(localStorage).filter(k => /view|mode|filter|theme|tab|sort|zoom|pref|collapse|expand|density|lang/i.test(k) && !/last|cache|pending|seen|ts$/i.test(k)).sort().map(k => [k, localStorage.getItem(k)])))`);
    if (lsBase === null) lsBase = lsNow;
    else if (lsNow !== lsBase) { rec.lsChanged = { before: lsBase, after: lsNow }; log("注意：主标签偏好（localStorage）变了（巡检已隔离，若是巡检造成即为违规）：" + lsNow.slice(0, 200)); lsBase = lsNow; }
    rec.health = await main.evalJs(HEALTH);
    rec.drain = await main.evalJs(`window.__pwDrain ? window.__pwDrain() : null`);
    rec.ui = await main.evalJs(UISNAP);
    rec.shot = await main.shot(`c${n}_1440_dark.jpg`);
    const chk = await main.evalJs(CHECK).catch((e) => ({ err: String(e) }));
    rec.layout = (chk?.issues ?? []).filter((i) => i.sev !== "info").slice(0, 80);
    rec.layoutErr = chk?.err;
  } catch (e) { rec.mainErr = String(e); }
  // 网络 / 控制台（本轮新增）
  rec.console = main.console.splice(0);
  rec.vite = (main.vite || []).splice(0);
  rec.burstMax = main.burstMax || null; main.burstMax = null;
  const si = (main.shotInit || []).splice(0);
  if (si.length > 12) { const g = {}; for (const x of si) g[x.stack] = (g[x.stack] || 0) + 1; rec.shotStorm = { n: si.length, from: new Date(si[0].t).toISOString(), to: new Date(si[si.length - 1].t).toISOString(), stacks: g }; }
  // HMR 窗口（热更新前后 4 秒）里的闪烁 / 骨架 / 换节点算开发热更新，不算产品 bug
  const hmrT = rec.vite.filter((v) => /hot updated|page reload/.test(v.msg)).map((v) => v.t);
  const inHmr = (t) => hmrT.some((h) => Math.abs(h - t) < 4000);
  if (rec.drain) {
    rec.drain.flashesHmr = rec.drain.flashes.filter((f) => inHmr(f.t)).length;
    rec.drain.flashes = rec.drain.flashes.filter((f) => !inHmr(f.t));
    rec.drain.skelHmr = rec.drain.skel.filter((f) => inHmr(f.t)).length;
    rec.drain.skel = rec.drain.skel.filter((f) => !inHmr(f.t));
    rec.drain.muts = rec.drain.muts.filter((f) => !inHmr(f.t));
  }
  rec.netErr = main.netErr.splice(0);
  const reqs = main.reqs.splice(0);
  rec.reqCount = reqs.length;
  rec.slow = reqs.filter((r) => r.dur > 2).map((r) => `${r.dur}s ${r.method} ${r.path} ${r.status} ${Math.round((r.bytes || 0) / 1024)}KB`);
  const byPath = {};
  for (const r of reqs) { const k = r.path.split("?")[0]; byPath[k] = (byPath[k] || 0) + 1; }
  rec.reqByPath = byPath;
  rec.blocked = main.blocked.splice(0);
  rec.sse = { ...main.sse, errors: main.sse.errors.splice(0), sinceLastMsg_s: main.sse.lastMsg ? Math.round((Date.now() - main.sse.lastMsg) / 1000) : null, stillOpen: main.sse.id ? main.inflight.has(main.sse.id) : false };
  // 直接读接口
  const api = {};
  for (const p of ["/api/story-runs", "/api/story-runs/series10_v1", "/api/progress?run=series10_v1", "/api/render-tasks", "/api/producer/status"]) api[p] = await apiGet(p);
  rec.apiTiming = Object.fromEntries(Object.entries(api).map(([k, v]) => [k, `${v.status} ${v.ms}ms ${Math.round((v.bytes || 0) / 1024)}KB`]));
  // UI 对接口：进度条
  const prog = api["/api/progress?run=series10_v1"].j;
  const mism = [];
  if (prog && rec.ui) {
    for (const sp of rec.ui.sps) {
      const m = sp.host.match(/^ep(\d+)$/);
      const segs = m ? prog.episodes.find((e) => e.episode === +m[1])?.segs : null;
      if (!segs) continue;
      sp.segs.forEach((s, i) => {
        const k = prog.order[i];
        const a = segs[k];
        if (!a || !s.title) return;
        const mm = s.title.match(/：(\d+)\/(\d+)/);
        if (mm && (+mm[1] !== a.done || +mm[2] !== a.total)) mism.push(`${sp.host} ${k} 页面 ${mm[1]}/${mm[2]} ≠ 接口 ${a.done}/${a.total}`);
        const pct = a.total ? Math.min(100, (a.done / a.total) * 100) : 0;
        if (s.fill && Math.abs(parseFloat(s.fill) - pct) > 0.5) mism.push(`${sp.host} ${k} 条宽 ${s.fill} ≠ ${pct.toFixed(1)}%`);
        if (!!a.running !== s.run && a.total) mism.push(`${sp.host} ${k} 进行中 页面${s.run} 接口${a.running}`);
        if (!!a.failed !== s.bad) mism.push(`${sp.host} ${k} 失败标 页面${s.bad} 接口${a.failed}`);
      });
    }
    // 倒退
    if (prevApi?.prog) for (const e of prog.episodes) {
      const pe = prevApi.prog.episodes.find((x) => x.episode === e.episode);
      if (!pe) continue;
      for (const k of prog.order) if (e.segs[k] && pe.segs[k] && e.segs[k].done < pe.segs[k].done) mism.push(`倒退 ep${e.episode} ${k} ${pe.segs[k].done}→${e.segs[k].done}`);
    }
  }
  rec.progMismatch = mism;
  // 集列表、运行状态
  const run = api["/api/story-runs/series10_v1"].j;
  if (run && rec.ui) {
    const eps = run.series_eps ?? [];
    rec.runCheck = { apiEps: eps.length, uiEps: rec.ui.seps.length, apiStatus: run.status, apiEpisode: run.episode, uiOn: rec.ui.seps.filter((s) => / on\b/.test(s.cls)).map((s) => s.n) };
    const ok = eps.filter((e) => e.stages?.P4 === "ok").length;
    const want = ok === eps.length ? `${eps.length} 集都写好了` : `${ok}/${eps.length} 集写好了`;
    if (rec.ui.seriesNote !== null && rec.ui.seriesNote !== want) mism.push(`集条小字 页面「${rec.ui.seriesNote}」≠ 接口「${want}」`);
    if (eps.length !== rec.ui.seps.length) mism.push(`集数 页面 ${rec.ui.seps.length} ≠ 接口 ${eps.length}`);
  }
  const rt = api["/api/render-tasks"].j;
  rec.renderCounts = rt?.counts ?? null;
  // 陈旧：接口进度变了，但页面在 30 s 内没跟上——由 watchStale 单独做
  prevApi = { prog, run, at: Date.now() };
  // 跨轮对比：页面整块没动但数据变了
  rec.uiChangedSincePrev = prevSnap ? JSON.stringify(prevSnap.sps) !== JSON.stringify(rec.ui?.sps) : null;
  prevSnap = rec.ui;
  // 周期性的附加检查
  if (cycle % 4 === 1) { rec.side = await sideSnapshots(n).catch((e) => ({ err: String(e) })); }
  if (cycle % 4 === 2) { rec.clicks = await clickPass(n).catch((e) => ({ err: String(e) })); }
  if (cycle % 6 === 1) {
    try {
      const out = execFileSync(join(ROOT, ".venv", "Scripts", "python.exe"), [join(ROOT, "tools", "qa", "data_parity.py"), "--ui", String(((cycle / 6) | 0) % 10 + 1), "--json", join(CYC, `c${n}_parity.json`)], { cwd: ROOT, env: { ...process.env, DA_PORT: String(PORT + 1), PYTHONIOENCODING: "utf-8" }, timeout: 300000, encoding: "utf8" });
      rec.parity = { code: 0, tail: out.split("\n").slice(-25).join("\n") };
    } catch (e) { rec.parity = { code: e.status, tail: String(e.stdout || e.message).split("\n").slice(-30).join("\n") }; }
  }
  rec.elapsed_s = Math.round((Date.now() - T) / 1000);
  writeFileSync(join(CYC, `c${n}.json`), JSON.stringify(rec, null, 1));
  writeFileSync(join(CYC, "latest.txt"), n);
  const d = rec.drain || {};
  const fl = d.flashes || [];
  log(`c${n} 整页重载${rec.vite.filter((v) => /\[vite\] connecting/.test(v.msg)).length} HMR${hmrT.length}(闪${rec.drain?.flashesHmr ?? 0})${rec.shotStorm ? ` 镜详情风暴${rec.shotStorm.n}` : ""}${rec.burstMax ? ` 事件阵${rec.burstMax.n}镜` : ""} 控制台${rec.console.length} 网络错${rec.netErr.length} 慢${rec.slow.length} 请求${rec.reqCount} SSE[开${rec.sse.stillOpen} 消息${rec.sse.msgs} 距今${rec.sse.sinceLastMsg_s}s] 闪${fl.length}(无变化${fl.filter((f) => f.changed === false).length} 大块${fl.filter((f) => f.area > 0.3).length}) 换同节点${(d.muts || []).reduce((a, m) => a + m.sameRemount, 0)} 跳动${(d.shifts || []).filter((s) => !s.input).reduce((a, s) => a + s.v, 0).toFixed(3)} 骨架重现${(d.skel || []).length} 进度不符${mism.length} 布局${rec.layout?.length} ${rec.elapsed_s}s`);
}

// 陈旧检测：每 10 s 比一次接口进度和页面进度条，接口变了而页面 30 s 还没跟上就记下
const staleLog = join(HERE, "stale.log");
let staleSince = null;
async function watchStale() {
  while (!closing) {
    await sleep(10000);
    try {
      const p = (await apiGet("/api/progress?run=series10_v1")).j;
      const ui = await main.evalJs(`[...document.querySelectorAll('.ns-sep')].map(b => [b.querySelector('.ns-sep-n')?.textContent.match(/\\d+/)?.[0], [...b.querySelectorAll('.sp-seg')].map(s => (s.getAttribute('title')||'').match(/：(\\d+\\/\\d+)/)?.[1] ?? '')])`);
      if (!p || !ui) continue;
      const diffs = [];
      for (const [ep, segs] of ui) {
        const e = p.episodes.find((x) => x.episode === +ep);
        if (!e) continue;
        segs.forEach((v, i) => { const s = e.segs[p.order[i]]; if (s && v && v !== `${s.done}/${s.total}`) diffs.push(`ep${ep} ${p.order[i]} 页面${v} 接口${s.done}/${s.total}`); });
      }
      if (diffs.length) {
        staleSince ??= Date.now();
        if (Date.now() - staleSince > 30000) appendFileSync(staleLog, `${new Date().toISOString()} 陈旧${Math.round((Date.now() - staleSince) / 1000)}s ${diffs.slice(0, 6).join("; ")}\n`);
      } else staleSince = null;
    } catch { /* 页面忙 */ }
  }
}
void watchStale();

for (;;) {
  try { await runCycle(); } catch (e) { log("本轮出错 " + e.stack); }
  const until = Date.now() + INTERVAL;
  while (Date.now() < until) { if (existsSync(STOPF)) { unlinkSync(STOPF); await shutdown(0); } await sleep(2000); }
}
