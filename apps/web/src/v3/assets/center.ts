// UX5：资产中心的统一卡片数据（A_assets_ia.md §3.2 / §3.3）。
// 第一步只做“映射”，不迁移、不写任何数据：从现有只读接口拼起来——
//   角色 / 形象 / 衣橱 / 道具：GET /api/assets/characters
//   场景：GET /api/assets/scenes
//   出图预设：GET /api/render/image-presets；视频基底 / 附加视频 LoRA：GET /api/video-bases、/api/video-loras
//   版本、依赖已更新、身份 LoRA、音色：GET /api/revisions/keys（:8800 没重启前 404 → 这几类显示降级）
// 每类状态统一成 5 个：草稿 / 候选 / 定稿 / 作废 / 依赖已更新（映射规则见 statusOf* 的注释）。
import { loadStoryImages, type StoryImages } from "../storyImages";
import { api } from "../../api";
import type { CharacterAssets, LookView, WardrobeItemView } from "../../types";
import type { AssetStatus } from "../../ds";
import { apiV1, type ImagePreset, type OptionalVideoLora, type VideoBaseInfo } from "../api_v1";
import { assetsV1, type LightEpisode } from "../api_v1_pages";
import { lookLetter, lookTitle } from "../looks";
import { loadScenes, plateUrl, sceneName, type SceneView } from "../pages/scenes_api";
import { revApi, type RevKeyRow } from "./rev_api";

export type AssetType = "character" | "look" | "item" | "prop" | "scene" | "preset" | "vbase" | "vlora" | "lora" | "voice" | "template";

export const TYPE_NAME: Record<AssetType, string> = {
  character: "角色",
  look: "形象",
  item: "衣橱单品",
  prop: "道具·产品",
  scene: "场景",
  preset: "出图预设",
  vbase: "视频出片方式",
  vlora: "附加视频模型",
  lora: "身份模型",
  voice: "音色",
  template: "提示词模板",
};

export { SLOT_NAME, slotName } from "../words";
import { slotName } from "../words";

export interface AssetCardData {
  uid: string;
  type: AssetType;
  id: string;
  name: string;
  owner?: { id: string; name: string };
  thumb?: string | null;
  /** UIRSI：已挑定的身份参考（脸）——角标小图 */
  face?: string | null;
  status: AssetStatus;
  statusNote?: string;
  /** 当前版本号（vN）；没有就不显示 */
  version?: number | null;
  versions?: number;
  usage?: { eps?: number; shots?: number; estimated?: boolean } | null;
  missing?: string[];
  sub?: string;
  /** 出现在哪些集（“只看本集”过滤用；不知道 = undefined，过滤时保留） */
  eps?: number[];
  /** B_revision 依赖键（有就能看版本账本 / 影响面） */
  revKey?: string;
  /** 回到原始数据 */
  raw?: unknown;
  search: string;
}

export interface CenterData {
  cards: AssetCardData[];
  chars: CharacterAssets[] | null;
  eps: LightEpisode[] | null;
  scenes: SceneView[] | null;
  revKeys: RevKeyRow[] | null;
  errors: Partial<Record<"chars" | "eps" | "scenes" | "presets" | "video" | "revisions", string>>;
  revNotReady: boolean;
  /** 出图预设还在读（接口要探测显卡，慢） */
  presetsPending: boolean;
}

const errMsg = (e: unknown) => String((e as Error)?.message ?? e);

