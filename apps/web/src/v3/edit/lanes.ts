// fredw-92/UXF2（审查 #25 / #44 / #47）：渲染道的共享读数——道名（gpu33:0 …）、在做什么、排队负载、是否被 LoRA 训练 / Qwen 锁着。
// 来源：GET /api/render/lanes（道表 + 活动）+ GET /api/gpu3/gpus（train.lock / gpu.lock，只对 gpu33 的卡）。
// 有组件在用时每 15 s 刷新；接口 404 后停止轮询（不再每 5 秒打一次 404）。
// fredw-92/UXF4（审查 N5 / N7 / #25）：卡名只有一种写法 cardName()（“gpu33·卡0”），技术细节（地址 / 隧道 / 显卡型号）只放 cardTip() 悬停；
//   “自动”落到哪条道读后端 pick_lane 的结果（/api/render/lanes 的 auto），预计耗时读后端 jobs.estimate 同口径的 eta 表。
import { useEffect, useSyncExternalStore } from "react";

export type LanePick = number | string; // 0 / 3 / "gpu36:1" / "auto"

export interface LaneInfo {
  gpu: number | string;
  /** 道名，例：gpu33:0 */
  id: string;
  server?: string;
  reachable: boolean;
  activity: "image" | "video" | "external" | "idle" | string;
  queued: number;
  /** 这条道上已有的活（秒，含别人直接投的外部任务） */
  load_s: number;
  image_pref: boolean;
  max_frames?: number;
  /** 被谁锁着（LoRA 训练 / Qwen / 别的进程）；人话 */
  lock: string | null;
  /** 后端判定：可达且没有训练锁（pick_lane 只在 ok 的道里挑） */
  ok: boolean;
  /** 技术细节（悬停用）：ComfyUI 地址、显卡型号、配置里的长名 */
  url?: string;
  gpuName?: string | null;
  longLabel?: string;
}

/** 后端 jobs.eta_table：kind → 道名 → 单次耗时 */
type EtaTable = Partial<Record<"frame" | "video" | "asset_gen", Record<string, { per_s: number; samples: number }>>>;

interface Snap {
  lanes: LaneInfo[] | null;
  err: string | null;
  at: number;
  /** 后端 pick_lane 现在会选哪条道（提交时同一个函数） */
  auto?: Partial<Record<"image" | "video", number | string | null>>;
  eta?: EtaTable;
  /** 是上次会话缓存的道表（还没读到新数据） */
  stale?: boolean;
}

// fredw-92/UXF5（审查 #3）：首屏不等 /api/render/lanes（后端忙时要 2–10 s）——先用上次读到的道表（本机 localStorage，
//   标 stale），读到新数据后替换。存取都包 try：隐私窗口 / 禁用存储时只是没有首屏缓存。
const CACHE_KEY = "ns.lanes.last";
function readCache(): Snap {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (raw) {
      const c = JSON.parse(raw) as { lanes?: LaneInfo[]; auto?: Snap["auto"]; eta?: EtaTable; at?: number };
      if (Array.isArray(c.lanes) && c.lanes.length) return { lanes: c.lanes, err: null, at: c.at ?? 0, auto: c.auto, eta: c.eta, stale: true };
    }
  } catch {
    /* 没有缓存 */
  }
  return { lanes: null, err: null, at: 0 };
}
function writeCache(s: Snap) {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify({ lanes: s.lanes, auto: s.auto, eta: s.eta, at: s.at }));
  } catch {
    /* 写不进去：下次首屏照样等接口 */
  }
}
let snap: Snap = typeof window !== "undefined" ? readCache() : { lanes: null, err: null, at: 0 };
const subs = new Set<() => void>();
let users = 0;
let timer: number | null = null;
let dead = false; // 接口不存在（404）→ 不再轮询
const POLL_MS = 15000;

/** train.lock 的主人 → 人话（不出现 qwen-agent / pid 之类内部词） */
export function lockWord(owner: string | null | undefined): string | null {
  if (!owner) return null;
  if (/lora|train/i.test(owner)) return "LoRA 训练占用中";
  if (/qwen/i.test(owner)) return "Qwen 写作模型占用中";
  if (/comfy/i.test(owner)) return null; // 渲染自己在用，不算锁
  return "被其他任务锁定";
}

