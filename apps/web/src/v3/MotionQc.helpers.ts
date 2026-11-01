// PW-019：从 MotionQc.tsx 挪出来的类型、取值和说明函数（组件文件只导出组件）。

export interface MotionQcMetrics {
  n?: number;
  fps?: number;
  duration_s?: number;
  mean_diff?: number;
  p90_diff?: number;
  max_diff?: number;
  still_frac?: number;
  frozen_tail_s?: number;
  frozen_head_s?: number;
  first_last_diff?: number;
  error?: string;
}

export interface MotionQc {
  verdict?: "pass" | "warn" | "fail" | "unknown" | string | null;
  labels?: string[] | null;
  reasons?: string[] | null;
  metrics?: MotionQcMetrics | null;
  take?: number | null;
}

export const f = (x: number | undefined, d = 2) => (typeof x === "number" ? x.toFixed(d) : "—");

export function motionTip(q: MotionQc | null | undefined): string {
  if (!q) return "";
  const m = q.metrics ?? {};
  if (m.error) return `运动质检失败：${m.error}`;
  const lines = [
    `运动质检：${q.verdict === "fail" ? "不合格" : q.verdict === "warn" ? "提示" : q.verdict === "pass" ? "通过" : "未知"}`,
    ...(q.reasons ?? []),
    `平均帧差 ${f(m.mean_diff)} · p90 ${f(m.p90_diff)} · 最大 ${f(m.max_diff, 1)}（0–255，正常有动作 > 1）`,
    `静止帧 ${typeof m.still_frac === "number" ? Math.round(m.still_frac * 100) : "—"}% · 开头定住 ${f(m.frozen_head_s, 1)}s · 结尾定住 ${f(m.frozen_tail_s, 1)}s`,
    `首帧↔尾帧差 ${f(m.first_last_diff, 1)} · ${m.n ?? "—"} 帧 / ${f(m.duration_s, 1)}s`,
  ];
  return lines.join("\n");
}

/** 通过 / 没质检过 → 不渲染 */

export const motionOf = (t: { qc?: unknown } | null | undefined): MotionQc | null =>
  ((t?.qc as { motion?: MotionQc } | null | undefined)?.motion ?? null);
