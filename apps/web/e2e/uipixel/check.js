// UIPIXEL 页面内检测（只读，不点任何东西）。由 scan.mjs 注入；返回 { issues:[…], clickables:n }。
// 每条 issue：{ kind, sev, msg, val, sel, cls, text, rect }。kind 见 scan.mjs 的 KINDS。
(() => {
  const W = innerWidth, H = innerHeight;
  const TOK = new Set([0, 1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64]); // 设计 token 刻度（--sp-* 4/8/12/16/24/32 + 细线 1/2 + 6/10 给紧凑控件 + 大留白）
  const issues = [];
  const seen = new Set();
  const cs = (e) => getComputedStyle(e);
  const px = (v) => parseFloat(v) || 0;
  const inViewport = (r) => r.bottom > 0 && r.right > 0 && r.top < H && r.left < W;
  const visible = (e) => {
    if (!e.isConnected) return false;
    const dd = e.closest("details:not([open])"); // 收起的 <details> 里除了 summary 都看不见
    if (dd && !e.closest("summary") && e !== dd) return false;
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = cs(e);
    if (s.visibility === "hidden" || s.display === "none" || +s.opacity < 0.05) return false;
    return true;
  };
  const isOverlayOpen = !!document.querySelector("[role=dialog]:not([hidden]), .ds-modal, .v3-overlay-box, .mp-lightbox");
  const sel = (e) => {
    const parts = [];
    let n = e;
    for (let i = 0; n && n !== document.body && i < 4; i++, n = n.parentElement) {
      const c = [...n.classList].filter((x) => !/^(on|active|sel|open|is-|has-)/.test(x)).slice(0, 2).join(".");
      parts.unshift(n.tagName.toLowerCase() + (c ? "." + c : ""));
    }
    return parts.join(" > ");
  };
  const clsChain = (e) => {
    const out = [];
    for (let n = e, i = 0; n && n !== document.body && i < 6; n = n.parentElement, i++) for (const c of n.classList) if (!out.includes(c)) out.push(c);
    return out.slice(0, 8);
  };
  const txt = (e) => (e.innerText || e.getAttribute?.("aria-label") || e.getAttribute?.("title") || "").replace(/\s+/g, " ").trim().slice(0, 40);
  const add = (kind, e, msg, val, sev = 2, key) => {
    const k = kind + "|" + (key ?? sel(e)) + "|" + (typeof val === "string" ? val : "");
    if (seen.has(k)) return;
    seen.add(k);
    const r = e.getBoundingClientRect();
    issues.push({ kind, sev, msg, val, sel: sel(e), cls: clsChain(e), text: txt(e), rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] });
  };
  const all = [...document.body.querySelectorAll("*")].filter((e) => !["SCRIPT", "STYLE", "svg", "path", "g", "BR", "OPTION", "TITLE"].includes(e.tagName) && !e.closest("svg"));
  const vis = all.filter(visible);
  const visSet = new Set(vis);
  const hasOwnText = (e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  const isCtrl = (e) => e.matches("button, a[href], [role=button], [role=tab], [role=menuitem], [role=option], [role=switch], [role=checkbox], summary, select, input:not([type=hidden]), textarea, label[for], [onclick]");

  // ---------------------------------------------------------------- 1 裁切（父容器 overflow 非 visible 或视口）
  const clipAnc = (e) => {
    for (let n = e.parentElement; n && n !== document.documentElement; n = n.parentElement) {
      const s = cs(n);
      if (s.overflowX !== "visible" || s.overflowY !== "visible") return { n, s };
    }
    return null;
  };
  for (const e of vis) {
    if (!(hasOwnText(e) || isCtrl(e) || e.tagName === "IMG" || e.tagName === "VIDEO" || /card|tile|chip|row|item|btn/.test(e.className?.toString?.() ?? ""))) continue;
    const r = e.getBoundingClientRect();
    if (!inViewport(r)) continue;
    const s = cs(e);
    if (s.position === "fixed") { if (r.left < -1 || r.right > W + 1) add("clip", e, "被视口左右边缘裁切", `${Math.round(Math.max(-r.left, r.right - W))}px`, 3); continue; }
    // 水平：部分超出视口（整页没有横向滚动时就是被裁）
    if ((r.left < -1 && r.right > 8) || (r.right > W + 1 && r.left < W - 8)) { add("clip", e, "被视口左右边缘裁切", `${Math.round(Math.max(-r.left, r.right - W))}px`, 3); continue; }
    const a = clipAnc(e);
    if (!a) continue;
    const pr = a.n.getBoundingClientRect();
    const bl = px(a.s.borderLeftWidth), br = px(a.s.borderRightWidth), bt = px(a.s.borderTopWidth), bb = px(a.s.borderBottomWidth);
    const L = pr.left + bl, R = pr.right - br, T = pr.top + bt, B = pr.bottom - bb;
    const hidX = a.s.overflowX === "hidden" || a.s.overflowX === "clip";
    const hidY = a.s.overflowY === "hidden" || a.s.overflowY === "clip";
    // 被横向“截一半”（看得见一部分、但左/右被切掉）——不管容器能不能滚，左边被切都是错（滚动容器左侧不该有内容在 0 以前，除非已滚动）
    const scrolledX = a.n.scrollLeft > 0;
    const cutL = L - r.left, cutR = r.right - R;
    if (r.right > L + 8 && r.left < R - 8) {
      if (cutL > 1.5 && !scrolledX && (hidX || a.n.scrollWidth <= a.n.clientWidth + 1)) add("clip", e, `左边被父容器（${sel(a.n).split(" > ").pop()}）裁掉`, `${Math.round(cutL)}px`, 3);
      else if (cutR > 1.5 && hidX && !(s.textOverflow === "ellipsis") && e.scrollWidth <= e.clientWidth + 1 && a.n.scrollWidth <= a.n.clientWidth + 1) add("clip", e, `右边被父容器（${sel(a.n).split(" > ").pop()}）裁掉`, `${Math.round(cutR)}px`, 2);
    }
    if (hidY && r.bottom > T + 8 && r.top < B - 8) {
      const cutB = r.bottom - B, cutT = T - r.top;
      if ((cutB > 2 || cutT > 2) && a.n.scrollHeight <= a.n.clientHeight + 1 && (hasOwnText(e) || isCtrl(e)) && !/-webkit-box/.test(cs(a.n).display) && cs(a.n).webkitLineClamp === "none")
        add("clip", e, `上下被父容器（${sel(a.n).split(" > ").pop()}）裁掉`, `${Math.round(Math.max(cutB, cutT))}px`, 2);
    }
  }
  if (document.scrollingElement.scrollWidth > W + 1) add("clip", document.body, "整页出现横向滚动", `${document.scrollingElement.scrollWidth - W}px`, 3, "body-hscroll");

  // ---------------------------------------------------------------- 2 文字溢出 / 省略号无 title
  for (const e of vis) {
    if (!hasOwnText(e)) continue;
    const s = cs(e);
    if (e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0 && ["hidden", "clip"].includes(s.overflowX)) {
      const titled = !!(e.closest("[title]") || e.closest("[aria-label]"));
      if (!titled) add("ellipsis", e, s.textOverflow === "ellipsis" ? "文字被省略但没有 title，看不到全文" : "文字被截断（无省略号、无 title）", `${e.scrollWidth}>${e.clientWidth}`, 2);
    } else if (s.overflowX === "visible" && s.whiteSpace === "nowrap" && e.scrollWidth > e.clientWidth + 2 && e.clientWidth > 0 && s.display !== "inline") {
      add("overflow", e, "文字溢出自身盒子（盖到旁边）", `${e.scrollWidth}>${e.clientWidth}`, 2);
    }
  }

  // ---------------------------------------------------------------- 3 同组兄弟左边缘不对齐（内容左边缘，容差 1px）
  const boxed = (e) => { const s = cs(e); return (s.backgroundColor !== "rgba(0, 0, 0, 0)" && s.backgroundColor !== "transparent") || (px(s.borderLeftWidth) > 0 && s.borderLeftStyle !== "none") || s.boxShadow !== "none"; };
  const inkLeft = (e) => {
    // 有底色 / 边框的块（卡片、输入框）看外框；否则看子树里第一个可见文字 / 控件 / 图片的左边缘（::before 图标、summary 三角算进去）
    if (boxed(e)) return e.getBoundingClientRect().left;
    // 大的布局容器（主栏 / 侧栏正文）：比内容框左边线，不钻进去找第一个字（里面居中的大图会让结果偏几 px）
    if (e.getBoundingClientRect().height > 150) { const s0 = cs(e); return e.getBoundingClientRect().left + px(s0.paddingLeft) + px(s0.borderLeftWidth); }
    // 树形缩进（行内 style 写了 padding-left / margin-left，如版本链按层级缩进）是刻意的
    // <details>：左边线 = summary 的三角（::marker 不是文字节点，Range 量不到）
    if (e.tagName === "DETAILS") { const sm = e.querySelector(":scope > summary"); if (sm && cs(sm).display === "list-item") { const ss = cs(sm); return sm.getBoundingClientRect().left + px(ss.paddingLeft) + px(ss.borderLeftWidth); } }
    let best = Infinity;
    const s0 = cs(e), b0 = getComputedStyle(e, "::before"), m0 = e.tagName === "SUMMARY" && s0.display === "list-item";
    if (m0 || (b0.content !== "none" && b0.content !== "normal" && b0.position !== "absolute")) best = e.getBoundingClientRect().left + px(s0.paddingLeft) + px(s0.borderLeftWidth);
    for (const c of e.querySelectorAll("*")) { if (!visSet.has(c)) continue; if (boxed(c) && c.getBoundingClientRect().width > 4) { best = Math.min(best, c.getBoundingClientRect().left); break; } }
    const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n = walker.currentNode, i = 0;
    while (n && i++ < 200) {
      if (n.nodeType === 3 && n.textContent.trim()) {
        const rg = document.createRange(); rg.selectNodeContents(n);
        const rr = rg.getClientRects()[0];
        if (rr && rr.width > 0) best = Math.min(best, rr.left);
      } else if (n.nodeType === 1 && n !== e && (["IMG", "VIDEO", "SELECT", "INPUT", "TEXTAREA", "BUTTON", "CANVAS"].includes(n.tagName)) && visSet.has(n)) {
        best = Math.min(best, n.getBoundingClientRect().left);
      }
      n = walker.nextNode();
    }
    return best;
  };
  for (const p of vis) {
    const ps = cs(p);
    const col = (ps.display.includes("flex") && ps.flexDirection.startsWith("column")) || ((ps.display === "block" || ps.display === "flow-root") && !p.matches("p, span, a, button, label, li, td, th, h1, h2, h3, h4, b, strong, small, em"));
    if (!col || ps.textAlign === "center" || ps.alignItems === "center") continue;
    const kids = [...p.children].filter((k) => visSet.has(k) && cs(k).position !== "absolute" && cs(k).position !== "fixed" && cs(k).float === "none");
    if (kids.length < 2) continue;
    const ks = kids.filter((k) => cs(k).textAlign !== "center" && cs(k).display !== "inline" && cs(k).justifyContent !== "center" && !["IMG", "VIDEO", "HR", "CANVAS"].includes(k.tagName));
    // 只有图 / 视频、没有字的兄弟（满宽缩略图）不参与左对齐比较：满宽图 + 内缩文字是卡片的常规排法
    const mediaBox = (k) => { const r = k.getBoundingClientRect(); if (r.height < 40) return false; if ([...k.querySelectorAll("img, video, canvas")].some((m) => { const mr = m.getBoundingClientRect(); return mr.width * mr.height > 0.5 * r.width * r.height; })) return true; const st = cs(k); return st.aspectRatio !== "auto" && px(st.paddingLeft) === 0; };
    const lefts = ks.filter((k) => !mediaBox(k) && ((k.innerText || "").trim() || k.matches("input, select, textarea, button"))).map((k) => [k, inkLeft(k)]).filter(([, l]) => Number.isFinite(l));
    if (lefts.length < 2) continue;
    const cnt = {};
    for (const [, l] of lefts) cnt[Math.round(l)] = (cnt[Math.round(l)] ?? 0) + 1;
    const mode = +Object.entries(cnt).sort((a, b) => b[1] - a[1])[0][0];
    for (const [k, l] of lefts) {
      const d = l - mode;
      // 1px 容差；16px 以上当成刻意的缩进（列表 / 层级），不报
      if (Math.abs(d) > 1.5 && Math.abs(d) <= 16 && !/^(UL|OL)$/.test(k.tagName) && !k.matches("li") && !/padding-left|margin-left/.test(k.getAttribute("style") || "")) add("align", k, `和同组兄弟左边缘差 ${Math.round(d)}px（同组应左对齐）`, `${Math.round(d)}px`, 2);
    }
  }

  // ---------------------------------------------------------------- 4 标签与控件垂直不居中（同一行）
  for (const p of vis) {
    const ps = cs(p);
    if (!(ps.display.includes("flex") && !ps.flexDirection.startsWith("column")) && !p.matches("label")) continue;
    const kids = [...p.children].filter((k) => visSet.has(k));
    const ctrl = kids.find((k) => k.matches("select, input:not([type=checkbox]):not([type=radio]), textarea, button, .ds-select, [role=combobox]"));
    if (!ctrl || ctrl.getBoundingClientRect().height > 48) continue; // 大卡片（按钮做的卡）不是表单控件，不按标签对齐查
    // 标签 = 同行里纯文字（单行）的兄弟
    const labs = kids.filter((k) => k !== ctrl && !isCtrl(k) && hasOwnText(k) && k.getBoundingClientRect().height < 30 && !k.querySelector("select,input,button"));
    if (p.matches("label") && hasOwnText(p)) {
      // <label>文字<select/></label>：用文字节点的盒子
      for (const n of p.childNodes) if (n.nodeType === 3 && n.textContent.trim()) {
        const rg = document.createRange(); rg.selectNodeContents(n); const rr = rg.getBoundingClientRect(); const cr = ctrl.getBoundingClientRect();
        if (rr.height && rr.right <= cr.left + 2) { const d = (rr.top + rr.bottom) / 2 - (cr.top + cr.bottom) / 2; if (Math.abs(d) > 1.5) add("vcenter", p, `标签文字和控件垂直中线差 ${d.toFixed(1)}px`, `${Math.round(d)}px`, 2); }
      }
    }
    const cr = ctrl.getBoundingClientRect();
    for (const l of labs) {
      const lr = l.getBoundingClientRect();
      if (lr.bottom < cr.top || lr.top > cr.bottom) continue; // 不同行（换行了）
      const d = (lr.top + lr.bottom) / 2 - (cr.top + cr.bottom) / 2;
      if (Math.abs(d) > 1.5) add("vcenter", l, `标签和控件垂直中线差 ${d.toFixed(1)}px`, `${Math.round(d)}px`, 2);
    }
  }

  // ---------------------------------------------------------------- 5 间距不在 token 刻度内（按 class 合并）
  const spaceSeen = new Set();
  for (const e of vis) {
    if (e.closest("[data-uipx-skip]")) continue;
    const s = cs(e);
    const cname = (e.className?.toString?.() ?? "").split(/\s+/).filter(Boolean)[0];
    if (!cname) continue;
    for (const prop of ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "marginTop", "marginBottom", "marginLeft", "marginRight", "rowGap", "columnGap"]) {
      const raw = s[prop];
      if (!raw || raw === "normal" || raw === "auto") continue;
      const v = Math.abs(px(raw));
      if (prop.startsWith("margin") && (s.display === "inline" || v > 64)) continue; // 自动居中 / 大段留白不算
      // flex / grid 里 margin:auto 推到底 / 推到右：算出来是剩余空间，不是写死的值
      if (prop.startsWith("margin") && e.parentElement && /flex|grid/.test(cs(e.parentElement).display) && (v > 16 || (prop === "marginTop" && !e.nextElementSibling) || (prop === "marginLeft" && !e.nextElementSibling))) continue;
      if (prop.endsWith("Gap") && !s.display.includes("flex") && !s.display.includes("grid")) continue;
      if (v % 1 !== 0 && Math.abs(v - Math.round(v)) > 0.05) { /* em 计算出的小数 */ }
      const rv = Math.round(v);
      if (!TOK.has(rv) && rv < 80) {
        const k = cname + "|" + prop.replace(/Top|Bottom|Left|Right/, "") + "|" + rv;
        if (spaceSeen.has(k)) continue;
        spaceSeen.add(k);
        add("spacing", e, `${prop} ${rv}px 不在间距刻度（4/8/12/16/24/32…）`, `${prop}:${rv}`, 1, "." + cname + "|" + prop.replace(/Top|Bottom|Left|Right/, "") + "|" + rv);
      }
    }
  }

  // ---------------------------------------------------------------- 6 同类组件内边距不一致（卡片 / 面板）
  const cardLike = (e) => {
    const s = cs(e);
    const r = e.getBoundingClientRect();
    if (r.width < 80 || r.height < 28) return false;
    const bg = s.backgroundColor !== "rgba(0, 0, 0, 0)" && s.backgroundColor !== "transparent";
    const bd = px(s.borderTopWidth) > 0 && px(s.borderLeftWidth) > 0 && s.borderTopStyle !== "none";
    return (bg || bd) && px(s.borderTopLeftRadius) >= 4 && !isCtrl(e) && !e.matches("img, video, input, textarea, select");
  };
  const cards = vis.filter(cardLike);
  // 同一个父容器下的卡片兄弟：padding 应一致
  const byParent = new Map();
  for (const c of cards) { const p = c.parentElement; if (!byParent.has(p)) byParent.set(p, []); byParent.get(p).push(c); }
  for (const [, cs_] of byParent) {
    if (cs_.length < 2) continue;
    const pads = cs_.map((c) => { const s = cs(c); return `${Math.round(px(s.paddingTop))}/${Math.round(px(s.paddingRight))}/${Math.round(px(s.paddingBottom))}/${Math.round(px(s.paddingLeft))}`; });
    const radii = cs_.map((c) => Math.round(px(cs(c).borderTopLeftRadius)));
    const cnt = {}; for (const p of pads) cnt[p] = (cnt[p] ?? 0) + 1;
    const mode = Object.entries(cnt).sort((a, b) => b[1] - a[1])[0][0];
    cs_.forEach((c, i) => { if (pads[i] !== mode) add("padding", c, `和同组卡片内边距不一致（${pads[i]} vs ${mode}）`, `${pads[i]} vs ${mode}`, 2); });
    const rmode = radii.slice().sort((a, b) => radii.filter((x) => x === b).length - radii.filter((x) => x === a).length)[0];
    cs_.forEach((c, i) => { if (radii[i] !== rmode) add("radius", c, `和同组卡片圆角不一致（${radii[i]} vs ${rmode}）`, `${radii[i]} vs ${rmode}`, 1); });
  }
  // 同一个 class 的卡片：padding 应一致
  const byCls = new Map();
  for (const c of cards) { const k = (c.className?.toString?.() ?? "").split(/\s+/)[0]; if (!k) continue; if (!byCls.has(k)) byCls.set(k, new Map()); const s = cs(c); const p = `${Math.round(px(s.paddingTop))}/${Math.round(px(s.paddingRight))}/${Math.round(px(s.paddingBottom))}/${Math.round(px(s.paddingLeft))}`; if (!byCls.get(k).has(p)) byCls.get(k).set(p, c); }
  for (const [k, m] of byCls) if (m.size > 1) { const [first, ...rest] = [...m.entries()]; for (const [p, c] of rest) add("padding", c, `同类卡片 .${k} 内边距有 ${m.size} 种（${[...m.keys()].join(" · ")}）`, p, 1, "." + k + "|padvar"); }

  // ---------------------------------------------------------------- 6b 同一行卡片：顶边和高度必须一致（±0.5px）；卡片之间的连接符要在同一高度
  const sigOf = (e) => e.tagName + "." + [...e.classList].filter((c) => !/^(on|active|sel|selected|multi|dim|cur|open|has|known|unknown|none|cut|bad|ok|warn)$/.test(c)).sort().join(".");
  const rowAnc = (e) => { for (let n = e.parentElement, i = 0; n && i < 3; n = n.parentElement, i++) { const s = cs(n); if ((s.display.includes("flex") && !s.flexDirection.startsWith("column")) || s.display.includes("grid")) { if (n.children.length > 1) return n; } } return null; };
  const groups = new Map();
  const boxes = vis.filter((e) => { const r = e.getBoundingClientRect(); return r.width >= 40 && r.height >= 40 && boxed(e) && !e.matches("img, video, input, textarea, select, canvas, .ds-skel, [class*=skel]"); });
  for (const c of boxes) {
    const r = c.getBoundingClientRect();
    if (r.width < 40 || r.height < 40 || !inViewport(r)) continue;
    const ra = rowAnc(c); if (!ra) continue;
    const k = sigOf(c);
    void ra;
    if (!groups.has(k)) groups.set(k, new Map([[k, []]]));
    groups.get(k).get(k).push(c);
  }
  for (const [, g] of groups) for (const [, list] of g) {
    if (list.length < 2) continue;
    const rows = [];
    for (const c of list) { const r = c.getBoundingClientRect(); const row = rows.find((x) => r.top < x.b && r.bottom > x.t); if (row) { row.items.push(c); row.t = Math.min(row.t, r.top); row.b = Math.max(row.b, r.bottom); } else rows.push({ t: r.top, b: r.bottom, items: [c] }); }
    for (const row of rows) {
      if (row.items.length < 2) continue;
      const tops = row.items.map((c) => c.getBoundingClientRect().top), hs = row.items.map((c) => c.getBoundingClientRect().height);
      const mode = (a) => { const m = {}; for (const v of a) m[Math.round(v * 2) / 2] = (m[Math.round(v * 2) / 2] ?? 0) + 1; return +Object.entries(m).sort((x, y) => y[1] - x[1])[0][0]; };
      const mt = mode(tops), mh = mode(hs);
      row.items.forEach((c, i) => {
        const dt = tops[i] - mt, dh = hs[i] - mh;
        if (Math.abs(dt) > 0.5 || Math.abs(dh) > 0.5) add("rowcard", c, `同一行卡片${Math.abs(dt) > 0.5 ? `顶边差 ${dt.toFixed(1)}px` : ""}${Math.abs(dt) > 0.5 && Math.abs(dh) > 0.5 ? "、" : ""}${Math.abs(dh) > 0.5 ? `高度差 ${dh.toFixed(1)}px` : ""}（同一行要等高、顶对齐）`, `top${dt.toFixed(1)}/h${dh.toFixed(1)}`, 2);
      });
    }
  }
  // 连接符（卡片之间 1–2 个字的符号）：相对旁边卡片顶边的中线位置要一致
  const glyphs = new Map();
  for (const e of vis) {
    const t = (e.textContent || "").trim();
    if (!t || t.length > 2 || e.children.length || boxed(e) || isCtrl(e)) continue;
    const sib = [...(e.parentElement?.children ?? [])].find((x) => x !== e && boxes.includes(x));
    if (!sib) continue;
    const r = e.getBoundingClientRect(), sr = sib.getBoundingClientRect();
    const k = sigOf(e).replace(/\.(cut|none)/g, "");
    if (!glyphs.has(k)) glyphs.set(k, []);
    glyphs.get(k).push([e, (r.top + r.bottom) / 2 - sr.top]);
  }
  for (const [, list] of glyphs) {
    if (list.length < 2) continue;
    const m = {}; for (const [, v] of list) m[Math.round(v)] = (m[Math.round(v)] ?? 0) + 1;
    const mode = +Object.entries(m).sort((x, y) => y[1] - x[1])[0][0];
    for (const [e, v] of list) if (Math.abs(v - mode) > 1) add("rowcard", e, `卡片之间的连接符「${e.textContent.trim()}」高度和其他连接符差 ${(v - mode).toFixed(1)}px`, `${(v - mode).toFixed(1)}px`, 2);
  }
  // 行内小胶囊 / 标签和旁边文字中线对齐
  for (const e of vis) {
    if (!boxed(e) || isCtrl(e) || !hasOwnText(e) || e.parentElement?.closest("button")) continue; // 按钮里的序号圆点等对整块居中，是设计
    const r = e.getBoundingClientRect();
    if (r.height > 26 || r.width > 240 || !inViewport(r)) continue;
    const p = e.parentElement; if (!p) continue;
    const ps = cs(p);
    if (ps.display.includes("flex") && ps.flexDirection.startsWith("column")) continue;
    const sibs = [...p.children].filter((x) => x !== e && visSet.has(x) && hasOwnText(x) && !boxed(x) && x.children.length === 0 && x.getBoundingClientRect().height < 26);
    for (const x of sibs) {
      const xr = x.getBoundingClientRect();
      const ov = Math.min(xr.bottom, r.bottom) - Math.max(xr.top, r.top);
      if (ov < Math.min(xr.height, r.height) / 2) continue; // 不在同一行
      const d = (r.top + r.bottom) / 2 - (xr.top + xr.bottom) / 2;
      if (Math.abs(d) > 1.5) { add("vcenter", e, `胶囊 / 标签和同行文字中线差 ${d.toFixed(1)}px`, `${d.toFixed(1)}px`, 2); break; }
    }
  }

  // ---------------------------------------------------------------- 7 可点区域 / 指针 / z-index 遮挡
  const clickables = vis.filter((e) => isCtrl(e) && !e.matches("input[type=hidden], input[type=range]") && !e.disabled && e.getAttribute("aria-disabled") !== "true");
  for (const e of clickables) {
    const r = e.getBoundingClientRect();
    if (!inViewport(r)) continue;
    const s = cs(e);
    // 伪元素扩展的点击区
    let ex = 0;
    for (const pe of ["::before", "::after"]) { const p = getComputedStyle(e, pe); if (p.content !== "none" && p.position === "absolute") ex = Math.max(ex, -px(p.top), -px(p.left)); }
    const w = r.width + 2 * ex, h = r.height + 2 * ex;
    const inline = e.matches("a") && e.closest("p, li, .ds-empty p, td") && s.display === "inline";
    if (!inline && !e.matches("input[type=checkbox], input[type=radio]") && (Math.min(w, h) < 24)) add("hit", e, `可点区域只有 ${Math.round(w)}×${Math.round(h)}px（<24 难点中）`, `${Math.round(w)}x${Math.round(h)}`, 3);
    else if (!inline && !e.matches("input[type=checkbox], input[type=radio], input, textarea, select") && Math.min(w, h) < 28) add("hit", e, `可点区域 ${Math.round(w)}×${Math.round(h)}px（<28）`, `${Math.round(w)}x${Math.round(h)}`, 1);
    if (!e.matches("input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=button]):not([type=submit]), textarea, select") && !["pointer", "zoom-in", "grab"].includes(s.cursor)) add("cursor", e, `可点元素鼠标不是手型（cursor:${s.cursor}）`, s.cursor, 2);
    // 只在元素真正露出来的那块里测（还在滚动区外面、没滚到的不算被盖住）
    let vL = Math.max(r.left, 0), vT = Math.max(r.top, 0), vR = Math.min(r.right, W), vB = Math.min(r.bottom, H);
    for (let n = e.parentElement; n && n !== document.documentElement; n = n.parentElement) { const ps = cs(n); if (ps.overflowX !== "visible" || ps.overflowY !== "visible") { const pr = n.getBoundingClientRect(); if (ps.overflowX !== "visible") { vL = Math.max(vL, pr.left); vR = Math.min(vR, pr.right); } if (ps.overflowY !== "visible") { vT = Math.max(vT, pr.top); vB = Math.min(vB, pr.bottom); } } if (ps.position === "fixed") break; }
    const shown = vR - vL > 4 && vB - vT > 4;
    if (shown && (!isOverlayOpen || e.closest("[role=dialog], .ds-modal, .v3-overlay-box, .mp-lightbox"))) {
      const cx = (vL + vR) / 2, cy = (vT + vB) / 2;
      const hit = document.elementFromPoint(cx, cy);
      if (hit && hit !== e && !e.contains(hit) && !hit.contains(e) && cs(hit).pointerEvents !== "none") {
        const hl = hit.closest("[role=dialog], [role=menu], [role=listbox], [role=tooltip], .ds-pop, .pop, .menu, .toast, .ds-toast");
        // 被吸顶 / 固定条盖住的，是正文滚到它下面去了（滚回来就看得到），不算 z-index 遮挡
        let stuck = false; for (let n = hit; n && n !== document.body; n = n.parentElement) { const p = cs(n).position; if ((p === "sticky" || p === "fixed") && !n.contains(e)) { stuck = true; break; } }
        if (stuck) continue;
        if (!hl) add("zindex", e, `被 ${sel(hit).split(" > ").slice(-2).join(" > ")} 盖住，点不到`, sel(hit).split(" > ").pop(), 3);
      }
    }
  }

  // ---------------------------------------------------------------- 8 隐藏元素仍占位 / 空元素撑出空白
  for (const e of all) {
    if (!e.isConnected) continue;
    const s = cs(e);
    if (s.display === "none" || s.position === "absolute" || s.position === "fixed") continue;
    const r = e.getBoundingClientRect();
    if (r.width * r.height < 16 || !inViewport(r)) continue;
    if ((s.visibility === "hidden" || +s.opacity === 0) && !e.closest("[aria-hidden=true] video") && s.transitionDuration === "0s" && !e.matches("input[type=file], input[type=checkbox], input[type=radio]") && !(e.parentElement && cs(e.parentElement).visibility === "hidden" && e.parentElement.getBoundingClientRect().width > 0)) {
      add("ghost", e, `隐藏了但仍占位 ${Math.round(r.width)}×${Math.round(r.height)}`, `${Math.round(r.width)}x${Math.round(r.height)}`, 2);
      continue;
    }
    if (e.children.length === 0 && !e.textContent.trim() && !["IMG", "VIDEO", "CANVAS", "INPUT", "TEXTAREA", "SELECT", "HR", "IFRAME", "AUDIO", "I", "svg"].includes(e.tagName) && s.backgroundColor === "rgba(0, 0, 0, 0)" && s.backgroundImage === "none" && px(s.borderTopWidth) === 0 && px(s.borderBottomWidth) === 0 && px(s.borderLeftWidth) === 0 && r.height >= 8 && r.width >= 8 && !e.matches("[role=progressbar], [class*=spacer], [class*=grow], [class*=skel]") && cs(e.parentElement).display !== "grid" && s.flexGrow === "0")
      add("ghost", e, `空元素撑出 ${Math.round(r.width)}×${Math.round(r.height)} 的空白`, `${Math.round(r.height)}h`, 1);
  }

  // ---------------------------------------------------------------- 9 滚动容器嵌套
  const scrollers = vis.filter((e) => { const s = cs(e); return e.tagName !== "TEXTAREA" && e.tagName !== "SELECT" && ["auto", "scroll"].includes(s.overflowY) && e.scrollHeight > e.clientHeight + 2 && e.clientHeight > 40; });
  for (const e of scrollers) {
    for (let n = e.parentElement; n && n !== document.body; n = n.parentElement) {
      if (scrollers.includes(n)) { add("nestscroll", e, `滚动区套在另一个滚动区（${sel(n).split(" > ").pop()}）里`, sel(n).split(" > ").pop(), 2); break; }
    }
  }

  // ---------------------------------------------------------------- 9b 吸顶条（G4）：滚动区的 scroll-padding-top 要 ≥ 吸顶条高度，否则键盘聚焦 / scrollIntoView 会把控件藏到条下面
  for (const e of vis) {
    const s = cs(e);
    if (s.position !== "sticky" || px(s.top) > 8) continue;
    const r = e.getBoundingClientRect();
    if (r.height < 16 || r.width < 200 || r.width < r.height * 2) continue; // 只查横向的吸顶条（竖着的侧栏不算）
    let sc = e.parentElement;
    while (sc && sc !== document.documentElement && !/(auto|scroll)/.test(cs(sc).overflowY)) sc = sc.parentElement;
    if (!sc) continue;
    const spt = cs(sc).scrollPaddingTop;
    const need = r.height + Math.min(0, px(s.top)); // top 为负时露出来的高度更小
    const have = spt === "auto" ? 0 : px(spt);
    if (have + 1 < need) add("sticky", e, `吸顶条高 ${Math.round(need)}px，但滚动区 scroll-padding-top 只有 ${Math.round(have)}px：Tab 聚焦 / 跳转会把控件藏到条下面（G4）`, `${Math.round(have)}<${Math.round(need)}`, 2);
  }

  // ---------------------------------------------------------------- 10 文案：内部路径 / 内部词 / 自相矛盾的时间
  const RE_PATH = /(?:[\w.-]+\/)+[\w.-]+\.(?:png|jpe?g|webp|json|mp4|mov|wav|mp3|safetensors|txt|yaml|md)\b|\b[\w-]+\.(?:png|jpe?g|webp|json|safetensors|yaml)\b/i;
  const RE_INTERNAL = /外部任务|\b(?:sk|ch|lk|it|sc)_[a-z0-9]+(?:_[a-z0-9]+)+\b|\bundefined\b|\bnull\b|\bNaN\b|\[object Object\]|\b[a-z]+_[a-z]+_[a-z_]+\b/;
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    const t = n.textContent;
    if (!t.trim()) continue;
    const e = n.parentElement;
    if (!e || !visSet.has(e) || e.closest("textarea, code, pre, [contenteditable], .prompt, [class*=prompt], [class*=mono], kbd, [data-uipx-skip]")) continue;
    const m1 = t.match(RE_PATH);
    if (m1) add("copy", e, `界面直接显示文件路径 / 文件名「${m1[0]}」`, m1[0], 3);
    const m2 = t.match(RE_INTERNAL);
    if (m2) add("copy", e, `界面出现内部词「${m2[0]}」`, m2[0], 3);
  }
  const unit = (n, u) => (/分/.test(u) ? n * 60 : /时/.test(u) ? n * 3600 : n);
  for (const e of vis) {
    if (!hasOwnText(e) && e.children.length > 3) continue;
    const t = e.innerText || "";
    const m = t.match(/已\s*(\d+(?:\.\d+)?)\s*(秒|分钟|分|小时)[^\n]{0,8}?预计约?\s*(\d+(?:\.\d+)?)\s*(秒|分钟|分|小时)/);
    if (m && unit(+m[1], m[2]) > unit(+m[3], m[4]) * 1.05 && e.children.length < 6) add("logic", e, `进度时间自相矛盾：「${m[0]}」（已用时超过预计）`, m[0], 3);
  }
  // ---------------------------------------------------------------- 11 重叠：两个可见的文字 / 可点元素互相压住（>2px）
  // 文字用真实字形盒（Range 每行一个矩形），控件用元素盒；各自先按裁切祖先（overflow 非 visible）裁掉看不见的部分。
  // 不算：祖先 / 后代关系；不在同一层（一个在弹层 / 抽屉 / 固定 / 粘性条里，另一个不在）；白名单里的刻意叠放角标。
  const OVERLAP_OK = ["[data-overlay-ok]", ".ds-tag.on-media.dot", ".v3-play", ".mp-wave", ".sea-last", "[role=tooltip]", ".ds-skel"];
  const LAYER = ".ds-tilebar-menu, [role=dialog], [role=menu], [role=listbox], [role=tooltip], .ds-modal-wrap, .ds-drawer, .ds-scrim, .ds-pop, .ds-toast, .ed-toast, .ds-undo-host, .toast, .v3-overlay-box, .mp-lightbox, .v3-vbox, .v3-pop, .menu, .popover";
  const layerOf = (e) => {
    for (let n = e; n && n !== document.body; n = n.parentElement) {
      if (n.matches(LAYER)) return n;
      const p = cs(n).position;
      if (p === "fixed" || p === "sticky") return n;
    }
    return document.body;
  };
  const clipRect = (e, r, self = false) => {
    let L = Math.max(r.left, 0), T = Math.max(r.top, 0), R = Math.min(r.right, W), B = Math.min(r.bottom, H);
    // 文字：元素自己 overflow 非 visible（多行省略 line-clamp、滚动框）时，被藏起来的行不算
    for (let n = self ? e : e.parentElement; n && n !== document.documentElement; n = n.parentElement) {
      const s = cs(n);
      if (s.overflowX !== "visible" || s.overflowY !== "visible") {
        const pr = n.getBoundingClientRect();
        if (s.overflowX !== "visible") { L = Math.max(L, pr.left); R = Math.min(R, pr.right); }
        if (s.overflowY !== "visible") { T = Math.max(T, pr.top); B = Math.min(B, pr.bottom); }
      }
      if (s.position === "fixed") break;
    }
    return R - L > 1 && B - T > 1 ? { l: L, t: T, r: R, b: B } : null;
  };
  const CTRL_SEL = "button, a[href], [role=button], [role=tab], [role=menuitem], summary, select, input:not([type=hidden]), textarea";
  const boxesO = [];
  const ctrlOf = (n) => n.closest?.(CTRL_SEL);
  for (const e of vis) {
    if (e.closest("#uipx-mark")) continue;
    if (e.matches(CTRL_SEL)) {
      const c = clipRect(e, e.getBoundingClientRect());
      if (c) boxesO.push({ e, owner: e, ...c, kind: "ctrl" });
      continue;
    }
    if (ctrlOf(e)) continue; // 控件里的文字随控件算
    if (e.matches("details:not([open])")) continue; // 收起的 details 自己的文字（summary 以外）看不见
    for (const n of e.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const rr of rg.getClientRects()) {
        if (rr.width < 2 || rr.height < 2) continue;
        const c = clipRect(e, rr, true);
        if (c) boxesO.push({ e, owner: e, ...c, kind: "text" });
      }
    }
  }
  const okLayered = (e) => OVERLAP_OK.some((q) => e.closest(q));
  const grid = new Map(), G = 64;
  boxesO.forEach((b, i) => { for (let gx = Math.floor(b.l / G); gx <= Math.floor(b.r / G); gx++) for (let gy = Math.floor(b.t / G); gy <= Math.floor(b.b / G); gy++) { const k = gx + "," + gy; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i); } });
  const donePair = new Set();
  const layerCache = new Map();
  const lay = (e) => { if (!layerCache.has(e)) layerCache.set(e, layerOf(e)); return layerCache.get(e); };
  for (const [, idx] of grid) for (let x = 0; x < idx.length; x++) for (let y = x + 1; y < idx.length; y++) {
    const a = boxesO[idx[x]], b = boxesO[idx[y]];
    if (a.owner === b.owner) continue;
    const ox = Math.min(a.r, b.r) - Math.max(a.l, b.l), oy = Math.min(a.b, b.b) - Math.max(a.t, b.t);
    if (ox <= 2 || oy <= 2) continue;
    if (a.owner.contains(b.owner) || b.owner.contains(a.owner)) continue;
    if (lay(a.owner) !== lay(b.owner)) continue;
    if (okLayered(a.owner) || okLayered(b.owner)) continue;
    const pk = [idx[x], idx[y]].join("|");
    const ek = sel(a.owner) + "‖" + sel(b.owner);
    if (donePair.has(ek)) continue;
    donePair.add(ek); void pk;
    // 报在“后画的那个”上（DOM 顺序靠后的），说明里写被压住的是谁
    const [top, under] = a.owner.compareDocumentPosition(b.owner) & Node.DOCUMENT_POSITION_FOLLOWING ? [b, a] : [a, b];
    const tn = (txt(under.owner) || under.owner.tagName.toLowerCase()).slice(0, 16);
    add("overlap", top.owner, `和「${tn}」（${sel(under.owner).split(" > ").slice(-1)[0]}）重叠 ${Math.round(ox)}×${Math.round(oy)}px，字 / 按钮互相压住`, `${Math.round(ox)}x${Math.round(oy)}`, 3, sel(top.owner) + "‖" + sel(under.owner));
  }

  return { issues, clickables: clickables.length, nodes: vis.length, url: location.hash };
})();
