// 项目设置页（K-UI-030 恢复：归档前「新建剧」向导 projects/Wizard.tsx 的约 30 项设置不再消失）。
// 每一项显示当前值和来源文件：
//   可改   —— 已转成配置的项，改了只写回那一个键（改前自动备份原文件，写请求自动记操作记录）；
//   只读   —— 落在写作 / 生产规则或你本人的确认记录里，这里只显示，写明“要改请在哪改”；
//   已并入 —— 旧项现在由别处承担，灰显并写明“已并入哪里”，能读到的当前值照样显示。
// 后端：services/api/ns_api/project_settings.py（GET /api/project-settings，PUT /api/project-settings/{id}）。
// 路由：#/settings（建议）。
import { humanText, placeOf } from "./settingsWords";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Button, Empty, LoadError, Seg, Skel, Tag } from "../../ds";
import { useMe } from "../../projects/AuthGate.helpers";
import "./pages.css";
import "./settings.css";
import { AllPages } from "../PageIntro"; // W5 UIUX：设置页底部 = 全部页面（导航收敛后，旧页面都从这里也能进）

type Status = "edit" | "readonly" | "merged";
type Opt = [string | boolean, string];
interface Item {
  id: string;
  group: string;
  label: string;
  legacy: string;
  status: Status;
  file: string | null;
  source: string | null;
  type: "text" | "longtext" | "number" | "bool" | "select" | "path" | "paths";
  hint: string;
  merged_into: string;
  edit_where: string;
  options: Opt[] | null;
  min: number | null;
  max: number | null;
  value: unknown;
  error: string | null;
  also: { label: string; source: string; value: unknown }[];
}
interface Resp {
  groups: string[];
  items: Item[];
  backups: string;
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const t = await r.text();
  if (!r.ok) {
    let m = t;
    try {
      const d = JSON.parse(t).detail;
      m = typeof d === "string" ? d : JSON.stringify(d ?? t);
    } catch {
      /* 原文 */
    }
    throw new Error(m || `HTTP ${r.status}`);
  }
  return JSON.parse(t) as T;
}
const putItem = (id: string, value: unknown, expect?: unknown) =>
  call<{ item: Item; prev: unknown; backup: string | null; unchanged?: boolean }>(`/api/project-settings/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value, by: "owner", key: id, expect, has_expect: expect !== undefined }),
  });

const STATUS: Record<Status, { label: string; tone: "ok" | "info" | "void"; tip: string }> = {
  edit: { label: "可改", tone: "ok", tip: "改了只写回这一个键；改前自动备份原文件" },
  readonly: { label: "只读", tone: "info", tip: "不在这里改，下面写了去哪改" },
  merged: { label: "已并入", tone: "void", tip: "这一项现在由别处承担，下面写了并入哪里" },
};

/** 任意值 → 给人看的文字 */
function show(v: unknown, opts?: Opt[] | null): ReactNode {
  if (opts) {
    const o = opts.find(([k]) => k === v);
    if (o) return o[1];
  }
  if (v === null || v === undefined || v === "") return <span className="v3p-muted">（没有）</span>;
  if (typeof v === "boolean") return v ? "是" : "否";
  if (Array.isArray(v))
    return (
      <ul className="pset-list">
        {v.map((x, i) => (
          <li key={i}>{humanText(typeof x === "object" ? JSON.stringify(x) : String(x))}</li>
        ))}
      </ul>
    );
  if (typeof v === "object")
    return (
      <ul className="pset-list">
        {Object.entries(v as Record<string, unknown>).map(([k, x]) => (
          <li key={k}>
            <b>{humanText(k)}</b>：{humanText(typeof x === "object" ? JSON.stringify(x) : String(x))}
          </li>
        ))}
      </ul>
    );
  return <span className="pset-pre">{humanText(String(v))}</span>;
}

/** 编辑框的草稿值：paths 用多行文字，其余照原值 */
const toDraft = (it: Item): unknown => (it.type === "paths" ? ((it.value as string[] | null) ?? []).join("\n") : it.value);
const fromDraft = (it: Item, d: unknown): unknown =>
  it.type === "paths"
    ? String(d ?? "")
        .split(/\r?\n/)
        .map((x) => x.trim())
        .filter(Boolean)
    : it.type === "number"
      ? Number(d)
      : d;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function Editor({ it, draft, set, disabled }: { it: Item; draft: unknown; set: (v: unknown) => void; disabled: boolean }) {
  const id = `pset-${it.id}`;
  switch (it.type) {
    case "bool":
      return (
        <label className="v3p-check">
          <input id={id} type="checkbox" checked={!!draft} disabled={disabled} title={disabled ? "登录项目方账户后才能改（保存中时请稍等）" : undefined} onChange={(e) => set(e.target.checked)} /> {draft ? "是" : "否"}
        </label>
      );
    case "select": {
      const opts = it.options ?? [];
      const idx = opts.findIndex(([k]) => k === draft);
      return (
        <select id={id} value={idx < 0 ? "" : String(idx)} disabled={disabled} title={disabled ? "登录项目方账户后才能改（保存中时请稍等）" : undefined} onChange={(e) => set(opts[Number(e.target.value)]?.[0])}>
          {idx < 0 && <option value="">（当前值不在选项里：{String(draft)}）</option>}
          {opts.map(([k, l], i) => (
            <option key={String(k)} value={String(i)}>
              {l}
              {typeof k === "string" && k !== l ? `（${k}）` : ""}
            </option>
          ))}
        </select>
      );
    }
    case "number":
      return (
        <span className="pset-num">
          <input
            type="range"
            min={it.min ?? 0}
            max={it.max ?? 1}
            step={0.05}
            value={Number(draft) || 0}
            disabled={disabled} title={disabled ? "登录项目方账户后才能改（保存中时请稍等）" : undefined}
            onChange={(e) => set(Number(e.target.value))}
            aria-label={`${it.label}（滑块）`}
          />
          <input id={id} type="number" min={it.min ?? undefined} max={it.max ?? undefined} step={0.05} value={String(draft ?? "")} disabled={disabled} title={disabled ? "登录项目方账户后才能改（保存中时请稍等）" : undefined} onChange={(e) => set(e.target.value)} />
        </span>
      );
    case "longtext":
    case "paths":
      return (
        <textarea
          id={id}
          rows={it.type === "paths" ? Math.max(2, String(draft ?? "").split("\n").length) : Math.min(8, Math.max(2, Math.ceil(String(draft ?? "").length / 60)))}
          value={String(draft ?? "")}
          disabled={disabled} title={disabled ? "登录项目方账户后才能改（保存中时请稍等）" : undefined}
          placeholder={it.type === "paths" ? "一行一个路径" : undefined}
          onChange={(e) => set(e.target.value)}
        />
      );
    default:
      return <input id={id} value={String(draft ?? "")} disabled={disabled} title={disabled ? "登录项目方账户后才能改（保存中时请稍等）" : undefined} onChange={(e) => set(e.target.value)} />;
  }
}

function Row({ it, canEdit, onSaved }: { it: Item; canEdit: boolean; onSaved: (n: Item) => void }) {
  const [draft, setDraft] = useState<unknown>(() => toDraft(it));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<{ prev: unknown; backup: string | null } | null>(null);
  useEffect(() => setDraft(toDraft(it)), [it]);
  const dirty = it.status === "edit" && !same(fromDraft(it, draft), it.value);
  const save = async (value: unknown, expect: unknown, undo = false) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await putItem(it.id, value, expect);
      onSaved(r.item);
      setDone(undo || r.unchanged ? null : { prev: r.prev, backup: r.backup });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const st = STATUS[it.status];
  return (
    <article className={`pset-row ${it.status}`} aria-labelledby={`pset-l-${it.id}`}>
      <div className="pset-row-head">
        {it.status === "edit" && canEdit ? (
          <label id={`pset-l-${it.id}`} htmlFor={`pset-${it.id}`} className="pset-label">
            {humanText(it.label)}
          </label>
        ) : (
          <span id={`pset-l-${it.id}`} className="pset-label pset-label-ro">
            {humanText(it.label)}
          </span>
        )}
        <Tag tone={st.tone} pill size="s" title={st.tip}>
          {st.label}
        </Tag>
        <span className="grow" />
        <span className="v3p-muted v3p-small" title="旧版「新建剧」向导里的位置">
          旧版：{humanText(it.legacy)}
        </span>
      </div>

      {it.status === "edit" ? (
        <div className="pset-edit">
          {it.type === "paths" ? (
            // 路径类设置：平时只显示文件名（人话），要改文件位置再展开“技术细节”（UIMASTER：界面不直接露路径）
            <>
              <ul className="pset-list">
                {((it.value as string[] | null) ?? []).map((x) => (
                  <li key={x}>{x.split("/").pop()?.replace(/\.(md|txt|json)$/i, "")}</li>
                ))}
              </ul>
              <details className="pset-tech v3p-small">
                <summary>技术细节：改文件位置</summary>
                <Editor it={it} draft={draft} set={(v) => (setDraft(v), setDone(null))} disabled={!canEdit || busy} />
              </details>
            </>
          ) : (
            <Editor it={it} draft={draft} set={(v) => (setDraft(v), setDone(null))} disabled={!canEdit || busy} />
          )}
          <div className="v3p-actions">
            <Button size="sm" variant="primary" disabled={!dirty || !canEdit || busy} why={!canEdit ? "登录项目方账户后才能改" : busy ? "正在保存" : "没有改动"} onClick={() => void save(fromDraft(it, draft), it.value)}>
              {busy ? "正在保存…" : "保存"}
            </Button>
            {dirty && (
              <Button size="sm" variant="ghost" onClick={() => setDraft(toDraft(it))}>
                放弃改动
              </Button>
            )}
            {done && (
              <>
                <span className="ok v3p-small" title={done.backup ? `备份：${done.backup}` : undefined}>已保存{done.backup ? "（改之前的版本已备份）" : ""}</span>
                <Button size="xs" variant="ghost" disabled={busy} onClick={() => void save(done.prev, it.value, true)} title="把这一项改回保存前的值">
                  撤销这次修改
                </Button>
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="pset-val">{it.error ? <span className="v3p-muted">{it.error}</span> : show(it.value, it.options)}</div>
      )}

      {it.also.map((a) => (
        <div key={a.source} className="pset-also v3p-small">
          <span className="v3p-muted">{humanText(a.label)}：</span>
          {show(a.value)}
        </div>
      ))}
      {it.hint && <p className="pset-hint">{humanText(it.hint)}</p>}
      {it.status === "merged" && it.merged_into && (
        <p className="pset-note merged">
          <b>已并入</b> {humanText(it.merged_into)}
          {placeOf(it.merged_into) && (
            <>
              {" "}
              <a className="v3p-link" href={placeOf(it.merged_into)!.href}>
                {placeOf(it.merged_into)!.label} ›
              </a>
            </>
          )}
        </p>
      )}
      {it.status === "readonly" && it.edit_where && (
        <p className="pset-note">
          要改请看：{humanText(it.edit_where)}
          {placeOf(it.edit_where) && (
            <>
              {" "}
              <a className="v3p-link" href={placeOf(it.edit_where)!.href}>
                {placeOf(it.edit_where)!.label} ›
              </a>
            </>
          )}
        </p>
      )}
      {/* 原始文件位置收进“技术细节”，默认收起（界面不直接露路径） */}
      {(it.source || it.also.length > 0) && (
        <details className="pset-tech v3p-small">
          <summary>技术细节</summary>
          {it.source && <code className="mono pset-src">{it.source}</code>}
          {it.also.map((a) => (
            <code key={a.source} className="mono pset-src">
              {a.source}
            </code>
          ))}
        </details>
      )}
      {err && (
        <p className="v3p-err v3p-small" role="alert">
          没保存：{err}
        </p>
      )}
    </article>
  );
}

type Filter = "all" | Status;

export function ProjectSettingsPage() {
  const { me } = useMe();
  const [d, setD] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  // 登录了但不是项目方：不能改；没有登录功能（旧后台）时交给后台判断
  const canEdit = !me || me.role === "owner";
  const load = useCallback(() => {
    setErr(null);
    call<Resp>("/api/project-settings").then(setD, (e) => setErr((e as Error).message));
  }, []);
  useEffect(load, [load]);
  const onSaved = (n: Item) => setD((old) => (old ? { ...old, items: old.items.map((x) => (x.id === n.id ? n : x)) } : old));

  const counts = useMemo(() => {
    const c = { all: 0, edit: 0, readonly: 0, merged: 0 } as Record<Filter, number>;
    for (const x of d?.items ?? []) {
      c.all++;
      c[x.status]++;
    }
    return c;
  }, [d]);
  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    return (d?.items ?? []).filter(
      (x) =>
        (filter === "all" || x.status === filter) &&
        (!k || [x.label, x.legacy, x.source, x.merged_into, x.edit_where, x.hint, typeof x.value === "string" ? x.value : JSON.stringify(x.value)].some((s) => (s ?? "").toLowerCase().includes(k))),
    );
  }, [d, filter, q]);

  return (
    <div className="v3p-page pset-page">
      <header className="v3p-head">
        <h1>项目设置</h1>
        <span className="v3p-muted">旧版「新建剧」向导里的每一项设置都在这里：现在的值、存在哪个文件；能改的直接改，改不了的写明去哪改或已并入哪里</span>
      </header>

      <div className="v3p-card pset-bar">
        <div className="v3p-actions">
          <Seg<Filter>
            value={filter}
            onChange={setFilter}
            label="按状态筛选"
            options={[
              ["all", `全部 ${counts.all}`],
              ["edit", `可改 ${counts.edit}`],
              ["readonly", `只读 ${counts.readonly}`],
              ["merged", `已并入 ${counts.merged}`],
            ]}
          />
          <input className="pset-search" type="search" placeholder="搜设置名、旧版位置、文件…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="搜索设置" />
          <span className="grow" />
          <Button size="sm" variant="ghost" onClick={load}>
            刷新
          </Button>
        </div>
        <p className="v3p-muted v3p-small pset-intro">
          改动只写回那一个键，文件里的其它内容和格式不动；每次保存前把原文件整份备份<span title={d?.backups ?? undefined}>（备份位置在技术细节里）</span>，并记入操作记录。
          {!canEdit && <b className="warn"> 你登录的不是项目方账户，只能看不能改。</b>}
        </p>
      </div>

      {err && <LoadError what="项目设置" err={err} retry={load} />}
      {!d && !err && (
        <div className="pset-skel">
          {[0, 1, 2].map((i) => (
            <Skel key={i} h={140} r="var(--r-l)" />
          ))}
        </div>
      )}
      {d && shown.length === 0 && <Empty title="没有符合条件的设置" sub="换个筛选或搜索词" />}
      {d &&
        d.groups.map((g) => {
          const list = shown.filter((x) => x.group === g);
          if (!list.length) return null;
          return (
            <section key={g} className="v3p-card pset-group" aria-label={g}>
              <div className="v3p-card-head">
                <h2>{g}</h2>
                <span className="v3p-muted v3p-small">
                  {list.length} 项 · 可改 {list.filter((x) => x.status === "edit").length}
                </span>
              </div>
              <div className="pset-rows">
                {list.map((it) => (
                  <Row key={it.id} it={it} canEdit={canEdit} onSaved={onSaved} />
                ))}
              </div>
            </section>
          );
        })}
      {/* W5 UIUX 11-03（L-146 旧功能不删只移位）：全部页面索引——顶部只留步骤条 / 待办 / 设置，其余页面都能从这里点进去 */}
      <section className="v3p-card pset-group" aria-label="全部页面" id="all-pages">
        <div className="v3p-card-head">
          <h2>全部页面</h2>
          <span className="v3p-muted v3p-small">顶部导航收起来的页面都在这里；工程页在“设置 › 高级”</span>
        </div>
        <AllPages />
      </section>
    </div>
  );
}

export default ProjectSettingsPage;
