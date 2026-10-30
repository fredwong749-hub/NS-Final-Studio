import { useCallback, useEffect, useState } from "react";

/** 剧本导入（项目方 2026-10-30）：Qwen 写的剧本稿 → 格式校验摘要 → 项目方勾选确认后导入。画布不读不改剧本内容。 */

interface Validation {
  sha256: string;
  ok: boolean;
  blocking?: number;
  warnings?: number;
  episodes?: number;
  top_rules?: { rule: string; count: number }[];
  validated_at?: string;
  error?: string;
}
interface Candidate {
  path: string;
  name: string;
  size: number;
  sha256: string;
  mtime: string;
  source: "staging" | "qwen-mailbox" | "script-chat" | "input";
  /** 项目方选定的主线（剧本创作对话，写作 = 本地 Qwen） */
  mainline?: boolean;
  validation: Validation | null;
}
interface Inbox {
  candidates: Candidate[];
  current: { path: string | null; mtime: string | null; last_import: { at: string; path: string; note?: string } | null };
}

async function call<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const t = await r.text();
  if (!r.ok) {
    let msg = t;
    try {
      msg = JSON.parse(t).detail ?? t;
    } catch {
      /* 原文 */
    }
    throw new Error(msg);
  }
  return JSON.parse(t) as T;
}

function Row({ c, onDone }: { c: Candidate; onDone: (msg: string, err?: boolean) => void }) {
  const [v, setV] = useState<Validation | null>(c.validation);
  const [busy, setBusy] = useState<"" | "validate" | "import">("");
  const [owner, setOwner] = useState(false);
  const [force, setForce] = useState(false);
  const [note, setNote] = useState("");
  useEffect(() => setV(c.validation), [c.validation]);
  const doValidate = async () => {
    setBusy("validate");
    try {
      setV(await call<Validation>("/api/script-inbox/validate", { path: c.path }));
    } catch (e) {
      onDone(`校验失败：${(e as Error).message}`, true);
    } finally {
      setBusy("");
    }
  };
  const doImport = async () => {
    setBusy("import");
    try {
      await call("/api/script-inbox/import", { path: c.path, sha256: c.sha256, by: "owner", confirm: true, accept_blocking: force, note: note || null });
      onDone(`已导入 ${c.name}（原剧本已备份）。集视图会自动换上新剧本。`);
      setOwner(false);
      setForce(false);
    } catch (e) {
      onDone(`导入未完成：${(e as Error).message}`, true);
    } finally {
      setBusy("");
    }
  };
  // 封板修复：校验器本身出错 ≠ 有格式问题：不给“仍然导入”，导入按钮保持禁用
  const vErr = !!v?.error;
  const needForce = !!v && !vErr && !v.ok;
  return (
    <article className="imp-row">
      <header>
        {c.mainline && <span className="chip chip-ok">主线</span>}
        <b className="imp-name" title={`${c.name}
${c.path}`}>{c.name}</b>
        <a className="btn-mini" href={`/api/script-inbox/download?path=${encodeURIComponent(c.path)}`} download title="原文件下载（不改内容）">
          下载 .md
        </a>
        <span className={`chip ${c.source === "staging" ? "chip-dark" : "chip-accent"}`}>
          {c.source === "qwen-mailbox" ? "Qwen 信箱交付" : c.source === "script-chat" ? "剧本创作对话" : c.source === "input" ? "剧本输入" : "暂存稿"}
        </span>
        <span className="muted small imp-meta" title={`sha256 ${c.sha256}`}>
          {c.mtime} · {(c.size / 1024).toFixed(0)} KB
        </span>
      </header>
      <div className="imp-val">
        {!v && <span className="muted">还没校验 · 导入前先点「校验格式」（约 1 分钟）</span>}
        {v?.error && <span className="warn">校验器出错：{v.error}</span>}
        {v && !v.error && (
          <>
            <span className={`chip ${v.ok ? "chip-ok" : "chip-bad"}`}>{v.ok ? "格式校验通过" : `格式问题 ${v.blocking}`}</span>
            <span className="muted small">
              提醒 {v.warnings} · {v.episodes} 集 · 校验于 {v.validated_at}
            </span>
            {!v.ok && (
              <span className="imp-rules muted small" title={(v.top_rules ?? []).map((r) => `${r.rule} × ${r.count}`).join("\n")}>
                最多：{(v.top_rules ?? []).slice(0, 3).map((r) => `${r.rule}×${r.count}`).join(" · ")}
                {(v.top_rules ?? []).length > 3 && " …"}
              </span>
            )}
          </>
        )}
        <button className="btn-mini" disabled={!!busy} onClick={doValidate}>
          {busy === "validate" ? "校验中…（约 1 分钟）" : v ? "重新校验" : "校验格式"}
        </button>
      </div>
      <div className="imp-act">
        <label>
          <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方，确认采纳这份剧本并导入
        </label>
        {needForce && (
          <label className="warn">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 仍有 {v?.blocking} 个格式问题，仍然导入
          </label>
        )}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="备注（可选）" />
        <button
          className="btn primary"
          disabled={!!busy || !owner || !v || vErr || (needForce && !force)}
          onClick={doImport}
          title={!v ? "先点「校验格式」" : vErr ? `校验器出错：${v.error}（先重新校验）` : !owner ? "先勾选「我是项目方，确认采纳」" : needForce && !force ? "有格式问题：先返修，或勾选「仍然导入」" : "导入：当前剧本先自动备份"}
        >
          {busy === "import" ? "导入中…" : "导入"}
        </button>
      </div>
    </article>
  );
}