/** 形象：有自己的图 → 候选（needs_review）或定稿；没有图 → 草稿 */
function statusOfLook(lk: LookView): AssetStatus {
  const img = !!lk.preview_url || (lk.reference_images?.length ?? 0) > 0;
  if (!img) return "draft";
  return lk.needs_review ? "candidate" : "final";
}
/** 单品：挂 LoRA（触发词出图，不靠图）→ 定稿；没图 → 草稿；有图待复核 → 候选；有图已复核 → 定稿 */
function statusOfItem(w: WardrobeItemView): AssetStatus {
  if (w.lora_file) return "final";
  if (!w.has_image && !w.thumb_url) return "draft";
  return w.needs_review ? "candidate" : "final";
}
/** 角色：有母版 → 定稿；只有零散图 → 候选；什么都没有 → 草稿 */
function statusOfChar(c: CharacterAssets): AssetStatus {
  if (c.master) return "final";
  if (c.hero || c.face_url || c.portraits?.length) return "candidate";
  return "draft";
}
/** 场景：locked / 项目方确认 → 定稿；candidate → 候选；missing → 草稿 */
function statusOfScene(s: SceneView): AssetStatus {
  const p = s.plate;
  if (p?.locked || p?.owner_confirmed_at || p?.plate_status === "owner_confirmed") return "final";
  if (p?.plate_status === "candidate" || p?.url || s.variants?.some((v) => v.url)) return "candidate";
  return "draft";
}

/** DATAALIGN 11-01（DATA_MAP §6 第 2 项）：镜头卡人物 → 本镜造型键。series10（cast_source 有值）用出图同源的 A/B/C（shot_looks.json，
 *  资产中心整集排期优先），键 = "s10:<字母>"；旧剧照旧用 look_id（旧库形象）。没有字母 = 不计入任何造型（不再编字母） */
export type ShotCharLike = { character: string; look_id: string | null; look_label?: string; cast_source?: string };
// DATAALIGN 11-01：/api/episodes/summary 已带 cast_source（:8800 11:17 重启后实测 124/124），去掉“单个大写字母也按 s10 算”的兜底
export const shotLookKey = (c: ShotCharLike) => (c.cast_source ? (c.look_label ? `s10:${c.look_label}` : "") : (c.look_id ?? ""));

function usageOf(eps: LightEpisode[] | null) {
  const byChar = new Map<string, { eps: Set<number>; shots: number }>();
  const byLook = new Map<string, { eps: Set<number>; shots: number }>();
  for (const ep of eps ?? [])
    for (const s of ep.shots)
      for (const c of s.characters ?? []) {
        const a = byChar.get(c.character) ?? { eps: new Set(), shots: 0 };
        a.eps.add(ep.number);
        a.shots++;
        byChar.set(c.character, a);
        const k = shotLookKey(c as ShotCharLike);
        if (k) {
          const key = k.startsWith("s10:") ? `${c.character}:${k}` : k; // series10 字母按人物区分（林晚 A ≠ 顾沉 A）
          const b = byLook.get(key) ?? { eps: new Set(), shots: 0 };
          b.eps.add(ep.number);
          b.shots++;
          byLook.set(key, b);
        }
      }
  return { byChar, byLook };
}

const fromRev = (r: RevKeyRow | undefined) => (r ? { versions: r.versions_count || undefined, version: r.current.seq } : {});

type Settled<T> = PromiseSettledResult<T> | { status: "pending" };
const track = <T>(p: Promise<T>) => {
  const box: { r: Settled<T> } = { r: { status: "pending" } };
  const done = p.then(
    (value) => void (box.r = { status: "fulfilled", value }),
    (reason) => void (box.r = { status: "rejected", reason }),
  );
  return { box, done };
};

/** 先等快的几项（角色 / 集摘要 / 场景 / 视频 / 账本）就返回；出图预设接口要探测显卡（约 20 s），回来后再调 onLate 补上 */
export async function loadCenter(onLate?: (d: CenterData) => void): Promise<CenterData> {
  const t = {
    chars: track(api.assets.list().then((x) => x.characters)),
    eps: track(assetsV1.episodes()),
    scenes: track(loadScenes()),
    presets: track(apiV1.imagePresets(0)),
    vb: track(apiV1.videoBases()),
    vl: track(apiV1.videoLoras()),
    rk: track(revApi.keys()),
    idr: track(loadIdentityRefs()),
    simg: track(loadStoryImages()),
  };
  const fast = [t.chars, t.eps, t.scenes, t.vb, t.vl, t.rk, t.idr, t.simg].map((x) => x.done);
  await Promise.all(fast);
  const build = () => withIdentity(buildCenter(t.chars.box.r, t.eps.box.r, t.scenes.box.r, t.presets.box.r, t.vb.box.r, t.vl.box.r, t.rk.box.r), t.idr.box.r, t.simg.box.r);
  if (onLate) void t.presets.done.then(() => onLate(build()));
  return build();
}

