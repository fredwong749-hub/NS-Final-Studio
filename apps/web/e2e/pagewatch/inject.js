// PAGEWATCH 页面内探针（只读）：记录 DOM 换节点、闪烁、布局跳动、动画、骨架屏重现。由 watcher.mjs 注入，数据挂 window.__pw，watcher 每轮取走。
(() => {
  if (window.__pw) return;
  const pw = (window.__pw = { t0: Date.now(), muts: [], flashes: [], shifts: [], anims: [], skel: [], ready: false });
  const now = () => Date.now();
  const path = (e) => {
    const parts = [];
    let n = e;
    for (let i = 0; n && n.nodeType === 1 && n !== document.body && i < 5; i++, n = n.parentElement) {
      const c = [...n.classList].filter((x) => !/^(on|active|sel|open|is-|has-|live-|full|ok|bad)$/.test(x) && x !== "live-flash").slice(0, 2).join(".");
      let idx = "";
      if (n.parentElement) {
        const sid = n.getAttribute && (n.getAttribute("data-shot") || n.getAttribute("data-shot-id") || n.getAttribute("data-rt-id"));
        if (sid) { parts.unshift(n.tagName.toLowerCase() + (c ? "." + c : "") + `[${sid}]`); continue; }
        const sib = [...n.parentElement.children].filter((x) => x.tagName === n.tagName);
        if (sib.length > 1) idx = `:${sib.indexOf(n)}`;
      }
      parts.unshift(n.tagName.toLowerCase() + (c ? "." + c : "") + idx);
    }
    return parts.join(">");
  };
  // 可见内容签名：文字 + 图片地址 + 带 style 的宽度（进度条）
  const sig = (e) =>
    (e.textContent || "").replace(/\s+/g, " ").slice(0, 3000) +
    "|" + [...e.querySelectorAll("img,video")].map((i) => i.currentSrc || i.src || "").join(",") +
    "|" + [...e.querySelectorAll("[style]")].map((x) => x.getAttribute("style")).join(";");
  const FLASHABLE = ".sp,.sp-seg,.ns-sep,.rt-row,.rt-btn,.v3-queue,.v3-row,.live-flash";
  const snap = new Map(); // path -> {sig, t}
  const takeSnap = () => {
    for (const e of document.querySelectorAll(FLASHABLE)) {
      if (e.classList.contains("live-flash")) continue;
      snap.set(path(e), { sig: sig(e), t: now() });
    }
  };
  setInterval(takeSnap, 1000);
  const flashing = new WeakSet();
  const onFlash = (e) => {
    const p = path(e);
    const r = e.getBoundingClientRect();
    const prev = snap.get(p);
    const cur = sig(e);
    const area = (Math.max(0, r.width) * Math.max(0, r.height)) / (innerWidth * innerHeight);
    pw.flashes.push({ t: now(), path: p, text: (e.textContent || "").replace(/\s+/g, " ").slice(0, 80), area: +area.toFixed(3), w: Math.round(r.width), h: Math.round(r.height), changed: prev && now() - prev.t >= 300 ? prev.sig !== cur : null, prevAge: prev ? now() - prev.t : null, prevSig: prev && prev.sig !== cur ? prev.sig.slice(0, 160) : undefined, curSig: prev && prev.sig !== cur ? cur.slice(0, 160) : undefined });
  };
  const mo = new MutationObserver((recs) => {
    let added = 0, removed = 0, same = 0, attrFlash = 0;
    const remHtml = new Map();
    const where = new Map();
    for (const r of recs) {
      if (r.type === "attributes" && r.attributeName === "class") {
        const e = r.target;
        if (e.classList && e.classList.contains("live-flash") && !flashing.has(e)) { flashing.add(e); attrFlash++; onFlash(e); }
        else if (e.classList && !e.classList.contains("live-flash")) flashing.delete(e);
        continue;
      }
      if (r.type !== "childList") continue;
      for (const n of r.removedNodes) if (n.nodeType === 1) { removed++; const h = n.outerHTML.replace(/ live-flash/g, ""); remHtml.set(h, (remHtml.get(h) || 0) + 1); }
      for (const n of r.addedNodes) {
        if (n.nodeType !== 1) continue;
        added++;
        if (n.classList && n.classList.contains("live-flash") && !flashing.has(n)) { flashing.add(n); onFlash(n); }
        for (const f of n.querySelectorAll ? n.querySelectorAll(".live-flash") : []) if (!flashing.has(f)) { flashing.add(f); onFlash(f); }
        if (n.matches && (n.matches(".ds-skel,.sp-skel") || n.querySelector(".ds-skel,.sp-skel")) && pw.ready) pw.skel.push({ t: now(), path: path(n) });
        const h = n.outerHTML.replace(/ live-flash/g, "");
        const k = remHtml.get(h);
        if (k) { same++; remHtml.set(h, k - 1); const p = path(r.target); where.set(p, (where.get(p) || 0) + 1); }
      }
    }
    if (added || removed) pw.muts.push({ t: now(), added, removed, sameRemount: same, where: [...where.entries()].slice(0, 5) });
    if (pw.muts.length > 3000) pw.muts.splice(0, 1000);
  });
  const go = () => {
    mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) pw.shifts.push({ t: Math.round(performance.timeOrigin + e.startTime), v: +e.value.toFixed(4), input: e.hadRecentInput, src: (e.sources || []).slice(0, 3).map((s) => (s.node && s.node.nodeType === 1 ? path(s.node) : "#text") + ` ${Math.round(s.previousRect.y)}→${Math.round(s.currentRect.y)} h${Math.round(s.previousRect.height)}→${Math.round(s.currentRect.height)}`) });
      }).observe({ type: "layout-shift", buffered: true });
    } catch (e) { pw.noLS = String(e); }
    document.addEventListener("animationstart", (ev) => {
      const e = ev.target;
      if (ev.animationName === "sp-shimmer") return;
      const r = e.getBoundingClientRect();
      pw.anims.push({ t: now(), name: ev.animationName, path: path(e), area: +((r.width * r.height) / (innerWidth * innerHeight)).toFixed(3) });
      if (pw.anims.length > 2000) pw.anims.splice(0, 500);
    }, true);
    setTimeout(() => (pw.ready = true), 8000);
  };
  if (document.body) go(); else document.addEventListener("DOMContentLoaded", go);
  window.__pwDrain = () => {
    const out = { muts: pw.muts.splice(0), flashes: pw.flashes.splice(0), shifts: pw.shifts.splice(0), anims: pw.anims.splice(0), skel: pw.skel.splice(0) };
    return out;
  };
})();
