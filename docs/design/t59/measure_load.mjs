// T60 首屏测量（fredw-25）：无头 Chrome 打开画布，记录「开始导航 → 第一个镜头行出现」「→ 首帧图加载完」的时间，
// 以及接口请求的字节数。用法：node docs/design/t59/measure_load.mjs <base-url> [次数]
//   例：node docs/design/t59/measure_load.mjs http://127.0.0.1:5173/ 3
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const BASE = process.argv[2] ?? "http://127.0.0.1:5173/";
const RUNS = Number(process.argv[3] ?? 3);
const PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const prof = mkdtempSync(join(tmpdir(), "t60-chrome-"));
  const proc = spawn(CHROME, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`,
    "--window-size=1600,900", "about:blank"], { stdio: "ignore" });
  try {
    let target;
    for (let i = 0; i < 50 && !target; i++) {
      await sleep(200);
      try {
        target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page");
      } catch { /* 等 Chrome */ }
    }
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((r) => (ws.onopen = r));
    let id = 0;
    const pending = new Map();
    const events = [];
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) {
        pending.get(m.id)(m.result);
        pending.delete(m.id);
      } else if (m.method) events.push(m);
    };
    const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
    await send("Page.enable");
    await send("Network.enable");
    await send("Runtime.enable");
    await send("Network.setCacheDisabled", { cacheDisabled: true });
    const rows = [];
    for (let run = 0; run < RUNS; run++) {
      events.length = 0;
      await send("Page.navigate", { url: "about:blank" });
      await sleep(300);
      const t0 = Date.now();
      await send("Page.navigate", { url: `${BASE}?view=episode&theme=dark#ep01-S1` });
      let rowAt = null, imgAt = null;
      while (Date.now() - t0 < 30000 && imgAt == null) {
        await sleep(25);
        const { result } = await send("Runtime.evaluate", {
          returnByValue: true,
          expression: `(() => { const r = document.querySelector(".srow"); const i = r && r.querySelector(".tile img");
            return { row: !!r, img: !!(i && i.complete && i.naturalWidth > 0) }; })()`,
        });
        if (result.value?.row && rowAt == null) rowAt = Date.now() - t0;
        if (result.value?.img) imgAt = Date.now() - t0;
      }
      await sleep(300);
      const api = new Map();
      const reqT = new Map(), urls = new Map(), water = [];
      for (const e of events) {
        if (e.method === "Network.requestWillBeSent" && /\/api\//.test(e.params.request.url)) reqT.set(e.params.requestId, e.params.timestamp);
        if (e.method === "Network.loadingFinished" && reqT.has(e.params.requestId)) water.push([reqT.get(e.params.requestId), e.params.timestamp, e.params.requestId]);
        if (e.method === "Network.responseReceived" && /\/api\//.test(e.params.response.url)) urls.set(e.params.requestId, e.params.response.url.replace(/^https?:\/\/[^/]+/, ""));
        if (e.method === "Network.responseReceived" && /\/api\/episodes/.test(e.params.response.url))
          api.set(e.params.requestId, { url: e.params.response.url.replace(/^https?:\/\/[^/]+/, ""), enc: e.params.response.headers["content-encoding"] ?? "-" });
        if (e.method === "Network.loadingFinished" && api.has(e.params.requestId)) api.get(e.params.requestId).bytes = e.params.encodedDataLength;
      }
      const t00 = Math.min(...water.map((w) => w[0]));
      const wf = water.sort((a, b) => a[0] - b[0]).map(([a, b, id]) => `${Math.round((a - t00) * 1000)}→${Math.round((b - t00) * 1000)}ms ${urls.get(id)}`);
      rows.push({ run: run + 1, firstRowMs: rowAt, firstImageMs: imgAt, api: [...api.values()], waterfall: process.env.WF ? wf : undefined });
    }
    console.log(JSON.stringify({ base: BASE, rows }, null, 1));
    ws.close();
  } finally {
    proc.kill();
  }
}
main().catch((e) => { console.error(e); process.exit(1); });
