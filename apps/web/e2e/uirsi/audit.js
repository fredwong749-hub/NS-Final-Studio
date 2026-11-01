// UIRSI 排版自动检查（RUBRIC R14–R17 的客观分数）：在页面里按计算样式统计，只读。
// 由 shoot.mjs 在每张截图后注入执行，返回一个 JSON 对象。
(() => {
  const root = getComputedStyle(document.documentElement);
  const FS = new Set([12, 13, 14, 16, 20]);              // --fs-xs/sm/m/lg/xl
  const SP_OK = (v) => v === 0 || v === 1 || v === 2 || v % 4 === 0; // --sp-* 是 4 的网格；1–2px 细线 / 微调放行
  const parseRgb = (s) => {
    // color-mix() 算出来是 color(srgb r g b / a)，分量 0–1
    const c = /color\(srgb ([^)]+)\)/.exec(s);
    if (c) {
      const q = c[1].split(/[ /]+/).filter(Boolean).map(Number);
      return { r: q[0] * 255, g: q[1] * 255, b: q[2] * 255, a: q.length > 3 ? q[3] : 1 };
    }
    const m = /rgba?\(([^)]+)\)/.exec(s);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const tokColors = new Set();
  const probe = document.createElement("i");
  document.body.appendChild(probe);
  for (const sh of document.styleSheets) {
    let rules;
    try { rules = sh.cssRules; } catch { continue; }
    for (const r of rules) {
      if (!r.style) continue;
      for (const name of r.style) {
        if (name.startsWith("--c-")) {
          probe.style.color = `var(${name})`;
          tokColors.add(getComputedStyle(probe).color);
        }
      }
    }
  }
  const secondary = new Set(["--c-text-2", "--c-text-3"].map((n) => { probe.style.color = `var(${n})`; return getComputedStyle(probe).color; }));
  const shadowTok = new Set(["none"]);
  for (const n of ["--sh-1", "--sh-pop", "--sh-float", "--sh-soft"]) { probe.style.boxShadow = `var(${n})`; shadowTok.add(getComputedStyle(probe).boxShadow); }
  probe.remove();

  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const blend = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const bgOf = (el) => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parseRgb(getComputedStyle(e).backgroundColor);
      if (getComputedStyle(e).backgroundImage !== "none" && e !== el) return null; // 图 / 渐变上的字不算
      if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; }
    }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    const bodyBg = parseRgb(getComputedStyle(document.body).backgroundColor);
    if (bodyBg && bodyBg.a > 0) bg = bodyBg;
    for (const c of stack.reverse()) bg = blend(c, bg);
    return bg;
  };
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05;
  };
  // 叠在图 / 视频上的角标（底色是画面，算不出对比度）一并跳过
  // 通用：绝对定位、且同一容器里有图 / 视频的文字（版本缩略图上的 #N、头像占位字）也算叠在画面上
  const onMedia = (el) => {
    for (let e = el, i = 0; e && i < 2; e = e.parentElement, i++) {
      if (getComputedStyle(e).position === "absolute" && e.parentElement?.querySelector(":scope > img, :scope > video, :scope img")) return true;
    }
    return false;
  };
  const media = (el) => !!el.closest("video, img, svg, canvas, .v3-media, .cut-video, .ns-raw, pre, code, .v3-frame, .v3-vid, .v3-clip, .ac-thumb, [class*=thumb], .v3-char") || onMedia(el);

  const out = { textEls: 0, fontOff: 0, fontOffSizes: {}, spaceOff: 0, spaceOffVals: {}, colorOff: 0, shadowOff: 0,
                overflow: 0, clipNoTitle: 0, orphan: 0, contrastFail: 0, contrastSecFail: 0, lineTight: 0, samples: {} };
  const sample = (k, el, note) => { (out.samples[k] ??= []).length < 5 && out.samples[k].push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]} ${note}`.slice(0, 120)); };

  for (const el of document.body.querySelectorAll("*")) {
    if (!vis(el) || media(el)) continue;
    const s = getComputedStyle(el);
    // 间距：padding / margin / gap
    for (const k of ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "marginTop", "marginRight", "marginBottom", "marginLeft", "rowGap", "columnGap"]) {
      const v = parseFloat(s[k]);
      if (!Number.isNaN(v) && v > 0 && !SP_OK(Math.round(v))) { out.spaceOff++; out.spaceOffVals[Math.round(v)] = (out.spaceOffVals[Math.round(v)] ?? 0) + 1; sample("space", el, `${k}=${s[k]}`); break; }
    }
    // 0 0 0 Npx 的描边环（选中 / 焦点）算边框，不算深度
    if (s.boxShadow !== "none" && !shadowTok.has(s.boxShadow) && !/inset/.test(s.boxShadow) && !/^[^,]*\)? ?0px 0px 0px \d/.test(s.boxShadow)) { out.shadowOff++; sample("shadow", el, s.boxShadow.slice(0, 50)); }
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    out.textEls++;
    const fs = parseFloat(s.fontSize);
    if (!FS.has(Math.round(fs))) { out.fontOff++; out.fontOffSizes[Math.round(fs)] = (out.fontOffSizes[Math.round(fs)] ?? 0) + 1; sample("font", el, `${s.fontSize}`); }
    if (!tokColors.has(s.color)) { out.colorOff++; sample("color", el, s.color); }
    // 溢出：内容比盒子宽且没有截断 / 滚动
    if (el.scrollWidth > el.clientWidth + 1 && s.overflowX === "visible" && s.whiteSpace !== "normal" && el.clientWidth > 0) { out.overflow++; sample("overflow", el, `${el.scrollWidth}>${el.clientWidth}`); }
    // 截断：有省略号但没有悬停全文
    if (s.textOverflow === "ellipsis" && el.scrollWidth > el.clientWidth + 1 && !el.closest("[title]")) { out.clipNoTitle++; sample("clip", el, el.textContent.trim().slice(0, 20)); }
    // 单字成行（中文换行后最后一行只剩 1 个字）
    const tn = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim().length >= 4);
    if (tn && s.whiteSpace !== "nowrap") {
      const rg = document.createRange();
      rg.selectNodeContents(tn);
      const rects = [...rg.getClientRects()].filter((r) => r.width > 0);
      const lines = [...new Set(rects.map((r) => Math.round(r.top)))];
      if (lines.length > 1) {
        const last = rects.filter((r) => Math.round(r.top) === lines[lines.length - 1]);
        const w = last.reduce((a, r) => a + r.width, 0);
        if (w < fs * 1.3) { out.orphan++; sample("orphan", el, tn.textContent.trim().slice(-6)); }
        const lh = parseFloat(s.lineHeight);
        if (!Number.isNaN(lh) && lh / fs < 1.3) { out.lineTight++; sample("lineh", el, `${s.lineHeight}/${s.fontSize}`); }
      }
    }
    // 对比度
    const fg = parseRgb(s.color);
    const bg = bgOf(el);
    if (fg && bg) {
      const c = blend(fg, bg);
      const L1 = lum(c), L2 = lum(bg);
      const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const large = fs >= 24 || (fs >= 18.66 && +s.fontWeight >= 700);
      const sec = secondary.has(s.color);
      const need = el.closest(":disabled, [aria-disabled=true]") ? 0 : sec || large ? 3 : 4.5;
      if (ratio < need) { sec ? out.contrastSecFail++ : out.contrastFail++; sample(sec ? "contrast2" : "contrast", el, `${ratio.toFixed(2)} ${el.textContent.trim().slice(0, 12)}`); }
    }
  }
  return out;
})();
