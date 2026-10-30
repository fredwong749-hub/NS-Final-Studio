// T42 项目 / 新建剧向导 / 编排 / 待办 / 看板 的接口与类型（services/api/ns_api/projects.py）

export interface ProjectSummary {
  slug: string;
  name: string;
  is_default: boolean;
  status: "legacy" | "draft" | "ready" | string;
  root: string;
  created_at: string | null;
  running: boolean;
  mode: "real" | "dry_run" | null;
  episodes: number;
}

export interface Check {
  key: string;
  label: string;
  ok: boolean;
}

export interface ProjectDetail extends ProjectSummary {
  settings?: {
    adult_content?: boolean;
    lora_plan?: Record<string, boolean>;
    script_files?: Record<string, string>;
    gates?: Record<string, { by: string; at: string }>;
  };
  readiness?: { checks: Check[]; ok: boolean };
  lora_kinds?: Record<string, string>;
}

export interface EpisodeReport {
  number: number;
  title: string;
  shots: number;
  adult: number;
  seconds: number;
  dialogue_lines: number;
  high_intensity: boolean;
  decor: string | null;
  issues: string[];
}

export interface ScriptReport {
  ok: boolean;
  fatal: string[];
  warnings: string[];
  files?: Record<string, string | null>;
  episodes?: number;
  shots?: number;
  adult_shots?: number;
  shots_rule?: [number, number];
  per_episode?: EpisodeReport[];
  durations?: { script: number; default: number; min: number; max: number };
  dialogue?: { lines: number; shots: number; unparsed: number };
  triggers?: { declared: string[]; used: Record<string, number>; unknown: string[]; without_file: string[] };
  decor?: { ranges: number; states: string[]; missing: number[] };
  character_locks?: { name: string; description: string }[];
  corrector?: { file: string; rule_count: number; rules: string[] } | null;
  image_suffix?: string;
}

export interface Rule {
  id: string;
  match: string[];
  term: string;
}

export interface StyleForm {
  lens: string;
  use_script_suffix: boolean;
  fallback_suffix: string;
  palette: string;
  style_negative: string;
  color_reference: string;
  color_match_strength: number;
  realism_texture_strength: number;
  materials: Rule[];
  shot_rules: Rule[];
  safe_term: string;
  safe_negative: string;
  soundscape_default: string;
  voice_rule: string;
  single_voice: boolean;
  bgm_style: string;
}

export interface Preview {
  shot: string;
  episode_title: string;
  parts: { label: string; text: string }[];
  prompt: string;
  negative: string;
}

export interface StyleState {
  form: StyleForm;
  defaults: StyleForm;
  confirmed: { by: string; at: string } | null;
  saved: boolean;
  toml: string | null;
  preview: Preview[];
}

export interface LookForm {
  label: string;
  name?: string;
  outfit?: string;
  shoes?: string;
  makeup?: string;
  hair?: string;
  nails?: string;
  accessory?: string;
}

export interface Character {
  id: string;
  name: string;
  description: string;
  references: string[];
  realism: "low" | "mid" | "high";
  makeup?: string;
  nails?: string;
  hair?: string;
  shoes?: string;
  wardrobe?: string;
  looks: LookForm[];
  schedule: { look: string; episodes: string }[];
  confirmed: boolean;
  approved_by?: string | null;
  approved_at?: string | null;
  master?: string;
}

export type LightStatus = "done" | "running" | "waiting" | "pending" | "failed" | "blocked" | "gate" | string;

export interface Light {
  status: LightStatus;
  done?: number | null;
  total?: number | null;
  detail?: string | null;
}

export interface BoardRow {
  number: number;
  title: string;
  shots: number;
  adult_shots: number;
  lights: Record<string, Light>;
  current: string | null;
  eta_s: number;
  accept: string | null;
}

export interface ExceptionItem {
  episode: number | null;
  step: string;
  label: string;
  status: string;
  attempts: number | null;
  error: string | null;
  source: "laptop" | "gpu3";
  retryable: boolean;
}

export interface Card {
  id: string;
  project: string;
  project_name: string;
  gate: string;
  title: string;
  opened_at: string | null;
  detail: Record<string, unknown>;
  last_rejected?: { decided_by: string; decided_at: string; note: string } | null;
  actions: { key: string; label: string; primary: boolean }[];
}

export interface Board {
  project: {
    slug: string;
    name: string;
    is_default: boolean;
    status: string;
    running: boolean;
    mode: string | null;
    started_at: string | null;
    updated_at: string | null;
    can_start: boolean;
  };
  gates: { id: string; title: string; status: string; decided_by?: string; decided_at?: string }[];
  episodes: BoardRow[];
  exceptions: ExceptionItem[];
  cards: Card[];
  eta: { laptop_s: number; gpu3_s: number; total_s: number; note: string };
  log: { at: string; msg: string }[];
}

