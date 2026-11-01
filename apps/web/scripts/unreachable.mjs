// UIRSI 重构：从 src/main.tsx 出发沿 import / import() / CSS import 走一遍，列出 src 里构建不到的文件（候选归档）。
// 用法：node scripts/unreachable.mjs [--json]
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src");
const EXT = ["", ".ts", ".tsx", ".css", "/index.ts", "/index.tsx"];
const RE = /(?:import|export)\s[^'"]*?from\s*["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)|import\s+["']([^"']+)["']/g;

function resolveFrom(file, spec) {
  if (!spec.startsWith(".")) return null;
  const base = resolve(dirname(file), spec);
  for (const e of EXT) if (existsSync(base + e) && statSync(base + e).isFile()) return resolve(base + e);
  return null;
}
const seen = new Set();
const stack = [join(SRC, "main.tsx")];
while (stack.length) {
  const f = stack.pop();
  if (seen.has(f)) continue;
  seen.add(f);
  if (!/\.(tsx?|css)$/.test(f)) continue;
  const txt = readFileSync(f, "utf8");
  if (f.endsWith(".css")) {
    for (const m of txt.matchAll(/@import\s+["']([^"']+)["']/g)) {
      const r = resolveFrom(f, m[1]);
      if (r) stack.push(r);
    }
    continue;
  }
  for (const m of txt.matchAll(RE)) {
    const r = resolveFrom(f, m[1] ?? m[2] ?? m[3]);
    if (r) stack.push(r);
  }
}
const all = [];
(function walk(d) {
  for (const n of readdirSync(d)) {
    const p = join(d, n);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(tsx?|css)$/.test(n) && !n.endsWith(".d.ts")) all.push(p);
  }
})(SRC);
const dead = all.filter((f) => !seen.has(f)).map((f) => relative(SRC, f).replaceAll("\\", "/")).sort();
if (process.argv.includes("--json")) console.log(JSON.stringify(dead));
else console.log(`可达 ${seen.size} · 全部 ${all.length} · 构建不到 ${dead.length}\n${dead.join("\n")}`);
