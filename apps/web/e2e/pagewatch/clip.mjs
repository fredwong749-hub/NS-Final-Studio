// 在 PAGEWATCH 主标签里按选择器截一块（放大 2 倍）。用法：node clip.mjs "<css 选择器>" 输出文件名 [pad=8]
import { writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const [, , SEL, OUT, PAD = "8"] = process.argv;
const list = await (await fetch(`http://127.0.0.1:${process.env.PW_PORT || 9731}/json/list`)).json();
const MAIN = (await import("node:fs")).readFileSync(new URL("./main_target.txt", import.meta.url), "utf8").trim();
const page = list.find((x) => x.id === MAIN) || list.find((x) => x.type === "page" && x.url.includes("theme=dark")) || list.find((x) => x.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = new Map();
ws.onmessage = (m) => { const j = JSON.parse(m.data); if (pend.has(j.id)) { pend.get(j.id)(j.result); pend.delete(j.id); } };
const send = (method, params) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const r = (await send("Runtime.evaluate", { expression: `(() => { const e = document.querySelector(${JSON.stringify(SEL)}); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height }; })()`, returnByValue: true })).result.value;
if (!r) { console.log("没找到"); process.exit(1); }
const p = +PAD;
const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: Math.max(0, r.x - p), y: Math.max(0, r.y - p), width: r.w + 2 * p, height: r.h + 2 * p, scale: 2 }, captureBeyondViewport: true });
writeFileSync(join(HERE, "shots", OUT), Buffer.from(shot.data, "base64"));
console.log(`apps/web/e2e/pagewatch/shots/${OUT}`, JSON.stringify(r));
process.exit(0);
