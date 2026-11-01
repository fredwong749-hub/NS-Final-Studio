import type { Episode, Job, LookConflict, ReviewState, ShotDetail, ShotSummary, Stage, Take } from "./types";

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

export const JOB_LABEL: Record<string, string> = { queued: "排队", running: "渲染中", done: "完成", failed: "失败", interrupted: "中断" };
// fredw-92/UXF5（审查 N10）：v1 任务的阶段是 frame / first / asset_gen，以前原样显示英文
export const STAGE_LABEL: Record<string, string> = { image: "首帧", frame: "首帧", first: "首帧", last: "尾帧", video: "视频", asset: "资产出图", asset_gen: "资产生成" };
/** fredw-92/UXF5（审查 #5 / N10）：被 API 重启打断的任务不是画面问题，单独算“中断”，不计入失败、不标红 */
export const isInterrupted = (j: { state: string; error?: string | null }) => j.state === "failed" && /API 重启/.test(j.error ?? "");
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
export type Filter = "all" | "unreviewed" | "rejected" | "passed" | "stale" | "failed" | "edited" | "missing" | "missing_last" | "no_expr" | "explicit";
/** 露骨红标（gpu3 status.json / BLOCKED.jsonl / 剧本 **H3校验**）：项目方自行处理 */
export const EXPLICIT_LABEL = "露骨·项目方自行处理";
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
  explicit: "仅看红标",
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
    case "explicit": return !!s.explicit_hold;
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

/** 某阶段的版本链：gpu3 负责的镜头看 gpu3 版本链（只读；gpu3 的尾帧 = 视频版本的尾帧 last_url），否则看笔记本 takes */
/** fredw-92/UXF1（审查 #6）：这一镜的帧走哪条链——与后端 _chain_fields 一致：摘要 frames_source = laptop（画布负责、画布有版本）
 *  时只看画布链；gpu3_takes 存在但不是出片用的那条链时只是历史。以前查看器只要有 gpu3_takes 就读 gpu3 链 → 两个“当前首帧” */
export const usesGpu3Chain = (d: ShotDetail | undefined): boolean => !!d?.gpu3_takes && d.summary?.frames_source !== "laptop";

export function stageTakes(d: ShotDetail | undefined, stage: Stage): Take[] {
  if (d?.gpu3_takes && usesGpu3Chain(d)) {
    const want = stage === "image" ? "image" : "video";
    return d.gpu3_takes.takes
      .filter((t) => t.stage === want)
      .map((t) => (stage === "last" ? { ...t, url: t.last_url ?? null } : t))
      .sort((a, b) => a.n - b.n);
  }
  return (d?.takes.takes ?? []).filter((t) => t.stage === stage).sort((a, b) => a.n - b.n);
}

/** 某阶段的当前版本号（gpu3：尾帧跟随当前视频版本） */
export function stageActive(d: ShotDetail | undefined, stage: Stage): number | undefined {
  if (d?.gpu3_takes && usesGpu3Chain(d)) {
    const a = d.gpu3_takes.active as Record<string, number | undefined>;
    return stage === "image" ? a.image : a.video;
  }
  return (d?.takes.active as Partial<Record<Stage, number>> | undefined)?.[stage];
}

/** 尾帧缺独立版本时的“预期来源”（E1/E3）：gpu3 尾帧目标 > 视频末帧 > 下一镜首帧 > 由本镜首帧编辑 */
export interface ExpectedLast {
  kind: "gpu3" | "video" | "next" | "edit" | "none";
  label: string;
  /** 能预览的图（视频末帧时为视频地址，由 <video> 定位到末尾） */
  url: string | null;
  hint: string;
  /** url 是视频（要定位到末尾显示） */
  isVideo?: boolean;
}
export function expectedLast(s: ShotSummary): ExpectedLast {
  // 跨集时写全镜号（ep02-S1），同集只写 S1
  const nextIdx = !s.next_shot ? "" : s.next_shot.slice(0, 4) === s.id.slice(0, 4) ? s.next_shot.split("-")[1] : s.next_shot;
  if (s.gpu3?.last_frame)
    return { kind: "gpu3", label: "gpu3 尾帧目标", url: s.gpu3.last_frame, hint: `gpu3 链已有尾帧目标（${s.gpu3.last_from || "last.png"}），画布还没同步为本镜尾帧` };
  if (s.last_frame_actual || s.video)
    return {
      kind: "video",
      label: "视频末帧（实际）",
      url: s.last_frame_actual ?? s.video,
      isVideo: !s.last_frame_actual,
      hint: "视频已出但没有独立尾帧：这里显示视频最后一帧，只作参考，不是给视频用的尾帧目标",
    };
  if (s.next_first_frame)
    return { kind: "next", label: `下一镜首帧（${nextIdx}）`, url: s.next_first_frame, hint: `没有独立尾帧时，衔接参考 = ${nextIdx} 的首帧；要锁定为尾帧请在“其他来源”里选` };
  if (s.first_frame) return { kind: "edit", label: "由本镜首帧编辑", url: null, hint: "尾帧 = 以本镜首帧为底图、按尾帧提示词编辑出来（gpu3 出）" };
  return { kind: "none", label: "先出首帧", url: null, hint: "尾帧以首帧为底图：首帧出来后才能出尾帧" };
}

/** 规则 7（项目方 2026-10-30：“视频只渲染一次，全部在 gpu3”）：笔记本出视频默认关闭，
 *  只在开发者开关打开时可用——localStorage `ns.dev.laptopVideo` = "1"，或打开一次 `?devLaptopVideo=1`（`=0` 关闭）。 */
export function laptopVideoEnabled(): boolean {
  try {
    const q = new URLSearchParams(location.search).get("devLaptopVideo");
    if (q === "1" || q === "0") localStorage.setItem("ns.dev.laptopVideo", q);
    return localStorage.getItem("ns.dev.laptopVideo") === "1";
  } catch {
    return false;
  }
}
