// UIAUDIT 内容断言：每一镜格子里的首帧 ① 互不相同 ② 属于这一镜（文件名 / 路径里带这一镜的 id，或等于 /api/shots/{id} 里某个 image take 的文件）。
// 用法：node parity_check.mjs <rN_detect.json>   退出码 1 = 有不一致（P0：界面内容 ≠ 后端这一镜）
// 只读：GET /api/shots/{id}（带本机只读查看令牌）。DATAALIGN 的 tools/qa/data_parity.py 交付后，这里改成调用它，保留本脚本做界面侧取样。
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "../../../../");
const API = "http://127.0.0.1:8800";
const tokFile = join(ROOT, "data/auth/viewer_token");
const H = existsSync(tokFile) ? { "x-ns-viewer-token": readFileSync(tokFile, "utf8").trim() } : {};
const rows = JSON.parse(readFileSync(process.argv[2], "utf8"));
const samples = [];
for (const r of rows) for (const [k, v] of Object.entries(r.probes)) if (k.startsWith("parity_")) samples.push({ page: k.slice(7), flow: r.id, overlay: r.overlay, ...v });

const norm = (s) => (s || "").replace(/\\/g, "/").replace(/^\/files\//, "").replace(/\?.*$/, "").toLowerCase();
const shotKeys = (id) => {
  const m = /^ep(\d+)-S(\d+)$/i.exec(id);
  if (!m) return [id.toLowerCase()];
  const ep = m[1].padStart(2, "0");
  return [`ep${ep}-s${m[2]}_`, `ep${ep}-s${m[2]}.`, `ep${ep}/s${m[2]}/`, `ep${ep}-s${m[2]}/`].map((x) => x.toLowerCase());
};
const out = ["| 页面 | 镜 | 格子里的首帧文件 | 属于这一镜？ | 与别镜重复？ |", "|---|---|---|---|---|"];
let bad = 0, checked = 0, untested = 0;
for (const s of samples) {
  if (s.overlay) { out.push(`| ${s.page} | — | 白屏 / 报错层，未测 | — | — |`); untested++; continue; }
  const byFile = new Map();
  for (const r of s.rows) if (r.file) byFile.set(norm(r.file), [...(byFile.get(norm(r.file)) ?? []), r.id]);
  for (const r of s.rows) {
    if (!r.file) { out.push(`| ${s.page} | ${r.id} | （没有图） | 未测 | — |`); untested++; continue; }
    let own = shotKeys(r.id).some((k) => norm(r.file).includes(k));
    let detail = "";
    if (!own) {
      try {
        const d = await (await fetch(`${API}/api/shots/${r.id}`, { headers: H })).json();
        const files = (d.takes?.takes ?? []).filter((t) => t.stage === "image").map((t) => norm(t.file || t.url));
        own = files.some((f) => f && (norm(r.file).endsWith(f) || f.endsWith(norm(r.file))));
        detail = own ? "（= take）" : `（这一镜的 take：${files.slice(0, 2).join("、") || "无"}）`;
      } catch (e) { detail = `（接口读不到：${e.message}）`; }
    }
    const dup = (byFile.get(norm(r.file)) ?? []).filter((x) => x !== r.id);
    checked++;
    if (!own || dup.length) bad++;
    out.push(`| ${s.page} | ${r.id} | ${norm(r.file).slice(-70)} | ${own ? "✓" : "**✗ 不是这一镜的图**"}${detail} | ${dup.length ? `**✗ 和 ${dup.join("、")} 同一张**` : "✓"} |`);
  }
}
out.push("", `内容断言：核对 ${checked} 格，不一致 ${bad}，未测 ${untested}。不一致 = P0（界面内容 ≠ 后端这一镜）。`);
console.log(out.join("\n"));
process.exit(bad ? 1 : 0);
