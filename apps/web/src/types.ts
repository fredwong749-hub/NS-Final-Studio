// 与 services/api/ns_api/app.py 的返回结构一一对应

export interface DialogueLine {
  speaker_note: string | null;
  text: string;
  /** 更前面的括号（舞台提示），如「接通」 */
  stage?: string | null;
}

export interface Voiceover {
  note: string | null;
  text: string;
}

export interface Extra {
  label: string;
  text: string;
}

export type JobState = "queued" | "running" | "done" | "failed";
export type Stage = "image" | "last" | "video";
export type LastSource = "gen" | "next" | "upload" | "video" | "gpu3";
export type FieldSource = "edit" | "auto" | "none";

export interface CameraInfo {
  text: string;
  source: FieldSource;
  sources: Partial<Record<"size" | "angle" | "move" | "lens", FieldSource>>;
  size: string;
  angle: string;
  move: string;
  lens: string;
}

export interface ExpressionInfo {
  text: string;
  source: FieldSource;
  cues: string[];
}

export interface SlotThumb {
  slot: string;
  items: { id: string; name: string; thumb_url: string | null }[];
  source: LookLayer | null;
  changed: boolean;
}

/** 镜头卡人物行（ns_api.assets.character_brief） */
export interface CharacterBrief {
  character: string;
  name: string;
  face_url: string | null;
  look_id: string | null;
  look_label: string;
  look_name: string;
  label: string;
  d_state: string | null;
  has_override: boolean;
  changed_from_prev: boolean;
  changed_fields: string[];
  slots: SlotThumb[];
  conflicts: LookConflict[];
  /** DATAALIGN（K-DATA-001）：剧本本镜 **人物** 行的出镜方式（在画 / 局部）；有 = 人选 / 造型字母 / 脸与出图同源（ns_api.shot_cast） */
  presence?: string;
  look_how?: string | null;
  cast_source?: "script_cast";
}

export interface Boost {
  first: string | null;
  last: string | null;
  episode_first: string | null;
  episode_last: string | null;
}

/** E8 声音字段（default = 不算人工修改时的值，「恢复默认」用） */
export interface AudioField {
  text: string;
  /** edit | script | script_h3 | episode | none */
  source: string;
  default: string;
  default_source: string;
  raw?: string;
}
export interface AudioSupported {
  soundscape: boolean;
  music: boolean;
  episode_music: boolean;
}
export interface ShotAudio {
  /** 环境声 overall_soundscape（进 H3） */
  soundscape: AudioField;
  /** 本镜配乐：英文 → 进本镜 H3 non_diegetic_music（覆盖本集默认）；中文 → 只作后期提示 */
  music: AudioField;
  episode_music: AudioField;
  supported: AudioSupported;
}

export interface EpisodeEdit {
  boost_first: string | null;
  boost_last: string | null;
  /** 本集背景音乐（后期） */
  music?: string | null;
  updated_at: string | null;
}

export interface TakeScore {
  total: number;
  parts?: Record<string, number>;
  missing?: string[];
  reasons?: string[];
}

