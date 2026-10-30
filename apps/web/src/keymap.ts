import { useEffect, useRef } from "react";
import { LOCK_SUPPORTED } from "./api";
import { PASTE_FIELDS, type Studio } from "./store";
import type { Stage } from "./types";
import { isTypingTarget } from "./util";

/** 下一个未审镜头（从当前往后找，到底再从头） */
export function nextUnreviewed(st: Studio): string | null {
  const order = st.shots;
  const i = st.sel ? order.findIndex((s) => s.id === st.sel) : -1;
  for (let k = 1; k <= order.length; k++) {
    const s = order[(i + k) % order.length];
    if (s.review.state === "unreviewed") return s.id;
  }
  return null;
}

function togglePlayer() {
  const v = (document.getElementById("review-player") ?? document.getElementById("main-player")) as HTMLVideoElement | null;
  if (!v || v.tagName !== "VIDEO") return;
  if (v.paused) void v.play();
  else v.pause();
}

/**
 * 单一 keymap（规范 C10）：焦点在输入框时不响应（Ctrl+S 由检查器单独处理）；
 * 焦点在按钮上时不抢 Enter / 空格；忽略按住重复；空格在 keyup 时触发。
 */
export function useKeymap(st: Studio) {
  const ref = useRef(st);
  ref.current = st;

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const s = ref.current;
      if (isTypingTarget(e.target)) return;
      const onButton = (e.target as HTMLElement | null)?.tagName === "BUTTON";
      if (e.key === " ") {
        if (!onButton) e.preventDefault(); // 防止页面滚动；真正动作在 keyup
        return;
      }
      if (e.repeat) return;
      const modal = s.confirmReq || s.rejectFor || s.helpOpen || s.paletteOpen || s.viewer;
      if (e.key === "Escape") {
        if (s.confirmReq) s.setConfirmReq(null);
        else if (s.rejectFor) s.setRejectFor(null);
        else if (s.helpOpen) s.setHelpOpen(false);
        else if (s.paletteOpen) s.setPaletteOpen(false);
        else if (s.reviewMode) s.setReviewMode(false);
        else if (s.preview) s.setPreview(null);
        else if (s.multi.size) s.setMulti(new Set());
        else if (s.drawer.open) s.setDrawer({ ...s.drawer, open: false });
        return;
      }
      if (modal) return;
      const ctrl = e.ctrlKey || e.metaKey;
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const sel = s.sel;
      const d = sel ? s.details[sel] : undefined;
      const handled = () => e.preventDefault();

      if (ctrl) {
        if (k === "k") return handled(), s.setPaletteOpen(true);
        if (k === "z") return handled(), void s.undo(e.shiftKey);
        if (k === "y") return handled(), void s.undo(true);
        if (k === "c" && !window.getSelection()?.toString()) return handled(), s.copyEdit();
        if (k === "v") return handled(), s.pasteEdit([...PASTE_FIELDS]);
        return;
      }
      if (e.altKey) return;

      // 审片模式专用
      if (s.reviewMode) {
        if (k === "j") return handled(), s.stepShot(-1);
        if (k === "k") return handled(), s.stepShot(1);
      }

      switch (k) {
        case "ArrowLeft":
          return handled(), s.stepShot(-1);
        case "ArrowRight":
          return handled(), s.stepShot(1);
        case "ArrowUp":
        case "PageUp":
          return handled(), s.gotoEpisode(s.epNum - 1);
        case "ArrowDown":
        case "PageDown":
          return handled(), s.gotoEpisode(s.epNum + 1);
        case "g":
          return handled(), s.setPaletteOpen(true);
        case "1":
          return s.setView("overview");
        case "2":
          return s.setView("episode");
        case "4":
          return s.setView("assets");
        case "d":
          return handled(), s.cycleDensity();
        case "t":
          return handled(), s.setListMode(!s.listMode);
        case "\\":
          return handled(), s.setInspectorHidden(!s.inspectorHidden);
        case "?":
          return s.setHelpOpen(true);
        case "r":
          return s.setReviewMode(!s.reviewMode);
        case "Enter": {
          if (onButton) return;
          if (e.shiftKey && s.preview && s.preview.shotId === sel)
            return handled(), void s.activate(s.preview.shotId, s.preview.stage, s.preview.n);
          return handled(), document.getElementById("inspector")?.focus();
        }
      }
      if (!sel) return;
      switch (k) {
        case "i":
          return s.requestRender(sel, "image");
        case "e":
          return s.requestRender(sel, "last");
        case "v":
          return e.shiftKey ? s.requestChain(sel) : s.requestRender(sel, "video");
        case "a": {
          const ids = s.multi.size ? [...s.multi] : [sel];
          void s.setReview(ids, "passed").then((ok) => {
            if (ok && s.reviewMode) {
              const n = nextUnreviewed(ref.current);
              if (n) ref.current.select(n);
            }
          });
          return;
        }
        case "x":
          return s.setRejectFor(s.multi.size ? [...s.multi] : [sel]);
        case "l":
          if (!LOCK_SUPPORTED) s.notify("锁定接口待后端提供", "err");
          return;
        case "[":
        case "]": {
          if (!d) return;
          const stage: Stage = s.inspTab === "last" ? "last" : s.inspTab === "video" ? "video" : "image";
          const list = d.takes.takes.filter((t) => t.stage === stage).sort((a, b) => b.n - a.n);
          if (!list.length) return s.notify("还没有版本");
          const cur = s.preview?.shotId === sel && s.preview.stage === stage ? s.preview.n : d.takes.active[stage];
          const idx = Math.max(0, list.findIndex((t) => t.n === cur));
          const next = list[Math.min(list.length - 1, Math.max(0, idx + (k === "]" ? 1 : -1)))];
          return s.setPreview(next.n === d.takes.active[stage] ? null : { shotId: sel, stage, n: next.n });
        }
        case "c": {
          // 全屏 A/B 对比当前页签的阶段（首帧 / 尾帧）
          if (!d) return;
          const stage = s.inspTab === "last" ? "last" : "image";
          const b = s.preview?.shotId === sel && s.preview.stage === stage ? s.preview.n : null;
          return handled(), s.openViewer(sel, stage, "ab", b);
        }
        case "f":
          return handled(), s.openViewer(sel, s.inspTab === "last" ? "last" : "image");
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.key !== " " || isTypingTarget(e.target) || (e.target as HTMLElement | null)?.tagName === "BUTTON") return;
      const s = ref.current;
      if (s.confirmReq || s.rejectFor || s.helpOpen || s.paletteOpen) return;
      togglePlayer();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);
}
