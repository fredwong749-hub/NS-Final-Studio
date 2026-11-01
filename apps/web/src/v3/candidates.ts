// UIRSI（BE-5 配套）：流水线登记进版本链、但还没设为当前的候选图（GET /api/candidates?ep=N，后端 ns_api/takes_ui.py）。
// 画布格子：没有当前版本时显示最新候选“候选 #n · 暂定 · 旧配方”；一键“用这张”= activate，10 秒内可撤销。
import { useEffect, useState } from "react";
import { showUndo } from "../ds/Undo.helpers";

export type Cand = { n: number; url: string; label: string | null; tentative: boolean; source: string | null; bad: string | null; ok?: boolean; why_not?: string | null; created_at: string | null; contract?: string | null; rejected?: boolean; /** UIRSI r40：current = 现行剧本版本；old = 剧本更新前出的（不作候选） */ script?: "current" | "old" | "unknown" };
/** active_quarantined：当前版本已隔离（UIRSI r41 旧剧本版本），接口把 active 当空，这里记原来是哪一版 */
export type CandStage = { active: number | null; takes: Cand[]; active_quarantined?: number };
/** UIRSI r40：每镜另带 video（视频各版的剧本版本）和 status（状态标签，后端 ns_api/shot_status.py） */
export type CandShots = Record<string, Partial<Record<"image" | "last", CandStage>> & {
  video?: { active: number | null; takes: { n: number; script?: "current" | "old" | "unknown"; created_at?: string | null }[] };
  status?: import("./StatusTags.helpers").ShotStatusTags;
}>;

const cache = new Map<number, Promise<CandShots>>();
const subs = new Set<() => void>();
export function loadCandidates(ep: number, force = false): Promise<CandShots> {
  let p = cache.get(ep);
  if (!p || force) {
    p = fetch(`/api/candidates?ep=${ep}`)
      .then((r) => (r.ok ? r.json() : { shots: {} }))
      .then((d: { shots: CandShots }) => d.shots ?? {}, () => ({}) as CandShots);
    cache.set(ep, p);
  }
  return p;
}
export function reloadCandidates(ep: number) {
  void loadCandidates(ep, true).then(() => subs.forEach((f) => f()));
}
export function useCandidates(ep: number): CandShots | null {
  const [v, setV] = useState<CandShots | null>(null);
  useEffect(() => {
    let alive = true;
    const get = () => void loadCandidates(ep).then((x) => alive && setV(x));
    get();
    subs.add(get);
    return () => {
      alive = false;
      subs.delete(get);
    };
  }, [ep]);
  return v;
}
export const epOf = (shot: string) => Number(shot.match(/^ep(\d+)/)?.[1]) || 0;

/** 这一格要显示的候选：有当前版本就不需要（返回 null）；否则最新一张“通过的”（暂定、规则过期只做角标，不藏）。
 *  项目方判过不合格的配方（旧配方）、坏图、流水线没通过的不作候选（总调度 11-01：只给他看通过的）。 */
export const passed = (t: Cand) => t.ok !== false && !t.bad;
export function candidateFor(c: CandShots | null, shot: string, stage: "image" | "last"): Cand | null {
  const s = c?.[shot]?.[stage];
  if (!s || s.active != null || !s.takes.length) return null;
  return [...s.takes].reverse().find(passed) ?? null;
}
/** 有版本但一张都不合格（例如只有旧配方）：格子仍写“未出”，只给一个“看旧配方 N 张”的小入口 */
export function rejectedFor(c: CandShots | null, shot: string, stage: "image" | "last"): Cand[] {
  const s = c?.[shot]?.[stage];
  if (!s || s.active != null) return [];
  return s.takes.filter((t) => !passed(t));
}
/** UIRSI r35：后端标签可能是流水线内部记录（“ASSETMASTER 已出（PRODUCER 接手登记）”），agent 名 / 登记过程 / 文件名不给项目方看——
 *  按“·”拆段，含大写内部代号（≥5 个连续大写字母）、“接手 / 登记”、文件名的段丢掉；“旧配方 / 新配方”这类人话照常显示 */
const INTERNAL_SEG = /[A-Z]{5,}|接手|登记|\.(json|ya?ml|py|md)\b|_overrides/;
export const plainLabel = (l: string | null | undefined) =>
  (l ?? "")
    .split(/\s*[·・]\s*/)
    .filter((x) => x && !INTERNAL_SEG.test(x))
    .join(" · ");
export const candLabel = (t: Cand) => [t.tentative ? "暂定" : "", plainLabel(t.label)].filter(Boolean).join(" · ");

async function post(url: string, body?: unknown) {
  const r = await fetch(url, { method: "POST", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) {
    let m = `HTTP ${r.status}`;
    try {
      const d = await r.json();
      if (d?.detail) m = String(d.detail);
    } catch {
      /* 非 JSON */
    }
    throw new Error(m);
  }
  return r.json();
}

/** 一键“用这张”：设为当前版本；提示条 10 秒内撤销（原来有当前版本就切回去，原来没有就撤成没有） */
export async function pickTake(shot: string, stage: "image" | "last", n: number, prev: number | null, after: () => void, notify: (m: string, k?: "ok" | "err") => void) {
  const name = `${shot.split("-")[1]} ${stage === "image" ? "首帧" : "尾帧"}`;
  try {
    await post(`/api/shots/${shot}/takes/${stage}/${n}/activate`);
  } catch (e) {
    notify(`${name} 没设成：${(e as Error).message}`, "err");
    return false;
  }
  reloadCandidates(epOf(shot));
  after();
  showUndo(`已用 ${name} #${n}`, async () => {
    if (prev != null) await post(`/api/shots/${shot}/takes/${stage}/${prev}/activate`);
    else await post(`/api/shots/${shot}/takes/${stage}/unset`, { expect: n });
    reloadCandidates(epOf(shot));
    after();
  });
  return true;
}
