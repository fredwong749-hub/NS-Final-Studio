// fredw-92/PX：出图参数面板（预设 + 每次覆盖）+ 版本参数对比。
// 选择是全局的“下一次出图用的参数”：右栏「高级」和「修改诉求」弹窗共用；submitFrame 自动带上（没改 = 不带，后端用默认预设）。
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { apiV1, errText, type ImageParams, type ImagePreset, type ImagePresetsResp, type LoraRow } from "../api_v1";
import type { TakeX } from "./state";

// ---------------- 全局选择 ----------------

interface Choice {
  /** null = 默认预设（后端 default_preset） */
  preset: string | null;
  /** 面板上的完整参数（null = 就是预设值） */
  full: ImageParams | null;
}
let choice: Choice = { preset: null, full: null };
let presetsCache: ImagePresetsResp | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
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

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
function merge<T extends object>(base: T, over: Partial<T> | undefined): T {
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

export function useImagePresets(gpu: 0 | 3) {
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

// ---------------- 小控件 ----------------

function Num({ label, value, onChange, min, max, step, disabled, hint }: { label: string; value: number; onChange: (v: number) => void; min: number; max: number; step: number; disabled?: boolean; hint?: string }) {
  return (
    <label className={`px-row ${disabled ? "off" : ""}`} title={hint}>
      <span className="k">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
      <input className="n" type="number" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => e.target.value !== "" && onChange(Number(e.target.value))} />
    </label>
  );
}
function Seg<T extends string>({ value, opts, onChange }: { value: T; opts: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="v3e-seg sm px-seg">
      {opts.map(([v, t]) => (
        <button key={v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>
          {t}
        </button>
      ))}
    </div>
  );
}
function Sec({ title, on, onToggle, children, note }: { title: string; on?: boolean; onToggle?: (v: boolean) => void; children?: React.ReactNode; note?: string }) {
  return (
    <div className="px-sec">
      <div className="px-sh">
        {onToggle ? (
          <label className="px-tg">
            <input type="checkbox" checked={!!on} onChange={(e) => onToggle(e.target.checked)} />
            {title}
          </label>
        ) : (
          <b>{title}</b>
        )}
        {note && <small>{note}</small>}
      </div>
      {(on ?? true) && children}
    </div>
  );
}

const rng = (r: ImagePresetsResp, k: string, d: [number, number]): [number, number] => {
  const v = r.ranges[k];
  return Array.isArray(v) ? (v as [number, number]) : d;
};

// ---------------- 面板 ----------------

export function ImageParamsPanel({ gpu, mode = "regen" }: { gpu: 0 | 3; mode?: string }) {
  const { r, err, reload } = useImagePresets(gpu);
  const ch = useParamChoice();
  const [saveName, setSaveName] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const pid = r ? ch.preset ?? r.default_preset : null;
  const base = useMemo(() => (r ? presetFull(r, pid) : null), [r, pid]);
  if (err && !r) return <div className="v3e-note warn">{err}</div>;
  if (!r || !base) return <div className="v3e-note">读取出图参数…</div>;
  const p = ch.full ?? base;
  const preset = r.presets.find((x) => x.id === pid) as ImagePreset | undefined;
  const ov = overridesOf(p, base);
  const nChanged = Object.keys(ov).length;
  const set = (patch: Partial<ImageParams>) => setParamChoice({ full: { ...p, ...patch } });
  const turbo = p.unet === "turbo";
  const final = preset?.tier === "final";
  const loraNames = [r.identity, ...r.allowed.loras.filter((n) => !r.banned_loras.includes(n))];
  const loras = p.loras;
  const setLora = (i: number, row: Partial<LoraRow>) => set({ loras: (loras ?? []).map((x, j) => (j === i ? { ...x, ...row } : x)) });
  const sz = rng(r, "size", [256, 2048]);

  const save = async () => {
    if (!saveName?.trim()) return;
    try {
      const s = await apiV1.saveImagePreset({ label: saveName.trim(), params: overridesOf(p, r.defaults), tier: preset?.tier ?? "preview", base: pid ?? undefined });
      await reload();
      setParamChoice({ preset: s.id, full: null });
      setSaveName(null);
      setMsg(`已存为“${s.label}”`);
    } catch (e) {
      setMsg(errText(e));
    }
  };
  const del = async () => {
    if (!preset || preset.builtin) return;
    try {
      await apiV1.deleteImagePreset(preset.id);
      setParamChoice({ preset: null, full: null });
      await reload();
      setMsg(`已删除“${preset.label}”`);
    } catch (e) {
      setMsg(errText(e));
    }
  };

  return (
    <div className="px">
      <div className="px-top">
        <select
          className="px-preset"
          value={pid ?? ""}
          onChange={(e) => setParamChoice({ preset: e.target.value === r.default_preset ? null : e.target.value, full: null })}
        >
          <optgroup label="内置">
            {r.presets.filter((x) => x.builtin).map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}
                {x.id === r.default_preset ? "（默认）" : ""}
              </option>
            ))}
          </optgroup>
          {r.presets.some((x) => !x.builtin) && (
            <optgroup label="我的预设">
              {r.presets.filter((x) => !x.builtin).map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <span className={`px-badge ${nChanged ? "chg" : ""}`}>{nChanged ? `改了 ${nChanged} 项` : "= 预设"}</span>
      </div>
      {preset?.note && <div className="px-note">{preset.note}</div>}
      {final && mode !== "regen" && <div className="v3e-note warn">定稿档预设只能整张出；这次改图会用默认预设。</div>}

      <Sec title="模型">
        <Seg value={p.unet} opts={[["turbo", "Turbo（快）"], ["base", "Base（真 CFG）"]]} onChange={(v) => set({ unet: v })} />
        {turbo && (
          <div className="px-note" title={r.notes.turbo}>
            Turbo 用官方固定 8 步 sigma、cfg 1：步数 / cfg / 调度器 / shift 不生效（悬停看 sigma）
          </div>
        )}
        <Num label="步数" value={turbo ? 8 : p.steps} min={1} max={100} step={1} disabled={turbo} onChange={(v) => set({ steps: v })} />
        <Num label="cfg" value={turbo ? 1 : p.cfg} min={1} max={10} step={0.1} disabled={turbo} onChange={(v) => set({ cfg: v })} />
        <label className="px-row">
          <span className="k">采样器</span>
          <select value={p.sampler} onChange={(e) => set({ sampler: e.target.value })}>
            {r.allowed.samplers.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className={`px-row ${turbo ? "off" : ""}`}>
          <span className="k">调度器</span>
          <select value={p.scheduler} disabled={turbo} onChange={(e) => set({ scheduler: e.target.value })}>
            {r.allowed.schedulers.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className={`px-row ${turbo ? "off" : ""}`} title={r.notes.shift}>
          <span className="k">
            <input type="checkbox" checked={p.shift != null && !turbo} disabled={turbo} onChange={(e) => set({ shift: e.target.checked ? 3.1 : null })} />
            shift
          </span>
          {p.shift != null && !turbo ? (
            <>
              <input type="range" min={0.5} max={20} step={0.1} value={p.shift} onChange={(e) => set({ shift: Number(e.target.value) })} />
              <input className="n" type="number" min={0.5} max={20} step={0.1} value={p.shift} onChange={(e) => set({ shift: Number(e.target.value) })} />
            </>
          ) : (
            <small className="dim">不加（现状）</small>
          )}
        </label>
        <label className="px-row">
          <span className="k">VAE</span>
          <Seg value={p.vae} opts={[["plain", "普通"], ["texture_fix", "纹理修复"]]} onChange={(v) => set({ vae: v })} />
        </label>
      </Sec>

      <Sec title="LoRA" note={r.allowed.source === "unavailable" ? "ComfyUI 连不上，列表为空" : `ComfyUI ${r.allowed.source === "live" ? "实时" : "缓存"}列表 ${r.allowed.loras.length} 个`}>
        <label className="px-tg sm">
          <input type="checkbox" checked={loras == null} onChange={(e) => set({ loras: e.target.checked ? null : [{ name: r.identity, strength: 0.8 }] })} />
          按剧本自动（身份 LoRA）
        </label>
        {loras != null && (
          <div className="px-loras">
            {loras.map((l, i) => (
              <div key={i} className="px-lora">
                <select value={l.name} onChange={(e) => setLora(i, { name: e.target.value })} title={l.name}>
                  {!loraNames.includes(l.name) && <option value={l.name}>{l.name}（不在列表）</option>}
                  {loraNames.map((n) => (
                    <option key={n} value={n}>
                      {n === r.identity ? "本镜身份 LoRA（@identity）" : n.replace(/\.safetensors$/, "")}
                    </option>
                  ))}
                </select>
                <input type="range" min={-1} max={2} step={0.05} value={l.strength} onChange={(e) => setLora(i, { strength: Number(e.target.value) })} />
                <input className="n" type="number" min={-1} max={2} step={0.05} value={l.strength} onChange={(e) => setLora(i, { strength: Number(e.target.value) })} />
                <button className="v3e-x sm" aria-label="去掉" onClick={() => set({ loras: loras.filter((_, j) => j !== i) })}>
                  ×
                </button>
              </div>
            ))}
            <button className="v3e-link" disabled={loras.length >= 8} onClick={() => set({ loras: [...loras, { name: loraNames.find((n) => !loras.some((x) => x.name === n)) ?? r.identity, strength: 0.5 }] })}>
              + 加一个 LoRA
            </button>
          </div>
        )}
      </Sec>

      <Sec title="尺寸">
        <div className="px-two">
          <Num label="宽" value={p.width} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ width: v })} />
          <Num label="高" value={p.height} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ height: v })} />
        </div>
        <Num label="放大出图" value={p.render_scale} min={0.5} max={2} step={0.05} disabled={p.two_stage.enabled} hint={r.notes.render_scale} onChange={(v) => set({ render_scale: v })} />
      </Sec>

      <Sec title="两段式（放大 + 低重绘第二遍）" on={p.two_stage.enabled} onToggle={(v) => set({ two_stage: { ...p.two_stage, enabled: v }, ...(v ? { detail_pass: { ...p.detail_pass, enabled: false }, render_scale: 1 } : {}) })}>
        <div className="px-two">
          <Num label="第一遍宽" value={p.two_stage.first_size[0]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, first_size: [v, p.two_stage.first_size[1]] } })} />
          <Num label="第一遍高" value={p.two_stage.first_size[1]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, first_size: [p.two_stage.first_size[0], v] } })} />
          <Num label="放大宽" value={p.two_stage.upscale_size[0]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, upscale_size: [v, p.two_stage.upscale_size[1]] } })} />
          <Num label="放大高" value={p.two_stage.upscale_size[1]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, upscale_size: [p.two_stage.upscale_size[0], v] } })} />
        </div>
        <Num label="重绘" value={p.two_stage.denoise} min={0.05} max={0.8} step={0.01} onChange={(v) => set({ two_stage: { ...p.two_stage, denoise: v } })} />
        <Num label="步数" value={p.two_stage.steps} min={1} max={60} step={1} disabled={turbo} onChange={(v) => set({ two_stage: { ...p.two_stage, steps: v } })} />
      </Sec>

      <Sec title="细节重绘（放大低重绘再缩回）" on={p.detail_pass.enabled} note="锐度对比预留" onToggle={(v) => set({ detail_pass: { ...p.detail_pass, enabled: v }, ...(v ? { two_stage: { ...p.two_stage, enabled: false } } : {}) })}>
        <Num label="重绘" value={p.detail_pass.denoise} min={0.05} max={0.6} step={0.01} onChange={(v) => set({ detail_pass: { ...p.detail_pass, denoise: v } })} />
        <Num label="放大" value={p.detail_pass.scale} min={1} max={2} step={0.05} onChange={(v) => set({ detail_pass: { ...p.detail_pass, scale: v } })} />
      </Sec>

      <Sec title="锐化（USM 后处理）" on={p.sharpen.enabled} note="锐度对比预留" onToggle={(v) => set({ sharpen: { ...p.sharpen, enabled: v } })}>
        <Num label="半径" value={p.sharpen.radius} min={0.1} max={10} step={0.1} onChange={(v) => set({ sharpen: { ...p.sharpen, radius: v } })} />
        <Num label="强度" value={p.sharpen.amount} min={0} max={3} step={0.05} onChange={(v) => set({ sharpen: { ...p.sharpen, amount: v } })} />
      </Sec>

      <Sec title="其他">
        <label className="px-row" title={r.notes.strength}>
          <span className="k">
            <input type="checkbox" checked={p.strength != null} onChange={(e) => set({ strength: e.target.checked ? 0.55 : null })} />
            重绘幅度
          </span>
          {p.strength != null ? (
            <>
              <input type="range" min={0.05} max={1} step={0.01} value={p.strength} onChange={(e) => set({ strength: Number(e.target.value) })} />
              <input className="n" type="number" min={0.05} max={1} step={0.01} value={p.strength} onChange={(e) => set({ strength: Number(e.target.value) })} />
            </>
          ) : (
            <small className="dim">按 小 / 中 / 大</small>
          )}
        </label>
        <label className="px-row" title={r.notes.grade}>
          <span className="k">调色</span>
          <Seg
            value={p.grade.enabled == null ? "auto" : p.grade.enabled ? "on" : "off"}
            opts={[["auto", "按现状"], ["on", "开"], ["off", "关"]]}
            onChange={(v) => set({ grade: { ...p.grade, enabled: v === "auto" ? null : v === "on" } })}
          />
        </label>
        {p.grade.enabled && <Num label="调色强度" value={p.grade.strength} min={0} max={1} step={0.05} onChange={(v) => set({ grade: { ...p.grade, strength: v } })} />}
        <label className="px-tg sm" title={r.notes.spec_words}>
          <input type="checkbox" checked={p.spec_words} onChange={(e) => set({ spec_words: e.target.checked })} />
          追加系统规格词（镜头句 / 风格后缀 / 纠正器条目）
        </label>
        <label className="px-row">
          <span className="k">种子</span>
          <input className="n wide" inputMode="numeric" placeholder="随机" value={p.seed ?? ""} onChange={(e) => set({ seed: e.target.value.trim() === "" ? null : Number(e.target.value) })} />
        </label>
      </Sec>

      <div className="px-acts">
        <button className="v3e-btn sm" disabled={!nChanged} onClick={() => setParamChoice({ full: null })}>
          恢复预设值
        </button>
        {saveName == null ? (
          <button className="v3e-btn sm" onClick={() => setSaveName(preset && !preset.builtin ? preset.label : "")}>
            存为我的预设
          </button>
        ) : (
          <span className="px-save">
            <input autoFocus placeholder="预设名" value={saveName} onChange={(e) => setSaveName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void save()} />
            <button className="v3e-btn sm primary" disabled={!saveName.trim()} onClick={() => void save()}>
              存
            </button>
            <button className="v3e-btn sm" onClick={() => setSaveName(null)}>
              取消
            </button>
          </span>
        )}
        {preset && !preset.builtin && (
          <button className="v3e-btn sm" onClick={() => void del()}>
            删除这个预设
          </button>
        )}
      </div>
      {msg && <div className="px-note">{msg}</div>}
      <div className="px-note">下一次出图（右栏 / 修改诉求 / 中区按钮）都用这里的参数；每一版都记下实际参数，可在「版本」里对比。</div>
    </div>
  );
}

