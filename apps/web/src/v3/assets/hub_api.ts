// ASSETUX：人物资产页接口（services/api/ns_api/character_hub.py）。点一下就生效，返回 prev 供 10 秒撤销。
export type Img = { file: string; url: string };
export type FaceCand = Img & { current: boolean; note: string; ref_id?: string | null };
export type SheetCand = Img & { current: boolean; seed: number | null; thumb: string | null };
export type PartStatus = "wardrobe" | "sheet_only" | "missing" | "identity" | "extra";
export type Part = {
  slot: string;
  slot_name: string;
  label: string;
  raw: string;
  zone: string | null;
  item_id: string | null;
  item_name: string | null;
  item_image: Img | null;
  status: PartStatus;
  extra: boolean;
  /** REFLOCK 隔离区：这条映射暂不生效，待项目方确认 */
  quarantine?: { item_id: string; item_name: string; why: string } | null;
};
export type HubLook = { look: string; use: string; zh: string; sheet: Img | null; custom?: boolean; candidates: SheetCand[]; parts: Part[]; counts: { wardrobe: number; sheet_only: number; missing: number } };
export type HubItem = {
  id: string;
  slot: string;
  slot_name: string;
  cat: string;
  note: string;
  /** 部位（和出图解析器 zone_of 同口径）：upper / lower / body / feet / hand / neck / waist / face */
  zone?: string | null;
  name: string;
  image: Img | null;
  images: number;
  gallery: (Img & { version: number })[];
  /** “↻ 再生成”出的候选图（点“✓ 用这张”才加进单品并设主图） */
  regen?: Img[];
  tags: string[];
  source: string;
  created_at: string | null;
  uploaded_by: string | null;
  looks: { look: string; part: string; extra?: boolean }[];
  version: number;
};
export type CheckResult = {
  dup: HubItem | null;
  dup_in_current: boolean;
  suggested: { name: string; source: "existing" | "model" | "none"; cat?: string | null; model?: string | null; error?: string | null };
};
export type HubRecent = { at: string; by: string; action: string; [k: string]: unknown };
export type HubChar = {
  project: string;
  cid: string;
  name: string;
  marker: string;
  face: FaceCand | null;
  faces: FaceCand[];
  looks: HubLook[];
  items: HubItem[];
  items_total: number;
  items_hidden: number;
  voice: { voice?: string; speed?: number; note?: string; gender?: string; age?: number; vo_speed?: number } | null;
  recent: HubRecent[];
  missing: number;
  sheet_only: number;
  /** 单品目录里没登记成单品的图片（相对路径） */
  unregistered?: string[];
  /** 标了“不要”的图（相对项目根路径 → 原因） */
  rejected?: Record<string, { reasons: string[]; note: string }>;
  /** 排期：每集这个人用哪套造型（registered = 逐镜登记的计数；override = 人物页整集覆盖） */
  schedule?: { ep: number; registered: Record<string, number>; override: string | null }[];
};
export type HubListRow = { cid: string; name: string; face: FaceCand | null; looks: number; sheets: number; items: number; missing: number; sheet_only: number };
export type HubList = { project: string; projects: string[]; characters: HubListRow[]; categories: { id: string; slot: string; name: string }[] };

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    const d = (b as { detail?: unknown }).detail;
    const msg = typeof d === "string" ? d : (d as { message?: string })?.message ?? `HTTP ${r.status}`;
    throw Object.assign(new Error(msg), { status: r.status, detail: d });
  }
  return r.json() as Promise<T>;
}
const enc = encodeURIComponent;

/** 隔离区（RECALL 11-01）：文件名 / 目录名集合。资产中心任何视图都不列、不链接这些（模块级缓存，读一次） */
let quarantineP: Promise<Set<string>> | null = null;
export function loadQuarantine(): Promise<Set<string>> {
  if (!quarantineP)
    quarantineP = fetch("/api/asset-quarantine")
      .then((r) => (r.ok ? r.json() : { names: [] }))
      .then((j: { names?: string[] }) => new Set(j.names ?? []))
      .catch(() => {
        quarantineP = null;
        return new Set<string>();
      });
  return quarantineP;
}
export const isQuarantined = (q: Set<string> | null, ...keys: (string | null | undefined)[]) =>
  !!q && keys.some((k) => !!k && (q.has(k) || q.has(k.split("/").pop() ?? "") || q.has((k.split("/").pop() ?? "").replace(/\.[A-Za-z0-9]+$/, ""))));

