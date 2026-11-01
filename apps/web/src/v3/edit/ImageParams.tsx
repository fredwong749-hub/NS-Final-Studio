// fredw-92/PX：出图参数面板（预设 + 每次覆盖）+ 版本参数对比。
// 选择是全局的“下一次出图用的参数”：右栏「高级」和「修改诉求」弹窗共用；submitFrame 自动带上（没改 = 不带，后端用默认预设）。
import { useEffect, useMemo, useState } from "react";
import { apiV1, errText, type ImageParams, type ImagePreset, type ImagePresetsResp, type LoraRow } from "../api_v1";
import type { TakeX } from "./state";
import { PARAM_ROWS, overridesOf, presetFull, setParamChoice, useImagePresets, useParamChoice, noteShort } from "./ImageParams.helpers";

// ---------------- 全局选择 ----------------

// ---------------- 小控件 ----------------

function Num({ label, value, onChange, min, max, step, disabled, hint, slim }: { label: string; value: number; onChange: (v: number) => void; min: number; max: number; step: number; disabled?: boolean; hint?: string; slim?: boolean }) {
  return (
    <label className={`px-row ${disabled ? "off" : ""} ${slim ? "slim" : ""}`} title={hint}>
      <span className="k">{label}</span>
      {!slim && <input type="range" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />}
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

// ---------------------------------------------------------------- 出图 / 视频 LoRA 区分（UXF5，审查 N12 / #27）
let videoLoraCache: Promise<Set<string>> | null = null;
/** 配置里登记的视频 LoRA 文件名：GET /api/video-bases（每个基底的 lora）+ GET /api/video-loras（附加视频 LoRA） */
function loadVideoLoraNames(): Promise<Set<string>> {
  if (!videoLoraCache)
    videoLoraCache = Promise.all([apiV1.videoBases().catch(() => null), apiV1.videoLoras().catch(() => null)]).then(([b, l]) => {
      const out = new Set<string>();
      for (const x of b?.bases ?? []) {
        const lo = (x as unknown as { lora?: string | null }).lora;
        if (lo) out.add(lo);
      }
      for (const x of l?.loras ?? []) if (x.name) out.add(x.name);
      return out;
    });
  return videoLoraCache;
}
function useVideoLoraNames(): Set<string> {
  const [v, setV] = useState<Set<string>>(new Set());
  useEffect(() => {
    let alive = true;
    void loadVideoLoraNames().then((x) => alive && setV(x));
    return () => {
      alive = false;
    };
  }, []);
  return v;
}
/** 视频模型（MiniMax H3 / Pika）LoRA 的命名特征；配置里没登记的也能认出来 */
const VIDEO_NAME = /minimax|(^|[^a-z])(mm)?h3([^a-z0-9]|$)|i2v|t2v|r2v|fl2v|flf2v|camera_motion|motion_repair|pika/i;
/** 训练中间检查点：放在 *_ckpts/ 目录里，或文件名以 6 位以上步数结尾 */
const CKPT_NAME = /(^|\/)[^/]*ckpts?\/|_\d{6,}\.safetensors$/i;
function imageLoraFilter(r: ImagePresetsResp, video: Set<string>): (n: string) => boolean {
  const keep = new Set<string>([r.identity, ...((r as { identity_loras?: string[] }).identity_loras ?? []), ...(((r as { realism_loras?: [string, number][] }).realism_loras ?? []).map((x) => x[0]))]);
  return (n) => keep.has(n) || !(video.has(n) || VIDEO_NAME.test(n) || CKPT_NAME.test(n));
}

export function ImageParamsPanel({ gpu, mode = "regen" }: { gpu: number | string; mode?: string }) {
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
  const videoL = useVideoLoraNames();
  // UXF5（审查 N12 / #27）：出图 LoRA 列表只列出图用的——去掉视频 LoRA（config 里的视频基底 / 附加视频 LoRA + 视频模型命名）和训练中间检查点
  const imageOk = imageLoraFilter(r, videoL);
  const allImage = r.allowed.loras.filter(imageOk);
  const loraNames = [r.identity, ...allImage.filter((n) => !r.banned_loras.includes(n))];
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
      {/* UXF2 #27：说明只写一句，细节折叠（原文不改） */}
      {preset?.note && (
        <details className="px-note px-notefold">
          <summary>{noteShort(preset.note)}</summary>
          {preset.note}
        </details>
      )}
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

      <Sec title="LoRA" note={r.allowed.source === "unavailable" ? "出图卡连不上，列表为空" : `出图可选 ${allImage.length} 个（视频 LoRA、训练检查点不列）`}>
        <label className="px-tg sm">
          <input type="checkbox" checked={loras == null} onChange={(e) => set({ loras: e.target.checked ? null : [{ name: r.identity, strength: 0.8 }] })} />
          按剧本自动（身份 LoRA）
        </label>
        {loras != null && (
          <div className="px-loras">
            {loras.map((l, i) => (
              <div key={i} className="px-lora">
                <select className="px-lora-sel" value={l.name} onChange={(e) => setLora(i, { name: e.target.value })} title={l.name}>
                  {!loraNames.includes(l.name) && <option value={l.name}>{l.name}（不在列表）</option>}
                  {loraNames.map((n) => (
                    <option key={n} value={n}>
                      {n === r.identity ? "本镜身份" : n.replace(/\.safetensors$/, "")}
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
          <Num label="宽" slim value={p.width} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ width: v })} />
          <Num label="高" slim value={p.height} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ height: v })} />
        </div>
        <Num label="放大出图" value={p.render_scale} min={0.5} max={2} step={0.05} disabled={p.two_stage.enabled} hint={r.notes.render_scale} onChange={(v) => set({ render_scale: v })} />
      </Sec>

      <Sec title="两段式（放大 + 低重绘第二遍）" on={p.two_stage.enabled} onToggle={(v) => set({ two_stage: { ...p.two_stage, enabled: v }, ...(v ? { detail_pass: { ...p.detail_pass, enabled: false }, render_scale: 1 } : {}) })}>
        <div className="px-two">
          <Num label="第一遍宽" slim value={p.two_stage.first_size[0]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, first_size: [v, p.two_stage.first_size[1]] } })} />
          <Num label="第一遍高" slim value={p.two_stage.first_size[1]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, first_size: [p.two_stage.first_size[0], v] } })} />
          <Num label="放大宽" slim value={p.two_stage.upscale_size[0]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, upscale_size: [v, p.two_stage.upscale_size[1]] } })} />
          <Num label="放大高" slim value={p.two_stage.upscale_size[1]} min={sz[0]} max={sz[1]} step={16} onChange={(v) => set({ two_stage: { ...p.two_stage, upscale_size: [p.two_stage.upscale_size[0], v] } })} />
        </div>
        <Num label="重绘" value={p.two_stage.denoise} min={0.05} max={0.8} step={0.01} onChange={(v) => set({ two_stage: { ...p.two_stage, denoise: v } })} />
        <Num label="步数" value={p.two_stage.steps} min={1} max={60} step={1} disabled={turbo} onChange={(v) => set({ two_stage: { ...p.two_stage, steps: v } })} />
      </Sec>

      <Sec title="细节重绘（放大低重绘再缩回）" on={p.detail_pass.enabled} note="锐度对比预留" onToggle={(v) => set({ detail_pass: { ...p.detail_pass, enabled: v }, ...(v ? { two_stage: { ...p.two_stage, enabled: false } } : {}) })}>
        <Num label="重绘" value={p.detail_pass.denoise} min={0.05} max={0.6} step={0.01} onChange={(v) => set({ detail_pass: { ...p.detail_pass, denoise: v } })} />
        <Num label="放大" value={p.detail_pass.scale} min={1} max={2} step={0.05} onChange={(v) => set({ detail_pass: { ...p.detail_pass, scale: v } })} />
      </Sec>

      <Sec title="锐化（USM 后处理）" on={p.sharpen.enabled} onToggle={(v) => set({ sharpen: { ...p.sharpen, enabled: v } })}>
        <Num label="半径" value={p.sharpen.radius} min={0.1} max={10} step={0.1} onChange={(v) => set({ sharpen: { ...p.sharpen, radius: v } })} />
        <Num label="强度" value={p.sharpen.amount} min={0} max={3} step={0.05} onChange={(v) => set({ sharpen: { ...p.sharpen, amount: v } })} />
        <Num label="阈值" value={p.sharpen.threshold ?? 0} min={0} max={255} step={1} onChange={(v) => set({ sharpen: { ...p.sharpen, threshold: Math.round(v) } })} />
      </Sec>

      {/* LCA：风格后缀 = 项目方选定的写作模型原文，只能开 / 关，不能改字 */}
      {(() => {
        const suf = base.style_suffix || presetFull(r, r.default_preset).style_suffix || "";
        if (!suf) return null;
        return (
          <Sec title="风格后缀（原样接在提示词末尾）" on={!!p.style_suffix} onToggle={(v) => set({ style_suffix: v ? suf : "" })}>
            <div className="px-note" title={r.notes.style_suffix}>
              ，{p.style_suffix || suf}
            </div>
          </Sec>
        );
      })()}

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

// ---------------- fredw-92/UXF2：项目出图设置（默认预设名 + 定稿后是否自动出定稿档），按 render_quality.json 实际值显示 ----------------

