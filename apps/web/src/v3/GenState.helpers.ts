// ASSETUX L-120：全站通用的“生成状态”纯函数（项目方 11-02：点“再生成”后没有任何反馈，要像呼吸灯那样提示正在生成或排队，并预估什么时候做完）。
// 数据源：GET /api/jobs（同一份任务队列：资产 gen-jobs / frame-jobs / video-jobs）。排队第 N 按同一条 GPU 道上更早入队、还没开始的任务数算。
// 预计完成 = 开始时间 + 预计耗时（job.eta_s，后端已按“该卡同类任务最近耗时的中位数 × 前面任务数”估好）；没有 eta_s 就用历史中位数；再没有用兜底。

export type JobLite = {
  id?: string;
  job_id?: string;
  state?: string; // queued | running | done | failed | error | cancelled ...
  gpu?: number | string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  eta_s?: number | null;
  wall_s?: number | null;
  kind?: string;
  error?: string | null;
  file?: string | null;
};

export type GenView = {
  phase: "queued" | "running" | "done" | "failed";
  /** 排队第几（1 = 下一个就轮到），非排队为 0 */
  queuePos: number;
  /** 预计完成的时间点（毫秒时间戳）；算不出为 null */
  etaAt: number | null;
  /** 距离预计完成还有多少秒（≥0）；算不出为 null */
  remainS: number | null;
  /** “估计”= 没有 job.eta_s，用的是历史中位数 / 兜底 */
  estimated: boolean;
  error: string | null;
};

export const DEFAULT_GEN_S = 120;
const FAIL = new Set(["failed", "error", "cancelled", "canceled"]);

export const jobId = (j: JobLite) => String(j.job_id ?? j.id ?? "");
const ts = (s?: string | null) => (s ? Date.parse(s.length <= 19 ? s : s) : NaN);

export function median(xs: number[]): number | null {
  const a = xs.filter((x) => Number.isFinite(x) && x > 0).sort((p, q) => p - q);
  if (!a.length) return null;
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

/** 同类（kind）已完成任务的耗时中位数（秒）：优先 wall_s，没有就用 finished-started */
export function historyMedian(all: JobLite[], kind?: string): number | null {
  const ds = all
    .filter((j) => j.state === "done" && (!kind || j.kind === kind))
    .map((j) => (j.wall_s != null ? Number(j.wall_s) : (ts(j.finished_at) - ts(j.started_at)) / 1000))
    .slice(0, 10);
  return median(ds);
}

export function genView(job: JobLite | undefined, all: JobLite[], now: number): GenView | null {
  if (!job) return null;
  const st = String(job.state ?? "");
  if (st === "done") return { phase: "done", queuePos: 0, etaAt: null, remainS: 0, estimated: false, error: null };
  if (FAIL.has(st)) return { phase: "failed", queuePos: 0, etaAt: null, remainS: null, estimated: false, error: job.error ?? (st === "cancelled" ? "已取消" : "没出成") };
  const running = st === "running";
  const me = jobId(job);
  const ahead = running
    ? 0
    : all.filter((j) => jobId(j) !== me && String(j.gpu) === String(job.gpu) && ["queued", "running"].includes(String(j.state)) && (j.state === "running" || ts(j.created_at) <= ts(job.created_at))).length;
  // 排队第 N = 同一条道上还没开始、比我早入队的任务数 + 1（正在跑的不算：它跑完下一个就是我 = 第 1）
  const queuedAhead = running
    ? 0
    : all.filter((j) => jobId(j) !== me && String(j.gpu) === String(job.gpu) && j.state === "queued" && ts(j.created_at) <= ts(job.created_at)).length;
  const queuePos = running ? 0 : queuedAhead + 1;
  const hist = historyMedian(all, job.kind);
  const estimated = job.eta_s == null;
  const per = job.eta_s != null ? Number(job.eta_s) : (hist ?? DEFAULT_GEN_S) * (ahead + 1);
  const base = running ? ts(job.started_at) : ts(job.created_at);
  const etaAt = Number.isFinite(base) ? base + per * 1000 : now + per * 1000;
  return { phase: running ? "running" : "queued", queuePos, etaAt, remainS: Math.max(0, Math.round((etaAt - now) / 1000)), estimated, error: null };
}

/** 8 秒 → “约 10 秒”；90 → “约 2 分钟”；超过预计 → “快好了”。estimated = 没有后端估时，只是历史中位数 / 兜底 */
export function fmtRemain(s: number | null, estimated = false): string {
  if (s == null) return "时间还不确定";
  if (s <= 5) return "快好了";
  const t = s < 60 ? `${Math.round(s / 5) * 5} 秒` : `${Math.round(s / 60)} 分钟`;
  return `${estimated ? "估计" : "约"} ${t}`;
}

/** 钟点 HH:MM（本地时区） */
export function fmtClock(ms: number | null): string {
  if (ms == null) return "";
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 叠层 / 小条上的一行状态文字 */
export function statusText(v: GenView): string {
  if (v.phase === "queued") return `排队第 ${v.queuePos}`;
  if (v.phase === "running") return "生成中";
  if (v.phase === "done") return "好了";
  return `没出成：${v.error ?? ""}`;
}