export interface ShotSummary {
  id: string;
  index: number;
  adult: boolean;
  edited: boolean;
  camera: CameraInfo;
  expression: ExpressionInfo;
  img_summary: string;
  script_text: string;
  image_prompt: string;
  image_prompt_edited: boolean;
  /** = h3_prompt（SOP §9A 官方四块提示词：gpu3 最终 > 剧本 **H3提示词** > 笔记本草稿） */
  video_prompt: string;
  video_prompt_edited: boolean;
  /** 旧版中文视频提示词（只作历史，不进 H3） */
  legacy_video_prompt?: string;
  h3_prompt?: string;
  h3_prompt_source?: H3Source;
  h3_prompt_source_label?: string;
  h3_prompt_where?: string;
  h3_blocks?: H3Blocks;
  h3_frames?: number;
  /** 帧数 / 24 的秒数（"10.12"，H3 对齐句里的 S.SS） */
  h3_sss?: string | null;
  h3_lint?: H3LintResult[];
  h3_lint_ok?: boolean;
  h3_failed?: string[];
  h3_overrides?: string[];
  h3_missing?: string[];
  h3_music_source?: string | null;
  h3_editable?: boolean;
  /** 画布显示的 H3 提示词 sha256（保存覆盖时作 base_sha，gpu3 判过期） */
  h3_prompt_sha256?: string | null;
  h3_take?: H3Take | null;
  h3_override?: H3Override | null;
  /** 露骨红标：项目方自行处理，画布不做任何自动动作（服务端也 409） */
  explicit_hold?: ExplicitHold | null;
  h3_override_stale?: boolean;
  /** 项目方修改的起点（已有覆盖 > 剧本 / 笔记本草稿；不是 gpu3 版本） */
  h3_edit_base?: H3Blocks;
  last_prompt: string;
  last_prompt_source: "edit" | "compiler" | "fallback";
  /** 卡片显示用：跳过角色锁 / 固定前缀后的部分 */
  image_prompt_focus: string;
  last_prompt_focus: string;
  boost: Boost;
  has_boost: boolean;
  first_frame: string | null;
  first_frame_take: number | null;
  /** fredw-92/UXF1：当前首帧 / 尾帧是不是坏图（原因）；后端上线前缺省 */
  bad?: Partial<Record<"image" | "last", string | null>>;
  /** fredw-92/UXF1：定稿版本号（与当前版本号不同 = 当前看的是草稿） */
  locked_take?: Partial<Record<"image" | "last", number | null>>;
  /** fredw-92/UXF4（审查 N1）：整集出片“自动测试定稿”且仍有效的阶段 → 版本号（待项目方复审，不算定稿 / 通过） */
  auto_locked?: Partial<Record<"image" | "last" | "video", number>>;
  /** 视频实际尾帧（= last_frame_actual，兼容 v1） */
  last_frame: string | null;
  last_frame_source: LastSource | null;
  last_frame_target: string | null;
  last_frame_actual: string | null;
  last_frame_take: number | null;
  next_shot: string | null;
  next_first_frame: string | null;
  last_supported: boolean;
  takes_count: Record<Stage, number>;
  /** 各阶段最新版本号；大于当前版本 = 有新版本待选 */
  latest_take: Partial<Record<Stage, number | null>>;
  duration: { seconds: number; source: string };
  /** 后端上线前可能缺省 */
  audio?: ShotAudio;
  /** 当前首帧 / 尾帧版本的评分（多候选，C5） */
  score: Partial<Record<Stage, TakeScore | null>>;
  /** 渲染器标记需要人工复核的阶段（takes.json review） */
  needs_review: Partial<Record<Stage, unknown>>;
  video: string | null;
  /** fredw-92/QCV：当前视频运动量质检（没质检过 / gpu3 链 → null） */
  video_qc?: import("./v3/MotionQc").MotionQc | null;
  dialogue: DialogueLine[];
  voiceover: Voiceover | null;
  decor_state: string | null;
  look_hash: string | null;
  characters: CharacterBrief[];
  job: "queued" | "running" | null;
  job_stage: Stage | "asset" | null;
  queue_pos: number | null;
  review: Review;
  /** 本镜输入变化导致的过期原因（卡片显示）；空数组 = 最新 */
  stale: Partial<Record<Stage, string[]>>;
  /** 全局编译器升级（只在检查器 / 版本里显示） */
  stale_global: Partial<Record<Stage, string[]>>;
  /** UX5-B：所用资产版本已更新（“依赖已更新”角标；不算过期） */
  stale_deps?: Partial<Record<Stage, DepStale[]>>;
  /** 一条链（§4）：谁负责出首尾帧+视频；行内显示的帧来自哪条链 */
  owner?: "gpu3" | "laptop";
  owner_reason?: string;
  frames_source?: "gpu3" | "laptop" | "none";
  gpu3?: Gpu3Chain;
  /** gpu3 负责时，笔记本已有的帧只作历史（未用于视频） */
  laptop_history?: LaptopHistory | null;
  readiness?: Readiness;
  prev_shot?: string | null;
}

export interface Gpu3Chain {
  present: boolean;
  dir: string | null;
  first_frame: string | null;
  first_mirrored: boolean;
  first_from: string;
  last_frame: string | null;
  last_mirrored: boolean;
  last_from: string;
  video: string | null;
  video_mirrored: boolean;
  image_take: number | null;
  video_take: number | null;
  video_before_first: boolean;
  takes_count: Record<string, number>;
  status: string | null;
  blocked_reasons: string[];
  continuity: unknown;
  updated_at: string | null;
}

