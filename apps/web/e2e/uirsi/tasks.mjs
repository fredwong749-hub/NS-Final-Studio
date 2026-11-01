// UIRSI 任务走查（RUBRIC T1–T7）：按项目方真实任务在真界面上一步一步点，计点击数、每步等待、卡住处、报错 / 空白，逐步截图。
// 只读：CDP 拦下全部非 GET（要花钱 / 写数据的那一下记成“到达提交点”，不真的提交）。
// 用法：node tasks.mjs <prefix> [theme] [width]  → <prefix>_tasks.json + <prefix>_T*_*.png
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [, , prefix = "t0", theme = "dark", width = "1440"] = process.argv;
const PORT = 9684;
const BASE = "http://127.0.0.1:5173";
const CH = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const udir = join(process.env.TEMP || HERE, `uirsi_tasks_${Date.now()}`);
mkdirSync(udir, { recursive: true });
const proc = spawn(CH, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 60 && !target; i++) {
  try {
    target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((x) => x.type === "page");
  } catch {}
  if (!target) await sleep(200);
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = new Map();
const consoleErr = [];
const blocked = [];
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    if (request.method !== "GET" && request.method !== "HEAD") {
      blocked.push(`${request.method} ${new URL(request.url).pathname}`);
      return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {});
    }
    return send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
  if (m.method === "Runtime.exceptionThrown") consoleErr.push(m.params.exceptionDetails?.exception?.description?.slice(0, 200) ?? "exception");
};
await send("Page.enable");
await send("Runtime.enable");
await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
// 登录：截图 / 走查用本机只读查看令牌（data/auth/viewer_token），能看界面、不能以项目方身份做决定
try {
  const vt = readFileSync(join(HERE, "..", "..", "..", "..", "data", "auth", "viewer_token"), "utf8").trim();
  await send("Network.enable");
  await send("Network.setExtraHTTPHeaders", { headers: { "x-ns-viewer-token": vt } });
} catch {
  /* 旧后端没有登录：照常 */
}
await send("Emulation.setDeviceMetricsOverride", { width: +width, height: Math.round(+width * 0.625), deviceScaleFactor: 1, mobile: false });

