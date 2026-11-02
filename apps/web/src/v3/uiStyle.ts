// UIRSI r46：界面视觉方向的开关。UIRSI2（总调度 11-02 14:3x 亲审定）：L-114 电影胶片 A 改为默认。
// 地址栏 ?ui=film / ?ui=slide / ?ui=off 或 localStorage "ui.style" 决定 <html> 上的类：
//   film  = L-114 电影胶片 A（v3/film.css + pages/FilmOverview.tsx）——默认（没有参数、也没有本地记录时）
//   slide = L-113 正片 B（v3/slide.css，已被 L-114 取代，隔离保留，退路）
//   off   = 旧默认界面（退路；旧样式只隐藏不删，K-UI 不删功能）
export type UiStyle = "film" | "slide" | null;

export function readUiStyle(): UiStyle {
  try {
    const q = new URLSearchParams(location.search).get("ui") ?? new URLSearchParams(location.hash.split("?")[1] ?? "").get("ui");
    if (q === "off" || q === "film" || q === "slide") localStorage.setItem("ui.style", q);
    const v = localStorage.getItem("ui.style");
    if (v === "off") return null;
    return v === "slide" ? "slide" : "film";
  } catch {
    return "film";
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
