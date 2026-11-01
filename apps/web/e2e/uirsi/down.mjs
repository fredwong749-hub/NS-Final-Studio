// 只读探针（r35）：模拟后端连不上——所有 /api 请求在 CDP 层直接失败（ConnectionRefused），非 GET 一律拦下；
// 截图 + 打印页面可见文字，用来检查“后端连不上时界面说人话”（UXF5 R8）。
// 用法：node down.mjs "<路径如 /#ep02>" <outName> [waitMs=9000] [宽x高=1440x900] [dark|light] [mode=down|up]
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [, , PATH = "/#ep01", OUT = "down", WAIT = "9000", SIZE = "1440x900", THEME = "dark", MODE = "down"] = process.argv;
const [W, H] = SIZE.split("x").map(Number);
const PORT = 9689;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const udir = join(process.env.TEMP || HERE, `uirsi_down_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
let wsUrl;
for (let i = 0; i < 150 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page")?.webSocketDebuggerUrl; } catch { /* 还没起来 */ }
  if (!wsUrl) await sleep(200);
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
let failed = 0, blocked = 0;
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    const isApi = /\/api\//.test(request.url) || /:8800\//.test(request.url);
    if (request.method !== "GET" && request.method !== "HEAD") { blocked++; send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }); }
    else if (MODE === "down" && isApi) { failed++; send("Fetch.failRequest", { requestId, errorReason: "ConnectionRefused" }); }
    else send("Fetch.continueRequest", { requestId });
  }
};
const send = (method, params = {}) => { const i = ++id; ws.send(JSON.stringify({ id: i, method, params })); return new Promise((res, rej) => pending.set(i, { res, rej })); };
await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setExtraHTTPHeaders", { headers: { "x-ns-viewer-token": readFileSync(join(HERE, "..", "..", "..", "..", "data", "auth", "viewer_token"), "utf8").trim() } }).catch(() => {});
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
const [p, hash] = PATH.split("#");
await send("Page.navigate", { url: `http://127.0.0.1:5173${p || "/"}?theme=${THEME}${hash ? `#${hash}` : ""}` });
await sleep(Number(WAIT));
const shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(join(HERE, `${OUT}.png`), Buffer.from(shot.data, "base64"));
const r = await send("Runtime.evaluate", { expression: "document.body.innerText.slice(0,3000)", returnByValue: true });
const text = r.result?.value ?? "";
const latin = (text.match(/[A-Za-z][A-Za-z ,.'’:/-]{12,}/g) || []).filter((s) => !/^(ep|S\d|http)/i.test(s));
writeFileSync(join(HERE, `${OUT}.json`), JSON.stringify({ path: PATH, mode: MODE, failedApi: failed, blockedNonGet: blocked, englishRuns: latin, text }, null, 1));
console.log(JSON.stringify({ out: `${OUT}.png`, failedApi: failed, blocked, englishRuns: latin.slice(0, 20) }));
ws.close();
spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" });
await sleep(300);
process.exit(0);
