// fredw-92/W4c：模型与 API 配置页（#/models，工具菜单；canvas-ui-spec-v3-merge §8.2，api_v1_contract §A）。
// 服务商清单可改（base_url、模型、默认、超时、参数）；密钥只写不读（接口只回 has_key）；测试连接；按用途默认；
// 图像 / 视频端点与连通状态。每处 ⚙ 覆盖用 <LlmOverride/>（从本文件或 ./LlmOverride 导入）。
import { useEffect, useState } from "react";
import {
  errText,
  isNotReady,
  llmApi,
  PURPOSE_LABEL,
  type LlmParams,
  type Provider,
  type ProviderPatch,
  type Purpose,
  type RenderEndpoint,
} from "../api_v1_pages";
import { KeyBadge, useProviders } from "./LlmOverride";
import "./pages.css";

export { LlmOverride, LlmFields, useLlmOverride, useProviders } from "./LlmOverride";

const PURPOSE_ORDER = ["script_write", "script_repair", "director_boost", "lora_llm", "prompt_rewrite"];
const EP_LABEL: Record<string, string> = { image: "图像（Image 2.1 / ComfyUI）", video: "视频（H3）" };

export default function ModelsPage() {
  const prov = useProviders();
  return (
    <div className="v3p-page v3p-models">
      <header className="v3p-head">
        <h1>模型与 API 配置</h1>
        <span className="v3p-muted">
          服务商清单存 config/llm_providers.json（不含密钥）；密钥只写进 config/llm_providers.local.json，页面只显示“已配置 / 未配置”。
        </span>
      </header>

      <section className="v3p-card">
        <div className="v3p-card-head">
          <h2>服务商</h2>
          <span className="grow" />
          <span className="v3p-muted">文本模型 · 经 GPU3 上的文本网关转发</span>
          <button className="btn-mini" onClick={() => void prov.reload()}>刷新</button>
        </div>
        {prov.notReady ? (
          <NotReady what="/api/llm/providers" />
        ) : prov.err ? (
          <p className="v3p-err">{prov.err}</p>
        ) : !prov.data ? (
          <p className="v3p-muted">加载中…</p>
        ) : prov.data.providers.length === 0 ? (
          <p className="v3p-muted">清单是空的。</p>
        ) : (
          <div className="v3p-prov-grid">
            {prov.data.providers.map((p) => (
              <ProviderCard
                key={p.id}
                p={p}
                onSaved={(np) => prov.setData((d) => (d ? { ...d, providers: d.providers.map((x) => (x.id === np.id ? np : x)) } : d))}
                reload={prov.reload}
              />
            ))}
          </div>
        )}
      </section>

      <section className="v3p-card">
        <div className="v3p-card-head">
          <h2>按用途的默认</h2>
          <span className="grow" />
          <span className="v3p-muted">每个用途一行；画布里每个 ⚙ 可以只改一次或记为此处默认</span>
        </div>
        {prov.notReady ? (
          <NotReady what="/api/llm/purposes" />
        ) : prov.data ? (
          <PurposesTable providers={prov.data.providers} purposes={prov.data.purposes} onSaved={(pp) => prov.setData((d) => (d ? { ...d, purposes: d.purposes.map((x) => (x.id === pp.id ? pp : x)) } : d))} />
        ) : null}
      </section>

      <EndpointsCard />
    </div>
  );
}

function NotReady({ what }: { what: string }) {
  return (
    <div className="v3p-notready">
      <b>后端未就绪</b>：{what} 还没上线（W1 实现中）。上线后这里自动可用，刷新即可。
    </div>
  );
}

