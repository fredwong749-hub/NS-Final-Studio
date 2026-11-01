// PW-019：从 ShotCard.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { jobStageText } from "./frames.helpers";
import type { Job, ShotDetail, ShotSummary, Stage, TakeScore } from "../types";
import { isFailed, JOB_LABEL, LAST_SOURCE_LABEL, REVIEW_LABEL } from "../util";

export type Cell = "ok" | "warn" | "bad" | "none" | "busy";

/** 四格状态条：首帧 / 尾帧 / 视频 / 审核（规范 §3.1） */
export function mediaChain(s: ShotSummary, d: ShotDetail | undefined, job: Job | undefined): [string, Cell, string][] {
  const failed = isFailed(s, job, d);
  const jobStage = job && (job.state === "queued" || job.state === "running" || job.state === "failed") ? job.stage : null;
  const cell = (stage: Stage, has: boolean): [Cell, string] => {
    const stale = s.stale[stage] ?? [];
    if (s.job && jobStage === stage) return ["busy", (job?.progress?.stage !== "queued" && jobStageText(job)) || JOB_LABEL[s.job]];
    if (failed && jobStage === stage) return ["bad", "渲染失败"];
    if (!has) return ["none", "缺失"];
    if (stale.length) return ["warn", `已过期：${stale.join("、")}`];
    return ["ok", "最新"];
  };
  const [ic, it] = cell("image", !!s.first_frame);
  const [lc, lt0] = cell("last", !!s.last_frame_target);
  const lt = s.last_frame_source ? `${lt0}（来源：${LAST_SOURCE_LABEL[s.last_frame_source]}）` : lt0;
  const [vc, vt] = cell("video", !!s.video);
  const r = s.review.state;
  const rc: Cell = r === "passed" ? "ok" : r === "rejected" ? "bad" : "none";
  return [
    ["首帧", ic, it],
    ["尾帧", lc, lt],
    ["视频", vc, vt],
    ["审核", rc, REVIEW_LABEL[r] + (s.review.reason ? `：${s.review.reason}` : "")],
  ];
}

export function scoreTitle(sc: TakeScore): string {
  return [`评分 ${sc.total}`, ...(sc.missing?.length ? [`缺：${sc.missing.join("、")}`] : []), ...(sc.reasons ?? [])].join("\n");
}
