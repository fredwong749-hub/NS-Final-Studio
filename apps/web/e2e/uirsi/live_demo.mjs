// 实时刷新验收：演示前端 :5181（同一份代码，/api 走演示后端 :8807——真实扫描器只看临时目录，进度用真实算法读临时摘要副本）。
// 先截“更新前”，再改临时目录（摘要副本里给几镜补首帧 + 写 takes.json + 一条进行中的任务），连拍几帧看闪烁和进度条变化。
// 不碰生产数据。用法：node live_demo.mjs <临时目录> <页面路径> <输出前缀> <dark|light>
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, utimesSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [, , TMP, PAGE = "/#/script-create?run=series10_v1", PREFIX = "live", THEME = "dark", MODE = "four"] = process.argv;
const PORT = 9686;
const BASE = "http://127.0.0.1:5181";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const udir = join(process.env.TEMP || HERE, `uirsi_live_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.value;
const shot = async (name) => {
  const r = await send("Page.captureScreenshot", { format: "png" });
  const f = join(HERE, `${PREFIX}_${name}_1440_${THEME}.png`);
  writeFileSync(f, Buffer.from(r.data, "base64"));
  return f;
};

await send("Page.enable");
await send("Runtime.enable");
const vt = readFileSync(join(HERE, "..", "..", "..", "..", "data", "auth", "viewer_token"), "utf8").trim();
await send("Network.enable");
await send("Network.setExtraHTTPHeaders", { headers: { "x-ns-viewer-token": vt } });
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
const [p, hash] = PAGE.split("#");
await send("Page.navigate", { url: `${BASE}${p || "/"}?theme=${THEME}#${hash}` });
// 等进度条读到数据 + 实时连接连上
for (let i = 0; i < 60; i++) {
  const ok = await evalJs(`!!document.querySelector('.sp-row') && !!document.querySelector('.live-ind:not(.connecting)')`);
  if (ok) break;
  await sleep(500);
}
await sleep(2500);
const log = { before: await shot("before"), ind: await evalJs(`document.querySelector('.live-ind')?.textContent`) };
log.before_label = await evalJs(`[...document.querySelectorAll('.sp-lbl')].slice(0,7).map(x=>x.textContent).join(' | ')`);

// —— 改临时目录（模拟 ASSETMASTER 写首帧、VIDEO10 在跑一条任务）——
const sumF = join(TMP, "summary.json");
const sum = JSON.parse(readFileSync(sumF, "utf8"));
const ids = [];
let tk;
if (MODE === "single") {
  // 只改一镜：第 2 集第 3 镜补上首帧（用第 1 集第 1 镜的图）——看只有这一格渐变，邻居不动
  const src = sum.find((e) => e.number === 1).shots[0].first_frame;
  const ep2 = sum.find((e) => e.number === 2);
  ep2.shots[2].first_frame = src;
  ep2.shots[2].first_frame_take = 1;
  ids.push(ep2.shots[2].id);
  writeFileSync(sumF, JSON.stringify(sum));
  mkdirSync(join(TMP, "renders", "ep02", "S3"), { recursive: true });
  tk = join(TMP, "renders", "ep02", "S3", "takes.json");
} else {
  const ep = sum.find((e) => e.number === 1);
  for (const s of ep.shots.slice(1, 5)) {
    s.first_frame = ep.shots[0].first_frame || "/files/placeholder.png";
    ids.push(s.id);
  }
  writeFileSync(sumF, JSON.stringify(sum));
  writeFileSync(join(TMP, "jobs.json"), JSON.stringify([{ id: "demo1", shot_id: ep.shots[5].id, stage: "image", state: "running", eta_s: 70, created_at: "2026-11-01T02:00:00", started_at: new Date(Date.now() - 20000).toISOString().slice(0, 19) }]));
  tk = join(TMP, "renders", "ep01", "S2", "takes.json");
}
writeFileSync(tk, JSON.stringify({ takes: [{ n: 1, stage: "image" }], active: { image: 1 } }));
const t = Date.now() / 1000 + 3;
utimesSync(tk, t, t);
log.changed = ids;

// 连拍：事件到达（≤1.5 s 扫描）+ 进度合并重取（1.5 s）后开始闪；拍出闪烁过程与之后的静止
const frames = [];
const t0 = Date.now();
for (let i = 0; i < 26; i++) {
  await sleep(350);
  const st = await evalJs(`({ev: (window.__live||[]).map(e=>e.type+':'+(e.field||'')).join(','), flash: document.querySelectorAll('.live-flash').length, which: [...document.querySelectorAll('.live-flash')].map(e=>e.className.replace('live-flash','').trim()).join(' ; '), lbl: [...document.querySelectorAll('.sp-lbl')].slice(0,7).map(x=>x.textContent).join(' | ')})`);
  frames.push({ ms: Date.now() - t0, ...st });
  if (st.flash && !log.flash) log.flash = await shot("flash");
}
await sleep(2000);
log.after = await shot("after");
log.after_label = await evalJs(`[...document.querySelectorAll('.sp-lbl')].slice(0,7).map(x=>x.textContent).join(' | ')`);
log.frames = frames;
log.flash_after_settle = await evalJs(`document.querySelectorAll('.live-flash').length`);
writeFileSync(join(HERE, `${PREFIX}_log_${THEME}.json`), JSON.stringify(log, null, 1));
console.log(JSON.stringify(log, null, 1));
ws.close();
spawn("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
await sleep(500);
process.exit(0);
