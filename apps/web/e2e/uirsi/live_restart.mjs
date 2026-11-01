// PW-008 验收：页面开着时把后端（演示后端 :8807，临时目录、不碰生产）重启一次，不按 F5，看页面能不能自己重连、徽标是否经过“重连中”回到“实时”、数字是否更新到重启后的值。
// 用法：node live_restart.mjs <临时目录> <demo_server.py> <输出前缀>
// 前提：演示前端 :5181 已开（vite --config e2e/uirsi/vite.live-demo.config.mjs）。
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [, , TMP, SERVER, PREFIX = "liverestart"] = process.argv;
const PY = "D:/NS-Final Studio/.venv/Scripts/python.exe";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const killTree = (p) => spawn("taskkill", ["/PID", String(p.pid), "/T", "/F"], { stdio: "ignore" });
const startServer = () => spawn(PY, [SERVER, TMP], { stdio: "ignore", cwd: "D:/NS-Final Studio" });
async function waitApi() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch("http://127.0.0.1:8807/api/progress")).ok) return true;
    } catch {
      /* 还没起来 */
    }
    await sleep(500);
  }
  return false;
}

let server = startServer();
await waitApi();
const PORT = 9687;
const udir = join(process.env.TEMP || HERE, `uirsi_live_${Date.now()}`);
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
const pending = new Map();
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
  }
};
const send = (method, params = {}) => {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((res, rej) => pending.set(i, { res, rej }));
};
const evalJs = async (e) => (await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true })).result?.value;
const state = () => evalJs(`({ind: document.querySelector('.live-ind')?.textContent, first: [...document.querySelectorAll('.ns-progress .sp-lbl')].find(x=>x.textContent.startsWith('首帧'))?.textContent})`);
const shot = async (name) => writeFileSync(join(HERE, `${PREFIX}_${name}_1440_dark.png`), Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Network.setExtraHTTPHeaders", { headers: { "x-ns-viewer-token": readFileSync(join(HERE, "..", "..", "..", "..", "data", "auth", "viewer_token"), "utf8").trim() } });
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: "http://127.0.0.1:5181/?theme=dark#/script-create?run=series10_v1" });
for (let i = 0; i < 60; i++) {
  const s = await state();
  if (s?.ind === "实时" && s?.first && /\d/.test(s.first)) break;
  await sleep(500);
}
await sleep(1500);
const log = { before: await state(), timeline: [] };
await shot("before");

// —— 后端重启：杀掉 → 改临时摘要（首帧 +2，模拟重启期间有新图）→ 3 秒后重启 ——
killTree(server);
const sumF = join(TMP, "summary.json");
const sum = JSON.parse(readFileSync(sumF, "utf8"));
const ep = sum.find((e) => e.number === 1);
for (const s of ep.shots.slice(1, 3)) s.first_frame = ep.shots[0].first_frame;
writeFileSync(sumF, JSON.stringify(sum));
await sleep(3000);
server = startServer();
const t0 = Date.now();
let sawReconnect = false;
let recovered = null;
for (let i = 0; i < 90; i++) {
  await sleep(1000);
  const s = await state();
  log.timeline.push({ s: Math.round((Date.now() - t0) / 1000), ...s });
  if (s?.ind && s.ind !== "实时") sawReconnect = true;
  if (s?.ind === "实时" && s?.first && s.first !== log.before.first) {
    recovered = Math.round((Date.now() - t0) / 1000);
    break;
  }
}
await sleep(1000);
log.after = await state();
log.saw_reconnecting = sawReconnect;
log.recovered_after_s = recovered;
log.pass = recovered != null;
await shot("after");
writeFileSync(join(HERE, `${PREFIX}_log.json`), JSON.stringify(log, null, 1));
console.log(JSON.stringify({ before: log.before, after: log.after, saw_reconnecting: sawReconnect, recovered_after_s: recovered, pass: log.pass }));
ws.close();
killTree(chrome);
killTree(server);
await sleep(500);
process.exit(log.pass ? 0 : 1);
