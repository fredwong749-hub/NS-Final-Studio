// UIRSI2 · L-116「待你看」队列的前端数据层（GET /api/owner/queue，POST /api/owner/decide | undo）。
// 一份模块级缓存 + 订阅：顶栏徽标、队列页、画布“选中待审 / 待你看”计数、每镜“机签通过 vN”都读这一份（data_parity D-QUEUE：页面数 = 队列数）。
import { useEffect, useState } from "react";

export interface QueueOption {
  key: string;
  label: string;
}
export interface QueueMedia {
  url: string | null;
  kind: "image" | "video";
  label?: string;
  key?: string;
}
export interface QueueScore {
  id: string;
  title: string;
  status: string;
  detail: string;
}
export interface QueueItem {
  id: string;
  kind: "decide" | "spot" | "pick";
  kind_label: string;
  category: string;
  category_label: string;
  title: string;
  detail: string;
  quote?: string;
  source: string;
  at?: string;
  sid?: string;
  stage?: string;
  n?: number;
  script?: string | null;
  media: QueueMedia[];
  scores: QueueScore[];
  options: QueueOption[];
  recommend: { choice: string; why: string } | null;
  link?: string | null;
}
export interface OwnerQueue {
  count: number;
  counts: Record<"decide" | "spot" | "pick", number>;
  items: QueueItem[];
  auto_today: { passed: number; rejected: number; signed: number; policy: number; redo: number; n_image: number; n_last: number; n_video: number; agreement?: number | null; agreement_n?: number | null; total: number };
  master_waits: { n: number; title: string };
  machine_signed: Record<string, { image?: number; last?: number }>;
  autosign_mode: string;
  status: "ok" | "error";
  status_label: string;
  source_errors: string[];
}

let cur: OwnerQueue | null = null;
let err: string | null = null;
const subs = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;
const emit = () => subs.forEach((f) => f());

export async function refreshQueue(): Promise<OwnerQueue | null> {
  try {
    const r = await fetch("/api/owner/queue", { credentials: "same-origin" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    cur = (await r.json()) as OwnerQueue;
    err = null;
  } catch (e) {
    // 读不到队列 ≠ 没有要看的：显式记错误，界面写“队列读取失败”
    err = (e as Error).message;
  }
  emit();
  return cur;
}

export function getQueue() {
  return { q: cur, err };
}

/** 队列读取失败的一句话（接口读不到 / 某个来源坏了），没失败返回 null */
export function queueFailText(q: OwnerQueue | null, e: string | null): string | null {
  if (e) return `队列读取失败：接口 /api/owner/queue（${e}）`;
  if (q && q.status === "error") return q.status_label || "队列读取失败";
  return null;
}

/** 这一镜这一阶段当前版本是否机签通过：返回版本号（= 当前版本）或 null */
export function machineSignedN(sid: string, stage: "image" | "last"): number | null {
  return cur?.machine_signed?.[sid]?.[stage] ?? null;
}

/** 这一镜这一阶段这一版是否是“待你看”里的机签抽检样本 */
export function inSpotQueue(sid: string, stage: "image" | "last", n: number | null | undefined): boolean {
  return n != null && !!cur?.items.some((x) => x.kind === "spot" && x.sid === sid && x.stage === stage && x.n === n);
}

/** 某集在队列里的条目（按镜号 sid 前缀） */
export function queueItemsOfEp(q: OwnerQueue | null, ep: number): QueueItem[] {
  const pre = `ep${String(ep).padStart(2, "0")}-`;
  return (q?.items ?? []).filter((x) => x.sid?.startsWith(pre));
}

export function useOwnerQueue() {
  const [, setN] = useState(0);
  useEffect(() => {
    const f = () => setN((x) => x + 1);
    subs.add(f);
    if (!timer) {
      void refreshQueue();
      timer = setInterval(() => void refreshQueue(), 20000);
    }
    return () => {
      subs.delete(f);
      if (!subs.size && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, []);
  return getQueue();
}

async function post(path: string, body: Record<string, unknown>) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...body, by: "owner" }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `HTTP ${r.status}`);
  return j;
}

/** 一键决定（登录即本人：by=owner，服务器按登录会话认人并记审计）；reason 选填 */
export async function decideItem(id: string, choice: string, reason = "") {
  const j = await post("/api/owner/decide", { id, choice, reason });
  await refreshQueue();
  return j;
}

export async function undoItem(id: string) {
  const j = await post("/api/owner/undo", { id });
  await refreshQueue();
  return j;
}
