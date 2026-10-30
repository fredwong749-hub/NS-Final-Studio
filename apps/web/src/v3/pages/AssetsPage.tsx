// fredw-92/W4c：资产页（#/assets，canvas-ui-spec-v3-merge §4 / §7.3，api_v1_contract §E）。
// 小云雀式角色卡：大头像、形象数、出现集数；点开看参考图、部件（服装 / 鞋 / 妆 / 甲 / 发 / 饰）、形象 A/B/C、
// 按集排期（哪几集用哪套）、“用到的镜头”反查。编辑走 W4b 的资产编辑抽屉（v3/edit/AssetDrawer），不另做一套。
// 出现集数 / 排期 / 反查都来自 /api/episodes/summary 每镜的出场人物与造型（实际编译结果），不另算。
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api";
import type { AssetEntry, CharacterAssets, LookView, ShotSummary, WardrobeItemView } from "../../types";
import { assetsV1, errText, isNotReady, type LightEpisode, type LightShot } from "../api_v1_pages";
import { setEdit, useEdit } from "../edit/state";
import { AssetDrawer, type DrawerTarget } from "../edit/AssetDrawer";
import ScenesTab from "./ScenesTab";
import type { PartKey } from "../api_v1";
import "./pages.css";

const PARTS: [PartKey, string][] = [
  ["outfit", "服装"],
  ["shoes", "鞋"],
  ["makeup", "妆容"],
  ["nails", "美甲"],
  ["hair", "发型"],
  ["accessory", "饰品"],
];
const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const LOOK_HUES = ["--c-accent", "--c-warn", "--c-ok", "--c-info", "--c-busy", "--c-bad"];
const pad = (n: number) => String(n).padStart(2, "0");


type Usage = { eps: Map<number, Map<string, LightShot[]>>; shots: number };

/** 每个人物：集号 → 形象 id → 镜头 */
function buildUsage(eps: LightEpisode[]): Map<string, Usage> {
  const m = new Map<string, Usage>();
  for (const ep of eps)
    for (const s of ep.shots)
      for (const c of s.characters ?? []) {
        let u = m.get(c.character);
        if (!u) m.set(c.character, (u = { eps: new Map(), shots: 0 }));
        let byLook = u.eps.get(ep.number);
        if (!byLook) u.eps.set(ep.number, (byLook = new Map()));
        const k = c.look_id ?? "";
        byLook.set(k, [...(byLook.get(k) ?? []), s]);
        u.shots++;
      }
  return m;
}

function letterOf(ch: CharacterAssets, lk: LookView | undefined) {
  if (!lk) return "?";
  if (lk.label) return lk.label;
  const i = ch.looks.findIndex((x) => x.id === lk.id);
  return LETTERS[i] ?? "?";
}
const hue = (i: number) => `var(${LOOK_HUES[i % LOOK_HUES.length]})`;