export interface LaptopHistory {
  first: string | null;
  first_take: number | null;
  last: string | null;
  video: string | null;
  note: string;
}

export type ReadinessLevel = "ok" | "warn" | "fail";

export interface ReadinessItem {
  key: string;
  label: string;
  ok: boolean;
  level: ReadinessLevel;
  reason: string;
  source: string;
}

export interface Readiness {
  ready: boolean;
  items: ReadinessItem[];
  blocked_reasons: string[];
  gpu3_blocked_reasons: string[];
  gpu3_status: string | null;
  by: "gpu3" | "laptop";
}

export interface EpisodeReadiness {
  ready: number;
  total: number;
  owner: "gpu3" | "laptop";
  continuity_sheet: string | null;
  continuity_sheet_path: string | null;
  qa: unknown;
}

export type ReviewState = "unreviewed" | "passed" | "rejected";

export interface Review {
  state: ReviewState;
  reason: string;
  at: string | null;
}

export interface Episode {
  number: number;
  /** T60：true = 来自 /api/episodes/summary 的轻量数据（shots 只有列表 / 总览 / 过滤用的字段），不能渲染镜头行 */
  light?: boolean;
  /** T60：每集摘要（仅摘要接口带） */
  summary?: { shots: number; ready: number | null; seconds: number; first_frames: number; videos: number; passed: number };
  title: string;
  high_intensity: boolean;
  tag: string;
  synopsis: string;
  edit: EpisodeEdit;
  music?: AudioField;
  audio_supported?: AudioSupported;
  readiness?: EpisodeReadiness;
  explicit_hold_count?: number;
  shots: ShotSummary[];
}

export interface ScriptShot {
  episode: number;
  index: number;
  img_note: string | null;
  img_prompt: string;
  img_triggers: string[];
  motion_prompt: string;
  motion_triggers: string[];
  sound: string;
  voiceover: Voiceover | null;
  dialogue_raw: string | null;
  dialogue: DialogueLine[];
  extras: Extra[];
  decor_state: string | null;
  source_line: number;
}

export type H3Source = "gpu3" | "script" | "laptop";

export interface H3Blocks {
  alignment: string;
  body: string;
  soundscape: string;
  music: string;
}

/** ns_schema.h3_lint 一条结果；rule_id 同 docs/audit/rule_ids.md */
export interface H3LintResult {
  rule_id: string;
  sop_ref: string;
  ok: boolean;
  detail: string;
  msg: string;
  level: "block" | "warn";
  overridden?: boolean;
}

export interface ExplicitHold {
  source: string;
  sources: string[];
  reason: string;
  label: string;
}

export interface H3Override {
  present: boolean;
  by: string | null;
  at: string | null;
  note: string | null;
  base_sha: string | null;
  based_on: "script" | "laptop";
  status: "renderable" | "draft";
  failed: string[];
  stale: boolean;
  current_script_sha: string | null;
}

export interface H3Take {
  n: number | null;
  prompt: string;
  frames: number | null;
  prompt_sha256: string | null;
  prompt_sha256_source: "takes.json" | "computed";
  is_h3: boolean;
}

export interface Compiled {
  image_prompt: string;
  image_negative: string;
  /** 画布显示的 H3 提示词（video_negative 不再下发：H3 cfg 1 没有负向） */
  video_prompt: string;
  legacy_video_prompt?: string;
  laptop_h3_prompt?: string;
  adult: boolean;
  adult_reasons: string[];
  dropped_triggers: string[];
}

export interface ShotEdit {
  image_prompt: string | null;
  image_negative: string | null;
  video_prompt: string | null;
  camera: string | null;
  expression: string | null;
  image_seed: number | null;
  video_seed: number | null;
  /** "next" = 下一镜首帧；否则为相对 data/ 的图片路径 */
  last_frame: string | null;
  last_prompt?: string | null;
  last_seed?: number | null;
  last_source?: LastSource | null;
  /** 导演加强（项目方原文，渲染器拼进提示词） */
  boost_first?: string | null;
  boost_last?: string | null;
  /** 环境声 overall_soundscape（英文 1–4 句） */
  soundscape?: string | null;
  /** 已停用：H3 只经 putH3Override 由项目方修改 */
  h3_body?: string | null;
  h3_prompt_override?: string | null;
  h3_override_by?: string | null;
  h3_override_at?: string | null;
  h3_override_note?: string | null;
  h3_override_base_sha?: string | null;
  h3_override_status?: "renderable" | "draft" | null;
  h3_override_failed?: string[] | null;
  /** 本镜配乐提示（后期） */
  music?: string | null;
  note: string;
  updated_at: string | null;
}

