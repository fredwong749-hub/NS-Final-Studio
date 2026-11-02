// UIRSI2 · 反馈模式数据层（后端 FEEDBACK：services/api/ns_api/feedback.py，接口 docs/feedback/API.md）。
// 开关存 localStorage "fb.mode"；列表一份缓存（顶栏计数、抽屉、帧角标共用）。
// 状态圆点按全站规则只用 灰 / 琥珀 / 绿（K-UI-049）：后端 dot red（新 / 被打回）→ 琥珀，yellow（处理中）→ 灰，green（已修复核 / 关单）→ 绿。
import { useEffect, useState } from "react";

export interface FbTarget {
  kind: "first" | "last" | "video" | "field" | "ui" | "shot" | "episode" | "other";
  field?: string | null;
  selector?: string | null;
  label?: string | null;
  file?: string | null;
}
export interface FbItem {
  id: string;
  created_at: string;
  by?: { name?: string; role?: string };
  text: string;
  route?: string;
  ep?: number | null;
  shot?: string | null;
  target?: FbTarget;
  take?: string | number | null;
  timecode?: number | null;
  status: string;
  status_zh?: string;
  dot: "red" | "yellow" | "green";
  owner?: string | null;
  fix_note?: string | null;
  root_cause?: string | null;
  reopened?: number;
  screenshot?: string | null;
}
export interface FbList {
  items: FbItem[];
  counts: Record<string, number>;
  dots: { red: number; yellow: number; green: number };
  total: number;
}
export type UiDot = "yellow" | "gray" | "green";
export const uiDot = (d: FbItem["dot"]): UiDot => (d === "red" ? "yellow" : d === "yellow" ? "gray" : "green");
export const DOT_WORD: Record<UiDot, string> = { yellow: "新 / 被打回", gray: "处理中", green: "已修 / 已验证" };

let mode = (() => {
  try {
    return localStorage.getItem("fb.mode") === "1";
  } catch {
    return false;
  }
})();
let list: FbList | null = null;
let err: string | null = null;
let drawer = false;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
let timer: ReturnType<typeof setInterval> | null = null;

export function setFbMode(v: boolean) {
  mode = v;
  try {
    localStorage.setItem("fb.mode", v ? "1" : "0");
  } catch {
    /* 隐私模式：只在本页生效 */
  }
  document.documentElement.classList.toggle("fb-on", v);
  emit();
}
export function setFbDrawer(v: boolean) {
  drawer = v;
  emit();
}

