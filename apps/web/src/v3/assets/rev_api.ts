// UX5：资产二次修改（B_revision.md §5 P0）的前端客户端。全部是只读接口：
//   GET  /api/revisions/keys?type=     GET /api/revisions/{key}
//   POST /api/revisions/impact          （只读预览，不写任何东西）
//   GET  /api/shots/{id}/deps
// :8800 没重启前这些接口是 404 → 抛 RevNotReady，界面降级为“后台还没有这项功能”，其余照常。
// 重出排队复用已有的整集出片接口 POST /api/episodes/{n}/produce（mode=review，不自动定稿），这里只包一层。

export class RevError extends Error {
  status: number;
  notReady: boolean;
  constructor(msg: string, status: number, notReady: boolean) {
    super(msg);
    this.status = status;
    this.notReady = notReady;
  }
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    throw new RevError(`连不上画布 API（:8800）：${String((e as Error)?.message ?? e)}`, 0, false);
  }
  if (!r.ok) {
    let detail: unknown = null;
    try {
      detail = (await r.json())?.detail;
    } catch {
      /* 非 JSON */
    }
    const msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `${r.status} ${r.statusText}`;
    const notReady = r.status === 405 || (r.status === 404 && (detail === "没有这个接口" || detail === "Not Found" || detail == null));
    throw new RevError(notReady ? `后台还没有这项功能（${url.split("?")[0]} 未上线，等 API 重启）` : msg, r.status, notReady);
  }
  return r.json() as Promise<T>;
}

export type RevType = "identity" | "loraslot" | "preset" | "vbase" | "vlora" | "voice";
export interface RevKeyRow {
  key: string;
  type: RevType | string;
  label: string;
  current: { rev: string; seq: number | null; at?: string | null; by?: string | null };
  versions_count: number;
  used_by_count: number;
  used_by_current: number;
  unregistered_change: boolean;
}
export interface RevVersion {
  rev: string;
  seq?: number | null;
  label?: string;
  at?: string;
  by?: string;
  owner_quote?: string;
  state: "current" | "superseded" | string;
  used_by: number;
  snapshot?: string;
  /** UX6（P1）：这一版留了内容快照 → 才能“回到这版” */
  has_snapshot?: boolean;
  rollback?: boolean;
}
export interface RevDetail {
  key: string;
  label: string;
  current: { rev: string | null; seq: number | null };
  versions: RevVersion[];
  used_by: Record<string, number>;
  unregistered: boolean;
  /** UX6：回滚是否属于项目方闸门（定妆 / 身份 LoRA / 音色）→ 必须带原话 */
  gated?: boolean;
  gate_label?: string | null;
  /** UX6：内容在 config/ 里 → 回滚只写提议，不直接改 */
  config_backed?: boolean;
}
export type Stage = "image" | "last" | "video";
export interface ImpactCell {
  shot_id: string;
  episode: number | null;
  stage: Stage;
  take_n: number;
  key: string;
  from_rev: string | null;
  from_v: number | null;
  active: boolean;
  locked: boolean;
  owner_locked: boolean;
  estimated: boolean;
  chain: string[];
  default_selected: boolean;
}
export interface Impact {
  changes: { key: string; label: string; current: { rev: string | null; seq: number | null }; to: { rev: string; seq: number | null } | null }[];
  cells: ImpactCell[];
  counts: { cells: number; shots: number; locked: number; owner_locked: number; unlocked: number; estimated: number };
  by_episode: Record<string, Record<Stage, number>>;
  by_stage: Record<Stage, number>;
  gpu_estimate_s: {
    per_job: { frame: number; video: number };
    lanes: number;
    all: { jobs: number; serial: number; parallel: number };
    default_selected: { jobs: number; serial: number; parallel: number };
  };
  requires_owner: boolean;
  owner_reasons: string[];
  note?: string;
}
export interface ShotDeps {
  shot_id: string;
  stages: Partial<
    Record<
      Stage,
      {
        n: number;
        active: boolean;
        locked: boolean;
        stamped: boolean;
        deps: { key: string; label: string; rev: string; v: number | null; current: string | null; current_v: number | null; fresh: boolean }[];
        stale_deps: StaleDep[];
      }[]
    >
  >;
}

