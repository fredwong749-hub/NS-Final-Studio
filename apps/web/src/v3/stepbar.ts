// W5 UIUX 11-03（L-146 / L-155）：顶部步骤条 + 总览进度矩阵的数据层。
// 唯一来源 GET /api/sop/stepbar（ns_api/sop.py：sop_gate 阶段判定折成六步 + report_issue 未关卡点）；
// 后台还没重启、新接口 404 时退回 GET /api/pipeline/status（同一个 sop_gate 判定，只是没有卡点和负责方）——前端不自己判阶段。
import { useEffect, useState } from "react";
import type { PipeStatus, PipeStepId } from "./NavTabs.helpers";
import { plainOwner, plainText } from "./plainWords";

export type CellState = "done" | "doing" | "blocked" | "todo";
export interface StepIssue {
  id: string;
  text: string;
  owner: string;
  blocking: boolean;
  at?: string;
}
export interface StepCell {
  state: CellState;
  /** 一句大白话：这一格现在什么情况 */
  plain: string;
  /** 卡点一句话（有阻断卡点时） */
  block: string;
  /** 谁在负责（系统 · 出图 / 总调度 / 你 …） */
  owner: string;
  /** 还没到这一步，但已知前面有坑 */
  ahead: boolean;
  issues: StepIssue[];
  issues_more: number;
  /** 已完成的格子上没关的旧“挡路”单数（不显示成挡路，只给总调度看个数） */
  stale?: number;
}
export interface StepEpisode {
  episode: number;
  stage: string;
  plain: string;
  cells: Record<PipeStepId, StepCell>;
}
export interface StepCount {
  id: PipeStepId;
  label: string;
  stages: string[];
  done: number;
  doing: number;
  blocked: number;
  todo: number;
}
export interface NowItem {
  episode: number;
  step: PipeStepId;
  label: string;
  plain: string;
  block?: string;
  owner: string;
  state?: CellState;
}
export interface Stepbar {
  run: string;
  title: string;
  episodes_total: number;
  steps: StepCount[];
  episodes: StepEpisode[];
  now: { focus: NowItem | null; doing: NowItem[]; blocked: (NowItem & { n_issues: number })[] };
  issues_open: number;
  issues_error?: string | null;
  /** true = 新接口还没生效，用的是旧进度接口（没有卡点和负责方） */
  fallback?: boolean;
}

export const STEP_IDS: PipeStepId[] = ["script", "assets", "board", "frames", "video", "cut"];
export const STEP_NUM = ["①", "②", "③", "④", "⑤", "⑥"];
export const STATE_WORD: Record<CellState, string> = { done: "完成", doing: "进行中", blocked: "卡住", todo: "未开始" };
export const STATE_GLYPH: Record<CellState, string> = { done: "✓", doing: "●", blocked: "⚠", todo: "·" };

/** 点步骤 / 点格子去哪一页：带上当前剧（run）和集（ep）。画布 = #epNN */
export function stepHref(step: PipeStepId, ep: number, run?: string | null): string {
  const q = `ep=${ep}${run ? `&run=${encodeURIComponent(run)}` : ""}`;
  switch (step) {
    case "script":
      return `#/script-create?${q}`;
    case "assets":
      return `#/assets?${q}`;
    case "board":
      return `#ep${String(ep).padStart(2, "0")}`;
    case "frames":
      return `#/frames?${q}`;
    case "video":
      return `#/videos?${q}`;
    case "cut":
      return `#/cut?${q}`;
  }
}

/** 这一步最该看的一集：卡住的 > 进行中的 > 当前集 */
export function focusEp(d: Stepbar | null, step: PipeStepId, fallback: number): number {
  const eps = d?.episodes ?? [];
  return (eps.find((e) => e.cells[step]?.state === "blocked") ?? eps.find((e) => e.cells[step]?.state === "doing"))?.episode ?? fallback;
}

