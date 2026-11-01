// v1 收尾接口（docs/api_v1_contract.md）。fredw-92/W4b 写 §C / §D / §E；其他段由各自 agent 追加，互不覆盖。
// 后端（W2 / W3 / W5）正在实现：未上线时接口返回 404 / 405 / 501，前端用 isNotReady() 判断并显示“后端未就绪”。
// 提示词、修改要求是项目方原话或写作方内容：原样发送，前端不改写、不补全、不做内容检测。

/** 带 HTTP 状态码的错误 */
export type ApiError = Error & { status?: number };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    throw Object.assign(new Error(`连不上后端：${(e as Error).message}`), { status: 0 });
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw Object.assign(new Error(msg), { status: r.status });
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const sid = encodeURIComponent;

/** 接口还没上线（路由不存在 / 未实现） */
export const isNotReady = (e: unknown) => {
  const s = (e as ApiError)?.status;
  return s === 404 || s === 405 || s === 501;
};
/** 错误 → 一句话；未上线的统一说“后端未就绪” */
// UIMASTER：调用方传进来的 what 常是开发用的接口代号（“W5 /assets/{id}/gen-jobs”），界面不得出现路径 / 开发细节——带斜杠或 Wn 编号的一律不显示
export const errText = (e: unknown, what = "") => {
  const label = what && !/\/|^W\d/.test(what) ? `（${what}）` : "";
  return isNotReady(e) ? `这个功能后台还没准备好${label}，稍后再试（后台重启后就能用）` : (e as Error)?.message ?? String(e);
};

// ---------------- §C 出图与精修循环（W2） ----------------

export type FrameSlot = "first" | "last";
export type Slot = FrameSlot | "video";
/** 现有 takes 里的 stage 名（首帧 = image） */
export type TakeStage = "image" | "last" | "video";
export const slotToStage = (s: Slot): TakeStage => (s === "first" ? "image" : s);
export const stageToSlot = (s: string): Slot => (s === "image" || s === "first" ? "first" : s === "last" ? "last" : "video");

export type EditMode = "regen" | "instruct" | "refs";
export type Strength = "small" | "medium" | "large";
export type RefRole = "identity" | "style" | "color" | "item";
export const ROLE_LABEL: Record<RefRole, string> = { identity: "人物", style: "风格", color: "色彩", item: "单件" };
export const STRENGTH_LABEL: Record<Strength, string> = { small: "小", medium: "中", large: "大" };
export const MODE_LABEL: Record<string, string> = {
  regen: "改提示词重出",
  instruct: "指令改图",
  refs: "换参考再改",
  inpaint: "局部重绘",
  video: "出视频",
};

export interface RefSpec {
  asset_id?: string;
  path?: string;
  role: RefRole;
  /** 前端显示用（后端忽略） */
  url?: string | null;
  label?: string;
}

export interface FrameJobBody {
  stage: FrameSlot;
  mode: EditMode;
  parent?: number;
  prompt?: string;
  instruction?: string;
  strength?: Strength;
  refs?: RefSpec[];
  seed?: number;
  /** 道：0 / 3 / "gpu36:1" / "auto"（后端 jobs.pick_lane 按任务类型挑空闲的卡） */
  gpu?: number | string;
  llm?: { provider: string; model: string; params?: Record<string, unknown> };
  /** fredw-92/Q1：preview | final（定稿档） */
  tier?: "preview" | "final";
  /** fredw-92/PX：出图参数预设 id；不给 = 后端 default_preset（项目方选定 C） */
  preset?: string;
  /** fredw-92/PX：覆盖（只写和预设不同的字段） */
  params?: Partial<ImageParams>;
}

// ---------------- 出图参数（fredw-92/PX，GET /api/render/image-presets） ----------------