/** UIRSI：项目方已挑定的设定图 + 身份参考（data/assets/identity_refs/manifest.json，项目方原话登记；只读） */
type IdRefs = { owner_quote?: string; registered_at?: string; chars?: Record<string, { file: string; source_sheet?: string }> };
const fileUrl = (p?: string | null) => (p ? `/files/${p.replace(/^data\//, "")}` : null);
async function loadIdentityRefs(): Promise<IdRefs> {
  const r = await fetch("/files/assets/identity_refs/manifest.json");
  return r.ok ? r.json() : {};
}
function withIdentity(d: CenterData, r: { status: string; value?: IdRefs } | undefined, si?: { status: string; value?: StoryImages }): CenterData {
  // 新出的设定图（IMGGEN：runs/<id>/images/chars/<角色>/）先上卡；项目方挑定的身份参考（manifest）优先
  const sim = si?.status === "fulfilled" ? si.value : undefined;
  if (sim?.chars)
    for (const c of d.cards) {
      if (c.type !== "character") continue;
      const hit = sim.chars[c.id] ?? sim.chars[c.name];
      const sheet = hit?.find((x) => x.kind === "sheet") ?? hit?.[0];
      if (sheet) {
        c.thumb = sheet.url;
        c.statusNote = `新设定图（${sim.run}，还没挑定）`;
      }
    }
  const m = r?.status === "fulfilled" ? r.value ?? null : null;
  if (!m?.chars) return d;
  for (const c of d.cards) {
    const ref = c.type === "character" ? m.chars[c.id] : undefined;
    if (!ref) continue;
    c.thumb = fileUrl(ref.source_sheet) ?? c.thumb;
    c.face = fileUrl(ref.file);
    c.statusNote = `设定图 / 身份参考已挑定（${m.registered_at ?? ""}${m.owner_quote ? ` · 原话“${m.owner_quote}”` : ""}）`;
  }
  return d;
}