export interface StaleDep {
  key: string;
  label: string;
  from: string | null;
  to: string | null;
  from_v: string;
  to_v: string;
  text: string;
  /** UX6：项目方“保留旧版”豁免（只对豁免时那一个 rev 生效） */
  waived?: { by: string; owner_quote: string; at: string } | null;
}

// ---------------------------------------------------------------- UX6：P1 写路径 + 资产中心 B6–B10
export interface Proposal {
  proposal_id: string;
  kind: string;
  status: string;
  created_at: string;
  file: string;
  key?: string;
  character?: string;
  from?: unknown;
  to?: unknown;
  by?: string;
  owner_quote?: string | null;
  requires_owner?: boolean;
  changes?: Record<string, unknown>;
}
export interface SetCurrentResult {
  key: string;
  rev: string;
  applied: boolean;
  changed: boolean;
  restored?: string[];
  proposal: Proposal | null;
  current_after?: string | null;
  message: string;
}
export interface CutDeps {
  episode: number;
  cut: { name: string; url: string; mtime: string; tags: string[] } | null;
  stale: boolean;
  behind: number;
  changed: { shot_id: string; used: string; current: string; current_locked: boolean }[];
  voices_changed: { key: string; label: string; at: string; to_v: number | null }[];
  note?: string;
}
export interface LoraVersion {
  lora_id: string;
  file: string;
  kind: string;
  character?: string | null;
  step?: number | null;
  sha256?: string | null;
  from_identity_rev?: string | null;
  dataset_manifest?: string | null;
  status: string;
  by?: string;
  at?: string;
  identity_outdated?: boolean;
}
export interface LoraRow {
  file: string;
  kind: "image" | "video";
  stage: string;
  owner: string | null;
  owner_type: "character" | "prop" | "style" | null;
  status: string | null;
  sha256: string | null;
  sha_missing: boolean;
  triggers: string[];
  sources: string[];
  strength: number | number[] | null;
  versions: LoraVersion[];
  license: string | null;
  location: string | null;
  notes: string[];
  slot?: string;
  items?: { id: string; name: string; character: string | null }[];
}
export interface LoraTable {
  loras: LoraRow[];
  datasets: { dir: string; manifest: string; trigger?: string; count: number; dataset_sha: string | null; master_shas: string[]; identity_outdated: Record<string, boolean> }[];
  video_identity_enabled: boolean;
  note?: string;
}
export interface ChainVersion {
  version: number | null;
  file: string;
  url: string | null;
  label?: string | null;
  at?: string | null;
  variant?: string;
  source?: string;
  current: boolean;
  kind: "in_place" | "original" | "image";
}
export interface AssetChain {
  asset_id: string;
  kind: "look" | "item";
  name: string;
  current_file: string | null;
  versions: ChainVersion[];
  copies: { asset_id: string; version: number | null; file: string | null; url: string | null; at: string | null; label: string | null; exists: boolean; mapped: string }[];
  note?: string;
}
export interface PropRow {
  id: string;
  name: string;
  kind: string;
  owner?: string | null;
  lora_file?: string | null;
  trigger?: string | null;
  thumb?: string | null;
  note?: string | null;
  source: "wardrobe" | "props";
  editable: boolean;
}
export interface VoiceRow {
  cid: string;
  name: string;
  gender?: string;
  sid: number;
  voice: string;
  speed: number;
  f0_hz?: number;
  note?: string;
  key: string;
  rev: string | null;
  seq: number | null;
  pending: Proposal[];
}
export interface PromptTemplate {
  id: string;
  name: string;
  kind: string;
  kind_label: string;
  created_at: string;
  current_v: number | null;
  current: { v: number; text: string; by: string; at: string; note?: string | null } | null;
  versions: { v: number; text: string; by: string; at: string; note?: string | null }[];
}

