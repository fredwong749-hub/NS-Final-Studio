// SENTINEL S9 界面 DOM 规则（K-OPS-S02、S04）：由 tools/sentinel/build_ui_flows.py 嵌进 ui_flows.json 的 js 步骤，经 uiaudit/detect.mjs 执行（只读令牌、非 GET 全拦）。
// 返回 {color_capsules, broken_imgs, contradictions}
const rgba = (c) => { c = String(c); let m = c.match(/rgba?\(([^)]+)\)/); if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0] / 255, p[1] / 255, p[2] / 255, p.length > 3 ? p[3] : 1]; } m = c.match(/color\(srgb ([^)]+)\)/); if (m) { const p = m[1].split(/[ \/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; } return null; };   // 兼容 color-mix 算出的 color(srgb …)
const sat = (c) => { const v = rgba(c); if (!v) return 0; const [r, g, b, a] = v; if (a < 0.12) return 0; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2; if (mx === mn) return 0; return (mx - mn) / (1 - Math.abs(2 * l - 1)); };
const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05; };
const SAT = __SAT__, DOT = __DOT__;
const alpha = (c) => { const v = rgba(c); return v ? v[3] : 0; };
const caps = [];
for (const e of document.querySelectorAll("body *")) {
  if (!vis(e)) continue;
  const s = getComputedStyle(e);
  const r = e.getBoundingClientRect();
  if (r.width <= DOT && r.height <= DOT) continue;               // 圆点允许
  const own = [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();
  const t = (e.innerText || "").trim().replace(/\s+/g, " ");
  const bgC = sat(s.backgroundColor) >= SAT && alpha(s.backgroundColor) >= 0.12;
  const bdC = parseFloat(s.borderTopWidth) >= 1 && sat(s.borderTopColor) >= SAT && alpha(s.borderTopColor) >= 0.3;
  const pill = t && t.length <= 14 && r.height <= 34 && r.width <= 260;
  const bar = !t && r.height <= 8 && r.width >= 30 && bgC;           // 彩色进度 / 状态色条
  if (!((pill && (bgC || bdC)) || bar)) continue;
  if (/^[+＋]/.test(t)) continue;                                    // 新建类入口
  if (e.closest("button,[role=button]") && !/待|过|败|错|渲染|过期|通过|驳回|没/.test(t)) continue;   // 主操作按钮的品牌色不算状态色
  const kind = bar ? "色条" : bgC ? "底色胶囊" : "描边胶囊";
  caps.push(`${kind}｜${(t || "").slice(0, 14)}｜${bgC || bar ? s.backgroundColor : s.borderTopColor}`);
}
const broken = [...document.querySelectorAll("img")].filter((i) => vis(i) && i.complete && i.getAttribute("src") && i.naturalWidth === 0).map((i) => i.getAttribute("src").slice(0, 100));
const text = (document.getElementById("root")?.innerText || "").replace(/[ \t]+/g, " ");
const con = [];
for (const m of text.matchAll(/([^\s\d]{1,6})\s*(\d+)\s*\/\s*(\d+)/g)) if (+m[2] > +m[3] && +m[3] > 0) con.push(`“${m[0].trim()}” 分子大于分母`);
const busy = text.match(/(\d+)\s*\/\s*(\d+)\s*忙/);
const rendering = [...document.querySelectorAll("[class*=render],[class*=breath],[data-status=rendering]")].filter(vis).length + (text.match(/渲染中/g) || []).length;
if (busy && +busy[1] === 0 && rendering > 0) con.push(`卡 ${busy[0]} 但页面有 ${rendering} 处“渲染中”`);
const doing = text.match(/在办\s*(\d+)/);
if (busy && doing && +doing[1] > +busy[2]) con.push(`在办 ${doing[1]} 超过卡数 ${busy[2]}`);
if (busy && doing && +busy[1] === 0 && +doing[1] > 0) con.push(`卡 ${busy[0]} 但渲染任务在办 ${doing[1]}`);
const stale = text.match(/过期/g) || [];
const eps = new Set((text.match(/第\s*\d+\s*集|ep\d{2}/gi) || []).map((x) => x.replace(/\s/g, "").toLowerCase()));
if (eps.size >= 3 && stale.length >= eps.size) con.push(`全部 ${eps.size} 集都显示“过期”（${stale.length} 处）`);
const fail = [...text.matchAll(/失败\s*(\d+)/g)].map((m) => +m[1]);
if (new Set(fail).size > 1 && /总览|全季|本季/.test(text.slice(0, 400))) con.push(`同页“失败”计数不一致：${[...new Set(fail)].join(" / ")}`);
return { color_capsules: caps.slice(0, 40), n_color: caps.length, broken_imgs: broken.slice(0, 20), contradictions: con };
