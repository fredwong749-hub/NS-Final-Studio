// T58 剧本创作对话框（#/script-chat[/<会话id>]）：输入大纲 → 外部写作模型按 config/script_chat_rules.md 写剧本与分镜。
// 系统只收发：回复原样显示；回复里的整集按集号并入会话草稿，草稿过格式校验（tools/validate_qwen_script.py）。
import { useCallback, useEffect, useRef, useState } from "react";
import { capi, chatStream, type ChatConfig, type EpCheck, type Msg, type Session, type SessionRow } from "./capi";
import "./chat.css";
import { ThemeToggle } from "../../themeMode";
import { lastCanvas } from "../../projects/route";

const go = (h: string) => (window.location.hash = h);

function sidFromHash(hash: string) {
  const m = hash.match(/^#\/script-chat\/([\w-]+)/);
  return m ? m[1] : null;
}

export default function ChatApp({ hash }: { hash: string }) {
  const sid = sidFromHash(hash);
  const [cfg, setCfg] = useState<ChatConfig | null>(null);
  const [rows, setRows] = useState<SessionRow[]>([]);
  const [s, setS] = useState<Session | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [live, setLive] = useState<{ content: string; reasoning: string; phase: string } | null>(null);
  const [rules, setRules] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const sidRef = useRef(sid);
  sidRef.current = sid;

  const refreshRows = useCallback(() => capi.sessions().then(setRows).catch((e) => setErr(String(e.message ?? e))), []);
  useEffect(() => {
    capi.config().then(setCfg).catch((e) => setErr(String(e.message ?? e)));
    refreshRows();
  }, [refreshRows]);
  // 封板修复：切会话后丢弃旧会话的迟到响应；卸载时中止流
  useEffect(() => {
    let alive = true;
    setS(null);
    if (sid) capi.session(sid).then((n) => alive && setS(n)).catch((e) => alive && setErr(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [sid]);
  useEffect(() => () => abort.current?.abort(), []);
  // 批量会话在后台写入时自动刷新
  useEffect(() => {
    if (!sid || live) return;
    const t = setInterval(() => {
      capi.session(sid).then((n) => sidRef.current === sid && setS((o) => (o && o.messages.length === n.messages.length && o.validation?.at === n.validation?.at ? o : n))).catch(() => {});
      refreshRows();
    }, 15000);
    return () => clearInterval(t);
  }, [sid, live, refreshRows]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [s?.messages.length, live?.content.length]);

  async function newChat() {
    try {
      const n = await capi.create();
      await refreshRows();
      go(`#/script-chat/${n.id}`);
    } catch (e) {
      setErr(`新建对话失败：${String((e as Error).message ?? e)}`);
    }
  }

  async function send(text: string) {
    if (!text.trim() || live) return;
    let id = sid;
    if (!id) {
      try {
        const n = await capi.create();
        id = n.id;
        go(`#/script-chat/${id}`);
        setS(n);
      } catch (e) {
        setErr(`新建对话失败：${String((e as Error).message ?? e)}`);
        return;
      }
    }
    const ac = new AbortController();
    abort.current = ac;
    setErr(null);
    setDraft("");
    setS((o) => (o ? { ...o, messages: [...o.messages, { role: "user", content: text }] } : o));
    setLive({ content: "", reasoning: "", phase: "思考中" });
    let ended = false;
    try {
      await chatStream(id, text, (e) => {
        if (e.t === "reasoning") setLive((l) => l && { ...l, reasoning: l.reasoning + e.d, phase: "思考中" });
        else if (e.t === "content") setLive((l) => l && { ...l, content: l.content + e.d, phase: "写作中" });
        else if (e.t === "progress") setLive((l) => l && { ...l, phase: e.d });
        else if (e.t === "validating") setLive((l) => l && { ...l, phase: "格式校验中" });
        else if (e.t === "warn") setErr(e.d);
        else if (e.t === "error") { ended = true; setErr(e.d); }
        else if (e.t === "done") ended = true;
      }, ac.signal);
      if (!ended && !ac.signal.aborted) setErr("连接中断：没有收到完成信号；已收到的部分已存档，刷新后可见，可以发“继续”或重新发送");
    } catch (e) {
      if (ac.signal.aborted) setErr("已停止；已收到的部分已存档");
      else setErr(`发送失败：${String((e as Error).message ?? e)}（检查画布 API :8800 是否在运行）`);
    } finally {
      abort.current = null;
      setLive(null);
      capi.session(id).then((n) => sidRef.current === id && setS(n)).catch(() => {});
      refreshRows();
    }
  }

  async function fillRepair() {
    if (!sid) return;
    try {
      const r = await capi.repair(sid);
      setDraft(r.text || "");
      if (!r.text) setErr("草稿没有格式 block 项，不需要返修");
    } catch (e) {
      setErr(`读取返修清单失败：${String((e as Error).message ?? e)}`);
    }
  }

  const v = s?.validation;
  return (
    <div className="sc-app">
      <aside className="sc-side">
        <div className="sc-side-head">
          <button className="btn-mini" onClick={() => go(lastCanvas())} title="回到画布（回到离开时的那一镜）">← 画布</button>
          <b>剧本创作</b>
          <span className="grow" />
          <ThemeToggle />
        </div>
        <button className="btn primary sc-new" onClick={newChat}>＋ 新对话</button>
        <div className="sc-list">
          {rows.map((r) => (
            <button key={r.id} className={"sc-row" + (r.id === sid ? " on" : "")} onClick={() => go(`#/script-chat/${r.id}`)} title={r.title}>
              <span className="sc-row-title">{r.title}</span>
              <span className="sc-row-meta">
                {r.episodes.length ? `${r.episodes.length} 集` : "未成稿"}
                {r.blocking != null && <span className={r.blocking ? "bad" : "ok"}> · {r.blocking ? `${r.blocking} 处格式问题` : "格式通过"}</span>}
              </span>
            </button>
          ))}
          {rows.length === 0 && <p className="sc-hint">还没有对话。点上面「新对话」，输入剧本大纲开始。</p>}
        </div>
        {cfg && (
          <div className="sc-model">
            <div><span className="muted">模型</span> {cfg.model}</div>
            <div className="muted small">{cfg.provider}{cfg.has_key ? "" : " · 缺 key"}</div>
            <button className="btn-mini" onClick={() => capi.system().then((x) => setRules(x.text))}>查看写作规则</button>
          </div>
        )}
      </aside>

      <main className="sc-main">
        <header className="sc-head">
          <h2 title={s?.title}>{s?.title ?? "新对话"}</h2>
          {live && <span className="sc-pill busy">{live.phase}…</span>}
        </header>

        <div className="sc-msgs">
          {!sid && !s && (
            <div className="sc-empty">
              <h3>输入剧本大纲，开始写剧本和镜头分镜</h3>
              <p className="muted">模型按「写作规则」输出：集头、6–8 镜、每镜 img（Image 2.1 Turbo 首帧）、motion（含尾帧结束状态）、时长、声音、配乐、对白、H3 提示词。写完自动做格式校验，可在画布「导入收件箱」采纳。</p>
              <p className="muted small">改稿：直接说“ep03 镜2 改成…”，模型会重新输出整集，草稿按集号覆盖。写下一集：说“继续”。</p>
            </div>
          )}
          {s?.messages.map((m, i) => <Bubble key={i} m={m} checks={v?.episodes} />)}
          {live && (
            <div className="sc-msg assistant">
              <div className="sc-meta">{live.phase}…</div>
              {live.reasoning && (
                <details className="sc-think" open={!live.content}>
                  <summary>思考过程（{live.reasoning.length} 字）</summary>
                  <pre>{live.reasoning.slice(-4000)}</pre>
                </details>
              )}
              {live.content && <pre className="sc-script">{live.content}</pre>}
            </div>
          )}
          <div ref={bottom} />
        </div>

        {err && (
          <div className="sc-err" role="alert">
            <span className="grow">{err}</span>
            <button className="btn-mini" onClick={() => setErr(null)} title="关闭提示">关闭</button>
          </div>
        )}

        <footer className="sc-compose">
          <textarea
            value={draft}
            placeholder="输入剧本大纲、修改意见，或“继续”…（Ctrl+Enter 发送）"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(draft); }
            }}
            rows={Math.min(12, Math.max(3, draft.split("\n").length))}
          />
          <div className="sc-compose-bar">
            <button className="btn-mini" disabled={!!live} onClick={() => send("继续")} title="发送“继续”，让模型写下一集">继续下一集</button>
            <span className="grow" />
            <span className="sc-kbd"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> 发送</span>
            {live ? (
              <button className="btn bad" onClick={() => abort.current?.abort()}>停止</button>
            ) : (
              <button className="btn primary" disabled={!draft.trim()} title={!draft.trim() ? "先在输入框里写大纲、修改意见，或“继续”" : "发送（Ctrl+Enter）"} onClick={() => send(draft)}>发送</button>
            )}
          </div>
        </footer>
      </main>

      <aside className="sc-draft">
        <header className="sc-draft-head">
          <h3>草稿 · 格式校验</h3>
          {v && !v.error && (
            <div className="sc-sum">
              <span><b>{v.episodes.length}</b>集</span>
              <span className={v.blocking ? "bad" : "ok"}><b>{v.blocking}</b>格式问题</span>
              <span className={v.warnings ? "warn" : ""}><b>{v.warnings}</b>提醒</span>
            </div>
          )}
          {sid && (
            <div className="sc-draft-act">
              <button className="btn" disabled={!!live} onClick={() => capi.validate(sid).then(() => capi.session(sid).then(setS)).catch((e) => setErr(`校验失败：${String(e.message ?? e)}（检查画布 API :8800 是否在运行，然后再点一次）`))}>
                重新校验
              </button>
              <button className="btn" disabled={!!live || !v?.blocking} onClick={fillRepair} title={v?.blocking ? "把校验出的格式问题整理成返修意见，填进下方输入框（不自动发送）" : "没有格式问题，不需要返修"}>
                按校验返修
              </button>
            </div>
          )}
        </header>
        {!sid && <p className="sc-hint">选择左侧对话，或新建对话。模型写完的每一集会自动出现在这里并做格式校验。</p>}
        {sid && !v && <p className="sc-hint">还没有成稿的集。模型写完一集后，这里显示格式校验结果。</p>}
        {v?.error && <p className="sc-hint bad">校验器出错：{v.error}。点「重新校验」重试；仍失败请看 API 日志。</p>}
        {v?.draft && <p className="sc-path mono" title={v.draft}>{v.draft}</p>}
        <div className="sc-eplist">{v?.episodes.map((e) => <EpRow key={e.number} e={e} />)}</div>
        {v && !v.error && v.episodes.length > 0 && (
          <footer className="sc-draft-foot">
            <span className="muted small">{v.blocking ? "先按校验返修，格式通过后再采纳" : "格式通过：去导入页采纳这份草稿"}</span>
            <a className={`btn${v.blocking ? "" : " primary"}`} href="/#/script-create?tab=import" title="剧本 → 输入 / 导入：勾选确认后导入">
              去导入页
            </a>
          </footer>
        )}
      </aside>

      {rules != null && (
        <div className="sc-modal" onClick={() => setRules(null)}>
          <div className="sc-modal-box" onClick={(e) => e.stopPropagation()}>
            <header>
              <b>写作规则（系统提示词全文）</b>
              <span className="muted small">改规则：config/script_chat_rules.md；格式：config/qwen_writer_system_prompt.txt；模型：config/script_chat.json</span>
              <span className="grow" />
              <button className="btn-mini" onClick={() => setRules(null)}>关闭</button>
            </header>
            <pre>{rules}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

function Bubble({ m, checks }: { m: Msg; checks?: EpCheck[] }) {
  const long = m.role === "user" && m.content.length > 1200;
  const [open, setOpen] = useState(!long);
  return (
    <div className={"sc-msg " + m.role}>
      <div className="sc-meta">
        {m.role === "user" ? "你" + (m.episode ? ` · ep${String(m.episode).padStart(2, "0")}` : "") : m.model ?? "模型"}
        {m.seconds != null && <span> · {Math.round(m.seconds)} 秒</span>}
        {m.usage?.completion_tokens != null && <span> · 输出 {m.usage.completion_tokens} tok</span>}
        {m.partial && <span className="bad"> · 未完成（{m.finish}）</span>}
        {m.finish === "length" && !m.partial && <span className="bad"> · 达到长度上限</span>}
        {m.episodes?.map((n) => {
          const c = checks?.find((x) => x.number === n);
          return (
            <span key={n} className={"sc-ep " + (c ? (c.blocking ? "bad" : "ok") : "")}>
              ep{String(n).padStart(2, "0")}{c ? (c.blocking ? ` ✕${c.blocking}` : " ✓") : ""}
            </span>
          );
        })}
      </div>
      {m.reasoning && (
        <details className="sc-think">
          <summary>思考过程（{m.reasoning.length} 字）</summary>
          <pre>{m.reasoning}</pre>
        </details>
      )}
      {open ? (
        <pre className={m.role === "assistant" ? "sc-script" : ""}>{m.content}</pre>
      ) : (
        <pre className="sc-fold">{m.content.slice(0, 300)}…</pre>
      )}
      {long && <button className="btn-mini" onClick={() => setOpen(!open)}>{open ? "收起" : `展开全文（${m.content.length} 字）`}</button>}
      {m.role === "assistant" && (
        <button className="btn-mini sc-copy" onClick={() => navigator.clipboard?.writeText(m.content)}>复制</button>
      )}
    </div>
  );
}

function EpRow({ e }: { e: EpCheck }) {
  const [open, setOpen] = useState(false);
  const shotIssues = e.shots.filter((x) => x.issues.length);
  return (
    <div className={"sc-eprow" + (e.blocking ? " bad" : "")}>
      <button className="sc-eprow-head" onClick={() => setOpen(!open)}>
        <span className="mono">ep{String(e.number).padStart(2, "0")}</span>
        <span className="sc-eptitle">《{e.title}》</span>
        <span className="grow" />
        <span className={e.blocking ? "bad" : "ok"}>{e.blocking ? `block ${e.blocking}` : "✓"}</span>
        {e.warnings > 0 && <span className="warn"> · warn {e.warnings}</span>}
      </button>
      {open && (
        <div className="sc-issues">
          <div className="muted small">{e.shots.length} 镜 · {e.shots.reduce((a, x) => a + (x.duration ?? 0), 0)} 秒</div>
          {e.issues.map((i, k) => <IssueLine key={k} where="集" i={i} />)}
          {shotIssues.map((sh) => sh.issues.map((i, k) => <IssueLine key={sh.id + k} where={`镜${sh.index}`} i={i} />))}
        </div>
      )}
    </div>
  );
}

function IssueLine({ where, i }: { where: string; i: { rule_id: string; level: string; detail: string } }) {
  return (
    <div className={"sc-issue " + (i.level === "block" ? "bad" : "warn")}>
      <b>{where}</b> <span className="mono">{i.rule_id}</span> {i.detail}
    </div>
  );
}
