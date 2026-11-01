// 在 PAGEWATCH 的主标签里执行一段 JS（同一个 Chrome，不另起）。用法：node ev.mjs "<表达式>"  或  node ev.mjs -f file.js
import { readFileSync } from "node:fs";
const PORT = +(process.env.PW_PORT || 9731);
const arg = process.argv[2] === "-f" ? readFileSync(process.argv[3], "utf8") : process.argv[2];
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const MAIN = (await import("node:fs")).readFileSync(new URL("./main_target.txt", import.meta.url), "utf8").trim();
const page = list.find((x) => x.id === MAIN) || list.find((x) => x.type === "page" && x.url.includes("script-create") && !x.url.includes("light") && x.url.includes("theme=dark")) || list.find((x) => x.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
ws.onmessage = (m) => { const j = JSON.parse(m.data); if (j.id === 1) { console.log(JSON.stringify(j.result?.result?.value ?? j.result?.exceptionDetails ?? j, null, 1)); ws.close(); process.exit(0); } };
ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: arg, awaitPromise: true, returnByValue: true } }));
setTimeout(() => process.exit(2), 20000);
