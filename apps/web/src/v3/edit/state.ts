// fredw-92/W4b：精修模式中区与右栏共享的小状态（两个组件由外壳分别挂载，靠这里同步）
import { useSyncExternalStore } from "react";
import type { ShotDetail, Take } from "../../types";
import { apiV1, isNotReady, slotToStage, type JobV1, type Slot, type TakeV1Fields, type EditMode, type JobStateV1 } from "../api_v1";
import { laneEta, laneName, type LanePick } from "./lanes";
import { AUTO_SHORT, AUTO_TIP, DEP_UPDATED, STALE_SHORT } from "../words";

export type TakeX = Take & TakeV1Fields & {
  /** fredw-92/UXF4（审查 N1）：整集出片自动测试定稿的那一版（待项目方复审，不算定稿 / 通过） */
  auto?: boolean;
  /** 视频：项目方已通过的当前版 */
  passed?: boolean;
};

export interface TrackedJob {
  id: string;
  shot: string;
  slot: Slot | "asset";
  label: string;
  state: JobStateV1;
  gpu: number | string | null;
  eta_s: number | null;
  submitted: number;
  started_at?: string | null;
  error?: string | null;
  notReady?: boolean;
  take?: number | null;
  /** 完成后回调（刷新镜头详情 / 资产） */
  onDone?: (j: TrackedJob) => void;
}

export interface LoopOpen {
  slot: Slot;
  mode: EditMode | "inpaint" | "video";
  parent: number | null;
}

export interface DrawerOpen {
  shot: string;
  /** 资产 id（形象或部件）；只知道人物时 = 人物 id */
  asset: string;
  character: string;
  label: string;
  /** "look" = 整套形象；其余是部件 */
  kind: "look" | import("../api_v1").PartKey;
  /** 从本镜某一版打开（“设为参考”） */
  fromTake?: { slot: Slot; n: number } | null;
}

interface ShotUi {
  slot: Slot;
  pick: Partial<Record<Slot, number>>;
}

interface EditState {
  ui: Record<string, ShotUi>;
  compare: { shot: string; slot: Slot; a: number; b: number } | null;
  loop: (LoopOpen & { shot: string }) | null;
  drawer: DrawerOpen | null;
  jobs: TrackedJob[];
  /** fredw-92/UXF2：用哪条道；默认 "auto"（后端按任务类型挑空闲的卡：出图偏好出图道，视频偏好其他道） */
  gpu: LanePick;
}

let state: EditState = { ui: {}, compare: null, loop: null, drawer: null, jobs: [], gpu: "auto" };
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
export const setEdit = (fn: (s: EditState) => Partial<EditState>) => {
  state = { ...state, ...fn(state) };
  emit();
};
export const getEdit = () => state;
export function useEdit(): EditState {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => state,
  );
}

export const shotUi = (s: EditState, shot: string): ShotUi => s.ui[shot] ?? { slot: "first", pick: {} };
export const setShotUi = (shot: string, patch: Partial<ShotUi>) =>
  setEdit((s) => ({ ui: { ...s.ui, [shot]: { ...shotUi(s, shot), ...patch } } }));
export const pickTake = (shot: string, slot: Slot, n: number) =>
  setEdit((s) => {
    const u = shotUi(s, shot);
    return { ui: { ...s.ui, [shot]: { ...u, slot, pick: { ...u.pick, [slot]: n } } } };
  });

// ---------- takes ----------

/** 本镜某一格的全部版本（新 → 旧按 n 排）；本机 takes 为空时退回 gpu3 只读版本链 */
export function takesOf(d: ShotDetail | undefined, slot: Slot): TakeX[] {
  if (!d) return [];
  const st = slotToStage(slot);
  let list = (d.takes?.takes ?? []).filter((t) => t.stage === st) as TakeX[];
  if (!list.length && d.gpu3_takes) list = (d.gpu3_takes.takes ?? []).filter((t) => t.stage === st) as TakeX[];
  // fredw-92/UXF4（审查 N1）：整集出片“自动测试定稿”的那一版标 auto；视频的“定稿”不给项目方看，只看“通过”（passed）
  const lb = (d.takes as { locked_by?: Record<string, { by?: string; n?: number } | null> } | undefined)?.locked_by?.[st];
  const act = activeN(d, slot);
  const passed = st === "video" && d.summary?.review?.state === "passed";
  return [...list]
    .map((t) => {
      const auto = lb?.by === "auto" && lb.n === t.n && (st === "video" ? t.n === act && !passed : !!t.locked);
      const pass = passed && t.n === act;
      return auto || pass ? { ...t, auto, passed: pass } : t;
    })
    .sort((a, b) => a.n - b.n);
}
export function activeN(d: ShotDetail | undefined, slot: Slot): number | null {
  if (!d) return null;
  const st = slotToStage(slot);
  const a = d.takes?.active?.[st] ?? (d.gpu3_takes?.active as Record<string, number> | undefined)?.[st];
  return typeof a === "number" ? a : null;
}
/** 当前选中的版本：先看本地选择，再看后端 active，最后取最新 */
export function currentTake(s: EditState, d: ShotDetail | undefined, shot: string, slot: Slot): TakeX | null {
  const list = takesOf(d, slot);
  if (!list.length) return null;
  const n = shotUi(s, shot).pick[slot] ?? activeN(d, slot);
  return list.find((t) => t.n === n) ?? list[list.length - 1];
}
export const lockedTake = (d: ShotDetail | undefined, slot: Slot) => takesOf(d, slot).find((t) => t.locked) ?? null;
export const isStale = (t: TakeX | null | undefined) => !!t && ((t.stale?.length ?? 0) > 0 || (t.stale_global?.length ?? 0) > 0);
export const takeUrl = (t: TakeX | null | undefined) => (t ? (t.stage === "video" ? t.last_url ?? null : t.url) : null);

