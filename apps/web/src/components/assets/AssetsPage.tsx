import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api } from "../../api";
import { useStudio } from "../../store";
import type { AffectedShots, AssetCatalog, AssetEntry, CharacterAssets, LookPatch, WardrobeItemView } from "../../types";
import { CAT_FULL, itemLbItem, Lightbox, LookStage, useAssetKeys, type LbItem } from "./CharacterCard";
import {
  faceFile,
  GenerateForm,
  LookComposer,
  lookLetter,
  PLATE_LABEL,
  ScheduleMatrix,
  SelInspector,
  stripLook,
  type GenDraft,
  type Schedule,
  type Sel,
} from "./parts";
import "./assets-v3.css";

/** 资产页 v3.1：小云雀式角色卡（9:16 大定妆图 · 造型 A/B/C 切换 · 单品一目了然 · 用于哪些集 · 全屏看图 · 身份底板 · 衣橱 · 排期） */
export default function AssetsPage() {
  const st = useStudio();
  const { notify, assetFocus, setView, gotoEpisode, onJobsQueued, episodes } = st;
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
  const [lookSel, setLookSel] = useState<string | null>(() => new URLSearchParams(location.search).get("alook"));
  const [lb, setLb] = useState<{ items: LbItem[]; index: number } | null>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const openLb = useCallback((items: LbItem[], index: number) => items.length && setLb({ items, index: Math.max(0, index) }), []);

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
      setLookSel(assetFocus.lookId);
      mainRef.current?.scrollTo({ top: 0 });
    } else if (assetFocus.itemId) setSel({ kind: "item", id: assetFocus.itemId });
  }, [assetFocus, cat]);

  useEffect(() => {
    if (!cat || cid || !cat.characters.length) return;
    // 深链 ?alook= / ?aitem= 定位到拥有它的角色
    const owner =
      (sel?.kind === "look" && cat.characters.find((c) => c.looks.some((l) => l.id === sel.id))) ||
      (sel?.kind === "item" && cat.characters.find((c) => c.wardrobe.some((w) => w.id === sel.id))) ||
      null;
    setCid((owner || cat.characters[0]).id);
  }, [cat, cid, sel]);

  // ?alb=1：打开后直接全屏看当前定妆图（便于截图核对）
  const albDone = useRef(false);
  useEffect(() => {
    if (!cat || !cid || albDone.current || !new URLSearchParams(location.search).get("alb")) return;
    albDone.current = true;
    setTimeout(() => document.querySelector<HTMLElement>(".av3-card")?.click(), 50);
  }, [cat, cid]);

  const ch = cat?.characters.find((c) => c.id === cid) ?? null;
  const curLook = ch ? ch.looks.find((l) => l.id === lookSel) ?? ch.looks.find((l) => l.id === ch.default_look_id) ?? ch.looks[0] ?? null : null;

  // 本页按键：←/→ 切换造型，F 全屏看当前定妆图，[ / ] 切换角色；同时屏蔽集视图的镜头快捷键
  useAssetKeys((e) => {
    if (!ch || st.confirmReq) return false;
    const k = e.key;
    if ((k === "ArrowLeft" || k === "ArrowRight") && ch.looks.length > 1) {
      const i = Math.max(0, ch.looks.findIndex((l) => l.id === curLook?.id));
      setLookSel(ch.looks[(i + (k === "ArrowRight" ? 1 : -1) + ch.looks.length) % ch.looks.length].id);
      return true;
    }
    if (k === "f" || k === "F") {
      document.querySelector<HTMLElement>(".av3-card")?.click();
      return true;
    }
    if ((k === "[" || k === "]") && cat && cat.characters.length > 1) {
      const i = cat.characters.findIndex((c) => c.id === ch.id);
      const n = cat.characters[(i + (k === "]" ? 1 : -1) + cat.characters.length) % cat.characters.length];
      setCid(n.id);
      setLookSel(null);
      setSel(null);
      setGen(null);
      mainRef.current?.scrollTo({ top: 0 });
      return true;
    }
    return false;
  });

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

  // T54-B #3：影响范围 + 只更新引用 / 选中这些镜头 / 批量重出（store 公共实现）
  const showAffected = useCallback((r: AffectedShots, what: string) => st.showAffected(r, what), [st]);

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
      (r) => showAffected(r, `${itemId} 已上传新版本 v${r.image.version}`),
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
  if (!cat)
    return (
      <div className="av3" aria-busy="true">
        <nav className="av3-rail" />
        <div className="av3-main">
          <div className="av3-skel-head" />
          <div className="av3-stage">
            <div className="av3-card av3-skel" />
            <div className="av3-stage-body">
              <div className="av3-skel-line" />
              <div className="av3-skel-line short" />
              <span className="muted">加载资产…</span>
            </div>
          </div>
        </div>
      </div>
    );

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
              setLookSel(null);
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
            <CharHeader ch={ch} busy={busy} onImport={() => importManifest(ch)} onReload={() => void run(async () => null)} />

            <LookStage
              ch={ch}
              sched={sched}
              nEp={episodes?.length ?? 60}
              maxRefs={cat.max_refs}
              lookId={curLook?.id ?? null}
              busy={busy}
              onLook={(id) => {
                setLookSel(id);
                if (composer) setHlLook(id);
              }}
              onOpen={openLb}
              onGenLook={(lk, refs) => openGen(`look/${lk.id}`, "", refs, lk.name)}
              onEdit={(id) => {
                setComposer(true);
                setHlLook(id);
                setTimeout(() => document.getElementById(`look-col-${id}`)?.scrollIntoView({ block: "nearest", inline: "center" }), 60);
              }}
              onNewLook={() => {
                setComposer(true);
                setTimeout(() => document.querySelector(".av3-composer")?.scrollIntoView({ block: "nearest" }), 60);
              }}
              onDefault={(id) => {
                const lk = ch.looks.find((l) => l.id === id);
                void run(() => api.looks.setDefault(ch.id, id), (r) => showAffected(r, `默认造型改为 ${lookLetter(lk)} · ${lk?.name ?? id}`));
              }}
              onOpenEp={(n) => {
                gotoEpisode(n);
                setView("episode");
              }}
              onUpload={uploadItem}
            />

            {composer && (
              <section className="av3-sec">
                <div className="av3-composer">
                  <div className="av3-composer-head">
                    <b>造型组合器</b>
                    <span className="muted">从衣橱给每个插槽选单品；保存后影响用到它的镜头（不会自动重渲）</span>
                    <span className="grow" />
                    <button className="btn" onClick={() => setComposer(false)}>
                      收起
                    </button>
                  </div>
                  <LookComposer
                    ch={ch}
                    decorStates={cat.decor_states}
                    busy={busy}
                    hl={hlLook}
                    onSelect={(id) => {
                      setLookSel(id);
                      pick({ kind: "look", id });
                    }}
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
              </section>
            )}

            <PlatesSection ch={ch} onOpen={openLb} onGen={openGen} />

            <ItemsGrid
              ch={ch}
              cats={cat.item_categories}
              sel={sel}
              busy={busy}
              onSel={pick}
              onOpen={openLb}
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

      {lb && (
        <Lightbox
          items={lb.items}
          index={lb.index}
          onIndex={(index) => setLb((x) => (x ? { ...x, index } : x))}
          onClose={() => setLb(null)}
          onDetail={pick}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- 角色头：名字 · 统计 · manifest

function CharHeader({ ch, busy, onImport, onReload }: { ch: CharacterAssets; busy: boolean; onImport: () => void; onReload: () => void }) {
  const withImg = ch.wardrobe.filter((w) => w.has_image).length;
  const itemFiles = Object.values(ch.items).reduce((n, l) => n + l.length, 0);
  return (
    <header className="av3-head">
      <div className="av3-title">
        <h2>{ch.name}</h2>
        <span className="muted">{ch.id}</span>
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
        <div className={ch.missing_count ? "bad" : ""} title={ch.missing.join("\n") || undefined}>
          <b>{ch.missing_count}</b>
          <span>缺图</span>
        </div>
        <div className={ch.unregistered ? "warn" : ""}>
          <b>{ch.unregistered}</b>
          <span>文件未登记</span>
        </div>
      </div>
      <span className="grow" />
      <div className="av3-hero-actions">
        {ch.unregistered > 0 ? (
          <button className="btn primary" disabled={busy} onClick={onImport} title="把 manifest 里的图片登记进衣橱（sha256 去重，同设计的多张图挂成新版本），造型和镜头才能用到">
            {busy ? "导入中…" : `导入 manifest（${ch.unregistered}）`}
          </button>
        ) : (
          <span className={itemFiles ? "av3-ok" : "muted"} title={ch.dir}>
            {itemFiles ? `✓ ${itemFiles} 个文件已登记` : "目录里还没有单品文件"}
          </span>
        )}
        <button className="btn" disabled={busy} onClick={onReload}>
          {busy ? "处理中…" : "刷新"}
        </button>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------- 身份底板 + 表情（点击全屏）

function PlatesSection({
  ch,
  onOpen,
  onGen,
}: {
  ch: CharacterAssets;
  onOpen: (items: LbItem[], index: number) => void;
  onGen: (target: string, prompt?: string, refs?: string[] | null, name?: string) => void;
}) {
  const plates = Object.entries(ch.plates).filter(([, e]) => e) as [string, AssetEntry][];
  const missingPlates = Object.keys(ch.plates).filter((v) => !ch.plates[v]);
  const entries: { e: AssetEntry; label: string }[] = [
    ...plates.map(([v, e]) => ({ e, label: PLATE_LABEL[v] ?? v })),
    ...ch.expressions.map((e) => ({ e, label: e.name || e.category })),
  ];
  const lbItems: LbItem[] = entries.map(({ e, label }) => ({ key: e.file, url: e.url, title: label, sub: e.file, sel: { kind: "entry", entry: e } }));
  return (
    <section className="av3-sec">
      <header className="av3-sec-head">
        <h3>身份底板 · 表情</h3>
        <span className="muted">正 / 3/4 / 侧 / 背 + 表情；正面底板就是镜头行上的脸图。点击全屏</span>
      </header>
      {entries.length ? (
        <div className="av3-plates">
          {entries.map(({ e, label }, i) => (
            <figure key={e.file} className="av3-plate" tabIndex={0} onClick={() => onOpen(lbItems, i)} onKeyDown={(k) => k.key === "Enter" && onOpen(lbItems, i)}>
              {e.url ? <img src={e.url} alt={label} loading="lazy" /> : <div className="av3-missing-file">文件缺失</div>}
              <figcaption>{label}</figcaption>
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
            <span className="muted">先有定妆图 / 母版，再生成正 / 3/4 / 侧 / 背四张底板；完成后正面图自动成为镜头行上的脸图。</span>
          </div>
          <button className="btn primary" onClick={() => onGen(ch.hero ? "plate/front" : "plate/master", "", null, ch.hero ? "" : "master")}>
            {ch.hero ? "生成身份底板" : "生成定妆母版"}
          </button>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- 单品大图网格

function ItemsGrid({
  ch,
  cats,
  sel,
  busy,
  onSel,
  onOpen,
  onUpload,
  onGen,
  onImport,
}: {
  ch: CharacterAssets;
  cats: string[];
  sel: Sel;
  busy: boolean;
  onSel: (s: Sel) => void;
  onOpen: (items: LbItem[], index: number) => void;
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
  // 全屏看图：未登记文件 + 有图单品，按网格顺序
  const lbItems: LbItem[] = [
    ...unreg.map((e) => ({ key: e.file, url: e.url, title: e.name || e.design || e.file, sub: "未登记进衣橱", sel: { kind: "entry", entry: e } as const })),
    ...items.filter((w) => w.has_image || w.thumb_url).map((w) => itemLbItem(w, tab)),
  ];
  const openAt = (key: string) => {
    const i = lbItems.findIndex((x) => x.key === key);
    if (i >= 0) onOpen(lbItems, i);
  };
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
        <span className="muted">点卡片全屏看大图和全部版本（「明细」看来源/上传）；把图片拖到卡片上 = 上传新版本（旧版本保留）</span>
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
              tabIndex={0}
              onClick={() => openAt(e.file)}
              onKeyDown={(k) => k.key === "Enter" && openAt(e.file)}
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
              tabIndex={0}
              onClick={() => (w.has_image || w.thumb_url ? openAt(`item:${w.id}`) : onSel({ kind: "item", id: w.id }))}
              onKeyDown={(k) => k.key === "Enter" && (w.has_image || w.thumb_url ? openAt(`item:${w.id}`) : onSel({ kind: "item", id: w.id }))}
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

