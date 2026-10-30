import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import type { CharacterAssets, ItemImage, LookView, WardrobeItemView } from "../../types";
import { isTypingTarget } from "../../util";
import { faceFile, latestImage, lookLetter, ROW_SLOTS, VARIANT_LABEL, type Schedule, type Sel } from "./parts";

// 资产页 v3.1：小云雀式角色卡（9:16 大定妆图 + 造型 A/B/C 切换 + 单品一目了然 + 用于哪些集 + 全屏看图）
// 本文件只有系统/界面：不生成、不改写、不评价任何内容文字（REQUIREMENTS G1–G5）。

export const CAT_FULL: Record<string, string> = { outfit: "服装", shoes: "鞋", nails: "美甲", hair: "发型", makeup: "妆容", accessory: "饰品" };

// ---------------------------------------------------------------- 工具

/** 单品主图：优先特写/正面的最高版本，其次任意变体最高版本 */
export function itemMainImage(w: WardrobeItemView | undefined): ItemImage | undefined {
  if (!w) return undefined;
  return latestImage(w, ["clean", "front"]) ?? [...w.image_urls].filter((im) => im.url).sort((a, b) => b.version - a.version)[0];
}

/** 单品用作参考的文件：最新版本图，没有版本图时退回登记的参考图 */
export function itemRefFile(w: WardrobeItemView | undefined): string | null {
  return itemMainImage(w)?.file ?? w?.reference_images[0] ?? null;
}

/** 造型出图的参考图：图1 = 身份（母版 → 正面底板），其后按插槽顺序放单品主图；去重并截到 maxRefs */
export function lookRefs(ch: CharacterAssets, lk: LookView, maxRefs: number): { file: string; label: string }[] {
  const byId = new Map(ch.wardrobe.map((w) => [w.id, w]));
  const out: { file: string; label: string }[] = [];
  const add = (file: string | null | undefined, label: string) => {
    if (file && !out.some((x) => x.file === file)) out.push({ file, label });
  };
  add(ch.master?.file ?? faceFile(ch), "身份");
  for (const [slot, ids] of lookSlots(lk)) for (const id of ids) add(itemRefFile(byId.get(id)), CAT_FULL[slot] ?? slot);
  return out.slice(0, Math.max(1, maxRefs));
}

function lookSlots(lk: LookView): [string, string[]][] {
  const known = ROW_SLOTS.map((s) => [s, lk.items[s] ?? []] as [string, string[]]);
  const extra = Object.entries(lk.items).filter(([s]) => !(ROW_SLOTS as readonly string[]).includes(s));
  return [...known, ...extra];
}

export interface LookUsage {
  /** 1-based 集号 → 0 未用 / 1 整集用 / 2 用但本集计划有单品或 D 状态改动 */
  eps: number[];
  count: number;
  shotOverrides: number;
}

/** 由排期（/api/look-schedule）推出造型用于哪些集：显式 look_id 命中，或默认造型且该集没指定别的造型 */
export function lookUsage(sched: Schedule | null, cid: string, lk: LookView, isDefault: boolean, nEp: number): LookUsage {
  const eps: number[] = [];
  let count = 0;
  for (let n = 1; n <= nEp; n++) {
    const plan = sched?.episodes[String(n)]?.[cid];
    const uses = plan?.look_id ? plan.look_id === lk.id : isDefault;
    const tweaked = !!plan && (!!(plan.slots && Object.keys(plan.slots).length) || !!plan.d_state);
    const v = uses ? (tweaked ? 2 : 1) : 0;
    eps.push(v);
    if (v) count++;
  }
  let shotOverrides = 0;
  for (const per of Object.values(sched?.shot_overrides ?? {})) if (per[cid]?.look_id === lk.id) shotOverrides++;
  return { eps, count, shotOverrides };
}

/** [1,2,3,5] → "1–3、5" */
export function epRanges(eps: number[]): { from: number; to: number }[] {
  const r: { from: number; to: number }[] = [];
  eps.forEach((v, i) => {
    if (!v) return;
    const n = i + 1;
    const last = r[r.length - 1];
    if (last && last.to === n - 1) last.to = n;
    else r.push({ from: n, to: n });
  });
  return r;
}

// ---------------------------------------------------------------- 全屏看图