export interface Take {
  n: number;
  stage: Stage;
  file: string;
  seed: number;
  prompt: string;
  negative: string;
  seconds: number | null;
  frames: number | null;
  last_frame: string | null;
  created_at: string;
  url: string | null;
  last_url: string | null;
  stale?: string[];
  stale_global?: string[];
  /** UX5-B：所用资产版本已更新（只标记，不算过期） */
  stale_deps?: DepStale[];
  /** UX5-B：出图 / 出视频时所用资产版本 {依赖键: rev} */
  deps?: Record<string, string> | null;
  workflow?: string | null;
  source?: string | null;
  reference?: string | null;
  raw_file?: string | null;
  raw_url?: string | null;
  grade?: Record<string, unknown> | null;
  score?: TakeScore | null;
  round?: number | null;
  references?: string[] | null;
  qc?: { nudity?: boolean; motion?: import("./v3/MotionQc").MotionQc } | null;
  /** fredw-92/UXF1：坏图原因（短边 < 256 px / 文件 < 10 KB / 尺寸与请求不符）；坏图不设为当前、不能定稿 */
  bad?: string | null;
  quarantined?: string | null;
}

export interface Takes {
  takes: Take[];
  active: Partial<Record<Stage, number>>;
}

export interface ShotDetail {
  summary: ShotSummary;
  episode: { number: number; title: string; synopsis: string; edit: EpisodeEdit };
  script: ScriptShot;
  compiled: Compiled;
  compiled_last: { last_prompt: string; source: string; compiler_has_last_prompt: boolean };
  /** 渲染器写的 compiled.json（含 image_body / end_state / visual_spec / boost_*） */
  compiled_file: Record<string, unknown> | null;
  visual_spec: Record<string, unknown> | null;
  assembled: {
    first: string;
    last: string;
    first_landed: boolean | null;
    first_episode_landed: boolean | null;
    last_landed: boolean | null;
    last_episode_landed: boolean | null;
  };
  edit: ShotEdit;
  /** "next"、上传尾帧的 /files URL，或 null */
  last_frame_target: string | null;
  takes: Takes;
  /** T21：gpu3 负责的镜头才有（只读版本链；video 版本带 last_url 尾帧） */
  gpu3_takes?: { takes: (Take & { last_url?: string | null })[]; active: Record<string, number> } | null;
  next_shot: string | null;
  error: { last: string; at: string } | null;
}

export interface Job {
  id: string;
  shot_id: string;
  stage: Stage | "asset";
  seed: number | null;
  state: JobState;
  created_at: string;
  error: string | null;
  take?: number;
  started_at?: string;
}

export interface BatchResult {
  shot_id: string;
  ok: boolean;
  job?: Job;
  error?: string;
}

// ---------- 造型 /api/looks（services/api/ns_api/looks.py, packages/schema/ns_schema/looks.py） ----------

export type LookLayer = "default" | "episode" | "shot";
export type Visibility = "visible" | "hidden" | "in_box";

export interface Look {
  id: string;
  character: string;
  name: string;
  items: Record<string, string[]>;
  decor_state: string | null;
  reference_images: string[];
  reference_urls?: (string | null)[];
  needs_review: boolean;
  notes: string[];
  label?: string | null;
  preview_image?: string | null;
  version?: number;
}

export interface LookPatch {
  look_id?: string | null;
  slots?: Record<string, string[]> | null;
  d_state?: string | null;
  visibility?: Visibility | null;
  present?: boolean | null;
  reference_images?: string[];
  needs_review?: boolean;
  notes?: string[];
}

export interface LookConflict {
  kind: string;
  severity: "error" | "warning" | "info";
  message: string;
  slot: string | null;
  item_id: string | null;
}

export interface ResolvedSlot {
  items: string[];
  names: string[];
  source: LookLayer | null;
  changed_from_prev: boolean;
}

