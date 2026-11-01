// UIPIXEL：给“某一格”拍前后对比特写（只读；拦截全部非 GET）。
// 用法：node cardshot.mjs <输出前缀> [path=/#ep01] [match=首帧,#4] [width=1440] [--job]
//   找到 .v3-frame / .v3-vid / .v3e-cell 里标签文字同时包含 match 各段的那一格，鼠标真悬停在上面（让 ✎ 改 / 🗑 出现），截这一格周围的图。
//   --job：这一格当时没有在跑的任务时，往格子里放一条和真实 JobBar 同结构的“渲染中”条（只为复现项目方截图里的叠放；截图文件名带 _simjob）。
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const SIM = process.argv.includes("--job");
const OPEN = process.argv.includes("--open"); // 点开格子底栏的 ⋯
const [prefix = "card", path = "/#ep01", match = "首帧,#4", width = "1440"] = args;
const W = +width, H = 900;
let VIEWER = "";
try { VIEWER = readFileSync(join(HERE, "../../../../data/auth/viewer_token"), "utf8").trim(); } catch { /* */ }
const busy = (p) => new Promise((res) => { const s = net.createServer().once("error", () => res(true)).once("listening", () => s.close(() => res(false))).listen(p, "127.0.0.1"); });
let PORT = 9731; while (await busy(PORT)) PORT++;
const udir = join(process.env.TEMP || HERE, `uipixel_card_${Date.now()}`); mkdirSync(udir, { recursive: true });
const proc = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const kill = () => spawn("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl; for (let i = 0; i < 200 && !wsUrl; i++) { try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page")?.webSocketDebuggerUrl; } catch { /* */ } await sleep(200); }
const ws = new WebSocket(wsUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pend = new Map();
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params; const u = new URL(request.url);
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {});
    if (VIEWER && u.pathname.startsWith("/api/")) return send("Fetch.continueRequest", { requestId, headers: [...Object.entries(request.headers).map(([name, value]) => ({ name, value })), { name: "x-ns-viewer-token", value: VIEWER }] }).catch(() => {});
    return send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
};
await send("Page.enable"); await send("Runtime.enable");
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 2, mobile: false });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result.value;
const [p, hash = ""] = path.split("#");
await send("Page.navigate", { url: `http://127.0.0.1:5173${p}?theme=dark${hash ? "#" + hash : ""}` });
for (let i = 0; i < 90; i++) { await sleep(500); if (await ev(`!!document.querySelector('.v3-frame, .v3e-cell')`)) break; }
await sleep(5000);
const want = JSON.stringify(match.split(","));
const r = await ev(`(() => { const want = ${want};
  const cells = [...document.querySelectorAll('.v3-frame, .v3-vid, .v3e-cell')];
  const c = cells.find((x) => { const t = (x.querySelector('.v3-tag, .v3e-lab, .ds-tiletop')?.innerText || '').replace(/\\s+/g, ' '); return want.every((w) => t.includes(w)); }) || cells.find((x) => x.querySelector('img'));
  if (!c) return null; c.scrollIntoView({ block: 'center' }); c.setAttribute('data-uipx-card', '1');
  const b = c.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height, tag: c.querySelector('.v3-tag, .v3e-lab')?.innerText, cls: c.className }; })()`);
if (!r) { console.log("没找到格子"); kill(); process.exit(1); }
await sleep(800);
let simulated = false;
if (SIM) simulated = await ev(`(() => { const c = document.querySelector('[data-uipx-card]'); if (c.querySelector('.jobbar')) return false;
  const job = document.createElement('div'); job.innerHTML = '<div class="jobbar running compact"><div class="jobbar-track"><i></i></div><span>渲染中 0:42</span></div>';
  const slot = c.querySelector('.ds-tilebar-job'); if (slot) { slot.appendChild(job.firstChild); slot.hidden = false; slot.style.display = ''; } else { job.className = 'v3-frame-job'; c.appendChild(job); }
  return true; })()`);
const b = await ev(`(() => { const b = document.querySelector('[data-uipx-card]').getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height }; })()`);
for (const type of ["mouseMoved"]) await send("Input.dispatchMouseEvent", { type, x: b.x + b.w / 2, y: b.y + b.h / 3 });
await sleep(600);
if (OPEN) {
  const m = await ev(`(() => { const s = document.querySelector('[data-uipx-card] .ds-tilebar-more > summary'); if (!s || !s.offsetParent) return null; const r = s.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  if (m) { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: m.x, y: m.y, button: "left", clickCount: 1 }); await sleep(500); }
  console.log("menu", JSON.stringify(m), await ev(`document.querySelector('[data-uipx-card] .ds-tilebar-more')?.open ?? null`), await ev(`location.hash`));
}
const pad = 16;
const clip = { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: Math.min(W, b.w + 2 * pad + 140), height: b.h + 2 * pad, scale: 1 };
const shot = await send("Page.captureScreenshot", { format: "png", clip });
const fn = join(HERE, `${prefix}${simulated ? "_simjob" : ""}.png`);
writeFileSync(fn, Buffer.from(shot.data, "base64"));
const info = await ev(`(() => { const c = document.querySelector('[data-uipx-card]'); return { text: c.innerText.replace(/\\s+/g, ' ').slice(0, 160), stale: !!c.querySelector('.v3-ftag.stale'), job: !!c.querySelector('.jobbar') }; })()`);
console.log(JSON.stringify({ file: fn, found: r, simulated, ...info }));
ws.close(); kill(); process.exit(0);
