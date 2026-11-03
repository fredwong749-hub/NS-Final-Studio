// UIRSI2 · L-116「待你看」队列的前端数据层（GET /api/owner/queue，POST /api/owner/decide | undo）。
// 一份模块级缓存 + 订阅：顶栏徽标、队列页、画布“选中待审 / 待你看”计数、每镜“机签通过 vN”都读这一份（data_parity D-QUEUE：页面数 = 队列数）。
import { useEffect, useState } from "react";
import type { LookPerson } from "../types";

export interface QueueOption {
  key: string;
  label: string;
}
export interface QueueMedia {
  url: string | null;
  kind: "image" | "video" | "audio";
  label?: string;
  key?: string;
}
export interface QueueScore {
  id: string;
  title: string;
  status: string;
  detail: string;
}
/** 通知直说（L-172 分期 1）：每条待办的按钮 = 现有后端入口，不另起登记链。method=LINK 时用 href；POST 时 path + body（body.choice 就是要提交的 choice） */
export interface QueueAction {
  key: string;
  label: string;
  style: "primary" | "secondary" | "link";
  method: "POST" | "LINK";
  path?: string | null;
  body?: { id: string; choice: string } | null;
  href?: string | null;
  needs_reason: boolean;
  ask?: string;
}
export type BlockLevel = "red" | "yellow" | "grey";
export interface QueueItem {
  id: string;
  kind: "gate" | "decide" | "spot" | "pick" | "info";
  kind_label: string;
  /** 通知直说（L-172）：一句“要你做什么”/ 为什么找你 / ≤3 个按钮 / 阻塞程度（red 卡住 · yellow 等你 · grey 只读） */
  say_what?: string;
  why?: string;
  actions?: QueueAction[];
  block_level?: BlockLevel;
  level_label?: string;
  sub_kind?: string;
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
  run?: string;
  /** 统一挑选入口（有值 = 点“用这个”直接 POST 到它，选定后真正生效；INBOXPICK-S） */
  pick_api?: string | null;
  pick_state?: { state?: string; error?: string | null; reason?: string; delegate?: { label?: string; choice?: string; score?: number | null; at?: string } } | null;
  candidates?: PickCandidate[];
  /** V2CUT-O 11-03：确认本集造型（pick:look）——本集全部人物（人名 / 本集造型 / 缩略图），一键确认整集 */
  people?: LookPerson[];
  episode?: number;
}
export interface PickCandidate {
  key: string;
  label: string;
  audio?: string | null;
  thumb?: string | null;
  scores?: QueueScore[];
  full?: string | null;
  url?: string | null;
  kind?: "image" | "video" | "audio";
}
export interface OwnerQueue {
  count: number;
  counts: Record<"gate" | "decide" | "spot" | "pick", number>;
  items: QueueItem[];
  /** 通知直说：按阻塞程度计数；readonly = 只读告知（灰、无按钮、不进 count） */
  levels?: Record<BlockLevel, number>;
  readonly?: QueueItem[];
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
    const r = await fetch("/api/owner/inbox", { credentials: "same-origin" })   // L-134：待办通知中心 = 待你看队列 + 写作闸门，顶栏数字 / 标签页标题 / #/queue 页同一个来源;
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
  // W5 UIUX：不露接口地址；技术原因只在悬停里（title）由调用方决定是否显示
  if (e) return `待办暂时读不到（${/fetch|network|HTTP 5/i.test(e) ? "后台服务没响应" : e}），系统每 20 秒自动再试`;
  if (q && q.status === "error") return q.status_label || "待办有一部分读不到，系统在自动再试";
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

/** 待办中心里直接挑选（统一入口 POST /api/owner/pick）：先回 202 收下，后台处理；选定后条目从通知里消失。choice="revise" = “修改”。
 *  by 不传——服务器只认登录会话；处理失败的原因在下一次刷新时出现在 pick_state.error */
export async function pickItem(id: string, choice: string, reason = "") {
  const r = await fetch("/api/owner/pick", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify({ id, choice, reason }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `HTTP ${r.status}`);
  for (const wait of [500, 1500, 3000]) {   // 后台异步处理：稍等几次，让通知刷掉；处理失败会带着原因重新出现
    await new Promise((x) => setTimeout(x, wait));
    await refreshQueue();
    if (!cur?.items.some((x) => x.id === id)) break;
  }
  return j as { ok: boolean; accepted: boolean; duplicate: boolean; state: string };
}

export async function undoItem(id: string) {
  const j = await post("/api/owner/undo", { id });
  await refreshQueue();
  return j;
}

/** 浏览器标签页标题前加未处理数：(3) 原标题；没有待办时还原。顶栏常驻组件调用，和顶栏数字同一个来源 */
let baseTitle: string | null = null;
export function useTabBadge() {
  const { q } = useOwnerQueue();
  const n = q?.count ?? 0;
  useEffect(() => {
    if (baseTitle == null) baseTitle = document.title.replace(/^\(\d+\)\s*/, "");
    document.title = n > 0 ? `(${n}) ${baseTitle}` : baseTitle;
  }, [n]);
}
