import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { thumb } from "../thumb";
import { manageApi } from "../api";
import { useStudio } from "../store";
import type { PeopleList, Person } from "../types";
import "./people.css";

/** 人物管理（项目方 2026-10-30；fredw-25）：全部人物一览、新建、改名 / 归档、按目标上传图片。
 *  单个人物的造型 / 单品 / 出图在「资产」页角色卡里做，这里点「打开资产」跳过去。系统只管文件与计数，不看图。 */

const PLATE_LABEL: Record<string, string> = { front: "正", "3q": "3/4", side: "侧", back: "背" };
const CAT_LABEL: Record<string, string> = {
  outfit: "服装", shoes: "鞋", nails: "美甲", hair: "发型", makeup: "妆容", accessory: "饰品",
};

/** 上传目标（与 manage.upload_target 一致） */
function targets(views: string[], cats: string[]): [string, string][] {
  return [
    ["plate/master", "写实母版"],
    ...views.map((v): [string, string] => [`plate/${v}`, `身份底板 · ${PLATE_LABEL[v] ?? v}`]),
    ["portrait", "参考图（原始照片 / 定妆参考）"],
    ...cats.map((c): [string, string] => [`item/${c}`, `单品 · ${CAT_LABEL[c] ?? c}`]),
  ];
}

