// fredw-92/W4a：画布 v3 统一状态词表（规格 §5）——一个圆点 + 一句“下一步”，不写系统内部状态。
// 灰 未出 · 蓝 生成中 · 黄 待你审 · 绿 已定 · 红 失败。成人镜不加锁（项目方 2026-10-30：不做成人拦截）。
import type { Studio } from "../store";
import type { ShotDetail, ShotSummary, SopShot, Stage, Take } from "../types";
import { isFailed, STAGE_LABEL } from "../util";
import { getEdit } from "./edit/state";
import { SLOT_NAME, submitFrame, submitVideo } from "./edit/actions";

export type Dot = "gray" | "blue" | "yellow" | "green" | "red";
export const DOT_LABEL: Record<Dot, string> = { gray: "未出", blue: "生成中", yellow: "待你审", green: "已定", red: "失败" };

export interface NextAction {
  label: string;
  run: () => void;
  title?: string;
}

export interface ShotStatus {
  dot: Dot;
  /** STATUS_TABLE 的键（可选，兼容旧代码） */
  key?: StatusKey;
  /** 一句话：只说下一步 */
  text: string;
  action: NextAction | null;
  /** “为什么卡住”小窗的条目（就绪清单、SOP 阻塞、过期原因、打回原因） */
  why: { text: string; who?: string }[];
}

const STAGES: Stage[] = ["image", "last", "video"];

function whyList(s: ShotSummary, d: ShotDetail | undefined, sop: SopShot | undefined, err: string | null): ShotStatus["why"] {
  const out: ShotStatus["why"] = [];
  const seen = new Set<string>();
  const add = (text: string, who?: string) => {
    const k = text.trim();
    if (!k || seen.has(k)) return;
    seen.add(k);
    out.push({ text: k, who });
  };
  if (err) add(`上次生成失败：${err}`);
  if (s.review.state === "rejected") add(`已打回${s.review.reason ? `：${s.review.reason}` : ""}`, "项目方");
  for (const b of sop?.blockers ?? []) add(b.text, whoLabel(b.actor ?? b.actor_label));
  for (const r of s.readiness?.blocked_reasons ?? []) add(r);
  for (const r of s.readiness?.gpu3_blocked_reasons ?? []) add(r, "视频端");
  for (const st of STAGES) for (const r of staleOf(s, d, st)) add(`${STAGE_LABEL[st]}已过期${r ? `：${r}` : ""}`);
  return out;
}

/** “谁来处理”说人话（原则 4：不出现 gpu3 / owner / canvas 等内部词） */
const WHO: Record<string, string> = { gpu3: "视频端", GPU3: "视频端", canvas: "画布", owner: "项目方", qwen: "Qwen", Qwen: "Qwen" };
export const whoLabel = (x?: string | null) => (x ? WHO[x] ?? x : undefined);

/** 某格过期原因（镜头摘要 stale[stage] + takes.json 顶层 stale.{stage}）——过期判定只此一处 */
export function staleOf(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): string[] {
  const out = [...(s.stale?.[stage] ?? [])].filter((x) => x != null);
  const tst = (d?.takes as { stale?: Partial<Record<string, { reason?: string } | null>> } | undefined)?.stale?.[stage];
  if (tst) out.push(tst.reason ?? "");
  return out;
}

/** 一格的状态（v3.1 §5.1：定稿 + 过期 只算“过期·需重出”，不算定稿） */
export type FrameState = "none" | "draft" | "locked" | "stale";
export function frameState(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): FrameState {
  const has = stage === "image" ? !!s.first_frame : stage === "last" ? !!s.last_frame_target : !!s.video;
  if (!has) return "none";
  if (staleOf(s, d, stage).length) return "stale";
  if (stage !== "video" && lockedN(d, stage) != null) return "locked";
  return "draft";
}

/** 已定 = 首帧、尾帧都已定稿且都没过期（视频另计）——片段条统计、步骤条共用 */
export const framesLocked = (s: ShotSummary, d: ShotDetail | undefined) => frameState(s, d, "image") === "locked" && frameState(s, d, "last") === "locked";

/** 整集统计：状态点计数 + 已定 + 有视频，全部来自 shotStatus / frameState（v3.1 §1.7） */
export function episodeCounts(shots: ShotSummary[], st: Studio, sop?: { shots: SopShot[] } | null) {
  const dots: Record<Dot, number> = { gray: 0, blue: 0, yellow: 0, green: 0, red: 0 };
  let locked = 0;
  let videos = 0;
  const status = new Map<string, ShotStatus>();
  for (const s of shots) {
    const x = shotStatus(s, st, sop?.shots.find((y) => y.id === s.id));
    status.set(s.id, x);
    dots[x.dot]++;
    if (framesLocked(s, st.details[s.id])) locked++;
    if (s.video) videos++;
  }
  return { dots, locked, videos, status, secs: shots.reduce((a, s) => a + (s.duration.seconds || 0), 0) };
}

