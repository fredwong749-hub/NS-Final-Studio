// L-128 / L-210 成人镜“本人触发”：数据与提交（PW-019：.tsx 只导出组件，非组件的东西放这里）。
// 只拿文字（镜号 / 秒数 / 状态），后端不回图、不回画面描述。
import { useEffect, useState } from "react";

export type AdultState = "waiting" | "triggered" | "rendering" | "done";
export type AdultShot = { shot: string; index: number; seconds: number | null; state: AdultState; state_word: string };
export type AdultEp = { ep: number; shots: AdultShot[]; counts: Record<AdultState, number>; waiting: number };
export type AdultList = { run: string; episodes: AdultEp[]; waiting: number; can_trigger: boolean };

const API = "/api/owner/adult-trigger";
let cache: AdultList | null = null;
let inflight: Promise<AdultList | null> | null = null;
const subs = new Set<(d: AdultList | null) => void>();

function publish(d: AdultList | null) {
  cache = d;
  subs.forEach((f) => f(d));
}

export function loadAdult(force = false): Promise<AdultList | null> {
  if (cache && !force) return Promise.resolve(cache);
  if (inflight) return inflight;
  inflight = fetch(API)
    .then((r) => (r.ok ? (r.json() as Promise<AdultList>) : null))
    .catch(() => null)
    .then((d) => {
      inflight = null;
      if (d) publish(d);
      return d;
    });
  return inflight;
}

/** 全页共用一份（总览每集一个按钮，不每集各拉一次）；60 秒刷新一次状态 */
export function useAdult(): AdultList | null {
  const [d, setD] = useState<AdultList | null>(cache);
  useEffect(() => {
    subs.add(setD);
    void loadAdult();
    const t = window.setInterval(() => void loadAdult(true), 60000);
    return () => {
      subs.delete(setD);
      window.clearInterval(t);
    };
  }, []);
  return d;
}

/** 本人点了确认才发；by 由后端从登录会话取 */
export async function triggerAdult(body: { episode?: number; objects?: string[]; note?: string }): Promise<void> {
  const r = await fetch(API, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ run: cache?.run, ...body }) });
  if (!r.ok) {
    let msg = "没有记下来，请再点一次";
    try {
      const j = (await r.json()) as { detail?: string };
      if (j?.detail) msg = j.detail;
    } catch {
      /* 读不出原因就用默认那句 */
    }
    throw new Error(msg);
  }
  const j = (await r.json()) as { listing?: AdultList };
  if (j.listing) publish({ ...j.listing, can_trigger: true });
  else void loadAdult(true);
}

export const fmtSecs = (s: number | null) => (s ? `${s} 秒` : "");
