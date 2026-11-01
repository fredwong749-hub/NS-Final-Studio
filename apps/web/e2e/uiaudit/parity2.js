// UIAUDIT 内容断言 v2（r19g 起）：每一镜行里 首帧格 / 尾帧格 / 视频格 各显示哪个文件、标的是第几版、是不是候选。只读。
// 由 detect.mjs 的 {parity2:"名"} 步骤注入；parity2_check.mjs 拿它和 GET /api/episodes/{n} + /api/candidates?ep=n 逐格对。
(() => {
  const fileOf = (src) => {
    if (!src) return null;
    try {
      const u = new URL(src, location.href);
      return decodeURIComponent(u.searchParams.get("path") || u.searchParams.get("src") || u.searchParams.get("url") || u.pathname);
    } catch { return src; }
  };
  const rows = [...document.querySelectorAll(".v3-row[data-shot]")];
  const seen = new Set();
  const out = [];
  for (const r of rows) {
    const id = r.getAttribute("data-shot");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const tiles = [...r.querySelectorAll(".v3-frames .v3-frame")].slice(0, 2).map((t) => {
      const img = t.querySelector("img.live-img");
      return {
        src: img ? (img.currentSrc || img.src || "").slice(0, 300) : null,
        file: img ? fileOf(img.currentSrc || img.src) : null,
        zoom: img?.getAttribute("data-zoom-label") || null,
        tag: (t.querySelector(".v3-tag")?.innerText || "").replace(/\s+/g, " "),
        hint: t.querySelector(".v3-frame-hint")?.innerText || null,
        none: t.querySelector(".v3-frame-none")?.innerText || null,
        cls: t.className,
      };
    });
    const vt = r.querySelector(".v3-vid");
    const v = vt?.querySelector("video");
    out.push({
      id,
      first: tiles[0] || null,
      last: tiles[1] || null,
      video: vt ? { src: v ? fileOf(v.getAttribute("src")) : null, none: vt.querySelector(".v3-frame-none")?.innerText?.replace(/\s+/g, " ") || null, cls: vt.className } : null,
    });
  }
  return { hash: location.hash, n: out.length, rows: out };
})();
