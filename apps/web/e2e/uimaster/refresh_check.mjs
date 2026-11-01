// PW-019：组件文件（.tsx）只能导出组件，否则 vite 热更新退化成整页重载 / 大片重挂（项目方看到“刷新闪”）。
// 规则同 eslint react-refresh/only-export-components：.tsx 里 export 的值必须是组件（大写开头的函数 / 常量）；
// 类型（type / interface）不算；小写函数、hook（useXxx）、全大写常量、对象常量 → 违规，要挪到同名 .ts（例如 Foo.helpers.ts）。
// 用法：node refresh_check.mjs            → 列出全部违规
//       node refresh_check.mjs --gate     → 只允许减少：出现基线（refresh_baseline.json）里没有的违规 = 退出 1
//       node refresh_check.mjs --baseline → 把当前违规写成基线（只在挪完一批后收紧用；不许为了过闸门放宽）
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "../../src");
const BASE = join(HERE, "refresh_baseline.json");
const files = [];
const walk = (d) => { for (const n of readdirSync(d, { withFileTypes: true })) { const p = join(d, n.name); if (n.isDirectory()) walk(p); else if (p.endsWith(".tsx")) files.push(p); } };
walk(SRC);
const isComp = (n) => /^[A-Z]/.test(n) && !/^[A-Z0-9_]+$/.test(n); // 大写开头且不是全大写常量
const out = [];
for (const f of files) {
  const s = readFileSync(f, "utf8");
  const rel = relative(SRC, f).replace(/\\/g, "/");
  const names = new Set();
  for (const m of s.matchAll(/^export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z0-9_$]+)/gm)) names.add(m[1]);
  for (const m of s.matchAll(/^export\s*\{([^}]*)\}(?!\s*from)/gm)) for (const part of m[1].split(",")) { const t = part.trim(); if (!t || /^type\s/.test(t)) continue; names.add(t.split(/\s+as\s+/).pop().trim()); }
  // 再导出：export { a, b as c } from "…" 逐个名字算（type 再导出不算）；export * from 整体算一条
  for (const m of s.matchAll(/^export\s*\{([^}]*)\}\s*from\s*["'][^"']+["']/gm)) for (const part of m[1].split(",")) { const t = part.trim(); if (!t || /^type\s/.test(t)) continue; names.add(t.split(/\s+as\s+/).pop().trim()); }
  for (const m of s.matchAll(/^export\s*\*\s*from\s*["']([^"']+)["']/gm)) names.add(`(export * from ${m[1]})`);
  for (const n of names) if (n !== "default" && !isComp(n)) out.push(`${rel}#${n}`);
}
out.sort();
const args = process.argv.slice(2);
if (args.includes("--baseline")) { writeFileSync(BASE, JSON.stringify(out, null, 1)); console.log(`基线已写：${out.length} 条`); process.exit(0); }
if (args.includes("--gate")) {
  const base = existsSync(BASE) ? new Set(JSON.parse(readFileSync(BASE, "utf8"))) : new Set();
  const added = out.filter((x) => !base.has(x));
  if (added.length) { console.log(`组件文件新增了非组件导出（会让热更新整页重载 / 闪屏，PW-019）：\n  ${added.join("\n  ")}\n挪到同名 .ts 再导入。`); process.exit(1); }
  console.log(`refresh_check：违规 ${out.length} 条（基线 ${base.size}，没有新增）`);
  process.exit(0);
}
const byFile = {};
for (const x of out) { const [f, n] = x.split("#"); (byFile[f] ??= []).push(n); }
for (const [f, ns] of Object.entries(byFile)) console.log(`${f}：${ns.join("、")}`);
console.log(`共 ${out.length} 条，${Object.keys(byFile).length} 个文件`);
