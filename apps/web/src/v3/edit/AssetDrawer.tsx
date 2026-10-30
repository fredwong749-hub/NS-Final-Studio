// fredw-92/W4b：资产编辑抽屉（spec §7.3）——参考图组（人物 / 风格 / 色彩 / 单件）、上传、从本镜某版「设为参考」、
// image2img 生成（出图卡）、结果存为：只这一镜 / 资产新版本 / 本集默认（项目方本人）。
// fredw-92/U3（v3.1 §3）：参考图组 = 每个用途一格缩略图网格，空格可拖图；先选图（上传 / 拖放 / 从版本或其他资产）再选用途；
// 底图选项带预览；生成结果直接进抽屉里的修改链（按 parent 连起来），选中一版与上一版并排对比，满意再保存。
// 提示词由项目方或写作方写，原样发送，不预填；不做内容检测。
import { useEffect, useRef, useState, type DragEvent } from "react";
import type { ShotSummary } from "../../types";
import { useStudio } from "../../store";
import {
  apiV1, errText, isNotReady, ROLE_LABEL, STRENGTH_LABEL, slotToStage,
  type AssetRef, type CharacterAssetsV1, type RefRole, type Strength,
} from "../api_v1";
import { currentTake, etaFor, fmtSec, setEdit, takeUrl, trackJob, useEdit, type DrawerOpen } from "./state";
import { SLOT_NAME } from "./actions";
import { bumpShotRefs } from "./RefBar";
import { loadScene, lockPlate, plateUrl, sceneName, sceneNotReady, unlockPlate, variantLabel, type SceneDetail, type SceneVersion } from "../pages/scenes_api";
import "./AssetDrawer.css";

type Save = "shot" | "version" | "episode";
type Base = "none" | "asset" | "take" | "gen";
/** 后端 asset_gens 记录（GET /api/assets/characters/{cid} 的 assets[].gens） */
interface Gen {
  gen_id: string;
  job_id?: string | null;
  file?: string | null;
  url?: string | null;
  parent?: string | null;
  prompt?: string;
  seed?: number;
  strength?: string | number;
  gpu?: number;
  created_at?: string;
}
/** 选中、还没定用途的图 */
type Pending =
  | { src: "file"; file: File; url: string; name: string }
  | { src: "take"; url: string | null; name: string }
  | { src: "copy"; from: string; ref: AssetRef; url: string | null; name: string }
  | { src: "url"; url: string; name: string };

const ROLES = Object.keys(ROLE_LABEL) as RefRole[];
const GPU_LABEL: Record<0 | 3, string> = { 0: "出图卡 GPU0", 3: "视频卡 GPU3" };
const SRC_MIME = "application/x-ns-src";
const REF_MIME = "application/x-ns-ref";

/** 场景资产的参考用途：后端仍用同一组 role id，只换叫法（空间 / 风格 / 色彩 / 道具） */
const SCENE_ROLE_LABEL: Record<RefRole, string> = { identity: "空间", style: "风格", color: "色彩", item: "道具" };
/** 场景：前端沿用 identity/item 两个格子，发给后端时换成 space/prop（后端也收中文） */
const SCENE_WIRE: Partial<Record<RefRole, string>> = { identity: "space", item: "prop" };
const SCENE_FROM_WIRE: Record<string, RefRole> = { space: "identity", prop: "item", 空间: "identity", 道具: "item", 风格: "style", 色彩: "color" };
/** DrawerOpen 加上场景资产（kind = "scene"，asset = scene_id，character 留空） */
export type DrawerTarget = Omit<DrawerOpen, "kind"> & { kind: DrawerOpen["kind"] | "scene" };
type AssetData = { id: string; name?: string; url?: string | null; refs?: AssetRef[]; versions?: import("../api_v1").AssetVersion[]; gens?: Gen[] };
/** /api/assets/file?path=… → 相对项目根的路径（底图要发路径） */
const pathOf = (url: string | null | undefined) => {
  if (!url) return null;
  try {
    return new URL(url, location.origin).searchParams.get("path");
  } catch {
    return null;
  }
};

export interface AssetDrawerProps {
  shot: ShotSummary;
  /** 不传 = 用共享状态 es.drawer（资产页 / 精修 ⋯ 菜单） */
  open?: DrawerTarget;
  onClose?: () => void;
  /** true = 放在外壳的浮层里（参考切换面板「编辑这个资产」），不画自己的遮罩 */
  embedded?: boolean;
}