export const hubApi = {
  list: () => fetch("/api/character-hub").then((r) => j<HubList>(r)),
  get: (cid: string, allItems = false) => fetch(`/api/character-hub/${enc(cid)}${allItems ? "?all_items=true" : ""}`).then((r) => j<HubChar>(r)),
  face: (cid: string, file: string) => fetch(`/api/character-hub/${enc(cid)}/face`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file }) }).then((r) => j<{ prev: string | null }>(r)),
  sheet: (cid: string, look: string, file: string) => fetch(`/api/character-hub/${enc(cid)}/sheet`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ look, file }) }).then((r) => j<{ prev: string | null }>(r)),
  map: (cid: string, look: string, part: string, item_id: string | null, via: "card" | "picker" | "undo" | "upload" = "undo") => fetch(`/api/character-hub/${enc(cid)}/map`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ look, part, item_id, via }) }).then((r) => j<{ prev: string | null }>(r)),
  rename: (cid: string, id: string, name: string) => fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/rename`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }).then((r) => j<{ prev: string }>(r)),
  trash: (cid: string, id: string) => fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/trash`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }).then((r) => j<{ entry_id: string; maps: { look: string; part: string }[] }>(r)),
  restore: (cid: string, id: string, entry_id: string, maps: { look: string; part: string }[]) => fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entry_id, maps }) }).then((r) => j<{ ok: true }>(r)),
  addImage: (cid: string, id: string, f: Blob, fileName: string) => {
    const fd = new FormData();
    fd.append("file", f, fileName);
    return fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/images`, { method: "POST", body: fd }).then((r) => j<{ version: number }>(r));
  },
  /** 删除登记的参考图（身份脸候选 / 场景底图参考）→ 回收站（EDITDEL）；撤销 = restore */
  trashRef: (assetId: string, refId: string) =>
    fetch(`/api/trash/object?type=asset_ref&id=${enc(`${assetId}/${refId}`)}&confirm=true&reason=${enc("资产中心删除参考图")}`, { method: "DELETE" }).then((r) => j<{ entry_id: string; name?: string }>(r)),
  /** EDITDEL 11-01 新增类型：sheet_candidate（id = 相对项目根的设定图路径）、prop（id = 道具 id） */
  trashObj: (type: "sheet_candidate" | "prop", id: string) =>
    fetch(`/api/trash/object?type=${type}&id=${enc(id)}&reason=${enc("资产中心删除")}`, { method: "DELETE" }).then((r) => j<{ entry_id: string }>(r)),
  /** ↻ 再生成（项目方 11-01）：当前图作底图 + 装备图参考 + 提示词 → 资产生成；出好的图回到对应位置当候选 */
  regen: (cid: string, b: { kind: "sheet" | "face" | "item"; file: string; prompt: string; look?: string; item_id?: string; gear: { path: string; label: string; item_id?: string }[] }) =>
    fetch(`/api/character-hub/${enc(cid)}/regen`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then((r) => j<{ job?: { job_id?: string } }>(r)),
  useRegen: (cid: string, id: string, file: string) =>
    fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/use-regen`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file }) }).then((r) => j<{ prev: string | null }>(r)),
  unuseRegen: (cid: string, id: string, file: string, prev: string | null) =>
    fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/unuse-regen`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file, prev }) }).then((r) => j<{ removed: boolean }>(r)),
  /** 单品附图 ✓ 用这张：设为主图（images[0]） */
  primary: (cid: string, id: string, file: string) =>
    fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/primary`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file }) }).then((r) => j<{ prev: string | null }>(r)),
  restoreTrash: (entryId: string) => fetch(`/api/trash/${enc(entryId)}/restore`, { method: "POST" }).then((r) => j<{ ok?: boolean }>(r)),
  newLook: (cid: string, b: { use: string; outfit: string; shoes: string; accessory: string }) =>
    fetch(`/api/character-hub/${enc(cid)}/looks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then((r) => j<{ look: string }>(r)),
  removeLook: (cid: string, look: string) => fetch(`/api/character-hub/${enc(cid)}/looks/${enc(look)}/remove`, { method: "POST" }).then((r) => j<{ ok: true }>(r)),
  uploadSheet: (cid: string, look: string, f: Blob, fileName: string) => {
    const fd = new FormData();
    fd.append("file", f, fileName);
    return fetch(`/api/character-hub/${enc(cid)}/looks/${enc(look)}/sheet`, { method: "POST", body: fd }).then((r) => j<{ prev: string | null }>(r));
  },
  schedule: (cid: string, ep: number, look: string | null) =>
    fetch(`/api/character-hub/${enc(cid)}/schedule`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ep, look }) }).then((r) => j<{ prev: string | null }>(r)),
  /** 选图后先查（不写）：已经在库里 → dup；否则看图起名（名字不用文件名） */
  check: (cid: string, f: Blob, fileName: string, cat: string | null, ignoreDup = false) => {
    const fd = new FormData();
    fd.append("file", f, fileName);
    if (cat) fd.append("cat", cat);
    if (ignoreDup) fd.append("ignore_dup", "true");
    return fetch(`/api/character-hub/${enc(cid)}/check-image`, { method: "POST", body: fd }).then((r) => j<CheckResult>(r));
  },
  adopt: (cid: string, id: string, looks: { look: string; part: string }[], remove = false) =>
    fetch(`/api/character-hub/${enc(cid)}/items/${enc(id)}/adopt`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ looks, remove }) }).then((r) =>
      j<{ was_adopted: boolean; mapped: { look: string; part: string; prev: string | null }[] }>(r),
    ),
  upload: (cid: string, f: Blob, fileName: string, cat: string, name: string, looks: { look: string; part: string }[], note = "", force = false) => {
    const fd = new FormData();
    fd.append("note", note);
    if (force) fd.append("force", "true");
    fd.append("file", f, fileName);
    fd.append("cat", cat);
    fd.append("name", name);
    fd.append("looks", JSON.stringify(looks));
    return fetch(`/api/character-hub/${enc(cid)}/wardrobe`, { method: "POST", body: fd }).then((r) => j<{ item: HubItem }>(r));
  },
};

/** 界面类别（和后端 CATS 一致）；hint = 这个类别对应造型部件的槽位 */
export const CATS: { id: string; name: string; slot: string }[] = [
  { id: "outfit", name: "衣服", slot: "outfit" },
  { id: "shoes", name: "鞋", slot: "shoes" },
  { id: "accessory", name: "饰品", slot: "accessory" },
  { id: "body", name: "身体饰品·穿环", slot: "accessory" },
  { id: "nails", name: "指甲", slot: "nails" },
  { id: "bag", name: "包", slot: "accessory" },
  { id: "hair", name: "发型", slot: "hair" },
  { id: "makeup", name: "妆容", slot: "makeup" },
];
export const catOf = (it: HubItem) => it.cat || (CATS.find((c) => c.slot === it.slot)?.id ?? "accessory");

export { partFor, nounOf, choicesFor, zoneOk, type PartPick } from "./hub_match";

export const ACTION_TEXT: Record<string, string> = {
  face: "换了身份脸",
  sheet: "选定了设定图",
  map: "改了造型单品",
  upload: "上传了单品",
  add_image: "给单品加了一张图",
  adopt: "用了库里已有的单品",
  new_look: "新建了造型",
  remove_look: "撤销了新造型",
  schedule: "改了排期",
  unadopt: "撤销了“用这件”",
  rename: "改了单品名",
  trash: "删除了单品（在回收站）",
  restore: "撤销了删除",
};
