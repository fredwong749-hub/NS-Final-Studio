// 每 3 秒读主标签的实时徽标和最后一条事件的 boot / seq；有变化才打印一行（给 Monitor 用）。另外每 3 秒探一次 :8800。
import { readFileSync } from "node:fs";
const VT = readFileSync(new URL("../../../../data/auth/viewer_token", import.meta.url), "utf8").trim();
let prev = "";
let apiPrev = "";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (;;) {
  try {
    const l = await (await fetch("http://127.0.0.1:9731/json/list")).json();
    const MAIN = readFileSync(new URL("./main_target.txt", import.meta.url), "utf8").trim();
    const p = l.find((x) => x.id === MAIN);
    if (!p) { await sleep(3000); continue; }
    const v = await new Promise((res) => {
      const ws = new WebSocket(p.webSocketDebuggerUrl);
      ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: `(() => { const L = window.__live || []; const b = [...L].reverse().find(e => e.boot); return (document.querySelector('.live-ind')?.textContent || '?') + ' boot=' + (b ? b.boot : '-'); })()`, returnByValue: true } }));
      ws.onmessage = (m) => { const j = JSON.parse(m.data); if (j.id === 1) { ws.close(); res(j.result?.result?.value); } };
      ws.onerror = () => res("ws错误");
      setTimeout(() => res("超时"), 5000);
    });
    let api;
    try { const r = await fetch("http://127.0.0.1:8800/api/auth/me", { headers: { "x-ns-viewer-token": VT }, signal: AbortSignal.timeout(4000) }); api = "API" + r.status; } catch { api = "API不通"; }
    const t = new Date().toISOString().slice(11, 19);
    if (api !== apiPrev) { console.log(`${t} ${api}`); apiPrev = api; }
    if (v !== prev) { console.log(`${t} 页面 ${v}`); prev = v; }
  } catch (e) { if (!/fetch failed/.test(e.message)) console.log("出错 " + e.message); }
  await sleep(3000);
}
