// UIRSI 截图工具（由 ux6 版改：CDP :9681、只读旁路 :8803 只挂 /api/story-runs）：自起无头 Chrome，CDP Fetch 层拦下全部非 GET/HEAD（一律不发到 :8800）。
// CDP Fetch 层拦截全部非 GET/HEAD 请求并计数（一律拦下，不发到 :8800）。
// :8800 还没重启，新接口（/api/revisions/*、/api/shots/{id}/deps）在线上是 404：
// 截图时把这几条 GET（以及只读的 POST /api/revisions/impact）转到本机只读旁路 :8801（只挂 revisions 路由、不写账本）；
// 旁路没开就照常走 :8800，界面显示降级状态。
// 用法：node shoot_ux5.mjs <scenarios.json> <outPrefix>
//   scenarios.json: [{ "name": "assets", "path": "/#/assets", "sizes": [[1440,900]], "themes": ["dark","light"], "wait": 4000, "js": "…可选，只点开弹层类按钮…" }]
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.SHOOT_PORT || 9681); // UIFIX-S：多个 agent 同时截图会撞端口、连到别人的浏览器
const BASE = "http://127.0.0.1:5173";
const SIDE = process.env.SIDE_URL || "http://127.0.0.1:8803";  // r38：可用环境变量换旁路（infra_sidecar.py :8804）
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const [, , scenFile, prefix = "impl"] = process.argv;
const scen = JSON.parse(readFileSync(scenFile, "utf8"));
const AUDIT = readFileSync(join(HERE, "audit.js"), "utf8");
const udir = join(process.env.TEMP || HERE, `uirsi_chrome_${Date.now()}`);
mkdirSync(udir, { recursive: true });

