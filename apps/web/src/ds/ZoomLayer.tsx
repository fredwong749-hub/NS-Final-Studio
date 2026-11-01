// UIMASTER G11（项目方 11-01："我点这个小图标可以放大，这样就可以检阅图里面的东西是对还是错…把全部类似的地方都改一下"）
// 全站一处：任何 < 160px 的小图都能看大图。挂在 main.tsx，所有页面自动生效，不用每个组件各写一遍。
// - 小图本身不可点（不在按钮 / 链接 / 可点卡片里）→ 直接点它就开大图；
// - 小图原本点了有别的作用（选中、打开编辑…）→ 原作用不变；悬停时右上角出现放大镜，点放大镜开大图；或按住 Alt 再点；
// - 键盘：焦点在小图（或包着小图的按钮）上按 Z 开大图；不可点的小图自动可以 Tab 到，Enter 也能开；
// - 大图：原图（不是缩略图）+ 这是什么（人物 · 造型 · 单品…）+ 文件名；Esc 关；← / → 翻同一组的兄弟图；滚轮 / 双指缩放，拖动平移，双击复位。
// 不想被放大的图加 data-nozoom；想写清楚“这是什么”加 data-zoom-label="林晚 · 造型A · 鞋"；想指定分组加 data-zoom-group 到容器上。
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./zoom.css";
import { fullSrc, isSmallImg } from "./ZoomLayer.helpers";

const INTERACTIVE = "button, a[href], [role=button], [role=tab], [role=option], [role=menuitem], label, summary, [onclick]";
/** UIRSI r37（UIAUDIT P1-1）：格子自己有点击动作（React onClick 不会出现在 [onclick] 属性里，cursor 又是 zoom-in）→ 显式标 data-zoom-own。
 *  只影响“点击归谁”：鼠标点 = 格子自己的动作；悬停放大镜 / Alt+点 / Tab 到小图按 Enter / Z 仍然放大（G11 不变） */
const OWN_CLICK = "[data-zoom-own]";

