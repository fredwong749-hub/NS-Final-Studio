// 画布前端冒烟回归（封板用，fredw-25）。无头 Chrome + DevTools 协议（Node 内置 WebSocket，不装依赖）。
// 逐页逐个交互真点一遍，每个场景记录：console 报错 / 未捕获异常 / 失败的请求（≥400 或网络失败）/
// 卡在“加载中” / 横向溢出 / 期望元素没出现；每个场景截图。
//
//   node tools/ui_smoke/smoke.mjs                         全部场景 × 1366/1600 × 深/浅
//   node tools/ui_smoke/smoke.mjs episode inspector-tabs  只跑指定场景
//   BASE=http://127.0.0.1:8800/ WIDTHS=1600 THEMES=dark node tools/ui_smoke/smoke.mjs
//
// 输出：tools/ui_smoke/shots/<场景>-<宽>-<主题>.jpg、tools/ui_smoke/results.json；退出码 = 有问题的场景数（0 = 全过）。
// 只读：不点出图 / 导入 / 发送 / 上传 / 通过 / 打回 / 设为当前；确认框只打开再按 Esc。
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = process.env.BASE ?? "http://127.0.0.1:5173/";
const PORT = Number(process.env.CDP_PORT ?? 9400 + (process.pid % 500)); // 每次运行换端口：上一次的 Chrome 退出慢时不会抢端口
const WIDTHS = (process.env.WIDTHS ?? "1366,1600").split(",").map(Number);
const THEMES = (process.env.THEMES ?? "dark,light").split(",");
const HEIGHT = { 1366: 768, 1600: 900 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 场景
// 步骤：{ shot: true|"名" } 立刻截图（菜单/抽屉打开时）· { key } 按键 · { click: "选择器" } · { clickText: "按钮文字开头" } · { expect: "选择器" } · { gone: "选择器" }
//       { wait: ms } · { eval: "表达式（返回字符串 = 问题）" } · { esc: true }
const SC = [
  { name: "episode", page: "?view=episode#ep01-S1", steps: [{ expect: ".srow" }, { expect: ".ep-head" }] },
  {
    name: "episode-keys", page: "?view=episode#ep01-S1", steps: [
      { key: "ArrowRight" }, { expect: '.srow.selected[data-shot="ep01-S2"]' }, { key: "ArrowLeft" }, { expect: '.srow.selected[data-shot="ep01-S1"]' },
      { key: "ArrowDown" }, { wait: 800 }, { eval: `/第 2 集/.test(document.querySelector(".tb-ep-name")?.textContent ?? "") ? "" : "↓ 没切到第 2 集"` },
      { expect: ".srow" }, { key: "ArrowUp" }, { wait: 800 },
      { key: "t" }, { expect: ".shot-table, table" }, { key: "t" }, { expect: ".srow" },
      { key: "d" }, { key: "d" }, { key: "d" },
      { key: "\\" }, { wait: 300 }, { key: "\\" }, { wait: 300 },
      { key: "?" }, { expect: ".modal, [role=dialog]" }, { esc: true }, { gone: ".modal, [role=dialog]" },
      { key: "g" }, { expect: ".palette, .modal, [role=dialog]" }, { esc: true },
      { key: "l" }, { wait: 200 },
    ],
  },
  {
    name: "inspector-tabs", page: "?view=episode#ep01-S1", insp: true, steps: [
      { expect: ".inspector .insp-tabs" },
      { eval: `(async () => { const out = []; for (const b of [...document.querySelectorAll(".inspector .insp-tabs button")]) { b.click(); await new Promise((r) => setTimeout(r, 450));
          const body = document.querySelector(".inspector .insp-tab-body"); if (!body || body.innerText.trim().length < 2) out.push("页签「" + b.textContent.trim() + "」内容为空"); } return out.join("；"); })()` },
    ],
  },
  { name: "viewer", page: "?view=episode#ep01-S2", insp: true, steps: [{ key: "f" }, { expect: ".viewer" }, { key: "ArrowRight" }, { wait: 300 }, { esc: true }, { gone: ".viewer" }] },
  { name: "compare-ab", page: "?view=episode#ep01-S2", insp: true, steps: [{ key: "c" }, { expect: ".viewer" }, { wait: 400 }, { esc: true }, { gone: ".viewer" }] },
  { name: "version-chain", page: "?view=episode#ep01-S2", insp: true, steps: [{ key: "[" }, { wait: 300 }, { key: "]" }, { wait: 300 }, { key: "]" }, { wait: 300 }] },
  {
    name: "batch-menu", page: "?view=episode#ep01-S1", steps: [
      { clickText: "批量出图" }, { expect: ".tb-pop .ep-menu-item" }, { shot: true },
      { eval: `(() => { const b = [...document.querySelectorAll(".ep-menu-item")].find((x) => !x.disabled && /整集出/.test(x.textContent)); if (!b) return ""; b.click(); return ""; })()` },
      { wait: 400 }, { esc: true }, { gone: ".modal, [role=dialog]" },
    ],
  },
  { name: "render-confirm", page: "?view=episode#ep01-S2", steps: [{ key: "i" }, { expect: ".modal, [role=dialog]" }, { esc: true }, { gone: ".modal, [role=dialog]" }] },
  { name: "review-mode", page: "?view=episode#ep01-S6", steps: [{ key: "r" }, { expect: ".review-mode" }, { key: "ArrowRight" }, { wait: 600 }, { key: "ArrowRight" }, { wait: 600 }, { esc: true }, { gone: ".review-mode" }] },
  {
    name: "topbar-menus", page: "?view=episode#ep01-S1", steps: [
      { clickText: "资产" }, { expect: ".tb-pop" }, { esc: true }, { click: "body" },
      { clickText: "剧本" }, { expect: ".tb-pop" }, { click: "body" },
      { clickText: "更多" }, { expect: ".tb-pop" }, { click: "body" },
      { clickText: "视图" }, { expect: ".tb-view" }, { click: "body" },
    ],
  },
  { name: "theme-toggle", page: "?view=episode#ep01-S1", steps: [
    { eval: `(async () => { const t0 = document.documentElement.dataset.theme; document.querySelector(".theme-toggle").click(); await new Promise((r) => setTimeout(r, 200));
        const t1 = document.documentElement.dataset.theme; document.querySelector(".theme-toggle").click(); await new Promise((r) => setTimeout(r, 200));
        const t2 = document.documentElement.dataset.theme; return t0 !== t1 && t0 === t2 ? "" : "主题切换不对：" + [t0, t1, t2].join("→"); })()` }] },
  { name: "gpu-panel", page: "?view=episode#ep01-S1", steps: [{ click: ".gpu-btn" }, { expect: ".gpu-drawer" }, { wait: 800 }, { shot: true }, { click: ".gpu-btn" }] },
  { name: "jobs-drawer", page: "?view=episode#ep01-S1", steps: [{ click: ".tb-status" }, { wait: 500 }, { click: ".tb-status" }] },
  { name: "assets", page: "?view=assets&char=lin_wan", steps: [{ expect: ".av3" }, { expect: ".av3-card:not(.empty):not(.av3-skel)" }, { click: ".av3-card:not(.empty):not(.av3-skel)" }, { expect: ".av3-lb" }, { esc: true }, { gone: ".av3-lb" }] },
  { name: "assets-other-char", page: "?view=assets&char=gu_chen", steps: [{ expect: ".av3" }] },
  { name: "people", page: "?view=people", steps: [{ expect: ".pp-card" }, { clickText: "+ 新建人物" }, { expect: ".pp-new" }, { clickText: "收起" }, { gone: ".pp-new" }] },
  { name: "import", page: "?view=import", steps: [{ expect: ".imp-view, .imp2" }] },
  { name: "script-chat", page: "#/script-chat", steps: [{ expect: ".sc-app" }, { click: ".sc-row" }, { wait: 1500 }, { expect: ".sc-msgs" }] },
  { name: "ab", page: "?view=ab", steps: [{ wait: 800 }] },
  { name: "overview", page: "?view=overview", steps: [{ expect: ".ov-cell, .overview" }] },
  { name: "nodes", page: "?view=nodes", steps: [{ wait: 2500 }, { expect: ".react-flow" }] },
  { name: "projects", page: "#/projects", steps: [{ expect: ".pj-main" }] },
  { name: "inbox", page: "#/inbox", steps: [{ expect: ".pj-main" }] },
  { name: "last-episode", page: "?view=episode#ep60-S1", steps: [{ expect: ".srow" }] },
];

// ---------------------------------------------------------------- CDP
async function connect() {
  const prof = mkdtempSync(join(tmpdir(), "ui-smoke-"));
  const proc = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
  let target;
  for (let i = 0; i < 60 && !target; i++) {
    await sleep(200);
    try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); } catch { /* 等 Chrome */ }
  }
  if (!target) throw new Error("Chrome 没起来");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0;
  const pend = new Map();
  const listeners = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { const { r } = pend.get(m.id); pend.delete(m.id); r(m); } else if (m.method) listeners.forEach((f) => f(m));
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, { r }); ws.send(JSON.stringify({ id: i, method, params })); }).then((m) => m.result ?? {});
  return { send, on: (f) => listeners.push(f), close: () => { ws.close(); proc.kill(); } };
}

