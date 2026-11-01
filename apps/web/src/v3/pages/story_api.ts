// UIRSI：新建剧本（提纲 → 写作链 P0→P4）接口。后端 services/api/ns_api/story_runs.py。
export type StageStatus = "ok" | "reused" | "running" | "needs_writer" | "budget_stop" | "pending" | "unchecked" | "missing";
export type RunStatus = "queued" | "running" | "ok" | "needs_writer" | "budget_stop" | "bad_brief" | "error" | "interrupted" | "paused" | "cli" | string;
export type Issue = { rule: string; level: "block" | "warn" | string; field?: string; message: string };
export type Stage = {
  node: "P0" | "P1" | "P2" | "P3" | "P4";
  label: string;
  link: string | null;
  file: string;
  status: StageStatus;
  exists?: boolean;
  rounds?: number;
  rounds_done?: number;
  usd?: number;
  blocking?: number;
  warnings?: number;
  n_issues?: number;
  edited_by?: string | null;
  issues?: Issue[];
};
export type Run = {
  id: string;
  ui: boolean;
  episode: number | null;
  status: RunStatus;
  current: string | null;
  upto: string;
  created_at: string;
  updated_at?: string | null;
  title: string;
  outline_head: string;
  episodes?: { from: number; to: number } | null;
  error?: string | null;
  budget_usd?: number | null;
  spent_usd: number;
  sent_to_import?: { at: string; path: string } | null;
  stages: Stage[];
  brief?: Record<string, unknown>;
  model?: string | null;
  /** 整季运行（SERIES：data/pipeline/runs/series10_v1/ 这类，epNN/ 子目录）：按集看，只读 */
  series?: boolean;
  readonly?: boolean;
  series_eps?: { ep: number; stages: Record<string, StageStatus> }[];
};
export type Artifact = { node: string; file: string; text: string; json: unknown; kind: "json" | "markdown" };
export type BriefIn = {
  title: string;
  outline: string;
  episodes: { from: number; to: number };
  episode_lines: Record<string, string>;
  seconds_per_episode: [number, number];
  shots_per_ep: number | null;
  notes?: string;
};

export class StoryError extends Error {
  status: number;
  issues: Issue[];
  constructor(status: number, msg: string, issues: Issue[] = []) {
    super(msg);
    this.status = status;
    this.issues = issues;
  }
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw new StoryError(0, `后台服务没响应（${String((e as Error).message ?? e)}）`);
  }
  if (r.ok) return (await r.json()) as T;
  let detail: unknown = null;
  try {
    detail = (await r.json()).detail;
  } catch {
    /* 不是 JSON */
  }
  if (r.status === 404 && !detail) throw new StoryError(404, "后台还没有这项功能（等 API 重启后出现）");
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; issues?: Issue[] };
    throw new StoryError(r.status, d.message ?? JSON.stringify(detail), d.issues ?? []);
  }
  throw new StoryError(r.status, typeof detail === "string" ? detail : `HTTP ${r.status}`);
}

export const storyApi = {
  list: () => call<{ runs: Run[]; busy: string | null }>("GET", "/api/story-runs"),
  get: (id: string, ep?: number | null) => call<Run>("GET", `/api/story-runs/${encodeURIComponent(id)}${ep ? `?ep=${ep}` : ""}`),
  start: (b: { brief: BriefIn; episode: number; upto: string; budget_usd: number }) => call<Run>("POST", "/api/story-runs", b),
  artifact: (id: string, node: string, ep?: number | null) => call<Artifact>("GET", `/api/story-runs/${encodeURIComponent(id)}/artifact/${node}${ep ? `?ep=${ep}` : ""}`),
  save: (id: string, node: string, text: string) =>
    call<{ report: { ok: boolean; blocking: number; warnings: number; issues: Issue[] }; status: string; superseded: string[]; run: Run }>(
      "PUT",
      `/api/story-runs/${encodeURIComponent(id)}/artifact/${node}`,
      { text },
    ),
  retry: (id: string, link?: string) => call<Run>("POST", `/api/story-runs/${encodeURIComponent(id)}/retry`, { link: link ?? null }),
  resume: (id: string, upto?: string) => call<Run>("POST", `/api/story-runs/${encodeURIComponent(id)}/resume`, { upto: upto ?? null }),
  sendToImport: (id: string, ep?: number | null) =>
    call<{ draft: { path: string; name: string }; import_href: string; note: string }>("POST", `/api/story-runs/${encodeURIComponent(id)}/send-to-import${ep ? `?ep=${ep}` : ""}`),
};

export const NODE_SHORT: Record<string, string> = { P0: "提纲", P1: "故事线", P2: "单集大纲", P3: "剧本", P4: "分镜" };
export const RUN_LABEL: Record<string, [string, "neutral" | "accent" | "ok" | "warn" | "bad" | "busy" | "info" | "stale"]> = {
  queued: ["排队", "busy"],
  running: ["写作中", "busy"],
  ok: ["写完了", "ok"],
  needs_writer: ["需返修", "warn"],
  budget_stop: ["预算停", "warn"],
  bad_brief: ["提纲有误", "bad"],
  error: ["出错", "bad"],
  interrupted: ["中断", "neutral"],
  paused: ["已暂停", "neutral"],
  cli: ["命令行", "neutral"],
  reused: ["写完了", "ok"],
};
export const STAGE_LABEL: Record<string, [string, "neutral" | "accent" | "ok" | "warn" | "bad" | "busy" | "info" | "stale"]> = {
  ok: ["通过", "ok"],
  reused: ["通过", "ok"],
  running: ["写作中", "busy"],
  needs_writer: ["需返修", "warn"],
  budget_stop: ["预算停", "warn"],
  pending: ["等待", "neutral"],
  unchecked: ["未校验", "info"],
  missing: ["缺", "bad"],
};