function ProviderCard({ p, onSaved, reload }: { p: Provider; onSaved: (p: Provider) => void; reload: () => Promise<void> }) {
  const [f, setF] = useState(() => toForm(p));
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setF(toForm(p)), [p]);
  const models = f.models.split(/[\n,，]/).map((s) => s.trim()).filter(Boolean);
  const dirty = JSON.stringify(f) !== JSON.stringify(toForm(p));

  async function save(patch: ProviderPatch, okText: string) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await llmApi.putProvider(p.id, patch);
      if (r && typeof r === "object" && "id" in r) onSaved(r as Provider);
      else await reload();
      setMsg({ ok: true, text: okText });
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(false);
    }
  }
  async function runTest() {
    setTest({ ok: true, text: "测试中…" });
    try {
      const r = await llmApi.test(p.id);
      setTest({ ok: r.ok, text: `${r.ok ? "连通" : "失败"}${r.latency_ms != null ? ` · ${Math.round(r.latency_ms)} ms` : ""}${r.detail ? ` · ${r.detail}` : ""}` });
    } catch (e) {
      setTest({ ok: false, text: isNotReady(e) ? "后端未就绪（测试接口还没上线）" : errText(e) });
    }
  }
  const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));

  return (
    <div className="v3p-prov">
      <div className="v3p-prov-head">
        <input className="v3p-prov-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="名称" />
        <span className="v3p-muted mono">{p.id}</span>
        <span className="grow" />
        <KeyBadge p={p} />
      </div>
      <div className="v3p-kv">
        <label>base_url</label>
        <input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder="按官方文档填写" spellCheck={false} />
        <label>模型</label>
        <input value={f.models} onChange={(e) => setF({ ...f, models: e.target.value })} placeholder="按官方文档填写，逗号分隔" spellCheck={false} />
        <label>默认模型</label>
        <select value={f.default_model} onChange={(e) => setF({ ...f, default_model: e.target.value })}>
          {!models.includes(f.default_model) && <option value={f.default_model}>{f.default_model || "（未选）"}</option>}
          {models.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <label>超时（秒）</label>
        <input type="number" min={1} value={f.timeout_s} onChange={(e) => setF({ ...f, timeout_s: e.target.value })} />
        <label>参数</label>
        <div className="v3p-inline">
          <span className="v3p-muted">温度</span>
          <input type="number" step="0.05" min={0} max={2} value={f.temperature} onChange={(e) => setF({ ...f, temperature: e.target.value })} />
          <span className="v3p-muted">最大输出</span>
          <input type="number" step="256" min={1} value={f.max_tokens} onChange={(e) => setF({ ...f, max_tokens: e.target.value })} />
          <label className="v3p-check">
            <input type="checkbox" checked={f.reasoning} onChange={(e) => setF({ ...f, reasoning: e.target.checked })} />
            推理
          </label>
        </div>
        <label>密钥</label>
        <form
          className="v3p-inline"
          onSubmit={(e) => {
            e.preventDefault();
            if (key.trim()) void save({ api_key: key.trim() }, "密钥已保存（不回显）").then(() => setKey(""));
          }}
        >
          <input
            type="password"
            autoComplete="new-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={p.has_key ? "已配置（不回显）· 输入新值可覆盖" : "未配置 · 只写不读"}
          />
          <button className="btn-mini" type="submit" disabled={!key.trim() || busy}>保存</button>
        </form>
        <label>费用档</label>
        <span title={p.estimate?.label}>{p.estimate?.label || p.estimate?.tier || <span className="v3p-muted">未知</span>}</span>
      </div>
      <div className="v3p-prov-foot">
        <button className="btn-mini" onClick={() => void runTest()}>测试连接</button>
        {test && <span className={test.ok ? "v3p-okline" : "v3p-errline"}><span className={`v3p-dot ${test.ok ? "ok" : "bad"}`} /> {test.text}</span>}
        <span className="grow" />
        {dirty && <button className="btn-mini" onClick={() => setF(toForm(p))}>撤销</button>}
        <button
          className="btn primary"
          disabled={!dirty || busy}
          onClick={() =>
            void save(
              {
                name: f.name,
                base_url: f.base_url.trim(),
                models,
                default_model: f.default_model,
                timeout_s: num(f.timeout_s) ?? p.timeout_s,
                params: { temperature: num(f.temperature), max_tokens: num(f.max_tokens), reasoning: f.reasoning } as LlmParams,
              },
              "已保存",
            )
          }
        >
          保存
        </button>
      </div>
      {msg && <p className={msg.ok ? "v3p-okline" : "v3p-err"}>{msg.text}</p>}
    </div>
  );
}

function toForm(p: Provider) {
  return {
    name: p.name ?? "",
    base_url: p.base_url ?? "",
    models: (p.models ?? []).join(", "),
    default_model: p.default_model ?? "",
    timeout_s: p.timeout_s == null ? "" : String(p.timeout_s),
    temperature: p.params?.temperature == null ? "" : String(p.params.temperature),
    max_tokens: p.params?.max_tokens == null ? "" : String(p.params.max_tokens),
    reasoning: !!p.params?.reasoning,
  };
}