/** 旧接口 /api/pipeline/status → 同一形状（计数照 sop_gate 的格子数；没有卡点、没有负责方——页面必须挂 FALLBACK_TEXT 横幅） */
export const FALLBACK_TEXT = "后台接口未更新，卡点读不到（旧接口口径）";
export function fromPipe(p: PipeStatus & { episodes: (PipeStatus["episodes"][number] & { plain?: string })[] }): Stepbar {
  const episodes: StepEpisode[] = p.episodes.map((e) => ({
    episode: e.episode,
    stage: e.stage,
    plain: e.plain ?? "",
    cells: Object.fromEntries(
      STEP_IDS.map((s) => {
        const c = (e.cells[s] ?? { state: "todo", why: "" }) as { state: CellState; plain?: string };
        // 旧接口没有负责方：不拿默认负责方冒充事实（A5 P1-1），留空
        return [s, { state: c.state, plain: c.plain ?? STATE_WORD[c.state], block: "", owner: "", ahead: false, issues: [], issues_more: 0 }];
      }),
    ) as unknown as Record<PipeStepId, StepCell>,
  }));
  const n = (id: PipeStepId, k: CellState) => episodes.filter((e) => e.cells[id].state === k).length;
  const steps: StepCount[] = p.steps.map((s) => ({ id: s.id, label: s.label, stages: [], done: n(s.id, "done"), doing: n(s.id, "doing"), blocked: n(s.id, "blocked"), todo: n(s.id, "todo") }));
  const items = (k: CellState) => episodes.flatMap((e) => STEP_IDS.filter((s) => e.cells[s].state === k).map((s) => ({ episode: e.episode, step: s, label: p.steps.find((x) => x.id === s)?.label ?? s, plain: e.cells[s].plain, owner: e.cells[s].owner, state: k })));
  const live = [...items("blocked"), ...items("doing")].sort((a, b) => a.episode - b.episode || STEP_IDS.indexOf(a.step) - STEP_IDS.indexOf(b.step));
  return { run: p.run, title: p.title, episodes_total: p.episodes_total, steps, episodes, now: { focus: live[0] ?? null, doing: items("doing").slice(0, 8), blocked: items("blocked").slice(0, 8).map((x) => ({ ...x, n_issues: 0 })) }, issues_open: 0, fallback: true };
}

/** 新接口的卡点一句话 / 负责方过一遍人话词典（plainWords.ts 是唯一来源） */
export function humanize(v: Stepbar): Stepbar {
  const cell = (c: StepCell): StepCell => ({ ...c, block: plainText(c.block), owner: plainOwner(c.owner), issues: (c.issues ?? []).map((x) => ({ ...x, text: plainText(x.text), owner: plainOwner(x.owner) })) });
  const item = <T extends NowItem>(x: T): T => ({ ...x, block: x.block == null ? x.block : plainText(x.block), owner: plainOwner(x.owner) });
  return {
    ...v,
    episodes: v.episodes.map((e) => ({ ...e, cells: Object.fromEntries(Object.entries(e.cells).map(([k, c]) => [k, cell(c)])) as Record<PipeStepId, StepCell> })),
    now: { focus: v.now.focus ? item(v.now.focus) : null, doing: v.now.doing.map(item), blocked: v.now.blocked.map(item) },
  };
}

// 一份模块级缓存：顶栏步骤条和总览矩阵、首页“现在”共用一次请求（30 s 刷新）
let cache: { at: number; v: Stepbar | null; err: string | null } | null = null;
const subs = new Set<() => void>();
let inflight: Promise<void> | null = null;
async function load() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      let r = await fetch("/api/sop/stepbar");
      if (r.status === 404) {
        const d = (await r.json().catch(() => ({}))) as { detail?: string };
        if (d.detail === "没有这部剧") throw new Error("登记表里没有当前剧");
        r = await fetch("/api/pipeline/status"); // 新接口还没生效（后台没重启）：退回同一个 sop_gate 判定
        if (!r.ok) throw new Error(r.status === 404 ? "进度接口还没生效，后台重启后自动出现" : `HTTP ${r.status}`);
        cache = { at: Date.now(), v: fromPipe(await r.json()), err: null };
      } else if (!r.ok) {
        const d = (await r.json().catch(() => ({}))) as { detail?: string };
        throw new Error(d.detail ?? `HTTP ${r.status}`);
      } else cache = { at: Date.now(), v: humanize((await r.json()) as Stepbar), err: null };
    } catch (e) {
      const m = String((e as Error).message ?? e);
      cache = { at: Date.now(), v: cache?.v ?? null, err: /fetch|network/i.test(m) ? "后台服务没响应，系统每 30 秒自动再试" : m };
    }
    subs.forEach((f) => f());
  })().finally(() => (inflight = null));
  return inflight;
}

export function useStepbar(): { v: Stepbar | null; err: string | null; reload: () => void } {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    subs.add(f);
    if (!cache || Date.now() - cache.at > 30000) void load();
    const t = window.setInterval(() => void load(), 30000);
    return () => {
      subs.delete(f);
      window.clearInterval(t);
    };
  }, []);
  return { v: cache?.v ?? null, err: cache?.err ?? null, reload: () => void load() };
}