export interface LoraRow {
  name: string;
  strength: number;
}
export interface ImageParams {
  unet: "turbo" | "base";
  steps: number;
  cfg: number;
  sampler: string;
  scheduler: string;
  shift: number | null;
  vae: "plain" | "texture_fix";
  /** null = 按剧本自动；"@identity" = 本镜身份 LoRA */
  loras: LoraRow[] | null;
  two_stage: { enabled: boolean; first_size: [number, number]; upscale_size: [number, number]; denoise: number; steps: number };
  width: number;
  height: number;
  seed: number | null;
  strength: number | null;
  grade: { enabled: boolean | null; strength: number };
  spec_words: boolean;
  /** threshold：PIL UnsharpMask 阈值（LCA；旧 API 没有 = 0） */
  sharpen: { enabled: boolean; radius: number; amount: number; threshold?: number };
  render_scale: number;
  detail_pass: { enabled: boolean; denoise: number; scale: number };
  /** LCA：风格后缀（项目方选定的写作模型原文，前加“，”原样接在提示词末尾；"" = 不加；旧 API 没有） */
  style_suffix?: string;
}
export interface ImagePreset {
  id: string;
  label: string;
  tier: "preview" | "final";
  params: Partial<ImageParams>;
  note?: string;
  src?: string;
  builtin: boolean;
}
export interface ImagePresetsResp {
  presets: ImagePreset[];
  defaults: ImageParams;
  default_preset: string;
  final_preset: string;
  /** fredw-92/UXF2：render_quality.json auto_final_on_lock（旧 API 没有这个字段） */
  auto_final_on_lock?: boolean;
  ranges: Record<string, number | [number, number]>;
  labels: Record<string, string>;
  unets: Record<string, string>;
  vaes: Record<string, string>;
  identity: string;
  identity_loras: string[];
  banned_loras: string[];
  notes: Record<string, string>;
  allowed: {
    loras: string[];
    samplers: string[];
    schedulers: string[];
    source: "live" | "cache" | "unavailable";
    age_s?: number;
    error?: string;
    gpu?: number;
    shift_node?: boolean | null;
  };
}
/** take.params 里出图部分（GET 时随 take 出来） */
export interface ImageTakeParams {
  preset?: string | null;
  overrides?: Partial<ImageParams> | null;
  effective?: (Partial<Omit<ImageParams, "loras" | "style_suffix">> & { loras?: LoraRow[]; unet_file?: string; vae_file?: string; sigmas?: string | null; tier?: string; denoise?: number; note?: string; rendered_size?: [number, number]; style_suffix?: string | null; style_suffix_applied?: boolean; render_scale_requested?: number; render_scale_note?: string }) | null;
  post?: { steps?: string[] } | null;
  /** LCA：送进 Image 2.1 的提示词（原文 + “，” + 风格后缀） */
  prompt_sent?: string | null;
  spec_removed?: string[] | null;
  tier?: string;
}

export type JobStateV1 = "queued" | "running" | "done" | "failed" | "cancelled";
export interface JobV1 {
  state: JobStateV1;
  take?: number | { n: number } | null;
  error?: string | null;
  gpu?: number | string | null;
  eta_s?: number | null;
  started_at?: string | null;
  progress?: number | null;
}

/** 列表里的任务（frame-jobs / video-takes.jobs） */
export interface ShotJobV1 extends JobV1 {
  id: string;
  job_id?: string;
  kind: "frame" | "video" | string;
  shot_id: string;
  params?: { stage?: FrameSlot; mode?: string } | null;
}

/** take 上 v1 新增字段（GET /api/shots/{id} 的 takes 里出现） */
export interface TakeV1Fields {
  parent?: number | null;
  mode?: string | null;
  instruction?: string | null;
  strength?: Strength | null;
  refs?: RefSpec[] | null;
  locked?: boolean | null;
  /** §D 视频 take 的参数；首帧 / 尾帧 take 是出图参数（fredw-92/PX） */
  params?: (VideoJobBody & ImageTakeParams) | null;
}

// ---------------- §D 视频（W3） ----------------

export interface VideoJobBody {
  parent?: number;
  prompt_override?: string;
  seed?: number;
  steps?: number;
  seconds?: number;
  lora_strength?: number;
  /** 道：3 / "gpu36:1" / "auto" */
  gpu?: number | string;
  /** fredw-92/VB：附加 H3 LoRA（串在 Turbo 之后），强度 0–1.5 */
  loras?: { name: string; strength: number }[];
  /** fredw-92/PF：视频基底 official_turbo（默认）| pika_flex；take.params.base 记这一版用的 */
  base?: string;
  /** fredw-92/QCV：use（默认，首尾帧都给）| none（只给首帧）| auto（首尾帧几乎一样时只给首帧） */
  last_frame_mode?: "use" | "none" | "auto";
}

/** GET /api/video-bases：config/render_quality.json video_bases（fredw-92/PF） */
export interface VideoBaseInfo {
  id: string;
  label?: string;
  short?: string;
  steps?: number;
  steps_adjustable?: boolean;
  experimental?: boolean;
  hint?: string;
  license?: string;
  source_url?: string;
}

/** GET /api/video-loras：config/render_quality.json 的可选视频 LoRA（fredw-92/VB） */
export interface OptionalVideoLora {
  id: string;
  name: string;
  label?: string;
  license?: string;
  usage?: string;
  tag?: string;
  recommended_strength?: number;
  strength_range?: [number, number];
}

// ---------------- §E 参考切换与资产（W5） ----------------

