// 稳定通道的构建器：源码有变 + gate.sh 全过（tsc、爬虫自检、vite build、main.tsx、data_parity）→ 出一份新构建 → 原子切换 current.txt。
// 闸门不过：保留旧版本，记日志，不切换（项目方永远只看到过了闸门的版本）。
// 用法：
//   node rebuild.mjs            构建一次（源码没变就跳过）
//   node rebuild.mjs --loop     常驻：每 15 分钟检查一次
//   node rebuild.mjs --force "原因"   源码没变也重建（仍然要过闸门）
//   node rebuild.mjs --rollback       指回上一份构建
//   node rebuild.mjs --list           列出保留的构建
// 日志：builds/rebuild.log；保留最近 6 份构建。
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync, appendFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "../../..");
const BUILDS = join(HERE, "builds");
const LOG = join(BUILDS, "rebuild.log");
const KEEP = 6;
const EVERY = 15 * 60 * 1000;
mkdirSync(BUILDS, { recursive: true });
const args = process.argv.slice(2);
const log = (s) => { const line = `${new Date().toISOString()} ${s}`; console.log(line); appendFileSync(LOG, line + "\n"); };
const bash = process.platform === "win32" ? "C:/Program Files/Git/bin/bash.exe" : "bash";

function srcStamp() {
  let max = 0;
  const walk = (d) => { for (const n of readdirSync(d, { withFileTypes: true })) { const p = join(d, n.name); if (n.isDirectory()) walk(p); else max = Math.max(max, statSync(p).mtimeMs); } };
  walk(join(WEB, "src"));
  for (const f of ["index.html", "vite.config.ts", "package.json"]) if (existsSync(join(WEB, f))) max = Math.max(max, statSync(join(WEB, f)).mtimeMs);
  return Math.round(max);
}
const builds = () => readdirSync(BUILDS, { withFileTypes: true }).filter((d) => d.isDirectory() && /^b\d{8}-\d{6}$/.test(d.name)).map((d) => d.name).sort();
const current = () => { try { return readFileSync(join(BUILDS, "current.txt"), "utf8").trim(); } catch { return null; } };
function setCurrent(name) {
  const tmp = join(BUILDS, "current.txt.tmp");
  writeFileSync(tmp, name + "\n");
  renameSync(tmp, join(BUILDS, "current.txt")); // 原子替换，服务端最多 2 秒后读到新指针
}

function once(force) {
  const stamp = srcStamp();
  const last = (() => { try { return JSON.parse(readFileSync(join(BUILDS, "last.json"), "utf8")); } catch { return {}; } })();
  if (!force && last.stamp === stamp && current()) return log(`源码没变（${new Date(stamp).toISOString()}），不重建；当前 ${current()}`);
  log(`开始：源码时间 ${new Date(stamp).toISOString()}${force ? `；强制：${force}` : ""}`);
  const g = spawnSync(bash, [join(HERE, "../gate.sh")], { cwd: WEB, encoding: "utf8", timeout: 15 * 60 * 1000 });
  const tail = `${g.stdout ?? ""}${g.stderr ?? ""}`.trim().split("\n").slice(-6).join(" ⏎ ");
  if (g.status !== 0) return log(`闸门没过（退出码 ${g.status}），不切换，项目方继续看 ${current() ?? "（无）"}：${tail}`);
  const d = new Date();
  const z = (n) => String(n).padStart(2, "0");
  const name = `b${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}`; // 本机时间
  const out = join(BUILDS, name);
  // 直接用 node 跑 vite 的入口（不经 shell：路径里有空格 “NS-Final Studio”，经 shell 会被拆开）
  const b = spawnSync(process.execPath, [join(WEB, "node_modules/vite/bin/vite.js"), "build", "--outDir", out, "--emptyOutDir", "--logLevel", "error"], { cwd: WEB, encoding: "utf8", timeout: 10 * 60 * 1000 });
  if (b.status !== 0 || !existsSync(join(out, "index.html"))) { rmSync(out, { recursive: true, force: true }); return log(`构建失败，不切换：${(b.stderr || b.stdout || "").slice(-300)}`); }
  const prev = current();
  setCurrent(name);
  writeFileSync(join(BUILDS, "last.json"), JSON.stringify({ stamp, name, prev, at: d.toISOString() }, null, 1));
  log(`已切换：${prev ?? "（无）"} → ${name}（闸门：${tail}）`);
  for (const old of builds().slice(0, -KEEP)) if (old !== current()) rmSync(join(BUILDS, old), { recursive: true, force: true });
}

if (args.includes("--list")) {
  console.log(builds().map((n) => (n === current() ? `* ${n}` : `  ${n}`)).join("\n") || "（没有构建）");
} else if (args.includes("--rollback")) {
  const all = builds();
  const i = all.indexOf(current());
  if (i <= 0) { log("回滚：没有更早的构建"); process.exit(1); }
  setCurrent(all[i - 1]);
  log(`回滚：${all[i]} → ${all[i - 1]}（下一次源码变化且闸门通过时会再出新版）`);
} else if (args.includes("--loop")) {
  log(`常驻构建器启动：每 ${EVERY / 60000} 分钟检查一次`);
  const tick = () => { try { once(null); } catch (e) { log(`出错：${e.message}`); } };
  tick();
  setInterval(tick, EVERY);
} else {
  const fi = args.indexOf("--force");
  once(fi >= 0 ? args[fi + 1] || "手动" : null);
}
