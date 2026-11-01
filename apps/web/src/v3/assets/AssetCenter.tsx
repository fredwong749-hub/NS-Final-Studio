// UX5：资产中心（#/assets）——A_assets_ia.md §3 / §4.1 的实现。
// 一个入口管全部资产：角色（形象 · 衣橱）· 道具·产品 · 场景 · 风格（出图预设 · 视频出片方式 · 身份 LoRA）· 音色 · 提示词模板。
// 统一卡片 + 统一 5 个状态（草稿 / 候选 / 定稿 / 作废 / 依赖已更新），点卡看详情（版本栈 · 哪些镜头在用 · 影响面与重出）。
// 角色详情复用原角色页（pages/AssetsPage embed 模式）；场景的上传 / 批量生成复用原场景工作台（ScenesTab）。
// 路由：#/assets?type=<分类>&char=<角色>&from=<镜头>&q=<搜索>；旧的 ?tab=scenes / ?char= 照样能进。
// ASSETUX（项目方：“这个资产管理没有之前做的好，乱七八糟的”）：资产中心改成以人物为中心——
//   默认打开人物页（PeopleHub：一个人一页看全），左栏上半是当前剧的人物；场景 / 风格 / 声音等收到左栏下半“其他资产”。
//   旧的“总览 / 角色 / 形象 / 衣橱 / 挑设定图”路由都落到人物页；“全部资产”总览改叫 type=overview。
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store";
import { Button, Empty, LoadError, Loading, Seg, Skel } from "../../ds";
import { ASSET_STATUS, type AssetStatus } from "../../ds/helpers";
import { useSop } from "../sop.helpers";
import { AssetDrawer, type DrawerTarget } from "../edit/AssetDrawer";
import type { ShotSummary } from "../../types";
import { AssetCard } from "./AssetCard";
import { AssetInspector } from "./AssetInspector";
import { ImpactDrawer, type ImpactSource } from "./ImpactDrawer";
import { loadCenter, shotLookKey, TREE, type AssetCardData, type CenterData, type ShotCharLike } from "./center";
import { LoraTablePanel, PropsPanel, TemplatesPanel } from "./P1Panels";
import { VoiceStudio } from "./VoiceStudio";
import { LookConfirm } from "../pages/AssetsPage";
import ScenesTab from "../pages/ScenesTab";
import { lazy } from "react";

const PeoplePage = lazy(() => import("../../components/PeoplePage"));
import { PeopleHub, PeopleNav } from "./PeopleHub";
import { useHubList } from "./PeopleHub.helpers";
import { isQuarantined, loadQuarantine } from "./hub_api"; // ASSETUX：人物资产页
import "../pages/pages.css";
import "./center.css";


/** 能算出“当前剧本用到几集”的资产类型（其余如预设 / 音色 / LoRA 不按剧本过滤） */
const USAGE_TYPES = new Set(["character", "look", "item", "prop", "scene"]);

type Route = { type: string; char: string | null; from: string | null; q: string };
function readRoute(): Route {
  const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const legacyScene = q.get("tab") === "scenes";
  const char = q.get("char");
  return { type: q.get("type") ?? (legacyScene ? "scene" : char ? "character" : "people-hub"), char, from: q.get("from"), q: q.get("q") ?? "" };
}
function writeRoute(r: Partial<Route>, push = true) {
  const cur = readRoute();
  const n = { ...cur, ...r };
  const q = new URLSearchParams();
  if (n.type && n.type !== "people-hub") q.set("type", n.type);
  if (n.char) q.set("char", n.char);
  if (n.from) q.set("from", n.from);
  if (n.q) q.set("q", n.q);
  const h = `#/assets${q.toString() ? `?${q}` : ""}`;
  if (push) location.hash = h;
  else history.replaceState(null, "", `${location.pathname}${location.search}${h}`);
}