/** 把现有数据（镜头摘要、任务、就绪清单、SOP 阻塞）映射成 圆点 + 一句话 + 主按钮 */
export function shotStatus(s: ShotSummary, st: Studio, sop?: SopShot): ShotStatus {
  const job = st.latest.get(s.id);
  // 失败的那一步如果已经有成品（例如 gpu3 链后来出了首帧），不再整行标红，只在“为什么卡住”里留一条
  const failedStage = (job?.stage && job.stage !== "asset" ? job.stage : "image") as Stage;
  const have = failedStage === "image" ? !!s.first_frame : failedStage === "last" ? !!s.last_frame_target : !!s.video;
  const rawFailed = isFailed(s, job, st.details[s.id]);
  const failed = rawFailed && !have;
  const err = rawFailed ? job?.error ?? st.details[s.id]?.error?.last ?? "" : null;
  const why = whyList(s, st.details[s.id], sop, err);
  // F2：主按钮走 v1 任务（frame-jobs / video-jobs，gpu3），不再走旧 /render 与 gpu3 桥（会被 owner=gpu3 的 409、_video_ok 闸门挡住）
  const go = (stage: Stage) => () => {
    st.select(s.id);
    const gpu = getEdit().gpu;
    if (stage === "video") void submitVideo(s.id, { gpu: gpu as 3 | 0 }, st.notify, st.refreshAfter);
    else {
      const slot = stage === "image" ? "first" : "last";
      void submitFrame(s.id, { stage: slot, mode: "regen", gpu }, `出${SLOT_NAME[slot]}`, st.notify, st.refreshAfter);
    }
  };
  const edit = () => {
    st.select(s.id);
    st.setCanvasMode("edit");
  };
  const watch = () => {
    st.select(s.id);
    st.setReviewMode(true);
  };

  const runOf: Record<ActKind, () => void> = {
    "regen-first": go("image"),
    "regen-last": go("last"),
    video: go("video"),
    edit,
    watch,
    jobs: () => st.setDrawer({ open: true, tab: "jobs" }),
  };
  const make = (key: StatusKey, why0: ShotStatus["why"], over?: { text?: string; title?: string }): ShotStatus => {
    const r = STATUS_TABLE[key];
    return {
      dot: r.dot,
      key,
      text: over?.text ?? r.text,
      action: r.act ? { label: r.label, run: runOf[r.act], title: over?.title ?? r.title } : null,
      why: why0,
    };
  };

  // v1 任务（精修 / 主按钮提交的 frame-jobs、video-jobs）
  const vj = getEdit().jobs.find((j) => j.shot === s.id && j.slot !== "asset" && (j.state === "queued" || j.state === "running") && !j.notReady);
  if (vj) {
    const nm = vj.slot === "first" ? "首帧" : vj.slot === "last" ? "尾帧" : "视频";
    return make("job_v1", why, { text: `${nm}${vj.state === "running" ? "生成中" : "排队中"}，稍等` });
  }
  for (const stage of STAGES) {
    const lj = st.liveJob(s.id, stage);
    if (lj) {
      const where = lj.job.state === "running" ? "生成中" : lj.gpu3 ? "已排队" : `排队第 ${lj.pos || "?"} 位`;
      return make("job_old", why, { text: `${STAGE_LABEL[stage]}${where}，稍等` });
    }
  }
  if (failed) return make(failedStage === "image" ? "failed_first" : failedStage === "last" ? "failed_last" : "failed_video", why);
  if (s.review.state === "rejected") return make("rejected", why);
  // fredw-92 定：按定稿走——首帧未定稿 → 审首帧；首帧定稿、尾帧未定稿 → 审尾帧；都定稿、没视频 → 出视频；有视频 → 审视频
  // v3.1 §5.1：过期优先于定稿（定稿 + 过期 = 过期·需重出）；判定统一走 frameState
  const d = st.details[s.id];
  const fFirst = frameState(s, d, "image");
  const fLast = frameState(s, d, "last");
  const why1 = (stage: Stage) => staleOf(s, d, stage).filter(Boolean).join("；");
  if (fFirst === "none") return make("no_first", why);
  if (fFirst === "stale") return make("stale_first", why, { title: `首帧已过期：${why1("image") || "上游改过"}。直接重出首帧（要先改再出：⋯ → 进精修）` });
  if (fFirst !== "locked") return make("review_first", why);
  if (fLast === "stale") return make("stale_last", why, { title: `尾帧已过期：${why1("last") || "首帧定稿换了版本"}。由定稿首帧直接重出尾帧` });
  if (fLast !== "locked") return make(s.last_frame_target ? "review_last" : "need_last", why);
  if (!s.video) return make("need_video", why);
  if (frameState(s, d, "video") === "stale") return make("stale_video", why, { title: `视频已过期：${why1("video") || "上游改过"}` });
  if (s.review.state === "passed") return make("done", []);
  return make("review_video", why);
}