export interface ResolvedField {
  value: string | null;
  source: LookLayer | null;
  changed_from_prev: boolean;
}

export interface ResolvedLook {
  character: string;
  name: string;
  present_source: "detected" | "shot";
  look_id: string | null;
  look_id_source: LookLayer | null;
  look_name: string;
  label: string;
  slots: Record<string, ResolvedSlot>;
  d_state: ResolvedField;
  visibility: ResolvedField;
  reference_images: string[];
  has_override: boolean;
  prev_shot_id: string | null;
  changed_from_prev: boolean;
  changed_fields: string[];
  conflicts: LookConflict[];
  needs_review: boolean;
  notes: string[];
  hash: string;
}

export interface ShotLookBrief {
  label: string;
  look_id: string | null;
  hash: string;
  has_override: boolean;
  changed_from_prev: boolean;
  changed_fields: string[];
  conflicts: LookConflict[];
}

export interface EpisodeLooks {
  episode: number;
  title: string;
  characters: Record<string, { name: string; default_look_id: string | null; plan: LookPatch | null; resolved: ResolvedLook }>;
  shots: { shot_id: string; index: number; look_hash: string; characters: Record<string, ShotLookBrief> }[];
}

export interface CharacterLookPrompt {
  character: string;
  name: string;
  fragment: string;
  triggers: string[];
  already_in_prompt: string[];
  skipped_not_in_shot: string[];
}

export interface ShotLooks {
  shot_id: string;
  episode: number;
  index: number;
  script_decor_state: string | null;
  look_hash: string;
  characters: ResolvedLook[];
  prompt: { shot_id: string; fragment: string; triggers: string[]; characters: CharacterLookPrompt[] };
}

export interface LookCatalog {
  characters: { id: string; name: string; default_look_id: string | null }[];
  slots: string[];
  items: { id: string; slot: string; name: string; character: string | null; reference_urls: (string | null)[] }[];
  looks: Look[];
  decor_states: { id: string; description: string; items: string[]; episodes: number[] }[];
}

export interface AffectedShots {
  affected_count: number;
  affected_shots: string[];
  rendering_triggered: false;
}

// ---------- 资产 /api/assets（services/api/ns_api/assets.py） ----------

export interface AssetEntry {
  file: string;
  url: string | null;
  kind: string;
  group: "plate" | "expression" | "item" | "look" | "portrait";
  category: string;
  name?: string | null;
  design?: string | null;
  prompt?: string | null;
  seed?: number | null;
  model?: string | null;
  workflow?: string | null;
  references?: string[] | null;
  sha256?: string | null;
  created_at?: string | null;
  tags?: string[] | null;
  manifest: string | null;
  source: "manifest" | "loose";
  missing_file: boolean;
  registered_item_id?: string | null;
}

export interface ItemImage {
  file: string;
  variant: string;
  version: number;
  sha256: string;
  source: string;
  created_at: string | null;
  url?: string | null;
}

export interface WardrobeItemView {
  id: string;
  slot: string;
  name: string;
  description: string;
  character: string | null;
  trigger: string | null;
  lora_file: string | null;
  keywords: string[];
  reference_images: string[];
  reference_urls: (string | null)[];
  prompt_policy: string;
  removable: boolean;
  source: string;
  needs_review: boolean;
  notes: string[];
  images: ItemImage[];
  image_urls: ItemImage[];
  tags: string[];
  version: number;
  thumb_url: string | null;
  has_image: boolean;
  used_by_looks: string[];
  used_by_shots: number;
}

export interface LookView extends Look {
  preview_url: string | null;
  used_by_shots: number;
}

export interface CharacterAssets {
  id: string;
  name: string;
  dir: string;
  dir_exists: boolean;
  face_url: string | null;
  /** plates/master.png（写实母版），没有时 null */
  master: AssetEntry | null;
  /** 资产页大图：母版 → 正面 plate → 定妆原图 */
  hero: AssetEntry | null;
  default_look_id: string | null;
  plates: Record<string, AssetEntry | null>;
  expressions: AssetEntry[];
  items: Record<string, AssetEntry[]>;
  look_images: AssetEntry[];
  portraits: AssetEntry[];
  wardrobe: WardrobeItemView[];
  looks: LookView[];
  missing: string[];
  missing_count: number;
  unregistered: number;
}

