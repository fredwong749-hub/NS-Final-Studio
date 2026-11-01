// fredw-92/U3：资产页「场景」页签的数据，接 S-back 正式接口（docs/api_v1_contract.md 变更记录 fredw-92/S-back）：
// GET /api/assets/scenes、GET /api/assets/scenes/{id}、POST / DELETE /api/assets/scenes/{id}/plate。
// 接口未上线（路由 404 / 405）→ 页面显示“后端未就绪”，不再逐集读 SOP 兜底。
import type { AssetRef, AssetVersion } from "../api_v1";
import { cardName } from "../edit/lanes";

export interface ScenePlate {
  file?: string | null;
  url?: string | null;
  plate_status?: string | null;
  status_label?: string | null;
  locked?: boolean;
  locked_by?: string | null;
  locked_at?: string | null;
  version?: number | null;
  owner_confirmed_at?: string | null;
  s2_gate_ok?: boolean;
}
export interface SceneVariant {
  variant: string;
  plate_id?: string;
  file?: string | null;
  url?: string | null;
  locked?: boolean;
  locked_by?: string | null;
  version?: number | null;
}
export interface SceneView {
  scene_id: string;
  asset_id?: string;
  name?: string | null;
  description?: { source?: string; name?: string | null; space?: string | null; time_of_day?: string | null; times?: string[] | null } | null;
  plate?: ScenePlate | null;
  variants?: SceneVariant[];
  episodes?: number[];
  episode_count?: number;
  shot_count?: number;
}
/** 场景版本（asset_versions 记录；场景 = 底图版本链） */
export interface SceneVersion extends AssetVersion {
  version?: number;
  variant?: string;
  file?: string | null;
}
export interface SceneDetail extends SceneView {
  refs_list?: AssetRef[];
  version_list?: SceneVersion[];
  gens?: unknown[];
  usage?: { episodes?: number[]; shots?: { shot_id: string; episode?: number; index?: number }[] };
  assets?: { id: string; name?: string; url?: string | null; refs?: AssetRef[]; versions?: SceneVersion[]; gens?: unknown[] }[];
}

export class SceneApiError extends Error {
  status: number;
  constructor(msg: string, status: number) {
    super(msg);
    this.status = status;
  }
}
/** 路由还没上线（API 未重启）：405，或 404 且 detail 是框架默认的 “Not Found”；旧 API 会把 /api/assets/scenes 当成资产 id 回“没有这个资产：scenes”（“没有这个场景”是资源不存在，不算） */
export const sceneNotReady = (e: unknown) => {
  const s = (e as SceneApiError)?.status;
  return s === 405 || s === 501 || (s === 404 && /^(Not Found|404 |没有这个资产：scenes)/.test((e as Error).message));
};

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    throw new SceneApiError(`连不上画布 API（:8800）：${String((e as Error)?.message ?? e)}`, 0);
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const d = (await r.json())?.detail;
      if (d) msg = typeof d === "string" ? d : JSON.stringify(d);
    } catch {
      /* 非 JSON */
    }
    throw new SceneApiError(msg, r.status);
  }
  return r.json() as Promise<T>;
}
const sid = encodeURIComponent;