export async function refreshFeedback() {
  try {
    const r = await fetch("/api/feedback?limit=500", { credentials: "same-origin" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    list = (await r.json()) as FbList;
    err = null;
  } catch (e) {
    err = (e as Error).message;
  }
  emit();
}

export function useFeedback() {
  const [, setN] = useState(0);
  useEffect(() => {
    const f = () => setN((x) => x + 1);
    subs.add(f);
    document.documentElement.classList.toggle("fb-on", mode);
    if (!timer) {
      void refreshFeedback();
      timer = setInterval(() => void refreshFeedback(), 30000);
    }
    return () => {
      subs.delete(f);
      if (!subs.size && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, []);
  return { mode, list, err, drawer };
}

async function post(path: string, body: unknown) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `HTTP ${r.status}`);
  return j;
}

export async function submitFeedback(body: Record<string, unknown>) {
  const j = await post("/api/feedback", body);
  await refreshFeedback();
  return j as FbItem;
}

/** 项目方点“没修好”：打回成新反馈（只认登录项目方） */
export async function reopenFeedback(id: string, note = "") {
  const j = await post(`/api/feedback/${id}/status`, { status: "new", note, by: "owner" });
  await refreshFeedback();
  return j;
}

/** 浏览器地址 → data 下的相对路径（/files/x → x；/api/thumb?src=/files/x → x） */
export function fileOf(src: string | null | undefined): string | null {
  if (!src) return null;
  try {
    const u = new URL(src, location.origin);
    const s = u.pathname === "/api/thumb" ? u.searchParams.get("src") ?? "" : u.pathname;
    const m = /\/files\/(.+)$/.exec(decodeURIComponent(s.split("?")[0]));
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

export interface FbPick {
  el: HTMLElement;
  ep: number | null;
  shot: string | null;
  target: FbTarget;
  take: string | null;
  timecode: number | null;
  media: HTMLImageElement | HTMLVideoElement | null;
  summary: string;
}

const short = (t: string, n = 40) => t.replace(/\s+/g, " ").trim().slice(0, n);

function cssPath(el: HTMLElement): string {
  const tid = el.closest<HTMLElement>("[data-testid]")?.dataset.testid;
  if (tid) return `[data-testid="${tid}"]`;
  const parts: string[] = [];
  let e: HTMLElement | null = el;
  for (let i = 0; e && i < 4 && e !== document.body; i++, e = e.parentElement) {
    const cls = [...e.classList].filter((c) => !/^(on|sel|hl|dim|multi|live-flash)$/.test(c)).slice(0, 2).join(".");
    parts.unshift(`${e.tagName.toLowerCase()}${cls ? "." + cls : ""}`);
  }
  return parts.join(" > ");
}

/** 点到的元素 → 反馈上下文：镜号 / 对象（首帧 · 尾帧 · 视频 · 字段 · 界面）/ 版本 / 时间码 */
export function pickOf(raw: HTMLElement, epNum: number | null): FbPick {
  const media = (raw.closest("video") as HTMLVideoElement | null) ?? (raw.tagName === "IMG" ? (raw as HTMLImageElement) : (raw.closest(".v3-frame, .fs-fr, .oq-cell, .oq-fr")?.querySelector("img, video") as HTMLImageElement | HTMLVideoElement | null));
  const el = (media?.closest(".v3-frame, .fs-fr, .oq-cell, .oq-fr") as HTMLElement | null) ?? (media as HTMLElement | null) ?? (raw.closest("button, a, [role=button], .v3-k, .v3-v, p, li, td, h1, h2, h3, h4, span") as HTMLElement | null) ?? raw;
  const zl = media?.getAttribute("data-zoom-label") ?? el.querySelector("[data-zoom-label]")?.getAttribute("data-zoom-label") ?? "";
  const rowShot = raw.closest<HTMLElement>("[data-shot]")?.dataset.shot ?? null;
  const full = /ep(\d+)-S(\d+)/i.exec(rowShot ?? "") ?? /ep(\d+)-S(\d+)/i.exec(zl);
  const epM = /EP\s*0*(\d+)/i.exec(zl);
  const sM = /\bS0*(\d+)\b/.exec(zl);
  const ep = full ? Number(full[1]) : epM ? Number(epM[1]) : epNum;
  const shot = full ? `S${Number(full[2])}` : sM ? `S${Number(sM[1])}` : null;
  const isVideo = media?.tagName === "VIDEO" || /视频/.test(zl);
  const kind: FbTarget["kind"] = media ? (isVideo ? "video" : /尾帧/.test(zl) ? "last" : "first") : el.closest(".v3-info, .fo-d, .oq-tx") ? "field" : "ui";
  const fieldName = kind === "field" ? short((el.closest("div, p")?.querySelector(".v3-k")?.textContent ?? el.previousElementSibling?.textContent ?? ""), 12) || null : null;
  const takeM = /(?:#|第\s*|v)(\d+)/.exec(zl);
  const src = media ? (media as HTMLImageElement).currentSrc || media.getAttribute("src") : null;
  const timecode = media?.tagName === "VIDEO" ? Math.round((media as HTMLVideoElement).currentTime * 10) / 10 : null;
  const label = short(zl || el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || "", 60) || null;
  const target: FbTarget = { kind, field: fieldName, selector: kind === "ui" || kind === "field" ? cssPath(el) : null, label, file: fileOf(src) };
  const KW: Record<string, string> = { first: "首帧", last: "尾帧", video: "视频", field: "字段", ui: "界面", shot: "镜头", episode: "整集", other: "其它" };
  const summary = [ep != null ? `第 ${ep} 集` : "", shot ?? "", KW[kind] + (fieldName ? `「${fieldName}」` : ""), takeM ? `第 ${takeM[1]} 版` : "", timecode != null ? `${timecode.toFixed(1)} 秒` : "", kind === "ui" && label ? `「${short(label, 20)}」` : ""].filter(Boolean).join(" · ");
  return { el, ep, shot, target, take: takeM ? takeM[1] : null, timecode, media, summary };
}

/** 帧 / 视频截一张图（同源 /files 或 /api/thumb；跨源或没加载完返回 null） */
export function snapMedia(m: HTMLImageElement | HTMLVideoElement | null): string | null {
  if (!m) return null;
  try {
    const w = m instanceof HTMLVideoElement ? m.videoWidth : m.naturalWidth;
    const h = m instanceof HTMLVideoElement ? m.videoHeight : m.naturalHeight;
    if (!w || !h) return null;
    const k = Math.min(1, 1280 / Math.max(w, h));
    const c = document.createElement("canvas");
    c.width = Math.round(w * k);
    c.height = Math.round(h * k);
    c.getContext("2d")!.drawImage(m, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.85);
  } catch {
    return null;
  }
}