const proc = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${udir}`, "--headless=new", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targetWs() {
  for (let i = 0; i < 50; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = l.find((x) => x.type === "page");
      if (p) return p.webSocketDebuggerUrl;
    } catch {
      /* 还没起来 */
    }
    await sleep(200);
  }
  throw new Error("chrome 没起来");
}

let sideUp = false;
try {
  sideUp = (await fetch(`${SIDE}${process.env.SIDE_HEALTH || "/api/story-runs"}`, { signal: AbortSignal.timeout(60000) })).ok;
} catch {
  sideUp = false;
}

const ws = new WebSocket(await targetWs());
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
const blocked = [];
const routed = [];
const consoleErr = [];
function send(method, params = {}) {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((res, rej) => pending.set(i, { res, rej }));
}
const SIDE_GET = process.env.SIDE_GET_RE ? new RegExp(process.env.SIDE_GET_RE) : /^\/api\/story-(runs|images)(\/|$)/;
ws.onmessage = async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    return;
  }
  if (m.method === "Fetch.requestPaused") {
    const { requestId, request } = m.params;
    const u = new URL(request.url);
    const isApi = u.pathname.startsWith("/api/");
    if (request.method !== "GET" && request.method !== "HEAD") {
      // 唯一放行：只读的影响面预览，转到旁路（不经过 :8800）
      if (sideUp && request.method === "POST" && (u.pathname === "/api/revisions/impact" || u.pathname === "/api/revisions/impact-shots")) {
        routed.push(`POST ${u.pathname}`);
        blocked.push({ method: request.method, url: u.pathname, action: "routed-readonly-sidecar" });
        return send("Fetch.continueRequest", { requestId, url: SIDE + u.pathname + u.search }).catch(() => {});
      }
      blocked.push({ method: request.method, url: u.pathname, action: "blocked" });
      return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }).catch(() => {});
    }
    if (sideUp && isApi && SIDE_GET.test(u.pathname)) {
      routed.push(`GET ${u.pathname}`);
      return send("Fetch.continueRequest", { requestId, url: SIDE + u.pathname + u.search }).catch(() => {});
    }
    return send("Fetch.continueRequest", { requestId }).catch(() => {});
  }
  if (m.method === "Runtime.exceptionThrown") consoleErr.push(m.params.exceptionDetails?.exception?.description?.slice(0, 300) ?? "exception");
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") consoleErr.push(m.params.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 300));
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

const out = [];
for (const s of scen) {
  for (const [w, h] of s.sizes ?? [[1440, 900]]) {
    for (const theme of s.themes ?? ["dark"]) {
      await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      const sep = s.path.includes("?") ? "&" : "?";
      // ?theme= 放在 # 之前
      const [p, hash = ""] = s.path.split("#");
      const url = `${BASE}${p}${p.includes("?") ? "&" : "?"}theme=${theme}${hash ? `#${hash}` : ""}`;
      void sep;
      // 只换 # 不会重新加载页面（单页应用状态会带到下一张），先回 about:blank 再进
      await send("Page.navigate", { url: "about:blank" });
      await sleep(200);
      await send("Page.navigate", { url });
      await sleep(s.wait ?? 4000);
      if (s.js) {
        try {
          await send("Runtime.evaluate", { expression: `(async()=>{const W=async(f,t=30000)=>{const s0=Date.now();while(Date.now()-s0<t){const v=f();if(v)return v;await new Promise(r=>setTimeout(r,250));}return null;};${s.js}})()`, awaitPromise: true });
        } catch (e) {
          consoleErr.push(`js: ${e.message}`);
        }
        await sleep(s.after ?? 1500);
      }
      const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
      const f = join(HERE, `${prefix}_${s.name}_${w}_${theme}.png`);
      writeFileSync(f, Buffer.from(r.data, "base64"));
      // 横向滚动检查
      const hs = await send("Runtime.evaluate", { expression: "document.documentElement.scrollWidth > innerWidth + 1", returnByValue: true });
      // UIRSI：排版自动检查（audit.js，只读计算样式）
      let audit = null;
      try {
        const a = await send("Runtime.evaluate", { expression: AUDIT, returnByValue: true });
        audit = a.result.value ?? { error: a.exceptionDetails?.text ?? "no value" };
      } catch (e) {
        audit = { error: String(e.message ?? e) };
      }
      // UIRSI（W-02）：本页打开到截图为止的 /api 请求数、重复数、>4 s 的请求（Resource Timing，只读）
      let net = null;
      try {
        const n = await send("Runtime.evaluate", {
          returnByValue: true,
          expression: `(() => { const a = performance.getEntriesByType("resource").filter((e) => e.name.includes("/api/") && !e.name.includes("/api/thumb"));
            const keys = a.map((e) => { const u = new URL(e.name); return u.pathname + u.search; });
            const k3 = a.filter((e) => e.startTime < 3000).map((e) => { const u = new URL(e.name); return u.pathname + u.search; });
            const dup = k3.length - new Set(k3).size; // 只数首屏 3 s 内的重复（之后的是正常轮询）
            const slow = a.filter((e) => e.duration > 4000).map((e) => new URL(e.name).pathname + " " + Math.round(e.duration) + "ms");
            const first = a.filter((e) => e.startTime < 3000).length;
            const img = performance.getEntriesByType("resource").filter((e) => e.initiatorType === "img");
            const imgKB = Math.round(img.reduce((s, e) => s + (e.encodedBodySize || e.transferSize || 0), 0) / 1024);
            const big = img.filter((e) => (e.encodedBodySize || 0) > 400 * 1024).length;
            return { api: a.length, first3s: first, dup, slow, max: Math.round(Math.max(0, ...a.map((e) => e.duration))), imgKB, bigImg: big }; })()`,
        });
        net = n.result.value;
      } catch {
        net = null;
      }
      out.push({ file: f.split(/[\\/]/).pop(), hscroll: hs.result.value, audit, net });
    }
  }
}
const summary = { shots: out, nonGet: blocked.length, blocked: blocked.filter((b) => b.action === "blocked"), routedToSidecar: routed.length, sidecar: sideUp, consoleErrors: [...new Set(consoleErr)].slice(0, 30) };
writeFileSync(join(HERE, `${prefix}_log.json`), JSON.stringify(summary, null, 2));
const SUM_KEYS = ["textEls", "fontOff", "spaceOff", "colorOff", "shadowOff", "overflow", "clipNoTitle", "orphan", "contrastFail", "contrastSecFail", "lineTight"];
const auditSum = Object.fromEntries(SUM_KEYS.map((k) => [k, out.reduce((a, x) => a + (x.audit?.[k] ?? 0), 0)]));
writeFileSync(join(HERE, `${prefix}_audit.json`), JSON.stringify({ sum: auditSum, shots: out.map((x) => ({ file: x.file, ...x.audit })) }, null, 1));
console.log(JSON.stringify({ audit: auditSum }));
const nets = out.filter((x) => x.net);
writeFileSync(join(HERE, `${prefix}_net.json`), JSON.stringify(nets.map((x) => ({ file: x.file, ...x.net })), null, 1));
console.log(JSON.stringify({ net: { maxApi: Math.max(0, ...nets.map((x) => x.net.api)), maxFirst3s: Math.max(0, ...nets.map((x) => x.net.first3s)), dupTotal: nets.reduce((a, x) => a + x.net.dup, 0), slow: nets.reduce((a, x) => a + x.net.slow.length, 0), maxImgKB: Math.max(0, ...nets.map((x) => x.net.imgKB ?? 0)), bigImg: nets.reduce((a, x) => a + (x.net.bigImg ?? 0), 0) } }));
console.log(JSON.stringify({ shots: out.length, hscroll: out.filter((x) => x.hscroll).map((x) => x.file), nonGet: summary.nonGet, blocked: summary.blocked.length, routed: routed.length, sidecar: sideUp, errors: summary.consoleErrors.length }, null, 0));
ws.close();
proc.kill();
process.exit(0);
