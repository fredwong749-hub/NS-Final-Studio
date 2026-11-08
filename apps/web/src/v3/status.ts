// fredw-92/W4a：画布 v3 统一状态词表（规格 §5）——一个圆点 + 一句“下一步”，不写系统内部状态。
// 灰 未出 · 蓝 生成中 · 黄 待你审 · 绿 已定 · 红 失败。成人镜不加锁（项目方 2026-10-30：不做成人拦截）。
import { useEffect, useState } from "react";
import type { Studio } from "../store";
import type { Episode, ShotDetail, ShotSummary, SopEpisode, SopShot, Stage, Take } from "../types";
import { isFailed, STAGE_LABEL } from "../util";
import { etaFor, fmtSec, getEdit } from "./edit/state";
import { laneBusyBy } from "./edit/lanes";
import { episodeMissing } from "./StoryboardDetails.helpers";
import { SLOT_NAME, lockAndNext, submitFrame, submitVideo } from "./edit/actions";
import { AUTO_LONG, staleLong } from "./words";
import { inSpotQueue, machineSignedN } from "./ownerQueue"; // UIRSI2 L-116：机签通过的镜不再提示人工点选

export type Dot = "gray" | "blue" | "yellow" | "green" | "red";
export const DOT_LABEL: Record<Dot, string> = { gray: "未出", blue: "生成中", yellow: "待你审", green: "已定", red: "出错" }; // UXF1：红 = 失败 / 坏图 / 链不完整

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
  why: { text: string; who?: string; sys?: boolean }[];
}

const STAGES: Stage[] = ["image", "last", "video"];

function whyList(s: ShotSummary, d: ShotDetail | undefined, sop: SopShot | undefined, err: string | null): ShotStatus["why"] {
  const out: ShotStatus["why"] = [];
  const seen = new Set<string>();
  // UX4（审查 #16）：“为什么卡住”里的每一条都过一遍人话（去 “sound/H3：” 前缀和【】，“编译器升级” → “出图规则更新”）
  // UM-P0-01：只把项目方能处理的事列出来；系统内部检查（校验器、规则号、采纳记录、卡 / 机器、链路要求……）标 sys，界面只合成一行“系统检查中”
  const add = (text: string, who?: string, mine = false) => {
    const k = gapText(text).replace(/编译器升级/g, "出图规则更新");
    if (!k || seen.has(k)) return;
    seen.add(k);
    const sys = !mine && (who !== "项目方" || SYS_RE.test(k));
    out.push({ text: k, who, sys });
  };
  if (err) add("上次没生成成功 → 点主按钮重出", undefined, true);
  if (s.review.state === "rejected") add(`你要改${s.review.reason ? `：${s.review.reason}` : ""} → 进精修改`, "项目方", true);
  for (const b of sop?.blockers ?? []) add(b.text, whoLabel(b.actor ?? b.actor_label));
  for (const r of s.readiness?.blocked_reasons ?? []) add(r);
  for (const r of s.readiness?.gpu3_blocked_reasons ?? []) add(r, "视频端");
  for (const st of STAGES) if (staleOf(s, d, st).length) add(`${STAGE_LABEL[st]}要重出（上游改过）→ 点主按钮重出`, undefined, true);
  return out;
}

/** 系统内部检查项的字样：不给项目方看（UM-P0-01：不许出现 laptop、G3、校验器、须为 0 等） */
export const isSysText = (t: string) => SYS_RE.test(t);
// 文件路径 / 内部文件名（.json .yaml .py、xxx_overrides）一律算系统字样（UM-0585…0592 兜底）
const SYS_RE = /系统正在刷新|对照表有更新|校验器|须为|须由|\bG\d|laptop|笔记本|gpu|GPU|规则|[A-Z]{1,4}\d*-[A-Z0-9]+|编译|sha|契约|SOP|§|采纳|记录|视频端|画布|写作模型|字段|校验|对齐|帧数|\.(json|ya?ml|py|md)\b|_overrides|[a-z_]+\/[a-z_]+\.[a-z]+/;

/** “谁来处理”说人话（原则 4：不出现 gpu3 / owner / canvas 等内部词） */
const WHO: Record<string, string> = { gpu3: "视频端", GPU3: "视频端", canvas: "画布", owner: "项目方", qwen: "写作模型", Qwen: "写作模型" }; // UX4：千问已撤下，写作方统一叫“写作模型”
export const whoLabel = (x?: string | null) => (x ? WHO[x] ?? x : undefined);