function NewPersonForm({ onDone }: { onDone: (p: Person | null, err?: string) => void }) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z][a-z0-9_]{1,31}$/.test(id) && name.trim().length > 0;
  const submit = async () => {
    setBusy(true);
    try {
      onDone(await manageApi.createPerson({ id, name: name.trim(), role: role.trim() }));
    } catch (e) {
      onDone(null, (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="pp-new">
      <label>
        中文名
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 苏晴" autoFocus />
      </label>
      <label>
        人物 id
        <input
          value={id}
          onChange={(e) => setId(e.target.value.toLowerCase())}
          placeholder="如 su_qing"
          className={id && !valid ? "bad" : ""}
          title="小写字母、数字、下划线，字母开头，2–32 位；建好后不能改（目录名）"
        />
      </label>
      <label className="grow">
        角色说明（可空）
        <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="如 林晚闺蜜" />
      </label>
      <button className="btn primary" disabled={!valid || busy} onClick={submit}>
        {busy ? "建立中…" : "建立人物"}
      </button>
    </div>
  );
}

function Uploader({ p, opts, onDone }: { p: Person; opts: [string, string][]; onDone: (msg: string, err?: boolean) => void }) {
  const [target, setTarget] = useState(opts[1]?.[0] ?? "plate/front");
  const [busy, setBusy] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const send = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => /\.(png|jpe?g|webp)$/i.test(f.name));
    if (!list.length) return onDone("只接受 png / jpg / webp 图片", true);
    let ok = 0;
    const errs: string[] = [];
    for (const [i, f] of list.entries()) {
      setBusy(`上传 ${i + 1}/${list.length}`);
      try {
        await manageApi.upload(p.id, target, f);
        ok++;
      } catch (e) {
        errs.push(`${f.name}：${(e as Error).message}`);
      }
    }
    setBusy("");
    onDone(`${p.name}：已上传 ${ok} 张到「${opts.find((o) => o[0] === target)?.[1]}」${errs.length ? `；失败 ${errs.join("；")}` : ""}`, errs.length > 0);
  };
  return (
    <div
      className={`pp-up${over ? " over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void send(e.dataTransfer.files);
      }}
    >
      <select value={target} onChange={(e) => setTarget(e.target.value)} title="图片存到哪里">
        {opts.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
      <button className="btn-mini" disabled={!!busy} onClick={() => input.current?.click()}>
        {busy || "选图片…"}
      </button>
      <span className="muted small">或把图片拖到这里（可多张）</span>
      <input
        ref={input}
        type="file"
        accept=".png,.jpg,.jpeg,.webp"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) void send(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function PersonCard({
  p, views, cats, opts, onChanged, onMsg,
}: {
  p: Person;
  views: string[];
  cats: string[];
  opts: [string, string][];
  onChanged: () => void;
  onMsg: (m: string, err?: boolean) => void;
}) {
  const { openAssets } = useStudio();
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(p.name);
  const [role, setRole] = useState(p.role);
  const [notes, setNotes] = useState(p.notes);
  const [full, setFull] = useState<string | null>(null);
  useEffect(() => {
    setName(p.name);
    setRole(p.role);
    setNotes(p.notes);
  }, [p.name, p.role, p.notes]);
  const save = async (patch: Parameters<typeof manageApi.updatePerson>[1]) => {
    try {
      await manageApi.updatePerson(p.id, patch);
      setEdit(false);
      onChanged();
    } catch (e) {
      onMsg(`${p.name}：${(e as Error).message}`, true);
    }
  };
  const hero = p.hero_url ?? p.face_url;
  return (
    <article className={`pp-card${p.archived ? " archived" : ""}`}>
      <button className="pp-hero" onClick={() => hero && setFull(hero)} title={hero ? "点开大图" : "还没有图：用下面的上传"}>
        {hero ? <img src={thumb(hero, 360) ?? hero} alt={p.name} loading="lazy" /> : <span className="muted">无图</span>}
      </button>
      <div className="pp-body">
        <header>
          {edit ? (
            <input className="pp-name-in" value={name} onChange={(e) => setName(e.target.value)} />
          ) : (
            <b className="pp-name">{p.name}</b>
          )}
          <code className="muted small">{p.id}</code>
          {p.archived && <span className="pp-tag">已归档</span>}
          {p.missing_count > 0 && (
            <span className="pp-tag bad" title={p.missing.join("\n")}>
              缺图 {p.missing_count}
            </span>
          )}
          <span className="grow" />
          <button className="btn-mini" onClick={() => openAssets({ character: p.id })} title="资产页：造型 A/B/C、单品、出图">
            打开资产
          </button>
        </header>
        {edit ? (
          <div className="pp-edit">
            <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="角色说明" />
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="备注" rows={2} />
            <div className="pp-row">
              <button className="btn-mini on" onClick={() => save({ name, role, notes })} disabled={!name.trim()}>
                保存
              </button>
              <button className="btn-mini" onClick={() => setEdit(false)}>
                取消
              </button>
              <span className="grow" />
              <button className="btn-mini" onClick={() => save({ archived: !p.archived })} title="归档只是隐藏，不删任何文件">
                {p.archived ? "恢复" : "归档"}
              </button>
            </div>
          </div>
        ) : (
          <div className="pp-role" onDoubleClick={() => setEdit(true)}>
            {p.role || <span className="muted">（无角色说明）</span>}
            {p.notes && <div className="muted small">{p.notes}</div>}
            <button className="btn-mini pp-edit-btn" onClick={() => setEdit(true)}>
              编辑
            </button>
          </div>
        )}
        <div className="pp-plates">
          {views.map((v) => (
            <button key={v} className={`pp-plate${p.plates[v] ? "" : " empty"}`} onClick={() => p.plates[v] && setFull(p.plates[v])}>
              {p.plates[v] ? <img src={thumb(p.plates[v]!, 240) ?? p.plates[v]!} alt={v} loading="lazy" /> : <span>缺</span>}
              <i>{PLATE_LABEL[v] ?? v}</i>
            </button>
          ))}
        </div>
        <div className="pp-counts">
          <span title="命名造型数（造型 A/B/C）">
            造型 <b>{p.looks}</b>
            {p.look_labels.filter(Boolean).length > 0 && <em> {p.look_labels.filter(Boolean).join("·")}</em>}
          </span>
          {cats.map((c) => (
            <span key={c} className={p.item_counts[c] ? "" : "zero"}>
              {CAT_LABEL[c] ?? c} <b>{p.item_counts[c] ?? 0}</b>
            </span>
          ))}
          <span>
            表情 <b>{p.expressions}</b>
          </span>
          <span title="衣橱里登记的单品数">
            衣橱 <b>{p.wardrobe}</b>
          </span>
          {p.used_by_shots > 0 && (
            <span title="用到该人物造型的镜头数（取最多的一套）">
              入镜 <b>{p.used_by_shots}</b>
            </span>
          )}
          {p.unregistered > 0 && (
            <span className="warn" title="目录里有图但没登记进衣橱：去资产页点「登记」">
              未登记 <b>{p.unregistered}</b>
            </span>
          )}
        </div>
        <Uploader p={p} opts={opts} onDone={(m, e) => (onMsg(m, e), onChanged())} />
      </div>
      {full && (
        <div className="pp-full" onClick={() => setFull(null)} title="点任意处关闭">
          <img src={full} alt="" />
        </div>
      )}
    </article>
  );
}

export function PeoplePage() {
  const [data, setData] = useState<PeopleList | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [q, setQ] = useState("");
  const load = useCallback(async () => {
    try {
      setData(await manageApi.people());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const views = data?.plate_views ?? ["front", "3q", "side", "back"];
  const cats = data?.item_categories ?? Object.keys(CAT_LABEL);
  const opts = useMemo(() => targets(views, cats), [views, cats]);
  const list = (data?.people ?? []).filter(
    (p) => (showArchived || !p.archived) && (!q || `${p.name} ${p.id} ${p.role}`.toLowerCase().includes(q.toLowerCase())),
  );
  const archivedN = (data?.people ?? []).filter((p) => p.archived).length;
  return (
    <div className="pp-view">
      <div className="pp-top">
        <h2>人物管理</h2>
        <span className="muted">{data ? `${data.people.length - archivedN} 个人物` : ""}</span>
        <input className="pp-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索 名字 / id / 角色" />
        {archivedN > 0 && (
          <label className="muted small">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> 显示已归档（{archivedN}）
          </label>
        )}
        <span className="grow" />
        <button className="btn-mini" onClick={load}>
          刷新
        </button>
        <button className="btn primary" onClick={() => setShowNew((v) => !v)}>
          {showNew ? "收起" : "+ 新建人物"}
        </button>
      </div>
      <p className="muted small">
        每个人物的参考图、身份底板、单品（服装 / 鞋 / 美甲 / 发型 / 妆容 / 饰品）在这里上传和清点；造型 A/B/C 组合、每集换装、出图在「资产」页角色卡里做。上传只新增文件，不覆盖旧图。
      </p>
      {showNew && (
        <NewPersonForm
          onDone={(p, e) => {
            if (p) {
              setShowNew(false);
              setMsg({ text: `已建立人物 ${p.name}（assets/characters/${p.id}）` });
              void load();
            } else setMsg({ text: `建立失败：${e}`, err: true });
          }}
        />
      )}
      {msg && (
        <div className={msg.err ? "warn" : "ok-msg"} onClick={() => setMsg(null)}>
          {msg.text}
        </div>
      )}
      {err && <div className="warn">读取失败：{err}（API 需重启才有人物管理接口）</div>}
      <div className="pp-grid">
        {list.map((p) => (
          <PersonCard key={p.id} p={p} views={views} cats={cats} opts={opts} onChanged={load} onMsg={(text, e) => setMsg({ text, err: e })} />
        ))}
        {data && list.length === 0 && <div className="muted">没有匹配的人物</div>}
      </div>
    </div>
  );
}

export default PeoplePage;