export default function AssetsPage() {
  const [chars, setChars] = useState<CharacterAssets[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [eps, setEps] = useState<LightEpisode[] | null>(null);
  const [epsErr, setEpsErr] = useState<string | null>(null);
  const [cid, setCid] = useState<string | null>(() => new URLSearchParams(location.hash.split("?")[1] ?? "").get("char"));
  const [detail, setDetail] = useState<(CharacterAssets & { episodes?: number[] }) | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [lookFilter, setLookFilter] = useState<string | null>(null);
  const [epFilter, setEpFilter] = useState<number | null>(null);
  const [showShots, setShowShots] = useState(false);
  const [big, setBig] = useState<{ url: string; label: string } | null>(null);
  const [tab, setTab] = useState<"chars" | "scenes">(() => (new URLSearchParams(location.hash.split("?")[1] ?? "").get("tab") === "scenes" ? "scenes" : "chars"));
  const [sceneDrawer, setSceneDrawer] = useState<DrawerTarget | null>(null);
  const es = useEdit();

  useEffect(() => {
    api.assets
      .list()
      .then((c) => setChars(c.characters))
      .catch((e) => setErr(isNotReady(e) ? "后端未就绪：/api/assets/characters" : errText(e)));
    assetsV1.episodes().then(setEps).catch((e) => setEpsErr(errText(e)));
  }, []);
  useEffect(() => {
    if (!cid && chars?.length) setCid(chars[0].id);
  }, [chars, cid]);
  useEffect(() => {
    if (!cid) return;
    let alive = true;
    setDetail(null);
    setDetailErr(null);
    setLookFilter(null);
    setEpFilter(null);
    setShowShots(false);
    api.assets
      .character(cid)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setDetailErr(errText(e)));
    return () => {
      alive = false;
    };
  }, [cid]);
  useEffect(() => {
    if (!big) return;
    const on = (e: KeyboardEvent) => e.key === "Escape" && setBig(null);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [big]);

  const usage = useMemo(() => (eps ? buildUsage(eps) : null), [eps]);
  const nEp = eps?.length ? Math.max(...eps.map((e) => e.number)) : 0;
  const ch = detail ?? chars?.find((c) => c.id === cid) ?? null;
  const u = ch ? usage?.get(ch.id) : undefined;
  const heroUrl = ch ? ch.hero?.url ?? ch.face_url ?? null : null;

  function openEditor(kind: "look" | PartKey, asset: string, label: string) {
    if (!ch) return;
    // W4b 的资产编辑抽屉（§7.3 与精修共用同一个编辑器）；资产页不在某一镜里，抽屉的“本镜”取该角色第一次出场的镜头
    const first = u ? [...u.eps.entries()].sort((a, b) => a[0] - b[0])[0]?.[1].values().next().value?.[0] : undefined;
    setEdit(() => ({ drawer: { shot: first?.id ?? "", asset, character: ch.id, label, kind, fromTake: null } }));
  }
  const pickTab = (t: "chars" | "scenes") => {
    setTab(t);
    const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
    if (t === "scenes") q.set("tab", "scenes");
    else q.delete("tab");
    history.replaceState(null, "", `${location.pathname}${location.search}#/assets${q.toString() ? `?${q}` : ""}`);
  };
  const shotById = (id: string) =>
    (eps?.flatMap((e) => e.shots).find((s) => s.id === id) ?? { id, index: 0, adult: false, first_frame: null, characters: [] }) as unknown as ShotSummary;
  const drawerShot = es.drawer
    ? ((eps?.flatMap((e) => e.shots).find((s) => s.id === es.drawer!.shot) ?? { id: es.drawer.shot, index: 0, adult: false, first_frame: null, characters: [] }) as unknown as ShotSummary)
    : null;

  return (
    <div className="v3p-page v3p-assets">
      <header className="v3p-head">
        <span className="v3p-step">②</span>
        <h1>资产</h1>
        <div className="v3p-tabs v3p-assettabs" role="tablist">
          <button role="tab" aria-selected={tab === "chars"} className={tab === "chars" ? "on" : ""} onClick={() => pickTab("chars")}>角色</button>
          <button role="tab" aria-selected={tab === "scenes"} className={tab === "scenes" ? "on" : ""} onClick={() => pickTab("scenes")}>场景</button>
        </div>
        <span className="v3p-muted">
          {tab === "chars" ? "形象、部件、按集排期；点“用到的镜头”反查。" : "每个场景的底图、出现集数、时段变体、定稿状态。"}改资产点卡片进编辑器（换参考 / 生成 / 上传）。
        </span>
        <span className="grow" />
        <a className="btn-mini" href="/?view=assets" title="旧资产页：衣橱、身份底板、生成">完整资产库 ↗</a>
      </header>

      {tab === "scenes" && (
        <ScenesTab
          eps={eps}
          onOpen={(sc, label) => setSceneDrawer({ shot: "", asset: sc.scene_id, character: "", label, kind: "scene", fromTake: null })}
        />
      )}
      {tab === "chars" && err && <p className="v3p-err">{err}</p>}
      {tab === "chars" && !chars && !err && <p className="v3p-muted">加载角色…</p>}

      {tab === "chars" && chars && <CharTabs chars={chars} cid={cid} usage={usage} epsLoaded={!!eps} onPick={setCid} />}

      {tab === "chars" && ch && (
        <section className="v3p-chardetail">
          <div className="v3p-charbody">
            {detailErr && <p className="v3p-err">{detailErr}</p>}

            <Block
              title={
                <>
                  {ch.name} <span className="v3p-blocksub">· 形象</span>
                </>
              }
              hint={`形象 ${ch.looks.length} · ${u ? `出现 ${u.eps.size} 集 · ${u.shots} 镜` : epsErr ? "出场统计读不到" : "统计中…"}　整套造型；按集排期决定哪集用哪套`}
              extra={ch.missing_count > 0 ? <span className="v3p-warn v3p-small">缺 {ch.missing_count} 张参考图</span> : undefined}
            >
              <div className="v3p-looks">
                {ch.looks.map((lk, i) => {
                  const nEps = u ? [...u.eps.values()].filter((m) => m.has(lk.id)).length : 0;
                  const nShots = u ? [...u.eps.values()].reduce((a, m) => a + (m.get(lk.id)?.length ?? 0), 0) : lk.used_by_shots;
                  const on = lookFilter === lk.id;
                  const own = lk.preview_url ?? lk.reference_urls?.[0] ?? null;
                  const img = own ?? heroUrl;
                  return (
                    <div key={lk.id} className={`v3p-look${on ? " on" : ""}`} style={{ ["--look" as string]: hue(i) }}>
                      <div className="v3p-look-img" onClick={() => img && setBig({ url: img, label: `${ch.name} · 形象 ${letterOf(ch, lk)}` })}>
                        {img ? <img src={img} alt="" loading="lazy" /> : <span className="v3p-initial">{letterOf(ch, lk)}</span>}
                        {img && !own && <span className="v3p-look-fallback" title="这个形象还没有自己的图，先显示角色主图">角色主图</span>}
                        <span className="v3p-look-letter">{letterOf(ch, lk)}</span>
                        {ch.default_look_id === lk.id && <span className="v3p-look-def">集默认</span>}
                      </div>
                      <div className="v3p-look-meta">
                        <b>{lk.name || lk.id}</b>
                        <span className="v3p-muted">{nEps} 集 · {nShots} 镜</span>
                      </div>
                      <div className="v3p-look-act">
                        <button
                          className="btn-mini"
                          onClick={() => {
                            setLookFilter(on ? null : lk.id);
                            setShowShots(true);
                          }}
                        >
                          用到的镜头
                        </button>
                        <button className="btn-mini" onClick={() => openEditor("look", lk.id, `${ch.name} · 形象 ${letterOf(ch, lk)}`)}>编辑</button>
                      </div>
                    </div>
                  );
                })}
                {ch.looks.length === 0 && <p className="v3p-muted">还没有形象。</p>}
              </div>
            </Block>

            <Block title="部件" hint="服装 / 鞋 / 妆 / 甲 / 发 / 饰；点缩略图编辑">
              <div className="v3p-parts">
                {PARTS.map(([k, label]) => {
                  const items = ch.wardrobe.filter((w) => w.slot === k).sort((a, b) => Number(!!b.thumb_url) - Number(!!a.thumb_url) || b.used_by_shots - a.used_by_shots);
                  return (
                    <div key={k} className="v3p-partrow">
                      <span className="v3p-partlabel">{label}</span>
                      <div className="v3p-partstrip">
                        {items.length === 0 && <span className="v3p-muted v3p-small">—</span>}
                        {items.map((w) => (
                          <PartThumb key={w.id} w={w} onOpen={() => openEditor(k, w.id, `${ch.name} · ${label} · ${w.name}`)} />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Block>

            <Block title="参考图" hint="身份底板、定妆、表情">
              <RefStrip ch={ch} onBig={setBig} />
            </Block>

            <Block title="按集排期" hint="每格一集；颜色 = 那集用的形象；点格子看那集的镜头">
              {!eps ? (
                <p className="v3p-muted">{epsErr ?? "加载中…"}</p>
              ) : (
                <>
                  <div className="v3p-sched" style={{ gridTemplateColumns: `repeat(${Math.min(nEp, 30)}, 1fr)` }}>
                    {Array.from({ length: nEp }, (_, i) => i + 1).map((n) => {
                      const m = u?.eps.get(n);
                      const looks = m ? [...m.keys()] : [];
                      const tip = m
                        ? `第 ${n} 集：${looks.map((l) => `形象 ${letterOf(ch, ch.looks.find((x) => x.id === l))} · ${m.get(l)!.length} 镜`).join("，")}`
                        : `第 ${n} 集：不出场`;
                      return (
                        <button
                          key={n}
                          className={`v3p-sched-cell${m ? "" : " off"}${epFilter === n ? " on" : ""}`}
                          title={tip}
                          aria-label={tip}
                          disabled={!m}
                          onClick={() => {
                            setEpFilter(epFilter === n ? null : n);
                            setShowShots(true);
                          }}
                        >
                          {looks.map((l) => (
                            <i key={l} style={{ background: hue(Math.max(0, ch.looks.findIndex((x) => x.id === l))) }} />
                          ))}
                          <span>{n}</span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="v3p-legend">
                    {ch.looks.map((lk, i) => (
                      <span key={lk.id}>
                        <i style={{ background: hue(i) }} /> 形象 {letterOf(ch, lk)}
                      </span>
                    ))}
                    <span>
                      <i className="off" /> 不出场
                    </span>
                  </div>
                </>
              )}
            </Block>

            <Block
              title="用到的镜头"
              hint={[lookFilter && `形象 ${letterOf(ch, ch.looks.find((x) => x.id === lookFilter))}`, epFilter && `第 ${epFilter} 集`].filter(Boolean).join(" · ") || "全部"}
              extra={
                <>
                  {(lookFilter || epFilter) && (
                    <button className="btn-mini" onClick={() => { setLookFilter(null); setEpFilter(null); }}>清除筛选</button>
                  )}
                  <button className="btn-mini" onClick={() => setShowShots(!showShots)}>{showShots ? "收起" : "展开"}</button>
                </>
              }
            >
              {showShots && u && <ShotList ch={ch} u={u} look={lookFilter} ep={epFilter} />}
              {showShots && !u && <p className="v3p-muted">{eps ? "这个角色没有出场镜头。" : epsErr ?? "加载中…"}</p>}
            </Block>
          </div>
        </section>
      )}

      {big && (
        <div className="v3p-lightbox" onClick={() => setBig(null)} role="dialog" aria-label={big.label}>
          <img src={big.url} alt={big.label} />
          <span>{big.label} · Esc 关闭</span>
        </div>
      )}

      {drawerShot && <AssetDrawer shot={drawerShot} />}
      {sceneDrawer && <AssetDrawer shot={shotById(sceneDrawer.shot)} open={sceneDrawer} onClose={() => setSceneDrawer(null)} />}
    </div>
  );
}

function CharTabs({ chars, cid, usage, epsLoaded, onPick }: { chars: CharacterAssets[]; cid: string | null; usage: Map<string, Usage> | null; epsLoaded: boolean; onPick: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState({ l: false, r: false });
  const sync = () => {
    const el = ref.current;
    if (el) setEdge({ l: el.scrollLeft > 2, r: el.scrollLeft + el.clientWidth < el.scrollWidth - 2 });
  };
  useEffect(() => {
    sync();
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    return () => ro.disconnect();
  }, [chars.length]);
  // 选中的人物滚进可见范围
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>(".v3p-charcard.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [cid]);
  const step = (d: number) => ref.current?.scrollBy({ left: d * Math.max(200, (ref.current?.clientWidth ?? 600) * 0.7), behavior: "smooth" });
  return (
    <div className={`v3p-chartabs${edge.l || edge.r ? " over" : ""}`}>
      <button className="v3p-chararrow" disabled={!edge.l} onClick={() => step(-1)} aria-label="向左滚动人物">‹</button>
      <div className="v3p-charrow" role="listbox" aria-label="角色" ref={ref} onScroll={sync}>
        {chars.map((c) => {
          const cu = usage?.get(c.id);
          const img = c.hero?.url ?? c.face_url;
          const use = cu ? `出现 ${cu.eps.size} 集 · ${cu.shots} 镜` : epsLoaded ? "未出场" : "…";
          const meta = `形象 ${c.looks.length} · ${use}`;
          return (
            <button key={c.id} role="option" aria-selected={c.id === cid} className={`v3p-charcard${c.id === cid ? " on" : ""}`} onClick={() => onPick(c.id)} title={`${c.name} · ${meta}`}>
              <div className="v3p-portrait">
                {img ? <img src={img} alt="" loading="lazy" /> : <span className="v3p-initial">{c.name.slice(0, 1)}</span>}
              </div>
              <div className="v3p-charcard-meta">
                <b>
                  {c.name} <small>形象 {c.looks.length}</small>
                </b>
                <span>{use}</span>
              </div>
            </button>
          );
        })}
      </div>
      <button className="v3p-chararrow" disabled={!edge.r} onClick={() => step(1)} aria-label="向右滚动人物">›</button>
    </div>
  );
}

function Block({ title, hint, extra, children }: { title: ReactNode; hint?: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <div className="v3p-block">
      <div className="v3p-block-head">
        <h3>{title}</h3>
        {hint && <span className="v3p-muted v3p-small">{hint}</span>}
        <span className="grow" />
        {extra}
      </div>
      {children}
    </div>
  );
}

function PartThumb({ w, onOpen }: { w: WardrobeItemView; onOpen: () => void }) {
  return (
    <button className="v3p-part" onClick={onOpen} title={`${w.name}${w.used_by_shots ? ` · 用于 ${w.used_by_shots} 镜` : ""} · 点一下编辑`}>
      <div className="v3p-part-img">{w.thumb_url ? <img src={w.thumb_url} alt="" loading="lazy" /> : <span className="v3p-muted v3p-small">无图</span>}</div>
      <span className="v3p-part-name">{w.name}</span>
    </button>
  );
}

function RefStrip({ ch, onBig }: { ch: CharacterAssets; onBig: (b: { url: string; label: string }) => void }) {
  const PL: Record<string, string> = { front: "正", "3q": "3/4", side: "侧", back: "背" };
  const list: { e: AssetEntry; label: string }[] = [];
  if (ch.master?.url) list.push({ e: ch.master, label: "母版" });
  for (const [k, e] of Object.entries(ch.plates)) if (e?.url) list.push({ e, label: `底板 ${PL[k] ?? k}` });
  for (const e of ch.portraits) if (e.url) list.push({ e, label: "定妆" });
  for (const e of ch.look_images) if (e.url) list.push({ e, label: e.name ?? "形象图" });
  for (const e of ch.expressions) if (e.url) list.push({ e, label: e.name ?? "表情" });
  if (!list.length) return <p className="v3p-muted">还没有参考图。</p>;
  return (
    <div className="v3p-refs">
      {list.map(({ e, label }) => (
        <button key={e.file} className="v3p-ref" onClick={() => onBig({ url: e.url!, label: `${ch.name} · ${label}` })} title={e.file}>
          <img src={e.url!} alt="" loading="lazy" />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}

function ShotList({ ch, u, look, ep }: { ch: CharacterAssets; u: Usage; look: string | null; ep: number | null }) {
  const rows = [...u.eps.entries()]
    .filter(([n]) => ep == null || n === ep)
    .sort((a, b) => a[0] - b[0])
    .map(([n, m]) => {
      const shots = [...m.entries()]
        .filter(([l]) => look == null || l === look)
        .flatMap(([l, ss]) => ss.map((s) => ({ s, l })))
        .sort((a, b) => a.s.index - b.s.index);
      return { n, shots };
    })
    .filter((r) => r.shots.length);
  if (!rows.length) return <p className="v3p-muted">没有符合的镜头。</p>;
  return (
    <div className="v3p-shotlist">
      {rows.map((r) => (
        <div key={r.n} className="v3p-shotep">
          <span className="v3p-shotep-n mono">ep{pad(r.n)}</span>
          <div className="v3p-shotchips">
            {r.shots.map(({ s, l }) => {
              const lk = ch.looks.find((x) => x.id === l);
              return (
                <a key={s.id} className="v3p-shotchip" href={`/#/${s.id}`} title={`${s.id} · 形象 ${letterOf(ch, lk)}`}>
                  <div className="v3p-shotchip-img">
                    {s.first_frame ? <img src={s.first_frame} alt="" loading="lazy" /> : <span className="v3p-muted v3p-small">未出</span>}
                  </div>
                  <span className="mono">S{s.index}</span>
                  <span className="v3p-shotchip-look" style={{ background: hue(Math.max(0, ch.looks.findIndex((x) => x.id === l))) }}>{letterOf(ch, lk)}</span>
                </a>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