/** 某格过期原因（镜头摘要 stale[stage] + stale_global[stage]（编译器升级等）+ takes.json 顶层 stale.{stage}）——过期判定只此一处。
 *  fredw-92/UXF1（审查 #11）：精修的“过期”角标一直把 stale_global 算进去，审片行没算 → 同一张图一边“过期”一边“待你审·满意就定稿”。现在两边同源 */
export function staleOf(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): string[] {
  // P5 M2（PLAN §2.4 口径表）：stale 只含本镜输入变化；stale_global（编译器升级等全局变化）不进卡片过期，只在检查器看（staleGlobalOf）
  const out = [...(s.stale?.[stage] ?? [])].filter((x) => x != null);
  const tst = (d?.takes as { stale?: Partial<Record<string, { reason?: string } | null>> } | undefined)?.stale?.[stage];
  if (tst) out.push(tst.reason ?? "");
  return [...new Set(out)];
}

/** 全局过期原因（编译器升级等）：独立字段，只给检查器 / 编辑页显示，不算卡片过期 */
export const staleGlobalOf = (s: ShotSummary, stage: Stage): string[] => (s.stale_global?.[stage] ?? []).filter((x) => x != null);

/** fredw-92/UXF1（审查 #6）：当前首帧 / 尾帧是不是坏图（太小 / 文件太小 / 尺寸与请求不符）→ 原因 */
export function badOf(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): string | null {
  if (stage === "video") return null;
  const fromSummary = s.bad?.[stage];
  if (fromSummary) return fromSummary;
  const n = stage === "image" ? s.first_frame_take : s.last_frame_take;
  if (n == null) return null;
  return d?.takes?.takes.find((t) => t.stage === stage && t.n === n)?.bad ?? null;
}

/** fredw-92/UXF4（审查 N1）：这一格是不是整集出片“自动测试定稿”的（项目方还没复审）→ 版本号。
 *  首帧 / 尾帧：定稿版 = 自动定稿那一版；视频：当前视频 = 自动定稿那一版且还没“通过”。摘要 auto_locked 优先，没有再看详情 locked_by */
export function autoLockOf(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): number | null {
  if (stage === "video" && s.review.state === "passed") return null;
  const dl = delegateLockOf(d, stage); // W18b P1-6：系统代选（L-142）与自动定稿并列，都不算项目方定稿、可改
  if (dl != null) return dl;
  const v = s.auto_locked?.[stage];
  if (v != null) return v;
  if (s.auto_locked) return null; // 后端给了这个字段：以它为准
  const tk = d?.takes as { locked_by?: Record<string, { by?: string; n?: number } | null>; locked?: Record<string, number | null>; active?: Record<string, number | null> } | undefined;
  const lb = tk?.locked_by?.[stage];
  if (lb?.by !== "auto" || lb.n == null) return null;
  const cur = stage === "video" ? tk?.active?.video : tk?.locked?.[stage];
  return cur === lb.n ? lb.n : null;
}

/** W18b P1-6：首帧超时代选（L-142，takes.json locked_by.by === "delegate"）→ 版本号；只看详情（摘要 auto_locked 只认 auto） */
export const DELEGATE_LABEL = "系统代选·可改";
export function delegateLockOf(d: ShotDetail | undefined, stage: Stage): number | null {
  const tk = d?.takes as { locked_by?: Record<string, { by?: string; n?: number } | null>; locked?: Record<string, number | null> } | undefined;
  const lb = tk?.locked_by?.[stage];
  if (lb?.by !== "delegate" || lb.n == null) return null;
  return tk?.locked?.[stage] === lb.n ? lb.n : null;
}
/** 这一格“非项目方定稿”的说法：系统代选·可改 / 自动定稿·待复审 */
export const autoWord = (d: ShotDetail | undefined, stage: Stage) => (delegateLockOf(d, stage) != null ? DELEGATE_LABEL : AUTO_LONG);

/** 当前显示的版本号（行格里的 #n） */
const shownN = (s: ShotSummary, stage: Stage) => (stage === "image" ? s.first_frame_take : stage === "last" ? s.last_frame_take : null);

