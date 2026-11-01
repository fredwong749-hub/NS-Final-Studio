// UIAUDIT 功能回退检查：对照 baseline_features.json，看 detect 收集到的当前界面里每条基线功能还在不在。
// 用法：node regress_check.mjs <rN_detect.json>   → 打印 markdown 表；退出码 1 = 有 P0 回退
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const base = JSON.parse(readFileSync(join(HERE, "baseline_features.json"), "utf8"));
const rows = JSON.parse(readFileSync(process.argv[2], "utf8"));
const pages = {};
const g0 = rows.filter((r) => r.overlay).map((r) => `${r.id}（${r.overlay}）`);
for (const r of rows) for (const [k, v] of Object.entries(r.probes)) if (k.startsWith("collect_")) pages[k.slice(8)] = v;
const all = Object.values(pages).map((p) => p.text + "\n" + p.attrs).join("\n");
const out = ["| 编号 | 区域 | 改版前能做的事 | 期望页面 | 期望页面里有？ | 全站有？ | 判定 | 基线出处 |", "|---|---|---|---|---|---|---|---|"];
let p0 = 0;
for (const f of base.features) {
  const re = new RegExp(f.re);
  const inPages = f.pages.length ? f.pages.filter((p) => pages[p] && re.test(pages[p].text + "\n" + pages[p].attrs)) : [];
  const missingPages = f.pages.filter((p) => pages[p] && !re.test(pages[p].text + "\n" + pages[p].attrs));
  const anywhere = re.test(all);
  let verdict;
  if (!anywhere) { verdict = "**P0 回退：全站没有**"; p0++; }
  else if (f.pages.length && missingPages.length) verdict = `P1 降级：${missingPages.join("、")} 里没有`;
  else verdict = "在";
  out.push(`| ${f.id} | ${f.area} | ${f.name} | ${f.pages.join("、") || "全站"} | ${f.pages.length ? (inPages.join("、") || "—") : "—"} | ${anywhere ? "✓" : "✗"} | ${verdict} | ${f.src} |`);
}
const media = Object.entries(pages).map(([k, v]) => `${k}: img ${v.media.img} · video ${v.media.video} · audio ${v.media.audio}`).join("；");
out.push("", `P0 回退 ${p0} 条 / 基线 ${base.features.length} 条。收集到的页面：${Object.keys(pages).join("、")}`, "", `媒体元素：${media}`);
if (g0.length) out.unshift(`> **本轮作废：G0 白屏 / 报错层** ${g0.join("；")}。白屏页面上的功能会被误判成“没有”，P0 数不可信，修好后重跑。`, "");
console.log(out.join("\n"));
process.exit(p0 ? 1 : 0);
