// UIMASTER 点击爬虫（只读）。每次改前端后必跑：node apps/web/e2e/uimaster/crawl.mjs --iter=N
// 自起无头 Chrome（CDP :9721）；GET /api 带只读查看令牌 data/auth/viewer_token；
// 所有非 GET 请求：记录请求体、对照后端 openapi.json 静态核对“会不会被接受”，然后拦下（不发到 :8800，不生成 / 不删除 / 不导入）。
// 每个页面：加载检查（vite 报错层 / 白屏 / 控制台 / 接口错误 / 慢接口）→ UIPIXEL check.js（对齐、间距、裁切、溢出、文案）
//   → 真实滚轮滚到底 + UIAUDIT scroll.js → 逐个点击每一个可点元素，记录：URL / DOM / 网络变化、无反应、弹框能否关、焦点陷阱、
//   布局跳动、被遮挡、原生 confirm/alert、新开标签、文件选择框。
// 参数：--iter=N（必填）--pages=id,id（默认全部）--cfg=1440x900:dark,...（点击用的尺寸主题；默认按 N 轮换）
//       --scan=all（另外在 6 种尺寸×主题下做加载+像素+滚动检查，不点）--max=80（每页最多点几个）--state=offline（GET /api 全部断网）
// 产物：docs/uimaster/log/iter_NNN.md、docs/uimaster/runs/iter_NNN.json、docs/uimaster/issues.json（去重合并）、docs/uimaster/shots/iterNNN/*.jpg
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "../../../..");
const DOCS = join(ROOT, "docs/uimaster");
let PORT = +(process.env.UIM_PORT || 9721);
// 端口被残留的 Chrome 占着就往后找一个空的（别的爬虫 / 上次没关干净）
for (let i = 0; i < 20; i++) { try { await fetch(`http://127.0.0.1:${PORT}/json/version`, { signal: AbortSignal.timeout(800) }); PORT++; } catch { break; } }
// 爬哪个前端：默认开发服务器（稳定通道上线后是 :5174）；UIM_BASE=http://127.0.0.1:5173 = 爬“项目方看到的稳定版”
const BASE = process.env.UIM_BASE || "http://127.0.0.1:5173";
const API = "http://127.0.0.1:8800";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const args = process.argv.slice(2);
const opt = (k, d) => args.find((a) => a.startsWith(`--${k}=`))?.split("=").slice(1).join("=") ?? d;
const ITER = +opt("iter", "0");
if (!ITER) { console.error("需要 --iter=N"); process.exit(2); }
const NNN = String(ITER).padStart(3, "0");
const MAXCLICK = +opt("max", "80");
const STATE = opt("state", "normal");
const FOCUS = opt("focus") ? new RegExp(opt("focus")) : null; // 只点 key 匹配的元素（排查用）
const NOSCROLL = args.includes("--noscroll");
const ALLCFG = ["1280x720:dark", "1440x900:light", "1920x1080:dark", "1280x720:light", "1440x900:dark", "1920x1080:light"];
const CLICKCFG = (opt("cfg") ?? ALLCFG[(ITER - 1) % ALLCFG.length]).split(",").map((c) => { const [s, t] = c.split(":"); const [w, h] = s.split("x").map(Number); return { w, h, theme: t || "dark", tag: `${w}x${h}:${t || "dark"}` }; });
const SCANCFG = opt("scan") === "all" ? ALLCFG.map((c) => { const [s, t] = c.split(":"); const [w, h] = s.split("x").map(Number); return { w, h, theme: t, tag: c }; }) : [];

// 页面清单（新增页面在这里加一行）
const PAGES = [
  { id: "shell", title: "顶栏（全站共用）", path: "/#/trash" },
  { id: "canvas", title: "画布·审片", path: "/#ep02", wait: 8000, zoomSel: ".v3-look-img img" },
  { id: "canvas_ep01", title: "画布·第 1 集（有视频）", path: "/#ep01", wait: 8000 },
  { id: "canvas_edit_ep01", title: "画布·精修（第 1 集，有首帧）", path: "/?mode=edit#ep01-S1", wait: 8000 },
  { id: "canvas_edit", title: "画布·精修", path: "/?mode=edit#ep02-S1", wait: 8000 },
  { id: "script", title: "新建剧本", path: "/#/script-create" },
  { id: "script_import", title: "剧本·导入", path: "/#/script-create?tab=import" },
  { id: "script_chat", title: "写作对话", path: "/#/script-chat" },
  { id: "script_ab", title: "剧本 A/B", path: "/#/script-ab" },
  { id: "overview", title: "全剧总览", path: "/#/overview", wait: 7000 },
  { id: "assets", title: "资产中心", path: "/#/assets", wait: 6000 },
  { id: "assets_people", title: "资产·人物", path: "/#/assets?type=people", wait: 6000 },
  { id: "assets_char", title: "资产·林晚", path: "/#/assets?type=character&char=lin_wan", wait: 6000, zoomSel: ".hub-part-thumb img" },
  { id: "assets_scene", title: "资产·场景", path: "/#/assets?type=scene", wait: 6000 },
  { id: "sound", title: "声音", path: "/#/sound" },
  { id: "cut", title: "成片", path: "/#/cut" },
  { id: "models", title: "模型与 API", path: "/#/models" },
  { id: "settings", title: "项目设置", path: "/#/settings" },
  { id: "trash", title: "回收站", path: "/#/trash" },
  { id: "audit", title: "操作记录", path: "/#/audit" },
];
const ONLY = opt("pages")?.split(",");
const pages = ONLY ? PAGES.filter((p) => ONLY.includes(p.id)) : PAGES;

const PIXEL = readFileSync(join(ROOT, "apps/web/e2e/uipixel/check.js"), "utf8");
const SCROLL = readFileSync(join(ROOT, "apps/web/e2e/uiaudit/scroll.js"), "utf8");
let VIEWER = "";
try { VIEWER = readFileSync(join(ROOT, "data/auth/viewer_token"), "utf8").trim(); } catch { /* 无登录 */ }
let OPENAPI = null;
try { OPENAPI = await (await fetch(`${API}/openapi.json`, { signal: AbortSignal.timeout(15000) })).json(); } catch { /* 后端不在 */ }

const SHOTDIR = join(DOCS, "shots", `iter${NNN}`);
mkdirSync(SHOTDIR, { recursive: true });
mkdirSync(join(DOCS, "log"), { recursive: true });
mkdirSync(join(DOCS, "runs"), { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 请求体静态核对（对照 openapi）
function matchOp(method, path) {
  if (!OPENAPI) return { op: null, why: "后端 openapi 不可用" };
  for (const [tpl, ops] of Object.entries(OPENAPI.paths)) {
    const re = new RegExp("^" + tpl.replace(/[.+*?^$()[\]|\\]/g, "\\$&").replace(/\\\{[^}]+\\\}|\{[^}]+\}/g, "[^/]+") + "$");
    if (re.test(path)) { const op = ops[method.toLowerCase()]; return op ? { op, tpl } : { op: null, why: `接口 ${tpl} 不支持 ${method}` }; }
  }
  return { op: null, why: "后端没有这个接口（会 404）" };
}
const deref = (s) => { let n = 0; while (s && s.$ref && n++ < 10) s = s.$ref.split("/").slice(1).reduce((o, k) => o?.[k], OPENAPI); return s; };
function checkBody(method, url, postData, ctype) {
  const u = new URL(url);
  if (!u.pathname.startsWith("/api/")) return null;
  const { op, why, tpl } = matchOp(method, u.pathname);
  if (!op) return { ok: false, why };
  const rb = op.requestBody;
  if (!rb) return { ok: true, tpl };
  const sch = deref(rb.content?.["application/json"]?.schema);
  if (!sch) return { ok: true, tpl, note: "非 JSON 请求体" };
  if (!postData) return rb.required ? { ok: false, tpl, why: "缺请求体" } : { ok: true, tpl };
  if (ctype && !/json/.test(ctype)) return { ok: true, tpl, note: ctype };
  let body;
  try { body = JSON.parse(postData); } catch { return { ok: false, tpl, why: "请求体不是合法 JSON" }; }
  const props = sch.properties ?? {};
  const miss = (sch.required ?? []).filter((k) => body?.[k] === undefined);
  if (miss.length) return { ok: false, tpl, why: `缺必填字段 ${miss.join(",")}` };
  const bad = [];
  for (const [k, v] of Object.entries(body ?? {})) {
    const ps = deref(props[k]);
    if (!ps) continue;
    const types = (ps.anyOf ?? [ps]).map((x) => deref(x)?.type).filter(Boolean);
    if (!types.length) continue;
    const jt = v === null ? "null" : Array.isArray(v) ? "array" : typeof v === "number" ? (Number.isInteger(v) ? "integer" : "number") : typeof v;
    if (!types.includes(jt) && !(jt === "integer" && types.includes("number"))) bad.push(`${k}:${jt}≠${types.join("|")}`);
  }
  if (bad.length) return { ok: false, tpl, why: `字段类型不对 ${bad.join(" ")}` };
  return { ok: true, tpl };
}

