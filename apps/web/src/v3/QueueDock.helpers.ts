import { useEffect, useState } from "react";

export type Item = { oid: string; shot: string; ep: number; idx: number; kind: "first" | "last"; state: "running" | "queued"; pos: number; eta_at: number; redo: boolean };
type Mine = { id: string; shot: string; stage: "first" | "last"; state: string; word: string; pos: number | null; eta_at: number | null; text: string; msg: string };
export type Q = { per_shot_s: number; lanes: number; running: number; queued: number; stale?: boolean | null; items: Item[]; mine: Mine[] };

export function useFrameQueue(ms = 5000): Q | null {
  const [q, setQ] = useState<Q | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch("/api/frame-queue")
        .then((r) => (r.ok ? (r.json() as Promise<Q>) : null))
        .then((x) => alive && x && setQ(x))
        .catch(() => undefined);
    load();
    const t = window.setInterval(load, ms);
    window.addEventListener("ns-frames-refresh", load);
    return () => {
      alive = false;
      window.clearInterval(t);
      window.removeEventListener("ns-frames-refresh", load);
    };
  }, [ms]);
  return q;
}