// ---------- 预计时长 ----------

/** fredw-92/U2：卡的旧显示名（资产抽屉还在用）。UXF2：卡不再固定用途（G36），精修 / 任务条一律写真实道名 */
export const GPU_LABEL: Record<string, string> = { "0": laneName(0), "3": laneName(3) };
/** 卡名（UXF4 / 审查 N7：全站唯一写法 lanes.cardName，“gpu33·卡0”）；"auto" → 自动分配 */
export const gpuLabel = (g: number | string | null | undefined) => laneName(g);

/** 后端任务记录里的实际耗时（wall_s，F4 也用它算 eta_s）。键 = 阶段:卡 */
const hist = new Map<string, { at: string; s: number }[]>();
type HistJob = { id?: string; kind?: string; gpu?: number | string | null; state?: string; wall_s?: number | null; started_at?: string | null; finished_at?: string | null; params?: { stage?: string } | null };
export function noteJobHistory(jobs: HistJob[]) {
  let added = false;
  for (const j of jobs) {
    if (j.state !== "done") continue;
    let s = typeof j.wall_s === "number" ? j.wall_s : null;
    if (s == null && j.started_at && j.finished_at) s = (Date.parse(j.finished_at) - Date.parse(j.started_at)) / 1000;
    if (s == null || !(s > 0)) continue;
    const slot = j.kind === "video" ? "video" : j.kind === "frame" ? (j.params?.stage === "last" ? "last" : "first") : "asset";
    const k = `${slot}:${j.gpu ?? "?"}`;
    const arr = hist.get(k) ?? [];
    const at = `${j.finished_at ?? ""}#${j.id ?? ""}`;
    if (arr.some((x) => x.at === at)) continue;
    arr.push({ at, s });
    arr.sort((a, b) => (a.at < b.at ? 1 : -1));
    hist.set(k, arr.slice(0, 8));
    added = true;
  }
  if (added) setEdit(() => ({})); // 让“预计约 N 分钟”跟着刷新
}

/** 预计（秒）：优先用后端任务记录里最近 5 次实际耗时的平均；没有记录才用粗估。排队按同卡在途任务数累加。
 *  任务提交后显示后端返回的 eta_s（GET /api/jobs/{id}）。 */
export function etaFor(slot: Slot | "asset", gpu: LanePick, seconds?: number | null): { eta: number; queue: number; n: number; one: number } {
  // fredw-92/UXF4（审查 N5）：先用后端 jobs.estimate 同口径的表（同类同卡最近 5 次中位数，没有样本 = 出图 70 s / 视频 840 s；
  // 自动 = 后端 pick_lane 会落到的那张卡）。本页记录只作后备，而且秒退的假任务（出图 < 5 s、视频 < 60 s）不算样本——以前出首帧写“约 1 秒”
  const be = laneEta(slot === "video" ? "video" : slot === "asset" ? "asset_gen" : "frame", gpu);
  const minS = slot === "video" ? 60 : 5;
  const h = (gpu === "auto" ? [...hist.entries()].filter(([k]) => k.startsWith(`${slot}:`)).flatMap(([, v]) => v) : hist.get(`${slot}:${gpu}`) ?? [])
    .filter((x) => x.s >= minS)
    .slice(0, 5);
  const guess = slot === "video" ? Math.max(840, Math.max(4, seconds ?? 6) * 120) : 70;
  const one = be ? be.per : h.length ? [...h].sort((a, b) => a.s - b.s)[Math.floor(h.length / 2)].s : guess;
  const queue = gpu === "auto" ? 0 : state.jobs.filter((j) => (j.state === "queued" || j.state === "running") && String(j.gpu) === String(gpu)).length;
  return { eta: one * (queue + 1), queue, n: be ? be.samples : h.length, one };
}
export const fmtSec = (s: number | null | undefined) =>
  s == null ? "—" : s < 90 ? `${Math.round(s)} 秒` : `${Math.round(s / 60)} 分钟`;

// ---------- 聚焦阶段 / 状态 ----------

