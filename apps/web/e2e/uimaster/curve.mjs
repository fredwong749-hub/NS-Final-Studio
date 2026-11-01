// UIMASTER 各页“未解决问题数”曲线：读 docs/uimaster/runs/iter_NNN.json（每次爬完的 perPage 快照），输出 markdown 表 + 状态汇总。
// 用法：node curve.mjs > docs/uimaster/curve.md
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const DOCS = join(dirname(fileURLToPath(import.meta.url)), "../../../../docs/uimaster");
const runs = readdirSync(join(DOCS, "runs")).filter((f) => /^iter_\d{3}\.json$/.test(f)).sort().map((f) => JSON.parse(readFileSync(join(DOCS, "runs", f), "utf8")));
const pages = [...new Set(runs.flatMap((r) => Object.keys(r.perPage ?? {})))].sort();
const out = ["# UIMASTER 各页未解决问题数（每次爬完的快照）", "", `来源：docs/uimaster/runs/iter_NNN.json；问题库 docs/uimaster/issues.json。`, "", `| 迭代 | 配置 | 总未解决 | 本次新 | 正向断言确认 | ${pages.join(" | ")} |`, `|---|---|---|---|---|${pages.map(() => "---").join("|")}|`];
for (const r of runs) out.push(`| ${r.iter} | ${(r.cfg ?? []).join(" ")} | ${r.open} | ${(r.new ?? []).length} | ${(r.verified ?? []).length} | ${pages.map((p) => r.perPage?.[p] ?? "").join(" | ")} |`);
if (existsSync(join(DOCS, "issues.json"))) {
  const db = JSON.parse(readFileSync(join(DOCS, "issues.json"), "utf8"));
  const by = {};
  for (const i of db.issues) by[i.status] = (by[i.status] || 0) + 1;
  const sev = {};
  for (const i of db.issues.filter((x) => x.status === "open")) sev[`s${i.sev}`] = (sev[`s${i.sev}`] || 0) + 1;
  const own = {};
  for (const i of db.issues.filter((x) => x.status === "open")) own[i.owner] = (own[i.owner] || 0) + 1;
  out.push("", `问题库状态（docs/uimaster/issues.json）：${Object.entries(by).map(([k, v]) => `${k} ${v}`).join(" · ")}`, `未解决按严重度：${Object.entries(sev).sort().reverse().map(([k, v]) => `${k} ${v}`).join(" · ")}`, `未解决按负责人：${Object.entries(own).map(([k, v]) => `${k} ${v}`).join(" · ")}`);
}
console.log(out.join("\n"));
