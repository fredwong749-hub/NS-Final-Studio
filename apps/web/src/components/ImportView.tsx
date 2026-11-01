import { useCallback, useEffect, useState } from "react";
import { useStudio } from "../store";
import { DeleteButton } from "../ds/editdel";

/** UX4（审查 #42）：时间写本地短格式“10-30 15:36”；认不出的原样返回 */
function shortTime(x: string | null | undefined): string {
  if (!x) return "—";
  const d = new Date(x);
  if (Number.isNaN(d.getTime())) return x;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

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
  /** fredw-92/UXF4（流程 d）：剧本创作会话的元数据（会话标题 / 集号 / 创建时间）——这类稿文件名都叫 script.md */
  session?: { id: string; title: string | null; episodes: number[]; created_at: string | null } | null;
}

/** 集号列表 → “第 1 集” / “第 1–3 集” / “第 1、4、7 集” */
function epText(eps: number[]): string {
  if (!eps.length) return "";
  const contiguous = eps.every((n, i) => i === 0 || n === eps[i - 1] + 1);
  if (eps.length === 1) return `第 ${eps[0]} 集`;
  return contiguous ? `第 ${eps[0]}–${eps[eps.length - 1]} 集` : `第 ${eps.slice(0, 4).join("、")}${eps.length > 4 ? "…" : ""} 集`;
}

/** 列表里显示的名字：剧本创作会话 = 会话标题 · 集号 · 创建时间；其余 = 文件名 */
/** 文件名 → 人话：“_series10_v1_ep01-10_lookfix_v3.md” → “第 1–10 集 · 造型修订 · v3” */
const FIX_WORDS: [RegExp, string][] = [[/lookfix/i, "造型修订"], [/hairfix/i, "发型修订"], [/fixpass|fix/i, "修订"], [/rewrite/i, "重写"], [/draft/i, "草稿"]];
function humanFileName(name: string): string {
  const base = name.replace(/\.(md|txt)$/i, "");
  const parts: string[] = [];
  const ep = /ep(\d{1,3})(?:\s*[-–~]\s*(?:ep)?(\d{1,3}))?/i.exec(base);
  if (ep) parts.push(ep[2] ? `第 ${+ep[1]}–${+ep[2]} 集` : `第 ${+ep[1]} 集`);
  for (const [re, w] of FIX_WORDS)
    if (re.test(base)) {
      parts.push(w);
      break;
    }
  const v = /(?:^|[_\s-])v(\d+(?:\.\d+)?)\b/i.exec(base.replace(/series\d+_v\d+/i, ""));
  if (v) parts.push(`v${v[1]}`);
  if (/series\d+/i.test(base) && !parts.length) parts.push("整季剧本");
  // 认不出结构的（例如中文书名）照原样显示
  return parts.length ? parts.join(" · ") : base.replace(/^_+/, "");
}
function displayName(c: Candidate): string {
  const ss = c.session;
  if (!ss) return humanFileName(c.name);
  const when = ss.created_at ? ss.created_at.replace("T", " ").slice(5, 16) : "";
  return [ss.title || `剧本创作 ${ss.id}`, epText(ss.episodes), when].filter(Boolean).join(" · ");
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

/** UIRSI：新建剧本送来的候选（data/staging_input/story_<运行 id>.md）→ 运行 id */
// 整季运行送来的稿子文件名是 story_<运行>_epNN.md：写作过程在 <运行> 下（以前把“_epNN”也当运行名，打开就 404，UM-0260）
const storyRunOf = (c: Candidate) => {
  const m = /(?:^|\/)story_(.+)\.md$/.exec(c.path)?.[1];
  return m ? m.replace(/_ep\d{2,3}$/, "") : null;
};
const focusOf = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("focus");

function Row({ c, onDone, newest, focus }: { c: Candidate; onDone: (msg: string, err?: boolean) => void; newest?: boolean; focus?: boolean }) {
  const run = storyRunOf(c);
  const [v, setV] = useState<Validation | null>(c.validation);
  const [busy, setBusy] = useState<"" | "validate" | "import">("");
  // 项目方 2026-10-31：登录即本人——不再勾“我是项目方”，导入一个按钮（导入前自动备份，可还原）
  const owner = true;
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
      onDone(`已导入 ${c.name}（原剧本已备份）。集视图会自动换上新剧本；点顶栏 ③ 出图回到画布。`);
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
    <article className={`imp-row${focus ? " imp-focus" : ""}`} ref={focus ? (el) => el?.scrollIntoView({ block: "center" }) : undefined}>
      <header>
        {newest && <span className="chip chip-accent" title="最近一份（按修改时间）">最新</span>}
        {c.mainline && <span className="chip chip-ok">主线</span>}
        <b className="imp-name" title={`${displayName(c)}
文件：${c.path}`}>{displayName(c)}</b>
        <a className="btn-mini" href={`/api/script-inbox/download?path=${encodeURIComponent(c.path)}`} download title="原文件下载（不改内容）">
          下载 .md
        </a>
        {/* EDITDEL：不要的候选稿移到回收站（可还原；当前在用的主线 / 导入过的会先提示） */}
        <DeleteButton type="import_candidate" id={c.path} size="xs" label="删除" onDeleted={(e) => onDone(e.state === "restored" ? `已还原：${displayName(c)}` : `已移到回收站：${displayName(c)}`)} />
        <span className={`chip ${c.source === "staging" ? "chip-dark" : "chip-accent"}`}>
          {run ? "新建剧本" : c.source === "qwen-mailbox" ? "写作模型交付" : c.source === "script-chat" ? "剧本创作对话" : c.source === "input" ? "剧本输入" : "暂存稿"}
        </span>
        {run && (
          <a className="btn-mini" href={`#/script-create?run=${encodeURIComponent(run)}`} title="回到这次写作：看故事线 / 大纲 / 剧本 / 分镜，改原文或返修">
            看写作过程 ›
          </a>
        )}
        <span className="muted small imp-meta" title={`sha256 ${c.sha256}`}>
          {shortTime(c.mtime)} · {(c.size / 1024).toFixed(0)} KB
        </span>
      </header>
      <div className="imp-val">
        {!v && <span className="muted">还没校验 · 导入前先点「校验格式」（约 1 分钟）</span>}
        {v?.error && <span className="warn">校验器出错：{v.error}</span>}
        {v && !v.error && (
          <>
            <span className={`chip ${v.ok ? "chip-ok" : "chip-bad"}`}>{v.ok ? "格式校验通过" : `格式问题 ${v.blocking}`}</span>
            <span className="muted small">
              提醒 {v.warnings} · {v.episodes} 集 · 校验于 {shortTime(v.validated_at)}
            </span>
            {!v.ok && (
              <span className="imp-rules muted small" title={`按规则编号（返修用）：\n${(v.top_rules ?? []).map((r) => `${r.rule.replace(/\|.*/, "")} × ${r.count}`).join("\n")}`}>
                格式问题 = 校验器按写作规则查出的必改项，可以按意见返修后重新校验（悬停看分布）
              </span>
            )}
          </>
        )}
        <button className="btn-mini" disabled={!!busy} onClick={doValidate}>
          {busy === "validate" ? "校验中…（约 1 分钟）" : v ? "重新校验" : "校验格式"}
        </button>
      </div>
      <div className="imp-act">
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
          title={!v ? "先点「校验格式」" : vErr ? `校验器出错：${v.error}（先重新校验）` : needForce && !force ? "有格式问题：先返修，或勾选「仍然导入」" : "导入：当前剧本先自动备份"}
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
        <button className="btn primary" disabled={busy || !name.trim() || !text.trim()} title={busy ? "正在保存" : !name.trim() ? "先填稿子的名字" : !text.trim() ? "先粘贴或上传剧本内容" : "存为草稿，之后在左侧校验、导入"} onClick={save}>
          {busy ? "保存中…" : "存为草稿"}
        </button>
        <span className="muted small">原样保存，不改内容；草稿出现在左侧列表</span>
      </div>
    </section>
  );
}