export type PartKey = "outfit" | "shoes" | "makeup" | "nails" | "hair" | "accessory";
export const PART_LABEL: Record<PartKey, string> = {
  outfit: "服装",
  shoes: "鞋",
  makeup: "妆容",
  nails: "美甲",
  hair: "发型",
  accessory: "饰品",
};
export const PART_KEYS = Object.keys(PART_LABEL) as PartKey[];

/** 选项里的一项（形象 / 部件 / 场景底图）；字段按 W5 实际返回宽松读取 */
export interface RefOption {
  id: string;
  name?: string;
  label?: string;
  letter?: string;
  url?: string | null;
  thumb_url?: string | null;
  preview_url?: string | null;
  is_default?: boolean;
  /** W5 实际字段：集默认 / 当前生效 */
  episode_default?: boolean;
  current?: boolean;
  /** 场景底图选项用 plate_id */
  plate_id?: string;
}
export type RefOptionLike = RefOption | string;

export interface CharRefState {
  id: string;
  name: string;
  effective: { look?: string | null; look_name?: string; label?: string; parts?: Partial<Record<PartKey, string>>; images?: (string | { url?: string | null; label?: string })[] };
  source: "episode" | "scene" | "shot";
  options: { looks?: RefOptionLike[]; parts?: Partial<Record<PartKey, RefOptionLike[]>> };
}
export interface ShotRefsV1 {
  characters: CharRefState[];
  scene?: {
    effective?: { plate?: string | null; plate_id?: string | null; id?: string | null; url?: string | null; name?: string } | string | null;
    source?: "episode" | "scene" | "shot";
    options?: RefOptionLike[];
  } | null;
}

export interface RefChange {
  characters?: Record<string, { look?: string | null; parts?: Partial<Record<PartKey, string | null>> }>;
  scene?: string | null;
  /** 借用另一镜的整套参考 */
  copy_from?: string;
  /** 恢复集默认 */
  reset?: boolean;
}
export type RefScope = "shot" | "scene" | "episode";
export interface RefPreview {
  affected: string[];
  stale: string[];
  /** 后端字段是 {shot_id, message}（F2 修） */
  continuity_warnings: (string | { shot_id?: string; message?: string })[];
}
/** /refs/apply 的“应用并重出首帧”：每镜一个首帧任务 */
export interface RefApplyResult extends RefPreview {
  rerender?: { shot_id: string; ok: boolean; job_id?: string; error?: string }[];
}

export interface AssetRef {
  ref_id: string;
  url?: string | null;
  role?: RefRole;
  label?: string;
  source?: string;
  /** fredw-92/CHR：作废候选（文件保留，不能再用作生成参考） */
  void?: { by: string; owner_quote?: string; reason?: string; at?: string } | null;
}
export interface AssetVersion {
  n?: number;
  id?: string;
  url?: string | null;
  label?: string;
  created_at?: string;
}
/** GET /api/assets/characters/{cid} 的 v1 扩展部分（W5）；旧字段见 types.ts CharacterAssets */
export interface CharacterAssetsV1 {
  id: string;
  name: string;
  face_url?: string | null;
  looks?: { id: string; name?: string; letter?: string; preview_url?: string | null }[];
  /** 每个资产（形象 / 部件）的参考图与版本 */
  assets?: { id: string; kind?: string; name?: string; url?: string | null; refs?: AssetRef[]; versions?: AssetVersion[] }[];
  episodes?: number[];
}

/** 查询串：跳过空值，没有参数就不带 ? */
const qs = (o: Record<string, string | undefined>) => {
  const u = new URLSearchParams(Object.entries(o).filter((e): e is [string, string] => e[1] != null));
  const t = u.toString();
  return t ? `?${t}` : "";
};

