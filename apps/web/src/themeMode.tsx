/** T59：深 / 浅主题。深色剪辑台默认；选择记在 localStorage（可能不可用，全部 try/catch）；
 *  ?theme=light|dark 可临时指定（截图用，也会记住）。主题挂在 <html data-theme>，样式只读 theme.css 变量。 */
import { useCallback, useEffect, useState } from "react";

export type ThemeMode = "dark" | "light";
const KEY = "ns.theme";
const EVENT = "ns-theme";

function read(): ThemeMode {
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

function apply(m: ThemeMode) {
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

/** 顶栏用的切换按钮 */
export function ThemeToggle() {
  const [mode, toggle] = useTheme();
  return (
    <button className="theme-toggle" onClick={toggle} title={mode === "dark" ? "切到浅色" : "切到深色"} aria-label="切换深色 / 浅色">
      {mode === "dark" ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}