const KEYCODE = { ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, Escape: 27 };

async function main() {
  const only = process.argv.slice(2);
  const scenes = only.length ? SC.filter((s) => only.includes(s.name)) : SC;
  mkdirSync(join(HERE, "shots"), { recursive: true });
  const c = await connect();
  let log = [];
  c.on((m) => {
    const p = m.params;
    if (m.method === "Runtime.exceptionThrown") log.push({ kind: "exception", text: p.exceptionDetails.exception?.description?.split("\n")[0] ?? p.exceptionDetails.text });
    if (m.method === "Runtime.consoleAPICalled" && (p.type === "error" || p.type === "assert"))
      log.push({ kind: "console", text: p.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 300) });
    if (m.method === "Log.entryAdded" && p.entry.level === "error" && !/Failed to load resource/.test(p.entry.text)) log.push({ kind: "log", text: p.entry.text.slice(0, 300) });
    if (m.method === "Network.responseReceived" && p.response.status >= 400 && /^https?:\/\/127\.0\.0\.1/.test(p.response.url))
      log.push({ kind: "http", text: `${p.response.status} ${p.response.url.replace(/^https?:\/\/[^/]+/, "")}` });
    if (m.method === "Network.loadingFailed" && !p.canceled && !/ERR_ABORTED/.test(p.errorText)) log.push({ kind: "net", text: `${p.errorText} (${p.type})` });
  });
  await c.send("Page.enable");
  await c.send("Runtime.enable");
  await c.send("Log.enable");
  await c.send("Network.enable");
  const ev = async (expression) => (await c.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result?.value;
  const key = async (k) => {
    const code = KEYCODE[k];
    const base = { key: k, windowsVirtualKeyCode: code ?? k.toUpperCase().charCodeAt(0), code: code ? k : undefined, text: code ? undefined : k };
    await c.send("Input.dispatchKeyEvent", { type: code ? "rawKeyDown" : "keyDown", ...base });
    await c.send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
    await sleep(150);
  };
  const results = [];
  for (const W of WIDTHS) {
    const H = HEIGHT[W] ?? Math.round(W * 9 / 16);
    await c.send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
    for (const theme of THEMES) {
      for (const sc of scenes) {
        log = [];
        const issues = [];
        const [path, frag] = sc.page.split("#");
        const url = `${BASE}${path}${path ? "&" : "?"}theme=${theme}${frag ? "#" + frag : ""}`;
        const t0 = Date.now();
        await c.send("Page.navigate", { url: "about:blank" });
        await c.send("Page.navigate", { url });
        // 等页面就绪：文档完成 + 不再显示“加载中” + 视口内图片加载完；20 s 未就绪 = 卡住
        let ready = false;
        while (Date.now() - t0 < 20000) {
          await sleep(300);
          ready = await ev(`document.readyState === "complete" && !!document.querySelector("#root > *")
            && !/^\\s*(加载中|加载 )/m.test(document.querySelector("main, .main, #root")?.innerText.slice(0, 200) ?? "")
            && [...document.images].filter((i) => { const r = i.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight && r.width > 0; }).every((i) => i.complete)`);
          if (ready) break;
        }
        if (!ready) issues.push("加载卡住：20 s 内没有就绪（还显示“加载中”或图片没加载完）");
        await sleep(400);
        // 检查器：场景需要时保证打开（\ 切换）；其余保持默认
        // 检查器加载中也是 .inspector（.empty）：只有完全没有检查器（被收起）时才按 \ 打开
        if (sc.insp && !(await ev(`!!document.querySelector(".inspector")`))) { await key("\\"); await sleep(800); }
        let shot = false;
        for (const st of sc.steps) {
          if (st.key) await key(st.key);
          if (st.esc) await key("Escape");
          if (st.wait) await sleep(st.wait);
          if (st.click) {
            const ok = await ev(`(() => { const e = document.querySelector(${JSON.stringify(st.click)}); if (!e) return false; e.click(); return true; })()`);
            if (!ok) issues.push(`找不到可点的 ${st.click}`);
            await sleep(250);
          }
          if (st.clickText) {
            const ok = await ev(`(() => { const e = [...document.querySelectorAll("button")].find((b) => b.offsetParent && b.textContent.trim().startsWith(${JSON.stringify(st.clickText)})); if (!e) return false; e.click(); return true; })()`);
            if (!ok) issues.push(`找不到按钮「${st.clickText}」`);
            await sleep(300);
          }
          if (st.expect) {
            let ok = false;
            for (let i = 0; i < 20 && !ok; i++) { ok = await ev(`!!document.querySelector(${JSON.stringify(st.expect)})`); if (!ok) await sleep(150); }
            if (!ok) issues.push(`没出现 ${st.expect}`);
          }
          if (st.gone) {
            await sleep(200);
            if (await ev(`!!document.querySelector(${JSON.stringify(st.gone)})`)) issues.push(`没关掉 ${st.gone}`);
          }
          if (st.eval) { const r = await ev(st.eval); if (r) issues.push(String(r)); }
          if (st.shot) {
            shot = true;
            const { data } = await c.send("Page.captureScreenshot", { format: "jpeg", quality: 70 });
            writeFileSync(join(HERE, "shots", `${sc.name}-${st.shot === true ? "open" : st.shot}-${W}-${theme}.jpg`), Buffer.from(data, "base64"));
          }
        }
        // 布局：整页横向溢出；视口右侧被裁的可见元素（祖先不裁切的才算）
        const ov = await ev(`(() => { const out = []; if (document.documentElement.scrollWidth > innerWidth + 1) out.push("整页横向溢出 " + document.documentElement.scrollWidth + "px > " + innerWidth + "px");
          const clips = (e) => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) { const s = getComputedStyle(p); if (s.overflowX !== "visible" || s.overflow !== "visible") return true; } return false; };
          for (const e of document.querySelectorAll("body *")) { const r = e.getBoundingClientRect(); if (r.width > 0 && r.height > 0 && r.right > innerWidth + 2 && r.left < innerWidth && getComputedStyle(e).position !== "fixed" && !clips(e)) { out.push("超出右边界：" + (e.className || e.tagName).toString().slice(0, 60)); if (out.length > 4) break; } }
          return out; })()`);
        issues.push(...(ov ?? []));
        const shotName = `${sc.name}-${W}-${theme}.jpg`;
        const { data } = await c.send("Page.captureScreenshot", { format: "jpeg", quality: 70 });
        writeFileSync(join(HERE, "shots", shotName), Buffer.from(data, "base64"));
        const errs = log.map((l) => `${l.kind}: ${l.text}`);
        results.push({ scene: sc.name, width: W, theme, ms: Date.now() - t0, ok: !issues.length && !errs.length, issues, errors: [...new Set(errs)], shot: `shots/${shotName}`, menuShot: shot });
        console.log(`${!issues.length && !errs.length ? "PASS" : "FAIL"} ${sc.name} ${W} ${theme}${issues.length || errs.length ? " — " + [...issues, ...new Set(errs)].join(" | ") : ""}`);
      }
    }
  }
  c.close();
  writeFileSync(join(HERE, "results.json"), JSON.stringify({ base: BASE, at: new Date().toISOString(), results }, null, 1));
  const bad = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - bad}/${results.length} 通过`);
  process.exit(bad);
}

main().catch((e) => { console.error(e); process.exit(99); });