export const apiV1 = {
  // §C
  frameJob: (shot: string, body: FrameJobBody) => req<{ job_id: string }>(`/api/shots/${sid(shot)}/frame-jobs`, json("POST", body)),
  imagePresets: (gpu: number | string, refresh = false) =>
    req<ImagePresetsResp>(`/api/render/image-presets${qs({ gpu: gpu === "auto" ? undefined : String(gpu), refresh: refresh ? "true" : undefined })}`), // UIDEBUG #2
  saveImagePreset: (b: { label: string; params: Partial<ImageParams>; tier?: "preview" | "final"; base?: string; note?: string }) =>
    req<ImagePreset>(`/api/render/image-presets`, json("POST", b)),
  deleteImagePreset: (id: string) => req<{ deleted: string }>(`/api/render/image-presets/${sid(id)}`, { method: "DELETE" }),
  job: (id: string) => req<JobV1>(`/api/jobs/${sid(id)}`),
  cancelJob: (id: string) => req<unknown>(`/api/jobs/${sid(id)}/cancel`, { method: "POST" }),
  /** 定稿 / 取消定稿；stage 用 takes 的名字（image | last | video），与现有 activate 一致 */
  lockTake: (shot: string, stage: TakeStage, n: number, on: boolean) =>
    req<unknown>(`/api/shots/${sid(shot)}/takes/${stage}/${n}/${on ? "lock" : "unlock"}`, { method: "POST" }),
  /** 本镜出图任务（含已完成）；刷新页面后用来接回进行中的任务 */
  frameJobs: (shot: string) => req<ShotJobV1[]>(`/api/shots/${sid(shot)}/frame-jobs`),
  // §D
  videoTakes: (shot: string) => req<{ jobs?: ShotJobV1[] }>(`/api/shots/${sid(shot)}/video-takes`),
  videoJob: (shot: string, body: VideoJobBody) => req<{ job_id: string; warnings?: string[]; keyframe_check?: { first_last_diff?: number; warn?: boolean; message?: string | null } }>(`/api/shots/${sid(shot)}/video-jobs`, json("POST", body)),
  videoBases: () => req<{ default: string; bases: VideoBaseInfo[] }>(`/api/video-bases`),
  videoLoras: () => req<{ loras: OptionalVideoLora[]; strength_range: [number, number] }>(`/api/video-loras`),
  // §E
  shotRefs: (shot: string) => req<ShotRefsV1>(`/api/shots/${sid(shot)}/refs`),
  refsPreview: (shot: string, scope: RefScope, change: RefChange) =>
    req<RefPreview>(`/api/shots/${sid(shot)}/refs/preview`, json("POST", { scope, change })),
  refsApply: (shot: string, scope: RefScope, change: RefChange, rerender_first: boolean, by?: "owner") =>
    req<RefApplyResult>(
      `/api/shots/${sid(shot)}/refs/apply`,
      json("POST", by ? { scope, change, rerender_first, by } : { scope, change, rerender_first }),
    ),
  characterAssets: (cid: string) => req<CharacterAssetsV1>(`/api/assets/characters/${sid(cid)}`),
  uploadAssetRef: (asset: string, file: File, role: RefRole) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("role", role);
    return req<AssetRef>(`/api/assets/${sid(asset)}/refs`, { method: "POST", body: fd });
  },
  assetRefFromTake: (asset: string, b: { shot: string; stage: TakeStage; n: number; role: RefRole }) =>
    req<AssetRef>(`/api/assets/${sid(asset)}/refs/from-take`, json("POST", b)),
  assetGenJob: (asset: string, b: { base?: string; refs: { ref_id: string; role: RefRole }[]; prompt: string; strength: Strength; gpu?: 0 | 3 }) =>
    req<{ job_id: string }>(`/api/assets/${sid(asset)}/gen-jobs`, json("POST", b)),
  /** 后端字段名是 job_id（F2 修：原来发 job，后端 422） */
  assetVersion: (asset: string, b: { job_id?: string; label: string }) =>
    req<AssetVersion & { asset_id?: string }>(`/api/assets/${sid(asset)}/versions`, json("POST", b)),
  /** UX6（A B6）：另存为新资产（POST /fork）；旧后端没有 /fork（404/405）→ 退回 versions 的旧默认（同样是另存） */
  assetFork: async (asset: string, b: { job_id?: string; label: string }) => {
    try {
      return await req<AssetVersion & { asset_id?: string }>(`/api/assets/${sid(asset)}/fork`, json("POST", b));
    } catch (e) {
      const st = (e as { status?: number })?.status;
      if (st === 405 || (st === 404 && /^(404 )?Not Found$/.test(String((e as Error)?.message))))
        return req<AssetVersion & { asset_id?: string }>(`/api/assets/${sid(asset)}/versions`, json("POST", b));
      throw e;
    }
  },
  /** 从其他资产复制一张参考图 */
  assetRefCopy: (asset: string, b: { from_asset: string; ref_id: string; role?: RefRole }) =>
    req<AssetRef>(`/api/assets/${sid(asset)}/refs/copy`, json("POST", b)),
  /** 去掉一张参考图 → 返回剩下的 */
  assetRefDelete: (asset: string, ref_id: string) =>
    req<AssetRef[]>(`/api/assets/${sid(asset)}/refs/${sid(ref_id)}`, { method: "DELETE" }),
};

/** 选项统一成对象 */
export const opt = (o: RefOptionLike): RefOption => {
  if (typeof o === "string") return { id: o, name: o };
  return {
    ...o,
    id: o.id ?? o.plate_id ?? "",
    is_default: o.is_default ?? o.episode_default,
    thumb_url: o.thumb_url ?? o.preview_url ?? o.url ?? null,
  };
};
