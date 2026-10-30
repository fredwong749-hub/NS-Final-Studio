// fredw-92/W4c：① 剧本创作页（#/script-create，canvas-ui-spec-v3-merge §8.1，api_v1_contract §B）。
// 提纲（项目方粘贴 / 上传）→ 模型设置（默认 = /api/llm/purposes 的 script_write）→ 流式写作（复用 /api/script-chat SSE）
// → 格式校验 → “送到剧本导入”（只登记候选，仍由项目方在导入页确认）；同一提纲可交给两个模型 → A/B 对比页。
// 系统只收发和校验格式：页面不预填、不生成、不改写任何剧本内容。
import { useEffect, useRef, useState } from "react";
import { capi, chatStream, type ChatConfig, type EpCheck, type Validation } from "../../chat/capi";
import { abIds, errText, isNotReady, scriptApi, type LlmChoice } from "../api_v1_pages";
import { KeyBadge, LlmFields, purposeDefault, useProviders } from "./LlmOverride";
import "./pages.css";

const RULES_FALLBACK = [{ id: "rules_v2", parts: [] as string[] }];
const pad = (n: number) => String(n).padStart(2, "0");

type Live = { content: string; reasoning: string; phase: string };

export default function ScriptCreatePage() {
  const prov = useProviders();
  const [legacy, setLegacy] = useState<ChatConfig | string | null>(null);
  const [outline, setOutline] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [epFrom, setEpFrom] = useState(1);
  const [epTo, setEpTo] = useState(1);
  const [shots, setShots] = useState<number | "">("");
  const [secs, setSecs] = useState<number | "">("");
  const [rulesList, setRulesList] = useState(RULES_FALLBACK);
  const [rules, setRules] = useState(RULES_FALLBACK[0].id);
  const [rulesDefault, setRulesDefault] = useState(RULES_FALLBACK[0].id);
  const [abRun, setAbRun] = useState<Record<"a" | "b", string>>({ a: "", b: "" });
  const [llm, setLlm] = useState<LlmChoice | null>(null);
  const [llmB, setLlmB] = useState<LlmChoice | null>(null);
  const [abOpen, setAbOpen] = useState(false);
  const [sid, setSid] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [out, setOut] = useState<{ content: string; reasoning: string } | null>(null);
  const [val, setVal] = useState<Validation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [inbox, setInbox] = useState<{ ok: boolean; text: string } | null>(null);
  const [ab, setAb] = useState<{ a: string | null; b: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [eps, setEps] = useState<Record<string, string> | null>(null);
  const [tab, setTab] = useState<string>("all");
  const abort = useRef<AbortController | null>(null);
  const abAbort = useRef<AbortController[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const outRef = useRef<HTMLPreElement>(null);

  // 默认模型 = 用途 script_write；后端未就绪时读旧写作对话框配置，只做展示
  useEffect(() => {
    if (prov.data && !llm) setLlm(purposeDefault(prov.data, "script_write"));
  }, [prov.data, llm]);
  useEffect(() => {
    if (prov.notReady) capi.config().then(setLegacy).catch((e) => setLegacy(`读不到（${errText(e)}），按后端默认`));
  }, [prov.notReady]);
  useEffect(() => {
    scriptApi
      .rules()
      .then((r) => {
        if (r.versions?.length) setRulesList(r.versions);
        if (r.default) {
          setRules(r.default);
          setRulesDefault(r.default);
        }
      })
      .catch(() => {});
  }, []);
  useEffect(
    () => () => {
      abort.current?.abort();
      abAbort.current.forEach((x) => x.abort());
    },
    [],
  );
  useEffect(() => {
    if (outRef.current) outRef.current.scrollTop = outRef.current.scrollHeight;
  }, [live?.content.length]);

  const range: [number, number] = [Math.min(epFrom, epTo), Math.max(epFrom, epTo)];
  // F2：发送前先估费用（POST /api/script-chat/estimate，不发写作请求、不花钱），提纲 / 模型变了 0.8 s 后重估
  const [est, setEst] = useState<{ text: string; tier?: string } | null>(null);
  useEffect(() => {
    if (!outline.trim()) return setEst(null);
    let dead = false;
    const t = window.setTimeout(() => {
      scriptApi
        .estimate({ outline, episodes: range, shots_per_ep: shots === "" ? undefined : shots, seconds_per_shot: secs === "" ? undefined : secs, rules, llm: llm ?? undefined })
        .then(
          (r) => !dead && setEst({ text: r.label || r.tier, tier: r.tier }),
          (e) => !dead && setEst({ text: `估不出（${errText(e)}）` }),
        );
    }, 800);
    return () => {
      dead = true;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outline, range[0], range[1], shots, secs, rules, llm]);
  const canWrite = !!outline.trim() && !live && !busy;

  async function onFile(f: File | undefined) {
    if (!f) return;
    try {
      setOutline(await f.text());
      setFileName(f.name);
    } catch (e) {
      setErr(`读取文件失败：${errText(e)}`);
    }
  }

  async function write() {
    if (!canWrite) return;
    setErr(null);
    setNote(null);
    setInbox(null);
    setVal(null);
    setOut(null);
    setEps(null);
    setTab("all");
    let id: string;
    try {
      const s = await scriptApi.create({
        title: fileName ?? undefined,
        outline,
        episodes: range,
        shots_per_ep: shots === "" ? undefined : shots,
        seconds_per_shot: secs === "" ? undefined : secs,
        rules,
        llm,
      });
      id = s.id;
      setSid(id);
    } catch (e) {
      setErr(`新建写作会话失败：${errText(e)}`);
      return;
    }
    const ac = new AbortController();
    abort.current = ac;
    let acc: Live = { content: "", reasoning: "", phase: "连接模型" };
    setLive(acc);
    let ended = false;
    const up = (p: Partial<Live>) => {
      acc = { ...acc, ...p };
      setLive(acc);
    };
    try {
      // 提纲已随新建会话交给后端（pending 首条请求 = 提纲原文 + 目标），这里 content 留空即发送它，不重复发提纲
      await chatStream(
        id,
        "",
        (ev) => {
          if (ev.t === "start") up({ phase: `${ev.model} 思考中` });
          else if (ev.t === "reasoning") up({ reasoning: acc.reasoning + ev.d, phase: "思考中" });
          else if (ev.t === "content") up({ content: acc.content + ev.d, phase: "写作中" });
          else if (ev.t === "progress") up({ phase: ev.d });
          else if (ev.t === "validating") up({ phase: "格式校验中" });
          else if (ev.t === "warn") setNote(ev.d);
          else if (ev.t === "error") {
            ended = true;
            setErr(ev.d);
          } else if (ev.t === "done") {
            ended = true;
            setVal(ev.validation);
          }
        },
        ac.signal,
        llm ? { llm } : undefined,
      );
      if (!ended && !ac.signal.aborted) setErr("连接中断：没有收到完成信号；已收到的部分已存档，可以去写作对话框里发“继续”");
    } catch (e) {
      setErr(ac.signal.aborted ? "已停止；已收到的部分已存档" : `写作失败：${errText(e)}`);
    } finally {
      abort.current = null;
      setOut({ content: acc.content, reasoning: acc.reasoning });
      setLive(null);
      capi
        .session(id)
        .then((s) => {
          if (s.validation) setVal(s.validation);
          setEps(Object.keys(s.episodes ?? {}).length ? s.episodes : null);
        })
        .catch(() => {});
    }
  }

  async function revalidate() {
    if (!sid) return;
    setBusy(true);
    try {
      setVal(await capi.validate(sid));
    } catch (e) {
      setErr(`校验失败：${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function toInbox() {
    if (!sid) return;
    setBusy(true);
    try {
      const r = await scriptApi.toInbox(sid);
      const path = String(r.path ?? r.draft ?? r.file ?? "");
      setInbox({ ok: true, text: `已登记为导入候选${path ? `：${path}` : ""}。去导入页确认后才会导入。` });
    } catch (e) {
      setInbox({ ok: false, text: isNotReady(e) ? "后端未就绪：/to-inbox 还没上线。可以先点“去导入页”手动采纳草稿。" : `送到剧本导入失败：${errText(e)}` });
    } finally {
      setBusy(false);
    }
  }

  async function runAb() {
    if (!outline.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await scriptApi.ab({
        outline,
        episodes: range,
        llm_a: llm,
        llm_b: llmB,
        shots_per_ep: shots === "" ? undefined : shots,
        seconds_per_shot: secs === "" ? undefined : secs,
        rules,
      });
      const [a, b] = abIds(r);
      setAb({ a, b });
      setAbOpen(false);
      // 后端只建两个会话（各带 pending 提纲请求），两边的写作由前端各发一次空 content 的 /chat 启动
      const run = (side: "a" | "b", sid: string | null, choice: LlmChoice | null) => {
        if (!sid) return;
        const ac = new AbortController();
        abAbort.current.push(ac);
        setAbRun((x) => ({ ...x, [side]: "写作中…" }));
        let done = false;
        void chatStream(
          sid,
          "",
          (ev) => {
            if (ev.t === "progress") setAbRun((x) => ({ ...x, [side]: ev.d }));
            else if (ev.t === "validating") setAbRun((x) => ({ ...x, [side]: "格式校验中" }));
            else if (ev.t === "error") {
              done = true;
              setAbRun((x) => ({ ...x, [side]: `失败：${ev.d}` }));
            } else if (ev.t === "done") {
              done = true;
              const v = ev.validation;
              setAbRun((x) => ({ ...x, [side]: v ? `写完 · ${v.episodes.length} 集 · ${v.blocking} 处格式问题` : "写完" }));
            }
          },
          ac.signal,
          choice ? { llm: choice } : undefined,
        )
          .then(() => !done && setAbRun((x) => ({ ...x, [side]: "连接中断；已收到的部分已存档" })))
          .catch((e) => setAbRun((x) => ({ ...x, [side]: ac.signal.aborted ? "已停止" : `失败：${errText(e)}` })));
      };
      run("a", a, llm);
      run("b", b, llmB);
    } catch (e) {
      setErr(isNotReady(e) ? "后端未就绪：/api/script-chat/ab 还没上线" : `交给两个模型失败：${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const text = live ? live.content : tab !== "all" && eps?.[tab] != null ? eps[tab] : (out?.content ?? "");
  const reasoning = live?.reasoning ?? out?.reasoning ?? "";
  const providers = prov.data?.providers ?? [];
  const pvA = providers.find((p) => p.id === llm?.provider);

  return (
    <div className="v3p-page v3p-script">
      <header className="v3p-head">
        <span className="v3p-step">①</span>
        <h1>剧本创作</h1>
        <span className="v3p-muted">提纲 → 模型写剧本与分镜 → 格式校验 → 送到剧本导入（导入仍由你确认）</span>
        <span className="grow" />
        <a className="btn-mini" href={sid ? `#/script-chat/${sid}` : "#/script-chat"} title="完整对话：改稿、继续下一集、按校验返修">
          写作对话框 ↗
        </a>
      </header>

      <div className="v3p-script-grid">
        <section className="v3p-col">
          <div className="v3p-card">
            <div className="v3p-card-head">
              <h2>1 · 提纲</h2>
              <span className="grow" />
              <input ref={fileRef} type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" hidden onChange={(ev) => void onFile(ev.target.files?.[0])} />
              <button className="btn-mini" onClick={() => fileRef.current?.click()}>上传文件</button>
              {outline && (
                <button className="btn-mini" onClick={() => { setOutline(""); setFileName(null); }}>清空</button>
              )}
            </div>
            <textarea
              className="v3p-outline"
              value={outline}
              onChange={(ev) => setOutline(ev.target.value)}
              placeholder="粘贴提纲，或点「上传文件」（.txt / .md）"
              spellCheck={false}
            />
            <div className="v3p-muted v3p-small">
              {fileName ? `来自 ${fileName} · ` : ""}
              {outline.length} 字
            </div>
            <div className="v3p-row">
              <label className="v3p-f narrow">
                <span>从第</span>
                <input type="number" min={1} value={epFrom} onChange={(ev) => setEpFrom(Math.max(1, Number(ev.target.value) || 1))} />
              </label>
              <label className="v3p-f narrow">
                <span>到第（集）</span>
                <input type="number" min={1} value={epTo} onChange={(ev) => setEpTo(Math.max(1, Number(ev.target.value) || 1))} />
              </label>
              <label className="v3p-f narrow">
                <span>每集镜头数</span>
                <input type="number" min={1} placeholder="按规则" value={shots} onChange={(ev) => setShots(ev.target.value === "" ? "" : Math.max(1, Number(ev.target.value)))} />
              </label>
              <label className="v3p-f narrow">
                <span>每镜秒数</span>
                <input type="number" min={1} placeholder="按规则" value={secs} onChange={(ev) => setSecs(ev.target.value === "" ? "" : Math.max(1, Number(ev.target.value)))} />
              </label>
              <label className="v3p-f">
                <span>写作规则</span>
                <select value={rules} onChange={(ev) => setRules(ev.target.value)}>
                  {rulesList.map((r) => (
                    <option key={r.id} value={r.id} title={r.parts.join("、")}>{r.id}{r.id === rulesDefault ? "（现行）" : ""}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="v3p-card">
            <div className="v3p-card-head">
              <h2>2 · 模型设置</h2>
              <span className="grow" />
              <span className="v3p-muted">只改这一次；长期默认去</span>
              <a className="v3p-link" href="#/models">模型与 API ⚙</a>
            </div>
            {prov.notReady ? (
              <div className="v3p-notready">
                <b>后端未就绪</b>：/api/llm/providers 还没上线，这次按写作对话框当前配置写：
                {typeof legacy === "string" ? (
                  ` ${legacy}`
                ) : legacy ? (
                  <span className="mono"> {legacy.provider} / {legacy.model}{legacy.has_key ? "" : "（缺 key）"}</span>
                ) : (
                  " 读取中…"
                )}
              </div>
            ) : prov.err ? (
              <p className="v3p-err">{prov.err} <button className="btn-mini" onClick={() => void prov.reload()}>重试</button></p>
            ) : !prov.data ? (
              <p className="v3p-muted">加载模型清单…</p>
            ) : (
              <>
                <LlmFields providers={providers} value={llm} onChange={setLlm} />
                {llm && pvA && !pvA.has_key && <p className="v3p-warn">这家还没配 key，写作会失败；去「模型与 API」填 key。</p>}
              </>
            )}
          </div>

          <div className="v3p-actions">
            {live ? (
              <button className="btn bad" onClick={() => abort.current?.abort()}>停止</button>
            ) : (
              <button className="btn primary" disabled={!canWrite} onClick={() => void write()} title={outline.trim() ? "" : "先填提纲"}>
                开始写作（第 {range[0]}{range[1] !== range[0] ? `–${range[1]}` : ""} 集）
              </button>
            )}
            <button className="btn" disabled={!outline.trim() || !!live || busy} onClick={() => setAbOpen(!abOpen)} aria-expanded={abOpen}>
              同一提纲交给两个模型…
            </button>
            {est && <span className="v3p-muted" title="按这次要发的提示 + 该模型输出上限估的上限">预计费用：{est.text}</span>}
          </div>

          {abOpen && (
            <div className="v3p-card v3p-ab">
              <div className="v3p-card-head">
                <h2>A / B：两个模型各写一版</h2>
              </div>
              <div className="v3p-ab-a">
                <span className="v3p-tag">A</span>
                <span className="mono">{llm ? `${llm.provider} / ${llm.model}` : "后端默认"}</span>
                <span className="v3p-muted">（上面的模型设置）</span>
              </div>
              <div className="v3p-ab-b">
                <span className="v3p-tag">B</span>
                {providers.length ? (
                  <LlmFields providers={providers} value={llmB} onChange={setLlmB} compact />
                ) : (
                  <span className="v3p-notready">后端未就绪：没有模型清单，B 无法选择</span>
                )}
              </div>
              <div className="v3p-actions">
                <button className="btn primary" disabled={busy || !llmB} onClick={() => void runAb()}>两个都写</button>
                <span className="v3p-muted">写完进「剧本 A/B 对比」页，由你挑</span>
              </div>
            </div>
          )}
          {ab && (
            <div className="v3p-card v3p-ok-card">
              已开始两版：
              {ab.a && <a className="v3p-link" href={`#/script-chat/${ab.a}`}>A 会话</a>}
              {abRun.a && <span className="v3p-muted">（{abRun.a}）</span>}
              {ab.b && <a className="v3p-link" href={`#/script-chat/${ab.b}`}>B 会话</a>}
              {abRun.b && <span className="v3p-muted">（{abRun.b}）</span>}
              <a className="btn-mini" href={`/?view=ab${ab.a ? `&sa=${encodeURIComponent(ab.a)}` : ""}${ab.b ? `&sb=${encodeURIComponent(ab.b)}` : ""}`}>去 A/B 对比页 →</a>
            </div>
          )}
        </section>

        <section className="v3p-col v3p-out">
          <div className="v3p-card v3p-stream">
            <div className="v3p-card-head">
              <h2>3 · 草稿（按集）</h2>
              {live && <span className="v3p-badge busy">{live.phase}…</span>}
              {!live && out && <span className="v3p-badge">已结束</span>}
              <span className="grow" />
              {text && !live && (
                <button className="btn-mini" onClick={() => void navigator.clipboard?.writeText(text)}>复制</button>
              )}
            </div>
            {!live && eps && (
              <div className="v3p-tabs" role="tablist">
                <button role="tab" aria-selected={tab === "all"} className={tab === "all" ? "on" : ""} onClick={() => setTab("all")}>本次输出</button>
                {Object.keys(eps)
                  .sort((a, b) => Number(a) - Number(b))
                  .map((k) => {
                    const c = val?.episodes.find((x) => x.number === Number(k));
                    return (
                      <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
                        第 {Number(k)} 集{c ? <span className={c.blocking ? "bad" : "ok"}>{c.blocking ? ` ✕${c.blocking}` : " ✓"}</span> : null}
                      </button>
                    );
                  })}
              </div>
            )}
            {reasoning && tab === "all" && (
              <details className="v3p-think" open={!!live && !live.content}>
                <summary>思考过程（{reasoning.length} 字）</summary>
                <pre>{reasoning.slice(-4000)}</pre>
              </details>
            )}
            {text ? (
              <pre ref={outRef} className="v3p-script-text">{text}</pre>
            ) : (
              <div className="v3p-empty">
                {live ? "等待模型输出…" : "填好提纲后点「开始写作」，模型的原文会实时显示在这里（原样显示，系统不改）。"}
              </div>
            )}
            {note && <p className="v3p-warn">{note}</p>}
            {err && (
              <p className="v3p-err" role="alert">
                {err} <button className="btn-mini" onClick={() => setErr(null)}>关闭</button>
              </p>
            )}
          </div>

          <div className="v3p-card">
            <div className="v3p-card-head">
              <h2>4 · 格式校验</h2>
              {val && !val.error && (
                <span className="v3p-sum">
                  <b>{val.episodes.length}</b> 集 · <b className={val.blocking ? "bad" : "ok"}>{val.blocking}</b> 处格式问题 · <b className={val.warnings ? "warn" : ""}>{val.warnings}</b> 提醒
                </span>
              )}
              <span className="grow" />
              {sid && (
                <button className="btn-mini" disabled={!!live || busy} onClick={() => void revalidate()}>重新校验</button>
              )}
            </div>
            {!sid && <p className="v3p-muted">写完自动校验格式（只看格式，不评价内容）。</p>}
            {sid && !val && !live && <p className="v3p-muted">还没有成稿的集。</p>}
            {val?.error && <p className="v3p-err">校验器出错：{val.error}</p>}
            <div className="v3p-eps">{val?.episodes.map((e) => <EpLine key={e.number} e={e} />)}</div>
            {val && !val.error && val.episodes.length > 0 && (
              <div className="v3p-actions">
                <button className={`btn${val.blocking ? "" : " primary"}`} disabled={busy || !!live} onClick={() => void toInbox()} title="登记为导入候选，不会自动导入">
                  送到剧本导入
                </button>
                {val.blocking > 0 && (
                  <a className="btn" href={`#/script-chat/${sid}`} title="在写作对话框里点「按校验返修」">去返修</a>
                )}
                <a className="v3p-link" href="/?view=import">去导入页</a>
              </div>
            )}
            {inbox && <p className={inbox.ok ? "v3p-okline" : "v3p-err"}>{inbox.text}</p>}
          </div>
          {!prov.notReady && pvA && (
            <div className="v3p-muted v3p-small">
              本次：{pvA.name} / {llm?.model} <KeyBadge p={pvA} />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function EpLine({ e }: { e: EpCheck }) {
  const [open, setOpen] = useState(false);
  const issues = [...e.issues.map((i) => ({ where: "集", i })), ...e.shots.flatMap((s) => s.issues.map((i) => ({ where: `镜${s.index}`, i })))];
  return (
    <div className={`v3p-ep${e.blocking ? " bad" : ""}`}>
      <button className="v3p-ep-head" onClick={() => setOpen(!open)} disabled={!issues.length}>
        <span className={`v3p-dot ${e.blocking ? "bad" : "ok"}`} />
        <span className="mono">ep{pad(e.number)}</span>
        <span className="v3p-ep-title">《{e.title}》</span>
        <span className="grow" />
        <span className="v3p-muted">{e.shots.length} 镜 · {e.shots.reduce((a, x) => a + (x.duration ?? 0), 0)} 秒</span>
        <span className={e.blocking ? "bad" : "ok"}>{e.blocking ? `${e.blocking} 处问题` : "通过"}</span>
        {e.warnings > 0 && <span className="warn">{e.warnings} 提醒</span>}
      </button>
      {open && (
        <div className="v3p-issues">
          {issues.map(({ where, i }, k) => (
            <div key={k} className={i.level === "block" ? "bad" : "warn"}>
              <b>{where}</b> <span className="mono">{i.rule_id}</span> {i.detail}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
