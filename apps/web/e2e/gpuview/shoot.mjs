// GPUVIEW 截图（基于 DATAALIGN 只读探针）。DATAALIGN 原注释：只读探针：无头 Chrome（CDP :9741）打开一个页面，GET /api 带只读查看令牌（data/auth/viewer_token），
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
const [, , path = "/", outName = "probe", waitArg = "8000", clickArg = ""] = process.argv;
const jsFile = process.env.DA_JS;
const ALT = process.env.DA_ALT || "";
const ALT_PATHS = (process.env.DA_ALT_PATHS || "").split(",").filter(Boolean);
const altHits = [];
const W = +(process.env.DA_W || 1440), H = +(process.env.DA_H || 900);
let VIEWER = "";
try { VIEWER = readFileSync(join(ROOT, "data/auth/viewer_token"), "utf8").trim(); } catch { /* 无 */ }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const udir = join(process.env.TEMP || HERE, `gpuview_chrome_${Date.now()}`);
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
}
process.on("exit", killChrome);
if (!page) { console.error("chrome 没起来"); killChrome(); process.exit(2); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let mid = 0;
const pending = new Map();
const send = (method, params = {}) => { const i = ++mid; ws.send(JSON.stringify({ id: i, method, params })); return new Promise((res, rej) => pending.set(i, { res, rej })); };
const blocked = [];
// DA_MOCK=<json 文件>：{ "/api/episodes/3": "<本地 json 文件>" }——:8800 还没重启时，用进程内算好的新接口结果验证前端渲染
const MOCK = process.env.DA_MOCK ? JSON.parse(readFileSync(process.env.DA_MOCK, "utf8")) : {};
const mocked = [];
ws.onmessage = (m0) => {
  const m = JSON.parse(m0.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    const u = new URL(request.url);
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      blocked.push(`${request.method} ${u.pathname}`);
      return send("Fetch.fulfillRequest", { requestId, responseCode: 503, responseHeaders: [{ name: "content-type", value: "application/json" }], body: Buffer.from('{"detail":"（只读探针：写操作未发送）"}').toString("base64") }).catch(() => {});
    }
    if (ALT && ALT_PATHS.some((p) => u.pathname.startsWith(p))) {
      altHits.push(u.pathname);
      return fetch(ALT + u.pathname + u.search).then(async (rr) => send("Fetch.fulfillRequest", { requestId, responseCode: rr.status, responseHeaders: [{ name: "content-type", value: rr.headers.get("content-type") || "application/json" }], body: Buffer.from(await rr.arrayBuffer()).toString("base64") })).catch(() => send("Fetch.failRequest", { requestId, errorReason: "Failed" }).catch(() => {}));
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
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
// GPUVIEW：打开页面 → 依次点 CLICK 里的选择器（| 分隔，"wait:ms" 停一下）→ 截图 + 取抽屉文字。
//   用法：node apps/web/e2e/gpuview/shoot.mjs "/?theme=dark#ep01" gpu_before 6000 ".v3-gpu"
//   DA_ALT=http://127.0.0.1:8801 DA_ALT_PATHS=/api/gpu/,/api/render-tasks：这些路径改从另一个只读实例取（:8800 未重启时验证新接口）
const CLICK = (clickArg ?? "").split("|").filter(Boolean);
await send("Page.navigate", { url: BASE + path });
await sleep(+waitArg);
for (const c of CLICK) {
  if (c.startsWith("wait:")) { await sleep(+c.slice(5)); continue; }
  const r0 = await send("Runtime.evaluate", { expression: `(() => { const el = document.querySelector(${JSON.stringify(c)}); if (!el) return false; el.click(); return true; })()`, returnByValue: true });
  console.log(`click ${c}: ${r0.result?.value}`);
  await sleep(2500);
}
const JS = jsFile ? readFileSync(jsFile, "utf8") : `(() => { const d = document.querySelector('.gpu-drawer, .rt-drawer'); return { text: d ? d.innerText : null, imgs: d ? [...d.querySelectorAll('img')].map((i) => i.getAttribute('src')) : [] }; })()`;
const r = await send("Runtime.evaluate", { expression: JS, awaitPromise: true, returnByValue: true });
const out = { url: BASE + path, at: new Date().toISOString(), blocked, alt: altHits, result: r.result?.value ?? null, error: r.exceptionDetails?.exception?.description ?? null };
writeFileSync(join(HERE, `${outName}.json`), JSON.stringify(out, null, 1));
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
writeFileSync(join(HERE, `${outName}.png`), Buffer.from(shot.data, "base64"));
console.log(`ok ${outName} blocked=${blocked.length} alt=${altHits.length}${out.error ? " err=" + out.error : ""}`);
ws.close();
killChrome();
process.exit(0);
