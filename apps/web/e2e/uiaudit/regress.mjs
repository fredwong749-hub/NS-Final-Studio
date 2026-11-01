// UIAUDIT 功能回退检查（静态部分）：把基线（git 某个提交里的 apps/web/src + data/_archive 归档代码）里
// 界面上能看到的“操作文字”（按钮 / 链接 / 页签 / 菜单 / title / aria-label）抽出来，和当前代码比，列出“基线有、现在没有”的。
// 用法：node regress.mjs [基线提交=HEAD] > regress_static.json
// 只读：git show / 读文件，不改任何东西。动态核对见 flows_regress.json（detect.mjs）。
import { execSync } from "node:child_process";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

import { fileURLToPath } from "node:url";
const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const BASE = process.argv[2] || "HEAD";
const sh = (c) => execSync(c, { cwd: ROOT, encoding: "utf8", maxBuffer: 64 << 20 });

// 操作文字：<button …>文字</button>、<a …>文字</a>、<summary>、Tab/Seg 选项、title= / aria-label=
const RX = [
  /<(button|a|summary|Button|option)\b[^>]*>\s*([^<{}]{2,40}?)\s*</g,
  /\b(title|aria-label|label)=["“]([^"”{}]{2,60})["”]/g,
  /\[\s*["'][\w-]+["']\s*,\s*["']([^"']{2,20})["']/g, // Seg/Tabs 选项 ["key","文字"]
];
const ZH = /[一-鿿]/;
function labels(src) {
  const out = new Set();
  for (const rx of RX) {
    for (const m of src.matchAll(rx)) {
      const t = (m[2] ?? m[1]).replace(/\s+/g, " ").trim();
      if (ZH.test(t) && t.length <= 40) out.add(t);
    }
  }
  return out;
}

function baseFiles() {
  const list = sh(`git ls-tree -r ${BASE} --name-only -- apps/web/src`).split("\n").filter((f) => /\.tsx$/.test(f));
  const files = list.map((f) => ({ f, src: sh(`git show ${BASE}:"${f}"`) }));
  const arch = join(ROOT, "data/_archive/20261031/code/apps_web/src");
  const walk = (d) => readdirSync(d).flatMap((n) => { const p = join(d, n); return statSync(p).isDirectory() ? walk(p) : /\.tsx$/.test(n) ? [p] : []; });
  if (existsSync(arch)) for (const p of walk(arch)) files.push({ f: "archive:" + relative(arch, p).replace(/\\/g, "/"), src: readFileSync(p, "utf8") });
  return files;
}
function curFiles() {
  const d = join(ROOT, "apps/web/src");
  const walk = (x) => readdirSync(x).flatMap((n) => { const p = join(x, n); return statSync(p).isDirectory() ? walk(p) : /\.tsx$/.test(n) ? [p] : []; });
  return walk(d).map((p) => ({ f: relative(ROOT, p).replace(/\\/g, "/"), src: readFileSync(p, "utf8") }));
}

const base = baseFiles();
const cur = curFiles();
const curAll = cur.map((x) => x.src).join("\n");
const removed = {};
for (const { f, src } of base) {
  for (const t of labels(src)) {
    // 当前代码里任何地方还出现这段文字就算还在（宽松：只抓真正消失的）
    const core = t.replace(/[…：:（）()·\s]/g, "").slice(0, 8);
    if (core.length < 2 || curAll.includes(t) || curAll.includes(core)) continue;
    (removed[f] ??= []).push(t);
  }
}
const goneFiles = base.filter((b) => !b.f.startsWith("archive:") && !cur.some((c) => c.f === b.f)).map((b) => b.f);
console.log(JSON.stringify({ base: BASE, baseFiles: base.length, curFiles: cur.length, goneFiles, removedCount: Object.values(removed).reduce((a, x) => a + x.length, 0), removed }, null, 1));
