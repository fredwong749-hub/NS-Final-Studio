// 挂到主标签上（新 CDP 会话，只读）：40 s 内记录页面发出的每个 /api/render-tasks 请求的起止和耗时，同时每 2 s 读一次顶栏按钮
import { readFileSync } from "node:fs";
const MAIN = readFileSync(new URL("./main_target.txt", import.meta.url), "utf8").trim();
const ver = await (await fetch("http://127.0.0.1:9731/json/version")).json();
const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pend = new Map(); let sid; const req = new Map(); const t0 = Date.now();
const rel = () => ((Date.now() - t0) / 1000).toFixed(1);
ws.onmessage = (m) => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { pend.get(j.id)(j.result); pend.delete(j.id); return; }
  if (j.sessionId !== sid) return; const P = j.params;
  if (j.method === "Network.requestWillBeSent" && /\/api\/render-tasks/.test(P.request.url)) { req.set(P.requestId, Date.now()); console.log(`${rel()}s 发出`); }
  if ((j.method === "Network.loadingFinished" || j.method === "Network.loadingFailed") && req.has(P.requestId)) { console.log(`${rel()}s 回来 用时 ${((Date.now() - req.get(P.requestId)) / 1000).toFixed(1)}s ${j.method === "Network.loadingFailed" ? "失败" : ""}`); req.delete(P.requestId); } };
const send = (method, params = {}, s) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, ...(s ? { sessionId: s } : {}) })); });
sid = (await send("Target.attachToTarget", { targetId: MAIN, flatten: true })).sessionId;
await send("Network.enable", {}, sid);
for (let i = 0; i < 20; i++) { const v = (await send("Runtime.evaluate", { expression: "document.querySelector('.v3-queue')?.innerText.replace(/\s+/g,' ').replace('渲染任务 ','')", returnByValue: true }, sid))?.result?.value; console.log(`${rel()}s 按钮 ${v}  在途 ${req.size}`); await new Promise((r) => setTimeout(r, 2000)); }
await send("Target.detachFromTarget", { sessionId: sid });
process.exit(0);