function buildCenter(
  chars: Settled<CharacterAssets[]>,
  eps: Settled<LightEpisode[]>,
  scenes: Settled<SceneView[]>,
  presets: Settled<unknown>,
  vb: Settled<unknown>,
  vl: Settled<unknown>,
  rk: Settled<{ keys: RevKeyRow[] }>,
): CenterData {
  const errors: CenterData["errors"] = {};
  const ok = <T>(r: Settled<T>, k: keyof CenterData["errors"]): T | null => {
    if (r.status === "fulfilled") return r.value;
    if (r.status === "rejected") errors[k] = errMsg(r.reason);
    return null;
  };
  const C = ok(chars, "chars");
  const E = ok(eps, "eps");
  const S = ok(scenes, "scenes");
  const P = ok(presets, "presets");
  const VB = ok(vb, "video");
  const VL = ok(vl, "video");
  const RK = ok(rk, "revisions");
  const revNotReady = rk.status === "rejected" && !!(rk.reason as { notReady?: boolean })?.notReady;
  const presetsPending = presets.status === "pending";
  const revBy = new Map((RK?.keys ?? []).map((r) => [r.key, r]));
  const depOf = (key: string): AssetStatus | null => (revBy.get(key)?.unregistered_change ? "dep" : null);
  const { byChar, byLook } = usageOf(E);
  const cards: AssetCardData[] = [];

  for (const c of C ?? []) {
    const u = byChar.get(c.id);
    const idKey = `identity:${c.id}`;
    cards.push({
      uid: `character:${c.id}`,
      type: "character",
      id: c.id,
      name: c.name,
      thumb: c.hero?.url ?? c.face_url,
      status: depOf(idKey) ?? statusOfChar(c),
      statusNote: c.master ? "有定妆母版" : undefined,
      ...fromRev(revBy.get(idKey)),
      usage: E ? { eps: u?.eps.size ?? 0, shots: u?.shots ?? 0 } : null,
      eps: u ? [...u.eps] : E ? [] : undefined,
      missing: c.missing_count ? [`参考图 ${c.missing_count} 张`] : [],
      sub: `形象 ${c.looks.map((l) => lookLetter(c, l)).join("/") || "—"} · 衣橱 ${c.wardrobe.length}`,
      revKey: revBy.has(idKey) ? idKey : undefined,
      raw: c,
      search: `${c.name} ${c.id}`,
    });
    for (const lk of c.looks) {
      const u2 = byLook.get(lk.id);
      cards.push({
        uid: `look:${lk.id}`,
        type: "look",
        id: lk.id,
        name: `${c.name} · ${lookTitle(c, lk)}`,
        owner: { id: c.id, name: c.name },
        thumb: lk.preview_url,
        status: statusOfLook(lk),
        version: lk.version,
        usage: { eps: u2?.eps.size, shots: u2?.shots ?? lk.used_by_shots },
        eps: u2 ? [...u2.eps] : E ? [] : undefined,
        sub: `部件 ${Object.values(lk.items ?? {}).flat().length}${c.default_look_id === lk.id ? " · 集默认" : ""}`,
        raw: { ch: c, lk },
        search: `${c.name} ${lookTitle(c, lk)} ${lk.id}`,
      });
    }
    for (const w of c.wardrobe) {
      const prop = w.slot === "accessory" && !!w.lora_file;
      cards.push({
        uid: `item:${w.id}`,
        type: prop ? "prop" : "item",
        id: w.id,
        name: w.name,
        owner: { id: c.id, name: c.name },
        thumb: w.thumb_url,
        status: statusOfItem(w),
        statusNote: w.lora_file ? `模型：${w.lora_file}` : undefined,
        version: w.version,
        versions: w.image_urls?.length || undefined,
        usage: { shots: w.used_by_shots },
        eps: E ? [...new Set((w.used_by_looks ?? []).flatMap((l) => [...(byLook.get(l)?.eps ?? [])]))] : undefined,
        missing: !w.thumb_url && !w.lora_file ? ["图"] : [],
        sub: `${slotName(w.slot)}${w.lora_file ? " · 带模型" : ""}`,
        raw: { ch: c, w },
        search: `${c.name} ${w.name} ${slotName(w.slot)} ${(w.tags ?? []).join(" ")} ${w.id}`,
      });
    }
  }

  for (const s of S ?? []) {
    cards.push({
      uid: `scene:${s.scene_id}`,
      type: "scene",
      id: s.scene_id,
      name: sceneName(s),
      thumb: plateUrl(s),
      status: statusOfScene(s),
      statusNote: s.plate?.status_label ?? undefined,
      version: s.plate?.version ?? null,
      usage: { eps: s.episode_count ?? s.episodes?.length, shots: s.shot_count },
      eps: s.episodes ?? undefined,
      missing: plateUrl(s) ? [] : ["底图"],
      sub: (s.variants?.length ?? 0) > 1 ? `变体 ${s.variants!.length}` : undefined,
      raw: s,
      search: `${sceneName(s)} ${s.scene_id}`,
    });
  }

  // 风格：出图预设（内置 = 定稿；用户存的 = 候选，tier=final 的算定稿）
  const presetList: ImagePreset[] = (P as { presets?: ImagePreset[] } | null)?.presets ?? [];
  const defPreset = (P as { default_preset?: string } | null)?.default_preset;
  for (const p of presetList) {
    const key = `preset:${p.id}`;
    cards.push({
      uid: key,
      type: "preset",
      id: p.id,
      name: p.label,
      status: depOf(key) ?? (p.builtin || p.tier === "final" ? "final" : "candidate"),
      statusNote: p.id === defPreset ? "默认预设" : p.builtin ? "内置" : "用户存的",
      ...fromRev(revBy.get(key)),
      usage: revBy.get(key)?.used_by_count ? { shots: revBy.get(key)!.used_by_count, estimated: true } : null,
      sub: `${p.tier === "final" ? "定稿档" : "预览档"}${p.id === defPreset ? " · 默认" : ""}`,
      revKey: revBy.has(key) ? key : undefined,
      raw: p,
      search: `${p.label} ${p.id} 出图预设`,
    });
  }
  const bases: VideoBaseInfo[] = (VB as { bases?: VideoBaseInfo[] } | null)?.bases ?? [];
  const defBase = (VB as { default?: string } | null)?.default;
  for (const b of bases) {
    const key = `vbase:${b.id}`;
    cards.push({
      uid: key,
      type: "vbase",
      id: b.id,
      name: b.label ?? b.id,
      status: depOf(key) ?? (b.experimental ? "candidate" : "final"),
      statusNote: b.id === defBase ? "默认" : b.experimental ? "试验" : undefined,
      ...fromRev(revBy.get(key)),
      sub: `${b.steps ? `${b.steps} 步` : ""}${b.id === defBase ? " · 默认" : ""}`,
      revKey: revBy.has(key) ? key : undefined,
      raw: b,
      search: `${b.label ?? ""} ${b.id} 视频 出片方式 基底`,
    });
  }
  const vloras: OptionalVideoLora[] = (VL as { loras?: OptionalVideoLora[] } | null)?.loras ?? [];
  for (const l of vloras) {
    const key = `vlora:${l.name}`;
    cards.push({
      uid: `vlora:${l.id}`,
      type: "vlora",
      id: l.id,
      name: l.label ?? l.name,
      status: depOf(key) ?? "final",
      statusNote: l.license ? `许可：${l.license}` : undefined,
      ...fromRev(revBy.get(key)),
      sub: l.usage ?? l.tag,
      revKey: revBy.has(key) ? key : undefined,
      raw: l,
      search: `${l.label ?? ""} ${l.name} LoRA 视频`,
    });
  }
  // 身份 LoRA 指针 / 音色：只有账本接口知道（没重启前不出卡，由页面写降级说明）
  const charName = new Map((C ?? []).map((c) => [c.id, c.name]));
  for (const r of RK?.keys ?? []) {
    if (r.type !== "loraslot" && r.type !== "voice") continue;
    const slug = r.key.split(":")[1];
    const ch = (C ?? []).find((c) => c.id === slug);
    cards.push({
      uid: r.key,
      type: r.type === "voice" ? "voice" : "lora",
      id: r.key,
      name: r.label,
      owner: charName.has(slug) ? { id: slug, name: charName.get(slug)! } : undefined,
      thumb: r.type === "voice" ? null : ch?.face_url ?? null,
      status: r.unregistered_change ? "dep" : "final",
      ...fromRev(r),
      usage: r.used_by_count ? { shots: r.used_by_count } : null,
      sub: r.type === "voice" ? "音色（config/voices.json，只读；改动写提议）" : r.key.endsWith(":video") ? "视频身份模型 指针（registry 扩展里已采用的版本）" : "出图身份模型 指针",
      revKey: r.key,
      raw: r,
      search: `${r.label} ${r.key}`,
    });
  }
  return { cards, chars: C, eps: E, scenes: S, revKeys: RK?.keys ?? null, errors, revNotReady, presetsPending };
}

/** 左栏分类树（A §3.1：角色是聚合根；风格 / 声音是组） */
export const TREE: { id: string; label: string; types: AssetType[]; indent?: boolean; group?: string }[] = [
  { id: "all", label: "总览", types: [] },
  { id: "character", label: "角色", types: ["character"], group: "人" },
  { id: "look", label: "形象", types: ["look"], indent: true },
  { id: "item", label: "衣橱", types: ["item"], indent: true },
  { id: "prop", label: "道具·产品", types: ["prop"], group: "物" },
  { id: "scene", label: "场景", types: ["scene"] },
  { id: "style", label: "风格", types: ["preset", "vbase", "vlora", "lora"], group: "画面" },
  { id: "preset", label: "出图预设", types: ["preset"], indent: true },
  { id: "vbase", label: "视频出片方式", types: ["vbase", "vlora"], indent: true },
  { id: "lora", label: "身份模型", types: ["lora"], indent: true },
  { id: "loras", label: "全部模型（总表）", types: [], indent: true },
  { id: "voice", label: "声音 · 音色", types: ["voice"], group: "声音与文字" },
  { id: "template", label: "提示词模板", types: ["template"] },
];