// ---------------- 版本参数（对比上一版，改了的高亮） ----------------

type Eff = NonNullable<NonNullable<TakeX["params"]>["effective"]>;
const f2 = (n: number | null | undefined) => (n == null ? "—" : String(Math.round(n * 100) / 100));
const sizeOf = (w?: number | null, h?: number | null) => (w && h ? `${w}×${h}` : "—");
export const PARAM_ROWS: [string, (e: Eff) => string][] = [
  ["模型", (e) => (e.unet === "turbo" ? "Turbo" : e.unet === "base" ? "Base" : "—") + (e.tier === "final" ? " · 定稿档" : "")],
  ["步数", (e) => (e.unet === "turbo" ? "8（官方 sigma）" : String(e.steps ?? "—"))],
  ["cfg", (e) => f2(e.cfg)],
  ["采样 / 调度", (e) => `${e.sampler ?? "—"} / ${e.unet === "turbo" ? "固定 sigma" : e.scheduler ?? "—"}`],
  ["shift", (e) => (e.shift == null ? "—" : f2(e.shift))],
  ["VAE", (e) => (e.vae === "texture_fix" ? "纹理修复" : e.vae === "plain" ? "普通" : String(e.vae ?? "—"))],
  ["LoRA", (e) => (e.loras?.length ? e.loras.map((l) => `${l.name.replace(/\.safetensors$/, "").replace(/_qwen21$/, "")} ${f2(l.strength)}`).join("，") : "无")],
  ["尺寸", (e) => sizeOf(e.width, e.height) + (e.rendered_size ? `（出图 ${sizeOf(e.rendered_size[0], e.rendered_size[1])}）` : "")],
  ["两段式", (e) => (e.two_stage?.enabled ? `${sizeOf(...(e.two_stage.first_size ?? [0, 0]))} → ${sizeOf(...(e.two_stage.upscale_size ?? [0, 0]))} · ${f2(e.two_stage.denoise)}` : "关")],
  ["细节重绘", (e) => (e.detail_pass?.enabled ? `×${f2(e.detail_pass.scale)} · ${f2(e.detail_pass.denoise)}` : "关")],
  ["重绘幅度", (e) => f2(e.strength)],
  ["调色", (e) => (e.grade?.enabled ? `开 ${f2(e.grade.strength)}` : "关")],
  ["锐化", (e) => (e.sharpen?.enabled ? `r${f2(e.sharpen.radius)} · ${f2(e.sharpen.amount)}` : "关")],
  ["规格词", (e) => (e.spec_words === false ? "去掉" : "带")],
  ["种子", (e) => String(e.seed ?? "—")],
];

