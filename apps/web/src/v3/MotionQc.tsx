// fredw-92/QCV：视频运动量质检角标（ns_render.motion_qc 写在 take.qc.motion，摘要里是 video_qc）。
// “静止·不合格”（红）/ “结尾定住 Ns”“动作偏弱”（黄）；通过的不显示。悬停看数字（相邻帧平均差 0–255）。

import { motionTip, type MotionQc } from "./MotionQc.helpers";
export type { MotionQc, MotionQcMetrics } from "./MotionQc.helpers";

export function MotionQcBadge({ q, className = "" }: { q: MotionQc | null | undefined; className?: string }) {
  if (!q || !q.verdict || q.verdict === "pass") return null;
  const cls = q.verdict === "fail" ? "bad" : "warn";
  const text = (q.labels ?? []).join(" · ") || (q.verdict === "fail" ? "静止·不合格" : "运动质检提示");
  return (
    <b className={`mqc ${cls} ${className}`} title={motionTip(q)}>
      {text}
    </b>
  );
}

/** take（TakeX）上的 qc.motion */
