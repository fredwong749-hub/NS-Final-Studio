// PW-019：从 ds/index.tsx 挪出来的非组件导出（hook / 常量 / 函数）。组件文件只导出组件，热更新才不会退化成整页重载。
import { useEffect, type RefObject } from "react";
import type { Tone } from "./index";

export function useEsc(on: () => void) {
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        on();
      }
    };
    window.addEventListener("keydown", f, true);
    return () => window.removeEventListener("keydown", f, true);
  }, [on]);
}

/** UIMASTER（crawl focus_trap / focus_return）：弹框 / 抽屉打开时焦点进框、Tab 在框内循环、关闭后焦点回到打开它的那个控件 */
const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
type Trig = { el: HTMLElement; tag: string; title: string | null; label: string | null; text: string; x: number; y: number; opener: HTMLElement | null };
const trigOf = (el: HTMLElement): Trig => {
  const r = el.getBoundingClientRect();
  // 按钮在弹出菜单 / 折叠里（菜单打开框后会自己收起，原按钮随之消失）：记下菜单的开关按钮，关框后焦点回到它
  const wrap = el.closest<HTMLElement>(".v3-popwrap");
  const det = el.closest("details");
  const opener = (wrap && !wrap.querySelector(":scope > button")?.contains(el) ? wrap.querySelector<HTMLElement>(":scope > button") : null) ?? (det && !el.matches("summary") ? det.querySelector<HTMLElement>(":scope > summary") : null);
  return { el, tag: el.tagName, title: el.getAttribute("title"), label: el.getAttribute("aria-label"), text: (el.innerText || "").trim(), x: r.x + r.width / 2, y: r.y + r.height / 2, opener };
};
/** 最近一次按下的控件（框打开前那一下）：有的按钮点了不拿焦点、或在框开着时被重新渲染，靠它找回去 */
let lastTrig: Trig | null = null;
if (typeof document !== "undefined")
  document.addEventListener(
    "pointerdown",
    (e) => {
      const el = (e.target as Element | null)?.closest?.<HTMLElement>(FOCUSABLE);
      if (el && !el.closest('[role=dialog][aria-modal="true"]')) lastTrig = trigOf(el);
    },
    true,
  );
// UIPIXEL：键盘（Enter / 空格）打开的框也记住触发控件——有的按钮点了以后自己变 disabled（如 🗑 读影响面时），
// 焦点先掉到 body，框打开时就找不到是谁开的，关框后焦点回不去（UIMASTER OT1：⋯ 菜单里的 🗑）
if (typeof document !== "undefined")
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const el = (e.target as Element | null)?.closest?.<HTMLElement>(FOCUSABLE);
      if (el && !el.closest('[role=dialog][aria-modal="true"]')) lastTrig = trigOf(el);
    },
    true,
  );
const visibleFocusable = () => [...document.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((e) => e.offsetParent !== null && getComputedStyle(e).visibility !== "hidden" && !e.closest('[role=dialog][aria-modal="true"]'));
function focusBack(t: Trig | null) {
  if (!t) return;
  const ok = (e: HTMLElement | null | undefined) => {
    if (!e || !e.isConnected) return false;
    e.focus({ preventScroll: true });
    return document.activeElement === e;
  };
  if (ok(t.el)) return;
  const d = (e: HTMLElement) => { const r = e.getBoundingClientRect(); return Math.hypot(r.x + r.width / 2 - t.x, r.y + r.height / 2 - t.y); };
  // 同一个按钮被重新渲染：找同样子（标签 / 标题 / 文字）里离原位置最近的
  const same = visibleFocusable().filter((e) => e.tagName === t.tag && e.getAttribute("title") === t.title && e.getAttribute("aria-label") === t.label && (e.innerText || "").trim() === t.text).sort((x, y) => d(x) - d(y));
  if (ok(same[0])) return;
  if (ok(t.opener)) return;
  // 原按钮已不在（例如收在窄屏的 ⋯ 菜单里）：退回到离原位置最近的、看得见的控件
  ok(visibleFocusable().sort((x, y) => d(x) - d(y))[0]);
}
export function useFocusTrap(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    // StrictMode 下 effect 会跑两次：第二次时焦点已经在框里了；打开前的控件记在框节点上，只记一次
    const holder = box as HTMLElement & { __uimTrig?: Trig | null };
    if (holder.__uimTrig === undefined) {
      const a = document.activeElement as HTMLElement | null;
      holder.__uimTrig = a && a !== document.body && !box.contains(a) ? trigOf(a) : lastTrig;
    }
    const trig = holder.__uimTrig;
    const items = () => [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((e) => e.offsetParent !== null || e === document.activeElement);
    if (!box.contains(document.activeElement)) (items().find((e) => !e.matches("[aria-label=关闭]")) ?? box).focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      // 只管最上层的框（框里再开的框 / 大图层自己管）
      const top = [...document.querySelectorAll('[role=dialog][aria-modal="true"]')].pop();
      if (top !== box) return;
      const f = items();
      if (!f.length) return e.preventDefault();
      const i = f.indexOf(document.activeElement as HTMLElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && (i === -1 || i === f.length - 1)) { e.preventDefault(); f[0].focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      // 等框真正卸载后再还焦点（同一帧里框还在）
      requestAnimationFrame(() => { if (!box.isConnected) focusBack(trig); }); // StrictMode 的假卸载（框还在）不还焦点
    };
  }, [ref]);
}

/* ---------------------------------------------------------------- 资产统一状态（A §3.3） */

export type AssetStatus = "draft" | "candidate" | "final" | "void" | "dep";
export const ASSET_STATUS: Record<AssetStatus, { label: string; tone: Tone; tip: string }> = {
  draft: { label: "草稿", tone: "neutral", tip: "只有文字或登记，还没有图" },
  candidate: { label: "候选", tone: "warn", tip: "有图，还没定稿" },
  final: { label: "定稿", tone: "ok", tip: "可以拿去出片" },
  void: { label: "作废", tone: "void", tip: "留着，不再用" },
  dep: { label: "依赖已更新", tone: "stale", tip: "定稿后上游改过：用它的镜头可能要重出（只标记，不自动重出）" },
};

/** 秒 → “约 N 分钟 / 约 N.N 小时” */
export function fmtDur(s: number) {
  if (!s || s < 60) return s ? "不到 1 分钟" : "0";
  const m = Math.round(s / 60);
  return m < 90 ? `约 ${m} 分钟` : `约 ${(m / 60).toFixed(1)} 小时`;
}
