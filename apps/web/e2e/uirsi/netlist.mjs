// 列出某页打开 6 s 内的 /api 请求（路径计数）
import { spawn } from "node:child_process";
const [,, path, wait = "6000"] = process.argv;
const PORT = 9682, CH = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const ud = `${process.env.TEMP}/uirsi_net_${Date.now()}`;
const pr = spawn(CH, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${ud}`, "--headless=new", "--disable-gpu", "about:blank"], { stdio: "ignore" });
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
let t; for (let i = 0; i < 50; i++) { try { t = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page"); if (t) break; } catch {} await sl(200); }
const ws = new WebSocket(t.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pend = new Map(); const reqs = [];
const send = (m, p = {}) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); return; }
  if (m.method === "Fetch.requestPaused") { const u = new URL(m.params.request.url); if (u.pathname.startsWith("/api/")) reqs.push(m.params.request.method + " " + u.pathname.replace(/ep\d\d-S\d+/, "<shot>")); return send(m.params.request.method === "GET" ? "Fetch.continueRequest" : "Fetch.failRequest", m.params.request.method === "GET" ? { requestId: m.params.requestId } : { requestId: m.params.requestId, errorReason: "BlockedByClient" }); } };
await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: `http://127.0.0.1:5173/${path}` });
await sl(+wait);
const dom = await send("Runtime.evaluate", { expression: "[location.hash, !!document.querySelector('.v3-row'), !!document.querySelector('.ns-page'), performance.getEntriesByType('resource').filter(e=>/api\/shots\/[^/]+$/.test(e.name)).map(e=>Math.round(e.startTime)).slice(0,3)].join(' | ')", returnByValue: true }); console.log(dom.result.value);
const c = {}; for (const r of reqs) c[r] = (c[r] ?? 0) + 1;
console.log(reqs.length, JSON.stringify(Object.entries(c).sort((a, b) => b[1] - a[1]), null, 0));
ws.close(); pr.kill(); process.exit(0);
