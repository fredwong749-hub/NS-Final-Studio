// UIAUDIT 内容断言 v2：画布每一镜的 首帧 / 尾帧 / 视频 格 = 后端这一镜（逐格、逐文件、逐版号）。
// 期望值（与 ReviewRow.tsx FrameTile / VideoTile 的显示顺序一致）：
//   首帧：接口 first_frame（版号 first_frame_take）> 最新合格候选（/api/candidates，active=null 时；标“候选”）> 草图兜底（不判，记“草图”）> 未出
//   尾帧：接口 last_frame_target（版号 last_frame_take）> “参考，非尾帧”提示（不判）> 最新合格候选 > 未出
//   视频：接口 video
// 另判：同一集里两镜显示同一文件 = P0。
// 用法：node parity2_check.mjs <rN_detect.json>   退出码 1 = 有不一致
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "../../../../");
const API = "http://127.0.0.1:8800";
const tokFile = join(ROOT, "data/auth/viewer_token");
const H = existsSync(tokFile) ? { "x-ns-viewer-token": readFileSync(tokFile, "utf8").trim() } : {};
const rows = JSON.parse(readFileSync(process.argv[2], "utf8"));
const norm = (s) => (s || "").replace(/\\/g, "/").replace(/^.*?\/files\//, "").replace(/^\/+/, "").replace(/\?.*$/, "").toLowerCase();
const get = async (p) => (await fetch(API + p, { headers: H })).json();
const passed = (t) => t.ok !== false && !t.bad;
const candFor = (c, id, st) => {
  const s = c?.[id]?.[st];
  if (!s || s.active != null || !s.takes?.length) return null;
  return [...s.takes].reverse().find(passed) ?? null;
};
const out = ["| 页面 | 镜 | 格 | 界面显示 | 后端期望 | 判定 |", "|---|---|---|---|---|---|"];
let bad = 0, ok = 0, untested = 0;
for (const r of rows) for (const [k, v] of Object.entries(r.probes)) {
  if (!k.startsWith("parity2_")) continue;
  const page = k.slice(8);
  if (r.overlay || !v?.rows) { out.push(`| ${page} | — | — | 白屏 / 报错层 / 无数据 | — | 未测 |`); untested++; continue; }
  const ep = +(/#ep(\d+)/.exec(v.hash)?.[1] ?? 0);
  if (!ep) { out.push(`| ${page} | — | — | hash=${v.hash} 认不出集号 | — | 未测 |`); untested++; continue; }
  const d = await get(`/api/episodes/${ep}`);
  const cands = (await get(`/api/candidates?ep=${ep}`)).shots ?? {};
  const byId = new Map((d.shots ?? []).map((s) => [s.id, s]));
  const apiIds = (d.shots ?? []).map((s) => s.id);
  const uiIds = v.rows.map((x) => x.id);
  const missing = apiIds.filter((x) => !uiIds.includes(x)), extra = uiIds.filter((x) => !apiIds.includes(x));
  if (missing.length || extra.length) { bad++; out.push(`| ${page} | — | 镜头列表 | ${uiIds.length} 行 | 接口 ${apiIds.length} 镜 | **✗ 少 ${missing.join("、") || "—"}，多 ${extra.join("、") || "—"}** |`); }
  else { ok++; out.push(`| ${page} | — | 镜头列表 | ${uiIds.length} 行 | 接口 ${apiIds.length} 镜 | ✓ |`); }
  const seen = { first: new Map(), last: new Map(), video: new Map() };
  for (const x of v.rows) {
    const s = byId.get(x.id);
    if (!s) continue;
    for (const st of ["first", "last"]) {
      const t = x[st];
      const stage = st === "first" ? "image" : "last";
      const apiUrl = st === "first" ? s.first_frame : s.last_frame_target;
      const apiTake = st === "first" ? s.first_frame_take : s.last_frame_take;
      let exp, expTake = null, expCand = false, skip = null;
      if (apiUrl) { exp = norm(apiUrl); expTake = apiTake; }
      else if (st === "last" && t?.hint && /参考/.test(t.hint)) skip = "参考，非尾帧（不判）";
      else { const c = candFor(cands, x.id, stage); if (c) { exp = norm(c.url); expTake = c.n; expCand = true; } }
      const got = norm(t?.file);
      if (t?.hint && /草图/.test(t.hint) && !exp) skip = "草图·还没进版本（不判）";
      // r22：候选还没读回来时界面写“读取中…”（UIRSI r37），记“读取中”不判；写“未出”而后端有 = 不一致
      if (!got && /读取中/.test((t?.none || "") + (t?.tag || "") + (t?.hint || ""))) skip = "读取中（不判；不是“未出”）";
      if (skip) { untested++; out.push(`| ${page} | ${x.id} | ${st === "first" ? "首帧" : "尾帧"} | ${got.slice(-60) || "—"} | — | ${skip} |`); continue; }
      const label = t?.zoom || t?.tag || t?.none || "";
      const takeShown = /#(\d+)/.exec(t?.zoom || t?.tag || "")?.[1];
      let verdict;
      if (!exp && !got) verdict = "✓（都没有）";
      else if (!exp && got) verdict = "**✗ 后端没有，界面有图**";
      else if (exp && !got) verdict = "**✗ 后端有，界面没显示**";
      else if (!(got.endsWith(exp) || exp.endsWith(got))) verdict = "**✗ 文件不同**";
      else if (expTake != null && takeShown != null && +takeShown !== +expTake) verdict = `**✗ 版号不同（界面 #${takeShown}）**`;
      else if (expCand && !/候选/.test(label)) verdict = "**✗ 是候选但没标“候选”**";
      else verdict = "✓";
      if (got) seen[st].set(got, [...(seen[st].get(got) ?? []), x.id]);
      verdict.startsWith("✓") ? ok++ : bad++;
      out.push(`| ${page} | ${x.id} | ${st === "first" ? "首帧" : "尾帧"} | ${got.slice(-60) || "（未出）"} ${takeShown ? "#" + takeShown : ""} | ${exp ? exp.slice(-60) + (expTake != null ? " #" + expTake : "") + (expCand ? "（候选）" : "") : "（无）"} | ${verdict} |`);
    }
    const gotV = norm(x.video?.src), expV = norm(s.video);
    let vv;
    if (!expV && !gotV) vv = "✓（都没有）";
    else if (!gotV) vv = "**✗ 后端有视频，界面没显示**";
    else if (!expV) vv = "**✗ 后端没有，界面有视频**";
    else vv = gotV.endsWith(expV) || expV.endsWith(gotV) ? "✓" : "**✗ 文件不同**";
    if (gotV) seen.video.set(gotV, [...(seen.video.get(gotV) ?? []), x.id]);
    vv.startsWith("✓") ? ok++ : bad++;
    out.push(`| ${page} | ${x.id} | 视频 | ${gotV.slice(-60) || "（无）"} | ${expV.slice(-60) || "（无）"} | ${vv} |`);
  }
  for (const [st, m] of Object.entries(seen)) for (const [f, ids] of m) if (ids.length > 1) { bad++; out.push(`| ${page} | ${ids.join("、")} | ${st} | ${f.slice(-60)} | 各镜应不同 | **✗ 多镜同一文件** |`); }
}
out.push("", `内容断言 v2：一致 ${ok} 格，不一致 ${bad}，未测 ${untested}。不一致 = P0（界面内容 ≠ 后端这一镜）。`);
console.log(out.join("\n"));
process.exit(bad ? 1 : 0);
