// UIMASTER 爬虫自检：crawl.mjs 里所有注入页面的脚本（evalJs(`…`) 和 const X = `…` 模板）都按模板字符串求值一遍，再当 JS 解析。
// 抓的是转义类 bug：模板里写 \s / \w / \/ 只剩一层反斜杠、"\n" 变成真换行导致字符串断开等（11-01 踩过三次）。
// 用法：node selftest.mjs   退出码 0 = 全部能解析
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "crawl.mjs"), "utf8");
const blocks = [];
const re = /(?:evalJs\(|const [A-Z_]+ = (?:\([a-z]+\) => )?)`([\s\S]*?)`(?=\)|;)/g;
for (let m; (m = re.exec(src)); ) blocks.push({ at: src.slice(0, m.index).split("\n").length, body: m[1] });
let bad = 0;
for (const b of blocks) {
  // ${…} 换成占位值后按模板字符串求值（得到真正发给页面的代码）
  const tpl = b.body.replace(/\$\{[^}]*\}/g, "null");
  let code;
  try {
    code = Function("return `" + tpl + "`")();
  } catch (e) {
    console.log(`第 ${b.at} 行：模板本身求值失败 ${e.message}`);
    bad++;
    continue;
  }
  try {
    Function(code.trim().startsWith("(") || code.trim().startsWith("[") ? "return " + code : code);
  } catch (e) {
    console.log(`第 ${b.at} 行：注入脚本解析失败 ${e.message}\n   ${code.slice(0, 160).replace(/\n/g, "⏎")}`);
    bad++;
  }
}
console.log(`selftest：${blocks.length} 段注入脚本，失败 ${bad}`);
process.exit(bad ? 1 : 0);