/** 一格的状态（v3.1 §5.1：定稿 + 过期 只算“过期·需重出”，不算定稿）。
 *  fredw-92/UXF1：orphan = 没有首帧却有尾帧 / 视频（链不完整，下游作废，不计入完成数）；bad = 坏图；
 *  locked 只在“当前显示的就是定稿版”时成立（当前 #5、定稿 #4 → 当前是草稿，不能标“已定稿”） */
export type FrameState = "none" | "draft" | "locked" | "stale" | "bad" | "orphan" | "auto";
export function frameState(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): FrameState {
  const has = stage === "image" ? !!s.first_frame : stage === "last" ? !!s.last_frame_target : !!s.video;
  if (!has) return "none";
  if (stage !== "image" && !s.first_frame) return "orphan";
  if (badOf(s, d, stage)) return "bad";
  if (staleOf(s, d, stage).length) return "stale";
  if (stage !== "video") {
    const lk = lockedOf(s, d, stage);
    const cur = shownN(s, stage);
    // UXF4（审查 N1）：自动测试定稿 ≠ 项目方定稿（不计入“已定”、整集出片不当作已完成）
    if (lk != null && (cur == null || cur === lk)) return autoLockOf(s, d, stage) === lk ? "auto" : "locked";
  } else if (autoLockOf(s, d, "video") != null) return "auto";
  return "draft";
}

/** 定稿版本号：摘要 locked_take 优先（每镜都有），没有再看详情 */
export function lockedOf(s: ShotSummary, d: ShotDetail | undefined, stage: Stage): number | null {
  if (stage !== "video") {
    const v = s.locked_take?.[stage];
    if (v !== undefined) return v ?? null;
  }
  return lockedN(d, stage);
}

/** 已定 = 首帧、尾帧都已定稿且都没过期（视频另计）——片段条统计、步骤条共用 */
export const framesLocked = (s: ShotSummary, d: ShotDetail | undefined) => frameState(s, d, "image") === "locked" && frameState(s, d, "last") === "locked";