/** 精修中区当前放大的阶段：用户选过就用；否则有视频默认视频，没有就首帧 */
export function focusSlot(s: EditState, d: ShotDetail | undefined, shot: string): Slot {
  const u = s.ui[shot];
  if (u) return u.slot;
  return takesOf(d, "video").length ? "video" : "first";
}

/** 一版的状态角标——只有一个：已定稿且过期 → “过期·需重出”（不再同时显示“已定稿”） */
export function takeBadge(t: TakeX | null | undefined): { text: string; cls: "ok" | "warn" | "auto" | "bad" | "dep"; why?: string } | null {
  if (!t) return null;
  if (t.bad) return { text: "坏图", cls: "bad", why: `${t.bad}：不能定稿、不能设为当前` }; // UXF1 #6：坏图优先（不能定稿 / 设为当前）
  const why = [...(t.stale ?? []), ...(t.stale_global ?? [])].join("；");
  if (isStale(t)) return { text: STALE_SHORT, cls: "warn", why }; // UXF5（R4）：过期只有一种写法
  // UX5-B：所用资产出了新版本 → 单独角标（不算过期；悬停列出哪项 vA→vB）
  if (t.stale_deps?.length) return { text: DEP_UPDATED, cls: "dep", why: t.stale_deps.map((d) => d.text).join("；") };
  // UXF4（审查 N1）：自动测试定稿单独标出，不和项目方定稿同色；视频只显示“通过”，不显示“定稿”
  if (t.auto) return { text: AUTO_SHORT, cls: "auto", why: AUTO_TIP };
  if (t.stage === "video") return t.passed ? { text: "已通过", cls: "ok" } : null;
  if (t.locked) return { text: "已定稿", cls: "ok" };
  return null;
}

/** 某一格现在能不能出 / 改；不能时返回原因（显示在按钮旁边） */
export function gateOf(d: ShotDetail | undefined, slot: Slot): string | null {
  const lf = lockedTake(d, "first");
  const ll = lockedTake(d, "last");
  if (slot === "last" && !lf) return "先定稿首帧";
  if (slot === "video") {
    if (!lf && !ll) return "首尾帧都定稿后才能出视频";
    if (!lf) return "首帧未定稿，先定稿首帧";
    if (!ll) return "尾帧未定稿，先定稿尾帧";
    if (isStale(lf)) return "首帧已过期，先重出首帧";
    if (isStale(ll)) return "尾帧已过期，先重出尾帧";
  }
  return null;
}

// ---------- 任务轮询 /api/jobs/{id} ----------

let timer: number | null = null;
const live = (j: TrackedJob) => (j.state === "queued" || j.state === "running") && !j.notReady;

export function trackJob(j: Omit<TrackedJob, "state" | "submitted" | "eta_s"> & { eta_s?: number | null }) {
  const job: TrackedJob = { state: "queued", submitted: Date.now(), eta_s: j.eta_s ?? null, ...j };
  setEdit((s) => ({ jobs: [job, ...s.jobs.filter((x) => x.id !== job.id)].slice(0, 30) }));
  ensurePolling();
}
const patchJob = (id: string, p: Partial<TrackedJob>) =>
  setEdit((s) => ({ jobs: s.jobs.map((j) => (j.id === id ? { ...j, ...p } : j)) }));
export const dismissJob = (id: string) => setEdit((s) => ({ jobs: s.jobs.filter((j) => j.id !== id) }));

function ensurePolling() {
  if (timer != null) return;
  timer = window.setInterval(poll, 2000);
  void poll();
}
async function poll() {
  const act = state.jobs.filter(live);
  if (!act.length) {
    if (timer != null) window.clearInterval(timer);
    timer = null;
    return;
  }
  await Promise.all(
    act.map(async (j) => {
      try {
        const r: JobV1 = await apiV1.job(j.id);
        const take = typeof r.take === "number" ? r.take : r.take?.n ?? null;
        patchJob(j.id, { state: r.state, gpu: r.gpu ?? j.gpu, eta_s: r.eta_s ?? j.eta_s, started_at: r.started_at, error: r.error ?? null, take });
        if (r.state === "done") noteJobHistory([{ ...(r as HistJob), id: j.id, kind: j.slot === "video" ? "video" : j.slot === "asset" ? "asset" : "frame", params: { stage: j.slot === "last" ? "last" : "first" } }]);
        if (r.state === "done" || r.state === "failed") {
          const done = state.jobs.find((x) => x.id === j.id);
          if (done) done.onDone?.(done);
        }
      } catch (e) {
        if (isNotReady(e)) patchJob(j.id, { notReady: true, error: "任务查询接口后端未就绪（/api/jobs/{id}）" });
        else patchJob(j.id, { error: (e as Error).message });
      }
    }),
  );
}
export async function cancelJob(id: string) {
  try {
    await apiV1.cancelJob(id);
    patchJob(id, { state: "cancelled" });
    return null;
  } catch (e) {
    return isNotReady(e) ? "取消接口后端未就绪" : (e as Error).message;
  }
}