const e = encodeURIComponent;
const post = (body: unknown, method = "POST"): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const p1Api = {
  /** 移当前指针（含回滚）。闸门类（定妆 / 身份 LoRA / 音色）必须 by=owner + owner_quote，否则后端 403 */
  setCurrent: (key: string, rev: string, by: string, owner_quote?: string, note?: string) =>
    call<SetCurrentResult>(`/api/revisions/${e(key)}/set-current`, post({ rev, by, owner_quote, note })),
  keep: (shot: string, b: { stage: Stage; key: string; n?: number; by: "owner"; owner_quote: string }) => call<unknown>(`/api/shots/${e(shot)}/deps/keep`, post(b)),
  cutDeps: (ep: number) => call<CutDeps>(`/api/episodes/${ep}/cut/deps`),
  loras: () => call<LoraTable>(`/api/loras`),
  proposals: (kind?: string) => call<{ proposals: Proposal[] }>(`/api/asset-proposals${kind ? `?kind=${e(kind)}` : ""}`),
  chain: (asset: string) => call<AssetChain>(`/api/assets/${e(asset)}/chain`),
  chainSetCurrent: (asset: string, file: string) => call<{ changed: boolean; affected_shots?: string[] }>(`/api/assets/${e(asset)}/chain/set-current`, post({ file, by: "canvas" })),
  props: () => call<{ props: PropRow[] }>(`/api/props`),
  createProp: (b: { name: string; kind?: string; lora_file?: string; trigger?: string; note?: string }) => call<PropRow>(`/api/props`, post({ ...b, by: "canvas" })),
  updateProp: (id: string, b: { name: string; kind?: string; lora_file?: string; trigger?: string; note?: string }) => call<PropRow>(`/api/props/${e(id)}`, post({ ...b, by: "canvas" }, "PUT")),
  voices: () => call<{ tts_model: string | null; characters: VoiceRow[]; proposals: Proposal[]; note?: string }>(`/api/voices`),
  voiceProposal: (cid: string, changes: Record<string, unknown>, by: string, owner_quote?: string, note?: string) =>
    call<Proposal>(`/api/voices/${e(cid)}/proposals`, post({ changes, by, owner_quote, note })),
  templates: () => call<{ templates: PromptTemplate[]; kinds: Record<string, string>; note?: string }>(`/api/prompt-templates`),
  createTemplate: (b: { name: string; kind: string; text: string; by: string; note?: string }) => call<PromptTemplate>(`/api/prompt-templates`, post(b)),
  updateTemplate: (id: string, b: { text: string; by: string; note?: string }) => call<PromptTemplate>(`/api/prompt-templates/${e(id)}`, post(b, "PUT")),
  templateUsage: (id: string) => call<{ refs: { template: string; v: number; target: string; by: string; at: string }[] }>(`/api/prompt-templates/${e(id)}/usage`),
};
export const revApi = {
  keys: (type?: string) => call<{ keys: RevKeyRow[]; types: string[] }>(`/api/revisions/keys${type ? `?type=${e(type)}` : ""}`),
  key: (key: string) => call<RevDetail>(`/api/revisions/${e(key)}`),
  /** 只读：不写任何东西、不提交任务 */
  impact: (keys: string[], episodes?: number[]) =>
    call<Impact>(`/api/revisions/impact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes: keys.map((key) => ({ key })), ...(episodes?.length ? { episodes } : {}) }),
    }),
  /** 只读：形象 / 单品 / 场景（还没进账本）——前端算出用到它的镜头，后端补每格定稿状态（UX5 新接口） */
  impactShots: (shots: string[], stages: Stage[], label: string) =>
    call<Impact>(`/api/revisions/impact-shots`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shots, stages, label }),
    }),
  shotDeps: (shot: string) => call<ShotDeps>(`/api/shots/${e(shot)}/deps`),
  /** 预估（已有接口，只算不排）：POST /api/episodes/{n}/produce/plan */
  plan: (ep: number, shots: string[], stages: Stage[]) =>
    call<unknown>(`/api/episodes/${ep}/produce/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shots, stages, mode: "review", force: true }),
    }),
  /** 排队重出（已有接口）：每集一个整集出片任务，只含勾选的镜头；mode=review = 出完等项目方定稿，旧定稿保留 */
  rerun: (ep: number, shots: string[], stages: Stage[], reason: string) =>
    call<unknown>(`/api/episodes/${ep}/produce`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shots, stages, mode: "review", force: true, by: `canvas:${reason}`.slice(0, 120) }),
    }),
};

export const STAGE_NAME: Record<Stage, string> = { image: "首帧", last: "尾帧", video: "视频" };
