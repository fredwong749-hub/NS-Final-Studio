import { useEffect, useState } from "react";
import type { LiveJob } from "../store";
import type { ShotSummary, Stage, TakeScore } from "../types";
import { JOB_LABEL, LAST_SOURCE_LABEL, REVIEW_LABEL } from "../util";

/** 每秒刷新一次（只在 on 时） */
export function useTick(on: boolean, ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => set((x) => x + 1), ms);
    return () => clearInterval(t);
  }, [on, ms]);
}

function elapsed(from?: string): string {
  if (!from) return "";
  const t = new Date(from).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 任务进度：排队第 N 位 / 渲染中 m:ss（不确定进度条） */
export function JobBar({ live, compact }: { live: LiveJob; compact?: boolean }) {
  const running = live.job.state === "running";
  useTick(running);
  return (
    <div className={`jobbar${running ? " running" : " queued"}${compact ? " compact" : ""}`}>
      <div className="jobbar-track">
        <i />
      </div>
      <span>
        {running ? `渲染中 ${elapsed(live.job.started_at ?? live.job.created_at)}` : `排队第 ${live.pos || "?"} 位`}
      </span>
    </div>
  );
}

export function scoreValue(sc: TakeScore | null | undefined): number | null {
  if (!sc || typeof sc.total !== "number") return null;
  return sc.total <= 1 ? Math.round(sc.total * 100) : Math.round(sc.total);
}

export function Score({ sc }: { sc: TakeScore | null | undefined }) {
  const v = scoreValue(sc);
  if (v == null) return null;
  const miss = sc?.missing?.length ?? 0;
  return (
    <span
      className={`chip ${miss ? "chip-warn" : v >= 80 ? "chip-ok" : "chip-dark"}`}
      title={[`评分 ${v}`, ...(miss ? [`缺：${sc!.missing!.join("、")}`] : []), ...(sc?.reasons ?? [])].join("\n")}
    >
      {v} 分
    </span>
  );
}

type StepState = "ok" | "warn" | "none" | "busy" | "bad";

/** 4 步状态：首帧 / 尾帧 / 视频 / 审核 */
export function steps(s: ShotSummary, liveOf: (stage: Stage) => LiveJob | undefined): [string, StepState, string][] {
  const one = (stage: Stage, has: boolean, label: string): [string, StepState, string] => {
    const lj = liveOf(stage);
    if (lj) return [label, "busy", lj.job.state === "running" ? "渲染中" : `排队第 ${lj.pos} 位`];
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

const STEP_ICON: Record<StepState, string> = { ok: "✓", warn: "!", none: "", busy: "…", bad: "✕" };

export function StepChips({ s, liveOf }: { s: ShotSummary; liveOf: (stage: Stage) => LiveJob | undefined }) {
  return (
    <span className="steps">
      {steps(s, liveOf).map(([k, st, t]) => (
        <span key={k} className={`step step-${st}`} title={`${k}：${t}`}>
          {STEP_ICON[st] && <b>{STEP_ICON[st]}</b>}
          {k}
        </span>
      ))}
    </span>
  );
}

export const lastSourceLabel = (s: ShotSummary) => (s.last_frame_source ? LAST_SOURCE_LABEL[s.last_frame_source] : "");
export { JOB_LABEL };
