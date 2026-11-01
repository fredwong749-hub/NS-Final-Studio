// UIPIXEL 低频维护模式（总调度 11-01）：
//   ① 每 2 小时一次全量扫描（31 个状态 × 1280/1440/1920 × 深浅）；
//   ② 任何 agent 改了 apps/web/src 下的界面文件（.tsx/.ts/.css），安静 3 分钟后跑一次快扫（1440 深色），两次快扫至少隔 15 分钟。
// 每次扫完和同类的上一次比，写 docs/uipixel/maintenance.md；出现新的严重 / 一般问题时追加 docs/uipixel/alerts.md（交总调度 / 各负责人看）。
// 只读（scan.mjs 本身拦截所有非 GET）；只清理自己产生的旧维护截图目录（m-* / q-*，各留最近 6 个）。
// 启动：node maintain.mjs        停止：删掉 apps/web/e2e/uipixel/maintain.pid 里的进程，或建一个 maintain.stop 文件（下一个检查点自己退出）
import { spawn } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, watch, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "../../../..");
const SRC = join(HERE, "../../src");
const DOC = join(ROOT, "docs/uipixel/maintenance.md");
const ALERT = join(ROOT, "docs/uipixel/alerts.md");
const FULL_EVERY = 2 * 3600e3, QUIET = 3 * 60e3, QUICK_GAP = 15 * 60e3;
writeFileSync(join(HERE, "maintain.pid"), String(process.pid));
mkdirSync(dirname(DOC), { recursive: true });
if (!existsSync(DOC)) writeFileSync(DOC, "# UIPIXEL 维护扫描记录\n\n| 时间 | 类型 | 轮次 | 去重问题 | 严重 | 一般 | 轻微 | 比上一次新增（严重 / 一般） | 触发 |\n|---|---|---|---|---|---|---|---|---|\n");

const stamp = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 16).replace(/[-:T]/g, "").replace(/^(\d{8})(\d{4})$/, "$1-$2");
let running = false, lastChange = 0, lastQuick = 0, lastFull = 0, changed = new Set();
const last = { full: null, quick: null };

function runScan(kind, why) {
  return new Promise((res) => {
    running = true;
    const round = `${kind === "full" ? "m" : "q"}-${stamp()}`;
    const args = ["scan.mjs", round, ...(kind === "quick" ? ["--quick"] : [])];
    const p = spawn(process.execPath, args, { cwd: HERE, stdio: "ignore" });
    p.on("exit", () => {
      running = false;
      try {
        const j = JSON.parse(readFileSync(join(HERE, round, "scan.json"), "utf8"));
        const sigs = new Set(j.items.filter((i) => i.sev >= 2).map((i) => i.sig));
        const prev = last[kind];
        const fresh = prev ? j.items.filter((i) => i.sev >= 2 && !prev.has(i.sig)) : [];
        last[kind] = sigs;
        const s = j.summary;
        appendFileSync(DOC, `| ${new Date().toLocaleString("zh-CN", { hour12: false })} | ${kind === "full" ? "全量" : "快扫"} | ${round} | ${s.unique} | ${s.sev3} | ${s.sev2} | ${s.sev1} | ${fresh.filter((i) => i.sev >= 3).length} / ${fresh.filter((i) => i.sev === 2).length} | ${why.replace(/\|/g, "/")} |\n`);
        if (fresh.length || s.crashed.length) {
          appendFileSync(ALERT, `\n## ${new Date().toLocaleString("zh-CN", { hour12: false })} ${round}（${why}）\n` +
            (s.crashed.length ? `- **页面崩溃**：${s.crashed.join(", ")}\n` : "") +
            fresh.slice(0, 20).map((i) => `- ${"●".repeat(i.sev)} ${i.kind} · ${[...new Set(i.where.map((w) => w.page))].join(",")} · \`${i.sel.split(" > ").slice(-2).join(" > ")}\` · ${i.msg}${i.loc ? ` · ${i.loc.css ?? i.loc.tsx}` : ""}`).join("\n") + "\n");
        }
      } catch (e) {
        appendFileSync(DOC, `| ${new Date().toLocaleString("zh-CN", { hour12: false })} | ${kind} | ${round} | 扫描没出结果：${String(e.message).slice(0, 60)} | | | | | ${why} |\n`);
      }
      // 只清理维护模式自己产生的旧目录（各留最近 6 个）
      for (const pre of ["m-", "q-"]) {
        const ds = readdirSync(HERE).filter((d) => d.startsWith(pre) && statSync(join(HERE, d)).isDirectory()).sort();
        for (const d of ds.slice(0, Math.max(0, ds.length - 6))) rmSync(join(HERE, d), { recursive: true, force: true });
      }
      res();
    });
  });
}

watch(SRC, { recursive: true }, (_e, f) => {
  if (!f || !/\.(tsx?|css)$/.test(f)) return;
  lastChange = Date.now();
  changed.add(String(f).replace(/\\/g, "/"));
});

for (;;) {
  if (existsSync(join(HERE, "maintain.stop"))) break;
  const now = Date.now();
  if (!running && now - lastFull >= FULL_EVERY) {
    lastFull = now;
    await runScan("full", "每 2 小时定时");
  } else if (!running && changed.size && now - lastChange >= QUIET && now - lastQuick >= QUICK_GAP) {
    lastQuick = now;
    const files = [...changed].slice(0, 6).join(", ") + (changed.size > 6 ? ` 等 ${changed.size} 个` : "");
    changed = new Set();
    await runScan("quick", `界面文件改动：${files}`);
  }
  await new Promise((r) => setTimeout(r, 30e3));
}
process.exit(0);
