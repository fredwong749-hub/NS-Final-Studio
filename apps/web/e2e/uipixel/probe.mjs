// UIPIXEL：只读探针——打开一页、可选点几下，然后在页面里跑一段 JS 打印结果（排查布局用）。拦截全部非 GET。
// 用法：node probe.mjs <path> <宽x高> <js 文件或表达式> [--click=文字1,文字2] [--shot=文件.png]
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const HERE = dirname(fileURLToPath(import.meta.url));
const pos = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const opt = (k) => process.argv.find((a) => a.startsWith(`--${k}=`))?.slice(k.length + 3);
const [path = "/#ep02", size = "1280x720", jsArg = "document.title"] = pos;
const [W, H] = size.split("x").map(Number);
const JS = existsSync(jsArg) ? readFileSync(jsArg, "utf8") : jsArg;
let VIEWER = "";
try { VIEWER = readFileSync(join(HERE, "../../../../data/auth/viewer_token"), "utf8").trim(); } catch { /* */ }
const busy = (p) => new Promise((res) => { const s = net.createServer().once("error", () => res(true)).once("listening", () => s.close(() => res(false))).listen(p, "127.0.0.1"); });
let PORT = 9741; while (await busy(PORT)) PORT++;
const udir = join(process.env.TEMP || HERE, `uipixel_probe_${Date.now()}`); mkdirSync(udir, { recursive: true });
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
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
const ev = async (expression) => { const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }); return r.exceptionDetails ? { error: r.exceptionDetails.exception?.description?.slice(0, 300) } : r.result.value; };
const [p, hash = ""] = path.split("#");
await send("Page.navigate", { url: `http://127.0.0.1:5173${p}${p.includes("?") ? "&" : "?"}theme=${opt("theme") ?? "dark"}${hash ? "#" + hash : ""}` });
for (let i = 0; i < 90; i++) { await sleep(500); if (await ev(`!document.querySelector('.boot-load') && document.body.innerText.trim().length > 80`)) break; }
await sleep(4000);
for (const t of (opt("click") ?? "").split(",").filter(Boolean)) {
  const r = await ev(`(() => { const w = ${JSON.stringify(t)}; const ex = w.startsWith("="); const q = ex ? w.slice(1) : w;
    const c = [...document.querySelectorAll("button, a, [role=button], [role=tab], summary")].filter((e) => { const b = e.getBoundingClientRect(); return b.width > 1 && b.height > 1; })
      .filter((e) => { const x = (e.innerText || e.title || "").trim(); return ex ? x === q : x.includes(q); }).sort((a, b) => a.innerText.length - b.innerText.length)[0];
    if (!c) return null; const b = c.getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; })()`);
  if (r) { for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: r.x, y: r.y, button: "left", clickCount: 1 }); await sleep(2500); }
  else console.log("没点到", t);
}
console.log(JSON.stringify(await ev(`(async () => { ${JS.includes("return") ? JS : "return " + JS} })()`), null, 1));
if (opt("shot")) { const s = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(join(HERE, opt("shot")), Buffer.from(s.data, "base64")); }
ws.close(); kill(); process.exit(0);
