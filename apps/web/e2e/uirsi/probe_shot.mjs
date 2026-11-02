// UIRSI2 r49：probe.mjs 加截图（第 6 个参数 = 输出 png 路径），其余同 probe（只读、非 GET 全拦）。原探针说明：只读探针：无头 Chrome 打开 :5173 某页，等 waitMs，执行一段表达式，把结果打印出来（非 GET 一律拦下，不写任何东西）。
// 用法：node probe.mjs "<路径如 /#ep02>" "<JS 表达式>" [waitMs=9000] [宽x高=1440x900] [dark|light]
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [, , PATH = "/#ep01", EXPR = "document.title", WAIT = "9000", SIZE = "1440x900", THEME = "dark", OUT = ""] = process.argv;
const [W, H] = SIZE.split("x").map(Number);
// V2-WALK 11-02：多个 agent 同时截图会抢同一个 9688 端口，连到别人的 Chrome 后卡死。PROBE_PORT 可以指定端口，没给就随机取一个
const PORT = Number(process.env.PROBE_PORT) || 9700 + Math.floor(Math.random() * 200);
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
// CUTEDIT 11-02：PROBE_BASE 可指向沙箱 / 测试夹具前端（默认仍是 :5173 正式页）
const BASE = process.env.PROBE_BASE || "http://127.0.0.1:5173";
await send("Page.navigate", { url: `${BASE}${p || "/"}?theme=${THEME}${hash ? `#${hash}` : ""}` });
await sleep(Number(WAIT));
const r = await send("Runtime.evaluate", { expression: EXPR, awaitPromise: true, returnByValue: true });
console.log(JSON.stringify(r.result?.value ?? r.exceptionDetails ?? null, null, 1));
if (OUT) { const shot = await send("Page.captureScreenshot", { format: "png" }); (await import("node:fs")).writeFileSync(OUT, Buffer.from(shot.data, "base64")); }
if (blocked.length) console.log("BLOCKED " + JSON.stringify(blocked));
ws.close();
spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" });
await sleep(300);
process.exit(0);
