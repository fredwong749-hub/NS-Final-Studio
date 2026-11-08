// NAVIA：顶栏五个 tab 的圆点（只用 灰 / 琥珀呼吸 / 琥珀实心 / 绿）与数字。优先级：琥珀实心 > 琥珀呼吸 > 灰 > 绿。
import { NS2_OVERVIEW, toSummary, type Ov } from "./ns2";
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
// P5 M2：顶栏视频圆点改读新 ns2 唯一总览（口径 ns2/overview.py）
export const useVideosSummary = () => usePoll<VideosSummary>(NS2_OVERVIEW, (d: Ov) => (d.videos ? toSummary(d) : null));
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

// ---------------------------------------------------------------- NAVFLOW-F 11-03（L-146）：各集生产进度（唯一来源 GET /api/pipeline/status，后端转调 sop_gate）
export type PipeStepId = "script" | "assets" | "board" | "frames" | "video" | "cut";
export type PipeCellState = "done" | "doing" | "blocked" | "todo";
export type PipeCell = { state: PipeCellState; plain: string; why: string }; // plain = 页面显示的大白话；why = sop_gate 原文（只给开发者，页面不显示）
export type PipeEpisode = { episode: number; cells: Record<PipeStepId, PipeCell>; stage: string; plain: string; why: string; retro?: string | null };
export type PipeStatus = {
  run: string;
  title: string;
  episodes_total: number;
  steps: { id: PipeStepId; label: string }[];
  episodes: PipeEpisode[];
  done: Record<PipeStepId, number>;
  lit: Record<PipeStepId, boolean>;
};
/** 六步对应的页面（点格子 / 点步骤去哪）；集号由调用方拼 */
export const PIPE_STEP_TO: Record<PipeStepId, (ep: number) => string> = {
  script: (ep) => `#/script-create?ep=${ep}`,
  assets: () => "#/assets",
  board: (ep) => `#ep${String(ep).padStart(2, "0")}`,
  frames: (ep) => `#/frames?ep=${ep}`,
  video: (ep) => `#/videos?ep=${ep}`,
  cut: () => "#/cut",
};
export const PIPE_CELL_GLYPH: Record<PipeCellState, string> = { done: "✓", doing: "●", blocked: "⚠", todo: "·" };
export const PIPE_CELL_WORD: Record<PipeCellState, string> = { done: "完成", doing: "进行中", blocked: "卡住", todo: "未开始" };

let _pipeCache: { at: number; v: PipeStatus | null; err: string | null } | null = null;
const _pipeSubs = new Set<() => void>();
async function _pipeLoad(run: string | null) {
  try {
    const r = await fetch(`/api/pipeline/status${run ? `?run=${encodeURIComponent(run)}` : ""}`);
    if (!r.ok) {
      const d = (await r.json().catch(() => ({}))) as { detail?: string };
      _pipeCache = { at: Date.now(), v: null, err: r.status === 404 ? "进度接口还没生效（后台重启后出现）" : d.detail ?? `HTTP ${r.status}` };
    } else _pipeCache = { at: Date.now(), v: (await r.json()) as PipeStatus, err: null };
  } catch (e) {
    _pipeCache = { at: Date.now(), v: null, err: String((e as Error).message ?? e) };
  }
  _pipeSubs.forEach((f) => f());
}
/** 顶栏和总览矩阵共用一份（30 s 刷新；多处挂载只请求一次）。读不到 → {v:null, err} 页面写明，不猜 */
export function usePipelineStatus(run: string | null = null): { v: PipeStatus | null; err: string | null; reload: () => void } {
  const [, setTick] = useState(0);
  useEffect(() => {
    const f = () => setTick((n) => n + 1);
    _pipeSubs.add(f);
    if (!_pipeCache || Date.now() - _pipeCache.at > 30000) void _pipeLoad(run);
    const t = window.setInterval(() => void _pipeLoad(run), 30000);
    return () => {
      _pipeSubs.delete(f);
      window.clearInterval(t);
    };
  }, [run]);
  return { v: _pipeCache?.v ?? null, err: _pipeCache?.err ?? null, reload: () => void _pipeLoad(run) };
}