export interface GpuInfo {
  laptop: { url: string; reachable: boolean; running?: number; pending?: number; gpu?: string; vram_total_mb?: number; vram_used_mb?: number; error?: string };
  gpu3: {
    reachable: boolean;
    simulated?: boolean;
    error?: string;
    gpus: { id: number; name?: string; faulty?: boolean; busy_by?: string | null; task?: string | null; vram_used_mb?: number; vram_total_mb?: number; util?: number }[];
  };
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* 非 JSON */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const enc = encodeURIComponent;
const upload = (file: File): RequestInit => {
  const fd = new FormData();
  fd.append("file", file);
  return { method: "POST", body: fd };
};
const P = (slug: string) => `/api/projects/${enc(slug)}`;

export const papi = {
  list: () => req<ProjectSummary[]>("/api/projects"),
  create: (name: string, slug?: string) => req<ProjectSummary>("/api/projects", json("POST", { name, slug: slug || null })),
  get: (slug: string) => req<ProjectDetail>(P(slug)),
  uploadScript: (slug: string, kind: string, file: File) =>
    req<ScriptReport>(`${P(slug)}/script?kind=${enc(kind)}`, upload(file)),
  report: (slug: string) => req<ScriptReport>(`${P(slug)}/script/report`),
  style: (slug: string) => req<StyleState>(`${P(slug)}/style`),
  saveStyle: (slug: string, form: StyleForm) => req<{ toml: string; preview: Preview[] }>(`${P(slug)}/style`, json("PUT", form)),
  uploadColorRef: (slug: string, file: File) =>
    req<{ color_reference: string; toml: string; preview: Preview[] }>(`${P(slug)}/style/color-reference`, upload(file)),
  confirmStyle: (slug: string, by: string) => req<{ by: string; at: string }>(`${P(slug)}/style/confirm`, json("POST", { by })),
  characters: (slug: string) => req<{ characters: Character[]; realism_levels: Record<string, number> }>(`${P(slug)}/characters`),
  saveCharacter: (slug: string, cid: string, body: Partial<Character>) =>
    req<Character>(`${P(slug)}/characters/${enc(cid)}`, json("PUT", body)),
  addReference: (slug: string, cid: string, file: File) => req<Character>(`${P(slug)}/characters/${enc(cid)}/references`, upload(file)),
  removeReference: (slug: string, cid: string, path: string) =>
    req<Character>(`${P(slug)}/characters/${enc(cid)}/references?path=${enc(path)}`, { method: "DELETE" }),
  confirmCharacter: (slug: string, cid: string, confirmed: boolean, by: string) =>
    req<Character>(`${P(slug)}/characters/${enc(cid)}/confirm`, json("POST", { confirmed, by })),
  saveSettings: (slug: string, body: { lora_plan?: Record<string, boolean>; adult_content?: boolean }) =>
    req<unknown>(`${P(slug)}/settings`, json("PUT", body)),
  finalize: (slug: string) => req<ProjectDetail>(`${P(slug)}/create`, { method: "POST" }),
  file: (slug: string, rel: string) => `${P(slug)}/file/${rel.split("/").map(enc).join("/")}`,

  board: (slug: string) => req<Board>(`${P(slug)}/production`),
  start: (slug: string, mode: "real" | "dry_run", by = "项目方") => req<Board>(`${P(slug)}/production/start`, json("POST", { mode, by })),
  pause: (slug: string, by = "项目方") => req<Board>(`${P(slug)}/production/pause`, json("POST", { by })),
  tick: (slug: string) => req<Board>(`${P(slug)}/production/tick`, { method: "POST" }),
  retry: (slug: string, episode: number | null, step: string) =>
    req<Board>(`${P(slug)}/production/retry`, json("POST", { episode, step })),
  decide: (slug: string, cardId: string, decision: string, payload: Record<string, unknown> = {}, by = "项目方") =>
    req<Board>(`${P(slug)}/cards/${enc(cardId)}`, json("POST", { decision, payload, by })),
  inbox: () => req<Card[]>("/api/inbox"),
  gpus: (project?: string) => req<GpuInfo>(`/api/gpus${project ? `?project=${enc(project)}` : ""}`),
};

export function fmtDur(s: number): string {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)} 天 ${h % 24} 小时`;
  return h ? `${h} 小时 ${m} 分` : `${m} 分钟`;
}

export function go(hash: string) {
  window.location.hash = hash;
}
