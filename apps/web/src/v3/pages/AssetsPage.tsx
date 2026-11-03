// fredw-92/W4c：资产页（#/assets，canvas-ui-spec-v3-merge §4 / §7.3，api_v1_contract §E）。
// 小云雀式角色卡：大头像、形象数、出现集数；点开看参考图、部件（服装 / 鞋 / 妆 / 甲 / 发 / 饰）、形象 A/B/C、
// 按集排期（哪几集用哪套）、“用到的镜头”反查。编辑走 W4b 的资产编辑抽屉（v3/edit/AssetDrawer），不另做一套。
// 出现集数 / 排期 / 反查都来自 /api/episodes/summary 每镜的出场人物与造型（实际编译结果），不另算。
// fredw-92/UXF3（UX 审查第 1 轮 #33–#36 #38 #39）：抽屉从资产页打开不带镜头上下文、带上资产现有的图；
// 形象统一叫“形象 A/B/C”，可新建形象（复制部件，参考图 / 版本各自独立；哪集用哪套仍由项目方确认）；
// 单品同名合并显示（“重复”角标，不删数据）、名字后缀变成图片标签、搜索 / 只看无图 / 展开全部；无图单品可“生成单品图”“上传图”。
import { shotLookKey, type ShotCharLike } from "../assets/center";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api";
import { useStudio } from "../../store";
import type { AssetEntry, CharacterAssets, LookView, ShotSummary, WardrobeItemView } from "../../types";
import { assetsV1, errText, isNotReady, type LightEpisode, type LightShot } from "../api_v1_pages";
import { AssetDrawer, type DrawerTarget } from "../edit/AssetDrawer";
import ScenesTab from "./ScenesTab";
import type { PartKey } from "../api_v1";
import { lookImage, lookLetter, lookTitle as sharedLookTitle, bumpLooks } from "../looks";
import { useSop } from "../sop.helpers";
import { OwnerDecisionDialog } from "../OwnerDecision";
import { isLookWaiting, lookWaitText, useOwnerDecisionApi } from "../OwnerDecision.helpers";
import type { SopOwnerAction } from "../../types";
import { LoadError } from "../../ds"; // UX5（D4）
import "./pages.css";
import { TERM } from "../words"; // UXF5（审查 R6）术语表

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
/** 每类部件先显示几组，其余“展开全部” */
const PART_FOLD = 8;

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
        const k = shotLookKey(c as ShotCharLike); // DATAALIGN：series10 按出图同源字母分组
        byLook.set(k, [...(byLook.get(k) ?? []), s]);
        u.shots++;
      }
  return m;
}

/** 形象字母 / 标题 / 图：与本镜参考条、参考切换面板共用 v3/looks.ts（审查 #31） */
const letterOf = (ch: CharacterAssets, lk: LookView | undefined) => lookLetter(ch, lk);
const lookTitle = (ch: CharacterAssets, lk: LookView) => sharedLookTitle(ch, lk);
const hue = (i: number) => `var(${LOOK_HUES[i % LOOK_HUES.length]})`;

// ---------------------------------------------------------------- 单品同名合并（只是显示，不改数据）

const SUFFIX_RE = /\s*[（(]([^（）()]*)[）)]\s*$/;
const TAG_WORD: Record<string, string> = { 产品: "产品图", 上身: "上身图" };
/** “黑色漆皮束腰（产品）” → base “黑色漆皮束腰”、tags [“产品图”] */
function splitName(n: string): { base: string; tags: string[] } {
  let base = n.trim();
  const tags: string[] = [];
  for (let m = base.match(SUFFIX_RE); m && m.index && m.index > 0; m = base.match(SUFFIX_RE)) {
    tags.unshift(TAG_WORD[m[1].trim()] ?? m[1].trim());
    base = base.slice(0, m.index).trim();
  }
  return { base: base || n, tags };
}
interface PartGroup {
  key: string;
  base: string;
  items: WardrobeItemView[];
  rep: WardrobeItemView;
  thumb: string | null;
  used: number;
}
function groupParts(items: WardrobeItemView[]): PartGroup[] {
  const m = new Map<string, WardrobeItemView[]>();
  const baseOf = new Map<string, string>();
  for (const w of items) {
    const { base } = splitName(w.name);
    const k = base.replace(/\s+/g, "");
    m.set(k, [...(m.get(k) ?? []), w]);
    if (!baseOf.has(k)) baseOf.set(k, base);
  }
  return [...m.entries()]
    .map(([key, list]) => {
      const sorted = [...list].sort((a, b) => Number(!!b.thumb_url) - Number(!!a.thumb_url) || b.used_by_shots - a.used_by_shots);
      return { key, base: baseOf.get(key) ?? key, items: sorted, rep: sorted[0], thumb: sorted.find((x) => x.thumb_url)?.thumb_url ?? null, used: list.reduce((a, x) => a + x.used_by_shots, 0) };
    })
    .sort((a, b) => Number(!!b.thumb) - Number(!!a.thumb) || b.used - a.used);
}

