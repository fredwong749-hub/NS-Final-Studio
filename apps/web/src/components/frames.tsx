
import type { LiveJob } from "../store";
import type { ShotSummary, Stage, TakeScore } from "../types";
import { jobStageText, scoreValue, steps, useTick, type StepState, elapsed } from "./frames.helpers";

/** 任务进度：阶段名 · 本段用时（有 job.progress 时）；否则 排队第 N 位 / 渲染中 m:ss（不确定进度条） */
export function JobBar({ live, compact }: { live: LiveJob; compact?: boolean }) {
  const running = live.job.state === "running";
  useTick(running || !!live.gpu3, live.gpu3 ? 15000 : 1000);
  if (live.gpu3)
    // 已请 gpu3：笔记本看不到 gpu3 队列位置（缺接口），只显示等了多久；新 take 到达后自动消失
    return (
      <div className={`jobbar gpu3${compact ? " compact" : ""}`} title="已写进 gpu3 重渲队列，等 gpu3 出新 take；新版本到了会自动出现在版本条">
        <div className="jobbar-track">
          <i />
        </div>
        <span>
          已请 gpu3 · 等待 {elapsed(live.job.created_at).replace(/:\d\d$/, "")} 分
          {live.clear && !compact && (
            <button
              className="link jobbar-x"
              title="撤销本地等待标记（请求丢了 / 想再请一次）；不会取消 gpu3 上已排的任务"
              onClick={(e) => (e.stopPropagation(), live.clear!())}
            >
              撤标记
            </button>
          )}
        </span>
      </div>
    );
  return (
    <div className={`jobbar${running ? " running" : " queued"}${compact ? " compact" : ""}`}>
      <div className="jobbar-track">
        <i />
      </div>
      <span>
        {(live.job.progress?.stage !== "queued" && jobStageText(live.job)) ||
          (running ? `渲染中 ${elapsed(live.job.started_at ?? live.job.created_at)}` : `排队第 ${live.pos || "?"} 位`)}
      </span>
    </div>
  );
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

