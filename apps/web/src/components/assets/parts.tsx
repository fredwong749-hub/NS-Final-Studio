import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api";
import type {
  AssetCatalog,
  AssetEntry,
  CharacterAssets,
  ItemImage,
  Look,
  LookView,
  WardrobeItemView,
} from "../../types";
import { fmtTime } from "../../util";
import "../../assets.css";

// ---------------------------------------------------------------- 常量

export const PLATE_LABEL: Record<string, string> = { front: "正", "3q": "3/4", side: "侧", back: "背" };
export const CAT_LABEL: Record<string, string> = { outfit: "衣", shoes: "鞋", nails: "美甲", hair: "发型", makeup: "妆", accessory: "饰" };
export const ROW_SLOTS = ["outfit", "shoes", "nails", "hair", "makeup", "accessory"] as const;
export const VARIANT_LABEL: Record<string, string> = { clean: "特写", worn: "上身", front: "正", "3q": "3/4", side: "侧", back: "背" };
export const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
export const LOOK_COLORS = ["#5b9dff", "#e6b13c", "#3fbf7f", "#e07bb5", "#b48cff", "#ef8a5a", "#4fc6c6", "#c9d35b"];

export type Schedule = Awaited<ReturnType<typeof api.looks.schedule>>;
export type Sel =
  | { kind: "entry"; entry: AssetEntry }
  | { kind: "item"; id: string }
  | { kind: "look"; id: string }
  | null;
export interface GenDraft {
  target: string;
  prompt: string;
  references: string[];
  name: string;
}

/** 造型字母：优先 label；没设时默认造型给 A（不用名字首字，免得“默 默认”重复），其余取名字首字 / id 末位 */
export const lookLetter = (lk: Pick<Look, "label" | "name" | "id"> | undefined) =>
  lk
    ? lk.label || (/默认|default/i.test(`${lk.name ?? ""} ${lk.id}`) ? "A" : lk.name ? lk.name.slice(0, 1) : lk.id.slice(-1).toUpperCase())
    : "?";

export function stripLook(lk: Look | LookView): Look {
  return {
    id: lk.id,
    character: lk.character,
    name: lk.name,
    items: lk.items,
    decor_state: lk.decor_state,
    reference_images: lk.reference_images,
    needs_review: lk.needs_review,
    notes: lk.notes,
    label: lk.label ?? null,
    preview_image: lk.preview_image ?? null,
    version: lk.version ?? 1,
  };
}

/** 单品某个变体的最新图 */
export function latestImage(it: WardrobeItemView, variants: string[]): ItemImage | undefined {
  return [...it.image_urls].filter((im) => variants.includes(im.variant) && im.url).sort((a, b) => b.version - a.version)[0];
}

export function faceFile(ch: CharacterAssets): string | null {
  return ch.plates.front?.file ?? ch.portraits[0]?.file ?? null;
}

// ---------------------------------------------------------------- 小组件

export function Section({ n, title, hint, children, extra }: { n: string; title: string; hint?: string; children: ReactNode; extra?: ReactNode }) {
  return (
    <section className="as-sec">
      <div className="as-sec-head">
        <b>
          {n} {title}
        </b>
        {hint && <span className="muted small">{hint}</span>}
        <span className="grow" />
        {extra}
      </div>
      {children}
    </section>
  );
}

