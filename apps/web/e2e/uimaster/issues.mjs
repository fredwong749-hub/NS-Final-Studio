// UIMASTER 问题清单小工具。
//   node issues.mjs list [--page=x] [--status=open] [--owner=X] [--kind=re] [--min=2]
//   node issues.mjs fix UM-0001,UM-0002 --iter=N --note="怎么修的"        → status=fixed（等下一次复爬转 verified）
//   node issues.mjs wontfix UM-0003 --iter=N --note="理由"              → 误报 / 按规则不改
//   node issues.mjs assign UM-0004 --owner=ASSETUX
//   node issues.mjs stats                                               → 各页 open 数
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const F = join(dirname(fileURLToPath(import.meta.url)), "../../../../docs/uimaster/issues.json");
const db = JSON.parse(readFileSync(F, "utf8"));
const [cmd, ids, ...rest] = process.argv.slice(2);
const all = [ids, ...rest].filter(Boolean);
const opt = (k) => all.find((a) => a.startsWith(`--${k}=`))?.split("=").slice(1).join("=");
const pick = (s) => new Set(String(s).split(","));
if (cmd === "list") {
  const st = opt("status") ?? "open";
  const rows = db.issues.filter((i) => (st === "all" || i.status === st) && (!opt("page") || i.page === opt("page")) && (!opt("owner") || i.owner === opt("owner")) && (!opt("kind") || new RegExp(opt("kind")).test(i.kind)) && i.sev >= +(opt("min") ?? 0));
  rows.sort((a, b) => b.sev - a.sev || a.page.localeCompare(b.page));
  for (const i of rows) console.log(`${i.id} [${i.status}] s${i.sev} ${i.page} ${i.kind} ${i.owner} | ${i.msg.slice(0, 170)} | ${i.cfgs.join(",")}`);
  console.log(`共 ${rows.length}`);
} else if (cmd === "fix" || cmd === "wontfix") {
  const s = pick(ids);
  for (const i of db.issues) if (s.has(i.id)) { i.status = cmd === "fix" ? "fixed" : "wontfix"; i.history.push({ iter: +(opt("iter") ?? 0), ev: cmd, note: opt("note") ?? "" }); }
  writeFileSync(F, JSON.stringify(db, null, 1));
  console.log(`${cmd} ${s.size}`);
} else if (cmd === "assign") {
  const s = pick(ids);
  for (const i of db.issues) if (s.has(i.id)) i.owner = opt("owner");
  writeFileSync(F, JSON.stringify(db, null, 1));
} else {
  const by = {};
  for (const i of db.issues) { by[i.page] ??= { open: 0, fixed: 0, verified: 0, wontfix: 0 }; by[i.page][i.status]++; }
  console.table(by);
}
