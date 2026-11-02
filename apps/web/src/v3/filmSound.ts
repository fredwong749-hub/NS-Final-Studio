// FILMUI r6：电影胶片总览“悬停出声”的全局状态（从 FilmOverview.tsx 挪出：组件文件只导出组件，iter_gate U1 / react-refresh 要求）。
// 项目方 12:5x：“不是说过要播放声音吗？没有声音啊”——默认开、记住选择；页面上任意一次点击 / 按键 / 滚动 = 浏览器解锁出声。
// 根因（r4）：默认关，且 play() 被浏览器拒绝后退回静音就再也没改回来。
import { useEffect, useState } from "react";

let FILM_SOUND = (() => {
  try {
    return localStorage.getItem("film.sound") !== "0";
  } catch {
    return true;
  }
})();
let SOUND_UNLOCKED = typeof navigator !== "undefined" && !!(navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation?.hasBeenActive;
const subs = new Set<() => void>();
const notify = () => subs.forEach((f) => f());

export function setFilmSound(v: boolean) {
  FILM_SOUND = v;
  try {
    localStorage.setItem("film.sound", v ? "1" : "0");
  } catch {
    /* 无痕模式 */
  }
  notify();
}
export const soundUnlocked = () => SOUND_UNLOCKED;
export function unlockSound() {
  if (SOUND_UNLOCKED) return;
  SOUND_UNLOCKED = true;
  notify();
}
if (typeof window !== "undefined") {
  const evs = ["pointerdown", "keydown", "wheel", "touchstart"];
  const once = () => {
    unlockSound();
    evs.forEach((t) => window.removeEventListener(t, once, true));
  };
  evs.forEach((t) => window.addEventListener(t, once, { capture: true, passive: true }));
}
export function useFilmSound(): [boolean, (v: boolean) => void] {
  const [, force] = useState(0);
  useEffect(() => {
    const f = () => force((x) => x + 1);
    subs.add(f);
    return () => {
      subs.delete(f);
    };
  }, []);
  return [FILM_SOUND, setFilmSound];
}
/** 视频有没有音轨（Chrome：webkitAudioDecodedByteCount；Firefox：mozHasAudio；标准：audioTracks） */
export function hasAudio(v: HTMLVideoElement) {
  const x = v as HTMLVideoElement & { mozHasAudio?: boolean; webkitAudioDecodedByteCount?: number; audioTracks?: { length: number } };
  return !!(x.mozHasAudio || (x.webkitAudioDecodedByteCount ?? 0) > 0 || (x.audioTracks && x.audioTracks.length > 0));
}
