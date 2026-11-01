// PW-019：从 ImageParams.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { useEffect, useState, useSyncExternalStore } from "react";
import { apiV1, errText, type ImageParams, type ImagePresetsResp } from "../api_v1";
import type { TakeX } from "./state";

export interface Choice {
  /** null = 默认预设（后端 default_preset） */
  preset: string | null;
  /** 面板上的完整参数（null = 就是预设值） */
  full: ImageParams | null;
}

export let choice: Choice = { preset: null, full: null };

export let presetsCache: ImagePresetsResp | null = null;

export const subs = new Set<() => void>();

export const emit = () => subs.forEach((f) => f());

export const setParamChoice = (c: Partial<Choice>) => {
  choice = { ...choice, ...c };
  emit();
};

export function useParamChoice(): Choice {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => choice,
  );
}

export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export function merge<T extends object>(base: T, over: Partial<T> | undefined): T {
  const out = clone(base) as Record<string, unknown>;
  for (const [k, v] of Object.entries(over ?? {})) {
    const b = out[k];
    out[k] = v && typeof v === "object" && !Array.isArray(v) && b && typeof b === "object" && !Array.isArray(b) ? merge(b as object, v as object) : clone(v);
  }
  return out as T;
}

export function presetFull(r: ImagePresetsResp, id: string | null): ImageParams {
  const p = r.presets.find((x) => x.id === (id ?? r.default_preset));
  return merge(r.defaults, p?.params);
}

/** 和预设不同的字段（顶层整块比较） */
export function overridesOf(full: ImageParams, base: ImageParams): Partial<ImageParams> {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(full) as (keyof ImageParams)[]) {
    if (JSON.stringify(full[k]) !== JSON.stringify(base[k])) out[k] = full[k];
  }
  return out as Partial<ImageParams>;
}

/** submitFrame 用：{preset, params}；没选也没改 = {}（后端默认 = 项目方选定 C）。定稿档预设只用于整张出 */
export function paramBody(mode: string): { preset?: string; params?: Partial<ImageParams> } {
  const r = presetsCache;
  if (!r) return {};
  const pid = choice.preset ?? r.default_preset;
  const pr = r.presets.find((p) => p.id === pid);
  if (pr?.tier === "final" && mode !== "regen") return {};
  const ov = choice.full ? overridesOf(choice.full, presetFull(r, pid)) : {};
  const changed = Object.keys(ov).length > 0;
  if (!changed && pid === r.default_preset) return {};
  return { preset: pid, ...(changed ? { params: ov } : {}) };
}

/** 预设说明的第一句（去掉转述人 / 日期），细节折叠 */
export function noteShort(note: string): string {
  const head = note.replace(/（fredw-[^）]*）/g, "").replace(/\d{4}-\d{2}-\d{2}\s*/g, "").split(/[：:；;。]/)[0].trim();
  return head.length > 2 && head.length <= 24 ? `${head}（展开看细节）` : "说明（展开看细节）";
}

export function useImagePresets(gpu: number | string) {
  const [r, setR] = useState<ImagePresetsResp | null>(presetsCache);
  const [err, setErr] = useState("");
  const load = (refresh = false) =>
    apiV1.imagePresets(gpu, refresh).then(
      (x) => {
        presetsCache = x;
        setR(x);
        setErr("");
        emit();
      },
      (e) => setErr(errText(e, "出图参数 /api/render/image-presets")),
    );
  useEffect(() => {
    void load();
  }, [gpu]); // eslint-disable-line react-hooks/exhaustive-deps
  return { r, err, reload: load };
}

export type Eff = NonNullable<NonNullable<TakeX["params"]>["effective"]>;

export const f2 = (n: number | null | undefined) => (n == null ? "—" : String(Math.round(n * 100) / 100));

export const sizeOf = (w?: number | null, h?: number | null) => (w && h ? `${w}×${h}` : "—");