/** 视频算不算“有视频”：链不完整（没有首帧）或过期的不算（审查 #10）——片段条、步骤条共用 */
export const videoCounts = (s: ShotSummary, d: ShotDetail | undefined) => !!s.video && !["orphan", "stale"].includes(frameState(s, d, "video"));

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
    if (videoCounts(s, st.details[s.id])) videos++;
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
    pass: () => void st.setReview([s.id], "passed"),
    // XYQ（小云雀走查 #1）：审片行直接“定稿这一版 + 排下一步”，不用先进精修
    "lock-first-next": () => {
      st.select(s.id);
      if (s.first_frame_take != null) void lockAndNext(s.id, "first", s.first_frame_take, getEdit().gpu, st.notify, st.refreshAfter, !s.last_frame_target);
    },
    "lock-last-next": () => {
      st.select(s.id);
      if (s.last_frame_take != null) void lockAndNext(s.id, "last", s.last_frame_take, getEdit().gpu, st.notify, st.refreshAfter, !s.video);
    },
  };
  const make = (key: StatusKey, why0: ShotStatus["why"], over?: { text?: string; title?: string }): ShotStatus => {
    const r = STATUS_TABLE[key];
    return {
      dot: r.dot,
      key,
      text: over?.text ?? r.text,
      action: r.act ? { label: actLabel(r.act, r.label, s), run: runOf[r.act], title: over?.title ?? r.title } : null,
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
  if (fFirst === "none") {
    // 审查 #10：没有首帧却已有尾帧 / 视频 → 链不完整，下游作废；修法 = 先出首帧（再按定稿首帧重出尾帧、视频）
    if (s.last_frame_target || s.video) {
      const what = [s.last_frame_target && "尾帧", s.video && "视频"].filter(Boolean).join("和");
      return make("broken_chain", [{ text: `没有首帧，现有的${what}不是由定稿首帧来的，已作废（不计入完成数）` }, ...why], {
        text: `链不完整：没有首帧，${what}作废`,
      });
    }
    return make("no_first", why);
  }
  if (fFirst === "bad") return make("bad_first", [{ text: badOf(s, d, "image") ?? "坏图" }, ...why], { title: `首帧 #${s.first_frame_take ?? "?"} 是${badOf(s, d, "image")}。直接重出首帧` });
  if (fFirst === "stale") return make("stale_first", why, { title: `首帧已过期：${why1("image") || "上游改过"}。直接重出首帧（要先改再出：⋯ → 进精修）` });
  if (fFirst === "auto") return make("auto_first", why, { text: `首帧 #${s.first_frame_take ?? "?"} 是${autoWord(d, "image")}` });
  // UIRSI2 L-116：当前首帧 / 尾帧机签通过（契约 + Q9 本地看图过、机签 mode=auto、不在待抽检里，口径 /api/owner/queue machine_signed）
  // → 灰字“机签通过 vN”，当作已通过往下走；只有抽检样本进“待你看”队列。手动“用这张 / 不要”仍在（不提示）
  const mFirst = s.first_frame_take != null && machineSignedN(s.id, "image") === s.first_frame_take;
  const mLast = s.last_frame_take != null && machineSignedN(s.id, "last") === s.last_frame_take;
  if (fFirst !== "locked" && mFirst && !s.last_frame_target)
    return make("machine_first", why, { text: `机签通过 v${s.first_frame_take}` });
  if (fFirst !== "locked" && !mFirst) {
    const lk = lockedOf(s, d, "image");
    if (lk != null && s.first_frame_take != null && lk !== s.first_frame_take)
      return make("review_first", why, { text: `当前看的是 #${s.first_frame_take}，定稿是 #${lk}：满意就改定这一版` });
    if (inSpotQueue(s.id, "image", s.first_frame_take)) return make("review_first", why, { text: `机签通过 v${s.first_frame_take} · 抽检样本，在“待你看”里` });
    return make("review_first", why);
  }
  if (fLast === "bad") return make("bad_last", [{ text: badOf(s, d, "last") ?? "坏图" }, ...why], { title: `尾帧是${badOf(s, d, "last")}。由定稿首帧重出尾帧` });
  if (fLast === "stale") return make("stale_last", why, { title: `尾帧已过期：${why1("last") || "首帧定稿换了版本"}。由定稿首帧直接重出尾帧` });
  if (fLast === "auto") return make("auto_last", why, { text: `尾帧 #${s.last_frame_take ?? "?"} 是${autoWord(d, "last")}` });
  if (fLast !== "locked" && mLast && !s.video) return make("machine_last", why, { text: `机签通过 v${s.last_frame_take}` });
  if (fLast !== "locked" && !mLast && s.last_frame_target && inSpotQueue(s.id, "last", s.last_frame_take))
    return make("review_last", why, { text: `机签通过 v${s.last_frame_take} · 抽检样本，在“待你看”里` });
  if (fLast !== "locked" && !mLast) return make(s.last_frame_target ? "review_last" : "need_last", why);
  if (!s.video) return make("need_video", why);
  if (frameState(s, d, "video") === "stale") return make("stale_video", why, { title: `视频已过期：${why1("video") || "上游改过"}` });
  if (s.review.state === "passed") return make("done", []);
  // UXF4（审查 N1）：视频只有一个对项目方的状态 = 通过；自动测试定稿的视频写明“待你复审”
  if (frameState(s, d, "video") === "auto") return make(st.canPass(s) ? "review_video_watched" : "review_video", why, { text: st.canPass(s) ? "自动定稿的视频已看完，满意就通过" : `视频是${AUTO_LONG}` });
  // UXF2→UXF1 #13：视频已完整看过一遍 → 主按钮直接“通过”（与 ⋯ / 片段条 / 精修同一个 setReview）
  if (st.canPass(s)) return make("review_video_watched", why);
  return make("review_video", why);
}

/** 主按钮做什么：regen-* / video = 直接提交 v1 任务（frame-job regen / video-job）；edit = 进精修；watch = 串播看视频；jobs = 打开任务队列 */
export type ActKind = "regen-first" | "regen-last" | "video" | "edit" | "watch" | "jobs" | "pass" | "lock-first-next" | "lock-last-next";

/** XYQ（小云雀走查 #1 / #6）：主按钮文字——定稿类带版本号和“→ 下一步”；生成类直接写预计时长（小云雀把消耗写在生成按钮上） */
export function actLabel(act: ActKind, label: string, s: ShotSummary): string {
  const gpu = getEdit().gpu;
  // 第二行用换行符隔开：审片行主按钮 white-space: pre-line 折成两行；别处按普通空白显示成一行
  if (act === "lock-first-next") return `${label} #${s.first_frame_take ?? "?"}${s.last_frame_target ? "" : "\n→ 出尾帧"}`;
  if (act === "lock-last-next") return `${label} #${s.last_frame_take ?? "?"}${s.video ? "" : "\n→ 出视频"}`;
  // 卡被外部任务 / 训练占着：只写“约 N 秒”会误导（实际要排在后面），改写成“卡被占用·要排队”
  const busy = act === "video" ? laneBusyBy("video", gpu, s.duration.seconds) : act === "regen-first" || act === "regen-last" ? laneBusyBy("image", gpu) : null;
  if (busy) return `${label}\n${busy === "train" ? "卡在训练" : "卡被占用"} · 要排队`;
  if (act === "video") return `${label}\n约 ${fmtSec(etaFor("video", gpu, s.duration.seconds).one)}`;
  if (act === "regen-first" || act === "regen-last") return `${label}\n约 ${fmtSec(etaFor(act === "regen-first" ? "first" : "last", gpu).one)}`;
  return label;
}
export type StatusKey =
  | "job_v1" | "job_old" | "failed_first" | "failed_last" | "failed_video" | "rejected"
  | "no_first" | "stale_first" | "review_first" | "stale_last" | "need_last" | "review_last"
  | "need_video" | "stale_video" | "review_video" | "done" | "broken_chain" | "bad_first" | "bad_last" | "review_video_watched"
  | "auto_first" | "auto_last" | "machine_first" | "machine_last";

/** 状态 ↔ 一句话 ↔ 主按钮 的唯一对照表（v3.1：状态写什么，主按钮就做什么；改对应关系只改这里） */
export const STATUS_TABLE: Record<StatusKey, { dot: Dot; text: string; label: string; act: ActKind | null; title?: string }> = {
  job_v1: { dot: "blue", text: "生成中，稍等", label: "看进度", act: "edit" },
  job_old: { dot: "blue", text: "排队中，稍等", label: "看进度", act: "jobs" },
  failed_first: { dot: "red", text: "首帧没出成，需重出", label: "重出首帧", act: "regen-first" },
  failed_last: { dot: "red", text: "尾帧没出成，需重出", label: "重出尾帧", act: "regen-last" },
  failed_video: { dot: "red", text: "视频没出成，需重出", label: "重出视频", act: "video" },
  rejected: { dot: "red", text: "待重做，去精修改", label: "去精修", act: "edit" },
  no_first: { dot: "gray", text: "还没有首帧，出首帧", label: "出首帧", act: "regen-first" },
  stale_first: { dot: "yellow", text: staleLong("首帧"), label: "重出首帧", act: "regen-first" },
  broken_chain: { dot: "red", text: "链不完整：没有首帧，下游作废", label: "出首帧", act: "regen-first", title: "先出首帧并定稿，再由定稿首帧重出尾帧和视频" },
  bad_first: { dot: "red", text: "首帧是坏图，需重出", label: "重出首帧", act: "regen-first" },
  bad_last: { dot: "red", text: "尾帧是坏图，需重出", label: "重出尾帧", act: "regen-last" },
  // XYQ（小云雀走查 #1）：待审首帧 / 尾帧时主按钮 = 定稿当前这一版并排下一步（下游已有就只定稿）；要对比版本、改图走 ⋯ → 进精修
  review_first: { dot: "yellow", text: "首帧待你看：用这张，或修改", label: "定稿首帧", act: "lock-first-next", title: "定稿当前这一版首帧，并由它出尾帧（要先对比、改图：⋯ → 进精修；点首帧可全屏看）" },
  auto_first: { dot: "yellow", text: `首帧是${AUTO_LONG}`, label: "确认首帧", act: "lock-first-next", title: "整集出片替你定稿的，不算你定稿：点这里确认这一版（要重出：⋯ → 进精修）" },
  auto_last: { dot: "yellow", text: `尾帧是${AUTO_LONG}`, label: "确认尾帧", act: "lock-last-next", title: "整集出片替你定稿的，不算你定稿：点这里确认这一版（要重出：⋯ → 进精修）" },
  stale_last: { dot: "yellow", text: staleLong("尾帧"), label: "重出尾帧", act: "regen-last" },
  need_last: { dot: "yellow", text: "首帧已定稿，下一步出尾帧", label: "出尾帧", act: "regen-last", title: "由定稿首帧出尾帧" },
  review_last: { dot: "yellow", text: "尾帧待你看：用这张，或修改", label: "定稿尾帧", act: "lock-last-next", title: "定稿当前这一版尾帧，并出视频（要先对比：⋯ → 进精修）" },
  need_video: { dot: "yellow", text: "首尾帧已定稿，下一步出视频", label: "出视频", act: "video" },
  stale_video: { dot: "yellow", text: staleLong("视频"), label: "重出视频", act: "video" },
  review_video: { dot: "yellow", text: "待你审视频", label: "看视频", act: "watch" },
  review_video_watched: { dot: "yellow", text: "视频看完了：用这版，或修改", label: "通过 ✓", act: "pass", title: "通过这版视频（想改用“修改”）" },
  done: { dot: "green", text: "已定，无需操作", label: "看视频", act: "watch" },
  // UIRSI2 L-116：机签通过（灰点 + 灰字，无主按钮——系统自动往下做；手动“用这张 / 不要”保留但不提示）
  machine_first: { dot: "gray", text: "机签通过", label: "", act: null, title: "首帧已自动检查通过并设为当前；系统自动出尾帧。要换：点首帧看候选，或 ⋯ → 进精修" },
  machine_last: { dot: "gray", text: "机签通过", label: "", act: null, title: "尾帧机签通过并已设为当前；系统自动出视频。要换：⋯ → 进精修" },
};

/** 某阶段的定稿版本号：takes.json 顶层 locked:{stage:n}，或某个 take.locked（本机链优先，再看 gpu3 链） */
export function lockedN(d: ShotDetail | undefined, stage: Stage): number | null {
  if (!d) return null;
  const top = (d.takes as { locked?: Partial<Record<string, number | null>> } | undefined)?.locked?.[stage];
  if (typeof top === "number") return top;
  const pick = (list: (Take & { locked?: boolean | null })[] | undefined) => list?.find((t) => t.stage === stage && t.locked)?.n ?? null;
  return pick(d.takes?.takes) ?? pick(d.gpu3_takes?.takes) ?? null;
}

/** fredw-92/UXF5（审查 N14）：运镜 / 景别只写中文（显示用，剧本原文不动、悬停仍可看原文）。
 *  中英混写（“camera push in 缓推”）只留中文；纯英文按常见运镜词翻；auto / none 不显示。 */
const CAM_EN: [RegExp, string][] = [
  [/static|locked[- ]?off|fixed/i, "固定"],
  [/push[- ]?in|dolly[- ]?in|zoom[- ]?in/i, "推近"],
  [/pull[- ]?(back|out)|dolly[- ]?out|zoom[- ]?out/i, "拉远"],
  [/orbit|arc shot/i, "环绕"],
  [/handheld/i, "手持跟拍"],
  [/tracking|follow/i, "跟拍"],
  [/tilt[- ]?up/i, "上摇"],
  [/tilt[- ]?down/i, "下摇"],
  [/pan[- ]?left/i, "左摇"],
  [/pan[- ]?right/i, "右摇"],
  [/\bpan\b/i, "摇镜"],
  [/crane[- ]?up|rise/i, "升镜"],
  [/crane[- ]?down/i, "降镜"],
  [/slow[- ]?motion/i, "慢动作"],
  [/close[- ]?up/i, "特写"],
  [/medium shot/i, "中景"],
  [/wide shot|long shot/i, "全景"],
];
export function camText(raw: string | null | undefined): string | null {
  const t = (raw ?? "").trim();
  if (!t || /^(auto|none|n\/a|-|—)$/i.test(t)) return null;
  if (/[一-鿿]/.test(t)) {
    const zh = t.replace(/[A-Za-z][A-Za-z\s\-/]*/g, " ").replace(/\s+/g, " ").trim();
    if (zh) return zh;
  }
  for (const [re, z] of CAM_EN) if (re.test(t)) return z;
  return t;
}

/** 景别 · 运镜 · 时长（行首和精修头共用） */
export function shotMeta(s: ShotSummary, scene?: string | null): string[] {
  return [camText(s.camera.size), camText(s.camera.move) || camText(s.camera.angle), `${s.duration.seconds}s`, scene || ""].filter(Boolean) as string[];
}
/** 运镜原文（悬停用） */
export const camRaw = (s: ShotSummary) => [s.camera.size, s.camera.move, s.camera.angle].filter((x) => x && !/^(auto|none)$/i.test(x)).join(" · ");

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
  if (frameState(s, d, "image") === "bad") return "首帧是坏图，先重出首帧";
  if (frameState(s, d, "last") === "bad") return "尾帧是坏图，先重出尾帧";
  if (frameState(s, d, "image") === "stale") return "首帧已过期，先重出首帧";
  if (frameState(s, d, "last") === "stale") return "尾帧已过期，先重出尾帧";
  if (!s.last_frame_target) return "还没有尾帧";
  return null;
}