export interface AssetCatalog {
  slots: string[];
  item_categories: string[];
  plate_views: string[];
  variants: string[];
  max_refs: number;
  decor_states: string[];
  characters: CharacterAssets[];
}

export interface RefEntry {
  character: string;
  name: string;
  role: string;
  label: string;
  item_id: string | null;
  file: string | null;
  url: string | null;
  text_only: boolean;
  duplicate: boolean;
  truncated: boolean;
  index?: number;
}

export interface ShotRefs {
  shot_id: string;
  limit: number;
  model: string;
  count: number;
  refs: RefEntry[];
  files: string[];
  anchor_lines: string[];
}

export interface ImportReport extends AffectedShots {
  created: { file: string; item_id: string }[];
  attached: { file: string; item_id: string; ref: string }[];
  skipped: { file: string; reason: string }[];
}

export interface GenerateRequest {
  target: string;
  prompt: string;
  references?: string[];
  model?: "qwen" | "klein";
  seed?: number | null;
  name?: string | null;
  negative?: string;
}

/** SOP 阶段 S1–S5 / 关口（/api/sop/*，docs/SOP_production.md ★）。只读：项目方关口只给命令，从不代为接受 */
export type SopStage = "S1" | "S2" | "S3" | "S4" | "S5";
export type SopActor = "owner" | "gpu3" | "laptop";

export interface SopBlocker {
  code: string;
  stage: SopStage;
  text: string;
  actor: SopActor;
  actor_label: string;
  cli?: string;
  shots?: string[];
}

export interface SopShot {
  id: string;
  episode: number;
  index: number;
  stage: SopStage;
  stage_label: string;
  blockers: SopBlocker[];
  stages: Record<string, { passed: boolean; blockers: SopBlocker[]; warnings?: { code: string; stage: string; trigger?: string; text: string; rule_ids?: string[] }[] }>;
  frames_owner: string;
  ahead_of_gate: string[];
}

export interface SopOwnerAction {
  gate: string;
  stage: SopStage;
  title: string;
  why: string;
  cli: string | null;
  cli_all?: string;
  cli_rework?: string;
  /** fredw-92/UXF1：确认造型的角色 id / 中文名 / 未确认的集；G4 / G5 的集号；底板的场景 */
  character?: string;
  character_name?: string;
  episodes?: number[];
  episode?: number;
  plate?: string | null;
  scene_id?: string;
  /** UIFIX-F 11-03（gate=look）：人物资产是否齐到能确认造型（身份脸 / 清单 / 本集排期，口径 tools/master/episode_ready）；
   *  false 时 asset_wait 是给项目方看的一句话（“X的形象还在出候选，选定后再确认造型”），入口不开。旧后端没有这两个字段 = 按就绪 */
  asset_ready?: boolean;
  asset_wait?: string | null;
  /** V2CUT-O 11-03（gate=look，资产包剧）：每集一条，列出本集全部人物（人名 / 本集造型 / 缩略图），一键确认整集；
   *  和通知中心 pick:look 同一个后端（ns_api.look_confirm），哪边确认了两边同时消失。前端一律显示 display_name，不显示 cid */
  per_episode?: boolean;
  people?: LookPerson[];
  pick_id?: string | null;
  actionable: boolean;
  waiting_on: string[];
}

export interface LookPerson {
  cid: string;
  display_name: string;
  look_id: string | null;
  look_name: string;
  thumb_url: string | null;
  thumb_note?: string | null;
  ready: boolean;
  wait: string | null;
}

export interface SopGate {
  id: string;
  label: string;
  stage: SopStage;
  status: "passed" | "blocked" | "pending" | "warn" | "info";
  detail: string;
  blockers: SopBlocker[];
}

export interface SopEpisode {
  project: string;
  episode: number;
  stage: SopStage | "done";
  stage_label: string;
  counts: Record<SopStage, number>;
  total: number;
  stages: { id: SopStage; label: string; shots_here: number }[];
  episode_blockers: SopBlocker[];
  blocker_summary: SopBlocker[];
  gates: SopGate[];
  owner_actions: SopOwnerAction[];
  shots: SopShot[];
}

// ---- 后端 C：Qwen 信箱代理（docs/qwen_comms.md；内容原样，不读不改）+ T44 ComfyUI 锁