// ---------------------------------------------------------------- Chrome / CDP
const udir = join(process.env.TEMP || HERE, `uimaster_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
// 被 timeout / Ctrl+C 杀掉时也把自己起的 Chrome 关掉（否则残留占端口、占内存）
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => { try { proc.kill(); } catch { /* */ } process.exit(130); });
process.on("exit", () => { try { proc.kill(); } catch { /* */ } });
async function pageWs() {
  for (let i = 0; i < 160; i++) {
    try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); const p = l.find((x) => x.type === "page"); if (p) return p; } catch { /* 等 */ }
    await sleep(250);
  }
  throw new Error("chrome 没起来");
}
const PAGE = await pageWs();
const ws = new WebSocket(PAGE.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let mid = 0;
const pending = new Map();
const send = (method, params = {}, sessionId) => {
  const i = ++mid;
  ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }));
  return new Promise((res, rej) => { pending.set(i, { res, rej }); setTimeout(() => pending.has(i) && (pending.delete(i), rej(new Error(`超时 ${method}`))), 30000); });
};
// 事件累积（每次点击前清零）
let backendDownTotal = 0;
const ev = { req: 0, blocked: [], netErr: [], slow: [], console: [], dialogs: [], newTabs: 0, chooser: 0, inflight: new Map() };
const resetEv = () => { if (ev.backendDown) backendDownTotal += ev.backendDown; ev.backendDown = 0; ev.req = 0; ev.blocked = []; ev.netErr = []; ev.slow = []; ev.console = []; ev.dialogs = []; ev.newTabs = 0; ev.chooser = 0; };
ws.onmessage = (m0) => {
  const m = JSON.parse(m0.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  const P = m.params;
  switch (m.method) {
    case "Fetch.requestPaused": {
      const { requestId, request } = P;
      const u = new URL(request.url);
      if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
        const chk = checkBody(request.method, request.url, request.postData, request.headers["Content-Type"] || request.headers["content-type"]);
        ev.blocked.push({ method: request.method, path: u.pathname + u.search, body: (request.postData || "").slice(0, 300), check: chk });
        // 记录但不发送：回 503 + 说明，界面应当给出“说明 + 一键解决”
        return send("Fetch.fulfillRequest", { requestId, responseCode: 503, responseHeaders: [{ name: "content-type", value: "application/json" }], body: Buffer.from(JSON.stringify({ detail: "（检查模式：写操作未发送）" })).toString("base64") }).catch(() => {});
      }
      if (STATE === "offline" && u.pathname.startsWith("/api/") && !u.pathname.startsWith("/api/auth/")) return send("Fetch.failRequest", { requestId, errorReason: "InternetDisconnected" }).catch(() => {});
      if (VIEWER && u.pathname.startsWith("/api/")) {
        const headers = Object.entries(request.headers).map(([name, value]) => ({ name, value }));
        headers.push({ name: "x-ns-viewer-token", value: VIEWER });
        return send("Fetch.continueRequest", { requestId, headers }).catch(() => {});
      }
      return send("Fetch.continueRequest", { requestId }).catch(() => {});
    }
    case "Network.requestWillBeSent": ev.req++; ev.inflight.set(P.requestId, { t: P.timestamp, url: P.request.url, method: P.request.method }); break;
    case "Network.responseReceived": {
      const r = P.response;
      const f = ev.inflight.get(P.requestId);
      if (r.url.includes("/api/") && (r.status === 502 || r.status === 504)) { ev.backendDown = (ev.backendDown || 0) + 1; break; }
      if (r.url.includes("/api/") && r.status >= 400 && r.status !== 503) ev.netErr.push(`${r.status} ${f?.method ?? ""} ${new URL(r.url).pathname}`);
      if (f && r.url.includes("/api/") && P.timestamp - f.t > 5) ev.slow.push(`${Math.round(P.timestamp - f.t)}s ${new URL(r.url).pathname}`);
      break;
    }
    case "Network.loadingFinished": ev.inflight.delete(P.requestId); break;
    case "Network.loadingFailed": {
      const f = ev.inflight.get(P.requestId);
      ev.inflight.delete(P.requestId);
      if (f && !P.canceled && !/BlockedByClient|InternetDisconnected/.test(P.errorText) && STATE !== "offline") ev.netErr.push(`失败 ${P.errorText} ${new URL(f.url).pathname}`);
      break;
    }
    case "Runtime.exceptionThrown": ev.console.push("异常 " + (P.exceptionDetails?.exception?.description ?? P.exceptionDetails?.text ?? "").split("\n")[0].slice(0, 200)); break;
    case "Runtime.consoleAPICalled": if (P.type === "error") ev.console.push(P.args.map((a) => a.value ?? a.description ?? "").join(" ").split("\n")[0].slice(0, 200)); break;
    case "Page.javascriptDialogOpening": if (P.type === "beforeunload") { ev.beforeunload = (ev.beforeunload || 0) + 1; send("Page.handleJavaScriptDialog", { accept: true }).catch(() => {}); break; } ev.dialogs.push(`${P.type}: ${P.message.slice(0, 80)}`); send("Page.handleJavaScriptDialog", { accept: false }).catch(() => {}); break;
    case "Page.fileChooserOpened": ev.chooser++; break;
    case "Target.targetCreated": if (P.targetInfo.type === "page" && P.targetInfo.targetId !== PAGE.id) { ev.newTabs++; send("Target.closeTarget", { targetId: P.targetInfo.targetId }).catch(() => {}); } break;
  }
};
await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Target.setDiscoverTargets", { discover: true });
await send("Page.setInterceptFileChooserDialog", { enabled: true }).catch(() => {});
await send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });

const evalJs = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description?.split("\n")[0] ?? r.exceptionDetails.text);
  return r.result.value;
};
const shot = async (name) => {
  try { const r = await send("Page.captureScreenshot", { format: "jpeg", quality: 55 }); const fn = join(SHOTDIR, name + ".jpg"); writeFileSync(fn, Buffer.from(r.data, "base64")); return `docs/uimaster/shots/iter${NNN}/${name}.jpg`; } catch { return null; }
};
const shotBuf = async () => { try { return (await send("Page.captureScreenshot", { format: "jpeg", quality: 45 })).data; } catch { return null; } };
const saveBuf = (b64, name) => { if (!b64) return null; writeFileSync(join(SHOTDIR, name + ".jpg"), Buffer.from(b64, "base64")); return `docs/uimaster/shots/iter${NNN}/${name}.jpg`; };
const key = async (k, code, vk) => { await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, windowsVirtualKeyCode: vk }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: vk }); };

// 页面健康：vite 报错层 / 白屏 / 错误边界
const HEALTH = `(() => {
  const ov = document.querySelector("vite-error-overlay");
  const root = document.getElementById("root");
  const txt = (root?.innerText || "").trim();
  const boundary = /页面出错|Something went wrong|出错了，请刷新/.test(document.body.innerText) ? (document.body.innerText.match(/(页面出错|Something went wrong|出错了)[^\\n]{0,80}/)?.[0] ?? "error") : null;
  return { overlay: ov ? (ov.shadowRoot?.querySelector(".message")?.innerText || "vite 报错").slice(0, 200) : null, white: !root || (txt.length < 4 && !root.querySelector("img,video,canvas,svg")), boundary, loading: !!document.querySelector(".boot") || (/加载中/.test(txt) && txt.length < 60), url: location.hash + location.search, href: location.href, title: document.title };
})()`;

// 枚举可点元素（返回稳定 key）
const ENUM = (scope) => `(() => {
  const SCOPE = ${JSON.stringify(scope)};
  const vis = (e) => { const r = e.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return false; const s = getComputedStyle(e); return s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05; };
  const EXPL = "button, a[href], [role=button], [role=tab], [role=menuitem], [role=option], [role=switch], [role=checkbox], [role=radio], summary, select, input[type=checkbox], input[type=radio], input[type=range], [tabindex]:not([tabindex='-1'])";
  const set = new Set([...document.querySelectorAll(EXPL)]);
  for (const e of document.querySelectorAll("div, span, li, img, td, tr, label, figure, article, section, svg")) {
    if (e.closest("svg") && e.tagName !== "svg") continue;
    const s = getComputedStyle(e);
    if (s.cursor === "pointer" && getComputedStyle(e.parentElement || document.body).cursor !== "pointer") set.add(e);
  }
  const out = []; const cnt = {};
  for (const e of set) {
    if (!vis(e)) continue;
    if (e.closest("vite-error-overlay")) continue;
    if (e.closest("details:not([open])") && !e.closest("summary")) continue; // 收起的 details 里的东西看不见（Chrome 仍给外框）
    const inTop = !!e.closest("header.v3-top");
    if (SCOPE === "shell" ? !inTop : inTop) continue; // 顶栏只在 shell 页点一次
    // 父级已是按钮 / 链接的，不重复点
    const par = e.parentElement?.closest("button, a[href], [role=button], [role=tab], [role=menuitem], summary");
    if (par && set.has(par)) continue;
    const t = (e.innerText || e.getAttribute("aria-label") || e.getAttribute("title") || e.getAttribute("alt") || e.getAttribute("placeholder") || "").replace(/\\s+/g, " ").trim().slice(0, 30);
    const cls = String(e.className?.baseVal ?? e.className ?? "").split(/\\s+/).filter((c) => c && !/^(on|active|sel|is-|has-|open)/.test(c))[0] || "";
    const norm = (e.tagName.toLowerCase() + "." + cls + "|" + t).replace(/\\d+/g, "#");
    cnt[norm] = (cnt[norm] || 0) + 1;
    if (cnt[norm] > 2) continue; // 重复行里的同类按钮只点前两个
    const k = norm + "|" + cnt[norm];
    e.setAttribute("data-uim-key", k);
    const act = e.getAttribute("aria-selected") === "true" || e.getAttribute("aria-pressed") === "true" || !!e.getAttribute("aria-current") || /(^|\s)(on|active|sel|cur|current|selected)(\s|$)/.test(String(e.className?.baseVal ?? e.className ?? ""));
    out.push({ k, t, act, tag: e.tagName.toLowerCase(), cls, dis: !!(e.disabled || e.getAttribute("aria-disabled") === "true"), title: e.getAttribute("title") || "", href: e.getAttribute("href") || "", target: e.getAttribute("target") || "" });
  }
  return out;
})()`;

// 点之前：定位、查遮挡、装计数器
const PREP = (k) => `(() => {
  const e = [...document.querySelectorAll("[data-uim-key]")].find((x) => x.getAttribute("data-uim-key") === ${JSON.stringify(k)});
  if (!e) return { gone: true };
  e.scrollIntoView({ block: "center", inline: "center" });
  const r = e.getBoundingClientRect();
  const x = Math.min(innerWidth - 2, Math.max(1, r.x + r.width / 2)), y = Math.min(innerHeight - 2, Math.max(1, r.y + r.height / 2));
  const hit = document.elementFromPoint(x, y);
  const covered = hit && hit !== e && !e.contains(hit) && !hit.contains(e) ? (hit.tagName.toLowerCase() + "." + String(hit.className?.baseVal ?? hit.className ?? "").split(" ")[0] + " 「" + (hit.innerText || "").trim().slice(0, 20) + "」") : null;
  window.__uimMut = 0;
  window.__uimObs?.disconnect();
  window.__uimObs = new MutationObserver((l) => { window.__uimMut += l.length; });
  window.__uimObs.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  window.__uimCls = 0;
  try { window.__uimPo?.disconnect(); window.__uimPo = new PerformanceObserver((l) => { for (const en of l.getEntries()) if (!en.hadRecentInput) window.__uimCls += en.value; }); window.__uimPo.observe({ type: "layout-shift" }); } catch {}
  const DLG = "[role=dialog], [role=alertdialog], [aria-modal=true], .ds-modal, .v3-overlay-box, .mp-lightbox, .ds-drawer, dialog[open], [role=menu], [role=listbox]";
  window.__uimDlg0 = [...document.querySelectorAll(DLG)].filter((d) => d.getBoundingClientRect().width > 2).length;
  window.__uimFocus0 = document.activeElement;
  window.__uimUrl0 = location.href;
  window.__uimChk0 = e.checked ?? null;
  window.__uimEl = e;
  // 按钮在弹出菜单 / 折叠里：菜单会随框打开而收起，关框后焦点回到菜单的开关按钮也算对（与 ds/helpers 的 focusBack 同口径）
  const wrap = e.closest(".v3-popwrap"), det = e.closest("details");
  const op = (wrap && !wrap.querySelector(":scope > button")?.contains(e) ? wrap.querySelector(":scope > button") : null) || (det && !e.matches("summary") ? det.querySelector(":scope > summary") : null);
  const openerText = op ? (op.innerText || op.getAttribute("aria-label") || op.getAttribute("title") || "").replace(/\\s+/g, " ").trim().slice(0, 30) : null;
  return { x, y, w: Math.round(r.width), h: Math.round(r.height), covered, openerText, inView: r.bottom > 0 && r.top < innerHeight };
})()`;
const POST = `(() => {
  const DLG = "[role=dialog], [role=alertdialog], [aria-modal=true], .ds-modal, .v3-overlay-box, .mp-lightbox, .ds-drawer, dialog[open], [role=menu], [role=listbox]";
  const dl = [...document.querySelectorAll(DLG)].filter((d) => d.getBoundingClientRect().width > 2);
  window.__uimObs?.disconnect();
  const e = window.__uimEl;
  return { mut: window.__uimMut, cls: +(window.__uimCls || 0).toFixed(3), dlg: dl.length, dlgNew: dl.length > window.__uimDlg0, urlChanged: location.href !== window.__uimUrl0, url: location.hash + location.search, focusMoved: document.activeElement !== window.__uimFocus0, chk: e && e.checked !== undefined && e.checked !== window.__uimChk0, toast: !!document.querySelector(".ds-toast, [role=status]:not(:empty), [role=alert]:not(:empty)") };
})()`;
// 弹框：焦点陷阱 + 能否关闭
const DLGINFO = `(() => {
  const DLG = "[role=dialog], [role=alertdialog], [aria-modal=true], .ds-modal, .v3-overlay-box, .mp-lightbox, .ds-drawer, dialog[open]";
  const dl = [...document.querySelectorAll(DLG)].filter((d) => d.getBoundingClientRect().width > 2);
  const d = dl[dl.length - 1];
  if (!d) return { none: true };
  return { modal: d.getAttribute("aria-modal") === "true" || d.matches(".ds-modal, dialog[open], .mp-lightbox"), inside: d.contains(document.activeElement), cls: String(d.className).split(" ")[0] };
})()`;
const DLGOPEN = `(() => [...document.querySelectorAll("[role=dialog], [role=alertdialog], [aria-modal=true], .ds-modal, .v3-overlay-box, .mp-lightbox, .ds-drawer, dialog[open], [role=menu], [role=listbox]")].filter((d) => d.getBoundingClientRect().width > 2).length)()`;
const CLOSEBTN = `(() => {
  const DLG = "[role=dialog], [role=alertdialog], [aria-modal=true], .ds-modal, .v3-overlay-box, .mp-lightbox, .ds-drawer, dialog[open], [role=menu], [role=listbox]";
  const dl = [...document.querySelectorAll(DLG)].filter((d) => d.getBoundingClientRect().width > 2);
  const d = dl[dl.length - 1];
  if (!d) return null;
  const b = [...d.querySelectorAll("button, [role=button], a")].find((b) => /^(×|✕|✖|关闭|取消|收起|返回|完成|知道了|算了|不了|关闭 Esc|退出 Esc)$/.test((b.innerText || b.getAttribute("aria-label") || b.title || "").trim()) || /关闭|close/i.test(b.getAttribute("aria-label") || b.title || ""));
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
})()`;

const OVERSIG = `(() => [...document.querySelectorAll("body *")].filter((e) => { const s = getComputedStyle(e); if (!/(fixed|absolute)/.test(s.position) || s.display === "none" || s.visibility === "hidden") return false; const r = e.getBoundingClientRect(); return r.width > innerWidth * 0.6 && r.height > innerHeight * 0.6; }).map((e) => e.tagName + "." + String(e.className?.baseVal ?? e.className ?? "").split(" ")[0]).sort().join(","))()`;
const mouseClick = async (x, y) => { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 }); };

// ---------------------------------------------------------------- 问题收集
const found = []; // {page, kind, sev, msg, target, cfg, shots}
const addIssue = (o) => found.push(o);
const logLines = [];
const L = (s) => { logLines.push(s); console.log(s); };
const clickedKeys = {}; // page -> Set(target)
const seenAll = {}; // `${page}|${cfg}` -> Set(key)（本页完整枚举到的所有可点元素；没点满上限时才算完整）
const passes = new Set();
const pxGone = new Set(); // 像素问题：同配置整页扫描时目标元素已不存在 // 正向断言：`${page}|${cfg}|click|${key}`、`|load`、`|scroll`、`|g11`、`|px|${target}`
const IFILE0 = join(DOCS, "issues.json");
const DB0 = existsSync(IFILE0) ? JSON.parse(readFileSync(IFILE0, "utf8")) : { issues: [] };
const scanned = {}; // page -> Set(cfg)

async function load(p, c) {
  await send("Emulation.setDeviceMetricsOverride", { width: c.w, height: c.h, deviceScaleFactor: 1, mobile: false });
  const [pp, hash = ""] = p.path.split("#");
  const url = `${BASE}${pp}${pp.includes("?") ? "&" : "?"}theme=${c.theme}${hash ? `#${hash}` : ""}`;
  await send("Page.navigate", { url: "about:blank" }).catch(() => {});
  await sleep(150);
  resetEv();
  const t0 = Date.now();
  await send("Page.navigate", { url }).catch(() => {});
  // 确认真的到了目标页（偶发：上一页还在卸载时，这次导航被吞掉，停在 about:blank → 误报白屏）
  let navOk = false;
  for (let i = 0; i < 3; i++) {
    let ok = false;
    for (let j = 0; j < 20 && !ok; j++) { await sleep(250); ok = String(await evalJs("location.href").catch(() => "")).startsWith(BASE); }
    if (ok) { navOk = true; break; }
    L(`  （导航没生效，重试 ${p.id}）`);
    await send("Page.navigate", { url }).catch(() => {});
  }
  await sleep(1500);
  // 等启动画面 / “加载中”消失，最多 25 秒；再给页面自己的数据 p.wait
  let h = await evalJs(HEALTH).catch((e) => ({ err: String(e.message) }));
  for (let i = 0; i < 116 && (h.loading || h.err); i++) { await sleep(500); h = await evalJs(HEALTH).catch((e) => ({ err: String(e.message) })); }
  const boot = Date.now() - t0;
  // 首屏可用：启动画面消失、页面主体里出现 ≥ 8 个可点控件，且没有“加载中 / 正在读”字样
  let first = null;
  for (let i = 0; i < 60 && first == null; i++) {
    const okFirst = await evalJs(`(() => { const m = document.querySelector("main, .v3-canvas, .v3-page") || document.body; const n = m.querySelectorAll("button, a[href], [role=tab]").length; return !document.querySelector(".boot") && (n >= 8 || (m.innerText || "").trim().length > 300) && !/正在读全剧|^加载中/.test((m.innerText || "").trim().slice(0, 40)); })()`).catch(() => false);
    if (okFirst) first = Date.now() - t0; else await sleep(250);
  }
  await sleep(Math.max(1500, (p.wait ?? 4500) - boot));
  h = await evalJs(HEALTH).catch(() => h);
  return { url, h, ms: Date.now() - t0, boot, navOk, first };
}
const cfgTag = (c) => c.tag;

async function pageChecks(p, c, withScroll = true) {
  const { url, h, ms, boot, navOk, first } = await load(p, c);
  if (!navOk) { L(`- [${p.id} @ ${cfgTag(c)}] 爬虫导航失败（停在 about:blank），本页这次不算，不记白屏`); return { url, broken: true }; }
  const base0 = `${p.id}_${c.w}_${c.theme}`;
  (scanned[p.id] ??= new Set()).add(cfgTag(c));
  const base = `${p.id}_${c.w}_${c.theme}`;
  const s0 = await shot(base);
  if (h.overlay) addIssue({ page: p.id, kind: "vite_overlay", sev: 4, msg: `vite 报错层：${h.overlay.split("\n").slice(0, 4).join(" ")}`, target: "page", cfg: cfgTag(c), shots: [s0] });
  if (h.white) {
    // 白屏先等 4 秒再看一次：恢复了记“短暂白屏”（多半是别人存文件触发整页热重载），没恢复才是真白屏
    await sleep(4000);
    const h2 = await evalJs(HEALTH).catch(() => h);
    L("  白屏现场 " + JSON.stringify(h) + " → 4 秒后 white=" + h2.white);
    if (!h2.white) { addIssue({ page: p.id, kind: "white_flash", sev: 2, msg: "打开时短暂白屏（4 秒内恢复）", target: "page", cfg: cfgTag(c), shots: [s0] }); h.white = false; }
  }
  if (h.white) L("  白屏现场 " + JSON.stringify(h)), h.white && addIssue({ page: p.id, kind: "white_screen", sev: 4, msg: "白屏（#root 无内容，4 秒后仍白）", target: "page", cfg: cfgTag(c), shots: [s0] });
  if (h.boundary) addIssue({ page: p.id, kind: "error_boundary", sev: 4, msg: `页面出错：${h.boundary}`, target: "page", cfg: cfgTag(c), shots: [s0] });
  if (h.loading) addIssue({ page: p.id, kind: "stuck_loading", sev: 3, msg: `打开 ${Math.round(ms / 1000)} 秒后仍显示“加载中”`, target: "page", cfg: cfgTag(c), shots: [s0] });
  else if (boot > 8000) addIssue({ page: p.id, kind: "slow_boot", sev: 2, msg: `启动画面“加载中”停了 ${(boot / 1000).toFixed(1)} 秒`, target: "page", cfg: cfgTag(c), shots: [] });
  for (const e of new Set(ev.console)) addIssue({ page: p.id, kind: "console", sev: 2, msg: `打开页面时控制台报错：${e}`, target: "load:" + e.replace(/\d+/g, "#").slice(0, 80), cfg: cfgTag(c), shots: [s0] });
  for (const e of new Set(ev.netErr)) addIssue({ page: p.id, kind: "net", sev: 3, msg: `打开页面时接口出错：${e}`, target: "load:" + e.replace(/\d{2,}/g, "#"), cfg: cfgTag(c), shots: [s0] });
  for (const e of new Set(ev.slow)) addIssue({ page: p.id, kind: "slow", sev: 1, msg: `接口很慢：${e}`, target: "load:" + e.replace(/^\d+s /, "").replace(/\d{2,}/g, "#"), cfg: cfgTag(c), shots: [] });
  if (!h.overlay && !h.white && !h.boundary && !h.loading) passes.add(`${p.id}|${cfgTag(c)}|load`);
  let pix = null;
  try { pix = await evalJs(PIXEL); } catch (e) { L(`  像素检查失败 ${e.message}`); }
  // px_zindex 复核：先把元素滚进视口、跳过收起的 details 里的元素，再测一次 elementFromPoint（UIPIXEL 11-01 指出的两种误报）
  const zi = (pix?.issues || []).filter((i) => i.kind === "zindex");
  if (pix && zi.length) {
    const still = await evalJs(`(${JSON.stringify(zi.map((i) => i.sel))}).map((q) => { let e; try { e = document.querySelector(q); } catch { return true; } if (!e) return true; if (e.closest("details:not([open])") && !e.closest("summary")) return false; e.scrollIntoView({ block: "center" }); const r = e.getBoundingClientRect(); const h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return !(h && (h === e || e.contains(h) || h.contains(e))); })`).catch(() => zi.map(() => true));
    const drop = new Set(zi.filter((_, k) => !still[k]));
    pix.issues = pix.issues.filter((i) => !drop.has(i));
    await evalJs("(() => { scrollTo(0,0); for (const e of document.querySelectorAll('*')) if (e.scrollTop > 0) e.scrollTop = 0; })()").catch(() => {});
  }
  if (pix) {
    // 像素问题的正向断言：上次记过的元素这次还在页面上、且这次没被标
    const prevPx = DB0.issues.filter((i) => i.page === p.id && i.kind.startsWith("px_") && i.status !== "verified" && i.status !== "wontfix");
    const exist = await evalJs(`(${JSON.stringify(prevPx.map((i) => String(i.target).split("|")[0]))}).map((q) => { try { return !!document.querySelector(q); } catch { return false; } })`).catch(() => []);
    const now = new Set((pix.issues || []).filter((i) => i.sev >= 2).map((i) => i.sel + (typeof i.val === "string" && /copy|logic/.test(i.kind) ? "|" + i.val : "")));
    prevPx.forEach((i, k) => { if (exist[k] && !now.has(i.target)) passes.add(`${p.id}|${cfgTag(c)}|px|${i.target}`); });
    // 像素问题指向的元素这次整页都找不到（结构改了）：记 gone，不算 verified（文案类另有“整页找不到这串字”的正向断言）
    prevPx.forEach((i, k) => { if (!exist[k] && i.kind !== "px_copy") pxGone.add(`${p.id}|${cfgTag(c)}|px|${i.target}`); });
    // 文案类（内部词 / 路径）：同配置整页加载后，这串字在页面正文和 title 里都找不到 = 正向断言通过（元素改了结构也算）
    const copyPrev = prevPx.filter((i) => i.kind === "px_copy" && String(i.target).includes("|"));
    if (copyPrev.length) {
      const has = await evalJs(`(() => { const t = document.body.innerText + "\\n" + [...document.querySelectorAll("[title]")].map((e) => e.getAttribute("title")).join("\\n"); return ${JSON.stringify(copyPrev.map((i) => String(i.target).split("|").slice(1).join("|")))}.map((v) => t.includes(v)); })()`).catch(() => copyPrev.map(() => true));
      copyPrev.forEach((i, k) => { if (!has[k]) passes.add(`${p.id}|${cfgTag(c)}|px|${i.target}`); });
    }
  }
  pix ??= { issues: [] };
  // 补充文案检查：项目目录路径（不带扩展名的也算，例如 data/_trash、config/recipes）——界面不得出现开发细节
  const paths = await evalJs(`(() => { const re = /(?:^|[^\\w/])((?:data|config|assets|knowledge|services|tools|apps|docs)\\/[\\w.\\-/]+)/; const out = []; const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); for (let n = tw.nextNode(); n; n = tw.nextNode()) { const e = n.parentElement; if (!e || e.closest("textarea, code, pre, details:not([open]), [data-uipx-skip], .zl-box") || !e.getClientRects().length) continue; const m = n.textContent.match(re); if (m && !out.includes(m[1])) out.push(m[1]); } return out.slice(0, 20); })()`).catch(() => []);
  for (const v of paths) (pix.issues ||= []).push({ kind: "copy", sev: 3, msg: `界面直接显示项目路径「${v}」`, val: v, sel: "body", text: v, rect: [0, 0, 0, 0] });
  const pixIss = (pix.issues || []).filter((i) => i.sev >= 2);
  for (const i of pixIss) addIssue({ page: p.id, kind: "px_" + i.kind, sev: i.sev, msg: `${i.msg}（${i.text || i.sel.split(" > ").pop()}）`, target: i.sel + (typeof i.val === "string" && /copy|logic/.test(i.kind) ? "|" + i.val : ""), cfg: cfgTag(c), shots: [s0], rect: i.rect });
  if (h.overlay || h.white) { L(`- [${p.id} @ ${cfgTag(c)}] ${h.overlay ? "vite 报错层" : "白屏"}，本页其余检查跳过（避免把报错层盖住的东西逐个记成问题）`); return { url, broken: true }; }
  if (opt("wheelat")) {
    // 排查用：在指定元素上用真实滚轮滚 30 下，报告每个滚动容器停在哪（能不能滚到底、滚轮被谁吃掉）
    for (const q of opt("wheelat").split("||")) {
      const pt = await evalJs(`(() => { const e = document.querySelector(${JSON.stringify(q)}); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: Math.min(innerHeight - 20, r.y + Math.min(r.height / 2, 40)) }; })()`).catch(() => null);
      if (!pt) { L(`  WHEEL ${q}：找不到`); continue; }
      for (let i = 0; i < 30; i++) { await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: pt.x, y: pt.y, deltaX: 0, deltaY: 300 }); await sleep(40); }
      await sleep(600);
      const st = await evalJs(`(() => [...document.querySelectorAll("*")].filter((e) => { const s = getComputedStyle(e); return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 4 && e.clientHeight > 40; }).map((e) => ({ c: e.tagName.toLowerCase() + "." + String(e.className).split(" ").slice(0, 2).join("."), top: Math.round(e.scrollTop), max: e.scrollHeight - e.clientHeight, ob: getComputedStyle(e).overscrollBehaviorY })))()`).catch(() => []);
      L(`  WHEEL ${q} @(${Math.round(pt.x)},${Math.round(pt.y)})：` + JSON.stringify(st));
    }
  }
  if (opt("eval")) { ev.blocked = []; L("  EVAL " + JSON.stringify(await evalJs(readFileSync(opt("eval"), "utf8")).catch((e) => "ERR " + e.message))); await sleep(500); for (const b of ev.blocked) L(`  拦下写请求 ${b.method} ${b.path} body=${b.body} 核对=${b.check ? (b.check.ok ? "可接受" : b.check.why) : "—"}`); }
  // G11：每张 < 160px 的小图都能看大图（悬停出放大镜 / 不可点的直接点 / Alt+点）
  const g11 = await zoomCheck(p, c, base).catch((e) => ({ err: e.message }));
  if (g11.err) L(`  G11 检查失败 ${g11.err}`);
  else if (g11.n && !g11.bad.length && /^打开/.test(g11.box || "")) passes.add(`${p.id}|${cfgTag(c)}|g11`);
  if (!g11.err && g11.n) L(`  G11 小图 ${g11.n} 张，抽查 ${g11.tested}，无放大入口 ${g11.bad.length}，大图框${g11.box ?? "未测"}`);
  let sc = null;
  if (withScroll) {
    const x = Math.round(c.w * 0.6), y = Math.round(c.h * 0.6);
    for (let i = 0; i < 25; i++) { await send("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: 600 }); await sleep(40); }
    await sleep(700);
    try { sc = await evalJs(SCROLL); } catch { /* */ }
    const s1 = await shot(base + "_bottom");
    if (sc) {
      passes.add(`${p.id}|${cfgTag(c)}|scroll`);
      if (!sc.lastInView && sc.notBottom.length) addIssue({ page: p.id, kind: "scroll_reach", sev: 3, msg: `滚轮滚不到底：${sc.notBottom.join("；")}`, target: "scroll", cfg: cfgTag(c), shots: [s1] });
      if (sc.nested > 0) addIssue({ page: p.id, kind: "scroll_nested", sev: 2, msg: `嵌套滚动 ${sc.nested} 处（深度 ${sc.depth}）`, target: "scroll_nested", cfg: cfgTag(c), shots: [s1] });
      if (sc.clippedN > 0) addIssue({ page: p.id, kind: "scroll_clip", sev: 2, msg: `内容被裁又滚不出：${sc.clipped.slice(0, 3).join("；")}`, target: "scroll_clip:" + sc.clipped[0]?.split(" ")[0], cfg: cfgTag(c), shots: [s1] });
      // G4 吸顶占比：只算“此刻真贴在视口上方”的固定 / 吸顶条（scroll.js 把页面上所有 sticky 元素都加起来，
      // 多镜头标题行这类“一次只吸一个”的会被算成 N 倍，UM-0448）。贴住 = fixed，或 sticky 且 top ≤ 它的 top 值 + 所在滚动区顶 + 1
      const pinned = await evalJs(`(() => { let px = 0; const seen = []; for (const e of document.querySelectorAll("body *")) { const s = getComputedStyle(e); if (!/(fixed|sticky)/.test(s.position) || s.display === "none" || s.visibility === "hidden") continue; const r = e.getBoundingClientRect(); if (r.height < 1 || r.width < innerWidth * 0.3 || r.height > innerHeight * 0.6 || r.bottom <= 0 || r.top >= innerHeight * 0.5) continue; if (s.position === "sticky") { let sp = e.parentElement; while (sp && !/(auto|scroll)/.test(getComputedStyle(sp).overflowY)) sp = sp.parentElement; const top0 = (sp ? sp.getBoundingClientRect().top : 0) + (parseFloat(s.top) || 0); if (r.top > top0 + 1) continue; } if (seen.some((x) => x.contains(e) || e.contains(x))) continue; seen.push(e); px += r.height; } return Math.round((px / innerHeight) * 100); })()`).catch(() => sc.stickyCoverPct);
      if (pinned > 15) addIssue({ page: p.id, kind: "sticky", sev: 2, msg: `吸顶 / 固定条此刻占视口 ${pinned}%（>15%）`, target: "sticky", cfg: cfgTag(c), shots: [s1] });
    }
  }
  L(`- [${p.id} @ ${cfgTag(c)}] 加载 ${(ms / 1000).toFixed(1)}s（启动 ${(boot / 1000).toFixed(1)}s，首屏可用 ${first == null ? "超时" : (first / 1000).toFixed(1) + "s"}），报错层=${!!h.overlay} 白屏=${!!h.white}，控制台 ${ev.console.length}，接口错 ${ev.netErr.length}，像素问题 ${pixIss.length}（sev≥2），可点 ${pix.clickables ?? "?"}${sc ? `，滚动 到底=${sc.lastInView} 嵌套=${sc.nested}` : ""}`);
  return { url };
}


const SMALLIMGS = `(() => {
  const out = [];
  for (const img of document.querySelectorAll("img")) {
    if (img.closest("[data-nozoom], .zl-box, .mp-lightbox")) continue;
    const r = img.getBoundingClientRect();
    // 缩略图口径（与 ZoomLayer.isSmallImg 一致）：短边 16–160、长边 < 400（竖版首帧格也算）
    if (Math.min(r.width, r.height) < 16 || Math.min(r.width, r.height) >= 160 || Math.max(r.width, r.height) >= 400) continue;
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const k = "g11-" + out.length; img.setAttribute("data-uim-img", k);
    out.push({ k, x: r.x + r.width / 2, y: r.y + r.height / 2, src: (img.currentSrc || img.src).slice(-80), lab: (img.alt || img.closest("[title]")?.title || img.parentElement?.innerText || "").trim().slice(0, 30) });
  }
  return out;
})()`;
async function zoomCheck(p, c, base) {
  const imgs = await evalJs(SMALLIMGS);
  const res = { n: imgs.length, tested: 0, bad: [], box: null };
  const step = Math.max(1, Math.floor(imgs.length / 30));
  for (let i = 0; i < imgs.length && res.tested < 30; i += step) {
    let im = imgs[i];
    res.tested++;
    // 先把图滚进视口中间（在滚动区里、被底部胶片条挡着的图，用户会先滚过去再看）
    const pos = await evalJs(`(() => { const e = document.querySelector('[data-uim-img="${im.k}"]'); if (!e) return null; e.scrollIntoView({ block: "center", inline: "center" }); const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`).catch(() => null);
    if (pos) { im = { ...im, ...pos }; await sleep(150); }
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: 2 });
    await sleep(60);
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: im.x, y: im.y });
    await sleep(250);
    const ok = await evalJs(`(() => { const m = document.querySelector(".zl-mag"); const img = document.querySelector('[data-uim-img="${im.k}"]'); return !!m || (img && img.tabIndex === 0); })()`).catch(() => false);
    if (!ok) { res.bad.push(im); addIssue({ page: p.id, kind: "g11_nozoom", sev: 3, msg: `小图没有放大入口（${im.lab || im.src}）`, target: "g11:" + (im.lab || im.src).replace(/\d+/g, "#").slice(0, 40), cfg: cfgTag(c), shots: [] }); }
  }
  // 抽一张：Alt+点 → 大图框应打开且是原图（不是 /api/thumb），Esc 关闭。页面指定了 zoomSel 就点那一类（人物小卡 / 衣橱格）
  let im = imgs[0];
  // 前面悬停时页面滚过了：先把这张图重新滚进视口、重算坐标（否则点到别的元素上，误报 g11_nobox，UM-0411 / 0509）
  if (im) {
    const pos = await evalJs(`(() => { const e = document.querySelector('[data-uim-img="${im.k}"]'); if (!e) return null; e.scrollIntoView({ block: "center", inline: "center" }); const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`).catch(() => null);
    if (pos) { im = { ...im, ...pos }; await sleep(200); }
  }
  if (opt("zoomsel")) p = { ...p, zoomSel: opt("zoomsel") };
  if (p.zoomSel) {
    const t = await evalJs(`(() => { const i = [...document.querySelectorAll(${JSON.stringify(p.zoomSel)})].find((x) => x.getBoundingClientRect().width > 15); if (!i) return null; i.scrollIntoView({ block: "center" }); const r = i.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, lab: ${JSON.stringify(p.zoomSel)} }; })()`).catch(() => null);
    if (t) { await sleep(400); im = t; } else L(`  G11 页面上找不到 ${p.zoomSel}`);
  }
  if (im) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: im.x, y: im.y });
    await sleep(300);
    if (process.env.UIM_DEBUG) L("    G11 dbg " + JSON.stringify(await evalJs(`(() => { const e = document.elementFromPoint(${im.x}, ${im.y}); const r = e?.getBoundingClientRect(); return { tag: e?.tagName, cls: String(e?.className?.baseVal ?? e?.className ?? ""), r: r && [r.x, r.y, r.width, r.height].map(Math.round), mag: !!document.querySelector(".zl-mag") }; })()`)));
    if (process.env.UIM_DEBUG) await evalJs(`window.__ct = []; new MutationObserver((l) => { for (const m of l) { for (const n of m.addedNodes) if (n.nodeType === 1 && n.matches?.(".zl-box, .zl-mag")) window.__ct.push(["+", n.className, performance.now()|0]); for (const n of m.removedNodes) if (n.nodeType === 1 && n.matches?.(".zl-box, .zl-mag")) window.__ct.push(["-", n.className, performance.now()|0]); } }).observe(document.body, { childList: true, subtree: true }); for (const t of ["pointerdown","mousedown","pointerup","click"]) document.addEventListener(t, (e) => window.__ct.push([t, e.target.tagName, e.altKey, e.defaultPrevented, performance.now()|0]), true)`);
    for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: im.x, y: im.y, button: "left", clickCount: 1, modifiers: 1 });
    await sleep(900);
    for (let i = 0; i < 16; i++) { if (await evalJs(`(() => { const i = document.querySelector(".zl-box img"); return !i || (i.complete && i.naturalWidth > 0) || i.complete; })()`).catch(() => true)) break; await sleep(250); }
    if (process.env.UIM_DEBUG) L("    G11 events " + JSON.stringify(await evalJs("window.__ct")));
    const b = await evalJs(`(() => { const b = document.querySelector(".zl-box"); if (!b) return null; const i = b.querySelector("img"); return { thumb: (i?.src || "").includes("/api/thumb"), label: b.querySelector(".zl-cap b")?.innerText, nat: i?.naturalWidth || 0, src: (i?.src || "").slice(-120) }; })()`).catch((e) => ({ err: e.message }));
    if (b?.err) { res.box = "检查脚本出错 " + b.err; }
    else if (!b) { res.box = "没打开"; addIssue({ page: p.id, kind: "g11_nobox", sev: 3, msg: `Alt+点小图没有打开大图（${im.lab || im.src}）`, target: "g11box", cfg: cfgTag(c), shots: [] }); }
    else {
      res.box = `打开（${b.label}，原图宽 ${b.nat}，${b.src}）`;
      if (!b.nat) addIssue({ page: p.id, kind: "g11_noload", sev: 3, msg: `大图框打开了但原图加载不出来（${b.src}）`, target: "g11noload", cfg: cfgTag(c), shots: [] });
      if (b.thumb) addIssue({ page: p.id, kind: "g11_thumb", sev: 2, msg: "大图框里显示的是缩略图，不是原图", target: "g11thumb", cfg: cfgTag(c), shots: [] });
      if (c.w === 1440 && c.theme === "dark") res.shot = await shot(base + "_zoom");
      await key("Escape", "Escape", 27);
      await sleep(300);
      if (await evalJs(`!!document.querySelector(".zl-box")`).catch(() => false)) addIssue({ page: p.id, kind: "g11_esc", sev: 3, msg: "大图框按 Esc 关不掉", target: "g11esc", cfg: cfgTag(c), shots: [] });
    }
  }
  return res;
}

let baseSig = "";
async function restore(p, c, url) {
  // 关掉残留弹层（包括不带 role=dialog 的全屏层，例如串播审片）：和页面刚打开时的“大块固定层”签名比
  for (let i = 0; i < 3; i++) {
    const open = (await evalJs(DLGOPEN).catch(() => 0)) > 0 || (await evalJs(OVERSIG).catch(() => baseSig)) !== baseSig;
    if (!open) break;
    await key("Escape", "Escape", 27); await sleep(350);
  }
  if ((await evalJs(OVERSIG).catch(() => baseSig)) !== baseSig) { L("    （有全屏层关不掉，整页重开）"); resetEv(); await send("Page.navigate", { url: "about:blank" }).catch(() => {}); await sleep(200); await send("Page.navigate", { url }).catch(() => {}); await sleep(p.wait ?? 4500); }
  const cur = await evalJs("location.href").catch(() => "");
  if (cur !== url) {
    const same = cur.split("#")[0] === url.split("#")[0];
    if (same) { await evalJs(`location.hash = ${JSON.stringify(url.split("#")[1] || "")}`).catch(() => {}); await sleep(900); }
    else { resetEv(); await send("Page.navigate", { url }).catch(() => {}); await sleep(p.wait ?? 4500); }
  }
  for (let i = 0; i < 30; i++) { const h = await evalJs(HEALTH).catch(() => ({ loading: true })); if (!h.loading) break; await sleep(500); }
  // 回到顶部
  await evalJs(`(() => { scrollTo(0,0); for (const e of document.querySelectorAll("*")) if (e.scrollTop > 0) e.scrollTop = 0; })()`).catch(() => {});
}

async function clickAll(p, c) {
  const { url, broken } = await pageChecks(p, c, false);
  if (broken) return;
  baseSig = await evalJs(OVERSIG).catch(() => "");
  const done = new Set();
  const ck = (clickedKeys[p.id] ??= new Set());
  let n = 0, quiet = 0, rounds = 0;
  while (n < MAXCLICK && rounds++ < MAXCLICK * 2) {
    const h = await evalJs(HEALTH).catch(() => ({}));
    if (h.overlay || h.white) { await restore(p, c, url); }
    const list = await evalJs(ENUM(p.id === "shell" ? "shell" : "page")).catch(() => []);
    const sa = (seenAll[`${p.id}|${cfgTag(c)}`] ??= new Set());
    for (const x of list) sa.add(x.k);
    let next = list.find((x) => !done.has(x.k) && (!FOCUS || FOCUS.test(x.k)));
    for (let i = 0; i < 6 && !next && n < 3; i++) { await sleep(1500); next = (await evalJs(ENUM(p.id === "shell" ? "shell" : "page")).catch(() => [])).find((x) => !done.has(x.k) && (!FOCUS || FOCUS.test(x.k))); }
    if (!next && list.length === 0) { await restore(p, c, url); await sleep(2500); next = (await evalJs(ENUM(p.id === "shell" ? "shell" : "page")).catch(() => [])).find((x) => !done.has(x.k) && (!FOCUS || FOCUS.test(x.k))); }
    if (!next) break;
    done.add(next.k);
    const tgt = `${next.tag}「${next.t || next.cls}」`;
    if (next.dis) {
      ck.add(next.k);
      if (!next.title) addIssue({ page: p.id, kind: "disabled_no_reason", sev: 1, msg: `按钮是灰的但没说为什么（${tgt}）`, target: next.k, cfg: cfgTag(c), shots: [] });
      else passes.add(`${p.id}|${cfgTag(c)}|click|${next.k}`); // 灰着但写了原因 = 正向断言通过
      continue;
    }
    const pre = await evalJs(PREP(next.k)).catch(() => ({ gone: true }));
    if (pre.gone) continue;
    n++;
    ck.add(next.k);
    const beforeImg = await shotBuf();
    if (pre.covered) {
      const s = saveBuf(beforeImg, `${p.id}_${n}_covered`);
      addIssue({ page: p.id, kind: "covered", sev: 2, msg: `${tgt} 被 ${pre.covered} 盖住，点不到`, target: next.k, cfg: cfgTag(c), shots: [s] });
    }
    resetEv();
    await mouseClick(pre.x, pre.y);
    await sleep(next.tag === "select" ? 300 : 1000);
    const post = await evalJs(POST).catch((e) => ({ err: e.message }));
    const h2 = await evalJs(HEALTH).catch(() => ({}));
    // 被检查模式拦下的写请求也算“有反应”（按钮确实发了操作，只是爬虫不让它到后端）
    let reacted = post.mut > 0 || post.urlChanged || ev.req > 0 || ev.blocked.length > 0 || post.dlgNew || post.focusMoved || post.chk || ev.newTabs || ev.chooser || ev.dialogs.length;
    const notes = [];
    if (!reacted && !next.act && next.tag !== "select" && next.tag !== "input") {
      // 第一次没反应：等页面稳定再点一次（排除爬虫恢复页面后数据还在刷新造成的误报）
      await sleep(1500);
      const pre2 = await evalJs(PREP(next.k)).catch(() => ({ gone: true }));
      if (!pre2.gone && !pre2.covered) {
        resetEv();
        await mouseClick(pre2.x, pre2.y);
        await sleep(1200);
        const p2 = await evalJs(POST).catch(() => ({}));
        const r2 = p2.mut > 0 || p2.urlChanged || ev.req > 0 || ev.blocked.length > 0 || p2.dlgNew || p2.focusMoved || p2.chk || ev.newTabs || ev.chooser || ev.dialogs.length;
        if (r2) { reacted = true; Object.assign(post, p2); notes.push("第二次才有反应"); addIssue({ page: p.id, kind: "late_reaction", sev: 1, msg: `点第一次没反应，等 1.5 秒再点才有反应（${tgt}）`, target: next.k, cfg: cfgTag(c), shots: [] }); }
      }
    }
    const flag = (kind, sev, msg) => { notes.push(kind); const s1 = saveBuf(beforeImg, `${p.id}_${n}_before`); return shot(`${p.id}_${n}_after`).then((s2) => addIssue({ page: p.id, kind, sev, msg: `${msg}（点 ${tgt}）`, target: next.k, cfg: cfgTag(c), shots: [s1, s2] })); };
    if (h2.overlay || h2.white) { await flag(h2.overlay ? "vite_overlay" : "white_screen", 4, h2.overlay ? `点击后出现 vite 报错层：${h2.overlay.split("\n")[0]}` : "点击后白屏"); L(`  ✗ ${p.id} 出现报错层 / 白屏，停止点本页`); break; }
    if (h2.boundary) await flag("error_boundary", 4, `点击后页面出错：${h2.boundary}`);
    for (const e of new Set(ev.console)) await flag("console", 2, `点击后控制台报错：${e}`);
    for (const e of new Set(ev.netErr)) await flag("net", 3, `点击后接口出错：${e}`);
    for (const d of ev.dialogs) await flag("native_dialog", 2, `用了浏览器原生弹框（${d}），应改成一键 + 撤销`);
    for (const b of ev.blocked) if (b.check && !b.check.ok) await flag("bad_request", 3, `写请求会被后端拒绝：${b.method} ${b.path} —— ${b.check.why}`);
    if (!reacted && !next.act && next.tag !== "select" && !/^(input)$/.test(next.tag)) await flag("no_reaction", 2, "点了没反应（DOM、地址、网络、焦点都没变化）");
    if (post.cls > 0.1 && !post.urlChanged) await flag("layout_shift", 1, `点击后布局跳动 CLS=${post.cls}`);
    if (post.dlgNew) {
      const info = await evalJs(DLGINFO).catch(() => ({ none: true }));
      if (!info.none && info.modal) {
        let escaped = 0;
        for (let i = 0; i < 12; i++) { await key("Tab", "Tab", 9); const ins = await evalJs(`(() => { const d = [...document.querySelectorAll("[role=dialog], [aria-modal=true], .ds-modal, dialog[open], .mp-lightbox")].filter((d) => d.getBoundingClientRect().width > 2).pop(); return !d || d.contains(document.activeElement); })()`).catch(() => true); if (!ins) escaped++; }
        if (escaped) await flag("focus_trap", 1, `弹框（${info.cls}）里按 Tab，焦点跑到弹框外面 ${escaped}/12 次`);
      }
      const d0 = await evalJs(DLGOPEN).catch(() => 0);
      await key("Escape", "Escape", 27);
      await sleep(400);
      const d1 = await evalJs(DLGOPEN).catch(() => 0);
      if (info.modal && d1 < d0) {
        // 关掉弹框后焦点应回到打开它的那个控件（同一文字 / 标题），不能掉到 body
        const fb = await evalJs(`(() => { const a = document.activeElement; if (!a || a === document.body) return "BODY"; const t = (a.innerText || a.getAttribute("aria-label") || a.getAttribute("title") || "").replace(/\\s+/g, " ").trim().slice(0, 30); return a.getAttribute("data-uim-key") === ${JSON.stringify(next.k)} || t === ${JSON.stringify(next.t)} || t === ${JSON.stringify(pre.openerText ?? "\u0000")} ? "OK" : a.tagName + "「" + t + "」"; })()`).catch(() => "?");
        if (fb !== "OK") await flag("focus_return", 1, `弹框关掉后焦点没回到原按钮（落在 ${fb}）`);
        else passes.add(`${p.id}|${cfgTag(c)}|focusret|${next.k}`);
      }
      if (d1 >= d0 && d0 > 0) {
        const cb = await evalJs(CLOSEBTN).catch(() => null);
        if (cb) { await mouseClick(cb.x, cb.y); await sleep(400); }
        const d2 = await evalJs(DLGOPEN).catch(() => 0);
        if (d2 >= d0) await flag("dialog_stuck", 3, "弹层按 Esc 关不掉，也找不到关闭 / 取消按钮");
        else await flag("dialog_no_esc", 1, "弹层按 Esc 关不掉（只能点按钮关）");
      }
    }
    // 第二次才有反应的不算通过（late_reaction 还没修好）
    if (reacted && !notes.length && !pre.covered) passes.add(`${p.id}|${cfgTag(c)}|click|${next.k}`);
    if ((next.act || next.tag === "select" || next.tag === "input") && !notes.length && !pre.covered) passes.add(`${p.id}|${cfgTag(c)}|click|${next.k}`);
    const what = [post.urlChanged && `跳到 ${post.url}`, post.dlgNew && "开了弹层", ev.req && `${ev.req} 个请求`, ev.blocked.length && `拦下写请求 ${ev.blocked.map((b) => `${b.method} ${b.path}${b.check ? (b.check.ok ? " ✓可接受" : " ✗" + b.check.why) : ""}`).join("；")}`, post.mut && `DOM 变 ${post.mut}`, ev.chooser && "开了选文件框", ev.newTabs && "开了新标签", post.toast && "有提示条"].filter(Boolean).join("，");
    if (FOCUS) L("     " + JSON.stringify({ pre, post, html: await evalJs(`(window.__uimEl?.outerHTML||'').slice(0,300)`).catch(() => '') }));
    L(`  ${n}. ${tgt} → ${what || "无变化"}${notes.length ? `  ⚠ ${notes.join(",")}` : ""}`);
    if (!reacted) quiet++;
    await restore(p, c, url);
  }
  L(`  （${p.id} 点了 ${n} 个，其中 ${quiet} 个无反应）`);
  if (n >= MAXCLICK) delete seenAll[`${p.id}|${cfgTag(c)}`]; // 没点完，不算完整枚举
  else seenAll[`${p.id}|${cfgTag(c)}`].complete = true;
}

// ---------------------------------------------------------------- 主流程
const t0 = Date.now();
L(`# UIMASTER 第 ${ITER} 次迭代 · 爬虫日志`);
L("");
L(`- 时间：${new Date().toLocaleString("zh-CN", { hour12: false })}`);
L(`- 点击配置：${CLICKCFG.map(cfgTag).join("、")}；额外扫描：${SCANCFG.length ? SCANCFG.map(cfgTag).join("、") : "无"}；数据状态：${STATE}`);
L(`- 页面：${pages.map((p) => p.id).join("、")}`);
L("");
L("## 点击记录");
for (const p of pages) {
  for (const c of CLICKCFG) {
    try { await clickAll(p, c); } catch (e) { L(`  ✗ ${p.id} 爬取中断：${e.message}`); }
  }
}
if (SCANCFG.length) {
  L("");
  L("## 多尺寸 / 主题扫描（加载 + 像素 + 滚动）");
  for (const p of pages) for (const c of SCANCFG) { try { await pageChecks(p, c, true); } catch (e) { L(`  ✗ ${p.id}@${cfgTag(c)} ${e.message}`); } }
} else if (!NOSCROLL) {
  L("");
  L("## 滚动检查");
  for (const p of pages) for (const c of CLICKCFG) { try { await pageChecks(p, c, true); } catch (e) { L(`  ✗ ${p.id} ${e.message}`); } }
}

if (args.includes("--dry")) { for (const f of found) console.log(`ISSUE ${f.page} s${f.sev} ${f.kind} ${f.msg}`); ws.close(); proc.kill(); process.exit(0); }
// ---------------------------------------------------------------- 合并 issues.json
const IFILE = join(DOCS, "issues.json");
const db = existsSync(IFILE) ? JSON.parse(readFileSync(IFILE, "utf8")) : { next: 1, issues: [] };
const byKey = new Map(db.issues.map((i) => [i.key, i]));
const OWNER = (pg) => (/^assets/.test(pg) ? "ASSETUX" : /^(trash|audit)$/.test(pg) ? "EDITDEL" : "UIRSI");
const seenKeys = new Set();
const newIds = [], reopened = [];
for (const f of found) {
  const k = `${f.page}|${f.kind}|${f.target}`;
  seenKeys.add(k);
  let it = byKey.get(k);
  if (!it) {
    it = { id: `UM-${String(db.next++).padStart(4, "0")}`, key: k, page: f.page, kind: f.kind, sev: f.sev, msg: f.msg, target: f.target, cfgs: [], first_iter: ITER, last_seen: ITER, status: "open", owner: /^px_(spacing|align|padding|radius|vcenter|clip|overflow|ellipsis|hit|cursor|ghost)/.test(f.kind) ? "UIPIXEL" : OWNER(f.page), shots: [], history: [{ iter: ITER, ev: "found" }] };
    db.issues.push(it); byKey.set(k, it); newIds.push(it.id);
  } else {
    if (it.status === "fixed" || it.status === "verified") { reopened.push(it.id); it.history.push({ iter: ITER, ev: `reopen(${it.status})` }); it.status = "open"; }
    it.last_seen = ITER; it.msg = f.msg; it.sev = Math.max(it.sev, f.sev);
  }
  if (!it.cfgs.includes(f.cfg)) it.cfgs.push(f.cfg);
  for (const s of f.shots || []) if (s && !it.shots.includes(s)) it.shots = [...it.shots.slice(-5), s];
}
const verified = [], notSeen = [], goneIds = [];
// 只有“同一元素 / 同一检查 + 同一配置 + 正向断言”才算 verified；没再出现但没测到 ≠ 已验证（ITERATION_PROTOCOL H4）
const passKey = (it, cfg) => {
  if (it.kind.startsWith("px_")) return `${it.page}|${cfg}|px|${it.target}`;
  if (it.kind.startsWith("g11")) return `${it.page}|${cfg}|g11`;
  if (/^(scroll|sticky)/.test(it.kind)) return `${it.page}|${cfg}|scroll`;
  if (/^(vite_overlay|white_screen|error_boundary|stuck_loading|slow_boot|slow)$/.test(it.kind) || String(it.target).startsWith("load:") || it.target === "page") return `${it.page}|${cfg}|load`;
  return `${it.page}|${cfg}|click|${it.target}`;
};
for (const it of db.issues) {
  if (seenKeys.has(it.key) || ["verified", "wontfix", "gone"].includes(it.status)) continue;
  const hit = it.cfgs.find((cf) => passes.has(passKey(it, cf)));
  if (!hit) {
    // 点击类问题：同配置下整页完整枚举过，这个元素已经不存在（文字 / 结构改了）→ gone，不算 verified
    const pk = passKey(it, "");
    const gone = pk.includes("|click|") && it.status === "open" && it.cfgs.some((cf) => { const sa = seenAll[`${it.page}|${cf}`]; return sa?.complete && !sa.has(it.target); });
    if (!gone && it.kind.startsWith("px_") && it.status === "open" && it.cfgs.some((cf) => pxGone.has(`${it.page}|${cf}|px|${it.target}`))) { it.status = "gone"; it.history.push({ iter: ITER, ev: "gone（同配置整页扫描，这个元素已不存在；无法正向验证，不算已修）" }); goneIds.push(it.id); continue; }
    if (gone) { it.status = "gone"; it.history.push({ iter: ITER, ev: "gone（同配置完整枚举，这个元素已不存在；无法正向验证，不算已修）" }); goneIds.push(it.id); continue; }
    // “点了没反应 / 第二次才有反应”且负责人的修法就是“不再做成可点的样子”：同配置完整枚举确认它已不可点 = 修法本身的正向断言
    const goneAsFixed = it.status === "fixed" && /^(no_reaction|late_reaction)$/.test(it.kind) && it.cfgs.some((cf) => { const sa = seenAll[`${it.page}|${cf}`]; return sa?.complete && !sa.has(it.target); });
    if (goneAsFixed) { it.history.push({ iter: ITER, ev: "verified（修法是去掉可点；同配置完整枚举确认这个控件已不再可点）" }); it.status = "verified"; it.verified_iter = ITER; verified.push(it.id); continue; }
    if (scanned[it.page]) notSeen.push(it.id);
    continue;
  }
  it.history.push({ iter: ITER, ev: `verified（${it.status === "fixed" ? "修后" : "未登记修复"}复爬：${hit} 同元素正向断言通过）` });
  it.status = "verified"; it.verified_iter = ITER; it.verified_cfg = hit; verified.push(it.id);
}
db.updated = new Date().toISOString();
writeFileSync(IFILE, JSON.stringify(db, null, 1));

// 本次统计
const cnt = (arr) => arr.reduce((m, x) => ((m[x] = (m[x] || 0) + 1), m), {});
const openNow = db.issues.filter((i) => i.status === "open");
const perPage = cnt(openNow.map((i) => i.page));
const runIds = [...new Set(found.map((f) => byKey.get(`${f.page}|${f.kind}|${f.target}`).id))];
L("");
L("## 本次发现");
L(`- 命中问题 ${runIds.length} 个（新 ${newIds.length}，复发 ${reopened.length}），正向断言确认 ${verified.length} 个`);
L(`- 全部未解决：${openNow.length}；各页：${Object.entries(perPage).map(([k, v]) => `${k} ${v}`).join("、") || "无"}`);
L(`- 新问题：${newIds.join(" ") || "无"}`);
L(`- 复发：${reopened.join(" ") || "无"}`);
L(`- 正向断言确认已修（verified）：${verified.join(" ") || "无"}`);
L(`- 本次没再出现但没有同配置正向断言（不算 verified）：${notSeen.length} 个`);
L(`- 元素已不存在（gone，不算 verified）：${goneIds.join(" ") || "无"}`);
L("");
L("| 编号 | 页 | 严重度 | 类型 | 说明 |");
L("|---|---|---|---|---|");
for (const id of runIds.slice(0, 200)) { const it = db.issues.find((i) => i.id === id); L(`| ${id} | ${it.page} | ${it.sev} | ${it.kind} | ${it.msg.replace(/\|/g, "／").slice(0, 160)} |`); }
L("");
if (backendDownTotal) L(`- 期间后端 :8800 不可用（502/504）共 ${backendDownTotal} 次（docs/uimaster/runs/iter_${NNN}.json）：这些时刻的结果不计入页面问题`);
L(`- 用时 ${Math.round((Date.now() - t0) / 1000)} 秒；截图目录 docs/uimaster/shots/iter${NNN}/`);
const LOGF = join(DOCS, "log", `iter_${NNN}.md`);
const prev = existsSync(LOGF) ? readFileSync(LOGF, "utf8").split("\n<!-- crawl -->")[0] : "";
writeFileSync(LOGF, (prev ? prev + "\n<!-- crawl -->\n" : "") + logLines.join("\n") + "\n");
writeFileSync(join(DOCS, "runs", `iter_${NNN}.json`), JSON.stringify({ iter: ITER, cfg: CLICKCFG.map(cfgTag), scan: SCANCFG.map(cfgTag), pages: pages.map((p) => p.id), found: runIds, new: newIds, reopened, verified, open: openNow.length, perPage }, null, 1));
ws.close();
proc.kill();
try { (await import("node:fs")).rmSync(udir, { recursive: true, force: true }); } catch { /* */ }
process.exit(0);