export const loadScenes = () => call<{ scenes?: SceneView[] }>("/api/assets/scenes").then((d) => d.scenes ?? []);
export const loadScene = (id: string) => call<SceneDetail>(`/api/assets/scenes/${sid(id)}`);
/** 定稿为底图（画布定稿 by=canvas；项目方确认走 SOP，不在这里） */
export const lockPlate = (id: string, version: number, variant?: string) =>
  call<{ plate_id?: string; url?: string; stale_shots?: string[] }>(`/api/assets/scenes/${sid(id)}/plate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version, ...(variant ? { variant } : {}), by: "canvas" }),
  });
export const unlockPlate = (id: string, variant = "main") =>
  call<unknown>(`/api/assets/scenes/${sid(id)}/plate?variant=${sid(variant)}`, { method: "DELETE" });

export const plateUrl = (s: SceneView) => s.plate?.url ?? s.variants?.find((v) => v.variant === "main")?.url ?? null;

const TIME: Record<string, string> = {
  dawn: "清晨", morning: "早晨", day: "白天", noon: "中午", afternoon: "下午", dusk: "黄昏",
  evening: "傍晚", night: "夜晚", late_night: "深夜", midnight: "午夜",
};
export const timeLabel = (t: string) => TIME[t] ?? t;
const VARIANT: Record<string, string> = { main: "主底图", low: "低机位", top: "俯拍", high: "高机位", wide: "全景", close: "近景", night: "夜" };
export const variantLabel = (v: string) => VARIANT[v] ?? v;
export const sceneName = (s: SceneView) => s.name || s.description?.name || s.scene_id.replace(/^sk_/, "").replace(/_/g, " ");

// ---------------------------------------------------------------- fredw-92/UXF3（UX 审查 #38）：上传底图 / 批量生成候选
// 全部用已有接口（不改 API 形状）：上传 = POST /api/assets/{id}/refs（暂存）→ POST /api/assets/{id}/versions {file, variant}
// → DELETE 暂存参考；批量 = 每个场景 POST /api/assets/{id}/gen-jobs，提示词 = 剧本场景表原文（不改写、不补全）。

/** 上传一张图，存为场景底图新版本（不定稿；定稿在抽屉“底图版本”里点） */
export async function uploadPlate(id: string, file: File, variant = "main"): Promise<SceneVersion> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("role", "space");
  fd.append("note", "上传底图（暂存，存成底图版本后去掉）");
  const ref = await call<{ ref_id: string; file: string }>(`/api/assets/${sid(id)}/refs`, { method: "POST", body: fd });
  const v = await call<SceneVersion>(`/api/assets/${sid(id)}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file: ref.file, variant, label: `上传 · ${file.name}` }),
  });
  await call<unknown>(`/api/assets/${sid(id)}/refs/${sid(ref.ref_id)}`, { method: "DELETE" }).catch(() => undefined);
  return v;
}

/** GET /api/render/lanes 的一道 */
export interface Lane {
  gpu: number | string;
  id: string;
  reachable?: boolean;
  ok?: boolean;
  activity?: "image" | "video" | "external" | "idle";
  queued?: number;
  load_s?: number;
  image_pref?: boolean;
}
export const loadLanes = () => call<{ lanes: Lane[] }>("/api/render/lanes").then((d) => d.lanes ?? []);
const ACT: Record<string, string> = { image: "正在出图", video: "出视频", external: "被其他任务占用", idle: "空闲" };
// fredw-92/UXF4（审查 N7）：卡名统一 lanes.cardName（以前 gpu33:0 和 gpu36:0 都写成“GPU0”）
export const laneText = (l: Lane) => `${cardName(l.gpu)} · ${l.ok === false ? "连不上" : ACT[l.activity ?? "idle"] ?? l.activity}${l.queued ? ` · 排队 ${l.queued}` : ""}`;

/** 出图默认预设（项目方选定的预览档）；读不到就不带预设（后端旧默认） */
export async function defaultImagePreset(): Promise<{ id: string; label: string } | null> {
  try {
    const d = await call<{ default_preset?: string; presets?: { id: string; label: string; tier?: string }[] }>("/api/render/image-presets?gpu=0");
    const p = d.presets?.find((x) => x.id === d.default_preset);
    return p && p.tier !== "final" ? { id: p.id, label: p.label } : null;
  } catch {
    return null;
  }
}

/** 剧本场景表原文（只有 source = script 才有；scenes.json 推断的不算原文）。字段原样拼，不改写 */
export function sceneTableText(s: SceneView): string | null {
  const d = s.description as (SceneView["description"] & { light?: unknown; fixtures?: string | null }) | null | undefined;
  if (!d || d.source !== "script") return null;
  const light = typeof d.light === "string" ? d.light : "";
  const lines = [
    d.name && `场景：${d.name}`,
    d.space && `空间：${d.space}`,
    d.time_of_day && `时段：${d.time_of_day}`,
    light && `光线：${light}`,
    d.fixtures && `陈设：${d.fixtures}`,
  ].filter(Boolean) as string[];
  // 只有名字、没有空间 / 光线 / 陈设的描述 = 没有可用的原文
  return d.space || light || d.fixtures ? lines.join("\n") : null;
}

/** 提交一个场景的底图候选生成（自动分道；结果进该场景的修改链，存版本 / 定稿由项目方在抽屉里点） */
export const submitSceneGen = (id: string, prompt: string, preset?: string) =>
  call<{ job_id: string }>(`/api/assets/${sid(id)}/gen-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, refs: [], strength: "medium", label: "候选·待复审 · 批量底图", ...(preset ? { preset } : {}) }),
  });
