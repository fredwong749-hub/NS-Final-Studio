// UIRSI r43（OVERVIEW_REDESIGN §4.1 / K1）：生产健康的共用轮询（GET /api/factory/health，8 s）。
// 顶栏“出图 N/5 道在出”和总览的生产灯都读它；接口还没上线（404）就停，用旧口径兜底。
import { useEffect, useState } from "react";

export type FLane = { id: string; label: string; state: "busy" | "idle" | "down" | "warn" | "faulty"; util?: number | null; queue?: number; last_s?: number | null; median_s?: number | null; text: string; tech?: string };
export type FVqa = { id: string; label: string; state: "busy" | "idle" | "down" | "warn"; queue: number | null; served?: number | null; text: string; tech?: string };
export type FHealth = {
  at: string;
  lanes: FLane[];
  vqa: FVqa[];
  phases: { id: string; label: string; phase: string | null; text: string }[];
  producer: { state: string; text: string; inflight?: number | null };
  busy?: number;
  total?: number;
  light?: { level: "ok" | "warn" | "bad"; text: string };
  source?: string;
};

let cur: FHealth | null = null;
let dead = false;
let timer = 0;
const subs = new Set<() => void>();
function poll() {
  fetch("/api/factory/health")
    .then((r) => {
      if (r.status === 404) {
        dead = true;
        return null;
      }
      return r.ok ? (r.json() as Promise<FHealth>) : null;
    })
    .then((d) => {
      if (d) cur = d;
    })
    .catch(() => {})
    .finally(() => {
      subs.forEach((f) => f());
      if (dead) stop();
    });
}
function start() {
  if (timer || dead) return;
  poll();
  timer = window.setInterval(poll, 8000);
}
function stop() {
  window.clearInterval(timer);
  timer = 0;
}

export function useFactory(): { data: FHealth | null; dead: boolean } {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    subs.add(f);
    start();
    return () => {
      subs.delete(f);
      if (!subs.size) stop();
    };
  }, []);
  return { data: cur, dead };
}

if (import.meta.hot) import.meta.hot.dispose(() => stop());
