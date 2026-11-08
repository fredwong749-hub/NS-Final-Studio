// P5 M2（PLAN §2.4）：新 ns2 唯一总览 /api/overview 的前端适配层。
// 浏览器同源走旧 :8800 的 /ns2/… 桥（services/api/ns_api/ns2_bridge.py → 隧道 18900 → gpu33:8900）。
// 各页原来的数据形状不变，只换数据源：口径以 ns2/overview.py 为准（final = 有片且你点了“用这版”；尽力版单独计；分母 = 剧本镜数）。
// 回滚 = revert 本次前端 commit（各调用点改回旧接口）。

export const NS2 = "/ns2";
export const NS2_OVERVIEW = `${NS2}/api/overview`;

type Cell = { state: string; url: string | null; n?: number | null; error?: string | null; fallback?: { mode: string } };
type VCell = { state: string; url: string | null; n: number | null; tries?: number | null; error?: string | null; queue_pos?: number; eta_s?: number };
export type OvShot = { id: string; index: number; first: Cell; last: Cell; video: VCell; review: string | null; missing: string[]; candidates: number; owner_trigger: boolean };
export type OvFilm = { name: string; version: number | null; url: string | null; kind: string; dur_s: number | null; script_s: number | null; missing_n: number; missing: string[]; best_effort: string[] };
export type OvEp = {
  ep: number; title: string; total: number; phase: string; start: string | null; last_at: string | null;
  first_done: number; last_done: number; fallback_n: number; video_done: number; assembled: boolean; film: OvFilm | null; shots: OvShot[];
};
export type Ov = {
  run: string; at: string;
  totals: Record<"first" | "last" | "video" | "cut", [number, number]>;
  videos: { total: number; final: number; rendering: number; queued: number; pending_review: number; best_effort: number; need_frames: number; todo: number; failed: number; blocked: number; median_s: number; eta_all_s: number };
  episodes: OvEp[];
};

/** 新 API 的文件路径（/files/<host>/…）加桥前缀 */
export const ns2Url = (u: string | null | undefined) => (u ? `${NS2}${u}` : null);
const isoIn = (s: number | null | undefined) => (s && s > 0 ? new Date(Date.now() + s * 1000).toISOString() : null);

export async function fetchOverview(): Promise<Ov> {
  const r = await fetch(NS2_OVERVIEW);
  if (!r.ok) throw new Error(r.status === 502 ? "新系统接口不通（隧道 18900 → gpu33:8900）" : `HTTP ${r.status}`);
  return (await r.json()) as Ov;
}

/** 顶栏 / 视频页摘要（旧 /api/videos/overview .summary 形状）。阻断计进 failed（都要人看） */
export const toSummary = (o: Ov) => ({
  total: o.videos.total, final: o.videos.final, rendering: o.videos.rendering, queued: o.videos.queued,
  pending_review: o.videos.pending_review, best_effort: o.videos.best_effort, need_frames: o.videos.need_frames,
  todo: o.videos.todo, failed: o.videos.failed + o.videos.blocked, eta_all: isoIn(o.videos.eta_all_s), median_s: o.videos.median_s,
});

/** 视频页每镜一行（旧 Row 形状）：ns2 状态 → 旧状态词 */
export function videoState(s: OvShot): string {
  const v = s.video.state;
  if (v === "passed") return "final";
  if (v === "ready") return "pending_review";
  if (v === "best_effort") return "best_effort";
  if (v === "running") return "rendering";
  if (v === "failed" || v === "blocked") return "failed";
  if (s.video.queue_pos) return "queued";
  return s.missing.some((m) => m === "first" || m === "last") ? "need_frames" : "todo";
}
export const toVideoRows = (o: Ov, ep: string) =>
  o.episodes
    .filter((e) => !ep || ep === "all" || String(e.ep) === ep)
    .map((e) => ({
      ep: e.ep,
      shots: e.shots.map((s) => ({
        id: s.id, index: s.index, state: videoState(s), video_url: ns2Url(s.video.url), n: s.video.n, progress: null,
        queue_pos: s.video.queue_pos ?? null, eta: isoIn(s.video.eta_s), candidates: s.candidates,
        missing: s.missing.filter((m) => m !== "video"),
        fallback: s.last.state === "na" ? "i2va" : null,
        ledger: s.video.state === "blocked" ? { state: "blocked", word: "卡住了", why: s.video.error ?? null, note: null } : null,
      })),
    }));

