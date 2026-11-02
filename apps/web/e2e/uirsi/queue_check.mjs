// UIRSI2 L-116 · data_parity D-QUEUE 的页面一半：页面显示的“待你看”数 = /api/owner/queue 的 count。
// 顶栏徽标 .v3-oq[data-oq-count]（每页都有）、画布底栏 a.s-yellow[data-oq-count]（单集页）、队列页条目数 .oq-it。
// 队列读取失败时徽标必须是 "error"（显示“!”），不能是 0。用 probe.mjs（无头 Chrome、只读、非 GET 全拦）。
// 用法：node apps/web/e2e/uirsi/queue_check.mjs   → 打印逐页结果；不一致退出码 1
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGES = ["/#/queue", "/#ep01", "/#/overview"];
const EXPR = `(async()=>{const q=await (await fetch("/api/owner/queue")).json();
const top=document.querySelector(".v3-oq");const strip=document.querySelector("a.s-yellow[data-oq-count]");
const rows=document.querySelectorAll(".oq-it").length;const page=location.hash.startsWith("#/queue");
const empty=!!document.querySelector(".oq-empty h2");const failTxt=document.querySelector(".oq-fail")?.textContent||"";
return JSON.stringify({api:q.status==="error"?"error":String(q.count),top:top?.dataset.oqCount??null,strip:strip?strip.dataset.oqCount:undefined,
rows:page?rows:undefined,emptyShown:page?empty:undefined,fail:failTxt});})()`;
let bad = 0;
for (const p of PAGES)
  for (const s of ["1440x900", "1920x1080"]) {
    let r;
    try {
      const out = execFileSync("node", [join(HERE, "probe.mjs"), p, EXPR, "30000", s], { encoding: "utf8", timeout: 120000, stdio: ["ignore", "pipe", "ignore"] }).trim().split("\n").pop();
      r = JSON.parse(JSON.parse(out));
    } catch (e) {
      r = { error: String(e.message || e).split("\n")[0].slice(0, 80) };
    }
    const miss = [];
    if (r.error) miss.push(r.error);
    else {
      if (r.top !== r.api) miss.push(`顶栏 ${r.top} ≠ 队列 ${r.api}`);
      if (r.strip !== undefined && r.api !== "error" && r.strip !== r.api) miss.push(`画布底栏 ${r.strip} ≠ 队列 ${r.api}`);
      if (r.rows !== undefined && r.api !== "error" && r.rows !== Number(r.api)) miss.push(`队列页 ${r.rows} 行 ≠ 队列 ${r.api}`);
      if (r.api === "error" && r.emptyShown && !r.fail.startsWith("队列读取失败")) miss.push("读取失败却显示成空队列");
    }
    if (miss.length) bad++;
    console.log(`${miss.length ? "✗" : "✓"} ${p} ${s} 队列 ${r.api ?? "?"}${miss.length ? " · " + miss.join("、") : ""}`);
  }
console.log(bad ? `D-QUEUE 页面不一致 ${bad} 处` : "D-QUEUE 页面一致");
process.exit(bad ? 1 : 0);
