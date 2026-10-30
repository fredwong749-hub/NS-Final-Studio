// T59 套用后截图（fredw-25）：无头 Chrome + DevTools 协议（Node 内置 WebSocket，无需安装依赖）。
// 等页面数据加载完（没有“加载中”且网络空闲）再截 1600×900，深 / 浅两套主题各一张。
//
//   node docs/design/t59/shoot_applied.mjs                  全部页面
//   node docs/design/t59/shoot_applied.mjs episode assets   指定页面
//
// 输出 docs/design/t59/applied/<页面>-<主题>.png；需要画布 dev server（5173）与 API（8800）在运行。
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.OUT ?? join(HERE, "applied");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const BASE = process.env.BASE ?? "http://127.0.0.1:5173/";
const PORT = 9333;
export const PAGES = {
  episode: { q: "?view=episode#ep01-S1", hideInsp: true },
  inspector: { q: "?view=episode#ep01-S1", showInsp: true },
  assets: { q: "?view=assets&char=lin_wan" },
  people: { q: "?view=people" },
  import: { q: "?view=import" },
  chat: { q: "#/script-chat" },
  overview: { q: "?view=overview" },
  ab: { q: "?view=ab" },
  ep30: { q: "?view=episode#ep30-S1", hideInsp: true },
  projects: { q: "#/projects" },
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function url(page, theme) {
  const [path, frag] = PAGES[page].q.split("#");
  return `${BASE}${path}${path ? "&" : "?"}theme=${theme}${frag ? "#" + frag : ""}`;
}

async function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((r, j) => ((ws.onopen = r), (ws.onerror = j)));
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { r, j } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? j(new Error(m.error.message)) : r(m.result);
    }
  };
  const send = (method, params = {}) =>
    new Promise((r, j) => {
      const i = ++id;
      pending.set(i, { r, j });
      ws.send(JSON.stringify({ id: i, method, params }));
    });
  return { send, close: () => ws.close() };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const prof = mkdtempSync(join(tmpdir(), "t59-chrome-"));
  const proc = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${prof}`, "--window-size=1600,900", "about:blank"], { stdio: "ignore" });
  try {
    let target;
    for (let i = 0; i < 50 && !target; i++) {
      await sleep(200);
      try {
        const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
        target = list.find((t) => t.type === "page");
      } catch { /* 还没起来 */ }
    }
    if (!target) throw new Error("Chrome 没起来");
    const c = await cdp(target.webSocketDebuggerUrl);
    await c.send("Page.enable");
    await c.send("Runtime.enable");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 900, deviceScaleFactor: 1, mobile: false });
    const pages = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(PAGES);
    for (const page of pages) {
      for (const theme of ["dark", "light"]) {
        await c.send("Page.navigate", { url: url(page, theme) });
        // 等：文档就绪 + 没有“加载中” + 图片加载完，最多 20 s
        const t0 = Date.now();
        for (;;) {
          await sleep(500);
          const { result } = await c.send("Runtime.evaluate", {
            expression: `document.readyState === "complete" && !/加载中/.test(document.body.innerText.slice(0, 400))
              && document.images.length > 0
              && [...document.images].filter((i) => { const r = i.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight && r.width > 0; })
                   .every((i) => i.complete && i.naturalWidth > 0)`,
            returnByValue: true,
          });
          if (result.value || Date.now() - t0 > 30000) break;
        }
        if (PAGES[page].hideInsp)
          await c.send("Runtime.evaluate", {
            expression: `document.querySelector(".inspector") && window.dispatchEvent(new KeyboardEvent("keydown", { key: "\\\\", bubbles: true }))`,
          });
        if (PAGES[page].showInsp)
          await c.send("Runtime.evaluate", {
            expression: `!document.querySelector(".inspector") && window.dispatchEvent(new KeyboardEvent("keydown", { key: "\\\\", bubbles: true }))`,
          });
        await sleep(1200);
        const { data } = await c.send("Page.captureScreenshot", { format: "png" });
        const out = join(OUT, `${page}-${theme}.png`);
        writeFileSync(out, Buffer.from(data, "base64"));
        console.log(out);
      }
    }
    c.close();
  } finally {
    proc.kill();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