function fileName(src: string): string {
  try {
    const u = new URL(src, location.href);
    const p = u.searchParams.get("path") ?? u.pathname;
    return decodeURIComponent(p.split("/").filter(Boolean).pop() ?? "");
  } catch {
    return "";
  }
}
const short = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, 60);
/** UIPIXEL：title 里常带操作说明（“林晚 · 默认 · D0 点击：切换本镜参考（…）”），大图说明只要前面“这是什么”那段 */
const OP_WORDS = /\n|点击|点开|单击|双击|悬停|拖动|拖到|Alt|Ctrl|Shift|（快捷键|\(快捷键/;
const noOps = (s: string | null | undefined) => {
  const raw = s ?? "";
  const i = raw.search(OP_WORDS);
  return short((i >= 0 ? raw.slice(0, i) : raw).replace(/[\s:：;；,，、·|｜（(-]+$/, ""));
};
function labelOf(img: HTMLImageElement): string {
  const own = img.closest<HTMLElement>("[data-zoom-label]")?.dataset.zoomLabel;
  if (own) return own;
  const alt = noOps(img.alt);
  if (alt) return alt;
  const t = noOps(img.title) || noOps(img.closest("[title]")?.getAttribute("title"));
  if (t && !/点开|看大图|放大/.test(t)) return t;
  const a = short(img.closest("[aria-label]")?.getAttribute("aria-label"));
  if (a) return a;
  const host = img.closest<HTMLElement>(INTERACTIVE + ", figure, li, [class*=card], [class*=chip], [class*=slot], [class*=tile]");
  return short(host?.innerText) || "图片";
}
function groupOf(img: HTMLImageElement): HTMLImageElement[] {
  const explicit = img.closest("[data-zoom-group]");
  const pick = (root: Element) => [...root.querySelectorAll("img")].filter(isSmallImg);
  if (explicit) return pick(explicit);
  let n: Element | null = img.parentElement;
  for (let i = 0; n && n !== document.body && i < 8; i++, n = n.parentElement) {
    const list = pick(n);
    if (list.length >= 2) return list;
  }
  return [img];
}

type Item = { src: string; full: string; label: string; file: string };
const itemOf = (img: HTMLImageElement): Item => {
  const src = img.currentSrc || img.src;
  const full = img.dataset.full || fullSrc(src);
  return { src, full, label: labelOf(img), file: fileName(full) };
};

/** 全站大图层：挂一次 */
export function ZoomLayer() {
  const [mag, setMag] = useState<{ img: HTMLImageElement; x: number; y: number } | null>(null);
  const [open, setOpen] = useState<{ items: Item[]; i: number; back: HTMLElement | null } | null>(null);
  const hideT = useRef<number>(0);
  const openFor = useCallback((img: HTMLImageElement) => {
    const g = groupOf(img);
    const i = Math.max(0, g.indexOf(img));
    // UM-0531：关框后焦点回到“那张小图”（自己可聚焦就用它，否则用包着它的按钮 / 链接），不回到放大镜（放大镜一开框就卸载了）
    const back = img.tabIndex >= 0 ? img : img.closest<HTMLElement>("button, a[href], [role=button], [tabindex]:not([tabindex='-1'])");
    setOpen({ items: (g.length ? g : [img]).map(itemOf), i, back });
    setMag(null);
  }, []);

  useEffect(() => {
    // 悬停：显示放大镜
    const over = (e: PointerEvent) => {
      const t = e.target as Element | null;
      if (t?.closest?.(".zl-mag")) return window.clearTimeout(hideT.current);
      const img = t?.tagName === "IMG" ? t : null;
      if (img && isSmallImg(img)) {
        window.clearTimeout(hideT.current);
        const r = img.getBoundingClientRect();
        setMag({ img, x: Math.min(innerWidth - 30, r.right - 10), y: Math.max(4, r.top - 10) });
      } else {
        window.clearTimeout(hideT.current);
        hideT.current = window.setTimeout(() => setMag(null), 180);
      }
    };
    // 点击：Alt+点 任何小图；或点不可点的小图
    const click = (e: MouseEvent) => {
      const img = e.target as Element | null;
      if (!isSmallImg(img)) return;
      const interactive = !!img.closest(INTERACTIVE) || !!img.closest(OWN_CLICK) || hasPointerAncestor(img);
      if (e.altKey || !interactive) {
        e.preventDefault();
        e.stopPropagation();
        openFor(img);
      }
    };
    // 键盘：焦点在小图 / 包着唯一小图的控件上，按 Z（或在小图本身上按 Enter）
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as Element)?.tagName ?? "") || (e.target as HTMLElement)?.isContentEditable) return;
      const f = document.activeElement as HTMLElement | null;
      if (!f) return;
      const img = f.tagName === "IMG" ? (f as HTMLImageElement) : [...f.querySelectorAll("img")].find(isSmallImg);
      if (!img || !isSmallImg(img)) return;
      if (e.key === "z" || e.key === "Z" || (e.key === "Enter" && f === img)) {
        e.preventDefault();
        e.stopPropagation();
        openFor(img);
      }
    };
    // 不可点的小图可以 Tab 到（给它 tabindex，不改原有行为）
    const tag = () => {
      for (const img of document.querySelectorAll<HTMLImageElement>("img:not([tabindex]):not([data-nozoom])")) {
        if (!isSmallImg(img) || img.closest(INTERACTIVE)) continue;
        img.tabIndex = 0;
        if (!img.title) img.title = "点开看大图（Esc 关，← → 翻）";
      }
    };
    let pend = 0;
    const mo = new MutationObserver(() => { if (!pend) pend = window.setTimeout(() => { pend = 0; tag(); }, 400); });
    mo.observe(document.body, { childList: true, subtree: true });
    tag();
    const scroll = () => setMag(null);
    document.addEventListener("pointerover", over, true);
    document.addEventListener("click", click, true);
    document.addEventListener("keydown", key, true);
    window.addEventListener("scroll", scroll, true);
    return () => {
      mo.disconnect();
      document.removeEventListener("pointerover", over, true);
      document.removeEventListener("click", click, true);
      document.removeEventListener("keydown", key, true);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [openFor]);

  return createPortal(
    <>
      {mag && !open && (
        <button
          type="button"
          className="zl-mag"
          style={{ left: mag.x, top: mag.y }}
          title="看大图（也可以按住 Alt 点图，或焦点在图上按 Z）"
          aria-label="看大图"
          onPointerLeave={() => (hideT.current = window.setTimeout(() => setMag(null), 180))}
          onClick={(e) => {
            e.stopPropagation();
            openFor(mag.img);
          }}
        >
          <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M13 13l4.5 4.5M8.5 6v5M6 8.5h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
        </button>
      )}
      {open && <ZoomBox items={open.items} index={open.i} returnTo={open.back} onClose={() => setOpen(null)} />}
    </>,
    document.body,
  );
}

function hasPointerAncestor(img: Element): boolean {
  for (let n = img.parentElement, i = 0; n && n !== document.body && i < 4; n = n.parentElement, i++) if (getComputedStyle(n).cursor === "pointer") return true;
  return false;
}