/** fredw-92/UXF1（审查 #4）：剧本待补——分镜字段缺的（StoryboardDetails.missingOf）∪ SOP 停在 S1 的阻塞项。
 *  顶栏步骤①“N 镜待补”、集头“N 镜待补 / 分镜字段齐全”、“只看这些”过滤都用这一份，不再各算各的 */
export function scriptGaps(ep: Episode, details: Record<string, ShotDetail>, sop: SopEpisode | null | undefined): Map<string, string[]> {
  const miss = episodeMissing(ep, details);
  const out = new Map<string, string[]>();
  for (const s of ep.shots) {
    const why = (miss.get(s.id) ?? []).map((f) => gapText(`缺${f.label}`));
    const ss = sop?.shots.find((x) => x.id === s.id);
    for (const b of ss?.stage === "S1" ? ss.blockers.filter((b) => b.stage === "S1") : []) why.push(gapText(b.text));
    if (why.length) out.set(s.id, [...new Set(why)]);
  }
  return out;
}

/** SOP 阻塞文案去掉内部前缀与 Markdown（“sound/H3：亲密镜头缺【亲密声】” → “亲密镜头缺亲密声”） */
export const gapText = (t: string) =>
  // UM-0585…0592：“状态表过期（looks/face_overrides.json、…item_map_overrides…）”——文件名是技术细节，正文写人话
  /状态表过期|_overrides|\.json\b/.test(t)
    ? "人物造型 / 单品对照表有更新，系统正在刷新"
    : t
    .replace(/^[A-Za-z0-9_/ ]+[:：]\s*/, "")
    .replace(/\*\*/g, "")
    .replace(/[【】]/g, "")
    .replace(/（[A-Za-z0-9 _]*(audio|cue|H3)[A-Za-z0-9 _]*）/gi, "")
    .replace(/（本镜 ?cue）/gi, "")
    .replace(/H3 ?audio/gi, "环境声")
    .trim();

