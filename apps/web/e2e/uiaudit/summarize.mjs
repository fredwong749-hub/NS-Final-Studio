// 汇总 detect 结果：node summarize.mjs r1s_detect.json → 每页 G1–G5 判定（markdown 表）
import { readFileSync } from "node:fs";
const rows = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = ["| 页面 | 尺寸 | G1 滚到底 | G2 单层滚动 | G3 不裁 | G4 吸顶≤15% | G5 无大空白 | 侧栏滚轮 | 细节 |", "|---|---|---|---|---|---|---|---|---|"];
let pass = 0;
for (const r of rows) {
  const m = r.probes.scroll_main, s = r.probes.scroll_side;
  if (!m) { out.push(`| ${r.title} | ${r.id.slice(1, 4)} | 未测 | | | | | | ${r.steps.map((x) => x.error).filter(Boolean).join(";")} |`); continue; }
  if (m.pageError) { out.push(`| ${r.title} | ${m.vh} | ✗ 页面崩了 | | | | | | ${m.pageError} |`); continue; }
  const g1 = m.lastInView && m.notBottom.length === 0 && !m.docNotBottom;
  const g2 = m.nested === 0 && m.lockedCards.length === 0;
  const g3 = m.clippedN === 0;
  const g4 = m.stickyCoverPct <= 15;
  const g5 = m.blankRows === 0 || m.lastInView;
  const ok = g1 && g2 && g3 && g4 && g5;
  if (ok) pass++;
  const d = [
    !g1 && `没到底：${[...m.notBottom, m.docNotBottom ? "document" : "", m.lastInView ? "" : `最后内容「${m.lastText}」不在视口`].filter(Boolean).join("；")}`,
    !g2 && `嵌套 ${m.nested} 层 / 定高卡 ${m.lockedCards.join("、")}`,
    !g3 && `被裁 ${m.clippedN}：${m.clipped.slice(0, 3).join("、")}`,
    !g4 && `吸顶 ${m.stickyCoverPx}px=${m.stickyCoverPct}%`,
    !g5 && `下方空白 ${m.blankRows} 行`,
  ].filter(Boolean).join("<br>");
  const side = s ? (s.notBottom.length ? "✗" : "✓") : "";
  out.push(`| ${r.title} | ${m.vh} | ${g1 ? "✓" : "✗"} | ${g2 ? "✓" : "✗"} | ${g3 ? "✓" : "✗"} | ${g4 ? "✓" : "✗"} | ${g5 ? "✓" : "✗"} | ${side} | ${d} |`);
}
out.push("", `全过：${pass} / ${rows.length}`);
console.log(out.join("\n"));