/** 剧本输入：粘贴或上传剧本文本，原样存成草稿（data/staging_input），自动出现在下方导入候选里 */
function ScriptInput({ onSaved }: { onSaved: (msg: string, err?: boolean) => void }) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const r = await call<{ name: string }>("/api/script-input", { name, text, overwrite });
      onSaved(`已存为草稿 ${r.name}，在左侧列表里校验格式后即可导入`);
      setText("");
    } catch (e) {
      onSaved(`保存失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };
  const upload = async (f: File) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("overwrite", String(overwrite));
      const r = await fetch("/api/script-input/upload", { method: "POST", body: fd });
      const t = await r.text();
      if (!r.ok) throw new Error((() => { try { return JSON.parse(t).detail; } catch { return t; } })());
      onSaved(`已上传为草稿 ${JSON.parse(t).name}`);
    } catch (e) {
      onSaved(`上传失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="imp-input">
      <h3>剧本输入</h3>
      <div className="imp-act">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="草稿名（例：为他而骚 v4）" />
        <label>
          <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> 覆盖同名草稿
        </label>
        <label className="btn-mini">
          上传 .md / .txt
          <input
            type="file"
            accept=".md,.txt"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = ""; // 封板修复：同一文件可再选一次
              if (f) void upload(f);
            }}
          />
        </label>
      </div>
      <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder="把剧本全文粘贴到这里（格式见 docs/qwen_writing_contract.md）" />
      <div className="imp-act">
        <button className="btn primary" disabled={busy || !name.trim() || !text.trim()} onClick={save}>
          {busy ? "保存中…" : "存为草稿"}
        </button>
        <span className="muted small">原样保存，不改内容；草稿出现在左侧列表</span>
      </div>
    </section>
  );
}

export function ImportView() {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);
  const load = useCallback(async () => {
    try {
      setInbox(await call<Inbox>("/api/script-inbox"));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className="imp-view imp2">
      <header className="page-head">
        <h2>剧本输入与导入</h2>
        {inbox?.current && (
          <span
            className="muted small page-head-sub"
            title={inbox.current.last_import ? `上次导入 ${inbox.current.last_import.at}：${inbox.current.last_import.path}` : undefined}
          >
            当前剧本：{inbox.current.path ?? "无"}（{inbox.current.mtime ?? "—"}）
          </span>
        )}
        <span className="grow" />
        <button className="btn" onClick={load} title="重新读取待导入列表">
          刷新
        </button>
      </header>
      {msg && (
        <div className={`banner ${msg.err ? "bad" : "ok"}`} role="status">
          <span className="grow">{msg.text}</span>
          <button className="btn-mini" onClick={() => setMsg(null)}>关闭</button>
        </div>
      )}
      {err && <div className="banner bad">读取失败：{err}。确认 API（:8800）在运行后点「刷新」；仍失败需重启 API。</div>}
      <div className="imp-grid">
      <section className="imp-col">
      <h3 className="imp-col-head">
        待导入的剧本稿 {inbox && <span className="muted">{inbox.candidates.length}</span>}
      </h3>
      <p className="muted small imp-steps">① 校验格式 → ② 勾选「我是项目方」→ ③ 导入。系统只查格式不看内容；导入前自动备份当前剧本，集视图随即换上新剧本。</p>
      <p className="muted small">剧本有 5 个入口：本页上方「剧本输入」（粘贴 / 上传存草稿）、这里的导入列表（校验 → 项目方确认导入，默认按集合并）、剧本创作对话（#/script-chat）、A/B 对比（?view=ab）、命令行（tools/import_script.py 等）。详见 docs/release/script_entrypoints.md。</p>
      {!inbox && !err && <div className="imp-skel">读取中…</div>}
      <div className="imp-list">
        {inbox?.candidates.map((c) => (
          <Row
            key={c.path + c.sha256}
            c={c}
            onDone={(text, e) => {
              setMsg({ text, err: e });
              void load();
            }}
          />
        ))}
        {inbox && inbox.candidates.length === 0 && <div className="imp-emptybox">暂时没有待导入的剧本稿。在右侧粘贴 / 上传剧本，或在「剧本 → 创作」里让模型写一份。</div>}
      </div>
      </section>
      <aside className="imp-side">
        <ScriptInput
          onSaved={(text, e) => {
            setMsg({ text, err: e });
            void load();
          }}
        />
      </aside>
      </div>
    </div>
  );
}

export default ImportView;