export const PARAM_ROWS: [string, (e: Eff) => string][] = [
  ["模型", (e) => (e.unet === "turbo" ? "Turbo" : e.unet === "base" ? "Base" : "—") + (e.tier === "final" ? " · 定稿档" : "")],
  ["步数", (e) => (e.unet === "turbo" ? "8（官方 sigma）" : String(e.steps ?? "—"))],
  ["cfg", (e) => f2(e.cfg)],
  ["采样 / 调度", (e) => `${e.sampler ?? "—"} / ${e.unet === "turbo" ? "固定 sigma" : e.scheduler ?? "—"}`],
  ["shift", (e) => (e.shift == null ? "—" : f2(e.shift))],
  ["VAE", (e) => (e.vae === "texture_fix" ? "纹理修复" : e.vae === "plain" ? "普通" : String(e.vae ?? "—"))],
  ["LoRA", (e) => (e.loras?.length ? e.loras.map((l) => `${l.name.replace(/\.safetensors$/, "").replace(/_qwen21$/, "")} ${f2(l.strength)}`).join("，") : "无")],
  ["尺寸", (e) => sizeOf(e.width, e.height) + (e.rendered_size && (e.rendered_size[0] !== e.width || e.rendered_size[1] !== e.height) ? `（出图 ${sizeOf(e.rendered_size[0], e.rendered_size[1])}）` : "")],
  ["两段式", (e) => (e.two_stage?.enabled ? `${sizeOf(...(e.two_stage.first_size ?? [0, 0]))} → ${sizeOf(...(e.two_stage.upscale_size ?? [0, 0]))} · ${f2(e.two_stage.denoise)}` : "关")],
  ["细节重绘", (e) => (e.detail_pass?.enabled ? `×${f2(e.detail_pass.scale)} · ${f2(e.detail_pass.denoise)}` : "关")],
  ["重绘幅度", (e) => f2(e.strength)],
  ["调色", (e) => (e.grade?.enabled ? `开 ${f2(e.grade.strength)}` : "关")],
  ["放大出图", (e) => (e.render_scale && e.render_scale !== 1 ? `×${f2(e.render_scale)}` : e.render_scale_requested ? `关（${e.render_scale_note ?? "改图不放大"}）` : "关")],
  ["锐化", (e) => (e.sharpen?.enabled ? `r${f2(e.sharpen.radius)} · ${f2(e.sharpen.amount)}` + (e.sharpen.threshold ? ` · 阈值 ${e.sharpen.threshold}` : "") : "关")],
  ["风格后缀", (e) => (e.style_suffix ? (e.style_suffix_applied === false ? "未接上：" : "") + e.style_suffix : "无")],
  ["规格词", (e) => (e.spec_words === false ? "去掉" : "带")],
  ["种子", (e) => String(e.seed ?? "—")],
];

export interface RenderSettings {
  /** 默认预设的显示名，例：C·Turbo 质感（项目方选定） */
  defaultLabel: string | null;
  /** true / false = 配置里的 auto_final_on_lock；null = 旧 API 没给 */
  autoFinal: boolean | null;
}

export function renderSettingsOf(r: ImagePresetsResp | null): RenderSettings {
  if (!r) return { defaultLabel: null, autoFinal: null };
  const p = r.presets.find((x) => x.id === r.default_preset);
  return { defaultLabel: p?.label ?? r.default_preset ?? null, autoFinal: typeof r.auto_final_on_lock === "boolean" ? r.auto_final_on_lock : null };
}

/** 读一次（与出图参数面板共用缓存） */
export function useRenderSettings(): RenderSettings {
  const { r } = useImagePresets("auto");
  return renderSettingsOf(r);
}

/** “定稿后会不会自动出定稿档”的一句话 */
export function autoFinalText(s: RenderSettings): string {
  return s.autoFinal == null ? "定稿后是否自动出定稿档按项目设置" : s.autoFinal ? "定稿后自动出定稿档" : "定稿后不自动出定稿档（定稿档已暂停）";
}

/** UX4：预设 id → 名字（“徕卡 S★”）；不给 id = 后端默认预设。读不到预设表时返回 id / “默认预设” */
export function presetLabelOf(id: string | null | undefined): string {
  const r = presetsCache;
  const pid = id ?? r?.default_preset ?? null;
  const p = r?.presets.find((x) => x.id === pid);
  return p?.label ?? pid ?? "默认预设";
}