export function ImportView() {
  const eps = useStudio().episodes;
  const epRange = eps && eps.length ? `第 ${Math.min(...eps.map((e) => e.number))}–${Math.max(...eps.map((e) => e.number))} 集` : "";
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
  // UIRSI（D13）：最新在上；默认只列最近 5 份，从“新建剧本”送来时定位到那一份
  const [all, setAll] = useState(false);
  const [focus, setFocus] = useState(focusOf);
  useEffect(() => {
    const on = () => setFocus(focusOf());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const sorted = [...(inbox?.candidates ?? [])].sort((a, b) => (a.mtime < b.mtime ? 1 : a.mtime > b.mtime ? -1 : 0));
  const shown = all ? sorted : sorted.filter((c, i) => i < 5 || c.path === focus || c.mainline);
  return (
    <div className="imp-view imp2">
      <header className="page-head">
        <h2>剧本输入与导入</h2>
        {inbox?.current && (
          <span
            className="muted small page-head-sub"
            title={`${inbox.current.path ? `文件：${inbox.current.path}` : ""}${inbox.current.last_import ? `
上次导入 ${shortTime(inbox.current.last_import.at)}` : ""}`}
          >
            {inbox.current.path ? `当前剧本：${epRange || "已导入的剧本"}（更新于 ${shortTime(inbox.current.mtime)}）` : "当前还没有导入剧本"}
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
      {err && <div className="banner bad" title={`技术细节：${err}（后台 127.0.0.1:8800）`}>待导入列表读不到：后台服务没响应。稍后点「刷新」；一直不行，后台服务可能需要重启。</div>}
      <div className="imp-grid">
      <section className="imp-col">
      <h3 className="imp-col-head">
        待导入的剧本稿 {inbox && <span className="muted">{inbox.candidates.length}</span>}
      </h3>
      <p className="muted small imp-steps">① 校验格式 → ② 导入（记在你的账户名下；导入前自动备份当前剧本，可还原）。系统只查格式不看内容；导入前自动备份当前剧本，集视图随即换上新剧本。</p>
      <p className="muted small">剧本稿从这几处来：本页上方「剧本输入」（粘贴 / 上传）、「① 新建剧本」写完送过来的、写作模型交付的。在这里校验格式，由项目方确认导入（默认按集合并）。</p>
      {!inbox && !err && <div className="imp-skel">读取中…</div>}
      <div className="imp-list">
        {shown.map((c, i) => (
          <Row
            key={c.path + c.sha256}
            c={c}
            newest={i === 0}
            focus={!!focus && c.path === focus}
            onDone={(text, e) => {
              setMsg({ text, err: e });
              void load();
            }}
          />
        ))}
        {sorted.length > shown.length && (
          <button className="btn-mini imp-more" onClick={() => setAll(true)}>
            还有 {sorted.length - shown.length} 份更早的稿件 · 展开
          </button>
        )}
        {inbox && inbox.candidates.length === 0 && <div className="imp-emptybox">暂时没有待导入的剧本稿。在右侧粘贴 / 上传剧本，或在「剧本 → ① 新建剧本」里从提纲自动写一份。</div>}
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
