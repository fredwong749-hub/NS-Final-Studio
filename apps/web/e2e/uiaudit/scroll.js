// UIAUDIT 滚动与可达性检查（只读）。由 detect.mjs 的 {scroll:"名"} 步骤在真实滚轮滚动之后注入执行。
// 回答四件事：①能不能滚到底（最后一块内容进入视口）②有没有嵌套多层滚动 ③有没有被裁掉、又滚不出来的内容 ④吸顶 / 固定条有没有盖住内容
(() => {
  const vis = (e) => {
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none";
  };
  const all = [...document.querySelectorAll("body *")].filter(vis);
  const isScroller = (e) => {
    const s = getComputedStyle(e);
    return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 4 && e.clientHeight > 40;
  };
  const scrollers = all.filter(isScroller);
  const docScroll = document.scrollingElement.scrollHeight > innerHeight + 4;
  // 嵌套：一个滚动容器里还有滚动容器（下拉菜单 / 弹层除外）
  const nested = scrollers.filter((e) => {
    for (let p = e.parentElement; p; p = p.parentElement) if (scrollers.includes(p)) return true;
    return false;
  });
  const maxDepth = Math.max(0, ...scrollers.map((e) => {
    let d = 1;
    for (let p = e.parentElement; p; p = p.parentElement) if (scrollers.includes(p)) d++;
    return d;
  })) + (docScroll ? 1 : 0);
  // 还没滚到底的滚动容器（真实滚轮已经滚过之后）
  const notBottom = scrollers.filter((e) => e.scrollTop + e.clientHeight < e.scrollHeight - 8).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]} ${Math.round(e.scrollTop + e.clientHeight)}/${e.scrollHeight}`);
  const docNotBottom = docScroll && scrollY + innerHeight < document.scrollingElement.scrollHeight - 8;
  // 被裁：overflow hidden / clip 且内容比盒子高，又不是图片容器 / 单行省略
  const clipped = all.filter((e) => {
    const s = getComputedStyle(e);
    if (!/(hidden|clip)/.test(s.overflowY)) return false;
    if (e.scrollHeight <= e.clientHeight + 12 || e.clientHeight < 24) return false;
    if (e.querySelector(":scope > img, :scope > video") && e.children.length <= 2) return false;
    if (s.webkitLineClamp && s.webkitLineClamp !== "none") return false;
    return !!e.innerText?.trim();
  }).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]} 内容${e.scrollHeight}>盒${e.clientHeight}`);
  // 吸顶 / 固定条：盖住的视口高度占比（G4 口径 v2，2026-11-01，UIAUDIT 认可 UIMASTER 的更正）
  // 只算"此刻真的贴在上方"的条：fixed 且在视口内的照算；sticky 要 rect.top ≤ 所在滚动区顶 + 自己的 top + 1 才算贴住；互相包含的只算一次。
  // v1 把页面上所有 sticky 都加起来（例：剧本 A/B 7 个镜头标题各 37px 算成 24%，实际同一时刻只贴住 1 个）。
  const scrollTop = (e) => { for (let p = e.parentElement; p; p = p.parentElement) { const s = getComputedStyle(p); if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight) return p.getBoundingClientRect().top; } return 0; };
  const stuck = all.filter((e) => {
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    if (r.height >= innerHeight * 0.6 || r.width <= innerWidth * 0.3 || r.bottom <= 0 || r.top >= innerHeight) return false;
    if (s.position === "fixed") return r.top < innerHeight * 0.5; // 底部固定条另算，不算吸顶
    if (s.position !== "sticky") return false;
    const topVal = parseFloat(s.top);
    if (Number.isNaN(topVal)) return false;
    return r.top <= scrollTop(e) + topVal + 1;
  });
  const fixed = stuck.filter((e) => !stuck.some((o) => o !== e && o.contains(e)));
  const coverPx = fixed.reduce((a, e) => a + e.getBoundingClientRect().height, 0);
  // 视口下半部大片空白（内容被锁在定高框里时常见）
  const probeY = [0.7, 0.8, 0.9].map((f) => Math.round(innerHeight * f));
  const blankRows = probeY.filter((y) => {
    const xs = [0.4, 0.55, 0.7, 0.85].map((f) => Math.round(innerWidth * f));
    return xs.every((x) => {
      const el = document.elementFromPoint(x, y);
      if (!el) return true;
      const r = el.getBoundingClientRect();
      return r.height > innerHeight * 0.5 && r.width > innerWidth * 0.5; // 指到的是大块背景容器，不是内容
    });
  }).length;
  // 页面里最后一块内容（文档顺序最后一个有字 / 有图的叶子，排除固定条）是否已进入视口
  const leaves = all.filter((e) => !e.closest("details:not([open]) > :not(summary)") && !e.closest("[style*='position: fixed'], .ds-toast, .v3-topbar, header") && (e.tagName === "IMG" || [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) && !/(fixed|sticky)/.test(getComputedStyle(e).position));
  const last = leaves[leaves.length - 1];
  const lr = last?.getBoundingClientRect();
  const lastInView = !last || (lr.top < innerHeight && lr.bottom > 0);
  // 定高卡片：一张卡固定高度且内部自带滚动条
  const lockedCards = scrollers.filter((e) => e !== document.scrollingElement && e.clientHeight < innerHeight * 0.85 && /card|panel|sheet|box|insp|detail|body/.test(String(e.className))).map((e) => `${String(e.className).split(" ")[0]} h=${e.clientHeight}`);
  return {
    pageError: /页面出错|Something went wrong/.test(document.body.innerText) ? document.body.innerText.match(/页面出错[^\n]*/)?.[0] ?? 'error' : null,
    vh: innerHeight,
    docScroll,
    scrollers: scrollers.length,
    nested: nested.length,
    depth: maxDepth,
    notBottom: notBottom.slice(0, 6),
    docNotBottom,
    clipped: clipped.slice(0, 8),
    clippedN: clipped.length,
    stickyRule: "v2",
    stickyCoverPx: Math.round(coverPx),
    stickyCoverPct: Math.round((coverPx / innerHeight) * 100),
    blankRows,
    lastInView,
    lastText: last ? (last.innerText || last.alt || last.tagName).trim().slice(0, 30) : null,
    lockedCards: lockedCards.slice(0, 6),
  };
})();