export function TakeParams({ t, parent }: { t: TakeX; parent?: TakeX | null }) {
  const e = t.params?.effective;
  if (!e) return <div className="v3e-ro small">这一版出图时还没记录参数（PX 之前的版本）</div>;
  const pe = parent?.params?.effective ?? null;
  const preset = t.params?.preset;
  const nChg = pe ? PARAM_ROWS.filter(([k, fn]) => k !== "种子" && fn(e) !== fn(pe)).length : 0;
  return (
    <div className="px-tp">
      <div className="px-tph">
        {preset ? <span className="v3e-chip">{preset}</span> : null}
        {pe ? <small>{nChg ? `和 #${parent!.n} 比改了 ${nChg} 项（高亮）` : `和 #${parent!.n} 参数相同`}</small> : <small>没有上一版可比</small>}
      </div>
      <dl className="px-kv">
        {PARAM_ROWS.map(([k, fn]) => {
          const v = fn(e);
          const pv = pe ? fn(pe) : null;
          const chg = pv != null && pv !== v;
          return (
            <div key={k} className={chg ? "chg" : ""}>
              <dt>{k}</dt>
              <dd title={chg ? `上一版：${pv}` : undefined}>
                {v}
                {chg && <s>{pv}</s>}
              </dd>
            </div>
          );
        })}
      </dl>
      {e.note && <div className="px-note">{e.note}</div>}
    </div>
  );
}