/** UX5：资产中心（v3/assets/AssetCenter）里“角色详情”复用这一页；embed 时不画页头、页签和人物横条，人物由外面指定 */
export default function AssetsPage({ embed }: { embed?: { cid: string } } = {}) {
  const studio = useStudio();
  const [chars, setChars] = useState<CharacterAssets[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [eps, setEps] = useState<LightEpisode[] | null>(null);
  const [epsErr, setEpsErr] = useState<string | null>(null);
  const [cidState, setCid] = useState<string | null>(() => new URLSearchParams(location.hash.split("?")[1] ?? "").get("char"));
  const cid = embed?.cid ?? cidState;
  const [detail, setDetail] = useState<(CharacterAssets & { episodes?: number[] }) | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [lookFilter, setLookFilter] = useState<string | null>(null);
  const [epFilter, setEpFilter] = useState<number | null>(null);
  const [showShots, setShowShots] = useState(false);
  const [big, setBig] = useState<{ url: string; label: string } | null>(null);
  const [tabState, setTab] = useState<"chars" | "scenes">(() => (new URLSearchParams(location.hash.split("?")[1] ?? "").get("tab") === "scenes" ? "scenes" : "chars"));
  const tab = embed ? "chars" : tabState;
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null);
  const [newLook, setNewLook] = useState<{ name: string; letter: string; from: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [pq, setPq] = useState("");
  const [noImgOnly, setNoImgOnly] = useState(false);
  const [unfold, setUnfold] = useState<Record<string, boolean>>({});
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const upRef = useRef<HTMLInputElement>(null);
  const upFor = useRef<WardrobeItemView | null>(null);

  const loadChars = () =>
    api.assets
      .list()
      .then((c) => setChars(c.characters))
      .catch((e) => setErr(isNotReady(e) ? "角色列表暂时读不到：后台还没提供这项功能" : errText(e)));
  useEffect(() => {
    void loadChars();
    assetsV1.episodes().then(setEps).catch((e) => setEpsErr(errText(e)));
  }, []);
  useEffect(() => {
    if (!cid && chars?.length) setCid(chars[0].id);
  }, [chars, cid]);
  useEffect(() => {
    setLookFilter(null);
    setEpFilter(null);
    setShowShots(false);
    setNewLook(null);
    setOpenGroup(null);
  }, [cid]);
  useEffect(() => {
    if (!cid) return;
    let alive = true;
    if (!reload) setDetail(null);
    setDetailErr(null);
    api.assets
      .character(cid)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setDetailErr(errText(e)));
    return () => {
      alive = false;
    };
  }, [cid, reload]);
  useEffect(() => {
    if (!big) return;
    const on = (e: KeyboardEvent) => e.key === "Escape" && setBig(null);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [big]);

  const usage = useMemo(() => (eps ? buildUsage(eps) : null), [eps]);
  const nEp = eps?.length ? Math.max(...eps.map((e) => e.number)) : 0;
  const ch = detail && detail.id === cid ? detail : chars?.find((c) => c.id === cid) ?? null;
  const u = ch ? usage?.get(ch.id) : undefined;
  const heroUrl = ch ? ch.hero?.url ?? ch.face_url ?? null : null;
  const curEp = studio.epNum;
  const curLooks = u?.eps.get(curEp);

  /** 资产页打开抽屉：不带镜头（审查 #34），带上卡片上的图（审查 #33） */
  function openEditor(kind: "look" | PartKey, asset: string, label: string, img?: string | null) {
    if (!ch) return;
    setDrawer({ shot: "", asset, character: ch.id, label, kind, fromTake: null, context: "assets", img: img ?? null });
  }
  const closeDrawer = () => {
    setDrawer(null);
    setReload((n) => n + 1); // 抽屉里可能存了新版本 / 新图
    bumpLooks();
  };
  const pickTab = (t: "chars" | "scenes") => {
    setTab(t);
    const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
    if (t === "scenes") q.set("tab", "scenes");
    else q.delete("tab");
    history.replaceState(null, "", `${location.pathname}${location.search}#/assets${q.toString() ? `?${q}` : ""}`);
  };
  const stubShot = { id: "", index: 0, adult: false, first_frame: null, characters: [] } as unknown as ShotSummary;

  // ---------- 新建形象（复制部件；参考图 / 版本按新 id 各自独立；不排进任何一集） ----------
  function startNewLook() {
    if (!ch) return;
    const used = new Set(ch.looks.map((l) => letterOf(ch, l)));
    const letter = [...LETTERS].find((x) => !used.has(x)) ?? "Z";
    setNewLook({ name: "", letter, from: ch.default_look_id ?? ch.looks[0]?.id ?? "" });
  }
  async function createLook() {
    if (!ch || !newLook) return;
    const letter = newLook.letter.trim().toUpperCase() || "B";
    if (ch.looks.some((l) => letterOf(ch, l) === letter)) return studio.notify(`形象 ${letter} 已经有了，换一个字母`, "err");
    const src = ch.looks.find((l) => l.id === newLook.from);
    const ids = new Set(ch.looks.map((l) => l.id));
    let id = `${ch.id}-look-${letter.toLowerCase()}`;
    for (let k = 2; ids.has(id); k++) id = `${ch.id}-look-${letter.toLowerCase()}${k}`;
    setBusy(true);
    try {
      await api.looks.putLook({
        id,
        character: ch.id,
        name: newLook.name.trim(),
        label: letter,
        items: src ? JSON.parse(JSON.stringify(src.items ?? {})) : {},
        decor_state: src?.decor_state ?? null,
        reference_images: [],
        preview_image: null,
        needs_review: false,
        notes: [src ? `资产页新建：部件复制自 ${lookTitle(ch, src)}（${src.id}）` : "资产页新建"],
        version: 1,
      });
      studio.notify(`已新建形象 ${letter}${src ? `（部件复制自形象 ${letterOf(ch, src)}）` : ""}；哪集用哪套由项目方确认`);
      setNewLook(null);
      setReload((n) => n + 1);
      void loadChars();
      bumpLooks();
    } catch (e) {
      studio.notify(`新建形象：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  }

  // ---------- 单品上传图 ----------
  function pickUpload(w: WardrobeItemView) {
    upFor.current = w;
    upRef.current?.click();
  }
  async function doUpload(f: File) {
    const w = upFor.current;
    if (!w) return;
    if (w.used_by_shots > 0 && !window.confirm(`“${w.name}”用于 ${w.used_by_shots} 镜。加图后这些镜的首帧会标为过期，确定上传？`)) return;
    setBusy(true);
    try {
      const r = await api.looks.uploadItemImage(w.id, f, "clean");
      studio.notify(`已上传到“${w.name}”${r.affected_count ? `；${r.affected_count} 镜标为过期` : ""}`);
      setReload((n) => n + 1);
    } catch (e) {
      studio.notify(`上传图：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  }

  const lookCount = ch?.looks.length ?? 0;

  return (
    <div className={`v3p-page v3p-assets${embed ? " embed" : ""}`}>
      {!embed && <header className="v3p-head">
        <span className="v3p-step">②</span>
        <h1>{TERM.assets}</h1>
        <div className="v3p-tabs v3p-assettabs" role="tablist">
          <button role="tab" aria-selected={tab === "chars"} className={tab === "chars" ? "on" : ""} onClick={() => pickTab("chars")}>角色</button>
          <button role="tab" aria-selected={tab === "scenes"} className={tab === "scenes" ? "on" : ""} onClick={() => pickTab("scenes")}>场景</button>
        </div>
        <span className="v3p-muted">
          {tab === "chars" ? "形象、部件、按集排期；点“用到的镜头”反查。" : "每个场景的底图、出现集数、时段变体、定稿状态。"}改资产点卡片进编辑器（换参考 / 生成 / 上传）。
        </span>
        <span className="grow" />
        <a className="btn-mini" href="/?view=assets&legacy=1" title="旧资产页（已并入资产中心，旧页保留）：身份底板生成、导入 manifest">旧资产库 ↗</a>
      </header>}

      {tab === "scenes" && (
        <ScenesTab
          eps={eps}
          onOpen={(sc, label) => setDrawer({ shot: "", asset: sc.scene_id, character: "", label, kind: "scene", fromTake: null, context: "assets", img: sc.plate?.url ?? null })}
        />
      )}
      {tab === "chars" && err && <LoadError what="角色列表" err={err} retry={() => void loadChars()} />}
      {tab === "chars" && !chars && !err && <p className="v3p-muted">加载角色…</p>}

      {tab === "chars" && chars && !embed && <CharTabs chars={chars} cid={cid} usage={usage} epsLoaded={!!eps} onPick={setCid} />}

      {tab === "chars" && ch && (
        <section className="v3p-chardetail">
          <div className="v3p-charbody">
            {detailErr && <LoadError what="角色详情" err={detailErr} retry={() => setReload((n) => n + 1)} />}

            {/* UX4（小云雀走查 #9）：角色卡一页看全——正面 / 半身 / 全身 / 转面 + 辨识特征 / 着装描述（剧本原文） */}
            <CharViews ch={ch} onBig={setBig} />

            <Block
              title={
                <>
                  {ch.name} <span className="v3p-blocksub">· 形象 {ch.looks.map((l) => letterOf(ch, l)).join(" / ") || "—"}</span>
                </>
              }
              hint={`${u ? `出现 ${u.eps.size} 集 · ${u.shots} 镜` : epsErr ? "出场统计读不到" : "统计中…"}　整套造型；哪集用哪套由项目方确认`}
              extra={ch.missing_count > 0 ? <span className="v3p-warn v3p-small">缺 {ch.missing_count} 张参考图</span> : undefined}
            >
              <div className="v3p-curep" aria-live="polite">
                <b>第 {curEp} 集用：</b>
                {!eps ? (
                  <span className="v3p-muted">统计中…</span>
                ) : curLooks?.size ? (
                  [...curLooks.entries()].map(([l, ss]) => {
                    const lk = ch.looks.find((x) => x.id === l);
                    const i = Math.max(0, ch.looks.findIndex((x) => x.id === l));
                    return (
                      <span key={l} className="v3p-curep-look" style={{ ["--look" as string]: hue(i) }}>
                        <i>{letterOf(ch, lk)}</i>
                        {lk ? lookTitle(ch, lk) : l || "未指定形象"} · {ss.length} 镜
                      </span>
                    );
                  })
                ) : (
                  <span className="v3p-muted">这一集不出场</span>
                )}
                {curLooks?.size ? <LookConfirm charId={ch.id} ep={curEp} /> : null}
              </div>
              <div className="v3p-looks">
                {ch.looks.map((lk, i) => {
                  const nEps = u ? [...u.eps.values()].filter((m) => m.has(lk.id)).length : 0;
                  const nShots = u ? [...u.eps.values()].reduce((a, m) => a + (m.get(lk.id)?.length ?? 0), 0) : lk.used_by_shots;
                  const on = lookFilter === lk.id;
                  const li = lookImage(ch, lk);
                  const own = li.own ? li.url : null;
                  const img = li.url ?? heroUrl;
                  const title = lookTitle(ch, lk);
                  const inCur = !!curLooks?.has(lk.id);
                  return (
                    <div key={lk.id} className={`v3p-look${on ? " on" : ""}${inCur ? " cur" : ""}`} style={{ ["--look" as string]: hue(i) }}>
                      <div className="v3p-look-img" onClick={() => img && setBig({ url: img, label: `${ch.name} · ${title}` })}>
                        {img ? <img src={img} alt="" loading="lazy" /> : <span className="v3p-initial">{letterOf(ch, lk)}</span>}
                        {img && !own && <span className="v3p-look-fallback" title="这个形象还没有自己的图，先显示角色主图">角色主图</span>}
                        <span className="v3p-look-letter">{letterOf(ch, lk)}</span>
                        {ch.default_look_id === lk.id && <span className="v3p-look-def">集默认</span>}
                        {inCur && <span className="v3p-look-cur">第 {curEp} 集</span>}
                      </div>
                      <div className="v3p-look-meta">
                        <b title={lk.id}>{title}</b>
                        <span className="v3p-muted">{nEps} 集 · {nShots} 镜 · 部件 {Object.values(lk.items ?? {}).flat().length}</span>
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
                        <button className="btn-mini" onClick={() => openEditor("look", lk.id, `${ch.name} · ${title}`, own)}>编辑</button>
                      </div>
                    </div>
                  );
                })}
                {newLook ? (
                  <div className="v3p-look v3p-look-new form">
                    <div className="v3p-newlook">
                      <b>新建形象</b>
                      <label>
                        <span>字母</span>
                        <input value={newLook.letter} maxLength={2} onChange={(e) => setNewLook({ ...newLook, letter: e.target.value.toUpperCase() })} aria-label="形象字母" />
                      </label>
                      <label>
                        <span>名字</span>
                        <input value={newLook.name} placeholder="可空" onChange={(e) => setNewLook({ ...newLook, name: e.target.value })} aria-label="形象名字" />
                      </label>
                      <label>
                        <span>部件复制自</span>
                        <select value={newLook.from} onChange={(e) => setNewLook({ ...newLook, from: e.target.value })}>
                          {ch.looks.map((l) => (
                            <option key={l.id} value={l.id}>{lookTitle(ch, l)}</option>
                          ))}
                          <option value="">不复制（空形象）</option>
                        </select>
                      </label>
                      <span className="v3p-muted v3p-small">参考图、版本从零开始，各自独立；不会排进任何一集。</span>
                      <div className="v3p-look-act">
                        <button className="btn-mini on" disabled={busy || !newLook.letter.trim()} onClick={() => void createLook()}>新建形象 {newLook.letter.trim().toUpperCase()}</button>
                        <button className="btn-mini" onClick={() => setNewLook(null)}>取消</button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <button className="v3p-look v3p-look-new" onClick={startNewLook} title="复制一套现有形象的部件，另起一套造型">
                    <span className="v3p-look-img add">＋</span>
                    <span className="v3p-look-meta">
                      <b>新建形象</b>
                      <span className="v3p-muted">现有 {lookCount} 套</span>
                    </span>
                  </button>
                )}
              </div>
            </Block>

            <PartsBlock
              ch={ch}
              q={pq}
              setQ={setPq}
              noImgOnly={noImgOnly}
              setNoImgOnly={setNoImgOnly}
              unfold={unfold}
              setUnfold={setUnfold}
              openGroup={openGroup}
              setOpenGroup={setOpenGroup}
              busy={busy}
              onEdit={(k, label, w) => openEditor(k, w.id, `${ch.name} · ${label} · ${w.name}`, w.thumb_url)}
              onUpload={pickUpload}
            />
            <input
              ref={upRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void doUpload(f);
              }}
            />

            <Block title="参考图" hint="身份底板、定妆、表情">
              <RefStrip ch={ch} onBig={setBig} />
            </Block>

            <Block title="按集排期" hint={`每格一集；颜色 = 那集用的形象；带框的是当前第 ${curEp} 集；点格子看那集的镜头`}>
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
                          className={`v3p-sched-cell${m ? "" : " off"}${epFilter === n ? " on" : ""}${n === curEp ? " cur" : ""}`}
                          title={n === curEp ? `${tip}（当前集）` : tip}
                          aria-label={tip}
                          aria-current={n === curEp ? "true" : undefined}
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
                        <i style={{ background: hue(i) }} /> {lookTitle(ch, lk)}
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

      {drawer && <AssetDrawer shot={stubShot} open={drawer} onClose={closeDrawer} />}
    </div>
  );
}

function PartsBlock(p: {
  ch: CharacterAssets;
  q: string;
  setQ: (s: string) => void;
  noImgOnly: boolean;
  setNoImgOnly: (b: boolean) => void;
  unfold: Record<string, boolean>;
  setUnfold: (f: (m: Record<string, boolean>) => Record<string, boolean>) => void;
  openGroup: string | null;
  setOpenGroup: (k: string | null) => void;
  busy: boolean;
  onEdit: (k: PartKey, label: string, w: WardrobeItemView) => void;
  onUpload: (w: WardrobeItemView) => void;
}) {
  const { ch, q } = p;
  const ql = q.trim().toLowerCase();
  const total = ch.wardrobe.length;
  const noImg = ch.wardrobe.filter((w) => !w.thumb_url).length;
  const nDup = PARTS.reduce((a, [k]) => a + groupParts(ch.wardrobe.filter((w) => w.slot === k)).filter((g) => g.items.length > 1).length, 0);
  return (
    <Block
      title="部件"
      hint={`服装 / 鞋 / 妆 / 甲 / 发 / 饰 · ${total} 件${noImg ? ` · 无图 ${noImg}` : ""}${nDup ? ` · 同名 ${nDup} 组（合并显示，数据不动）` : ""}`}
      extra={
        <>
          <label className="v3p-chk">
            <input type="checkbox" checked={p.noImgOnly} onChange={(e) => p.setNoImgOnly(e.target.checked)} /> 只看无图
          </label>
          <input className="v3p-partsearch" placeholder="搜单品" value={q} onChange={(e) => p.setQ(e.target.value)} aria-label="搜单品" />
        </>
      }
    >
      <div className="v3p-parts">
        {PARTS.map(([k, label]) => {
          const groups = groupParts(ch.wardrobe.filter((w) => w.slot === k)).filter(
            (g) =>
              (!p.noImgOnly || g.items.some((w) => !w.thumb_url)) &&
              (!ql || g.items.some((w) => `${w.name} ${w.description ?? ""} ${(w.tags ?? []).join(" ")}`.toLowerCase().includes(ql))),
          );
          const all = !!p.unfold[k] || !!ql;
          const shown = all ? groups : groups.slice(0, PART_FOLD);
          const open = groups.find((g) => `${k}:${g.key}` === p.openGroup);
          if (!groups.length && (ql || p.noImgOnly)) return null; // 筛选时空的类不占行
          return (
            <div key={k} className="v3p-partrow">
              <span className="v3p-partlabel">{label}</span>
              <div className="v3p-partcol">
                <div className={`v3p-partstrip${all ? " wrap" : ""}`}>
                  {groups.length === 0 && <span className="v3p-muted v3p-small">{ql || p.noImgOnly ? "没有符合的" : "—"}</span>}
                  {shown.map((g) => (
                    <PartCard
                      key={g.key}
                      g={g}
                      open={open === g}
                      busy={p.busy}
                      onOpen={() => (g.items.length > 1 ? p.setOpenGroup(open === g ? null : `${k}:${g.key}`) : p.onEdit(k, label, g.rep))}
                      onGen={() => p.onEdit(k, label, g.rep)}
                      onUpload={() => p.onUpload(g.rep)}
                    />
                  ))}
                  {groups.length > PART_FOLD && !ql && (
                    <button className="v3p-part v3p-part-more" onClick={() => p.setUnfold((m) => ({ ...m, [k]: !m[k] }))}>
                      <span className="v3p-part-img">{all ? "收起" : `展开全部\n${groups.length}`}</span>
                    </button>
                  )}
                </div>
                {open && (
                  <div className="v3p-dupe" role="group" aria-label={`${open.base}：${open.items.length} 条登记`}>
                    <div className="v3p-dupe-h">
                      <b>{open.base}</b>
                      <span className="v3p-muted v3p-small">衣橱里有 {open.items.length} 条同名登记；合并只是显示，数据不动。挑一条编辑 / 补图。</span>
                      <span className="grow" />
                      <button className="btn-mini" onClick={() => p.setOpenGroup(null)}>收起</button>
                    </div>
                    <div className="v3p-dupe-list">
                      {open.items.map((w) => {
                        const { tags } = splitName(w.name);
                        return (
                          <div key={w.id} className="v3p-dupe-row">
                            <button className="v3p-part-img" onClick={() => p.onEdit(k, label, w)} title="编辑这一条">
                              {w.thumb_url ? <img src={w.thumb_url} alt="" loading="lazy" /> : <span className="v3p-muted v3p-small">无图</span>}
                            </button>
                            <div className="v3p-dupe-meta">
                              <span title={w.id}>{w.name}</span>
                              <span className="v3p-muted v3p-small">
                                {tags.length ? `${tags.join(" · ")} · ` : ""}
                                {w.image_urls?.length ?? w.images?.length ?? 0} 张图 · 用于 {w.used_by_shots} 镜
                              </span>
                              <div className="v3p-look-act">
                                <button className="btn-mini" onClick={() => p.onEdit(k, label, w)}>{w.thumb_url ? "编辑" : "生成单品图"}</button>
                                <button className="btn-mini" disabled={p.busy} onClick={() => p.onUpload(w)}>上传图</button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Block>
  );
}

function PartCard({ g, open, busy, onOpen, onGen, onUpload }: { g: PartGroup; open: boolean; busy: boolean; onOpen: () => void; onGen: () => void; onUpload: () => void }) {
  const tags = [...new Set(g.items.flatMap((w) => splitName(w.name).tags))];
  const dup = g.items.length > 1;
  const tip = `${g.base}${dup ? `（同名 ${g.items.length} 条：${g.items.map((w) => w.name).join("、")}）` : ""}${g.used ? ` · 用于 ${g.used} 镜` : ""} · ${dup ? "点一下看全部" : "点一下编辑"}`;
  return (
    <div className={`v3p-part${open ? " open" : ""}`}>
      <button className="v3p-part-img" onClick={onOpen} title={tip} aria-expanded={dup ? open : undefined}>
        {g.thumb ? <img src={g.thumb} alt="" loading="lazy" /> : <span className="v3p-muted v3p-small">无图</span>}
        {dup && <span className="v3p-part-dup">重复 ×{g.items.length}</span>}
        {tags.length > 0 && <span className="v3p-part-tag">{tags[0]}{tags.length > 1 ? ` +${tags.length - 1}` : ""}</span>}
      </button>
      <span className="v3p-part-name" title={tip}>{g.base}</span>
      {!g.thumb && !dup && (
        <span className="v3p-part-acts">
          <button className="btn-mini" onClick={onGen} title="打开编辑器：单品文字放在旁边作参考，提示词由你或写作模型写">生成单品图</button>
          <button className="btn-mini" disabled={busy} onClick={onUpload}>上传图</button>
        </span>
      )}
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
          const letters = c.looks.map((l) => letterOf(c, l)).join("/") || "—";
          const meta = `形象 ${letters} · ${use}`;
          return (
            <button key={c.id} role="option" aria-selected={c.id === cid} className={`v3p-charcard${c.id === cid ? " on" : ""}`} onClick={() => onPick(c.id)} title={`${c.name} · ${meta}`}>
              <div className="v3p-portrait">
                {img ? <img src={img} alt="" loading="lazy" /> : <span className="v3p-initial">{c.name.slice(0, 1)}</span>}
              </div>
              <div className="v3p-charcard-meta">
                <b>
                  {c.name} <small>· {c.looks.length} 个形象</small>
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

// ---------------------------------------------------------------- UX4（XYQ #9）角色卡多视图

/** 剧本里的人物文字（只读原文）：全局角色锁 / 人物表的外貌句、日常穿搭行。整页只读一次。 */
type CharText = { looks: Map<string, string>; outfit: string };
let charTextP: Promise<CharText> | null = null;
function loadCharText(): Promise<CharText> {
  if (!charTextP)
    charTextP = fetch("/api/projects")
      .then((r) => (r.ok ? r.json() : []))
      .then((ps: { slug: string; is_default?: boolean }[]) => {
        const slug = (ps.find((p) => p.is_default) ?? ps[0])?.slug;
        return slug ? fetch(`/api/projects/${encodeURIComponent(slug)}/file/data/import/script_v2.json`).then((r) => (r.ok ? r.json() : null)) : null;
      })
      .then((d: { globals?: { character_locks?: { name: string; description?: string }[]; character_registry?: { name: string; zh?: string }[]; daily_outfit?: string } } | null) => {
        const g = d?.globals;
        const looks = new Map<string, string>();
        for (const c of g?.character_locks ?? []) if (c.description) looks.set(c.name, c.description);
        for (const c of g?.character_registry ?? []) if (c.zh && c.zh !== "系统锁") looks.set(c.name, c.zh);
        return { looks, outfit: g?.daily_outfit ?? "" };
      })
      .catch(() => ({ looks: new Map<string, string>(), outfit: "" }));
  return charTextP;
}

type View = { key: string; label: string; hint: string; img: AssetEntry | null; sub?: { label: string; img: AssetEntry | null }[] };

/** 四格：正面 = 正脸底板；半身 = 母版（没有就定妆照）；全身 = 形象全身图（*_front）；转面 = 3/4 · 侧 · 背 底板（没有就用形象图的 34 / back） */
function viewsOf(ch: CharacterAssets): View[] {
  const has = (e: AssetEntry | null | undefined) => (e?.url ? e : null);
  // 形象图文件名形如 REF-LW-01_front_s0：按“_front / _34 / _back”片段认视角
  const lookImg = (suf: string) => ch.look_images.find((e) => e.url && new RegExp(`${suf}(_|$)`).test((e.category ?? "").toLowerCase())) ?? null;
  const full = lookImg("_front");
  return [
    { key: "front", label: "正面", hint: "正脸底板", img: has(ch.plates.front) },
    { key: "half", label: "半身", hint: "母版 / 定妆照", img: has(ch.master) ?? has(ch.portraits.find((e) => e.url)) },
    { key: "full", label: "全身", hint: full?.name ? `形象图：${full.name.replace(/[（(]front[）)]$/i, "")}` : "形象全身图", img: full },
    {
      key: "turn",
      label: "转面",
      hint: "3/4 侧 · 正侧 · 背面（身份底板）",
      img: null,
      sub: [
        { label: "3/4", img: has(ch.plates["3q"]) ?? lookImg("_34") },
        { label: "侧", img: has(ch.plates.side) },
        { label: "背", img: has(ch.plates.back) ?? lookImg("_back") },
      ],
    },
  ];
}

function CharViews({ ch, onBig }: { ch: CharacterAssets; onBig: (b: { url: string; label: string }) => void }) {
  const [txt, setTxt] = useState<CharText | null>(null);
  useEffect(() => {
    let alive = true;
    void loadCharText().then((t) => alive && setTxt(t));
    return () => {
      alive = false;
    };
  }, []);
  const views = viewsOf(ch);
  const look = txt?.looks.get(ch.name) ?? "";
  const outfit = txt?.outfit && txt.outfit.includes(ch.name) ? txt.outfit : "";
  const nHave = views.reduce((n, v) => n + (v.img ? 1 : 0) + (v.sub?.filter((x) => x.img).length ?? 0), 0);
  // 借小云雀角色详情的结构：每个视图一块深色圆角面板，左上角压白底小胶囊标签；没图就空面板 + 标签（不放按钮）
  const img = (e: AssetEntry | null, label: string) =>
    e?.url ? (
      <button className="v3p-cv-img" onClick={() => onBig({ url: e.url!, label: `${ch.name} · ${label}` })} title={`${label}：${e.name ?? e.file}（点开看大图）`}>
        <img src={e.url} alt="" loading="lazy" />
      </button>
    ) : (
      <span className="v3p-cv-img none" title={`${label}：还没有这张图`} />
    );
  const u = ch.looks.reduce((n, l) => n + (l.used_by_shots ?? 0), 0);
  return (
    <Block title={<>{ch.name} <span className="v3p-blocksub">· 角色卡</span></>} hint={`多视图 ${nHave}/6 张 · 点图看大图`}>
      <div className="v3p-cv">
        <div className="v3p-cv-views">
          {views.map((v) => (
            <figure key={v.key} className={`v3p-cv-panel k-${v.key}`} title={v.hint}>
              {v.sub ? <div className="v3p-cv-turn">{v.sub.map((x) => <div key={x.label} className="v3p-cv-sub">{img(x.img, `转面 ${x.label}`)}<small>{x.label}</small></div>)}</div> : img(v.img, v.label)}
              <figcaption className="v3p-cv-pill">{v.label}</figcaption>
            </figure>
          ))}
        </div>
        <div className="v3p-cv-side">
          <h4>人物属性</h4>
          <dl className="v3p-cv-kv">
            <dt>形象</dt>
            <dd>共 {ch.looks.length} 个</dd>
            <dt>部件</dt>
            <dd>{ch.wardrobe.length} 件</dd>
            <dt>表情</dt>
            <dd>{ch.expressions.length} 张</dd>
            <dt>出场</dt>
            <dd>{u} 镜</dd>
          </dl>
          <section>
            <h4>辨识特征</h4>
            <p title="剧本角色锁 / 人物表原文，只读">{look || <span className="v3p-muted">{txt ? "剧本人物表没写" : "读取中…"}</span>}</p>
          </section>
          {outfit && (
            <section>
              <h4>着装描述</h4>
              <p title="剧本里的日常穿搭行原文，只读">{outfit.replace(/\*\*/g, "")}</p>
            </section>
          )}
        </div>
      </div>
    </Block>
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

/** fredw-92/UXF5（审查 #39）：资产页直接确认“第 N 集用这套”——打开与顶栏“待你决定”同一个确认框（OwnerDecisionDialog，
 *  勾“我是项目方本人”+ 原话，POST /api/sop/owner-decision）；这里不另写确认逻辑 */
export function LookConfirm({ charId, ep }: { charId: string; ep: number }) {
  const { sop } = useSop();
  const api = useOwnerDecisionApi(); // UIFIX-F 11-03：后端没有确认接口 → 入口不显示
  const [open, setOpen] = useState<SopOwnerAction | null>(null);
  if (!sop) return <span className="v3p-muted v3p-small">读取确认状态…</span>;
  const a = (sop.owner_actions ?? []).find((x) => x.gate === "look" && x.character === charId);
  if (!a) return <span className="v3p-ok v3p-small" title="本集这个角色的造型已经由项目方确认过（或不需要确认）">✓ 第 {ep} 集造型已确认</span>;
  if (isLookWaiting(a)) return <span className="v3p-muted v3p-small">{lookWaitText(a)}</span>; // 造型确认属于资产阶段：身份脸没选定不开入口
  if (api === false) return null;
  return (
    <>
      <button className="btn-mini on v3p-confirm" onClick={() => setOpen(a)} title={`${a.why}
点开确认（与顶栏“待你决定”是同一个确认框）`}>
        确认第 {ep} 集用这套造型
      </button>
      {open && <OwnerDecisionDialog a={open} onClose={() => setOpen(null)} />}
    </>
  );
}