function PurposesTable({ providers, purposes, onSaved }: { providers: Provider[]; purposes: Purpose[]; onSaved: (p: Purpose) => void }) {
  const [msg, setMsg] = useState<Record<string, { ok: boolean; text: string }>>({});
  const rank = (id: string) => (PURPOSE_ORDER.includes(id) ? PURPOSE_ORDER.indexOf(id) : 99);
  const rows = [...purposes].sort((a, b) => rank(a.id) - rank(b.id));
  async function put(pp: Purpose, provider: string, model: string) {
    setMsg((m) => ({ ...m, [pp.id]: { ok: true, text: "保存中…" } }));
    try {
      const r = await llmApi.putPurpose(pp.id, { provider, model });
      onSaved(r && typeof r === "object" && "id" in r ? (r as Purpose) : { ...pp, provider, model });
      setMsg((m) => ({ ...m, [pp.id]: { ok: true, text: "已保存" } }));
    } catch (e) {
      setMsg((m) => ({ ...m, [pp.id]: { ok: false, text: errText(e) } }));
    }
  }
  return (
    <table className="v3p-table">
      <thead>
        <tr>
          <th>用途</th>
          <th>服务商</th>
          <th>模型</th>
          <th>key</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((pp) => {
          const pv = providers.find((x) => x.id === pp.provider);
          const m = msg[pp.id];
          return (
            <tr key={pp.id}>
              <td>{pp.label || PURPOSE_LABEL[pp.id] || pp.id}</td>
              <td>
                <select
                  value={pp.provider}
                  onChange={(e) => {
                    const np = providers.find((x) => x.id === e.target.value);
                    if (np) void put(pp, np.id, np.default_model || np.models[0] || "");
                  }}
                >
                  {!pv && <option value={pp.provider}>{pp.provider || "（未选）"}</option>}
                  {providers.map((x) => (
                    <option key={x.id} value={x.id}>{x.name || x.id}</option>
                  ))}
                </select>
              </td>
              <td>
                <select value={pp.model} onChange={(e) => void put(pp, pp.provider, e.target.value)} disabled={!pv}>
                  {pv && !pv.models.includes(pp.model) && <option value={pp.model}>{pp.model || "（未选）"}</option>}
                  {pv?.models.map((x) => (
                    <option key={x} value={x}>{x}</option>
                  ))}
                </select>
              </td>
              <td><KeyBadge p={pv} /></td>
              <td className={m ? (m.ok ? "v3p-okline" : "v3p-errline") : ""}>{m?.text}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function EndpointsCard() {
  const [eps, setEps] = useState<RenderEndpoint[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notReady, setNotReady] = useState(false);
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    try {
      setEps(await llmApi.endpoints());
      setErr(null);
      setNotReady(false);
    } catch (e) {
      setErr(errText(e));
      setNotReady(isNotReady(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  return (
    <section className="v3p-card">
      <div className="v3p-card-head">
        <h2>图像 / 视频端点</h2>
        <span className="grow" />
        <span className="v3p-muted">Image 2.1、H3 的地址与连通状态</span>
        <button className="btn-mini" disabled={busy} onClick={() => void load()}>{busy ? "检测中…" : "测试连接"}</button>
      </div>
      {notReady ? (
        <NotReady what="/api/render/endpoints" />
      ) : err ? (
        <p className="v3p-err">{err}</p>
      ) : !eps ? (
        <p className="v3p-muted">检测中…</p>
      ) : (
        <table className="v3p-table">
          <thead>
            <tr>
              <th>端点</th>
              <th>地址</th>
              <th>GPU</th>
              <th>连通</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {eps.map((e) => (
              <EndpointRow key={e.id} e={e} onSaved={(ne) => setEps((l) => l?.map((x) => (x.id === ne.id ? ne : x)) ?? null)} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function EndpointRow({ e, onSaved }: { e: RenderEndpoint; onSaved: (e: RenderEndpoint) => void }) {
  const [url, setUrl] = useState(e.url);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setUrl(e.url), [e.url]);
  async function save() {
    setMsg({ ok: true, text: "保存中…" });
    try {
      const r = await llmApi.putEndpoint(e.id, url.trim());
      onSaved(r && typeof r === "object" && "id" in r ? r : { ...e, url: url.trim() });
      setMsg({ ok: true, text: "已保存" });
    } catch (x) {
      setMsg({ ok: false, text: errText(x) });
    }
  }
  return (
    <tr>
      <td>{EP_LABEL[e.id] ?? e.id}</td>
      <td>
        <input className="mono v3p-url" value={url} onChange={(ev) => setUrl(ev.target.value)} spellCheck={false} />
      </td>
      <td className="mono">{e.gpu ?? "—"}</td>
      <td title={e.detail}>
        <span className={`v3p-dot ${e.reachable ? "ok" : "bad"}`} /> {e.reachable ? "连通" : "不通"}
        {e.detail && <span className="v3p-muted v3p-small"> · {e.detail}</span>}
      </td>
      <td>
        <button className="btn-mini" disabled={url.trim() === e.url} onClick={() => void save()}>保存</button>
        {msg && <span className={msg.ok ? "v3p-okline" : "v3p-errline"}> {msg.text}</span>}
      </td>
    </tr>
  );
}
