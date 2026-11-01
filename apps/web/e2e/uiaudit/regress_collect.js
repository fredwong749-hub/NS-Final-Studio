// UIAUDIT 功能回退检查（动态部分）：把当前页面所有可见文字 + 控件 title/aria-label/alt + 媒体元素数收集起来，供 regress_check.mjs 对照基线清单。只读。
(() => {
  // 先展开所有折叠段（<details>），只改显示，不触发任何请求；⋯ 菜单由 flows_regress.json 里的点击步骤打开
  document.querySelectorAll("details:not([open])").forEach((d) => { d.open = true; });
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none"; };
  const attrs = [...document.querySelectorAll("[title],[aria-label],[alt],[placeholder]")].filter(vis)
    .map((e) => [e.getAttribute("title"), e.getAttribute("aria-label"), e.getAttribute("alt"), e.getAttribute("placeholder")].filter(Boolean).join(" "));
  const media = {
    img: [...document.querySelectorAll("img")].filter(vis).length,
    video: [...document.querySelectorAll("video")].filter(vis).length,
    audio: document.querySelectorAll("audio").length,
  };
  const CHROME = ".v3-top, .v3-topbar, header, .v3-steps, nav.ac-nav, [class*=TopBar], [class*=topbar]"; const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); const parts = []; for (let n; (n = walker.nextNode()); ) { const p = n.parentElement; if (!p || !n.textContent.trim() || p.closest(CHROME) || !vis(p)) continue; parts.push(n.textContent.trim()); } const chromeText = [...document.querySelectorAll(CHROME)].map((e) => e.innerText).join(" ").slice(0, 2000); return { hash: location.hash, chromeText, text: parts.join("\n").slice(0, 200000), attrs: attrs.join("\n").slice(0, 100000), media };
})();
