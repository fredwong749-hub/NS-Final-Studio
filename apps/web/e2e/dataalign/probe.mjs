// DATAALIGN 只读探针：无头 Chrome（CDP :9741）打开一个页面，GET /api 带只读查看令牌（data/auth/viewer_token），
// 非 GET 一律拦下（不发到 :8800）。等页面渲染后执行一段取数 JS，把结果写成 JSON，并截一张图。
// 用法：node apps/web/e2e/dataalign/probe.mjs <url-path> <outName> [waitMs] [extractJsFile]
//   例：node apps/web/e2e/dataalign/probe.mjs "/#/script-create?run=series10_v1" script_s10 9000
// 产物：apps/web/e2e/dataalign/<outName>.png、<outName>.json（{ url, rows:[...], extra }）
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "../../../..");
const PORT = +(process.env.DA_PORT || 9741);
const BASE = process.env.DA_BASE || "http://127.0.0.1:5173";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const [, , path = "/", outName = "probe", waitArg = "8000", jsFile] = process.argv;
const W = +(process.env.DA_W || 1440), H = +(process.env.DA_H || 900);
let VIEWER = "";
try { VIEWER = readFileSync(join(ROOT, "data/auth/viewer_token"), "utf8").trim(); } catch { /* 无 */ }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const udir = join(process.env.TEMP || HERE, `dataalign_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "about:blank"], { stdio: "ignore" });
let page;
for (let i = 0; i < 80 && !page; i++) {
  try { page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page"); } catch { /* 等 */ }
  if (!page) await sleep(250);
}
// 无头 Chrome 整棵进程树一起关（Windows 上 proc.kill 只关父进程，子进程会留着）
function killChrome() {
  try { spawnSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* 已退出 */ }
  try { proc.kill(); } catch { /* 已退出 */ }
  // 兜底：按本次的 user-data-dir 找残留的 chrome 进程（Chrome 有时换了父进程，taskkill /T 够不着）
  try {
    spawnSync("powershell", ["-NoProfile", "-Command", `Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like '*${udir.split(/[\/]/).pop()}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`], { stdio: "ignore", timeout: 20000 });
  } catch { /* 无 */ }
}
process.on("exit", killChrome);
if (!page) { console.error("chrome 没起来"); killChrome(); process.exit(2); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let mid = 0;
const pending = new Map();
const send = (method, params = {}) => { const i = ++mid; ws.send(JSON.stringify({ id: i, method, params })); return new Promise((res, rej) => pending.set(i, { res, rej })); };
const blocked = [];
const net = new Map();
const netDone = [];
let t0Nav = null;
// DA_MOCK=<json 文件>：{ "/api/episodes/3": "<本地 json 文件>" }——:8800 还没重启时，用进程内算好的新接口结果验证前端渲染
const MOCK = process.env.DA_MOCK ? JSON.parse(readFileSync(process.env.DA_MOCK, "utf8")) : {};
const mocked = [];
ws.onmessage = (m0) => {
  const m = JSON.parse(m0.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Network.requestWillBeSent" && m.params.request.url.includes("/api/")) net.set(m.params.requestId, { url: new URL(m.params.request.url).pathname + new URL(m.params.request.url).search, t0: m.params.timestamp });
  if ((m.method === "Network.loadingFinished" || m.method === "Network.loadingFailed") && net.has(m.params.requestId)) {
    const x = net.get(m.params.requestId);
    netDone.push({ url: x.url, ms: Math.round((m.params.timestamp - x.t0) * 1000), at_ms: Math.round((x.t0 - (t0Nav ?? x.t0)) * 1000), failed: m.method === "Network.loadingFailed" });
    net.delete(m.params.requestId);
  }
  if (m.method === "Network.requestWillBeSent" && t0Nav == null) t0Nav = m.params.timestamp;
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    const u = new URL(request.url);
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      blocked.push(`${request.method} ${u.pathname}`);
      return send("Fetch.fulfillRequest", { requestId, responseCode: 503, responseHeaders: [{ name: "content-type", value: "application/json" }], body: Buffer.from('{"detail":"（只读探针：写操作未发送）"}').toString("base64") }).catch(() => {});
    }
    if (MOCK[u.pathname]) {
      mocked.push(u.pathname);
      return send("Fetch.fulfillRequest", { requestId, responseCode: 200, responseHeaders: [{ name: "content-type", value: "application/json" }], body: readFileSync(MOCK[u.pathname]).toString("base64") }).catch(() => {});
    }
    if (VIEWER && u.pathname.startsWith("/api/")) {
      const headers = Object.entries(request.headers).map(([name, value]) => ({ name, value }));
      headers.push({ name: "x-ns-viewer-token", value: VIEWER });
      return send("Fetch.continueRequest", { requestId, headers }).catch(() => {});
    }
    return send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
};
await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
await send("Page.navigate", { url: BASE + path });
await sleep(+waitArg);
const DEFAULT_JS = `(() => {
  const rows = [...document.querySelectorAll('[data-shot-id], .v3-row, .er-shot')].map((r) => ({
    id: r.getAttribute('data-shot-id') || r.id || '',
    text: (r.innerText || '').replace(/\\s+/g, ' ').slice(0, 600),
    imgs: [...r.querySelectorAll('img')].map((i) => i.getAttribute('src')).slice(0, 12),
  }));
  return { title: document.title, hash: location.hash, rows };
})()`;
const js = jsFile ? readFileSync(jsFile, "utf8") : DEFAULT_JS;
const r = await send("Runtime.evaluate", { expression: js, awaitPromise: true, returnByValue: true });
const out = { url: BASE + path, blocked, mocked, net: netDone.sort((a, b) => b.ms - a.ms), result: r.result?.value ?? null, error: r.exceptionDetails?.exception?.description ?? null };
writeFileSync(join(HERE, `${outName}.json`), JSON.stringify(out, null, 1));
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
writeFileSync(join(HERE, `${outName}.png`), Buffer.from(shot.data, "base64"));
console.log(`ok ${outName}: rows=${out.result?.rows?.length ?? "?"} blocked=${blocked.length}${out.error ? " err=" + out.error : ""}`);
try { await Promise.race([send("Browser.close"), sleep(3000)]); } catch { /* 已关 */ }
ws.close();
killChrome();
process.exit(0);
