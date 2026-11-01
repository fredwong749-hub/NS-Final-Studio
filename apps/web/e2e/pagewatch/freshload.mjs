// 在 PAGEWATCH 的同一个 Chrome 里开一个新标签，从零加载页面，量 12 秒内的闪烁 / 布局跳动，截图后关掉（不另起 Chrome）。
// 用法：node freshload.mjs 输出前缀 [dark|light] [宽=1440]
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..", "..", "..");
const [, , PREFIX = "fresh", THEME = "dark", W = "1440"] = process.argv;
const VT = readFileSync(join(ROOT, "data", "auth", "viewer_token"), "utf8").trim();
const ver = await (await fetch("http://127.0.0.1:9731/json/version")).json();
const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = new Map();
let sid;
const blocked = [];
ws.onmessage = (m) => {
  const j = JSON.parse(m.data);
  if (j.id && pend.has(j.id)) { const p = pend.get(j.id); pend.delete(j.id); j.error ? p.rej(new Error(JSON.stringify(j.error))) : p.res(j.result); return; }
  if (j.sessionId === sid && j.method === "Fetch.requestPaused") {
    const { requestId, request } = j.params;
    const u = new URL(request.url);
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) { blocked.push(request.method + " " + u.pathname); return send("Fetch.fulfillRequest", { requestId, responseCode: 503, responseHeaders: [{ name: "content-type", value: "application/json" }], body: Buffer.from('{"detail":"PAGEWATCH 只读"}').toString("base64") }, sid); }
    if (u.pathname.startsWith("/api/") || u.pathname.startsWith("/files/")) return send("Fetch.continueRequest", { requestId, headers: [...Object.entries(request.headers).map(([name, value]) => ({ name, value })), { name: "x-ns-viewer-token", value: VT }] }, sid);
    return send("Fetch.continueRequest", { requestId }, sid);
  }
};
const send = (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) })); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { targetId } = await send("Target.createTarget", { url: "about:blank" });
sid = (await send("Target.attachToTarget", { targetId, flatten: true })).sessionId;
const s = (m, p) => send(m, p, sid);
await s("Page.enable");
await s("Runtime.enable");
await s("Network.enable");
await s("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
await s("Emulation.setDeviceMetricsOverride", { width: +W, height: 900, deviceScaleFactor: 1, mobile: false });
await s("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: THEME }] });
await s("Page.addScriptToEvaluateOnNewDocument", { source: readFileSync(join(HERE, "inject.js"), "utf8") });
await s("Page.navigate", { url: `http://localhost:5173/?theme=${THEME}#/script-create?run=series10_v1` });
await sleep(+(process.env.FL_WAIT || 12000));
const r = (await s("Runtime.evaluate", { expression: `(() => { const d = window.__pwDrain(); return { flashes: d.flashes.map(f => ({ path: f.path.split('>').slice(-2).join('>'), text: f.text.slice(0, 40), changed: f.changed })), cls: +d.shifts.filter(x => !x.input).reduce((a, x) => a + x.v, 0).toFixed(4), shifts: d.shifts.filter(x => x.v > 0.005).map(x => [x.v, ...x.src.slice(0, 3)]), prod: document.querySelector('.ns-prod')?.innerText.replace(/\\s+/g, ' ').slice(0, 400) ?? null, liveDup: (() => { const L = window.__live || []; const k = L.filter(e => e.type !== "tick").map(e => e.type + ":" + e.seq); return { n: L.length, uniq: new Set(k).size, nonTick: k.length }; })(), prodH: Math.round(document.querySelector('.ns-prod')?.getBoundingClientRect().height ?? 0) }; })()`, returnByValue: true })).result.value;
const shot = await s("Page.captureScreenshot", { format: "jpeg", quality: 65 });
writeFileSync(join(HERE, "shots", `${PREFIX}_${W}_${THEME}.jpg`), Buffer.from(shot.data, "base64"));
r.shot = `apps/web/e2e/pagewatch/shots/${PREFIX}_${W}_${THEME}.jpg`;
r.blocked = blocked;
console.log(JSON.stringify(r, null, 1));
await send("Target.closeTarget", { targetId });
process.exit(0);