/** 大图框：可单独用（替代旧 Lightbox） */
export function ZoomBox({ items, index = 0, onClose, returnTo }: { items: Item[] | { src: string; full?: string; label?: string; file?: string }[]; index?: number; onClose: () => void; returnTo?: HTMLElement | null }) {
  const list: Item[] = items.map((x) => ({ src: x.src, full: (x as Item).full ?? fullSrc(x.src), label: (x as Item).label ?? "图片", file: (x as Item).file ?? fileName((x as Item).full ?? x.src) }));
  const [i, setI] = useState(Math.min(index, list.length - 1));
  const [z, setZ] = useState({ s: 1, x: 0, y: 0 });
  const [nat, setNat] = useState<string>("");
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const prevFocus = useRef<Element | null>(null);
  const it = list[i];
  const go = useCallback((d: number) => { setI((v) => (v + d + list.length) % list.length); setZ({ s: 1, x: 0, y: 0 }); setNat(""); }, [list.length]);
  useEffect(() => {
    const el = box.current; // 在 effect 里先拿住节点：StrictMode 假卸载时 ref 会先被清空
    if (!prevFocus.current || !el?.contains(document.activeElement)) prevFocus.current = document.activeElement;
    el?.focus();
    return () => {
      // 回位目标：调用方指定的（小图 / 它的按钮）优先；不行再回打开前的焦点；都不在了就不动
      const t = [returnTo, prevFocus.current as HTMLElement | null].find((e) => e && e.isConnected && e !== document.body);
      requestAnimationFrame(() => { if (!el?.isConnected) t?.focus?.({ preventScroll: true }); }); // StrictMode 的假卸载（框还在）不还焦点
    };
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); }
      else if (e.key === "ArrowRight" && list.length > 1) { e.preventDefault(); e.stopPropagation(); go(1); }
      else if (e.key === "ArrowLeft" && list.length > 1) { e.preventDefault(); e.stopPropagation(); go(-1); }
      else if (e.key === "+" || e.key === "=") setZ((v) => ({ ...v, s: Math.min(8, v.s * 1.25) }));
      else if (e.key === "-") setZ((v) => ({ ...v, s: Math.max(1, v.s / 1.25) }));
      else if (e.key === "0") setZ({ s: 1, x: 0, y: 0 });
      else if (e.key === "Tab") {
        // 焦点留在框里
        const f = [...(box.current?.querySelectorAll<HTMLElement>("button") ?? [])];
        if (!f.length) return;
        const at = f.indexOf(document.activeElement as HTMLElement);
        e.preventDefault();
        f[(at + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [go, onClose, list.length]);
  if (!it) return null;
  const wheel = (e: React.WheelEvent) => {
    const f = Math.exp(-e.deltaY / 400);
    setZ((v) => {
      const s = Math.min(8, Math.max(1, v.s * f));
      return s === 1 ? { s, x: 0, y: 0 } : { ...v, s };
    });
  };
  return (
    <div className="zl-box" role="dialog" aria-modal="true" aria-label={`大图：${it.label}`} tabIndex={-1} ref={box} onClick={onClose}>
      <div className="zl-stage" onWheel={wheel}
        onPointerDown={(e) => { if (z.s > 1) { e.stopPropagation(); drag.current = { x: e.clientX, y: e.clientY, ox: z.x, oy: z.y }; (e.target as Element).setPointerCapture?.(e.pointerId); } }}
        onPointerMove={(e) => { const d = drag.current; if (d) setZ((v) => ({ ...v, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y })); }}
        onPointerUp={() => (drag.current = null)}
      >
        <img
          src={it.full}
          alt={it.label}
          draggable={false}
          className={z.s > 1 ? "zoomed" : ""}
          style={{ transform: `translate(${z.x}px, ${z.y}px) scale(${z.s})` }}
          onLoad={(e) => setNat(`${e.currentTarget.naturalWidth}×${e.currentTarget.naturalHeight}`)}
          onError={(e) => { if (e.currentTarget.src !== new URL(it.src, location.href).href) e.currentTarget.src = it.src; }}
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={(e) => { e.stopPropagation(); setZ((v) => (v.s > 1 ? { s: 1, x: 0, y: 0 } : { s: 2.5, x: 0, y: 0 })); }}
        />
      </div>
      <div className="zl-bar" onClick={(e) => e.stopPropagation()}>
        <div className="zl-cap">
          <b>{it.label}</b>
          <span>{[it.file, nat, list.length > 1 ? `${i + 1} / ${list.length}` : ""].filter(Boolean).join(" · ")}</span>
        </div>
        <div className="zl-btns">
          {list.length > 1 && <button type="button" className="ds-btn sm" onClick={() => go(-1)} title="上一张（←）">‹ 上一张</button>}
          {list.length > 1 && <button type="button" className="ds-btn sm" onClick={() => go(1)} title="下一张（→）">下一张 ›</button>}
          <button type="button" className="ds-btn sm" onClick={() => setZ((v) => ({ ...v, s: Math.min(8, v.s * 1.5) }))} title="放大（滚轮 / + ）">＋</button>
          <button type="button" className="ds-btn sm" onClick={() => setZ((v) => { const s = Math.max(1, v.s / 1.5); return s === 1 ? { s, x: 0, y: 0 } : { ...v, s }; })} title="缩小（滚轮 / - ）">－</button>
          <button type="button" className="ds-btn sm" onClick={() => setZ({ s: 1, x: 0, y: 0 })} title="复位（0 / 双击图）">{Math.round(z.s * 100)}%</button>
          <a className="ds-btn sm" href={it.full} target="_blank" rel="noreferrer" title="在新标签打开原图">原图 ↗</a>
          <button type="button" className="ds-btn sm" onClick={onClose} title="关闭（Esc）">关闭 Esc</button>
        </div>
      </div>
    </div>
  );
}
