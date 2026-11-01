// 真实鼠标点击探针（r37，由 probe.mjs 改）：无头 Chrome 打开 :5173 某页，等 waitMs，执行一段表达式，把结果打印出来（非 GET 一律拦下，不写任何东西）。
// 用法：node probe.mjs "<路径如 /#ep02>" "<JS 表达式>" [waitMs=9000] [宽x高=1440x900] [dark|light]
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [, , PATH = "/#ep01", EXPR = "document.title", WAIT = "9000", SIZE = "1440x900", THEME = "dark"] = process.argv;
const [W, H] = SIZE.split("x").map(Number);
const PORT = 9687;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const udir = join(process.env.TEMP || HERE, `uirsi_probe_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
let wsUrl;
for (let i = 0; i < 150 && !wsUrl; i++) {
  try {
    wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page")?.webSocketDebuggerUrl;
  } catch {
    /* 还没起来 */
  }
  if (!wsUrl) await sleep(200);
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const blocked = []; // 被拦下的写请求（方法 + 路径 + 请求体），最后一起打印，用来核对按钮打的是哪个接口
const pending = new Map();
ws.onmessage = async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    return;
  }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    if (request.method !== "GET" && request.method !== "HEAD") {
      blocked.push({ method: request.method, url: request.url.replace(/^https?:\/\/[^/]+/, ""), body: (request.postData ?? "").slice(0, 600) });
      send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
    }
    else send("Fetch.continueRequest", { requestId });
  }
};
const send = (method, params = {}) => {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((res, rej) => pending.set(i, { res, rej }));
};
await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setExtraHTTPHeaders", { headers: { "x-ns-viewer-token": readFileSync(join(HERE, "..", "..", "..", "..", "data", "auth", "viewer_token"), "utf8").trim() } });
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
const [p, hash] = PATH.split("#");
await send("Page.navigate", { url: `http://127.0.0.1:5173${p || "/"}?theme=${THEME}${hash ? `#${hash}` : ""}` });
// r37：真实鼠标（CDP Input.dispatchMouseEvent）。EXPR 返回 {x,y,alt?,hover?} 的点击坐标；点完 1.5 s 后执行 AFTER（第 7 个参数）
const AFTER = process.argv[7] || "document.title";
await sleep(Number(WAIT));

const pt = (await send("Runtime.evaluate", { expression: EXPR, returnByValue: true })).result?.value;
if (!pt) { console.log("NO_POINT"); process.exit(1); }
await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: pt.x, y: pt.y });
await sleep(400);
if (pt.hover) {
  const hv = (await send("Runtime.evaluate", { expression: AFTER, returnByValue: true })).result?.value;
  console.log(JSON.stringify({ hover: true, after: hv }));
} else {
  const mods = pt.alt ? 1 : 0;
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: pt.x, y: pt.y, button: "left", clickCount: 1, modifiers: mods });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: pt.x, y: pt.y, button: "left", clickCount: 1, modifiers: mods });
  await sleep(1500);
  const r = (await send("Runtime.evaluate", { expression: AFTER, returnByValue: true })).result?.value;
  console.log(JSON.stringify({ point: pt, after: r }));
}
if (blocked.length) console.log("BLOCKED " + JSON.stringify(blocked));
ws.close();
spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" });
await sleep(300);
process.exit(0);