/** UIRSI r43（K-UI-048 呼吸灯）：同屏多个“正在渲染”呼吸点按镜号 / 卡号错开相位，避免整屏齐闪。
 *  返回给父元素的 style（CSS 变量会继承给里面的 .is-rendering / .stag.k-busy 等）；负延迟 = 从周期中段开始。 */
export function breatheDelay(key: string | number | null | undefined): Record<string, string> {
  const s = String(key ?? "");
  let h = 0;
  for (const ch of s.replace(/^.*?(\d+)\D*$/, "$1") || s) h = (h * 31 + ch.charCodeAt(0)) % 997;
  return { "--breathe-delay": `-${((h * 0.37) % 2.7).toFixed(2)}s` };
}

/** UIRSI r45（L-113 / D-LENS）：审片页每镜一行的“镜头”字段——读 /api/season 的 lens（实拍取本版出图提示词、计划取作业；不一致写“实拍 … · 计划 …”）。
 *  全页一份缓存（60 秒内不重取），各行订阅。 */
let lensMap: Record<string, string> | null = null;
let lensAt = 0;
let lensP: Promise<void> | null = null;
const lensSubs = new Set<() => void>();
function loadLens() {
  if (lensP || (lensMap && Date.now() - lensAt < 60000)) return;
  lensP = fetch("/api/season")
    .then((r) => (r.ok ? r.json() : null))
    .then((d: { episodes?: { shots?: { id: string; lens?: string | null }[] }[] } | null) => {
      if (!d) return;
      const m: Record<string, string> = {};
      for (const e of d.episodes ?? []) for (const x of e.shots ?? []) if (x.lens) m[x.id] = x.lens;
      lensMap = m;
      lensAt = Date.now();
    })
    .catch(() => {})
    .finally(() => {
      lensP = null;
      lensSubs.forEach((f) => f());
    });
}
export function useLens(id: string): string | null {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    lensSubs.add(f);
    loadLens();
    return () => {
      lensSubs.delete(f);
    };
  }, []);
  return lensMap?.[id] ?? null;
}