// 页面里的小工具：等元素、按文字点、看有没有报错 / 空白
const LIB = `window.__T = {
  vis(e){ if(!e) return false; const r=e.getBoundingClientRect(); return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=="hidden"; },
  q(sel){ return [...document.querySelectorAll(sel)].find((e)=>__T.vis(e)) || null; },
  byText(t, sel){ const all=[...document.querySelectorAll(sel||"button, a, [role=tab], .ns-run, .ns-sep, .ns-node, .ac-card-hit, .cut-item, .v3-step, label")].filter(__T.vis);
    return all.find((e)=>e.textContent.trim()===t) || all.find((e)=>e.textContent.trim().startsWith(t)) || all.find((e)=>e.textContent.includes(t)) || null; },
  problems(){ const out=[]; for (const e of document.querySelectorAll(".ds-loaderr, .boot-err, .banner.bad, [role=alert]")) if(__T.vis(e)) out.push(e.textContent.trim().slice(0,80));
    for (const e of document.querySelectorAll(".ds-empty, .empty")) if(__T.vis(e) && !e.closest(".v3-frame, .v3-vid, .v3e-stage, .v3-clip")) out.push("空：" + e.textContent.trim().slice(0,60)); return out; }
};`;
async function ev(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  return r.result?.value;
}
async function waitFor(js, timeout = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await ev(`(()=>{ try { return !!(${js}); } catch { return false; } })()`)) return Date.now() - t0;
    await sleep(150);
  }
  return -1;
}
async function open(path) {
  await send("Page.navigate", { url: "about:blank" });
  await sleep(150);
  const [p, h = ""] = path.split("#");
  await send("Page.navigate", { url: `${BASE}${p}${p.includes("?") ? "&" : "?"}theme=${theme}${h ? `#${h}` : ""}` });
  await waitFor("document.readyState==='complete'", 15000);
  // 外壳出来（顶栏）+ 主内容出来（画布行 / 页面主体）= 首屏时间
  const t0 = Date.now();
  await waitFor("document.querySelector('.v3-top') && (document.querySelector('.v3-row, .ns-page, .ac-card, .cut-item, .cut-page, .v3p-page, .sf-page, .v3e-btn'))", 30000);
  await ev(LIB);
  // 首屏出来之前发出的 /api 请求数（不含缩略图）= 首屏关键路径上的请求（K2）
  lastFirstApi = await ev(`performance.getEntriesByType("resource").filter((e) => e.name.includes("/api/") && !e.name.includes("/api/thumb")).length`);
  return Date.now() - t0;
}
let lastFirstApi = 0;

const tasks = [];
// 每个任务的目标（点击数、秒）：参照小云雀同类任务（docs/xyq_walkthrough.md 点击数表）
const TARGET = {"T1": {"clicks": 1, "sec": 3}, "T2": {"clicks": 3, "sec": 3}, "T3": {"clicks": 2, "sec": 3}, "T4": {"clicks": 1, "sec": 2}, "T5": {"clicks": 2, "sec": 3}, "T6": {"clicks": 2, "sec": 2}, "T7": {"clicks": 2, "sec": 3}};
/** 任务分 0–10：多点一次 −1.5；多等 1 s −1；卡住 −5；被闸门挡 −1（写明原因的闸门是设计，不算迷路）；每个报错 / 空白 −1（最多 −3）；首屏 >3 s −2 */
export function taskScore(r) {
  const t = r.target ?? { clicks: 2, sec: 3 };
  let x = 10 - 1.5 * Math.max(0, r.clicks + r.keys - t.clicks) - Math.max(0, r.ms / 1000 - (r.first_ms ?? 0) / 1000 - t.sec);
  if (r.stuck) x -= 5;
  if (r.gate) x -= 1;
  x -= Math.min(3, r.problems.length);
  if ((r.first_ms ?? 0) > 3000) x -= 2;
  return Math.max(0, Math.round(x * 10) / 10);
}
async function task(id, name, xyq, start, steps) {
  const rec = { id, name, xyq, target: TARGET[id], clicks: 0, keys: 0, ms: 0, steps: [], stuck: null, problems: [], ok: false };
  const t0 = Date.now();
  rec.first_ms = await open(start);
  rec.first_api = lastFirstApi;
  for (const [i, st] of steps.entries()) {
    await ev(LIB);
    const s0 = Date.now();
    let did = "";
    if (st.waitBefore) await waitFor(st.waitBefore, 8000);
    if (st.gateIf) {
      await sleep(600);
      const why = await ev(`(()=>{ try { return (${st.gateIf}) || ""; } catch { return ""; } })()`);
      if (why) { rec.gate = `（生产状态）${why}`; const shot = await send("Page.captureScreenshot", { format: "png" }); const f = `${prefix}_${id}_${i + 1}_${theme}.png`; writeFileSync(join(HERE, f), Buffer.from(shot.data, "base64")); rec.steps.push({ did: "—", note: rec.gate, wait_ms: 0, total_ms: Date.now() - s0, shot: f, ok: true }); break; }
    }
    if (st.skipIf && (await ev(`(()=>{ try { return !!(${st.skipIf}); } catch { return false; } })()`))) continue;
    if (st.click) {
      let ok = false;
      for (let k = 0; k < 40 && !ok; k++) { if (k) await sleep(200); ok = await ev(`(()=>{ const e = ${st.click.startsWith("css:") ? `__T.q(${JSON.stringify(st.click.slice(4))})` : `__T.byText(${JSON.stringify(st.click)}, ${JSON.stringify(st.within ?? null)})`}; if(!e) return false; e.scrollIntoView({block:"center"});
        if (e.disabled) { const near = e.parentElement ? e.parentElement.textContent.replace(e.textContent, "").trim().slice(0, 60) : ""; return "gate:" + (e.title || near || "按钮不可点"); }
        e.click(); return true; })()`); }
      if (!ok) { rec.stuck = `第 ${i + 1} 步找不到“${st.click}”`; break; }
      if (typeof ok === "string" && ok.startsWith("gate:")) { rec.gate = ok.slice(5); rec.clicks++; const shot = await send("Page.captureScreenshot", { format: "png" }); const f = `${prefix}_${id}_${i + 1}_${theme}.png`; writeFileSync(join(HERE, f), Buffer.from(shot.data, "base64")); rec.steps.push({ did: `点 ${st.click}（不可点）`, note: `闸门：${rec.gate}`, wait_ms: 0, total_ms: Date.now() - s0, shot: f, ok: true }); break; }
      rec.clicks++;
      did = `点 ${st.click}`;
    }
    if (st.key) {
      await ev(`document.dispatchEvent(new KeyboardEvent("keydown",{key:${JSON.stringify(st.key)},bubbles:true}))`);
      rec.keys++;
      did = `按 ${st.key}`;
    }
    if (st.type) {
      await ev(`(()=>{ const e=__T.q(${JSON.stringify(st.type[0])}); if(!e) return false; const set=Object.getOwnPropertyDescriptor(e.__proto__,"value").set; set.call(e, ${JSON.stringify(st.type[1])}); e.dispatchEvent(new Event("input",{bubbles:true})); return true; })()`);
      did = `输入 ${st.type[0]}`;
    }
    const w = st.wait ? await waitFor(st.wait, st.timeout ?? 20000) : 0;
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const f = `${prefix}_${id}_${i + 1}_${theme}.png`;
    writeFileSync(join(HERE, f), Buffer.from(shot.data, "base64"));
    const probs = await ev("__T ? __T.problems() : []");
    rec.problems.push(...(probs ?? []));
    rec.steps.push({ did, note: st.note ?? "", wait_ms: w, total_ms: Date.now() - s0, shot: f, ok: w >= 0 });
    if (st.expectPost) { await sleep(800); if (!blocked.some((b) => b.startsWith("POST"))) { rec.stuck = `第 ${i + 1} 步点了但没有发出提交`; } }
    if (rec.stuck) break;
    if (w < 0) { rec.stuck = `第 ${i + 1} 步等不到：${st.note ?? st.wait}`; break; }
  }
  rec.ms = Date.now() - t0;
  rec.ok = !rec.stuck;
  rec.problems = [...new Set(rec.problems)].slice(0, 8);
  rec.score = taskScore(rec);
  tasks.push(rec);
  console.log(`${id} 分 ${rec.score} · ${rec.gate ? "闸门" : rec.ok ? "OK" : "卡住"} 首屏 ${(rec.first_ms / 1000).toFixed(1)}s 点击 ${rec.clicks} 按键 ${rec.keys} 用时 ${(rec.ms / 1000).toFixed(1)}s ${rec.stuck ?? ""}${rec.gate ? `闸门：${rec.gate}` : ""} ${rec.problems.join(" | ")}`);
}

// ---------------------------------------------------------------- 任务（项目方真实流程）
await task("T1", "新建剧本：从画布出发，写好提纲到可以提交", "小云雀：上传剧本 → 解析（1–2 次）", "/#ep02", [
  { click: "＋ 新建剧本", within: ".v3-top a, .v3-top button", wait: "document.querySelector('.ns-outline')", note: "打开新建剧本表单" },
  { type: [".ns-outline", "（走查用提纲，不提交）一个都市女孩入职第一天……"], wait: "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('开始自动写作')&&!b.disabled)", note: "填提纲后“开始自动写作”可点" },
]);
await task("T2", "看 10 集新剧本：打开整季、逐集看分镜", "小云雀：分集卡列表 0 次点击看进度", "/#/script-create", [
  { click: "css:.ns-run", wait: "document.querySelector('.ns-sep')", note: "打开最新剧本（整季）", skipIf: "document.querySelector('.ns-sep')" },
  { wait: "document.querySelector('.er-shot')", note: "这一集的剧情和每一镜（默认就显示）" },
  { click: "css:.ns-sep:nth-child(2)", wait: "document.querySelector('.ns-sep.on')?.textContent.includes('第 2 集') && document.querySelector('.er-shot')", note: "换到第 2 集，看到这一集每一镜（有首帧就带图）" },
  { click: "css:.ns-sep:nth-child(10)", wait: "document.querySelector('.ns-sep.on')?.textContent.includes('第 10 集') && document.querySelector('.er-shot')", note: "换到第 10 集" },
]);
await task("T3", "挑设定图：从画布出发，到某角色某套造型的设定图候选，点一张", "小云雀：资源库 → 角色卡一页放全（1–2 次）", "/#ep02", [
  { click: "资产", within: ".v3-step", wait: "document.querySelector('.hub-nav, .ac-card')", note: "点顶栏 ② 资产（人物页）" },
  { click: "造型 A", wait: "document.querySelector('.hub-sheet img, .hub-pick img, .sp-cand img')", note: "看造型 A 的设定图候选" },
]);
await task("T4", "看首帧：画布里放大看一镜的首帧", "小云雀：没有首帧层（片段卡缩略图 0 次）", "/#ep02", [
  { gateIf: "document.querySelector('.v3-row .v3-frame') && !document.querySelector('.v3-row .v3-frame img') && '这一集还没有首帧'", click: "css:.v3-row .v3-frame", wait: "document.querySelector('.viewer, .v3-viewer, [class*=viewer]')", note: "点首帧全屏看" },
]);
await task("T5", "出视频：给一镜重出视频（到提交那一下）", "小云雀：填提示词 + 立即生成（2 次）", "/#ep02-S2", [
  { key: "Enter", wait: "document.querySelector('.v3e-btn')", note: "进精修" },
  { gateIf: "(document.body.textContent.match(/首尾帧都定稿后才能出视频|首帧已过期，先重出首帧|先定稿首帧/)||[])[0] || ''", click: "出视频", wait: "window.__blockedSeen === undefined || true", note: "点出视频（提交被拦，不真出）", expectPost: true },
]);
await task("T6", "审片打回：看一镜视频，打回并写原因", "小云雀：没有审片 / 打回层", "/#ep02-S2", [
  { key: "Enter", wait: "document.querySelector('.v3e-btn')", note: "进精修" },
  { gateIf: "!document.querySelector('.v3e-stage video, video') && '这一镜还没有视频，没有可打回的'", click: "打回", wait: "document.querySelector('.ds-modal, .dlg, [role=dialog]')", note: "打开打回原因框" },
]);
await task("T7", "看成片对比：两版成片并排同步看", "小云雀：合成全集在多轨编辑器（未走到）", "/#ep02", [
  { click: "成片", within: ".v3-step", wait: "document.querySelector('.cut-item, .cut-page')", note: "进成片页" },
  { gateIf: "!document.querySelector('.cut-item') && '这一集还没有成片'", click: "两版对比", wait: "document.querySelectorAll('.cut-cmp video').length>=2", note: "两版并排" },
]);

const avg = Math.round((tasks.reduce((a, t) => a + t.score, 0) / tasks.length) * 10) / 10;
console.log(`任务分平均 ${avg}`);
writeFileSync(join(HERE, `${prefix}_tasks.json`), JSON.stringify({ avg, theme, width: +width, tasks, blocked, consoleErrors: [...new Set(consoleErr)].slice(0, 20) }, null, 1));
ws.close();
proc.kill();
process.exit(0);
