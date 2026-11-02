// UIRSI r46：界面视觉方向的开关（总调度：新样式定稿前放在开关后，亲审通过才去掉开关）。
// 地址栏 ?ui=film / ?ui=slide / ?ui=off 或 localStorage "ui.style" 决定 <html> 上的类：
//   film  = L-114 电影胶片 A（v3/film.css + pages/FilmOverview.tsx）
//   slide = L-113 正片 B（v3/slide.css，已被 L-114 取代，隔离保留）
// 默认不加任何类 = 现有界面。
export type UiStyle = "film" | "slide" | null;

export function readUiStyle(): UiStyle {
  try {
    const q = new URLSearchParams(location.search).get("ui") ?? new URLSearchParams(location.hash.split("?")[1] ?? "").get("ui");
    if (q === "off") localStorage.removeItem("ui.style");
    else if (q === "film" || q === "slide") localStorage.setItem("ui.style", q);
    const v = localStorage.getItem("ui.style");
    return v === "film" || v === "slide" ? v : null;
  } catch {
    return null;
  }
}

export function applyUiStyle(): UiStyle {
  const v = readUiStyle();
  const c = document.documentElement.classList;
  c.toggle("ui-film", v === "film");
  c.toggle("ui-slide", v === "slide");
  return v;
}

export const filmOn = () => document.documentElement.classList.contains("ui-film");
