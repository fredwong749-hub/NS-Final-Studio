// UIPIXEL（PW-019）：ZoomLayer 的常量和纯函数单独放这里，组件文件只导出组件（热更新不整页重载）。
export const ZOOM_MAX = 160; // 短边小于这个尺寸的图算“小图”（UM-0411：竖版首帧格 106×188 也要能放大）
export const ZOOM_LONG_MAX = 400; // 长边上限：1000×100 这种横幅不算缩略图
/** 缩略图地址 → 原图地址（/api/thumb?src=…&w=… → src） */
export function fullSrc(src: string): string {
  try {
    const u = new URL(src, location.href);
    if (u.pathname === "/api/thumb" && u.searchParams.get("src")) return u.searchParams.get("src")!;
    return u.pathname + u.search;
  } catch {
    return src;
  }
}
export function isSmallImg(el: Element | null): el is HTMLImageElement {
  if (!el || el.tagName !== "IMG") return false;
  const img = el as HTMLImageElement;
  if (img.closest("[data-nozoom], .zl-box, .mp-lightbox, vite-error-overlay")) return false;
  if (!img.currentSrc && !img.src) return false;
  const r = img.getBoundingClientRect();
  const lo = Math.min(r.width, r.height), hi = Math.max(r.width, r.height);
  return lo >= 16 && lo < ZOOM_MAX && hi < ZOOM_LONG_MAX;
}
