// UIAUDIT detect 工具（ua_detect：detect.mjs 副本 + MOCK_POST_RE 假成功，见第 70 行）（按 docs/uiaudit/UI_CONTRACT.md 逐对象、逐操作打勾）。
// 自起无头 Chrome（CDP :9701），CDP Fetch 层拦下全部非 GET/HEAD（不发到 :8800；绝不生成 / 删除 / 导入）。
// 用法：node detect.mjs <flows.json> <round>     例：node detect.mjs flows_r1.json r1
// flows.json: [{ id, title, path, wait?, theme?, size?, steps:[ {click:"文字"|["文字",…], within?:"css"} | {js:"…"} | {shot:"名"} | {probe:"名"} | {wait:ms} | {key:"Escape"} ] }]
// 产物：<round>_<flow>_<shot>.png、<round>_detect.json（每步结果 + 每次 probe 的控件清单 + 被拦请求 + 控制台错误）
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = +(process.env.DETECT_PORT || 0) || 9730 + Math.floor(Math.random() * 60); // 每次随机端口：上一轮的 chrome 子进程没退干净也不会抢端口
// PW-019：:5174 = vite 开发版（复核新改动）；NS_WEB=http://127.0.0.1:5173 = 稳定版（项目方看到的）。没设 NS_WEB 时先试 :5174，连不上退回 :5173（稳定通道还没切的时候开发服务器在 :5173）
let BASE = process.env.NS_WEB || "";
// 顺序（UIMASTER 11-01）：先 :5173，/src/main.tsx 返回 200（= 开发服务器）就用它；否则再试 :5174。:5174 曾被 VOICE10 的临时服务器占用（/api 转 :8812），在它上面测到的不是 :8800 的数据
if (!BASE) { for (const b of ["http://127.0.0.1:5173", "http://127.0.0.1:5174"]) { try { const r = await fetch(b + "/src/main.tsx", { signal: AbortSignal.timeout(2000) }); if (r.ok) { BASE = b; break; } } catch { /* 下一个 */ } } BASE ||= "http://127.0.0.1:5173"; }
console.log(`[detect] BASE=${BASE}`);
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const [, , flowFile, round = "r1"] = process.argv;
const flows = JSON.parse(readFileSync(flowFile, "utf8"));
const PROBE = readFileSync(join(HERE, "probe.js"), "utf8");
const SCROLL = readFileSync(join(HERE, "scroll.js"), "utf8");
let VIEWER = "";
try { VIEWER = readFileSync(join(HERE, "../../../../data/auth/viewer_token"), "utf8").trim(); } catch { /* 旧 API 无登录 */ }
const udir = join(process.env.TEMP || HERE, `uiaudit_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targetWs() {
  for (let i = 0; i < 200; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = l.find((x) => x.type === "page");
      if (p) return p.webSocketDebuggerUrl;
    } catch { /* not yet */ }
    await sleep(200);
  }
  throw new Error("chrome 没起来");
}
const ws = new WebSocket(await targetWs());
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
let blocked = [];
let errs = [];
let api404 = [];
function send(method, params = {}) {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((res, rej) => {
    pending.set(i, { res, rej });
    // 任何一步卡住 25 s 就放弃这一步（页面死循环 / 弹窗不会把整轮卡死）
    setTimeout(() => pending.has(i) && (pending.delete(i), rej(new Error(`timeout ${method}`))), 25000);
  });
}
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    return;
  }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    const u = new URL(request.url);
    if (request.method !== "GET" && request.method !== "HEAD" && request.method !== "OPTIONS") {
      const pd = request.postData ? String(request.postData) : ""; const form = /Content-Disposition: form-data/.test(pd) ? [...pd.matchAll(/name="([^"]+)"(?:; filename="([^"]+)")?\r?\n(?:Content-Type:[^\n]*\n)?\r?\n([^\r\n]*)/g)].map((m) => m[2] ? `${m[1]}=<file ${m[2]}>` : `${m[1]}=${m[3].slice(0, 120)}`).join(" & ") : null; blocked.push(`${request.method} ${u.pathname}${form ? " [form] " + form : pd ? " " + pd.slice(0, 300) : request.hasPostData ? " <body>" : ""}`);
      // UIAUDIT r38–r41：MOCK_POST_RE 命中的写请求 → 本地假装成功（200 + MOCK_BODY），请求不发到 :8800，真实数据不变；用于验证“撤销”界面流程
      if (process.env.MOCK_POST_RE && new RegExp(process.env.MOCK_POST_RE).test(u.pathname)) {
        blocked.push("MOCKED " + request.method + " " + u.pathname + " " + (request.postData || "").slice(0, 300));
        const body = Buffer.from(process.env.MOCK_BODY || '{"ok":true,"prev":null}').toString("base64");
        return send("Fetch.fulfillRequest", { requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body }).catch(() => {});
      }
      return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {});
    }
    // r20：DETECT_API_DOWN=1 → 模拟后端连不上（全部 /api 与 /files 请求 ConnectionRefused），复核“后端连不上时说人话”
    if ((process.env.DETECT_API_DOWN === "1" && (u.pathname.startsWith("/api/") || u.pathname.startsWith("/files/"))) || (process.env.DETECT_FAIL_RE && new RegExp(process.env.DETECT_FAIL_RE).test(u.pathname))) { // r22：DETECT_FAIL_RE=只让匹配的接口失败
      return send("Fetch.failRequest", { requestId, errorReason: "ConnectionRefused" }).catch(() => {});
    }
    // 登录闸门：GET 带本机只读查看令牌（role=viewer，不能以项目方身份做任何决定）
    if (VIEWER && u.pathname.startsWith("/api/")) {
      const headers = Object.entries(request.headers).map(([name, value]) => ({ name, value }));
      headers.push({ name: "x-ns-viewer-token", value: VIEWER });
      return send("Fetch.continueRequest", { requestId, headers }).catch(() => {});
    }
    return send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
  if (m.method === "Network.responseReceived") {
    const r = m.params.response;
    if (r.url.includes("/api/") && r.status >= 400) api404.push(`${r.status} ${new URL(r.url).pathname}`);
  }
  if (m.method === "Runtime.exceptionThrown") errs.push(m.params.exceptionDetails?.exception?.description?.slice(0, 200) ?? "exception");
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errs.push(m.params.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 200));
};
await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });

const evalJs = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description?.slice(0, 200) ?? r.exceptionDetails.text);
  return r.result.value;
};
// 按可见文字找最小的可点元素并点击（真实鼠标事件）
const CLICK = (texts, within) => `(() => {
  const want = ${JSON.stringify(Array.isArray(texts) ? texts : [texts])};
  const root = ${within ? `document.querySelector(${JSON.stringify(within)})` : "document"} || document;
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none"; };
  const cands = [...root.querySelectorAll("button, a, [role=button], [role=tab], [role=menuitem], summary, label, li, td, [tabindex], [class*=card], [class*=row], [class*=tile], [class*=chip], img, video")].filter(vis);
  for (const w of want) {
    const hit = cands.filter((e) => { const t = (e.innerText || e.getAttribute("aria-label") || e.getAttribute("title") || e.getAttribute("alt") || "").trim(); return w.startsWith("=") ? t === w.slice(1) : t.includes(w); })
      .sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    if (hit[0]) { hit[0].scrollIntoView({ block: "center" }); const r = hit[0].getBoundingClientRect(); return { ok: true, w, x: r.x + r.width / 2, y: r.y + r.height / 2, tag: hit[0].tagName, text: (hit[0].innerText || hit[0].title || "").trim().slice(0, 40) }; }
  }
  return { ok: false, want };
})()`;

const results = [];
for (const f of flows) {
  const [w, h] = f.size ?? [1440, 900];
  const theme = f.theme ?? "dark";
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  blocked = []; errs = []; api404 = [];
  const [p, hash = ""] = f.path.split("#");
  const url = `${BASE}${p}${p.includes("?") ? "&" : "?"}theme=${theme}${hash ? `#${hash}` : ""}`;
  await send("Page.navigate", { url: "about:blank" }).catch(() => {});
  await sleep(200);
  const t0 = Date.now();
  await send("Page.navigate", { url }).catch((e) => errs.push(String(e.message)));
  await sleep(f.wait ?? 4500);
  const rec = { id: f.id, title: f.title, path: f.path, steps: [], probes: {}, shots: [] };
  // 等页面真正出来（最多再等 45 s）：首屏加载时间单独记，>10 s 记 P1 性能问题，不再误判白屏
  const tReady = Date.now(); for (let i = 0; i < 90 && Date.now() - tReady < 45000; i++) { let ok = false; try { ok = await evalJs(`(() => { if (document.querySelector("vite-error-overlay")) return true; const r = document.getElementById("root"); if (!r) return false; const c = r.cloneNode(true); c.querySelectorAll("header, .v3-top, nav, aside.v3-rail").forEach((e) => e.remove()); const t = (c.textContent || "").replace(/\\s+/g, " ").trim(); return t.length > 300 || (t.length > 60 && !/^(momoso.{0,40})?加载中/.test(t) && !/正在读取|加载中…\\s*$/.test(t.slice(0, 200))); })()`); } catch {} if (ok) break; await sleep(500); }
  rec.loadMs = Date.now() - t0;
  // G0：vite 报错层 / 白屏（UIRSI 11-01 建议，K-UI-031）——任一命中 = P0，本流程其余结果作废
  try { rec.overlay = await evalJs(`(() => { const o = document.querySelector("vite-error-overlay"); const root = document.getElementById("root"); const blank = !root || !root.innerText.trim(); return o ? "vite-error-overlay: " + (o.shadowRoot?.querySelector(".message")?.innerText ?? "").slice(0, 160) : blank ? "白屏（#root 无内容）" : null; })()`); } catch (e) { rec.overlay = "检查失败 " + e.message; }
  let clicks = 0;
  for (const s of f.steps ?? [{ shot: "main" }, { probe: "main" }]) {
    try {
      if (s.click) {
        const r = await evalJs(CLICK(s.click, s.within));
        if (r.ok) {
          clicks++;
          for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: r.x, y: r.y, button: "left", clickCount: 1 });
          await sleep(s.after ?? 1500);
        }
        rec.steps.push({ click: s.click, ...r });
      } else if (s.key) {
        await send("Input.dispatchKeyEvent", { type: "keyDown", key: s.key, code: s.key, windowsVirtualKeyCode: s.key === "Escape" ? 27 : 0 });
        await send("Input.dispatchKeyEvent", { type: "keyUp", key: s.key, code: s.key });
        await sleep(600);
        rec.steps.push({ key: s.key });
      } else if (s.js) {
        const v = await evalJs(`(async()=>{${s.js}})()`);
        rec.steps.push({ js: s.js.slice(0, 60), value: v });
        await sleep(s.after ?? 800);
      } else if (s.wait) {
        await sleep(s.wait);
      } else if (s.shot) {
        const r = await send("Page.captureScreenshot", { format: "png" });
        const fn = `${round}_${f.id}_${s.shot}.png`;
        writeFileSync(join(HERE, fn), Buffer.from(r.data, "base64"));
        rec.shots.push(fn);
      } else if (s.tabwalk) {
        // 真实 Tab 走 n 步：每步记录焦点元素是否被吸顶 / 固定条盖住（焦点元素中心取点不是它自己）
        const res = [];
        for (let k = 0; k < (s.n ?? 30); k++) {
          await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
          await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
          await sleep(150);
          res.push(await evalJs(`(() => { const a = document.activeElement; if (!a || a === document.body) return null; const r = a.getBoundingClientRect(); if (r.width < 2) return null; const inView = r.bottom > 0 && r.top < innerHeight; const h = inView ? document.elementFromPoint(r.x + r.width / 2, Math.max(r.top + 2, Math.min(r.bottom - 2, r.top + r.height / 2))) : null; const covered = inView && h && !a.contains(h) && !h.contains(a); const by = covered ? (h.closest("[class]")?.className || h.tagName).toString().slice(0, 40) : null; return { t: (a.innerText || a.getAttribute("aria-label") || a.tagName).trim().slice(0, 12), top: Math.round(r.top), inView, covered, by }; })()`));
        }
        const hits = res.filter(Boolean);
        rec.probes[`tab_${s.tabwalk}`] = { steps: hits.length, covered: hits.filter((x) => x.covered), offscreen: hits.filter((x) => !x.inView).length };      } else if (s.scrollEach) {
        // 多栏页面：每个滚动容器在它自己的中心点各滚 25 下，再量到底没有（UIMASTER 指出单点滚动会把别的栏误报成没到底）
        const pts = await evalJs(`[...document.querySelectorAll("body *")].filter((e) => { const st = getComputedStyle(e); const r = e.getBoundingClientRect(); return /(auto|scroll)/.test(st.overflowY) && e.scrollHeight > e.clientHeight + 4 && e.clientHeight > 40 && r.width > 40 && r.bottom > 0 && r.top < innerHeight; }).map((e) => { const r = e.getBoundingClientRect(); const top = Math.max(r.top, 0), bot = Math.min(r.bottom, innerHeight); return [r.left + r.width / 2, (top + bot) / 2]; })`);
        for (const [x, y] of pts) {
          for (let i = 0; i < 25; i++) { await send("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: 600 }); await sleep(40); }
        }
        await sleep(800);
        rec.probes[`scroll_${s.scrollEach}`] = { ...(await evalJs(SCROLL)), wheeledAt: pts.length };      } else if (s.scroll) {
        // 真实滚轮：在内容区（默认 60%/60% 处）连续滚 25 下，每下 600px，然后量“到没到底”
        const x = Math.round(w * (s.x ?? 0.6)), y = Math.round(h * (s.y ?? 0.6));
        for (let i = 0; i < 25; i++) {
          await send("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: 600 });
          await sleep(60);
        }
        await sleep(800);
        rec.probes[`scroll_${s.scroll}`] = await evalJs(SCROLL);
        const r = await send("Page.captureScreenshot", { format: "png" });
        const fn = `${round}_${f.id}_scroll_${s.scroll}.png`;
        writeFileSync(join(HERE, fn), Buffer.from(r.data, "base64"));
        rec.shots.push(fn);
      } else if (s.hoverAt) {
        // r21：真实鼠标移到坐标（悬停，例如触发 ZoomLayer 放大镜），不点击
        const [x, y] = Array.isArray(s.hoverAt) ? s.hoverAt : await evalJs(s.hoverAt);
        if (x != null) { await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x - 3, y: y - 3 }); await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }); await sleep(s.after ?? 900); }
        rec.steps.push({ hoverAt: [x, y] });
      } else if (s.clickAt) {
        // 真实鼠标点坐标（JS 返回的位置），用于找不到唯一文字的小按钮
        const [x, y] = Array.isArray(s.clickAt) ? s.clickAt : await evalJs(s.clickAt);
        if (x != null) { const modifiers = s.alt ? 1 : 0; /* r22：{clickAt, alt:true} = Alt+点 */ for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1, modifiers }); await sleep(s.after ?? 1200); }
        rec.steps.push({ clickAt: [x, y] });
      } else if (s.upload) {
        // 给页面上第 N 个 file input 设文件（CDP DOM.setFileInputFiles，只读本地文件，不上传——后续 POST 照样被拦）
        const doc = await send("DOM.getDocument", { depth: -1 });
        const q = await send("DOM.querySelectorAll", { nodeId: doc.root.nodeId, selector: s.selector || "input[type=file]" });
        const nid = q.nodeIds[s.index ?? 0];
        if (nid) await send("DOM.setFileInputFiles", { nodeId: nid, files: [s.upload] });
        rec.steps.push({ upload: s.upload, found: q.nodeIds.length });
        await sleep(s.after ?? 1500);      } else if (s.typeText != null) {
        // 真实键入（CDP Input.insertText，进当前焦点元素）
        await send("Input.insertText", { text: s.typeText });
        await sleep(s.after ?? 500);
        rec.steps.push({ typeText: s.typeText });      } else if (s.tabtrap) {
        // 焦点陷阱：真实 Tab / Shift+Tab 按 n 次，每次记录焦点是否还在容器里；最后按真实 Esc，记录焦点回到了谁
        const sel = s.tabtrap;
        const out = { container: sel, open: await evalJs(`!!document.querySelector(${JSON.stringify(sel)})`), tab: [], shiftTab: [] };
        for (const [arr, mod] of [[out.tab, 0], [out.shiftTab, 8]]) {
          for (let k = 0; k < (s.n ?? 12); k++) {
            await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: mod });
            await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: mod });
            await sleep(120);
            arr.push(await evalJs(`(() => { const a = document.activeElement; const c = document.querySelector(${JSON.stringify(sel)}); return c && c.contains(a) ? 1 : 0; })()`));
          }
        }
        await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
        await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
        await sleep(600);
        out.closed = await evalJs(`!document.querySelector(${JSON.stringify(sel)})`);
        out.focusAfter = await evalJs(`(() => { const a = document.activeElement; return a ? (a.tagName + " " + (a.innerText || a.getAttribute("aria-label") || a.title || "").replace(/\\s+/g, " ").slice(0, 40)) : null; })()`);
        out.inside = { tab: out.tab.reduce((a, b) => a + b, 0) + "/" + out.tab.length, shiftTab: out.shiftTab.reduce((a, b) => a + b, 0) + "/" + out.shiftTab.length };
        rec.probes[`trap_${sel}`] = out;      } else if (s.realzoom) {
        // G11 真实鼠标复核：悬停（mouseMoved）看 .zl-mag；Alt+按下/松开（modifiers:1）看 .zl-box；等原图 complete；真实 Esc 键看关闭
        const pts = await evalJs(`[...document.querySelectorAll("img")].map((i) => { const r = i.getBoundingClientRect(); return { w: r.width, x: r.x + r.width / 2, y: r.y + r.height / 2, src: (i.currentSrc || i.src).slice(-60) }; }).filter((p) => p.w > 8 && p.w < 160 && p.y > 0 && p.y < innerHeight).slice(0, ${s.max ?? 10})`);
        const res = [];
        for (const p of pts) {
          await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: p.x, y: p.y });
          await sleep(500);
          const mag = await evalJs(`!!document.querySelector(".zl-mag")`);
          for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: p.x, y: p.y, button: "left", clickCount: 1, modifiers: 1 });
          let box = null;
          for (let k = 0; k < 16; k++) { await sleep(250); box = await evalJs(`(() => { const b = document.querySelector(".zl-box"); if (!b) return null; const im = b.querySelector("img"); return { complete: !!im?.complete, nat: im?.naturalWidth ?? 0, thumb: /\\/api\\/thumb/.test(im?.src || ""), cap: b.innerText.slice(0, 50) }; })()`); if (box && box.complete && box.nat) break; }
          await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
          await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
          await sleep(500);
          const closed = await evalJs(`!document.querySelector(".zl-box")`);
          res.push({ w: Math.round(p.w), src: p.src, mag, box: !!box, nat: box?.nat ?? 0, thumb: box?.thumb ?? null, cap: box?.cap ?? null, escClosed: closed });
        }
        rec.probes[`zoom_${s.realzoom}`] = res;      } else if (s.parity2) {
        // r19g：逐格内容断言 v2（首帧 / 尾帧 / 视频 文件 + 版号），parity2_check.mjs 判
        rec.probes[`parity2_${s.parity2}`] = await evalJs(readFileSync(join(HERE, "parity2.js"), "utf8"));
      } else if (s.parity) {
        rec.probes[`parity_${s.parity}`] = await evalJs(readFileSync(join(HERE, "parity.js"), "utf8"));
      } else if (s.collect) {
        rec.probes[`collect_${s.collect}`] = await evalJs(readFileSync(join(HERE, "regress_collect.js"), "utf8"));
      } else if (s.probe) {
        rec.probes[s.probe] = await evalJs(PROBE);
      }
    } catch (e) {
      rec.steps.push({ step: s, error: String(e.message ?? e).slice(0, 200) });
    }
  }
  rec.clicks = clicks;
  rec.ms = Date.now() - t0;
  rec.blocked = [...new Set(blocked)];
  rec.apiErrors = [...new Set(api404)];
  rec.consoleErrors = [...new Set(errs)].slice(0, 10);
  results.push(rec);
  console.log(`${rec.overlay ? "[G0 P0 " + rec.overlay + "] " : ""}${rec.loadMs > 10000 ? "[慢 " + Math.round(rec.loadMs / 1000) + "s] " : ""}${f.id}: clicks=${clicks} shots=${rec.shots.length} blocked=${rec.blocked.length} apiErr=${rec.apiErrors.length} ${rec.steps.filter((x) => x.ok === false).map((x) => "MISS:" + x.want).join(" ")}`);
}
writeFileSync(join(HERE, `${round}_detect.json`), JSON.stringify(results, null, 1));
ws.close();
try { (await import("node:child_process")).execSync(`taskkill /PID ${proc.pid} /T /F`, { stdio: "ignore" }); } catch { proc.kill(); } // 连子进程一起关（只关自己起的无头实例）
await sleep(2500);
process.exit(0);
