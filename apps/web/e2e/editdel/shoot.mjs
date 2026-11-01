// EDITDEL 端到端截图：自起无头 Chrome（CDP :9701），以“查看者”身份（x-ns-viewer-token，只读）打开页面，
// 执行可选的 JS（只点开抽屉 / 弹层，不提交），截图存本目录。非 GET/HEAD 请求在 CDP Fetch 层一律拦下（不写任何东西）。
// 用法：node shoot.mjs <scenarios.json>
//   scenarios.json: [{ "name": "canvas_edit_btn", "path": "/#/...", "size": [1440, 900], "wait": 5000, "js": "…", "after": 2000 }]
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = 9701;
const BASE = "http://127.0.0.1:5173";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const TOKEN_FILE = join(HERE, "..", "..", "..", "..", "data", "auth", "viewer_token");
const token = existsSync(TOKEN_FILE) ? readFileSync(TOKEN_FILE, "utf8").trim() : "";
const scen = JSON.parse(readFileSync(process.argv[2], "utf8"));
const udir = join(process.env.TEMP || HERE, `editdel_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targetWs() {
  for (let i = 0; i < 50; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = l.find((x) => x.type === "page");
      if (p) return p.webSocketDebuggerUrl;
    } catch {
      /* 还没起来 */
    }
    await sleep(200);
  }
  throw new Error("chrome 没起来");
}

const ws = new WebSocket(await targetWs());
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
let blocked = 0;
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) {
    pending.get(d.id)(d);
    pending.delete(d.id);
  } else if (d.method === "Fetch.requestPaused") {
    const rq = d.params.request;
    if (rq.method === "GET" || rq.method === "HEAD") send("Fetch.continueRequest", { requestId: d.params.requestId });
    else {
      blocked++;
      send("Fetch.failRequest", { requestId: d.params.requestId, errorReason: "BlockedByClient" });
    }
  }
};
function send(method, params = {}) {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((r) => pending.set(i, r));
}
await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
if (token) await send("Network.setExtraHTTPHeaders", { headers: { "x-ns-viewer-token": token } });
await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
const log = [];
for (const s of scen) {
  const [w, h] = s.size ?? [1440, 900];
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: BASE + s.path });
  await sleep(s.wait ?? 5000);
  let jsOut = null;
  if (s.js) {
    const r = await Promise.race([send("Runtime.evaluate", { expression: s.js, awaitPromise: true, returnByValue: true }), sleep(20000).then(() => ({ result: { result: { value: "js timeout" } } }))]);
    jsOut = r.result?.result?.value ?? r.result?.exceptionDetails?.text ?? null;
    await sleep(s.after ?? 2500);
  }
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const f = join(HERE, `${s.name}.png`);
  writeFileSync(f, Buffer.from(shot.result.data, "base64"));
  log.push({ name: s.name, path: s.path, js: jsOut, file: f });
  console.log(s.name, JSON.stringify(jsOut));
}
writeFileSync(join(HERE, "shoot_log.json"), JSON.stringify({ at: new Date().toISOString(), blocked_writes: blocked, shots: log }, null, 1));
ws.close();
proc.kill();
process.exit(0);