export interface LbItem {
  key: string;
  url: string | null;
  title: string;
  sub?: string;
  /** 同一单品的全部版本（新→旧）；有则 ↑/↓ 切换 */
  versions?: { url: string | null; label: string }[];
  /** 「明细」按钮打开右侧面板 */
  sel?: NonNullable<Sel>;
}

export function Lightbox({
  items,
  index,
  onIndex,
  onClose,
  onDetail,
}: {
  items: LbItem[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  onDetail: (s: NonNullable<Sel>) => void;
}) {
  const it = items[Math.min(index, items.length - 1)];
  const [ver, setVer] = useState(0);
  useEffect(() => setVer(0), [index]);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), []);

  useEffect(() => {
    // capture：先于全局 keymap 和资产页的 Esc 处理，且吞掉事件
    const h = (e: KeyboardEvent) => {
      const nv = it?.versions?.length ?? 0;
      let used = true;
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") onIndex((index - 1 + items.length) % items.length);
      else if (e.key === "ArrowRight" || e.key === " ") onIndex((index + 1) % items.length);
      else if (e.key === "Home") onIndex(0);
      else if (e.key === "End") onIndex(items.length - 1);
      else if (e.key === "ArrowDown" && nv) setVer((v) => Math.min(nv - 1, v + 1));
      else if (e.key === "ArrowUp" && nv) setVer((v) => Math.max(0, v - 1));
      else used = false;
      if (used) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    const up = (e: KeyboardEvent) => e.key === " " && e.stopImmediatePropagation();
    window.addEventListener("keydown", h, true);
    window.addEventListener("keyup", up, true);
    return () => {
      window.removeEventListener("keydown", h, true);
      window.removeEventListener("keyup", up, true);
    };
  }, [it, index, items.length, onClose, onIndex]);

  if (!it) return null;
  const url = it.versions?.length ? it.versions[ver]?.url ?? it.url : it.url;
  return (
    <div className="av3-lb" role="dialog" aria-modal="true" aria-label={it.title} tabIndex={-1} ref={box} onClick={onClose}>
      <div className="av3-lb-top" onClick={(e) => e.stopPropagation()}>
        <b>{it.title}</b>
        {it.sub && <span className="muted">{it.sub}</span>}
        <span className="grow" />
        <span className="muted small">
          {index + 1} / {items.length} · ←/→ 切换{it.versions && it.versions.length > 1 ? " · ↑/↓ 版本" : ""} · Esc 关闭
        </span>
        {it.sel && (
          <button className="btn" onClick={() => (onDetail(it.sel!), onClose())}>
            明细
          </button>
        )}
        <button className="btn" onClick={onClose}>
          关闭 ✕
        </button>
      </div>
      <div className="av3-lb-stage">
        {items.length > 1 && (
          <button className="av3-lb-nav l" aria-label="上一张" onClick={(e) => (e.stopPropagation(), onIndex((index - 1 + items.length) % items.length))}>
            ‹
          </button>
        )}
        {url ? <img src={url} alt={it.title} onClick={(e) => e.stopPropagation()} /> : <div className="av3-lb-none">没有图片</div>}
        {items.length > 1 && (
          <button className="av3-lb-nav r" aria-label="下一张" onClick={(e) => (e.stopPropagation(), onIndex((index + 1) % items.length))}>
            ›
          </button>
        )}
      </div>
      {it.versions && it.versions.length > 1 && (
        <div className="av3-lb-vers" onClick={(e) => e.stopPropagation()}>
          {it.versions.map((v, i) => (
            <button key={i} className={i === ver ? "on" : ""} onClick={() => setVer(i)} title={v.label}>
              {v.url ? <img src={v.url} alt="" /> : <span />}
              <span>{v.label}</span>
            </button>
          ))}
        </div>
      )}
      {items.length > 1 && (
        <div className="av3-lb-strip" onClick={(e) => e.stopPropagation()}>
          {items.map((x, i) => (
            <button key={x.key} className={i === index ? "on" : ""} onClick={() => onIndex(i)} title={x.title}>
              {x.url ? <img src={x.url} alt="" /> : <span>{x.title.slice(0, 2)}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function itemLbItem(w: WardrobeItemView, slot: string): LbItem {
  const vers = [...w.image_urls].sort((a, b) => b.version - a.version).map((im) => ({ url: im.url ?? null, label: `v${im.version} · ${VARIANT_LABEL[im.variant] ?? im.variant}` }));
  if (!vers.length) w.reference_urls.forEach((u, i) => u && vers.push({ url: u, label: `参考图 ${i + 1}` }));
  const main = itemMainImage(w);
  const mainIdx = main ? vers.findIndex((v) => v.url === main.url) : -1;
  if (mainIdx > 0) vers.unshift(...vers.splice(mainIdx, 1));
  return {
    key: `item:${w.id}`,
    url: main?.url ?? w.thumb_url,
    title: `${CAT_FULL[slot] ?? slot} · ${w.name}`,
    sub: w.image_urls.length ? `${w.id} · ${w.image_urls.length} 个版本` : `${w.id} · 没有版本图，显示登记的参考图`,
    versions: vers.length ? vers : undefined,
    sel: { kind: "item", id: w.id },
  };
}

// ---------------------------------------------------------------- 角色卡主体

export function LookStage({
  ch,
  sched,
  nEp,
  maxRefs,
  lookId,
  busy,
  onLook,
  onOpen,
  onGenLook,
  onEdit,
  onNewLook,
  onDefault,
  onOpenEp,
  onUpload,
}: {
  ch: CharacterAssets;
  sched: Schedule | null;
  nEp: number;
  maxRefs: number;
  lookId: string | null;
  busy: boolean;
  onLook: (id: string) => void;
  onOpen: (items: LbItem[], index: number) => void;
  onGenLook: (lk: LookView, refs: string[]) => void;
  onEdit: (id: string) => void;
  onNewLook: () => void;
  onDefault: (id: string) => void;
  onOpenEp: (n: number) => void;
  onUpload: (itemId: string, f: File, variant: string) => void;
}) {
  const lk = ch.looks.find((l) => l.id === lookId) ?? ch.looks.find((l) => l.id === ch.default_look_id) ?? ch.looks[0] ?? null;
  const byId = useMemo(() => new Map(ch.wardrobe.map((w) => [w.id, w])), [ch.wardrobe]);
  const [over, setOver] = useState<string | null>(null);

  const heroUrl = lk?.preview_url ?? ch.hero?.url ?? null;
  const heroCap = lk?.preview_url ? "造型预览" : ch.hero ? (ch.hero === ch.master || ch.hero.category === "master" ? "写实母版（本造型还没有预览图）" : "定妆图（本造型还没有预览图）") : "";

  const tiles = useMemo(() => {
    if (!lk) return [];
    return lookSlots(lk).flatMap(([slot, ids]) => (ids.length ? ids.map((id) => ({ slot, id, w: byId.get(id) })) : (ROW_SLOTS as readonly string[]).includes(slot) ? [{ slot, id: "", w: undefined }] : []));
  }, [lk, byId]);

  const lbItems = useMemo<LbItem[]>(() => {
    const out: LbItem[] = [];
    if (heroUrl) out.push({ key: "hero", url: heroUrl, title: lk ? `${lookLetter(lk)} · ${lk.name || lk.id}` : ch.name, sub: heroCap, sel: lk ? { kind: "look", id: lk.id } : undefined });
    for (const t of tiles) if (t.w) out.push(itemLbItem(t.w, t.slot));
    return out;
  }, [heroUrl, heroCap, lk, tiles, ch.name]);

  const usage = useMemo(() => (lk ? lookUsage(sched, ch.id, lk, ch.default_look_id === lk.id, nEp) : null), [sched, ch.id, ch.default_look_id, lk, nEp]);
  const refs = lk ? lookRefs(ch, lk, maxRefs) : [];
  const missingImg = tiles.filter((t) => t.id && !(itemMainImage(t.w)?.url || t.w?.thumb_url)).length;
  const isDefault = !!lk && ch.default_look_id === lk.id;

  const drop = (w: WardrobeItemView) => (e: DragEvent) => {
    e.preventDefault();
    setOver(null);
    const f = e.dataTransfer.files?.[0];
    if (f && f.type.startsWith("image/")) onUpload(w.id, f, w.slot === "makeup" || w.slot === "hair" ? "front" : "clean");
  };

  return (
    <section className="av3-stage" aria-label="角色卡">
      <figure
        className={`av3-card${heroUrl ? "" : " empty"}`}
        tabIndex={heroUrl ? 0 : -1}
        onClick={() => heroUrl && onOpen(lbItems, 0)}
        onKeyDown={(e) => e.key === "Enter" && heroUrl && onOpen(lbItems, 0)}
        title={heroUrl ? "点击全屏（F）" : undefined}
      >
        {heroUrl ? <img src={heroUrl} alt={ch.name} /> : <div className="av3-card-empty">还没有定妆图</div>}
        {lk && <span className="av3-letter">{lookLetter(lk)}</span>}
        {heroCap && <figcaption>{heroCap}</figcaption>}
      </figure>

      <div className="av3-stage-body">
        <div className="av3-looktabs" role="tablist" aria-label="造型">
          {ch.looks.map((l, li) => (
            <button
              key={l.id}
              role="tab"
              aria-selected={l.id === lk?.id}
              className={l.id === lk?.id ? "on" : ""}
              onClick={() => onLook(l.id)}
              title={`${l.name || l.id}（←/→ 切换造型）`}
            >
              {/* 没设字母时按顺序 A/B/C（不用名字首字，免得“默 默认”）；名字本身就是“默认”时不再加“默认”徽标 */}
              <span className="av3-lt-letter">{l.label || String.fromCharCode(65 + li)}</span>
              <span className="av3-lt-name">{l.name || l.id}</span>
              {ch.default_look_id === l.id && (l.name || "").trim() !== "默认" && <span className="badge b-active">默认</span>}
            </button>
          ))}
          <button className="av3-lt-add" onClick={onNewLook}>
            + 新造型
          </button>
        </div>

        {lk ? (
          <>
            <div className="av3-lookmeta">
              <span>
                用于 <b>{lk.used_by_shots}</b> 镜
              </span>
              {usage && (
                <span>
                  · <b>{usage.count}</b> 集{usage.shotOverrides ? ` · 另有 ${usage.shotOverrides} 镜单镜指定` : ""}
                </span>
              )}
              {lk.decor_state && <span className="badge">{lk.decor_state}</span>}
              {lk.needs_review && <span className="badge b-stale">待确认</span>}
            </div>
            {usage && <EpStrip usage={usage} onOpenEp={onOpenEp} isDefault={isDefault} />}

            <div className="av3-slots">
              {tiles.map((t) =>
                t.w ? (
                  <figure
                    key={t.slot + t.id}
                    className={`av3-slot${itemMainImage(t.w)?.url || t.w.thumb_url ? "" : " missing"}${over === t.id ? " drop" : ""}`}
                    tabIndex={0}
                    onClick={() => onOpen(lbItems, lbItems.findIndex((x) => x.key === `item:${t.id}`))}
                    onKeyDown={(e) => e.key === "Enter" && onOpen(lbItems, lbItems.findIndex((x) => x.key === `item:${t.id}`))}
                    onDragOver={(e) => {
                      if (e.dataTransfer.types.includes("Files")) {
                        e.preventDefault();
                        setOver(t.id);
                      }
                    }}
                    onDragLeave={() => setOver(null)}
                    onDrop={drop(t.w)}
                    title={`${t.w.name}\n点击全屏看全部版本；拖图片到这里 = 上传新版本`}
                  >
                    <div className="av3-slot-img">
                      {itemMainImage(t.w)?.url || t.w.thumb_url ? <img src={itemMainImage(t.w)?.url ?? t.w.thumb_url!} alt="" loading="lazy" /> : <span className="av3-slot-noimg">缺图</span>}
                      {t.w.image_urls.length > 1 && <span className="av3-ver">{t.w.image_urls.length} 版</span>}
                    </div>
                    <figcaption>
                      <span className="av3-slot-cat">{CAT_FULL[t.slot] ?? t.slot}</span>
                      <span className="av3-slot-name">{t.w.name}</span>
                    </figcaption>
                  </figure>
                ) : t.id ? (
                  <figure key={t.slot + t.id} className="av3-slot missing" title={`单品 ${t.id} 不在衣橱里`}>
                    <div className="av3-slot-img">
                      <span className="av3-slot-noimg">不在衣橱</span>
                    </div>
                    <figcaption>
                      <span className="av3-slot-cat">{CAT_FULL[t.slot] ?? t.slot}</span>
                      <span className="av3-slot-name">{t.id}</span>
                    </figcaption>
                  </figure>
                ) : (
                  <button key={t.slot} className="av3-slot empty" onClick={() => onEdit(lk.id)} title="在组合器里给这个插槽选单品">
                    <div className="av3-slot-img">
                      <span>+</span>
                    </div>
                    <span className="av3-slot-cat">{CAT_FULL[t.slot] ?? t.slot}</span>
                    <span className="muted small">未设</span>
                  </button>
                ),
              )}
            </div>

            <div className="av3-gen">
              <div className="av3-gen-refs" aria-label="将使用的参考图">
                {refs.map((r, i) => {
                  const url = refUrl(ch, r.file);
                  return (
                    <span key={r.file} className="av3-gen-ref" title={r.file}>
                      {url ? <img src={url} alt="" /> : <i />}
                      <span>
                        图{i + 1} {r.label}
                      </span>
                    </span>
                  );
                })}
              </div>
              <div className="av3-gen-actions">
                <button className="btn primary big" disabled={busy} onClick={() => onGenLook(lk, refs.map((r) => r.file))}>
                  {refs.length ? `用这些参考出图（${refs.length} 张）` : "出图（还没有参考图 · 文生图）"}
                </button>
                <button className="btn" onClick={() => onEdit(lk.id)}>
                  编辑组合
                </button>
                {!isDefault && (
                  <button className="btn" disabled={busy} onClick={() => onDefault(lk.id)}>
                    设为默认
                  </button>
                )}
              </div>
              {missingImg > 0 && <div className="small warn">{missingImg} 个单品还没有图，出图时只能靠提示词文字</div>}
            </div>
          </>
        ) : (
          <div className="av3-empty">
            <p>这个角色还没有造型</p>
            <button className="btn primary" onClick={onNewLook}>
              + 新造型
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function refUrl(ch: CharacterAssets, file: string): string | null {
  if (ch.master?.file === file) return ch.master.url;
  for (const e of Object.values(ch.plates)) if (e?.file === file) return e.url;
  for (const e of ch.portraits) if (e.file === file) return e.url;
  for (const w of ch.wardrobe) {
    for (const im of w.image_urls) if (im.file === file) return im.url ?? null;
    const i = w.reference_images.indexOf(file);
    if (i >= 0) return w.reference_urls[i] ?? null;
  }
  return null;
}

function EpStrip({ usage, onOpenEp, isDefault }: { usage: LookUsage; onOpenEp: (n: number) => void; isDefault: boolean }) {
  const ranges = epRanges(usage.eps);
  return (
    <div className="av3-eps">
      <div className="av3-eps-bar" role="list" aria-label="各集是否使用本造型">
        {usage.eps.map((v, i) => (
          <button
            key={i}
            role="listitem"
            className={`av3-ep v${v}`}
            onClick={() => onOpenEp(i + 1)}
            title={`ep${String(i + 1).padStart(2, "0")}：${v === 0 ? "不用" : v === 2 ? "使用（本集计划另改了单品 / D 状态）" : "使用"} · 点击打开该集`}
          />
        ))}
      </div>
      <div className="av3-eps-txt">
        {ranges.length ? (
          ranges.slice(0, 12).map((r) => (
            <button key={r.from} className="av3-eps-chip" onClick={() => onOpenEp(r.from)}>
              {r.from === r.to ? `ep${pad(r.from)}` : `ep${pad(r.from)}–${pad(r.to)}`}
            </button>
          ))
        ) : (
          <span className="muted">排期里还没有集使用这个造型{isDefault ? "" : "（在下方排期里指定）"}</span>
        )}
        {ranges.length > 12 && <span className="muted">… 共 {ranges.length} 段</span>}
        <span className="grow" />
        <span className="av3-eps-legend">
          <i className="v1" />
          使用 <i className="v2" />
          本集另有改动
        </span>
      </div>
    </div>
  );
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 资产页挂载期间屏蔽全局镜头快捷键（i/e/v/a/x/←/→ 等会作用于集视图里选中的镜头），并提供本页按键 */
export function useAssetKeys(handler: (e: KeyboardEvent) => boolean) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const SHOT_KEYS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Enter", " ", "i", "e", "v", "V", "a", "x", "l", "[", "]", "r", "d", "t", "\\"]);
    const down = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector(".av3-lb")) return; // 全屏看图自己处理按键（同为 capture，注册更晚）
      if (ref.current(e)) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return;
      }
      // 留给浏览器默认行为（按钮回车、滚动），但不让全局 keymap 拿到
      if (SHOT_KEYS.has(e.key)) e.stopImmediatePropagation();
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === " " && !isTypingTarget(e.target) && !document.querySelector(".av3-lb")) e.stopImmediatePropagation();
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
    };
  }, []);
}
