// PW-019：从 themeMode.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { useCallback, useEffect, useState } from "react";

export type ThemeMode = "dark" | "light";

export const KEY = "ns.theme";

export const EVENT = "ns-theme";

export function read(): ThemeMode {
  try {
    const q = new URLSearchParams(location.search).get("theme");
    if (q === "dark" || q === "light") {
      localStorage.setItem(KEY, q);
      return q;
    }
  } catch {
    /* 无 localStorage / URL 解析失败：用默认 */
  }
  try {
    const v = localStorage.getItem(KEY);
    if (v === "dark" || v === "light") return v;
  } catch {
    /* 同上 */
  }
  return "dark";
}

export function apply(m: ThemeMode) {
  document.documentElement.dataset.theme = m;
}

export function initTheme() {
  apply(read());
}

export function setTheme(m: ThemeMode) {
  apply(m);
  try {
    localStorage.setItem(KEY, m);
  } catch {
    /* 存不了就只对本页生效 */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: m }));
}

export function useTheme(): [ThemeMode, () => void] {
  const [mode, setMode] = useState<ThemeMode>(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));
  useEffect(() => {
    const on = (e: Event) => setMode((e as CustomEvent<ThemeMode>).detail);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  const toggle = useCallback(() => setTheme(mode === "dark" ? "light" : "dark"), [mode]);
  return [mode, toggle];
}
