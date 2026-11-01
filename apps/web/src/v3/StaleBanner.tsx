// UIRSI r45 页面过期检测（L-103；项目方 04:4x“我的猫猫车 logo 呢？……顶部都没有了”——实测代码齐全，是标签页停在旧状态）。
// 不靠项目方自己按刷新：
//   · 开发版（:5173，有 import.meta.hot）：热更新报错（vite:error）、和开发服务器断开又连上（vite:ws:disconnect → connect）、
//     或 GET /api/ui/version 的 src_at 比“本页加载 / 最后一次热更新”新且 90 秒内热更新没跟上 → 判过期；
//   · 打包版（:8800 挂 apps/web/dist）：dist_at 和本页加载时不同（有新打包）→ 判过期。
// 过期 → 顶部一条中性提示“界面已更新 · 点此刷新”；空闲 2 分钟（没有键鼠操作、没有打开抽屉 / 对话框）自动刷新。
import { useEffect, useRef, useState } from "react";

const POLL_MS = 60000;
const HMR_GRACE_S = 90;
const IDLE_MS = 120000;

export function StaleBanner() {
  const [why, setWhy] = useState<string | null>(null);
  const loadedAt = useRef(Date.now() / 1000);
  const lastHmr = useRef(0);
  const firstDist = useRef<number | null>(null);
  const lastInput = useRef(Date.now());
  const disconnected = useRef(false);

  useEffect(() => {
    const hot = import.meta.hot;
    if (!hot) return;
    const onUpdate = () => (lastHmr.current = Date.now() / 1000);
    const onErr = () => setWhy("界面热更新出错");
    const onDis = () => (disconnected.current = true);
    const onCon = () => {
      if (disconnected.current) setWhy("和界面服务断开过，可能没跟上最新改动");
    };
    hot.on("vite:afterUpdate", onUpdate);
    hot.on("vite:error", onErr);
    hot.on("vite:ws:disconnect", onDis);
    hot.on("vite:ws:connect", onCon);
    return () => {
      hot.off?.("vite:afterUpdate", onUpdate);
      hot.off?.("vite:error", onErr);
      hot.off?.("vite:ws:disconnect", onDis);
      hot.off?.("vite:ws:connect", onCon);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const check = () =>
      fetch("/api/ui/version")
        .then((r) => (r.ok ? (r.json() as Promise<{ src_at: number; dist_at: number }>) : null))
        .then((v) => {
          if (!alive || !v) return;
          if (import.meta.hot) {
            const seen = Math.max(loadedAt.current, lastHmr.current);
            if (v.src_at > seen + 5 && Date.now() / 1000 - v.src_at > HMR_GRACE_S) setWhy("界面有新改动，这一页还没跟上");
          } else {
            if (firstDist.current == null) firstDist.current = v.dist_at;
            else if (v.dist_at !== firstDist.current) setWhy("界面已发布新版本");
          }
        })
        .catch(() => {});
    const t0 = window.setTimeout(check, 15000);
    const t = window.setInterval(check, POLL_MS);
    return () => {
      alive = false;
      window.clearTimeout(t0);
      window.clearInterval(t);
    };
  }, []);

  useEffect(() => {
    const mark = () => (lastInput.current = Date.now());
    window.addEventListener("keydown", mark, true);
    window.addEventListener("pointerdown", mark, true);
    window.addEventListener("wheel", mark, { capture: true, passive: true });
    return () => {
      window.removeEventListener("keydown", mark, true);
      window.removeEventListener("pointerdown", mark, true);
      window.removeEventListener("wheel", mark, true);
    };
  }, []);

  useEffect(() => {
    if (!why) return;
    const t = window.setInterval(() => {
      const busy = document.querySelector(".sd, [role=dialog], .v3-pop, input:focus, textarea:focus, [contenteditable=true]:focus");
      if (!busy && Date.now() - lastInput.current > IDLE_MS) location.reload();
    }, 10000);
    return () => window.clearInterval(t);
  }, [why]);

  if (!why) return null;
  return (
    <div className="stale-bar" role="status">
      <i className="sea-dot d-need" aria-hidden />
      <span>{why}</span>
      <button type="button" onClick={() => location.reload()}>
        点此刷新
      </button>
      <small>空闲 2 分钟会自动刷新</small>
    </div>
  );
}
