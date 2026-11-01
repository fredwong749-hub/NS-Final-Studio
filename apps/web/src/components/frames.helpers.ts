// PW-019：从 frames.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { useEffect, useState } from "react";
import type { LiveJob } from "../store";
import type { Job, ShotSummary, Stage, TakeScore } from "../types";
import { LAST_SOURCE_LABEL, REVIEW_LABEL } from "../util";

/** 每秒刷新一次（只在 on 时） */
export function useTick(on: boolean, ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => set((x) => x + 1), ms);
    return () => clearInterval(t);
  }, [on, ms]);
}

export function elapsed(from?: string): string {
  if (!from) return "";
  const t = new Date(from).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const PROGRESS_DONE = new Set(["done", "failed", "cancelled"]);

/** IMGPERF（11-01，UIAUDIT 打回 r1）：任务当前阶段的人话——job.progress.label（如“GPU 出图”“ComfyUI 排队（前面 2 个）”
 *  “上传参考图 2”）+ 本段用时（progress.since 起）；后端没给 progress（旧任务 / 旧 API）→ null，调用方回落原文案 */
export function jobStageText(job: Job | undefined | null): string | null {
  const p = job?.progress;
  if (!p || !p.label || PROGRESS_DONE.has(p.stage)) return null;
  const step = p.total && p.step != null && !/\d/.test(p.label) ? ` ${p.step}/${p.total}` : "";
  const t = elapsed(p.since ?? undefined);
  return `${p.label}${step}${t ? ` · ${t}` : ""}`;
}

export function scoreValue(sc: TakeScore | null | undefined): number | null {
  if (!sc || typeof sc.total !== "number") return null;
  return sc.total <= 1 ? Math.round(sc.total * 100) : Math.round(sc.total);
}

export type StepState = "ok" | "warn" | "none" | "busy" | "bad";

/** 4 步状态：首帧 / 尾帧 / 视频 / 审核 */
export function steps(s: ShotSummary, liveOf: (stage: Stage) => LiveJob | undefined): [string, StepState, string][] {
  const one = (stage: Stage, has: boolean, label: string): [string, StepState, string] => {
    const lj = liveOf(stage);
    if (lj)
      return [label, "busy", lj.gpu3 ? "已请 gpu3，等新 take" : (lj.job.progress?.stage !== "queued" && jobStageText(lj.job)) || (lj.job.state === "running" ? "渲染中" : `排队第 ${lj.pos} 位`)];
    if (!has) return [label, "none", "还没有"];
    const st = s.stale[stage] ?? [];
    if (st.length) return [label, "warn", `已过期：${st.join("、")}`];
    return [label, "ok", "最新"];
  };
  const r = s.review.state;
  return [
    one("image", !!s.first_frame, "首帧"),
    one("last", !!s.last_frame_target, "尾帧"),
    one("video", !!s.video, "视频"),
    ["审核", r === "passed" ? "ok" : r === "rejected" ? "bad" : "none", REVIEW_LABEL[r] + (s.review.reason ? `：${s.review.reason}` : "")],
  ];
}

export const lastSourceLabel = (s: ShotSummary) => (s.last_frame_source ? LAST_SOURCE_LABEL[s.last_frame_source] : "");
