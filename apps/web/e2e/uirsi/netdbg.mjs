// 调试：某页打开后的请求时间线（开始 / 结束 ms）和画布行出现的时间
import { spawn } from "node:child_process";
const [, , path, wait = "6000"] = process.argv;
const PORT = 9683, CH = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const pr = spawn(CH, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${process.env.TEMP}/uirsi_dbg_${Date.now()}`, "--headless=new", "--disable-gpu", "about:blank"], { stdio: "ignore" });
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
let t;
for (let i = 0; i < 50; i++) {
  try {
    t = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page");
    if (t) break;
  } catch {}
  await sl(200);
}
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = new Map();
const send = (m, p = {}) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
await send("Runtime.enable");
await send("Page.navigate", { url: `http://127.0.0.1:5173/${path}` });
let rowAt = null;
for (let i = 0; i < +wait / 100; i++) {
  await sl(100);
  const r = await send("Runtime.evaluate", { expression: "!!document.querySelector('.v3-row')", returnByValue: true });
  if (r?.result?.value && rowAt == null) rowAt = i * 100;
}
const r = await send("Runtime.evaluate", { returnByValue: true, expression: `performance.getEntriesByType("resource").filter(e=>e.name.includes("/api/")||e.name.includes("/src/")).map(e=>[Math.round(e.startTime),Math.round(e.responseEnd),new URL(e.name).pathname.replace(/^\\/src\\//,"src:")].join(" ")).sort((a,b)=>+a.split(" ")[0]-+b.split(" ")[0]).filter((x,i)=>!x.includes("src:")||i<3)` });
console.log("rows at ~", rowAt, "ms");
for (const x of r.result.value.filter((x) => x.includes("/api/")).slice(0, 40)) console.log(x);
const nav = await send("Runtime.evaluate", { returnByValue: true, expression: `JSON.stringify(performance.getEntriesByType("navigation")[0].toJSON(), ["domContentLoadedEventEnd","loadEventEnd"])` });
console.log(nav.result.value);
ws.close();
pr.kill();
process.exit(0);