/** 修改链：按 parent 排成树（深度优先，同层按时间） */
function chainOrder(list: Gen[]): { g: Gen; depth: number }[] {
  const ids = new Set(list.map((g) => g.gen_id));
  const kids = new Map<string | null, Gen[]>();
  for (const g of list) {
    const p = g.parent && ids.has(g.parent) ? g.parent : null;
    kids.set(p, [...(kids.get(p) ?? []), g]);
  }
  const out: { g: Gen; depth: number }[] = [];
  const walk = (p: string | null, depth: number) => {
    for (const g of kids.get(p) ?? []) {
      out.push({ g, depth });
      walk(g.gen_id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}
const hhmm = (s?: string) => s?.replace("T", " ").slice(5, 16) ?? "";

export function AssetDrawer({ shot, open, onClose, embedded }: AssetDrawerProps) {
  const studio = useStudio();
  const es = useEdit();
  const dr: DrawerTarget = (open ?? es.drawer)!;
  const isScene = dr.kind === "scene";
  const RL = isScene ? SCENE_ROLE_LABEL : ROLE_LABEL;
  const close = onClose ?? (() => setEdit(() => ({ drawer: null })));
  const [ca, setCa] = useState<{ data: CharacterAssetsV1 | null; notReady: boolean; err: string | null }>({ data: null, notReady: false, err: null });
  const [sc, setSc] = useState<{ data: SceneDetail | null; notReady: boolean; err: string | null }>({ data: null, notReady: false, err: null });
  const [variant, setVariant] = useState("main");
  const [reload, setReload] = useState(0);
  const [extraRefs, setExtraRefs] = useState<AssetRef[]>([]);
  const [roles, setRoles] = useState<Record<string, RefRole>>({});
  const [off, setOff] = useState<Record<string, boolean>>({});
  /** 已去掉的参考（DELETE 成功后本地隐藏） */
  const [gone, setGone] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState<Pending | null>(null);
  const [pendRole, setPendRole] = useState<RefRole>("style");
  const [picker, setPicker] = useState(false);
  const [dropOn, setDropOn] = useState<RefRole | "any" | null>(null);
  const [base, setBase] = useState<Base>("asset");
  const [baseGen, setBaseGen] = useState<Gen | null>(null);
  const [prompt, setPrompt] = useState("");
  const [strength, setStrength] = useState<Strength>("medium");
  const [gpu, setGpu] = useState<0 | 3>(0);
  const [lastJob, setLastJob] = useState<string | null>(null);
  const [selGen, setSelGen] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [save, setSave] = useState<Save>("version");
  const [label, setLabel] = useState("");
  const [owner, setOwner] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const d = studio.details[shot.id];
  const fromSlot = dr.fromTake?.slot ?? "first";
  const take = dr.fromTake ? currentTake(es, d, shot.id, fromSlot) : currentTake(es, d, shot.id, "first");
  const takeImg = takeUrl(take);

  useEffect(() => {
    if (!isScene) return;
    let dead = false;
    loadScene(dr.asset).then(
      (data) => !dead && setSc({ data, notReady: false, err: null }),
      (e) => !dead && setSc({ data: null, notReady: sceneNotReady(e), err: String((e as Error)?.message ?? e) }),
    );
    return () => {
      dead = true;
    };
  }, [isScene, dr.asset, reload]);
  useEffect(() => {
    if (isScene || !dr.character) return setCa({ data: null, notReady: false, err: null });
    let dead = false;
    apiV1.characterAssets(dr.character).then(
      (data) => !dead && setCa({ data, notReady: false, err: null }),
      (e) => !dead && setCa({ data: null, notReady: isNotReady(e), err: errText(e) }),
    );
    return () => {
      dead = true;
    };
  }, [dr.character, reload]);
  // 资产自己没有图、也没有角色主图可用：默认改成“不选底图”
  useEffect(() => {
    if ((ca.data || sc.data || sc.err) && base === "asset" && !baseImg) setBase("none");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ca.data, sc.data, sc.err]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (full) return setFull(false);
      close();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });
  useEffect(() => () => {
    if (pending?.src === "file") URL.revokeObjectURL(pending.url);
  }, [pending]);

  const asset: AssetData | null = isScene
    ? sc.data
      ? {
          id: dr.asset,
          name: sceneName(sc.data),
          url: plateUrl(sc.data) ?? sc.data.assets?.[0]?.url ?? null,
          refs: (sc.data.assets?.[0]?.refs ?? sc.data.refs_list ?? []).map((r) => ({ ...r, role: SCENE_FROM_WIRE[r.role as string] ?? r.role })),
          versions: sc.data.assets?.[0]?.versions ?? sc.data.version_list,
          gens: (sc.data.assets?.[0]?.gens ?? sc.data.gens) as Gen[] | undefined,
        }
      : null
    : ca.data?.assets?.find((a) => a.id === dr.asset) ?? null;
  const assetsV1Ready = isScene ? !!sc.data : !!ca.data && Array.isArray(ca.data.assets);
  const refs = [...(asset?.refs ?? []), ...extraRefs.filter((x) => !(asset?.refs ?? []).some((y) => y.ref_id === x.ref_id))].filter((r) => !gone[r.ref_id]);
  const roleOf = (r: AssetRef): RefRole => roles[r.ref_id] ?? r.role ?? "style";
  /** 发给后端的用途 id（场景：空间 / 道具 用 space / prop） */
  const wire = (k: RefRole) => (isScene ? SCENE_WIRE[k] ?? k : k) as RefRole;
  const used = refs.filter((r) => !off[r.ref_id]);
  /** 生成时的顺序：底图第一，其余按用途 人物 → 单件 → 风格 → 色彩（与后端 plan_gen 一致） */
  const ORDER: RefRole[] = ["identity", "item", "style", "color"];
  const ordered = [...used].sort((a, b) => ORDER.indexOf(roleOf(a)) - ORDER.indexOf(roleOf(b)));
  const look = isScene ? undefined : ca.data?.looks?.find((l) => l.id === dr.asset);
  /** 资产自己的当前图（后端 base="current" 无图会 409） */
  const assetImg = asset?.url ?? look?.preview_url ?? asset?.versions?.at(-1)?.url ?? null;
  /** 角色主图（资产页形象卡没图时显示的那张）：资产自己没图时，底图就用它（发路径） */
  const hero = isScene ? null : ((ca.data as { hero?: { url?: string | null; file?: string | null } | null } | null)?.hero ?? null);
  const mainUrl = isScene ? null : hero?.url ?? ca.data?.face_url ?? null;
  const mainFile = isScene ? null : hero?.file ?? pathOf(mainUrl);
  const baseImg = assetImg ?? (mainFile ? mainUrl : null);
  const heroUrl = assetImg ?? mainUrl;
  const gens: Gen[] = (asset?.gens ?? []).filter((g) => g.gen_id);
  const gen = gens.find((g) => g.gen_id === selGen) ?? null;
  const genParent = gen?.parent ? gens.find((g) => g.gen_id === gen.parent) ?? null : null;
  const eta = etaFor("asset", gpu);
  const lastJobState = es.jobs.find((j) => j.id === lastJob);
  const liveJob = lastJobState && (lastJobState.state === "queued" || lastJobState.state === "running") && !lastJobState.notReady ? lastJobState : null;
  const nBase = base === "none" ? 0 : 1;
  const imgNo = (r: AssetRef) => ordered.indexOf(r) + 1 + nBase;

  /** 可选的图源：本资产的生成 / 版本、同一人物其他资产的参考图与主图 */
  const sources: { key: string; p: Pending; group: string }[] = [];
  for (const g of [...gens].reverse()) if (g.url) sources.push({ key: `g:${g.gen_id}`, group: "这个资产的生成", p: { src: "url", url: g.url, name: `生成 ${hhmm(g.created_at)}` } });
  for (const v of asset?.versions ?? []) if (v.url) sources.push({ key: `v:${v.id ?? v.n}`, group: "这个资产的版本", p: { src: "url", url: v.url, name: v.label ?? `v${v.n ?? ""}` } });
  for (const a of isScene ? [] : ca.data?.assets ?? []) {
    if (a.id === dr.asset) continue;
    for (const r of a.refs ?? []) sources.push({ key: `r:${a.id}:${r.ref_id}`, group: "其他资产", p: { src: "copy", from: a.id, ref: r, url: r.url ?? null, name: a.name ?? a.id } });
    if (a.url) sources.push({ key: `a:${a.id}`, group: "其他资产", p: { src: "url", url: a.url, name: a.name ?? a.id } });
  }

  function choose(p: Pending, role?: RefRole) {
    setPending(p);
    setPendRole(role ?? (p.src === "take" ? "identity" : "style"));
    setPicker(false);
  }
  async function commit() {
    if (!pending) return;
    const role = pendRole;
    setBusy(true);
    try {
      let r: AssetRef;
      if (pending.src === "file") r = await apiV1.uploadAssetRef(dr.asset, pending.file, wire(role));
      else if (pending.src === "take") {
        if (!take) return;
        r = await apiV1.assetRefFromTake(dr.asset, { shot: shot.id, stage: slotToStage(fromSlot), n: take.n, role: wire(role) });
        r = { ...r, url: r.url ?? takeImg };
      } else if (pending.src === "copy") {
        r = await apiV1.assetRefCopy(dr.asset, { from_asset: pending.from, ref_id: pending.ref.ref_id, role: wire(role) });
        r = { ...r, url: r.url ?? pending.ref.url };
      } else {
        const blob = await (await fetch(pending.url)).blob();
        const ext = (blob.type.split("/")[1] || "png").replace("jpeg", "jpg");
        r = await apiV1.uploadAssetRef(dr.asset, new File([blob], `ref.${ext}`, { type: blob.type || "image/png" }), wire(role));
      }
      setExtraRefs((l) => [...l, { ...r, role: (isScene ? SCENE_FROM_WIRE[r.role as string] : undefined) ?? r.role ?? role }]);
      setPending(null);
      studio.notify(`已加入参考：取${RL[role]}`);
    } catch (e) {
      studio.notify(`加参考：${errText(e, "W5 /assets/{id}/refs")}`, "err");
    } finally {
      setBusy(false);
    }
  }
  async function dropRef(r: AssetRef) {
    try {
      await apiV1.assetRefDelete(dr.asset, r.ref_id);
      setGone((m) => ({ ...m, [r.ref_id]: true }));
      studio.notify("已去掉这张参考");
    } catch (e) {
      studio.notify(`去掉参考：${errText(e, "W5 DELETE /refs")}`, "err");
    }
  }

  // ---------- 拖放：文件 / 图源条里的图 / 已挂的参考（换用途） / 网页里的图片 ----------
  const dragOver = (e: DragEvent, k: RefRole | "any") => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    if (dropOn !== k) setDropOn(k);
  };
  function onDrop(e: DragEvent, role?: RefRole) {
    e.preventDefault();
    setDropOn(null);
    const dt = e.dataTransfer;
    const refId = dt.getData(REF_MIME);
    if (refId) {
      if (role) setRoles((m) => ({ ...m, [refId]: role }));
      return;
    }
    const f = [...dt.files].find((x) => x.type.startsWith("image/"));
    if (f) return choose({ src: "file", file: f, url: URL.createObjectURL(f), name: f.name }, role);
    const key = dt.getData(SRC_MIME);
    if (key === "take" && take) return choose({ src: "take", url: takeImg, name: `本镜${SLOT_NAME[fromSlot]} #${take.n}` }, role);
    const s = sources.find((x) => x.key === key);
    if (s) return choose(s.p, role);
    const uri = dt.getData("text/uri-list") || dt.getData("text/plain");
    if (uri && /^(https?:|\/)/.test(uri.trim())) return choose({ src: "url", url: uri.trim().split("\n")[0], name: "拖进来的图" }, role);
    studio.notify("只能拖图片进来", "err");
  }

  async function gen_() {
    setBusy(true);
    try {
      const b: Parameters<typeof apiV1.assetGenJob>[1] & { parent?: string } = { refs: used.map((r) => ({ ref_id: r.ref_id, role: wire(roleOf(r)) })), prompt, strength, gpu };
      if (base === "asset" && assetImg) b.base = "current"; // 后端只认 "current" | ref_id | 路径
      else if (base === "asset" && mainFile) b.base = mainFile; // 资产自己没图：用角色主图
      if (base === "take" && take) b.base = take.file;
      if (base === "gen" && baseGen?.file) {
        b.base = baseGen.file;
        b.parent = baseGen.gen_id; // 修改链：从这一版继续改
      }
      const { job_id } = await apiV1.assetGenJob(dr.asset, b);
      setLastJob(job_id);
      trackJob({
        id: job_id,
        shot: shot.id,
        slot: "asset",
        label: `资产生成 · ${dr.label}`,
        gpu,
        eta_s: eta.eta,
        onDone: (j) => {
          studio.notify(j.state === "done" ? `${dr.label} 生成完成，结果在修改链里` : `${dr.label} 生成失败：${j.error ?? ""}`, j.state === "done" ? "ok" : "err");
          if (j.state === "done") setReload((n) => n + 1);
        },
      });
      studio.notify(`已排队：${dr.label} 生成（${GPU_LABEL[gpu]}）`);
    } catch (e) {
      studio.notify(`生成：${errText(e, "W5 /assets/{id}/gen-jobs")}`, "err");
    } finally {
      setBusy(false);
    }
  }
  // 生成完成、列表刷新后自动选中这次的结果
  useEffect(() => {
    if (!lastJob) return;
    const g = gens.find((x) => x.job_id === lastJob);
    if (g && selGen !== g.gen_id) setSelGen(g.gen_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ca.data, lastJob]);

  async function lock(version: number, vv: string) {
    setBusy(true);
    try {
      const r = await lockPlate(dr.asset, version, vv === "main" ? undefined : vv);
      const n = r.stale_shots?.length ?? 0;
      studio.notify(`已定稿为${variantLabel(vv)}${n ? `；${n} 镜首帧会标为过期，需要重出` : ""}`);
      setReload((x) => x + 1);
    } catch (e) {
      studio.notify(`定稿底图：${sceneNotReady(e) ? "后端未就绪（/api/assets/scenes/{id}/plate）" : (e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  }
  async function unlock(vv: string) {
    setBusy(true);
    try {
      await unlockPlate(dr.asset, vv);
      studio.notify(`已取消${variantLabel(vv)}定稿`);
      setReload((x) => x + 1);
    } catch (e) {
      studio.notify(`取消定稿：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  }
  const saveFrom = gen ? { gen_id: gen.gen_id } : lastJobState?.state === "done" && lastJob ? { job_id: lastJob } : null;
  async function doSave() {
    if (!saveFrom) return;
    if (save === "episode" && !owner) return studio.notify("设为本集默认需要项目方本人勾选确认", "err");
    setBusy(true);
    try {
      const v = await apiV1.assetVersion(dr.asset, { ...saveFrom, label: label || dr.label, ...(isScene ? { variant } : {}) } as { job_id?: string; label: string });
      if (isScene) {
        // 场景 = 底图版本链：存完留在抽屉里，在“底图版本”里定稿
        studio.notify(`已存为底图版本 v${(v as SceneVersion).version ?? ""}（${variantLabel(variant)}）；需要时点“定稿为底图”`);
        setReload((n) => n + 1);
        return;
      }
      const newId = v.asset_id ?? v.id ?? dr.asset;
      if (save !== "version" && dr.character) {
        const ch = dr.kind === "look" ? { look: newId } : { parts: { [dr.kind]: newId } };
        await apiV1.refsApply(shot.id, save === "shot" ? "shot" : "episode", { characters: { [dr.character]: ch } }, false, save === "episode" ? "owner" : undefined);
      }
      bumpShotRefs();
      studio.notify(save === "shot" ? "已存为只这一镜用" : save === "episode" ? "已设为本集默认（造型确认需重做）" : "已存为资产新版本");
      await studio.refreshAfter([shot.id]);
      close();
    } catch (e) {
      studio.notify(`保存：${errText(e, "W5 /assets/{id}/versions")}`, "err");
    } finally {
      setBusy(false);
    }
  }

  const baseOpts: { k: Base; t: string; url: string | null; ok: boolean }[] = [
    assetImg
      ? { k: "asset", t: isScene ? "当前底图" : "当前资产图", url: assetImg, ok: true }
      : { k: "asset", t: isScene ? "当前底图（还没有）" : mainFile ? "角色主图" : "当前资产图（还没有）", url: mainFile ? mainUrl : null, ok: !!mainFile },
    { k: "take", t: `本镜${SLOT_NAME[fromSlot]}${take ? ` #${take.n}` : ""}`, url: takeImg, ok: !!take },
    ...(baseGen ? [{ k: "gen" as Base, t: "选中的生成版", url: baseGen.url ?? null, ok: !!baseGen.file }] : []),
    { k: "none", t: "不选底图（只用参考图）", url: null, ok: true },
  ];
  const cmpLeft = genParent?.url ?? null;
  const cmpLeftLabel = genParent ? `上一版 · ${hhmm(genParent.created_at)}` : "这是链的起点";

  const body = (
    <aside className={`v3e-drawer v3a${embedded ? " embed" : ""}`} role="dialog" aria-label="编辑资产">
      <header>
        {heroUrl ? <img className="v3e-dthumb" src={heroUrl} alt="" /> : <span className="v3e-dthumb e" />}
        <div>
          <h3>编辑资产 · {dr.label}</h3>
          <div className="sub">① 选图并定用途 → ② 选底图、写提示词 → ③ 出图卡生成，结果进修改链 → ④ 满意再保存</div>
        </div>
        <button className="v3e-x" onClick={close} aria-label={embedded ? "返回" : "关闭"}>
          {embedded ? "←" : "×"}
        </button>
      </header>
      <div className="v3e-dbody">
        {isScene && sc.notReady && <div className="v3e-note warn">场景资产接口后端未就绪（/api/assets/scenes/{"{id}"}）。上传、生成、保存会提示失败。</div>}
        {isScene && sc.err && !sc.notReady && <div className="v3e-note warn">{sc.err}</div>}
        {!isScene && (ca.notReady || (ca.data && !assetsV1Ready)) && (
          <div className="v3e-note warn">资产参考图 / 版本接口后端还没接好。上传、设为参考、生成会提示失败。</div>
        )}
        {ca.err && !ca.notReady && <div className="v3e-note warn">{ca.err}</div>}

        <section>
          <h4>
            ① 参考图<span>点图 = 用 / 不用；拖到别的组 = 换用途</span>
          </h4>
          <div className="v3a-pick" onDragOver={(e) => dragOver(e, "any")} onDragLeave={() => setDropOn(null)} onDrop={(e) => onDrop(e)}>
            {pending ? (
              <div className="v3a-pend">
                <div className="v3a-pend-img">{pending.url ? <img src={pending.url} alt="" /> : <span className="e">无图</span>}</div>
                <div className="v3a-pend-body">
                  <div className="v3a-pend-name" title={pending.name}>
                    已选：{pending.name}
                  </div>
                  <div className="v3a-q">这张图用来：</div>
                  <div className="v3a-roles">
                    {ROLES.map((k) => (
                      <button key={k} className={pendRole === k ? "on" : ""} onClick={() => setPendRole(k)}>
                        取{RL[k]}
                      </button>
                    ))}
                  </div>
                  <div className="v3a-pend-act">
                    <button className="v3e-btn primary sm" disabled={busy} onClick={() => void commit()}>
                      加入「取{RL[pendRole]}」
                    </button>
                    <button className="v3e-btn sm" onClick={() => setPending(null)}>
                      换一张
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className={`v3a-pick-row${dropOn === "any" ? " drop" : ""}`}>
                <span className="v3a-q">先选图：</span>
                <button className="v3e-btn sm" onClick={() => fileRef.current?.click()}>
                  上传图片…
                </button>
                <button
                  className="v3e-btn sm v3a-takebtn"
                  disabled={!take}
                  draggable={!!take}
                  onDragStart={(e) => e.dataTransfer.setData(SRC_MIME, "take")}
                  onClick={() => take && choose({ src: "take", url: takeImg, name: `本镜${SLOT_NAME[fromSlot]} #${take.n}` })}
                  title={take ? "用本镜这一版作参考" : "本镜还没有图"}
                >
                  {takeImg && <img src={takeImg} alt="" />}
                  本镜{SLOT_NAME[fromSlot]}
                  {take ? ` #${take.n}` : "（还没有图）"}
                </button>
                <button className={`v3e-btn sm${picker ? " on" : ""}`} disabled={!sources.length} onClick={() => setPicker(!picker)}>
                  从版本 / 其他资产选{sources.length ? `（${sources.length}）` : ""} {picker ? "▴" : "▾"}
                </button>
                <span className="v3a-hint">或把图片拖到这里 / 拖到下面某一组</span>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) choose({ src: "file", file: f, url: URL.createObjectURL(f), name: f.name });
                    e.target.value = "";
                  }}
                />
              </div>
            )}
            {picker && !pending && (
              <div className="v3a-srcs">
                {[...new Set(sources.map((s) => s.group))].map((grp) => (
                  <div key={grp} className="v3a-srcgrp">
                    <div className="v3a-srcgrp-h">{grp}</div>
                    <div className="v3a-grid">
                      {sources
                        .filter((s) => s.group === grp)
                        .slice(0, 60)
                        .map((s) => (
                          <button
                            key={s.key}
                            className="v3a-th"
                            title={`${s.p.name} · 点一下选这张（也可以拖到某一组）`}
                            draggable
                            onDragStart={(e) => e.dataTransfer.setData(SRC_MIME, s.key)}
                            onClick={() => choose(s.p)}
                          >
                            {s.p.url ? <img src={s.p.url} alt="" loading="lazy" /> : <span className="e">无图</span>}
                            <span className="nm">{s.p.name}</span>
                          </button>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="v3a-groups">
            {ROLES.map((role) => {
              const g = refs.filter((r) => roleOf(r) === role);
              return (
                <div
                  key={role}
                  className={`v3a-grp${dropOn === role ? " drop" : ""}${g.length ? "" : " empty"}`}
                  onDragOver={(e) => {
                    e.stopPropagation();
                    dragOver(e, role);
                  }}
                  onDragLeave={() => setDropOn(null)}
                  onDrop={(e) => {
                    e.stopPropagation();
                    onDrop(e, role);
                  }}
                >
                  <div className="v3a-grp-h">
                    <b>取{RL[role]}</b>
                    <span>{g.length ? `${g.filter((r) => !off[r.ref_id]).length}/${g.length} 张在用` : "拖图到这里"}</span>
                  </div>
                  {g.length > 0 && (
                    <div className="v3a-grid">
                      {g.map((r) => (
                        <div
                          key={r.ref_id}
                          className={`v3a-th ref${off[r.ref_id] ? " off" : ""}`}
                          draggable
                          onDragStart={(e) => e.dataTransfer.setData(REF_MIME, r.ref_id)}
                        >
                          <button
                            className="im"
                            onClick={() => setOff((m) => ({ ...m, [r.ref_id]: !m[r.ref_id] }))}
                            title={off[r.ref_id] ? "没在用 · 点一下用这张" : "在用 · 点一下不用这张；拖到别的组换用途"}
                          >
                            {r.url ? <img src={r.url} alt="" /> : <span className="e">无图</span>}
                          </button>
                          {!off[r.ref_id] && <i className="no">图{imgNo(r)}</i>}
                          <button className="x" onClick={() => void dropRef(r)} title="从这个资产上去掉这张参考" aria-label="去掉这张参考">
                            ×
                          </button>
                        </div>
                      ))}
                      <button className="v3a-th add" onClick={() => fileRef.current?.click()} title={`上传一张，之后选用途`}>
                        +
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <h4>
            ② 底图<span>{base === "none" ? "不选底图时只按参考图出，改动幅度不生效" : "图1 = 底图，参考图从图2起"}</span>
          </h4>
          <div className="v3a-bases">
            {baseOpts.map((o) => (
              <button key={o.k} className={`v3a-base${base === o.k ? " on" : ""}`} disabled={!o.ok} onClick={() => setBase(o.k)} title={o.ok ? o.t : `${o.t}（没有图，不能选）`}>
                <span className="pv">{o.url ? <img src={o.url} alt="" /> : <span className="e">{o.k === "none" ? "无底图" : "没有图"}</span>}</span>
                <span className="t">{o.t}</span>
              </button>
            ))}
          </div>
          <label className="v3e-fld">
            <span>提示词（原样发送，不改写；写明图1、图2…各自的用途）</span>
            <textarea rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </label>
          {lastJobState && (lastJobState.notReady || lastJobState.state === "failed") && (
            <div className="v3e-note warn">{lastJobState.notReady ? "任务查询接口后端还没接好" : `生成失败：${lastJobState.error ?? ""}`}</div>
          )}
        </section>

        <section>
          <h4>
            ③ 生成结果 · 修改链<span>{gens.length ? `${gens.length} 次生成；旧的不删，随时回到任何一版` : "生成后结果出现在这里"}</span>
          </h4>
          {!gens.length && !liveJob ? (
            <div className="v3a-empty wide">还没有生成过。写好提示词点「生成」，结果会出现在这里。</div>
          ) : (
            <div className="v3a-chain">
              {chainOrder(gens).map(({ g, depth }) => (
                <button key={g.gen_id} className={`v3a-node${selGen === g.gen_id ? " sel" : ""}`} style={{ paddingLeft: 6 + Math.min(depth, 5) * 14 }} onClick={() => setSelGen(g.gen_id)} title={g.prompt}>
                  {depth > 0 && <span className="tw">└</span>}
                  {g.url ? <img src={g.url} alt="" loading="lazy" /> : <span className="th e" />}
                  <span className="when">{hhmm(g.created_at)}</span>
                  <span className="ins">{g.prompt ?? ""}</span>
                  {baseGen?.gen_id === g.gen_id && base === "gen" && <span className="tag">底图</span>}
                </button>
              ))}
              {liveJob && (
                <div className="v3a-node gen">
                  <span className="th e" />
                  <span className="when">{liveJob.state === "queued" ? "排队中" : "生成中"}</span>
                  <span className="ins">{GPU_LABEL[gpu]} · 预计约 {fmtSec(liveJob.eta_s)}</span>
                </div>
              )}
            </div>
          )}
          {gen && (
            <>
              <div className="v3a-pair">
                <figure>
                  {cmpLeft ? <img src={cmpLeft} alt="" onClick={() => setFull(true)} /> : <div className="e">{cmpLeftLabel}</div>}
                  <figcaption>{genParent ? cmpLeftLabel : "上一版：—"}</figcaption>
                </figure>
                <figure className="this">
                  {gen.url ? <img src={gen.url} alt="" onClick={() => setFull(true)} /> : <div className="e">无图</div>}
                  <figcaption>这一版 · {hhmm(gen.created_at)}</figcaption>
                </figure>
              </div>
              <div className="v3a-acts">
                <button
                  className="v3e-btn sm"
                  disabled={!gen.file}
                  onClick={() => {
                    setBaseGen(gen);
                    setBase("gen");
                  }}
                >
                  以这一版为底图继续改
                </button>
                <button className="v3e-btn sm" disabled={!genParent} onClick={() => setFull(true)}>
                  全屏对比
                </button>
              </div>
            </>
          )}
          {isScene && asset?.versions?.length ? (
            <div className="v3a-saved">
              <span className="v3a-q">底图版本（定稿后，首帧自动带这张底图）</span>
              <div className="v3a-plates">
                {(asset.versions as SceneVersion[]).map((v, i) => {
                  const vv = v.variant ?? "main";
                  const cur = (sc.data?.variants ?? []).find((x) => x.variant === vv);
                  const isLocked = !!cur?.locked && cur.version === v.version;
                  return (
                    <div key={v.id ?? v.version ?? i} className={`v3a-plate${isLocked ? " on" : ""}`}>
                      {v.url ? <img src={v.url} alt="" loading="lazy" /> : <span className="e">v{v.version ?? i + 1}</span>}
                      <div className="nm">
                        v{v.version ?? i + 1} · {variantLabel(vv)}
                        {v.label ? ` · ${v.label}` : ""}
                      </div>
                      {isLocked ? (
                        <button className="v3e-btn sm" disabled={busy} onClick={() => void unlock(vv)} title="取消画布定稿（不删文件）">
                          已定稿 · 取消
                        </button>
                      ) : (
                        <button className="v3e-btn primary sm" disabled={busy || v.version == null} onClick={() => void lock(v.version!, vv)}>
                          定稿为{variantLabel(vv)}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : !isScene && asset?.versions?.length ? (
            <div className="v3a-saved">
              <span className="v3a-q">已存的版本</span>
              <div className="v3a-grid">
                {asset.versions.map((v, i) => (
                  <span key={v.id ?? i} className="v3a-th ro" title={v.label ?? `v${v.n ?? i + 1}`}>
                    {v.url ? <img src={v.url} alt="" loading="lazy" /> : <span className="e">v{v.n ?? i + 1}</span>}
                    <span className="nm">{v.label ?? `v${v.n ?? i + 1}`}</span>
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </section>

        <section>
          <h4>④ 满意后保存{gen ? <span>保存选中的这一版（{hhmm(gen.created_at)}）</span> : null}</h4>
          {(isScene
            ? ([["version", "存为场景新底图版本（原底图不动）"]] as [Save, string][])
            : [
              ["shot", "只这一镜用（存为镜头覆盖）"],
              ["version", "存为资产新版本（形象数 +1）"],
              ["episode", "设为本集默认（造型确认需重做）"],
            ] as [Save, string][]
          ).map(([k, t]) => (
            <label key={k} className={`v3e-radio ${save === k ? "on" : ""}`}>
              <input type="radio" checked={save === k} onChange={() => setSave(k)} /> {t}
            </label>
          ))}
          {save === "episode" && (
            <label className="v3e-owner">
              <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方本人，确认改本集默认
            </label>
          )}
          {isScene && (
            <div className="v3e-fld">
              <span>存为哪种底图（变体）</span>
              <div className="v3a-roles">
                {["main", "low", "top", "wide", "close", "night"].map((k) => (
                  <button key={k} className={variant === k ? "on" : ""} onClick={() => setVariant(k)}>
                    {variantLabel(k)}
                  </button>
                ))}
              </div>
            </div>
          )}
          <label className="v3e-fld">
            <span>版本名称</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={dr.label} />
          </label>
        </section>
      </div>
      <footer className="v3a-foot">
          <div className="v3a-genrow">
          <div className="v3a-inline">
            <span>改动幅度</span>
            <div className="v3e-seg sm">
              {(Object.keys(STRENGTH_LABEL) as Strength[]).map((s) => (
                <button key={s} className={strength === s ? "on" : ""} disabled={base === "none"} onClick={() => setStrength(s)}>
                  {STRENGTH_LABEL[s]}
                </button>
              ))}
            </div>
          </div>
          <label className="v3a-inline">
            <span>用卡</span>
            <select value={gpu} onChange={(e) => setGpu(Number(e.target.value) as 0 | 3)}>
              <option value={0}>{GPU_LABEL[0]}</option>
              <option value={3}>{GPU_LABEL[3]}</option>
            </select>
          </label>
          <span className="eta">预计约 {fmtSec(eta.eta)}</span>
          <span className="sp" />
          <button className="v3e-btn primary" disabled={busy || !prompt.trim() || !!liveJob} onClick={() => void gen_()}>
            {liveJob ? "生成中…" : "生成"}
          </button>
        </div>
        <div className="v3a-saverow">
        <span className="eta">{saveFrom ? "选中的结果可以保存" : liveJob ? "等生成完成再保存" : gens.length ? "在修改链里选一版再保存" : "先生成一张"}</span>
        <span className="sp" />
        <button className="v3e-btn" onClick={close}>
          关闭
        </button>
        <button className="v3e-btn primary" disabled={busy || !saveFrom || (save === "episode" && !owner)} onClick={() => void doSave()}>
          保存这一版
        </button>
        </div>
      </footer>
      {full && gen && (
        <div className="v3a-full" onClick={() => setFull(false)} role="dialog" aria-label="对比">
          {[genParent, gen].map((g, i) => (
            <figure key={i}>
              {g?.url ? <img src={g.url} alt="" /> : <div className="e">没有上一版</div>}
              <figcaption>{i === 0 ? (g ? `上一版 · ${hhmm(g.created_at)}` : "—") : `这一版 · ${hhmm(gen.created_at)}`}</figcaption>
            </figure>
          ))}
          <span className="hint">点任意处 / Esc 关闭</span>
        </div>
      )}
    </aside>
  );
  if (embedded) return body;
  return (
    <div className="v3e-drawer-wrap" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      {body}
    </div>
  );
}