/** 主按钮做什么：regen-* / video = 直接提交 v1 任务（frame-job regen / video-job）；edit = 进精修；watch = 串播看视频；jobs = 打开任务队列 */
export type ActKind = "regen-first" | "regen-last" | "video" | "edit" | "watch" | "jobs";
export type StatusKey =
  | "job_v1" | "job_old" | "failed_first" | "failed_last" | "failed_video" | "rejected"
  | "no_first" | "stale_first" | "review_first" | "stale_last" | "need_last" | "review_last"
  | "need_video" | "stale_video" | "review_video" | "done";

/** 状态 ↔ 一句话 ↔ 主按钮 的唯一对照表（v3.1：状态写什么，主按钮就做什么；改对应关系只改这里） */
export const STATUS_TABLE: Record<StatusKey, { dot: Dot; text: string; label: string; act: ActKind | null; title?: string }> = {
  job_v1: { dot: "blue", text: "生成中，稍等", label: "看进度", act: "edit" },
  job_old: { dot: "blue", text: "排队中，稍等", label: "看进度", act: "jobs" },
  failed_first: { dot: "red", text: "首帧没出成，需重出", label: "重出首帧", act: "regen-first" },
  failed_last: { dot: "red", text: "尾帧没出成，需重出", label: "重出尾帧", act: "regen-last" },
  failed_video: { dot: "red", text: "视频没出成，需重出", label: "重出视频", act: "video" },
  rejected: { dot: "red", text: "已打回，去精修改", label: "去精修", act: "edit" },
  no_first: { dot: "gray", text: "还没有首帧，出首帧", label: "出首帧", act: "regen-first" },
  stale_first: { dot: "yellow", text: "首帧已过期，需重出", label: "重出首帧", act: "regen-first" },
  review_first: { dot: "yellow", text: "待你审首帧，满意就定稿", label: "审首帧", act: "edit", title: "进精修：对比版本、改图、定稿首帧" },
  stale_last: { dot: "yellow", text: "尾帧已过期，需重出", label: "重出尾帧", act: "regen-last" },
  need_last: { dot: "yellow", text: "首帧已定稿，下一步出尾帧", label: "出尾帧", act: "regen-last", title: "由定稿首帧出尾帧" },
  review_last: { dot: "yellow", text: "待你审尾帧，满意就定稿", label: "审尾帧", act: "edit", title: "进精修：对比版本、定稿尾帧" },
  need_video: { dot: "yellow", text: "首尾帧已定稿，下一步出视频", label: "出视频", act: "video" },
  stale_video: { dot: "yellow", text: "视频已过期，需重出", label: "重出视频", act: "video" },
  review_video: { dot: "yellow", text: "待你审视频", label: "看视频", act: "watch" },
  done: { dot: "green", text: "已定，无需操作", label: "看视频", act: "watch" },
};

/** 某阶段的定稿版本号：takes.json 顶层 locked:{stage:n}，或某个 take.locked（本机链优先，再看 gpu3 链） */
export function lockedN(d: ShotDetail | undefined, stage: Stage): number | null {
  if (!d) return null;
  const top = (d.takes as { locked?: Partial<Record<string, number | null>> } | undefined)?.locked?.[stage];
  if (typeof top === "number") return top;
  const pick = (list: (Take & { locked?: boolean | null })[] | undefined) => list?.find((t) => t.stage === stage && t.locked)?.n ?? null;
  return pick(d.takes?.takes) ?? pick(d.gpu3_takes?.takes) ?? null;
}

/** 景别 · 运镜 · 时长（行首和精修头共用） */
export function shotMeta(s: ShotSummary, scene?: string | null): string[] {
  return [s.camera.size, s.camera.move || s.camera.angle, `${s.duration.seconds}s`, scene || ""].filter(Boolean) as string[];
}

/** 本镜地点：详情的 visual_spec.scene（字符串或 {name|location|text}） */
export function sceneOf(d: { visual_spec?: Record<string, unknown> | null } | undefined): string | null {
  const v = d?.visual_spec?.scene as unknown;
  if (!v) return null;
  if (typeof v === "string") return v;
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const t = [o.place || o.name || o.location || o.id, o.time_of_day].filter((x) => typeof x === "string" && x).join("·");
    return t || null;
  }
  return null;
}

/** v3.1 §5.3：出视频前尾帧过期 → 按钮禁用并写明原因；可以出时返回 null */
export function videoBlock(s: ShotSummary, d: ShotDetail | undefined): string | null {
  if (!s.first_frame) return "还没有首帧";
  if (frameState(s, d, "image") === "stale") return "首帧已过期，先重出首帧";
  if (frameState(s, d, "last") === "stale") return "尾帧已过期，先重出尾帧";
  if (!s.last_frame_target) return "还没有尾帧";
  return null;
}
