// UX5（D §4.6 防回潮）：样式统计——theme.css 以外写死的颜色、px 字号、不在档位上的圆角。
// 用法：npm run ds:stats            只打印
//       npm run ds:stats -- --check 超过基线就退出码 1（基线 = UX5 第 4 轮收尾时的数，只许降不许升）
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const BASE = { hex: 14, rgba: 29, pxFont: 125, offRadius: 18 }; // UX5 收尾时（改之前：hex 119 · rgba 53 · 圆角 25 种）

function walk(d, out = []) {
  for (const f of readdirSync(d)) {
    const p = join(d, f);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith(".css")) out.push(p);
  }
  return out;
}
const files = walk(SRC).filter((f) => !f.endsWith("theme.css"));
let hex = 0, rgba = 0, pxFont = 0, offRadius = 0;
const per = [];
for (const f of files) {
  const s = readFileSync(f, "utf8");
  const h = (s.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).length;
  const r = (s.match(/rgba?\(/g) ?? []).length;
  const fp = (s.match(/font-size:\s*\d+(\.\d+)?px/g) ?? []).length;
  const rad = (s.match(/border-radius:\s*(\d+)px/g) ?? []).filter((x) => ![4, 8, 12, 999].includes(Number(x.match(/(\d+)px/)[1]))).length;
  hex += h; rgba += r; pxFont += fp; offRadius += rad;
  if (h || fp || rad) per.push([relative(SRC, f), h, fp, rad]);
}
console.log(`theme.css 以外：写死 hex ${hex} · rgba() ${rgba} · px 字号 ${pxFont} · 不在 4/8/12/999 的圆角 ${offRadius}`);
for (const [f, h, fp, rad] of per.sort((a, b) => b[2] - a[2]).slice(0, 12)) console.log(`  ${f.padEnd(40)} hex ${h} · px 字号 ${fp} · 圆角 ${rad}`);
if (process.argv.includes("--check")) {
  const over = Object.entries({ hex, rgba, pxFont, offRadius }).filter(([k, v]) => v > BASE[k]);
  if (over.length) {
    console.error(`超过基线：${over.map(([k, v]) => `${k} ${v} > ${BASE[k]}`).join("，")}`);
    process.exit(1);
  }
  console.log("没有超过基线");
}