/** 每集进度（旧 /api/episodes/kpi 形状）。用时 = 本集新系统首个开工 → 最近落定（迁移来的行不计时） */
const PHASE_WORD: Record<string, string> = { frames: "出首尾帧", videos: "出视频", assembly: "合成", done: "完成" };
const KPI_CELL = (c: { state: string }, last = false) =>
  c.state === "na" ? (last ? "fallback" : "na") : c.state === "blocked" ? "failed" : c.state;
export function toKpi(o: Ov, budget = 50) {
  return {
    run: o.run, at: o.at, budget_min: budget,
    source: { kpi: "ns2 /api/overview（jobs 表）", snapshot_age_s: 0, registry_age_s: null },
    episodes: o.episodes.map((e) => {
      const t0 = e.start ? Date.parse(e.start) : null;
      const t1 = e.assembled && e.last_at ? Date.parse(e.last_at) : Date.now();
      const el = t0 ? Math.max(0, (t1 - t0) / 60000) : null;
      return {
        ep: e.ep, title: e.title, total: e.total, phase: e.phase, phase_word: PHASE_WORD[e.phase] ?? e.phase,
        state: e.assembled && e.phase === "done" ? "assembled" : el == null ? "not_started" : el > budget ? "over_budget" : "in_budget",
        start: e.start, elapsed_min: el, eta_min: null, over_min: el != null && el > budget ? el - budget : null, clock_from: "dispatch",
        first_done: e.first_done, last_done: e.last_done, fallback_n: e.fallback_n, video_done: e.video_done, assembled: e.assembled,
        shots: e.shots.map((s) => ({
          id: s.id, index: s.index,
          first: { state: KPI_CELL(s.first), url: ns2Url(s.first.url) },
          last: { state: KPI_CELL(s.last, true), url: ns2Url(s.last.url), fallback: s.last.state === "na" ? { word: "不用尾帧（i2va）", why: "" } : null },
          video: { state: s.video.state === "blocked" ? "failed" : s.video.state, url: ns2Url(s.video.url) },
        })),
        film: e.film && e.film.url ? {
          name: e.film.name, version: e.film.version, url: ns2Url(e.film.url) as string, at: e.last_at ?? o.at, duration_s: e.film.dur_s,
          video_shots: e.total - e.film.missing_n, placeholder_shots: e.film.missing_n, kind: "preview", kind_word: "预览版",
          word: `v1 无配音 · ${e.film.dur_s ?? "?"} 秒 / 剧本 ${e.film.script_s ?? "?"} 秒${e.film.missing_n ? ` · 缺 ${e.film.missing_n} 镜用占位` : ""}${e.film.best_effort.length ? ` · 含尽力版 ${e.film.best_effort.length} 镜` : ""}`,
          missing_n: e.film.missing_n, missing: e.film.missing, post: false,
        } : null,
      };
    }),
  };
}

/** 全剧总览的五段进度（旧 /api/progress 形状） */
export const toProgress = (o: Ov) => ({
  order: ["script", "first", "last", "video", "cut"],
  labels: { script: "剧本", first: "首帧", last: "尾帧", video: "视频定稿", cut: "成片" } as Record<string, string>,
  episodes: o.episodes.map((e) => ({
    segs: {
      script: { done: 1, total: 1 }, first: { done: e.first_done, total: e.total }, last: { done: e.last_done, total: e.total },
      video: { done: e.video_done, total: e.total }, cut: { done: e.assembled ? 1 : 0, total: 1 },
    } as Record<string, { done: number; total: number }>,
  })),
});