async function load() {
  try {
    const r = await fetch("/api/render/lanes");
    if (r.status === 404) {
      dead = true;
      snap = { lanes: null, err: "后端没有道表接口", at: Date.now() };
      return;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    type Raw = Partial<Omit<LaneInfo, "ok">> & { ok?: boolean; train_locked?: boolean; label?: string; gpu_name?: string | null };
    const d = (await r.json()) as { lanes?: Raw[]; auto?: Snap["auto"]; eta?: EtaTable };
    let locks: Record<string, string | null> = {};
    try {
      const g = await fetch("/api/gpu3/gpus");
      if (g.ok) {
        const gd = (await g.json()) as { gpus?: { id: number; train_lock: string | null; gpu_lock: string | null; paused?: string | null }[] };
        locks = Object.fromEntries((gd.gpus ?? []).map((x) => [String(x.id), lockWord(x.train_lock) ?? (x.paused ? `预留：${x.paused}` : null)]));
      }
    } catch {
      /* 锁信息读不到：只是少一条提示 */
    }
    const lanes: LaneInfo[] = (d.lanes ?? []).map((l) => {
      const server = l.server ?? "";
      const local = server === "gpu33" || server === "gpu3" || server === "";
      const lock = local && typeof l.gpu === "number" ? locks[String(l.gpu)] ?? null : null;
      return {
        gpu: l.gpu as number | string,
        id: l.id ?? laneId(l.gpu as number | string),
        server,
        reachable: l.reachable !== false,
        activity: l.train_locked && (l.activity ?? "idle") === "idle" ? "train" : l.activity ?? "idle",
        queued: l.queued ?? 0,
        load_s: l.load_s ?? 0,
        image_pref: !!l.image_pref,
        max_frames: l.max_frames,
        lock: lock ?? (l.train_locked ? "LoRA 训练占用中" : null),
        ok: (l.ok ?? l.reachable !== false) && !l.train_locked,
        url: l.url,
        gpuName: l.gpu_name ?? null,
        longLabel: l.label,
      };
    });
    snap = { lanes, err: null, at: Date.now(), auto: d.auto, eta: d.eta };
    writeCache(snap);
  } catch (e) {
    snap = { ...snap, err: (e as Error).message, at: Date.now() };
  } finally {
    subs.forEach((f) => f());
  }
}

function start() {
  if (timer != null || dead) return;
  void load();
  timer = window.setInterval(() => (dead ? stop() : void load()), POLL_MS);
}
function stop() {
  if (timer != null) window.clearInterval(timer);
  timer = null;
}

/** 道表（null = 还没读到 / 接口没有）；挂载时开始轮询，全部卸载后停 */
export function useLanes(): Snap {
  useEffect(() => {
    users++;
    start();
    return () => {
      users--;
      if (users <= 0) stop();
    };
  }, []);
  return useSyncExternalStore(
    (f) => (subs.add(f), () => void subs.delete(f)),
    () => snap,
  );
}
export const getLanes = () => snap.lanes;
export const refreshLanes = () => void load();

/** 道 id（后端 lane_name 同规则）：0 → gpu33:0；"gpu36:1" 原样；"GPU3" / "3" → gpu33:3 */
export function laneId(g: LanePick | null | undefined): string {
  if (g == null) return "";
  const s = String(g).trim();
  if (/^\d+$/.test(s)) return `gpu33:${s}`;
  const m = /^gpu\s*(\d+)$/i.exec(s);
  if (m) return `gpu33:${m[1]}`;
  return s;
}

/** 全站唯一的卡名（审查 N7）：gpu33:0 / 0 / "GPU0" → “gpu33·卡0”；"gpu36:1" → “gpu36·卡1”；"auto" → “自动分配” */
export function cardName(g: LanePick | null | undefined): string {
  if (g == null || g === "") return "卡未定";
  if (g === "auto") return "自动分配";
  const id = laneId(g);
  const m = /^([a-z]+\d+):(\d+)$/i.exec(id);
  return m ? `${m[1]}·卡${m[2]}` : id;
}

/** 卡的技术细节（只放悬停提示）：道 id、显卡、地址 / 隧道 */
export function cardTip(g: LanePick | null | undefined): string {
  if (g == null || g === "auto") return "";
  const id = laneId(g);
  const l = snap.lanes?.find((x) => x.id === id || String(x.gpu) === String(g));
  const parts = [`${cardName(g)} = ${id}`];
  if (l?.gpuName) parts.push(l.gpuName.replace(/^cuda:\d+\s*/, "").replace(/\s*:\s*cudaMallocAsync$/, ""));
  if (l?.longLabel && l.longLabel !== id) parts.push(l.longLabel);
  else if (l?.url) parts.push(`ComfyUI ${l.url.replace(/^https?:\/\//, "")}${l.server && l.server !== "gpu33" ? `（隧道 → ${l.server}）` : ""}`);
  if (l?.max_frames) parts.push(`一次最多 ${l.max_frames} 帧视频`);
  return parts.join(" · ");
}

/** 兼容旧名：道名 = cardName */
export const laneName = cardName;

/** 后端 jobs.estimate 同口径的单次耗时（秒）；kind = 出图 frame / 视频 video / 资产 asset_gen。没有道表 → null */
export function laneEta(kind: "frame" | "video" | "asset_gen", g: LanePick, frames?: number | null): { per: number; samples: number } | null {
  const tab = snap.eta?.[kind];
  if (!tab) return null;
  const pick = g === "auto" ? autoLane(kind === "video" ? "video" : "image", snap.lanes, frames)?.gpu : g;
  const row = pick != null ? tab[laneId(pick)] : undefined;
  if (row) return { per: row.per_s, samples: row.samples };
  const any = Object.values(tab).filter((x) => x.samples);
  if (!any.length) return null;
  const xs = any.map((x) => x.per_s).sort((a, b) => a - b);
  return { per: xs[Math.floor(xs.length / 2)], samples: 0 };
}

/** 这次会落到的那张卡现在被谁占着（"external" = 不经本队列的外部任务，例如资产 / 实验线直连；"train" = 训练）。
 *  界面的“约 N 秒”只按本队列算——卡被外部任务占着时实际要等，不能只写 N 秒（总调度 11-01：ep01-S1 写 51 秒、实际 10 分钟） */
export function laneBusyBy(kind: "image" | "video", g: LanePick, frames?: number | null): "external" | "train" | null {
  const l = g === "auto" ? autoLane(kind, snap.lanes, frames) : (snap.lanes ?? []).find((x) => laneId(x.gpu) === laneId(g)) ?? null;
  if (!l) return null;
  return l.activity === "external" || l.activity === "train" ? l.activity : null;
}

const ACT: Record<string, string> = { image: "正在出图", video: "正在出视频", external: "其他任务占用", idle: "空闲", train: "训练占用" };

/** “自动”为什么选这张卡（一句话，写在下拉里） */
export function autoWhy(kind: "image" | "video", l: LaneInfo | null, lanes: LaneInfo[] | null): string {
  if (!l) return "没有能用的卡";
  if (kind === "image") {
    if (l.image_pref) return l.load_s ? "出图卡只排着出图，等它" : "出图卡空闲";
    const pref = (lanes ?? []).find((x) => x.image_pref);
    return pref ? `出图卡${!pref.ok || pref.lock ? "被占用" : pref.activity === "video" ? "在出视频" : "忙"}，改用空闲卡` : "空闲卡";
  }
  return l.load_s ? "所有卡都忙，排最短的队" : l.image_pref ? "其他卡都忙，出图卡空着" : "空闲卡";
}

/** 一条道现在的状态（人话） */
export function laneState(l: LaneInfo): string {
  if (!l.reachable) return "连不上";
  // UXF5：训练占用且有锁说明时只写锁说明（以前是“训练占用 · LoRA 训练占用中”）
  const parts = l.activity === "train" && l.lock ? [] : [ACT[l.activity] ?? l.activity];
  if (l.queued > 1) parts.push(`队列 ${l.queued}`);
  if (l.lock) parts.push(l.lock);
  return parts.join(" · ");
}

/** 自动分配会落到哪条道：优先用后端 pick_lane 的结果（提交时同一个函数）；读不到时按同口径近似：
 *  出图偏好出图卡（出图卡只排着出图任务也等它），视频偏好非出图卡；被训练锁 / 连不上的卡不算 */
export function autoLane(kind: "image" | "video", lanes: LaneInfo[] | null, frames?: number | null): LaneInfo | null {
  const ok = (lanes ?? []).filter((l) => l.ok && !l.lock);
  if (!ok.length) return null;
  const be = snap.auto?.[kind];
  if (be != null && lanes === snap.lanes && !(kind === "video" && frames)) {
    const hit = ok.find((l) => String(l.gpu) === String(be));
    if (hit) return hit;
  }
  const idle = ok.filter((l) => !l.load_s);
  if (kind === "image") {
    const pref = ok.find((l) => l.image_pref && l.activity === "image" && l.load_s <= 140);
    if (pref && !idle.some((l) => l.image_pref)) return pref;
    if (idle.length) return [...idle].sort((a, b) => Number(b.image_pref) - Number(a.image_pref))[0];
    return [...ok].sort((a, b) => a.load_s - b.load_s || Number(b.image_pref) - Number(a.image_pref))[0];
  }
  if (frames) {
    const fit = ok.filter((l) => !l.max_frames || l.max_frames >= frames);
    if (!fit.length) return null;
  }
  const others = idle.filter((l) => !l.image_pref && (!frames || !l.max_frames || l.max_frames >= frames));
  if (others.length) return others[0];
  if (idle.length) return idle[0];
  const pool = ok.filter((l) => !l.image_pref);
  return [...(pool.length ? pool : ok)].sort((a, b) => a.load_s - b.load_s)[0];
}
