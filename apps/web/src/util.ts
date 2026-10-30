import type { Episode, Job, LookConflict, ReviewState, ShotDetail, ShotSummary } from "./types";

export function shotLine(s: Pick<ShotSummary, "dialogue" | "voiceover">): { text: string; vo: boolean } {
  const d = s.dialogue[0];
  if (d) return { text: `${d.speaker_note ? d.speaker_note + "：" : ""}${d.text}`, vo: !!s.voiceover };
  if (s.voiceover) return { text: s.voiceover.text, vo: true };
  return { text: "", vo: false };
}

/** jobs 按时间倒序；返回每个镜头最新的一条任务 */
export function latestJobs(jobs: Job[]): Map<string, Job> {
  const m = new Map<string, Job>();
  for (const j of jobs) if (!m.has(j.shot_id)) m.set(j.shot_id, j);
  return m;
}

export const isActiveJob = (j: Job) => j.state === "queued" || j.state === "running";

export const JOB_LABEL: Record<string, string> = { queued: "排队", running: "渲染中", done: "完成", failed: "失败" };
export const STAGE_LABEL: Record<string, string> = { image: "首帧", last: "尾帧", video: "视频", asset: "资产出图" };
export const LAST_SOURCE_LABEL: Record<string, string> = { gen: "生成", next: "next", upload: "上传", video: "视频抽帧", gpu3: "gpu3" };
export const SLOT_LABEL: Record<string, string> = { outfit: "衣", shoes: "鞋", nails: "甲", hair: "发", makeup: "妆", accessory: "饰", other: "他" };
export const SLOT_NAME: Record<string, string> = { outfit: "服装", shoes: "鞋", nails: "美甲", hair: "发型", makeup: "妆容", accessory: "饰品", other: "其他" };
export const REVIEW_LABEL: Record<ReviewState, string> = { unreviewed: "未审", passed: "通过", rejected: "打回" };
export const REJECT_CODES = ["画面", "表情", "造型", "连贯", "口型", "尾帧", "其他"] as const;

/** 打回原因存成 "码｜备注" */
export function parseReason(r: string): { code: string; note: string } {
  const i = r.indexOf("｜");
  if (i < 0) return (REJECT_CODES as readonly string[]).includes(r) ? { code: r, note: "" } : { code: "", note: r };
  return { code: r.slice(0, i), note: r.slice(i + 1) };
}
export const joinReason = (code: string, note: string) => (note.trim() ? `${code}｜${note.trim()}` : code);

export function fmtTime(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export const epCode = (n: number) => `ep${String(n).padStart(2, "0")}`;

/** 失败：最新任务失败；或 errors.json 晚于所有版本 */
export function isFailed(s: ShotSummary, job: Job | undefined, d?: ShotDetail): boolean {
  if (s.job) return false;
  if (job) return job.state === "failed";
  if (d?.error) {
    const lastTake = d.takes.takes.reduce((m, t) => (t.created_at > m ? t.created_at : m), "");
    return d.error.at > lastTake;
  }
  return false;
}

export const staleList = (s: ShotSummary) => [...(s.stale.image ?? []), ...(s.stale.last ?? []), ...(s.stale.video ?? [])];
export const isStale = (s: ShotSummary) => staleList(s).length > 0;

// ---------- 过滤 ----------
export type Filter = "all" | "unreviewed" | "rejected" | "passed" | "stale" | "failed" | "edited" | "missing" | "missing_last" | "no_expr";
export const FILTER_LABEL: Record<Filter, string> = {
  all: "全部",
  unreviewed: "待审",
  rejected: "打回",
  passed: "通过",
  stale: "已过期",
  failed: "失败",
  edited: "有修改",
  missing: "缺首帧",
  missing_last: "缺尾帧",
  no_expr: "表情未标注",
};
export function matchFilter(f: Filter, s: ShotSummary, job: Job | undefined): boolean {
  switch (f) {
    case "all": return true;
    case "unreviewed": return s.review.state === "unreviewed";
    case "rejected": return s.review.state === "rejected";
    case "passed": return s.review.state === "passed";
    case "stale": return isStale(s);
    case "failed": return isFailed(s, job);
    case "edited": return s.edited;
    case "missing": return !s.first_frame;
    case "missing_last": return !s.last_frame_target;
    case "no_expr": return s.expression.source === "none";
  }
}

// ---------- 造型标签 ----------
export interface LookTag {
  character: string;
  label: string;
  lookId: string | null;
  override: boolean;
  changed: boolean;
  changedFields: string[];
  conflicts: LookConflict[];
}

export function flatShots(episodes: Episode[]): ShotSummary[] {
  return episodes.flatMap((e) => e.shots);
}

export const epOfShot = (id: string) => Number(id.slice(2, 4));

/** 按逗号切分做段级 diff（提示词主要以逗号分段） */
export function segDiff(a: string, b: string): { text: string; op: "same" | "add" | "del" }[] {
  const A = a.split(/(?<=[，,。；;])/);
  const B = b.split(/(?<=[，,。；;])/);
  const n = A.length, m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { text: string; op: "same" | "add" | "del" }[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push({ text: A[i], op: "same" }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ text: A[i++], op: "del" });
    else out.push({ text: B[j++], op: "add" });
  }
  while (i < n) out.push({ text: A[i++], op: "del" });
  while (j < m) out.push({ text: B[j++], op: "add" });
  return out;
}

export function isTypingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}
