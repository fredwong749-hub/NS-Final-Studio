// fredw-92/W4c：模型选择的共用部件（canvas-ui-spec-v3-merge §8.2）。
//   useProviders()      读 /api/llm/providers（404 → 后端未就绪）
//   <LlmFields/>        服务商 + 模型 + 参数 + key 状态 + 费用档（剧本创作页的模型设置块也用它）
//   <LlmOverride/>      每处 ⚙：点开只改这一次，或“记为此处默认”（存本机浏览器，按 where 区分）
//   useLlmOverride(where) 取 / 存“此处默认”
// 只收发配置，不回显密钥。
import { useEffect, useRef, useState } from "react";
import { PURPOSE_LABEL, type LlmChoice, type Provider } from "../api_v1_pages";
import { loadAt, purposeDefault, saveAt, useProviders } from "./LlmOverride.helpers";
import "./pages.css";

export function KeyBadge({ p }: { p: Provider | undefined | null }) {
  if (!p) return null;
  return <span className={`v3p-badge ${p.has_key ? "ok" : "warn"}`}>{p.has_key ? "key 已配置" : "缺 key"}</span>;
}

export function LlmFields({
  providers,
  value,
  onChange,
  compact,
}: {
  providers: Provider[];
  value: LlmChoice | null;
  onChange: (v: LlmChoice) => void;
  compact?: boolean;
}) {
  const pv = providers.find((p) => p.id === value?.provider) ?? null;
  const params = value?.params ?? pv?.params ?? {};
  const set = (patch: Partial<LlmChoice>) => {
    const base: LlmChoice = value ?? { provider: pv?.id ?? providers[0]?.id ?? "", model: pv?.default_model ?? "" };
    onChange({ ...base, ...patch });
  };
  const setParam = (k: keyof NonNullable<LlmChoice["params"]>, v: number | boolean | null) => set({ params: { ...params, [k]: v } });
  const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));
  return (
    <div className={`v3p-llm${compact ? " compact" : ""}`}>
      <label className="v3p-f">
        <span>服务商</span>
        <select
          value={value?.provider ?? ""}
          onChange={(ev) => {
            const np = providers.find((p) => p.id === ev.target.value);
            if (np) onChange({ provider: np.id, model: np.default_model || np.models[0] || "", params: { ...np.params } });
          }}
        >
          {!value && <option value="">（选择）</option>}
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name || p.id}
              {p.has_key ? "" : "（缺 key）"}
            </option>
          ))}
        </select>
      </label>
      <label className="v3p-f">
        <span>模型</span>
        <select value={value?.model ?? ""} onChange={(ev) => set({ model: ev.target.value })} disabled={!pv}>
          {pv && !pv.models.includes(value?.model ?? "") && value?.model && <option value={value.model}>{value.model}</option>}
          {pv?.models.map((m) => (
            <option key={m} value={m}>
              {m}
              {m === pv.default_model ? "（默认）" : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="v3p-f narrow">
        <span>温度</span>
        <input type="number" step="0.05" min={0} max={2} value={params.temperature ?? ""} onChange={(ev) => setParam("temperature", num(ev.target.value))} />
      </label>
      <label className="v3p-f narrow">
        <span>最大输出</span>
        <input type="number" step="256" min={1} value={params.max_tokens ?? ""} onChange={(ev) => setParam("max_tokens", num(ev.target.value))} />
      </label>
      <label className="v3p-f check">
        <input type="checkbox" checked={!!params.reasoning} onChange={(ev) => setParam("reasoning", ev.target.checked)} />
        <span>开推理</span>
      </label>
      <div className="v3p-llm-meta">
        <KeyBadge p={pv} />
        <span className="v3p-muted">费用档：<span title={pv?.estimate?.label}>{pv?.estimate?.tier || "未知"}</span></span>
        {pv && <span className="v3p-muted mono" title="经 GPU3 上的文本网关转发">{pv.base_url}</span>}
      </div>
    </div>
  );
}

/** ⚙ 就地覆盖。value=null 表示跟随用途默认；onChange 只影响这一次调用（除非点“记为此处默认”）。 */
export function LlmOverride({
  purpose,
  where,
  value,
  onChange,
  align = "right",
}: {
  purpose: string;
  /** 此处的唯一名，如 "canvas.boost"；“记为此处默认”按它存 */
  where: string;
  value: LlmChoice | null;
  onChange: (v: LlmChoice | null) => void;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const { data, err, notReady } = useProviders();
  const [draft, setDraft] = useState<LlmChoice | null>(value);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) setDraft(value ?? purposeDefault(data, purpose));
  }, [open, value, data, purpose]);
  useEffect(() => {
    if (!open) return;
    const on = (ev: MouseEvent) => {
      if (box.current && !box.current.contains(ev.target as Node)) setOpen(false);
    };
    const key = (ev: KeyboardEvent) => ev.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", on);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", on);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  const def = purposeDefault(data, purpose);
  const saved = loadAt(where);
  return (
    <div className="v3p-ovr" ref={box}>
      <button
        type="button"
        className={`v3p-gear${value ? " on" : ""}`}
        onClick={() => setOpen(!open)}
        title={`模型设置（${PURPOSE_LABEL[purpose] ?? purpose}）：${value ? `本次用 ${value.provider} / ${value.model}` : def ? `默认 ${def.provider} / ${def.model}` : "跟随默认"}`}
        aria-expanded={open}
      >
        ⚙{value ? <span className="v3p-gear-lbl">{value.model}</span> : null}
      </button>
      {open && (
        <div className={`v3p-pop ${align}`} role="dialog" aria-label="模型设置">
          <div className="v3p-pop-head">
            <b>模型设置 · {PURPOSE_LABEL[purpose] ?? purpose}</b>
            <span className="v3p-muted">默认：{def ? `${def.provider} / ${def.model}` : "—"}</span>
          </div>
          {notReady ? (
            <p className="v3p-notready">后端未就绪：/api/llm/providers 还没上线，暂用后端默认模型。</p>
          ) : err ? (
            <p className="v3p-err">{err}</p>
          ) : !data ? (
            <p className="v3p-muted">加载中…</p>
          ) : (
            <LlmFields providers={data.providers} value={draft} onChange={setDraft} compact />
          )}
          <div className="v3p-pop-act">
            <button type="button" className="btn-mini" onClick={() => { onChange(null); setOpen(false); }} disabled={!value}>
              跟随默认
            </button>
            {saved && (
              <button type="button" className="btn-mini" onClick={() => { saveAt(where, null); onChange(null); setOpen(false); }} title="清掉本机记住的此处默认">
                清除此处默认
              </button>
            )}
            <span className="grow" />
            <button type="button" className="btn-mini" disabled={!draft} onClick={() => { saveAt(where, draft); onChange(draft); setOpen(false); }} title="记在本机浏览器，下次这里默认用它">
              记为此处默认
            </button>
            <button type="button" className="btn primary" disabled={!draft} onClick={() => { onChange(draft); setOpen(false); }}>
              只这一次
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
