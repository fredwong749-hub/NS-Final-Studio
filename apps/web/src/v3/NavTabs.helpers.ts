// NAVIA：顶栏五个 tab 的圆点（只用 灰 / 琥珀呼吸 / 琥珀实心 / 绿）与数字。优先级：琥珀实心 > 琥珀呼吸 > 灰 > 绿。
import { useEffect, useState } from "react";

export type VideosSummary = { total: number; final: number; rendering: number; queued: number; pending_review: number; need_frames: number; todo: number; failed: number; eta_all: string | null; median_s: number };
export type FramesCounts = { counts: { shots: number; missing: number; new: number; final: number }; gen: { running: number; queued: number } };
export type NavDot = { cls: "d-gray" | "d-yellow" | "d-green" | "d-breathe"; text: string; title: string };

/** 轮询某个只读接口（30 s），首次延后 1.8 s 不抢首屏；接口不存在 / 出错 → null（圆点退回灰色，不白板） */
function usePoll<T>(url: string, pick: (d: never) => T | null): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(url)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => alive && setV(d ? pick(d as never) : null))
        .catch(() => undefined);
    const first = window.setTimeout(load, 1800);
    const t = window.setInterval(load, 30000);
    return () => {
      alive = false;
      window.clearTimeout(first);
      window.clearInterval(t);
    };
  }, [url]); // eslint-disable-line react-hooks/exhaustive-deps
  return v;
}
export const useVideosSummary = () => usePoll<VideosSummary>("/api/videos/overview", (d: { summary: VideosSummary }) => d.summary ?? null);
export const useFramesCounts = () => usePoll<FramesCounts>("/api/frames-index", (d: FramesCounts) => (d.counts ? { counts: d.counts, gen: d.gen } : null));

/** 按优先级合成一个点：amber = 要你看 / 卡住；run = 在出；idle = 排队 / 没开始；其余 = 全部定稿 */
export function pickDot(amber: boolean, run: boolean, idle: boolean, text: string, title: string): NavDot {
  return { cls: amber ? "d-yellow" : run ? "d-breathe" : idle ? "d-gray" : "d-green", text, title };
}

export const fmtEta = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(+d) ? "" : `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export type PreviewSummary = { total: number; have: number; building: number; stale: number };
/** 成片 tab：逐集读 GET /api/episodes/{n}/preview 汇总（全集视角）；读不到 → null */
export function useEpisodePreviews(total: number): PreviewSummary | null {
  const [v, setV] = useState<PreviewSummary | null>(null);
  useEffect(() => {
    if (!total) return;
    let alive = true;
    const load = () =>
      Promise.all(
        Array.from({ length: total }, (_, i) =>
          fetch(`/api/episodes/${i + 1}/preview`)
            .then((r) => (r.ok ? (r.json() as Promise<{ url?: string | null; building?: boolean; stale?: boolean }>) : null))
            .catch(() => null),
        ),
      ).then((rows) => {
        if (!alive) return;
        const ok = rows.filter((x): x is { url?: string | null; building?: boolean; stale?: boolean } => !!x);
        setV(ok.length ? { total, have: ok.filter((x) => !!x.url).length, building: ok.filter((x) => x.building).length, stale: ok.filter((x) => x.stale).length } : null);
      });
    const first = window.setTimeout(load, 2200);
    const t = window.setInterval(load, 30000);
    return () => {
      alive = false;
      window.clearTimeout(first);
      window.clearInterval(t);
    };
  }, [total]);
  return v;
}