export type QwenKind = "script" | "lora" | "blender" | "crawl" | "image_request" | "other";
export type QwenStatus = "queued" | "running" | "done" | "failed";

export interface QwenMeta {
  kind: QwenKind;
  project?: string;
  episode?: number | string;
  shot?: string;
  parent?: string;
  [k: string]: unknown;
}

export interface QwenScriptValidation {
  ok: boolean;
  exit_code: number;
  blocking: number | null;
  warnings: number | null;
  episodes_found: number;
  repair_text: string;
  stderr: string;
}

export interface QwenScriptInfo {
  project: string;
  path: string;
  sha256: string;
  bytes: number;
  fetched_at: string;
  validation: QwenScriptValidation;
}

export interface QwenTask {
  id: string;
  meta: QwenMeta;
  text: string | null;
  status: QwenStatus | null;
  created_at: string | null;
  updated_at?: string;
  output?: unknown;            // = result.output 原样
  result?: unknown;
  error?: unknown;
  reachable?: boolean;
  hint?: string;
  script?: QwenScriptInfo;
  repair_task?: string;
  imported?: { at: string; by: string; out: string; sha256: string; log: string };
}

export interface QwenTaskList {
  tasks: QwenTask[];
  reachable: boolean | null;
  hint?: string;
}

export interface QwenHealth {
  reachable: boolean;
  upstream: string;
  health?: unknown;
  error?: string;
  hint?: string;
}

export interface ComfyLock {
  free: boolean;
  holder: { who: "canvas" | "orchestrator" | string; what?: string; pid?: number; since?: string } | null;
  lock: string;
}

/** T44：渲染任务在等本机 ComfyUI 锁时带上占用者（state 仍是 running）；拿到锁后字段消失。
 *  who = "offline"：本机 ComfyUI 没开，任务挂起等待，启动后自动继续 */
export interface Job {
  comfy_wait?: ComfyLock["holder"] & { error?: string };
}

/** IMGPERF（11-01）：ns_api.jobs 写的当前阶段（stage 固定：queued / lane_check / prepare / upload / comfy_queue /
 *  comfy_run / download / post / finish，结束后 done / failed / cancelled）。label 是可直接显示的中文；
 *  step = 上传第几张 / ComfyUI 前面还有几个；since = 本阶段开始时间（本段用时 = 现在 − since） */
export interface JobProgress {
  stage: string;
  label: string;
  step?: number | null;
  total?: number | null;
  since?: string | null;
}
export interface Job {
  progress?: JobProgress | null;
}

/** GET /api/render-backend：本机出图后端（ComfyUI）状态 */
export interface RenderBackend {
  url: string;
  reachable: boolean;
  running?: number;
  pending?: number;
  gpu?: string;
  vram_total_mb?: number;
  vram_used_mb?: number;
  error?: string;
}

/** GET /api/gpu3/requests：「请 gpu3 重出」每条请求的进度（新→旧） */
export type Gpu3RequestState =
  "queued" | "started" | "image_done" | "video_done" | "done" | "failed" | "skipped" | "cancelled";
export interface Gpu3Request {
  id: string;
  shot: string;
  stage: "image" | "video" | "both" | string;
  state: Gpu3RequestState;
  at: string | null;
  requested_at: string | null;
  error: string | null;
  takes: { stage: string; n: number }[];
  source: "bridge" | "mirror";
}

/** GET /api/people：人物管理总表一行 */
export interface Person {
  id: string;
  name: string;
  role: string;
  notes: string;
  archived: boolean;
  created_at?: string | null;
  dir: string;
  dir_exists: boolean;
  face_url: string | null;
  hero_url: string | null;
  plates: Record<string, string | null>;
  item_counts: Record<string, number>;
  expressions: number;
  looks: number;
  look_labels: (string | null)[];
  wardrobe: number;
  missing_count: number;
  missing: string[];
  unregistered: number;
  used_by_shots: number;
}
export interface PeopleList {
  plate_views: string[];
  item_categories: string[];
  people: Person[];
}

/** UX5-B（docs/ux_round5/B_revision.md）：一条“依赖已更新” */
export interface DepStale {
  key: string;
  label: string;
  from: string | null;
  to: string | null;
  from_v: string;
  to_v: string;
  text: string;
}
