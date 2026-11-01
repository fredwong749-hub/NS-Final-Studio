// PW-019：从 EpisodeProduce.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { useSyncExternalStore } from "react";

export type Stage = "first" | "last" | "video";

export type StageState = "pending" | "ready" | "queued" | "running" | "review" | "done" | "skipped" | "failed" | "blocked" | "waiting" | "cancelled";

export type ProduceStage = {
  state: StageState;
  step?: "gen" | "final" | "video" | null;
  gpu?: number | string | null;
  lane?: string | null;
  take?: number | null;
  reason?: string | null;
  error?: string | null;
  frames?: number | null;
  locked_by?: string | null;
  eta_s?: number;
  /** 超过所有卡的单卡上限：没有能出的卡 */
  no_lane?: boolean;
  /** 以前自动测试定稿的，没重出，等项目方复审 */
  auto_review?: boolean;
};

export type ProduceView = {
  episode: number;
  id?: string;
  state: "none" | "running" | "waiting" | "done" | "cancelled";
  mode?: "auto_lock" | "review";
  stages?: Stage[];
  eta_s: number;
  counts?: Record<string, number>;
  lanes: { gpu: number | string; id?: string; label?: string; ok?: boolean; image_pref?: boolean; max_frames?: number; busy_with: { shot_id: string; stage: Stage; state: string; step?: string }[] }[];
  shots: { shot_id: string; eta_s: number; stages: Partial<Record<Stage, ProduceStage>> }[];
  failures?: { shot_id: string; stage: Stage; state: string; reason?: string; error?: string }[];
};

// ---------------------------------------------------------------- 共享进度（集号 → 视图）
export const views = new Map<number, ProduceView>();

export const subs = new Set<() => void>();

export const subscribe = (f: () => void) => (subs.add(f), () => void subs.delete(f));

export function useProduceView(ep: number): ProduceView | undefined {
  return useSyncExternalStore(subscribe, () => views.get(ep));
}
