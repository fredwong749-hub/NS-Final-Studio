// UIAUDIT 内容断言（ITERATION_PROTOCOL H1）：画布 / 剧本页每一镜格子里的首帧图是哪个文件。只读。
// 由 detect.mjs 的 {parity:"名"} 步骤注入；parity_check.mjs 拿它和 GET /api/shots/{id} 对。
(() => {
  const rows = [...document.querySelectorAll("[data-shot]")];
  const seen = new Set();
  const out = [];
  for (const r of rows) {
    const id = r.getAttribute("data-shot");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    // 首帧格：行内第一张宽 ≥ 60px 的图（头像、角标都小于 60）
    const img = [...r.querySelectorAll("img")].find((i) => i.getBoundingClientRect().width >= 60);
    let src = img ? img.currentSrc || img.src : null;
    let file = null;
    if (src) {
      try {
        const u = new URL(src, location.href);
        file = decodeURIComponent(u.searchParams.get("path") || u.searchParams.get("src") || u.pathname);
      } catch { file = src; }
    }
    const label = (r.querySelector("img")?.closest("[class*=frame], [class*=slot], [class*=cell]")?.innerText || "").replace(/\s+/g, " ").slice(0, 40);
    out.push({ id, src: src && src.slice(0, 300), file, label });
  }
  return { hash: location.hash, rows: out };
})();
