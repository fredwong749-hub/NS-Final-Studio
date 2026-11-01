// 从 RenderTasks.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）；GPUVIEW 11-01 授权（LOCKS CONSENT）
import { useEffect, useSyncExternalStore } from "react";

import { useLiveEvent } from "../v3/live";

export type RTStatus = "pending" | "rendering" | "failed" | "done";
export interface RTRow {
  id: string;
  type: string;
  episode: number | null;
  shot: string | null;
  obj: string | null;
  title: string;
  agent: string | null;
  lane: string | null;
  status: RTStatus;
  sub: string | null;
  progress: { step?: number; steps?: number; pct?: number; step_left_s?: number | null; source?: string } | null;
  eta_s: number | null;
  elapsed_s: number | null;
  started: number | null;
  attempt: number | null;
  max_attempts: number | null;
  error: { what?: string; next?: string; raw?: string | null; resolved_by?: string | null; resolved_text?: string } | null;
  thumb: string | null;
  full: string | null;
  link: string | null;
  source: "ns_api" | "comfy" | "heartbeat" | "story" | "producer" | "plan";
  ids: { job_id?: string; prompt_id?: string; client_id?: string; seed?: number | string | null; take?: number | null; job?: string };
  at: number | null;
  batch?: { idx?: number; total?: number } | null;
  /** IMGPERF：当前阶段开始时间（秒）；行里写“本段 m:ss” */
  stage_since?: number | null;
}
export interface RTData {
  at: string;
  ts: number;
  run: string | null;
  /** UIRSI r42：queued = 真在排队（不含计划）、planned = 计划中的镜、failed_recent = 最近 recent_fail_h 小时的失败 */
  counts: Record<RTStatus | "all", number> & { queued?: number; planned?: number; failed_recent?: number; recent_fail_h?: number };
  rows: RTRow[];
  sources: Record<string, number>;
  episodes: number[];
  types: string[];
  /** 前端用 /api/jobs 拼的（后端还没有 /api/render-tasks） */
  fallback?: boolean;
}

// ---------------------------------------------------------------- 共享读数（全站一份轮询）
interface Snap {
  data: RTData | null;
  err: string | null;
}
let snap: Snap = { data: null, err: null };
const subs = new Set<() => void>();
let users = 0;
let timer: number | null = null;
let inflight = false;
const POLL_MS = 4000;

const ST_MAP: Record<string, RTStatus> = { queued: "pending", running: "rendering", failed: "failed", done: "done" };
const STAGE_TYPE: Record<string, string> = { image: "首帧", first: "首帧", last: "尾帧", video: "视频", asset: "资产图", asset_gen: "资产图" };

/** 旧后端兜底：/api/jobs → 行（只有画布任务；报错人话用同一套关键词） */
function fromJobs(js: Record<string, unknown>[]): RTData {
  const rows: RTRow[] = [];
  for (const j of js) {
    const state = String(j.state ?? "");
    if (state === "cancelled") continue;
    const sid = (j.shot_id as string | null) ?? null;
    const m = /^ep(\d+)-(S\d+)$/.exec(sid ?? "");
    const type = STAGE_TYPE[String(j.stage ?? "")] ?? (j.kind === "video" ? "视频" : "首帧");
    const ep = m ? Number(m[1]) : null;
    const st = ST_MAP[state] ?? "pending";
    const t = (s: unknown) => (s ? new Date(String(s)).getTime() / 1000 : null);
    const started = t(j.started_at);
    rows.push({
      id: `job:${j.id}`, type, episode: ep, shot: m ? m[2] : null, obj: sid?.startsWith("asset:") ? sid.slice(6) : null,
      title: [type, ep ? `第${ep}集${m ? ` ${m[2]}` : ""}` : null].filter(Boolean).join(" · "), agent: "画布",
      lane: j.gpu != null ? (typeof j.gpu === "number" ? `gpu33:${j.gpu}` : String(j.gpu)) : null, status: st,
      sub: st === "pending" ? "排队" : st === "rendering" ? "渲染中" : st === "failed" ? "失败" : "完成",
      ...(() => {
        const p = j.progress as { stage?: string; label?: string; since?: string } | undefined;
        return p?.label && (st === "rendering" || st === "pending") && !["queued", "done", "failed", "cancelled"].includes(p.stage ?? "") ? { sub: p.label, stage_since: t(p.since) } : {};
      })(),
      progress: null, eta_s: (j.eta_s as number) ?? null, elapsed_s: started ? ((t(j.finished_at) ?? Date.now() / 1000) - started) : null,
      started, attempt: null, max_attempts: null,
      error: st === "failed" ? { what: humanErr(String(j.error ?? "")), raw: (j.error as string) ?? null } : null,
      thumb: null, full: null, link: m ? `#ep${m[1].padStart(2, "0")}-${m[2]}` : null, source: "ns_api",
      ids: { job_id: String(j.id), prompt_id: j.prompt_id as string, seed: (j.seed as number) ?? null }, at: t(j.finished_at) ?? started ?? t(j.created_at),
    });
  }
  const counts = { all: rows.length, pending: 0, rendering: 0, failed: 0, done: 0 } as RTData["counts"];
  rows.forEach((r) => counts[r.status]++);
  return { at: new Date().toISOString(), ts: Date.now() / 1000, run: null, counts, rows, sources: { ns_api: rows.length }, episodes: [...new Set(rows.map((r) => r.episode).filter((x): x is number => x != null))], types: [...new Set(rows.map((r) => r.type))], fallback: true };
}