export function EmptyState({ text, children }: { text: string; children?: ReactNode }) {
  return (
    <div className="as-empty">
      <span className="muted">{text}</span>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- ④ 造型组合器

export function LookComposer({
  ch,
  decorStates,
  busy,
  hl,
  onSelect,
  onGen,
  onSave,
  onDefault,
}: {
  ch: CharacterAssets;
  decorStates: string[];
  busy: boolean;
  hl: string | null;
  onSelect: (id: string) => void;
  onGen: (target: string, prompt?: string, refs?: string[] | null, name?: string) => void;
  onSave: (lk: Look, isNew: boolean) => void;
  onDefault: (id: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, Look>>({});
  const [added, setAdded] = useState<Look[]>([]);
  useEffect(() => {
    setDrafts({});
    setAdded((a) => a.filter((x) => x.character === ch.id && !ch.looks.some((l) => l.id === x.id)));
  }, [ch]);
  const byId = useMemo(() => new Map(ch.wardrobe.map((w) => [w.id, w])), [ch.wardrobe]);
  const cols: { base: Look | LookView; isNew: boolean }[] = [
    ...ch.looks.map((l) => ({ base: l as Look | LookView, isNew: false })),
    ...added.map((l) => ({ base: l, isNew: true })),
  ];
  const used = new Set(cols.map((c) => (drafts[c.base.id] ?? c.base).label).filter(Boolean));

  const edit = (lk: Look, fn: (l: Look) => Look) => setDrafts((d) => ({ ...d, [lk.id]: fn({ ...lk, items: { ...lk.items } }) }));
  const addItem = (lk: Look, slot: string, id: string) =>
    edit(lk, (l) => ({ ...l, items: { ...l.items, [slot]: [...(l.items[slot] ?? []).filter((x) => x !== id), id] } }));
  const delItem = (lk: Look, slot: string, id: string) =>
    edit(lk, (l) => {
      const rest = (l.items[slot] ?? []).filter((x) => x !== id);
      const items = { ...l.items };
      if (rest.length) items[slot] = rest;
      else delete items[slot];
      return { ...l, items };
    });

  const newLook = () => {
    const letter = LETTERS.find((x) => !used.has(x)) ?? "Z";
    let id = `${ch.id}-look-${letter.toLowerCase()}`;
    while (cols.some((c) => c.base.id === id)) id += "x";
    setAdded((a) => [
      ...a,
      { id, character: ch.id, name: `造型 ${letter}`, items: {}, decor_state: null, reference_images: [], needs_review: false, notes: [], label: letter, preview_image: null, version: 1 },
    ]);
  };

  return (
    <Section
      n="④"
      title="造型组合器 A/B/C"
      hint="把单品卡拖进格子即可组合；保存后显示影响镜头数，不会自动重渲"
      extra={
        <button className="btn-mini" onClick={newLook}>
          + 新造型
        </button>
      }
    >
      {!cols.length ? (
        <EmptyState text="这个角色还没有命名造型">
          <button className="btn-mini" onClick={newLook}>
            + 新造型
          </button>
        </EmptyState>
      ) : (
        <div className="composer">
          <table>
            <thead>
              <tr>
                <th />
                {cols.map(({ base, isNew }) => {
                  const lk = drafts[base.id] ?? base;
                  const pv = "preview_url" in base ? base.preview_url : null;
                  const dirty = isNew || !!drafts[base.id];
                  const refs = [faceFile(ch), ...Object.values(lk.items).flat().map((i) => byId.get(i)?.image_urls.at(-1)?.file ?? null)].filter(
                    (x): x is string => !!x,
                  );
                  return (
                    <th key={base.id} id={`look-col-${base.id}`} className={`look-col${hl === base.id ? " hl" : ""}`} onClick={() => !isNew && onSelect(base.id)}>
                      <div className="look-col-head">
                        <select
                          value={lk.label ?? ""}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => edit(lk, (l) => ({ ...l, label: e.target.value || null }))}
                          title="造型字母"
                        >
                          <option value="">—</option>
                          {LETTERS.slice(0, 8).map((x) => (
                            <option key={x} value={x}>
                              {x}
                            </option>
                          ))}
                        </select>
                        <input
                          value={lk.name}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => edit(lk, (l) => ({ ...l, name: e.target.value }))}
                          placeholder="造型名"
                        />
                      </div>
                      <div className="look-preview">
                        {pv ? <img src={pv} alt="" /> : <span className="muted small">无预览</span>}
                      </div>
                      <div className="look-col-actions" onClick={(e) => e.stopPropagation()}>
                        <button className="btn-mini" onClick={() => onGen(`look/${base.id}`, "", refs, lk.name)}>
                          生成预览
                        </button>
                        <button className={`btn-mini${dirty ? " on" : ""}`} disabled={busy || !dirty} onClick={() => onSave(lk, isNew)}>
                          保存
                        </button>
                        {dirty && !isNew && (
                          <button className="btn-mini" onClick={() => setDrafts((d) => Object.fromEntries(Object.entries(d).filter(([k]) => k !== base.id)))}>
                            放弃
                          </button>
                        )}
                        {isNew && (
                          <button className="btn-mini" onClick={() => setAdded((a) => a.filter((x) => x.id !== base.id))}>
                            移除
                          </button>
                        )}
                      </div>
                      <div className="small muted">
                        {ch.default_look_id === base.id ? (
                          <span className="badge b-active">默认</span>
                        ) : (
                          !isNew && (
                            <a
                              onClick={(e) => {
                                e.stopPropagation();
                                onDefault(base.id);
                              }}
                            >
                              设为默认
                            </a>
                          )
                        )}{" "}
                        {"used_by_shots" in base ? `用于 ${base.used_by_shots} 镜` : "未保存"}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {ROW_SLOTS.map((slot) => (
                <tr key={slot}>
                  <th className="row-h">{CAT_LABEL[slot]}</th>
                  {cols.map(({ base }) => {
                    const lk = drafts[base.id] ?? base;
                    const ids = lk.items[slot] ?? [];
                    const opts = ch.wardrobe.filter((w) => w.slot === slot && !ids.includes(w.id));
                    return (
                      <td
                        key={base.id}
                        className="look-cell"
                        onDragOver={(e) => e.dataTransfer.types.includes("text/ns-item") && e.preventDefault()}
                        onDrop={(e) => {
                          const id = e.dataTransfer.getData("text/ns-item");
                          const s = e.dataTransfer.getData("text/ns-slot");
                          if (!id) return;
                          e.preventDefault();
                          addItem(lk, s && s !== "other" ? s : slot, id);
                        }}
                      >
                        {ids.map((i) => {
                          const w = byId.get(i);
                          return (
                            <span key={i} className={`cell-item${w?.has_image ? "" : " no-img"}`} title={w ? `${w.name}${w.has_image ? "" : "（缺图，只用文字描述）"}` : `未知单品 ${i}`}>
                              {w?.thumb_url ? <img src={w.thumb_url} alt="" /> : <span className="ci-empty" />}
                              <span className="ci-name">{w?.name ?? i}</span>
                              <button className="ci-x" onClick={() => delItem(lk, slot, i)} title="移出">
                                ×
                              </button>
                            </span>
                          );
                        })}
                        {opts.length > 0 && (
                          <select className="cell-add" value="" onChange={(e) => e.target.value && addItem(lk, slot, e.target.value)}>
                            <option value="">+ 加</option>
                            {opts.map((w) => (
                              <option key={w.id} value={w.id}>
                                {w.name}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr>
                <th className="row-h">D 状态</th>
                {cols.map(({ base }) => {
                  const lk = drafts[base.id] ?? base;
                  return (
                    <td key={base.id} className="look-cell">
                      <select value={lk.decor_state ?? ""} onChange={(e) => edit(lk, (l) => ({ ...l, decor_state: e.target.value || null }))}>
                        <option value="">（不指定）</option>
                        {decorStates.map((d) => (
                          <option key={d} value={d}>
                            {d}
                          </option>
                        ))}
                      </select>
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------- ⑤ 排期

export function ScheduleMatrix({
  cat,
  sched,
  nEp,
  cid,
  busy,
  onOpenEp,
  onApply,
}: {
  cat: AssetCatalog;
  sched: Schedule | null;
  nEp: number;
  cid: string;
  busy: boolean;
  onOpenEp: (n: number) => void;
  onApply: (char: string, text: string, lookId: string) => void;
}) {
  const [char, setChar] = useState(cid);
  const [text, setText] = useState("");
  const [lookId, setLookId] = useState("");
  useEffect(() => setChar(cid), [cid]);
  const allLooks = useMemo(() => new Map(cat.characters.flatMap((c) => c.looks.map((l) => [l.id, l] as const))), [cat]);
  const colorOf = useMemo(() => {
    const m = new Map<string, string>();
    [...allLooks.keys()].forEach((id, i) => m.set(id, LOOK_COLORS[i % LOOK_COLORS.length]));
    return m;
  }, [allLooks]);
  const overridden = useMemo(() => {
    const s = new Set<string>();
    for (const [shot, chars] of Object.entries(sched?.shot_overrides ?? {}))
      for (const c of Object.keys(chars)) s.add(`${c}|${Number(shot.slice(2, 4))}`);
    return s;
  }, [sched]);
  if (!sched) return <Section n="⑤" title="排期">{<div className="muted">排期接口不可用</div>}</Section>;
  const eps = Array.from({ length: nEp }, (_, i) => i + 1);
  const rows = cat.characters.filter((c) => c.id === cid || sched.character_defaults[c.id] || Object.values(sched.episodes).some((e) => e[c.id]));
  const charLooks = cat.characters.find((c) => c.id === char)?.looks ?? [];
  return (
    <Section n="⑤" title="排期：角色 × 集" hint="格子 = 造型字母；◆ = 该集有单镜覆盖；• = 集计划改了单品/D 状态；点格子打开该集">
      <div className="sched-wrap">
        <table className="sched">
          <thead>
            <tr>
              <th />
              {eps.map((n) => (
                <th key={n} className={n % 5 === 0 ? "five" : ""}>
                  {n % 5 === 0 || n === 1 ? n : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              let prev: string | null = null;
              return (
                <tr key={c.id} className={c.id === cid ? "cur" : ""}>
                  <th className="row-h">{c.name}</th>
                  {eps.map((n) => {
                    const patch = sched.episodes[String(n)]?.[c.id];
                    const lid = patch?.look_id ?? sched.character_defaults[c.id] ?? null;
                    const lk = lid ? allLooks.get(lid) : undefined;
                    const cont = lid === prev;
                    prev = lid;
                    const tweak = !!(patch && (patch.slots || patch.d_state || patch.visibility));
                    return (
                      <td
                        key={n}
                        className={`sc${cont ? " cont" : ""}`}
                        style={{ background: lid ? `${colorOf.get(lid) ?? "#555"}33` : undefined, borderLeftColor: lid && !cont ? colorOf.get(lid) : undefined }}
                        title={`ep${String(n).padStart(2, "0")} · ${c.name}：${lk ? `${lookLetter(lk)} ${lk.name}` : lid ?? "无"}${patch?.d_state ? ` · ${patch.d_state}` : ""}`}
                        onClick={() => onOpenEp(n)}
                      >
                        {!cont && lid ? lookLetter(lk) : ""}
                        {tweak && <i className="sc-tweak">•</i>}
                        {overridden.has(`${c.id}|${n}`) && <i className="sc-ov">◆</i>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="sched-form">
        <select value={char} onChange={(e) => setChar(e.target.value)}>
          {cat.characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="集号，如 1-8, 17" />
        <select value={lookId} onChange={(e) => setLookId(e.target.value)}>
          <option value="">选造型…</option>
          {charLooks.map((l) => (
            <option key={l.id} value={l.id}>
              {lookLetter(l)} · {l.name || l.id}
            </option>
          ))}
          <option value="__default">恢复默认（删除集计划）</option>
        </select>
        <button className="btn-mini" disabled={busy || !text.trim() || !lookId} onClick={() => onApply(char, text, lookId)}>
          应用
        </button>
        <span className="muted small">写错集号会被后端拒绝（422），不会猜</span>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- 右侧：选中项检查器 / 出图表单

export function SelInspector({
  ch,
  sel,
  variants,
  busy,
  onUpload,
  onGen,
  onImport,
}: {
  ch: CharacterAssets;
  sel: NonNullable<Sel>;
  variants: string[];
  busy: boolean;
  onUpload: (id: string, f: File, variant: string) => void;
  onGen: (target: string, prompt?: string, refs?: string[] | null, name?: string) => void;
  onImport: () => void;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [variant, setVariant] = useState("clean");
  if (sel.kind === "entry") {
    const e = sel.entry;
    const w = e.registered_item_id ? ch.wardrobe.find((x) => x.id === e.registered_item_id) : undefined;
    return (
      <div className="si">
        <div className="si-img">{e.url ? <img src={e.url} alt="" /> : <div className="thumb-empty">文件缺失</div>}</div>
        <h3>{e.design ? `${e.design} · ${e.name ?? ""}` : e.name || e.category}</h3>
        <dl className="si-kv">
          <KV k="kind" v={e.kind} />
          <KV k="文件" v={e.file} />
          <KV k="manifest" v={e.manifest ?? "（无，loose 文件）"} />
          <KV k="prompt" v={e.prompt} />
          <KV k="seed" v={e.seed != null ? String(e.seed) : null} />
          <KV k="model" v={e.model} />
          <KV k="workflow" v={e.workflow} />
          <KV k="references" v={e.references?.length ? e.references.join("\n") : null} />
          <KV k="sha256" v={e.sha256} />
          <KV k="生成时间" v={e.created_at ? fmtTime(e.created_at) : null} />
        </dl>
        <div className="si-sub">引用</div>
        {e.group === "item" ? (
          w ? (
            <div className="small">
              已登记为 <b>{w.id}</b>：被 {w.used_by_looks.length} 个造型（{w.used_by_looks.join("、") || "—"}）/ {w.used_by_shots} 镜使用
            </div>
          ) : (
            <div className="small warn">
              未登记进衣橱，造型和镜头还用不到它{" "}
              <button className="btn-mini" disabled={busy} onClick={onImport}>
                导入 manifest
              </button>
            </div>
          )
        ) : e.group === "plate" && e.category === "front" ? (
          <div className="small">正面 plate = 镜头卡脸图、参考图组第 1 张</div>
        ) : (
          <div className="small muted">—</div>
        )}
        <div className="row-actions">
          <button className="btn" onClick={() => onGen(e.kind, e.prompt ?? "", e.references ?? null, e.name ?? "")}>
            重新生成
          </button>
        </div>
      </div>
    );
  }
  if (sel.kind === "item") {
    const w = ch.wardrobe.find((x) => x.id === sel.id);
    if (!w) return <div className="muted pad">单品 {sel.id} 不在 {ch.name} 的衣橱里</div>;
    const main = latestImage(w, ["clean", "front"]) ?? latestImage(w, variants);
    return (
      <div className="si">
        <div className="si-img">{main?.url ? <img src={main.url} alt="" /> : w.thumb_url ? <img src={w.thumb_url} alt="" /> : <div className="thumb-empty">缺图（只用文字描述）</div>}</div>
        <h3>
          {w.name} <span className="muted small">v{w.version}</span>
        </h3>
        <dl className="si-kv">
          <KV k="id" v={w.id} />
          <KV k="插槽" v={CAT_LABEL[w.slot] ?? w.slot} />
          <KV k="提示词描述" v={w.description || "（空：不进提示词）"} />
          <KV k="LoRA" v={w.trigger ? `${w.trigger} · ${w.lora_file ?? ""}` : null} />
          <KV k="标签" v={w.tags.join("、") || null} />
          <KV k="关键词" v={w.keywords.join("、") || null} />
          <KV k="参考图" v={w.reference_images.join("\n") || null} />
          <KV k="来源" v={w.source} />
        </dl>
        {w.image_urls.length > 0 && (
          <>
            <div className="si-sub">全部版本（旧版本保留）</div>
            <div className="si-versions">
              {[...w.image_urls].sort((a, b) => b.version - a.version).map((im) => (
                <figure key={im.file + im.version}>
                  {im.url ? <img src={im.url} alt="" /> : <div className="thumb-empty">缺</div>}
                  <figcaption className="small">
                    v{im.version} · {VARIANT_LABEL[im.variant] ?? im.variant} · {im.source}
                  </figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
        <div className="si-sub">引用</div>
        <div className="small">
          被 {w.used_by_looks.length} 个造型（{w.used_by_looks.join("、") || "—"}）/ {w.used_by_shots} 镜使用
        </div>
        {w.notes.map((n, i) => (
          <div key={i} className="small muted">
            · {n}
          </div>
        ))}
        <div className="row-actions">
          <select value={variant} onChange={(e) => setVariant(e.target.value)}>
            {variants.map((v) => (
              <option key={v} value={v}>
                {VARIANT_LABEL[v] ?? v}
              </option>
            ))}
          </select>
          <button className="btn" disabled={busy} onClick={() => file.current?.click()}>
            上传新版本
          </button>
          <input
            ref={file}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(w.id, f, variant);
              e.target.value = "";
            }}
          />
          <button className="btn" onClick={() => onGen(`item/${w.slot === "other" ? "accessory" : w.slot}`, w.description, null, w.name)}>
            重新生成
          </button>
        </div>
      </div>
    );
  }
  const lk = ch.looks.find((l) => l.id === sel.id);
  if (!lk) return <div className="muted pad">造型 {sel.id} 未保存或不存在</div>;
  const byId = new Map(ch.wardrobe.map((w) => [w.id, w]));
  return (
    <div className="si">
      <div className="si-img">{lk.preview_url ? <img src={lk.preview_url} alt="" /> : <div className="thumb-empty">没有预览图（looks/）</div>}</div>
      <h3>
        {lookLetter(lk)} · {lk.name || lk.id}
      </h3>
      <dl className="si-kv">
        <KV k="id" v={lk.id} />
        <KV k="D 状态" v={lk.decor_state} />
        {Object.entries(lk.items).map(([slot, ids]) => (
          <KV key={slot} k={CAT_LABEL[slot] ?? slot} v={ids.map((i) => byId.get(i)?.name ?? i).join("、")} />
        ))}
        <KV k="用于" v={`${lk.used_by_shots} 镜`} />
        <KV k="备注" v={lk.notes.join("\n") || null} />
      </dl>
      <div className="row-actions">
        <button
          className="btn"
          onClick={() =>
            onGen(
              `look/${lk.id}`,
              "",
              [faceFile(ch), ...Object.values(lk.items).flat().map((i) => byId.get(i)?.image_urls.at(-1)?.file ?? null)].filter((x): x is string => !!x),
              lk.name,
            )
          }
        >
          生成预览
        </button>
      </div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: ReactNode }) {
  if (v == null || v === "") return null;
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

export function GenerateForm({
  ch,
  draft,
  maxRefs,
  busy,
  onChange,
  onCancel,
  onSubmit,
}: {
  ch: CharacterAssets;
  draft: GenDraft;
  maxRefs: number;
  busy: boolean;
  onChange: (d: GenDraft) => void;
  onCancel: () => void;
  onSubmit: (d: GenDraft, model: "qwen" | "klein", seed: string) => void;
}) {
  const [model, setModel] = useState<"qwen" | "klein">("qwen");
  const [seed, setSeed] = useState("");
  // 可选参考图：脸 / plates / 表情 / 资产文件 / 衣橱单品图
  const cands = useMemo(() => {
    const m = new Map<string, { file: string; url: string | null; label: string }>();
    const add = (file: string | null | undefined, url: string | null | undefined, label: string) => {
      if (file && !m.has(file)) m.set(file, { file, url: url ?? null, label });
    };
    for (const [v, e] of Object.entries(ch.plates)) add(e?.file, e?.url, `plate ${PLATE_LABEL[v] ?? v}`);
    for (const e of ch.portraits) add(e.file, e.url, "定妆原图");
    for (const w of ch.wardrobe) for (const im of w.image_urls) add(im.file, im.url, `${w.name} ${VARIANT_LABEL[im.variant] ?? im.variant} v${im.version}`);
    for (const lst of Object.values(ch.items)) for (const e of lst) add(e.file, e.url, `${e.design ?? ""} ${e.name ?? ""}`.trim());
    for (const e of ch.expressions) add(e.file, e.url, `表情 ${e.name ?? e.category}`);
    for (const r of draft.references) add(r, null, r);
    return [...m.values()];
  }, [ch, draft.references]);
  const toggle = (f: string) =>
    onChange({
      ...draft,
      references: draft.references.includes(f) ? draft.references.filter((x) => x !== f) : [...draft.references, f].slice(0, maxRefs),
    });
  const [group, sub] = draft.target.split("/");
  return (
    <div className="gen-form">
      <h3>资产出图 · {ch.name}</h3>
      <label className="gf-row">
        <span>目标</span>
        <input value={draft.target} onChange={(e) => onChange({ ...draft, target: e.target.value })} placeholder="plate/front · expression/<名> · item/<类别> · look/<id>" />
      </label>
      {!sub && <div className="small warn">目标需要写全，如 expression/{"<表情名>"}</div>}
      <label className="gf-row">
        <span>名称</span>
        <input value={draft.name} onChange={(e) => onChange({ ...draft, name: e.target.value })} placeholder="文件名前缀（可选）" />
      </label>
      <label className="gf-col">
        <span>提示词（由 Qwen / 项目方填写，系统原样提交）</span>
        <textarea
          rows={7}
          value={draft.prompt}
          onChange={(e) => onChange({ ...draft, prompt: e.target.value })}
          placeholder="粘贴 Qwen 写好的提示词；参考图顺序见下方「图1、图2…」"
        />
        {!draft.prompt.trim() && <span className="small muted">提示词为空时不能入队</span>}
      </label>
      <div className="gf-col">
        <span>
          参考图（按勾选顺序 = 图1、图2…；最多 {maxRefs} 张，已选 {draft.references.length}）
        </span>
        <div className="gf-refs">
          {cands.length ? (
            cands.map((c) => {
              const i = draft.references.indexOf(c.file);
              return (
                <label key={c.file} className={`gf-ref${i >= 0 ? " on" : ""}`} title={c.file}>
                  <input type="checkbox" checked={i >= 0} onChange={() => toggle(c.file)} />
                  {c.url ? <img src={c.url} alt="" /> : <span className="ci-empty" />}
                  <span className="small">
                    {i >= 0 && <b>图{i + 1} </b>}
                    {c.label}
                  </span>
                </label>
              );
            })
          ) : (
            <span className="muted small">这个角色还没有任何图片；不选参考图则为纯文生图</span>
          )}
        </div>
      </div>
      <div className="gf-row">
        <span>模型</span>
        <select value={model} onChange={(e) => setModel(e.target.value as "qwen" | "klein")}>
          <option value="qwen">Qwen Image 2.1（本机 Turbo）</option>
          <option value="klein" disabled>Klein（未接入）</option>
        </select>
        <span>种子</span>
        <input className="gf-seed" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="随机" inputMode="numeric" />
      </div>
      <div className="row-actions">
        <button className="btn primary" disabled={busy || !draft.prompt.trim() || !sub || !(group in { plate: 1, expression: 1, item: 1, look: 1 })} onClick={() => onSubmit(draft, model, seed)}>
          入队出图
        </button>
        <button className="btn" onClick={onCancel}>
          取消
        </button>
      </div>
      <div className="small muted">在 GPU 队列串行执行；结果存到 {ch.dir}/ 对应目录并追加 manifest，不会自动登记进衣橱、不会重渲镜头。</div>
    </div>
  );
}
