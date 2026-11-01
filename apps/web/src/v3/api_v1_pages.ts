// fredw-92/W4c：v1 收尾页面（剧本创作 / 模型与 API / 资产）用的接口客户端，按 docs/api_v1_contract.md §A §B §E。
// 后端（W1 / W5）未上线的接口返回 404 / 405 → 抛 NotReadyError，页面显示“后端未就绪”。永不读写密钥明文（只写）。
import { detailText } from "../api";

export class ApiError extends Error {
  status: number;
  notReady: boolean;
  constructor(msg: string, status: number, notReady = false) {
    super(msg);
    this.status = status;
    this.notReady = notReady;
  }
}

/** 404 / 405 且是“接口不存在”（而不是“资源不存在”）时 notReady=true */
async function req<T>(url: string, init?: RequestInit, opts: { resource404?: boolean } = {}): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    throw new ApiError(`连不上画布 API（:8800）：${String((e as Error).message ?? e)}`, 0);
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    let detail: unknown = null;
    try {
      detail = (await r.json())?.detail;
      if (detail) msg = detailText(detail);
    } catch {
      /* 非 JSON */
    }
    const routeMissing = r.status === 405 || (r.status === 404 && (!opts.resource404 || detail === "没有这个接口" || detail === "Not Found"));
    throw new ApiError(routeMissing ? `后端未就绪（${url.split("?")[0]} 还没上线）` : msg, r.status, routeMissing);
  }
  return r.json() as Promise<T>;
}

