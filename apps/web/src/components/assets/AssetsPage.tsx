import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { api } from "../../api";
import { useStudio } from "../../store";
import type { AffectedShots, AssetCatalog, AssetEntry, CharacterAssets, LookPatch, LookView, WardrobeItemView } from "../../types";
import {
  faceFile,
  GenerateForm,
  LookComposer,
  lookLetter,
  PLATE_LABEL,
  ROW_SLOTS,
  ScheduleMatrix,
  SelInspector,
  stripLook,
  type GenDraft,
  type Schedule,
  type Sel,
} from "./parts";
import "./assets-v3.css";

const CAT_FULL: Record<string, string> = { outfit: "服装", shoes: "鞋", nails: "美甲", hair: "发型", makeup: "妆容", accessory: "饰品" };
const SLOT_SHORT: Record<string, string> = { outfit: "衣", shoes: "鞋", nails: "甲", hair: "发", makeup: "妆", accessory: "饰" };

/** 资产页 v3：小云雀式角色卡（大定妆图 · 身份底板 · 造型 A/B/C 大卡 · 单品大图 · 排期） */
export default function AssetsPage() {
  const st = useStudio();
  const { notify, assetFocus, setConfirmReq, setMulti, setView, gotoEpisode, onJobsQueued, episodes } = st;
  const [cat, setCat] = useState<AssetCatalog | null>(null);
  const [sched, setSched] = useState<Schedule | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cid, setCid] = useState<string | null>(assetFocus?.character ?? null);
  const [sel, setSel] = useState<Sel>(() => {
    const q = new URLSearchParams(location.search);
    const it = q.get("aitem");
    const lk = q.get("alook");
    return it ? { kind: "item", id: it } : lk ? { kind: "look", id: lk } : null; // 深链：?aitem=<单品 id> / ?alook=<造型 id>
  });
  const [gen, setGen] = useState<GenDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [hlLook, setHlLook] = useState<string | null>(null);
  const [composer, setComposer] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);

  const reload = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([api.assets.list(), api.looks.schedule().catch(() => null)]);
      setCat(c);
      setSched(s);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);

  // 从镜头行点脸图 / 单品过来：定位角色、造型
  useEffect(() => {
    if (!assetFocus || !cat) return;
    const c = cat.characters.find((x) => x.id === assetFocus.character || x.name === assetFocus.character);
    if (!c) return;
    setCid(c.id);
    if (assetFocus.lookId) {
      setHlLook(assetFocus.lookId);
      setTimeout(() => document.getElementById(`look-card-${assetFocus.lookId}`)?.scrollIntoView({ block: "center" }), 80);
    } else if (assetFocus.itemId) setSel({ kind: "item", id: assetFocus.itemId });
  }, [assetFocus, cat]);

  useEffect(() => {
    if (cat && !cid && cat.characters.length) setCid(cat.characters[0].id);
  }, [cat, cid]);

  const ch = cat?.characters.find((c) => c.id === cid) ?? null;

  // Esc 关闭右侧明细面板（全局 keymap 不处理资产页）
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !st.confirmReq) {
        setSel(null);
        setGen(null);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [st.confirmReq]);

  const showAffected = useCallback(
    (r: AffectedShots, what: string) => {
      if (!r.affected_count) return notify(`${what}：不影响任何镜头`);
      setConfirmReq({
        title: what,
        lines: [`影响 ${r.affected_count} 镜（不会自动重渲）：`, r.affected_shots.slice(0, 30).join("、") + (r.affected_count > 30 ? " …" : "")],
        confirmLabel: "选中这些镜头",
        onConfirm: () => {
          setMulti(new Set(r.affected_shots));
          setView("episode");
        },
      });
    },
    [notify, setConfirmReq, setMulti, setView],
  );

  const run = useCallback(
    async <T,>(fn: () => Promise<T>, ok?: (r: T) => void): Promise<T | undefined> => {
      setBusy(true);
      try {
        const r = await fn();
        ok?.(r);
        await reload();
        return r;
      } catch (e) {
        notify((e as Error).message, "err");
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [notify, reload],
  );

  const importManifest = (c: CharacterAssets) =>
    void run(
      () => api.assets.importManifest(c.id),
      (r) => {
        const n = r.created.length + r.attached.length;
        notify(
          n
            ? `已登记 ${n} 个文件（新建单品 ${r.created.length}，挂到已有单品 ${r.attached.length}）${r.skipped.length ? `，跳过 ${r.skipped.length}` : ""}；影响 ${r.affected_count} 镜，不会自动重渲`
            : `没有需要登记的文件${r.skipped.length ? `（跳过 ${r.skipped.length}：${r.skipped[0].reason}）` : ""}`,
        );
        void st.refreshEpisodes();
      },
    );

  const uploadItem = (itemId: string, file: File, variant: string) =>
    void run(
      () => api.looks.uploadItemImage(itemId, file, variant),
      (r) => notify(`${itemId} 已上传新版本 v${r.image.version}：影响 ${r.affected_count} 镜（不会自动重渲）`),
    );

  const openGen = useCallback(
    (target: string, prompt = "", refs?: string[] | null, name = "") => {
      const face = ch ? faceFile(ch) : null;
      const master = ch?.master?.file ?? null;
      const base = master ?? face;
      setGen({ target, prompt, references: refs && refs.length ? refs : base ? [base] : [], name });
      setSel(null);
    },
    [ch],
  );

  const submitGen = async (g: GenDraft, model: "qwen" | "klein", seed: string) => {
    if (!ch) return;
    const s = seed.trim();
    if (s && !/^\d+$/.test(s)) return notify("种子必须是非负整数", "err");
    setBusy(true);
    try {
      const job = await api.assets.generate(ch.id, {
        target: g.target,
        prompt: g.prompt,
        references: g.references,
        model,
        seed: s ? Number(s) : null,
        name: g.name || null,
      });
      onJobsQueued([job]);
      notify(`已入队资产出图（任务 ${job.id}），完成后点「刷新」即可看到`);
      setGen(null);
    } catch (e) {
      notify(`出图提交失败：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const pick = (s: Sel) => {
    setGen(null);
    setSel(s);
  };

  if (err && !cat)
    return (
      <div className="empty">
        <p className="bad">资产接口不可用：{err}</p>
        <button className="btn" onClick={() => void reload()}>
          重试
        </button>
      </div>
    );
  if (!cat) return <div className="empty">加载资产…</div>;

  const panelOpen = !!ch && (!!gen || !!sel);

  return (
    <div className={`av3${panelOpen ? " with-panel" : ""}`}>
      <nav className="av3-rail">
        <div className="av3-rail-title">角色</div>
        {cat.characters.map((c) => (
          <button
            key={c.id}
            className={`av3-char${c.id === cid ? " on" : ""}`}
            onClick={() => {
              setCid(c.id);
              setSel(null);
              setGen(null);
              setComposer(false);
              mainRef.current?.scrollTo({ top: 0 });
            }}
            title={c.missing.join("\n") || "资产齐全"}
          >
            {c.face_url ? <img src={c.face_url} alt="" /> : <span className="av3-face-missing" />}
            <span className="av3-char-txt">
              <b>{c.name}</b>
              <span className="muted">
                {c.looks.length} 造型 · {c.wardrobe.length} 单品
              </span>
            </span>
            {c.missing_count > 0 && <span className="av3-miss">缺 {c.missing_count}</span>}
          </button>
        ))}
      </nav>

      <div className="av3-main" ref={mainRef}>
        {ch ? (
          <>
            <Hero ch={ch} busy={busy} onImport={() => importManifest(ch)} onReload={() => void run(async () => null)} onSel={pick} onGen={openGen} />

            <section className="av3-sec">
              <header className="av3-sec-head">
                <h3>造型</h3>
                <span className="muted">每集换装都从这里挑；点卡片看明细，「编辑组合」换单品</span>
                <span className="grow" />
                <button className={`btn${composer ? " on" : ""}`} onClick={() => setComposer((v) => !v)}>
                  {composer ? "收起组合器" : "+ 新造型 / 编辑组合"}
                </button>
              </header>
              <div className="av3-looks">
                {ch.looks.map((lk) => (
                  <LookCard
                    key={lk.id}
                    ch={ch}
                    lk={lk}
                    hl={hlLook === lk.id}
                    selected={sel?.kind === "look" && sel.id === lk.id}
                    busy={busy}
                    onSel={() => pick({ kind: "look", id: lk.id })}
                    onEdit={() => {
                      setComposer(true);
                      setHlLook(lk.id);
                      setTimeout(() => document.getElementById(`look-col-${lk.id}`)?.scrollIntoView({ block: "nearest", inline: "center" }), 60);
                    }}
                    onGen={openGen}
                    onDefault={() => void run(() => api.looks.setDefault(ch.id, lk.id), (r) => showAffected(r, `默认造型改为 ${lookLetter(lk)} · ${lk.name}`))}
                  />
                ))}
                {!ch.looks.length && (
                  <div className="av3-empty">
                    <p>这个角色还没有造型</p>
                    <button className="btn primary" onClick={() => setComposer(true)}>
                      + 新造型
                    </button>
                  </div>
                )}
              </div>
              {composer && (
                <div className="av3-composer">
                  <LookComposer
                    ch={ch}
                    decorStates={cat.decor_states}
                    busy={busy}
                    hl={hlLook}
                    onSelect={(id) => pick({ kind: "look", id })}
                    onGen={openGen}
                    onSave={(lk, isNew) =>
                      void run(
                        () => api.looks.putLook(stripLook(lk)),
                        (r) => showAffected(r, `${isNew ? "新建" : "保存"}造型 ${lookLetter(lk)} · ${lk.name || lk.id}`),
                      )
                    }
                    onDefault={(id) => void run(() => api.looks.setDefault(ch.id, id), (r) => showAffected(r, `默认造型改为 ${id}`))}
                  />
                </div>
              )}
            </section>

            <ItemsGrid
              ch={ch}
              cats={cat.item_categories}
              sel={sel}
              busy={busy}
              onSel={pick}
              onUpload={uploadItem}
              onGen={openGen}
              onImport={() => importManifest(ch)}
            />

            <div className="av3-sched">
              <ScheduleMatrix
                cat={cat}
                sched={sched}
                nEp={episodes?.length ?? 60}
                cid={ch.id}
                busy={busy}
                onOpenEp={(n) => {
                  gotoEpisode(n);
                  setView("episode");
                }}
                onApply={(char, text, lookId) =>
                  void run(
                    () => api.looks.episodeRange(char, text, lookId === "__default" ? null : ({ look_id: lookId } as LookPatch)),
                    (r) => showAffected(r, `排期 ${text} → ${lookId === "__default" ? "恢复默认" : lookId}`),
                  )
                }
              />
            </div>
          </>
        ) : (
          <div className="empty">请选择角色</div>
        )}
      </div>

      {panelOpen && ch && (
        <aside className="av3-panel">
          <div className="av3-panel-head">
            <b>{gen ? "资产出图" : sel?.kind === "look" ? "造型明细" : sel?.kind === "item" ? "单品明细" : "资产明细"}</b>
            <button
              className="btn-mini"
              onClick={() => {
                setSel(null);
                setGen(null);
              }}
              title="关闭（Esc）"
            >
              关闭 ✕
            </button>
          </div>
          {gen ? (
            <GenerateForm ch={ch} draft={gen} maxRefs={cat.max_refs} busy={busy} onChange={setGen} onCancel={() => setGen(null)} onSubmit={submitGen} />
          ) : sel ? (
            <SelInspector ch={ch} sel={sel} variants={cat.variants} busy={busy} onUpload={uploadItem} onGen={openGen} onImport={() => importManifest(ch)} />
          ) : null}
        </aside>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- 角色头：大定妆图 + 身份底板 + 表情

function Hero({
  ch,
  busy,
  onImport,
  onReload,
  onSel,
  onGen,
}: {
  ch: CharacterAssets;
  busy: boolean;
  onImport: () => void;
  onReload: () => void;
  onSel: (s: Sel) => void;
  onGen: (target: string, prompt?: string, refs?: string[] | null, name?: string) => void;
}) {
  const hero = ch.hero;
  const heroKind = !hero ? "" : hero === ch.master || hero.category === "master" ? "写实母版" : hero.group === "plate" ? "正面底板" : "定妆原图";
  const plates = Object.entries(ch.plates).filter(([, e]) => e) as [string, AssetEntry][];
  const missingPlates = Object.keys(ch.plates).filter((v) => !ch.plates[v]);
  const withImg = ch.wardrobe.filter((w) => w.has_image).length;
  const itemFiles = Object.values(ch.items).reduce((n, l) => n + l.length, 0);
  return (
    <section className="av3-hero">
      <figure className={`av3-hero-img${hero ? "" : " empty"}`} onClick={() => hero && onSel({ kind: "entry", entry: hero })}>
        {hero?.url ? (
          <img src={hero.url} alt={ch.name} />
        ) : (
          <div className="av3-hero-empty">
            <span className="av3-face-missing big" />
            <p>还没有定妆图</p>
            <button className="btn primary" onClick={(e) => (e.stopPropagation(), onGen("plate/master", "", null, "master"))}>
              生成定妆母版
            </button>
          </div>
        )}
        {heroKind && <figcaption>{heroKind}</figcaption>}
      </figure>

      <div className="av3-hero-body">
        <div className="av3-title">
          <h2>{ch.name}</h2>
          <span className="muted">{ch.id}</span>
          {ch.default_look_id && (
            <span className="muted">· 默认造型：{ch.looks.find((l) => l.id === ch.default_look_id)?.name ?? ch.default_look_id}</span>
          )}
        </div>
        <div className="av3-stats">
          <div>
            <b>{ch.looks.length}</b>
            <span>造型</span>
          </div>
          <div>
            <b>{ch.wardrobe.length}</b>
            <span>衣橱单品</span>
          </div>
          <div>
            <b>{withImg}</b>
            <span>有图单品</span>
          </div>
          <div className={ch.missing_count ? "bad" : ""}>
            <b>{ch.missing_count}</b>
            <span>缺图</span>
          </div>
          <div className={ch.unregistered ? "warn" : ""}>
            <b>{ch.unregistered}</b>
            <span>文件未登记</span>
          </div>
        </div>
        <div className="av3-hero-actions">
          {ch.unregistered > 0 ? (
            <button className="btn primary big" disabled={busy} onClick={onImport} title="把 manifest 里的图片登记进衣橱（sha256 去重，同设计的多张图挂成新版本），造型和镜头才能用到">
              {busy ? "导入中…" : `导入 manifest（${ch.unregistered} 个未登记）`}
            </button>
          ) : (
            <span className={itemFiles ? "av3-ok" : "muted"}>{itemFiles ? `✓ manifest 里的 ${itemFiles} 个文件都已登记` : "目录里还没有单品文件"}</span>
          )}
          <button className="btn" disabled={busy} onClick={onReload}>
            刷新
          </button>
          <span className="muted small">{ch.dir}</span>
        </div>

        <div className="av3-sub">
          <h4>身份底板</h4>
          <span className="muted">正 / 3/4 / 侧 / 背 + 表情；正面底板就是镜头行上的脸图</span>
        </div>
        {plates.length || ch.expressions.length ? (
          <div className="av3-plates">
            {plates.map(([v, e]) => (
              <figure key={v} className="av3-plate" onClick={() => onSel({ kind: "entry", entry: e })}>
                {e.url ? <img src={e.url} alt={v} /> : <div className="av3-missing-file">文件缺失</div>}
                <figcaption>{PLATE_LABEL[v] ?? v}</figcaption>
              </figure>
            ))}
            {ch.expressions.map((e) => (
              <figure key={e.file} className="av3-plate" onClick={() => onSel({ kind: "entry", entry: e })}>
                {e.url ? <img src={e.url} alt={e.category} /> : <div className="av3-missing-file">文件缺失</div>}
                <figcaption>{e.name || e.category}</figcaption>
              </figure>
            ))}
            <div className="av3-plate-add">
              {missingPlates.length > 0 && <span className="muted">还缺 {missingPlates.map((v) => PLATE_LABEL[v] ?? v).join(" · ")}</span>}
              {missingPlates.length > 0 && (
                <button className="btn" onClick={() => onGen(`plate/${missingPlates[0]}`)}>
                  生成 {PLATE_LABEL[missingPlates[0]]}
                </button>
              )}
              <button className="btn" onClick={() => onGen("expression/")}>
                + 表情
              </button>
            </div>
          </div>
        ) : (
          <div className="av3-empty row">
            <div>
              <p>还没有身份底板和表情图</p>
              <span className="muted">
                {ch.master ? "用写实母版" : hero ? `用${heroKind}` : "先有定妆图，再"}生成正 / 3/4 / 侧 / 背四张底板；完成后正面图自动成为镜头行上的脸图。
              </span>
            </div>
            <button className="btn primary" onClick={() => onGen("plate/front")}>
              生成身份底板
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 造型大卡

function LookCard({
  ch,
  lk,
  hl,
  selected,
  busy,
  onSel,
  onEdit,
  onGen,
  onDefault,
}: {
  ch: CharacterAssets;
  lk: LookView;
  hl: boolean;
  selected: boolean;
  busy: boolean;
  onSel: () => void;
  onEdit: () => void;
  onGen: (target: string, prompt?: string, refs?: string[] | null, name?: string) => void;
  onDefault: () => void;
}) {
  const byId = useMemo(() => new Map(ch.wardrobe.map((w) => [w.id, w])), [ch.wardrobe]);
  const isDefault = ch.default_look_id === lk.id;
  const slots = ROW_SLOTS.map((slot) => ({ slot, items: (lk.items[slot] ?? []).map((id) => ({ id, w: byId.get(id) })) })).filter((x) => x.items.length);
  const others = Object.entries(lk.items).filter(([s]) => !(ROW_SLOTS as readonly string[]).includes(s));
  for (const [slot, ids] of others) slots.push({ slot: slot as (typeof ROW_SLOTS)[number], items: ids.map((id) => ({ id, w: byId.get(id) })) });
  const thumbs = slots.flatMap((s) => s.items).filter((x) => x.w?.thumb_url).slice(0, 4);
  const refs = [ch.master?.file ?? faceFile(ch), ...slots.flatMap((s) => s.items.map((x) => x.w?.image_urls.at(-1)?.file ?? null))].filter((x): x is string => !!x);
  return (
    <article id={`look-card-${lk.id}`} className={`av3-look${hl ? " hl" : ""}${selected ? " sel" : ""}`} onClick={onSel}>
      <div className={`av3-look-media${!lk.preview_url && !thumbs.length && !ch.face_url ? " blank" : ""}`}>
        {lk.preview_url ? (
          <img src={lk.preview_url} alt={lk.name} />
        ) : thumbs.length || ch.face_url ? (
          <div className={`av3-collage n${Math.min(4, thumbs.length + (ch.face_url ? 1 : 0))}`}>
            {ch.face_url && <img src={ch.face_url} alt="" />}
            {thumbs.map((t) => (
              <img key={t.id} src={t.w!.thumb_url!} alt="" title={t.w!.name} />
            ))}
            <span className="av3-collage-tag">无预览图 · 单品拼图</span>
          </div>
        ) : (
          <div className="av3-look-blank">还没有预览</div>
        )}
        <span className="av3-letter">{lookLetter(lk)}</span>
      </div>
      <div className="av3-look-body">
        <div className="av3-look-title">
          <b>{lk.name || lk.id}</b>
          {isDefault && <span className="badge b-active">默认</span>}
          {lk.decor_state && <span className="badge">{lk.decor_state}</span>}
          <span className="grow" />
          <span className="muted">用于 {lk.used_by_shots} 镜</span>
        </div>
        {slots.length ? (
          <div className="av3-look-items">
            {slots.map(({ slot, items }) =>
              items.map(({ id, w }) => (
                <div key={slot + id} className={`av3-chip${w?.has_image ? "" : " missing"}`} title={`${CAT_FULL[slot] ?? slot}：${w?.name ?? id}${w?.has_image ? "" : "\n缺图：只用文字描述"}`}>
                  {w?.thumb_url ? <img src={w.thumb_url} alt="" /> : <span className="av3-chip-txt">{SLOT_SHORT[slot] ?? "他"}</span>}
                  <span className="av3-chip-cap">
                    {SLOT_SHORT[slot] ?? "他"} · {w?.name ?? id}
                  </span>
                </div>
              )),
            )}
          </div>
        ) : (
          <div className="muted">还没有放单品</div>
        )}
        <div className="av3-look-actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn" onClick={() => onGen(`look/${lk.id}`, "", refs, lk.name)}>
            生成预览
          </button>
          <button className="btn" onClick={onEdit}>
            编辑组合
          </button>
          {!isDefault && (
            <button className="btn" disabled={busy} onClick={onDefault}>
              设为默认
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

// ---------------------------------------------------------------- 单品大图网格

function ItemsGrid({
  ch,
  cats,
  sel,
  busy,
  onSel,
  onUpload,
  onGen,
  onImport,
}: {
  ch: CharacterAssets;
  cats: string[];
  sel: Sel;
  busy: boolean;
  onSel: (s: Sel) => void;
  onUpload: (id: string, f: File, variant: string) => void;
  onGen: (target: string, prompt?: string, refs?: string[] | null, name?: string) => void;
  onImport: () => void;
}) {
  const inCat = (w: WardrobeItemView, c: string) => w.slot === c || (c === "accessory" && w.slot === "other");
  // 默认打开「有图最多」的类别；?atab=makeup 可直接定位
  const urlTab = new URLSearchParams(location.search).get("atab");
  const score = (c: string) => ch.wardrobe.filter((w) => inCat(w, c) && w.has_image).length * 10 + (ch.items[c] ?? []).length + ch.wardrobe.filter((w) => inCat(w, c)).length;
  const firstWithStuff = urlTab && cats.includes(urlTab) ? urlTab : [...cats].sort((a, b) => score(b) - score(a))[0] ?? "outfit";
  const [tab, setTab] = useState(firstWithStuff);
  useEffect(() => setTab(firstWithStuff), [ch.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const file = useRef<HTMLInputElement>(null);
  const pending = useRef<string | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const variantFor = (slot: string) => (slot === "makeup" || slot === "hair" ? "front" : "clean");
  const unreg = (ch.items[tab] ?? []).filter((e) => !e.registered_item_id);
  const items = ch.wardrobe.filter((w) => inCat(w, tab)).sort((a, b) => Number(b.has_image) - Number(a.has_image));
  const upload = (id: string) => {
    pending.current = id;
    file.current?.click();
  };
  const drop = (w: WardrobeItemView) => (e: DragEvent) => {
    e.preventDefault();
    setOver(null);
    const f = e.dataTransfer.files?.[0];
    if (f && f.type.startsWith("image/")) onUpload(w.id, f, variantFor(w.slot));
  };

  useEffect(() => {
    if (urlTab) setTimeout(() => document.getElementById("av3-items")?.scrollIntoView({ block: "start" }), 120);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="av3-sec" id="av3-items">
      <header className="av3-sec-head">
        <h3>单品</h3>
        <span className="muted">点卡片看大图和全部版本；把图片拖到卡片上 = 上传新版本（旧版本保留）</span>
      </header>
      <div className="av3-tabs">
        {cats.map((c) => {
          const n = ch.wardrobe.filter((w) => inCat(w, c)).length;
          const u = (ch.items[c] ?? []).filter((e) => !e.registered_item_id).length;
          const miss = ch.wardrobe.some((w) => inCat(w, c) && !w.has_image);
          return (
            <button key={c} className={tab === c ? "on" : ""} onClick={() => setTab(c)}>
              {CAT_FULL[c] ?? c}
              <span className="av3-count">{n + u}</span>
              {miss && <i className="av3-dot bad" title="有单品缺图" />}
              {u > 0 && <i className="av3-dot warn" title="有文件未登记" />}
            </button>
          );
        })}
      </div>

      {unreg.length > 0 && (
        <div className="av3-banner">
          <span>
            <b>{unreg.length}</b> 个{CAT_FULL[tab]}文件还没登记进衣橱，造型和镜头暂时用不到
          </span>
          <button className="btn primary" disabled={busy} onClick={onImport}>
            导入 manifest
          </button>
        </div>
      )}

      {!items.length && !unreg.length ? (
        <div className="av3-empty row">
          <div>
            <p>还没有{CAT_FULL[tab]}</p>
            <span className="muted">
              用 Image 2.1 按{ch.master ? "写实母版" : "定妆图"}多参考生成，结果存到 {ch.dir}/items/{tab}/
            </span>
          </div>
          <button className="btn primary" onClick={() => onGen(`item/${tab}`)}>
            生成{CAT_FULL[tab]}
          </button>
        </div>
      ) : (
        <div className="av3-items">
          {unreg.map((e) => (
            <figure
              key={e.file}
              className={`av3-item unreg${sel?.kind === "entry" && sel.entry.file === e.file ? " sel" : ""}`}
              onClick={() => onSel({ kind: "entry", entry: e })}
              title={e.prompt ?? e.file}
            >
              <div className="av3-item-img">{e.url ? <img src={e.url} alt="" loading="lazy" /> : <div className="av3-missing-file">文件缺失</div>}</div>
              <figcaption>
                <b>{e.name || e.design}</b>
                <div className="av3-item-meta">
                  <span className="badge b-stale">未登记</span>
                  {e.design && <span className="muted">{e.design}</span>}
                </div>
              </figcaption>
            </figure>
          ))}
          {items.map((w) => (
            <figure
              key={w.id}
              className={`av3-item${w.has_image ? "" : " missing"}${sel?.kind === "item" && sel.id === w.id ? " sel" : ""}${over === w.id ? " drop" : ""}`}
              onClick={() => onSel({ kind: "item", id: w.id })}
              onDragOver={(e) => {
                if (e.dataTransfer.types.includes("Files")) {
                  e.preventDefault();
                  setOver(w.id);
                }
              }}
              onDragLeave={() => setOver(null)}
              onDrop={drop(w)}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData("text/ns-item", w.id);
                e.dataTransfer.setData("text/ns-slot", w.slot);
              }}
              title={w.description || w.name}
            >
              <div className="av3-item-img">
                {w.thumb_url ? (
                  <img src={w.thumb_url} alt="" loading="lazy" />
                ) : (
                  <div className="av3-noimg" onClick={(e) => e.stopPropagation()}>
                    <span>缺图 · 只用文字描述</span>
                    <div>
                      <button className="btn" disabled={busy} onClick={() => upload(w.id)}>
                        上传
                      </button>
                      <button className="btn" onClick={() => onGen(`item/${w.slot === "other" ? "accessory" : w.slot}`, w.description, null, w.name)}>
                        生成
                      </button>
                    </div>
                  </div>
                )}
                {w.version > 1 && <span className="av3-ver">v{w.version}</span>}
              </div>
              <figcaption>
                <b>{w.name}</b>
                <div className="av3-item-meta">
                  {w.trigger && <span className="badge" title={w.lora_file ?? ""}>LoRA {w.trigger}</span>}
                  {w.needs_review && <span className="badge b-stale">待确认</span>}
                  {w.tags.slice(0, 3).map((t) => (
                    <span key={t} className="badge">
                      {t}
                    </span>
                  ))}
                </div>
                <div className="muted">
                  用于 {w.used_by_looks.length} 个造型 · {w.used_by_shots} 镜
                </div>
              </figcaption>
            </figure>
          ))}
          <button className="av3-item add" onClick={() => onGen(`item/${tab}`)}>
            <span>+</span>生成{CAT_FULL[tab]}
          </button>
        </div>
      )}
      <input
        ref={file}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          const id = pending.current;
          const w = ch.wardrobe.find((x) => x.id === id);
          if (f && w) onUpload(w.id, f, variantFor(w.slot));
          e.target.value = "";
        }}
      />
    </section>
  );
}