export function humanErr(e: string): string {
  if (!e) return "没出成";
  if (/No such file or directory/.test(e)) return /refcrops/i.test(e) ? "参考裁切图刚好在重建" : "找不到文件";
  if (/out of memory|OutOfMemory|allocation on device/i.test(e)) return "显存不够（同一张卡上还有别的任务）";
  if (/API 重启/.test(e)) return "API 重启时被打断（不是画面问题）";
  if (/timed? ?out|超时/i.test(e)) return "超时：卡太忙或隧道慢";
  if (/connection|refused|unreachable/i.test(e)) return "连不上出图卡";
  return e.split("\n")[0].slice(0, 80);
}

let fallbackMode = false;
async function load() {
  if (inflight) return;
  inflight = true;
  try {
    let r = fallbackMode ? null : await fetch("/api/render-tasks");
    if (r && r.status === 404) fallbackMode = true;
    if (fallbackMode) {
      r = await fetch("/api/jobs");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      snap = { data: fromJobs(await r.json()), err: null };
    } else {
      if (!r || !r.ok) throw new Error(`HTTP ${r?.status}`);
      snap = { data: (await r.json()) as RTData, err: null };
    }
  } catch (e) {
    snap = { ...snap, err: (e as Error).message };
  } finally {
    inflight = false;
    subs.forEach((f) => f());
  }
}
export const refreshRenderTasks = () => void load();

/** 渲染任务（全站一份）：挂载时开始每 4 秒轮询；实时事件（出图 / 视频 / 任务 / 写作）来了立即重取 */
export function useRenderTasks(): Snap {
  useEffect(() => {
    users++;
    if (timer == null) {
      void load();
      timer = window.setInterval(() => void load(), POLL_MS);
    }
    return () => {
      users--;
      if (users <= 0 && timer != null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
  }, []);
  useLiveEvent((e) => ["job", "frame", "lastframe", "video", "stage", "voice", "asset"].includes(e.type), () => void load(), 800);
  return useSyncExternalStore(
    (f) => (subs.add(f), () => void subs.delete(f)),
    () => snap,
  );
}

// ---------------------------------------------------------------- 小工具
export const fmtS = (s: number | null | undefined) => {
  if (s == null || !isFinite(s)) return "";
  s = Math.max(0, s);
  if (s < 60) return `${Math.round(s)} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${String(Math.round(s % 60)).padStart(2, "0")} 秒`;
  return `${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分`;
};
export function ago(ts: number | null | undefined): { text: string; abs: string } {
  if (!ts) return { text: "", abs: "" };
  const d = Date.now() / 1000 - ts;
  const abs = new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
  const text = d < 45 ? "刚刚" : d < 3600 ? `${Math.round(d / 60)} 分钟前` : d < 86400 ? `${Math.round(d / 3600)} 小时前` : `${Math.round(d / 86400)} 天前`;
  return { text, abs };
}

/** 筛选（集："" 全部 / "none" 不属于某集 / "3"；类型："" 全部）——列表和任何显示数字的地方都用这一个，数字才对得上 */
export interface RTFilter {
  ep: string;
  type: string;
}
export function filterRows(rows: RTRow[], f: RTFilter): RTRow[] {
  return rows.filter((r) => (!f.ep || String(r.episode ?? "") === f.ep || (f.ep === "none" && r.episode == null)) && (!f.type || r.type === f.type));
}
/** 按状态计数（UIAUDIT verify_gpuview_r1 P2：底栏标签上的“失败 N”与列表同一筛选） */
export function countRows(rows: RTRow[]): RTData["counts"] {
  const c = { all: rows.length, pending: 0, rendering: 0, failed: 0, done: 0 };
  rows.forEach((r) => c[r.status]++);
  return c;
}