const body = (method: string, b: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
const e = encodeURIComponent;

export const isNotReady = (x: unknown) => x instanceof ApiError && x.notReady;
// UX4（审查 R8）：网络层失败（后台没起 / 断开）写成人话，原文放括号里给技术排查
export const errText = (x: unknown) => {
  const m = String((x as Error)?.message ?? x);
  return /Failed to fetch|NetworkError|连不上画布 API/i.test(m) ? "这一块读不到：后台服务没响应，恢复后点刷新（Failed to fetch）" : m;
};

// ---------------------------------------------------------------- A. 模型与 API 配置

export interface LlmParams {
  temperature?: number | null;
  max_tokens?: number | null;
  reasoning?: boolean | null;
}
export interface Provider {
  id: string;
  name: string;
  base_url: string;
  models: string[];
  default_model: string;
  has_key: boolean;
  timeout_s: number;
  params: LlmParams;
  /** 预计费用（后端 estimate.tier：低 | 中 | 高 | 未知；label 是一句完整说明）。F2：原来读不存在的 cost_tier */
  estimate?: CostEstimate | null;
}
export interface CostEstimate {
  prompt_tokens?: number;
  max_tokens?: number;
  upper_usd?: number | null;
  tier: string;
  label?: string;
}
export type PurposeId = "script_write" | "script_repair" | "director_boost" | "lora_llm" | "prompt_rewrite";
export interface Purpose {
  id: PurposeId | string;
  label: string;
  provider: string;
  model: string;
}
export interface Providers {
  providers: Provider[];
  purposes: Purpose[];
}
/** 每处 ⚙ 覆盖：调用模型的接口都接受可选 llm */
export interface LlmChoice {
  provider: string;
  model: string;
  params?: LlmParams;
}
export interface ProviderPatch {
  name?: string;
  base_url?: string;
  models?: string[];
  default_model?: string;
  timeout_s?: number;
  params?: LlmParams;
  api_key?: string;
}
export interface RenderEndpoint {
  id: "image" | "video" | string;
  url: string;
  gpu: string | number | null;
  reachable: boolean;
  detail: string;
}

export const PURPOSE_LABEL: Record<string, string> = {
  script_write: "剧本写作",
  script_repair: "格式返修",
  director_boost: "导演加强",
  lora_llm: "LoRA 训练（打标 / 规划）",
  prompt_rewrite: "首帧提示词改写",
};

export const llmApi = {
  providers: () => req<Providers>("/api/llm/providers"),
  putProvider: (id: string, patch: ProviderPatch) => req<Provider>(`/api/llm/providers/${e(id)}`, body("PUT", patch), { resource404: true }),
  putPurpose: (purpose: string, v: { provider: string; model: string }) => req<Purpose>(`/api/llm/purposes/${e(purpose)}`, body("PUT", v), { resource404: true }),
  test: (id: string) => req<{ ok: boolean; latency_ms: number | null; detail: string }>(`/api/llm/providers/${e(id)}/test`, { method: "POST" }, { resource404: true }),
  endpoints: () => req<RenderEndpoint[]>("/api/render/endpoints"),
  putEndpoint: (id: string, url: string) => req<RenderEndpoint>(`/api/render/endpoints/${e(id)}`, body("PUT", { url }), { resource404: true }),
};

// ---------------------------------------------------------------- B. 剧本创作

export interface ScriptSessionInit {
  title?: string;
  outline?: string;
  episodes?: [number, number];
  shots_per_ep?: number;
  seconds_per_shot?: number;
  rules?: string;
  llm?: LlmChoice | null;
}

export const scriptApi = {
  /** 预计费用（不发写作请求、不花钱） */
  estimate: (b: { sid?: string; content?: string; outline?: string; episodes?: number[]; shots_per_ep?: number; seconds_per_shot?: number; rules?: string; llm?: LlmChoice }) =>
    req<CostEstimate & { provider: string; model: string }>("/api/script-chat/estimate", body("POST", b)),
  create: (b: ScriptSessionInit) => req<{ id: string; title: string }>("/api/script-chat/sessions", body("POST", b)),
  toInbox: (sid: string) => req<Record<string, unknown>>(`/api/script-chat/sessions/${e(sid)}/to-inbox`, { method: "POST" }, { resource404: true }),
  /** → {a, b, group}：两个会话 id（各带 pending 提纲请求，前端分别 /chat 启动） */
  ab: (b: { outline: string; episodes: [number, number]; llm_a: LlmChoice | null; llm_b: LlmChoice | null; shots_per_ep?: number; seconds_per_shot?: number; rules?: string }) =>
    req<{ a: string; b: string; group?: string }>("/api/script-chat/ab", body("POST", b)),
  rules: () => req<{ default: string | null; versions: { id: string; parts: string[] }[] }>("/api/script-chat/rules"),
};

/** /ab 的返回只约定“两个会话 id”：兼容 {a,b} / {session_a,session_b} / {sessions:[..]} / [..] */
export function abIds(r: unknown): [string | null, string | null] {
  const o = (r ?? {}) as Record<string, unknown>;
  const arr = Array.isArray(r) ? r : Array.isArray(o.sessions) ? o.sessions : Array.isArray(o.ids) ? o.ids : null;
  const id = (x: unknown) => (typeof x === "string" ? x : x && typeof x === "object" && typeof (x as { id?: unknown }).id === "string" ? (x as { id: string }).id : null);
  if (arr) return [id(arr[0]), id(arr[1])];
  return [id(o.a ?? o.session_a ?? o.sid_a), id(o.b ?? o.session_b ?? o.sid_b)];
}

// ---------------------------------------------------------------- E. 资产（角色卡）

export interface ShotChar {
  character: string;
  name: string;
  face_url: string | null;
  look_id: string | null;
  look_label: string;
  look_name: string;
  d_state?: string | null;
}
export interface LightShot {
  id: string;
  index: number;
  adult: boolean;
  first_frame: string | null;
  img_summary?: string;
  duration?: { seconds: number } | null;
  characters?: ShotChar[] | null;
}
export interface LightEpisode {
  number: number;
  title: string;
  shots: LightShot[];
}

export const assetsV1 = {
  /** 每集每镜的出场人物与造型（服务端缓存）：出现集数、按集排期、“用到的镜头”都从这里反查 */
  episodes: () => req<{ episodes: LightEpisode[] }>("/api/episodes/summary").then((x) => x.episodes),
};
