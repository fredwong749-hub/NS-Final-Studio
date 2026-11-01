// UX6 实现轮截图工具（由 ux5 版改：CDP :9675、只读旁路 :8802、旁路覆盖 UX6 新 GET 接口）（只读）：自起无头 Chrome（CDP :9675，独立用户目录），
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
const PORT = 9675;
const BASE = "http://127.0.0.1:5173";
const SIDE = "http://127.0.0.1:8802";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const [, , scenFile, prefix = "impl"] = process.argv;
const scen = JSON.parse(readFileSync(scenFile, "utf8"));
const udir = join(process.env.TEMP || HERE, `ux6_chrome_${Date.now()}`);
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
  sideUp = (await fetch(`${SIDE}/api/revisions/keys`, { signal: AbortSignal.timeout(60000) })).ok;
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
const SIDE_GET = /\/api\/revisions\/|\/api\/shots\/[^/]+\/deps(\/waivers)?$|\/api\/episodes\/\d+\/(cuts|cut-job|cut\/deps)$|^\/api\/(loras|props|voices|prompt-templates|asset-proposals)(\/|$)|^\/api\/assets\/[^/]+\/chain$/;
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
      out.push({ file: f.split(/[\\/]/).pop(), hscroll: hs.result.value });
    }
  }
}
const summary = { shots: out, nonGet: blocked.length, blocked: blocked.filter((b) => b.action === "blocked"), routedToSidecar: routed.length, sidecar: sideUp, consoleErrors: [...new Set(consoleErr)].slice(0, 30) };
writeFileSync(join(HERE, `${prefix}_log.json`), JSON.stringify(summary, null, 2));
console.log(JSON.stringify({ shots: out.length, hscroll: out.filter((x) => x.hscroll).map((x) => x.file), nonGet: summary.nonGet, blocked: summary.blocked.length, routed: routed.length, sidecar: sideUp, errors: summary.consoleErrors.length }, null, 0));
ws.close();
proc.kill();
process.exit(0);