const STATUS_ORDER: AssetStatus[] = ["dep", "draft", "candidate", "final", "void"];
/** 这些旧路由都打开人物页 */
const PEOPLE_ROUTES = new Set(["people-hub", "all", "character", "look", "item", "sheets"]);
/** 左栏下半“其他资产”：只放人物页以外的类别 */
const OTHER_NODES = new Set(["prop", "scene", "style", "preset", "vbase", "lora", "loras", "voice", "template"]);

export default function AssetCenter() {
  const studio = useStudio();
  const ep = studio.epNum;
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const on = () => setRoute(readRoute());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const [data, setData] = useState<CenterData | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [q, setQ] = useState(route.q);
  // UIRSI（项目方：“界面不再显示任何旧数据”）：默认只看当前剧本用到的资产；不在当前剧本里的旧资产留在库中，切“全部（含旧）”才显示
  const [scope, setScope] = useState<"cur" | "all" | "ep">("cur");
  const inScope = (c: AssetCardData) => (scope === "all" ? true : scope === "ep" ? !c.eps || c.eps.includes(ep) : !c.eps || c.eps.length > 0 || !USAGE_TYPES.has(c.type));
  const [status, setStatus] = useState<AssetStatus | null>(null);
  const [insp, setInsp] = useState<AssetCardData | null>(null);
  const [impact, setImpact] = useState<ImpactSource | null>(null);
  const [edit, setEdit] = useState<DrawerTarget | null>(null);
  const [sceneMode, setSceneMode] = useState<"cards" | "bench">("cards");
  const [hubTick, setHubTick] = useState(0);
  const { list: hubList, err: hubErr } = useHubList(hubTick);
  const peopleMode = PEOPLE_ROUTES.has(route.type) || (!!route.char && route.type !== "people");
  const hubCid = route.char && hubList?.characters.some((c) => c.cid === route.char) ? route.char : peopleMode ? (route.char ?? hubList?.characters[0]?.cid ?? null) : null;

  const reload = useCallback(() => setTick((n) => n + 1), []);
  useEffect(() => {
    let alive = true;
    loadCenter((late) => alive && setData(late)).then(
      (d) => alive && (setData(d), setLoadErr(null)),
      (e) => alive && setLoadErr(String((e as Error).message ?? e)),
    );
    return () => {
      alive = false;
    };
  }, [tick]);

  // ASSETUX 11-01（RECALL 隔离旧剧资产后）：人物相关卡片只认当前剧演员表（人物资产页接口 = series10 的 P1 人物）；
  // 旧 60 集演员（Alex / Ryan / Kai / Leo）即使旧接口还列着，也不在资产中心任何视图出现。
  const cast = useMemo(() => (hubList ? new Set(hubList.characters.map((c) => c.cid)) : null), [hubList]);
  const [quar, setQuar] = useState<Set<string> | null>(null);
  useEffect(() => void loadQuarantine().then(setQuar), []);
  const cards = useMemo(
    () =>
      (data?.cards ?? []).filter((c) => {
        if (isQuarantined(quar, c.id, c.name)) return false; // 隔离区里的（旧场景、证伪的 LoRA…）不列
        if (!cast) return c.type !== "character" && !c.owner; // 演员表还没读到：先不显示人物相关卡片，免得闪出旧演员
        if (c.type === "character") return cast.has(c.id);
        if (c.owner && ["look", "item", "prop", "voice", "lora"].includes(c.type)) return cast.has(c.owner.id);
        return true;
      }),
    [data, cast, quar],
  );
  const ql = q.trim().toLowerCase();
  const filtered = useMemo(
    () => cards.filter((c) => (!ql || c.search.toLowerCase().includes(ql)) && (!status || c.status === status) && inScope(c) && (status === "void" || c.status !== "void")),
    [cards, ql, status, scope, ep],
  );
  const hiddenOld = useMemo(() => cards.filter((c) => c.eps && !c.eps.length && USAGE_TYPES.has(c.type)).length, [cards]);
  const node = TREE.find((t) => t.id === (route.type === "overview" ? "all" : route.type)) ?? TREE[0];
  const inNode = (c: AssetCardData, types = node.types) => !types.length || types.includes(c.type);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of TREE) m.set(t.id, filtered.filter((c) => inNode(c, t.types)).length);
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered]);
  const statusCounts = useMemo(() => {
    const m = new Map<AssetStatus, number>();
    const base = cards.filter((c) => inNode(c) && (!ql || c.search.toLowerCase().includes(ql)) && inScope(c));
    for (const c of base) m.set(c.status, (m.get(c.status) ?? 0) + 1);
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, ql, scope, ep, node.id]);

  const go = (type: string, char: string | null = null) => {
    setInsp(null);
    writeRoute({ type, char });
  };
  const openCard = (c: AssetCardData) => (c.type === "character" ? go("character", c.id) : setInsp(c));
  const openEditor = (c: AssetCardData) => {
    const base = { shot: "", fromTake: null, context: "assets" as const, img: c.thumb ?? null };
    if (c.type === "look") setEdit({ ...base, asset: c.id, character: c.owner!.id, label: `${c.owner!.name} · ${c.name}`, kind: "look" });
    else if (c.type === "item" || c.type === "prop") {
      const w = (c.raw as { w: { slot: string } }).w;
      setEdit({ ...base, asset: c.id, character: c.owner!.id, label: `${c.owner!.name} · ${c.name}`, kind: w.slot as DrawerTarget["kind"] });
    } else if (c.type === "scene") setEdit({ ...base, asset: c.id, character: "", label: c.name, kind: "scene" });
  };
  const editable = (c: AssetCardData) => ["look", "item", "prop", "scene"].includes(c.type);
  const stubShot = { id: "", index: 0, adult: false, first_frame: null, characters: [] } as unknown as ShotSummary;
  const charCard = route.char ? cards.find((c) => c.type === "character" && c.id === route.char) : null;
  const fromShot = route.from;

  return (
    <div className="ac-page">
      <nav className="ac-nav" aria-label="资产分类">
        <div className="ac-nav-h">
          <span className="ac-step">②</span>
          <b>资产中心</b>
        </div>
        <div className="ac-nav-g">人物 · 当前剧</div>
        {hubErr && !hubList ? (
          <p className="ds-small ds-muted ac-nav-note">人物列表暂时读不到，后台恢复后自动出现</p>
        ) : (
          <PeopleNav list={hubList} cur={hubCid} onPick={(cid) => go("people-hub", cid)} />
        )}
        <div className="ac-nav-g">其他资产</div>
        {TREE.filter((t) => OTHER_NODES.has(t.id)).map((t) => (
          <div key={t.id}>
            <button className={`ac-nav-i${t.indent ? " in" : ""}${!peopleMode && node.id === t.id ? " on" : ""}`} onClick={() => go(t.id)}>
              <span>{t.label}</span>
              {t.types.length > 0 && <small>{data ? counts.get(t.id) ?? 0 : ""}</small>}
            </button>
          </div>
        ))}
        <div className="ac-nav-foot">
          <button className={`ac-nav-i${route.type === "overview" ? " on" : ""}`} onClick={() => go("overview")} title="所有类别的资产卡片（含造型 / 衣橱的旧卡片视图）">
            <span>全部资产（卡片总览）</span>
          </button>
          <button className={`ac-nav-i${route.type === "people" ? " on" : ""}`} onClick={() => go("people")} title="新建人物、改名 / 归档、按目标上传参考照片">
            <span>人物登记（新建 · 改名 · 归档）</span>
          </button>
        </div>
      </nav>

      <main className="ac-main">
        {!peopleMode && (
        <header className="ac-head">
          <div className="ac-crumbs">
            {fromShot && (
              <a className="ac-back" href={`#${fromShot}`} title="回到画布里的这一镜">
                ← 回到 {fromShot}
              </a>
            )}
            <h1>
              {route.char ? (
                <>
                  <button className="ac-crumb" onClick={() => go("character")}>
                    角色
                  </button>
                  <span className="ac-sep">/</span>
                  {charCard?.name ?? route.char}
                </>
              ) : (
                route.type === "sheets" ? "挑设定图" : route.type === "people" ? "新建人物 · 上传参考" : node.id === "all" ? "全部资产" : node.label
              )}
            </h1>
          </div>
          {!route.char && route.type !== "people" && route.type !== "sheets" && !["loras", "template"].includes(node.id) && (
            <div className="ac-tools">
              <input className="ds-input ac-search" placeholder="搜名字、角色、槽位…" value={q} onChange={(e) => (setQ(e.target.value), writeRoute({ q: e.target.value }, false))} aria-label="搜资产" />
              <Seg
                value={scope}
                onChange={setScope}
                label="范围"
                options={[
                  ["cur", "当前剧本"],
                  ["ep", `第 ${ep} 集用到的`],
                  ["all", hiddenOld ? `全部（含当前剧没用到的 ${hiddenOld}）` : "全部"],
                ]}
              />
              <div className="ac-stats" role="group" aria-label="按状态筛选">
                {STATUS_ORDER.filter((s) => statusCounts.get(s) || status === s).map((s) => (
                  <button key={s} className={`ac-stat st-${s}${status === s ? " on" : ""}`} onClick={() => setStatus(status === s ? null : s)} title={ASSET_STATUS[s].tip}>
                    <i />
                    {ASSET_STATUS[s].label} <b>{statusCounts.get(s) ?? 0}</b>
                  </button>
                ))}
                {status && (
                  <button className="ac-stat clear" onClick={() => setStatus(null)}>
                    清除
                  </button>
                )}
              </div>
            </div>
          )}
        </header>
        )}

        {data?.presetsPending && ["all", "style", "preset"].includes(node.id) && !route.char && <Loading text="出图预设还在读（接口要探测显卡，约 20 秒），其余已显示" />}
        {loadErr && <LoadError what="资产" err={loadErr} retry={reload} />}
        {data && Object.keys(data.errors).length > 0 && (
          <div className="ac-errs">
            {data.errors.chars && <LoadError what="角色 / 形象 / 衣橱" err={data.errors.chars} retry={reload} />}
            {data.errors.scenes && <LoadError what="场景" err={data.errors.scenes} retry={reload} />}
            {(data.errors.presets || data.errors.video) && <LoadError what="风格（预设 / 出片方式）" err={data.errors.presets ?? data.errors.video} retry={reload} />}
            {data.errors.revisions && (node.id === "all" || ["style", "lora", "voice"].includes(node.id)) && (
              <LoadError what="版本账本（身份 LoRA、音色、依赖已更新）" err={data.errors.revisions} hint="其余资产照常显示。" />
            )}
          </div>
        )}

        {peopleMode ? (
          <>
            {fromShot && (
              <a className="ac-back" href={`#${fromShot}`} title="回到画布里的这一镜">
                ← 回到 {fromShot}
              </a>
            )}
            {hubCid ? (
              <PeopleHub key={hubCid} cid={hubCid} onListChanged={() => setHubTick((n) => n + 1)} />
            ) : hubErr ? (
              <LoadError what="人物资产页" err={hubErr} retry={() => setHubTick((n) => n + 1)} hint="后台恢复后这里显示人物的身份脸、造型和单品；已登记的资产不会丢。" />
            ) : hubList ? (
              <Empty icon="◎" title="当前剧还没有人物" sub="剧本写到人物表（P1）后，人物会出现在这里。" />
            ) : (
              <Skel h={360} r="var(--r-l)" />
            )}
          </>
        ) : route.type === "people" && !route.char ? (
          <Suspense fallback={<Skel h={320} />}>
            <PeoplePage />
          </Suspense>
        ) : (
          <>
            {(node.id === "all" || node.id === "character") && data?.eps && <EpisodeLookStrip data={data} ep={ep} onOpen={(id) => go("character", id)} />}
            {/* UIAUDIT r12 P1（提示词模板页首屏 31 秒）：模板 / LoRA 总表有自己的接口，不等资产总索引（/api/assets/characters 等可能要十几秒） */}
            {!data && !loadErr && !["template", "loras"].includes(node.id) && <GridSkel />}
            {!data && node.id === "template" && <TemplatesPanel />}
            {!data && node.id === "loras" && <LoraTablePanel />}
            {data && node.id === "all" && (
              <Overview
                filtered={filtered}
                onMore={(id) => go(id)}
                onOpen={openCard}
                onUsage={(c) => setInsp(c)}
                selected={insp?.uid}
              />
            )}
            {data && node.id === "scene" && (
              <div className="ac-scene-sw">
                <Seg
                  value={sceneMode}
                  onChange={setSceneMode}
                  label="场景视图"
                  options={[
                    ["cards", "资产卡片"],
                    ["bench", "底图工作台（上传 · 批量生成候选）"],
                  ]}
                />
              </div>
            )}
            {data && node.id === "scene" && sceneMode === "bench" ? (
              <Suspense fallback={<Skel h={320} />}>
                <ScenesTab onOpen={(sc, label) => setEdit({ shot: "", asset: sc.scene_id, character: "", label, kind: "scene", fromTake: null, context: "assets", img: sc.plate?.url ?? null })} />
              </Suspense>
            ) : (
              data &&
              node.id !== "all" &&
              (node.id === "template" ? (
                <TemplatesPanel />
              ) : node.id === "loras" ? (
                <LoraTablePanel />
              ) : (
                <>
                {node.id === "prop" && <PropsPanel />}
                {node.id === "voice" && <VoiceStudio />}
                {node.id !== "voice" && <Grid list={filtered.filter((c) => inNode(c))} showType={node.types.length > 1} onOpen={openCard} onUsage={(c) => setInsp(c)} selected={insp?.uid} emptyHint={node.id === "voice" || node.id === "lora" ? (data.revNotReady ? "音色和身份 LoRA 来自版本账本接口，API 重启后出现。" : undefined) : undefined} />}
                </>
              ))
            )}
          </>
        )}
      </main>

      {insp && (
        <AssetInspector
          c={insp}
          eps={data?.eps ?? null}
          onClose={() => setInsp(null)}
          onEdit={editable(insp) ? () => openEditor(insp) : undefined}
          onOpenChar={(id) => go("character", id)}
          onImpact={(s) => setImpact(s)}
          onChanged={reload}
        />
      )}
      {impact && <ImpactDrawer src={impact} onClose={() => setImpact(null)} />}
      {edit && (
        <AssetDrawer
          shot={stubShot}
          open={edit}
          onClose={() => {
            setEdit(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function GridSkel() {
  return (
    <div className="ac-grid">
      {Array.from({ length: 12 }, (_, i) => (
        <Skel key={i} h={220} r="var(--r-l)" />
      ))}
    </div>
  );
}

function Grid({ list, showType, onOpen, onUsage, selected, emptyHint }: { list: AssetCardData[]; showType?: boolean; onOpen: (c: AssetCardData) => void; onUsage: (c: AssetCardData) => void; selected?: string; emptyHint?: string }) {
  if (!list.length) return <Empty icon="○" title="没有符合的资产" sub={emptyHint ?? "换个搜索词，或者清除状态筛选 / 改成“全部”。"} />;
  return (
    <div className="ac-grid">
      {list.map((c) => (
        <AssetCard key={c.uid} c={c} showType={showType} on={selected === c.uid} onOpen={() => onOpen(c)} onUsage={c.usage ? () => onUsage(c) : undefined} />
      ))}
    </div>
  );
}

const OVERVIEW: { id: string; limit: number }[] = [
  { id: "character", limit: 8 },
  { id: "scene", limit: 8 },
  { id: "look", limit: 8 },
  { id: "item", limit: 8 },
  { id: "prop", limit: 8 },
  { id: "style", limit: 8 },
  { id: "voice", limit: 8 },
];

function Overview({ filtered, onMore, onOpen, onUsage, selected }: { filtered: AssetCardData[]; onMore: (id: string) => void; onOpen: (c: AssetCardData) => void; onUsage: (c: AssetCardData) => void; selected?: string }) {
  const any = OVERVIEW.some(({ id }) => filtered.some((c) => TREE.find((t) => t.id === id)!.types.includes(c.type)));
  if (!any) return <Empty icon="○" title="没有符合的资产" sub="换个搜索词，或者清除状态筛选 / 改成“全部”。" />;
  return (
    <>
      {OVERVIEW.map(({ id, limit }) => {
        const t = TREE.find((x) => x.id === id)!;
        const list = filtered.filter((c) => t.types.includes(c.type));
        if (!list.length) return null;
        // 优先显示要处理的：依赖已更新 → 草稿 → 候选 → 定稿
        const rank: Record<AssetStatus, number> = { dep: 0, draft: 2, candidate: 1, final: 3, void: 4 };
        const shown = id === "character" ? list.slice(0, limit) : [...list].sort((a, b) => rank[a.status] - rank[b.status] || (b.usage?.shots ?? 0) - (a.usage?.shots ?? 0)).slice(0, limit);
        return (
          <section key={id} className="ac-sec">
            <header>
              <h2>{t.label}</h2>
              <span className="ds-muted ds-small">{list.length} 个</span>
              <span className="ds-grow" />
              {list.length > shown.length && (
                <Button size="sm" variant="ghost" onClick={() => onMore(id)}>
                  全部 {list.length} ›
                </Button>
              )}
            </header>
            <Grid list={shown} showType={t.types.length > 1} onOpen={onOpen} onUsage={onUsage} selected={selected} />
          </section>
        );
      })}
    </>
  );
}

/** D8：本集造型确认条——本集出场的每个角色一张小卡：用哪套形象、确认了没有、没确认就地点“确认”（同一个项目方确认框） */
function EpisodeLookStrip({ data, ep, onOpen }: { data: CenterData; ep: number; onOpen: (id: string) => void }) {
  const { sop } = useSop();
  const epData = data.eps?.find((e) => e.number === ep);
  if (!epData) return null;
  const m = new Map<string, { name: string; face: string | null; looks: Map<string, string>; shots: number }>();
  for (const s of epData.shots)
    for (const c of s.characters ?? []) {
      const r = m.get(c.character) ?? { name: c.name, face: c.face_url, looks: new Map(), shots: 0 };
      r.shots++;
      const lk = shotLookKey(c as ShotCharLike); // DATAALIGN：和出图同源（series10 = A/B/C）
      if (lk) r.looks.set(lk, c.look_label || c.look_name);
      m.set(c.character, r);
    }
  if (!m.size) return null;
  const pending = sop ? (sop.owner_actions ?? []).filter((a) => a.gate === "look").length : null;
  return (
    <section className="ac-epstrip" aria-label={`第 ${ep} 集造型确认`}>
      <header>
        <b>第 {ep} 集造型确认</b>
        <span className="ds-muted ds-small">{pending == null ? "读取确认状态…" : pending ? `${pending} 个角色待项目方确认` : "全部已确认"}</span>
      </header>
      <div className="ac-epstrip-row">
        {[...m.entries()].map(([id, r]) => (
          <div key={id} className="ac-epchar">
            <button className="ac-epchar-face" onClick={() => onOpen(id)} title={`打开 ${r.name} 的角色详情`}>
              {r.face ? <img src={r.face} alt="" /> : <span>{r.name.slice(0, 1)}</span>}
            </button>
            <div className="ac-epchar-t">
              <b>{r.name}</b>
              <span className="ds-muted ds-small">
                {[...r.looks.values()].map((l) => `形象 ${l}`).join(" / ") || "未指定形象"} · {r.shots} 镜
              </span>
              <LookConfirm charId={id} ep={ep} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

