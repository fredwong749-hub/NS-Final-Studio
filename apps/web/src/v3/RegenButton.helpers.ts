// UIRSI 11-01：“↻ 再生成”的接口和装备图登记（项目方原话：“添加一个生成按钮,基于现在再生成一个新的图”；
// “弹出需求提示词输入框,upload对应的装备(衣服,鞋子,视频,美甲等)图片,然后生图”）。
// 后端：POST /api/shots/{id}/takes/{stage}/{n}/regen（ns_api.takes_ui.regen）→ 走 /frame-jobs 同一条提交与校验；
// 新图进版本链、旧版本保留；过契约才设为当前（G3）。装备图先经资产中心接口登记到人物 + 类别（已在库里的直接用那件）。
import { hubApi, type HubItem } from "./assets/hub_api";

export type RegenStage = "image" | "last";
export type GearCat = "outfit" | "shoes" | "nails" | "accessory" | "bag" | "hair" | "makeup";
export const GEAR_CATS: { id: GearCat; name: string }[] = [
  { id: "outfit", name: "衣服" },
  { id: "shoes", name: "鞋" },
  { id: "nails", name: "美甲" },
  { id: "accessory", name: "饰品" },
  { id: "bag", name: "包" },
  { id: "hair", name: "发型" },
  { id: "makeup", name: "妆容" },
];
export const gearName = (c: GearCat) => GEAR_CATS.find((x) => x.id === c)?.name ?? "装备";

export type GearRef = { path: string; role: "item"; label: string; item_id?: string; reused: boolean; /** 查重接口没通、没查重就登记了（库里可能重复） */ unchecked?: boolean };
export type RegenResult = { job_id?: string; regen_of: number; mode: string; seed: number };

async function jsonOrThrow<T>(r: Response): Promise<T> {
  const t = await r.text();
  let d: unknown = null;
  try {
    d = t ? JSON.parse(t) : null;
  } catch {
    /* 非 JSON */
  }
  if (!r.ok) {
    const det = (d as { detail?: unknown } | null)?.detail;
    const msg = typeof det === "string" ? det : det && typeof det === "object" && "message" in det ? String((det as { message: unknown }).message) : t.slice(0, 200);
    throw Object.assign(new Error(r.status === 404 ? `接口还没上线（后端需重启）：${msg}` : msg || `HTTP ${r.status}`), { status: r.status });
  }
  return d as T;
}

export function regenTake(shot: string, stage: RegenStage, n: number, body: { instruction?: string; refs?: GearRef[] } = {}) {
  const refs = (body.refs ?? []).map((r) => ({ path: r.path, role: r.role, label: r.label }));
  return fetch(`/api/shots/${encodeURIComponent(shot)}/takes/${stage}/${n}/regen`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(body.instruction?.trim() ? { instruction: body.instruction.trim() } : {}), ...(refs.length ? { refs } : {}) }),
  }).then((r) => jsonOrThrow<RegenResult>(r));
}

/** 装备图登记进资产库（人物 + 类别，不挂到任何造型——只给这一次出图作参考，不改别的镜头）；已在库里 → 用库里那件 */
export async function registerGear(cid: string, file: File, cat: GearCat, name?: string, where = ""): Promise<GearRef> {
  const label = gearName(cat);
  let chk: Awaited<ReturnType<typeof hubApi.check>> | null = null;
  try {
    chk = await hubApi.check(cid, file, file.name, cat);
  } catch {
    chk = null; // 查重 / 起名失败不拦上传
  }
  const pathOf = (it: HubItem | null | undefined) => it?.image?.file ?? null;
  if (chk?.dup && pathOf(chk.dup)) return { path: pathOf(chk.dup)!, role: "item", label, item_id: chk.dup.id, reused: true };
  const nm = (name ?? "").trim() || chk?.suggested?.name?.trim() || `${label}（再生成上传）`;
  let up: { item: HubItem };
  try {
    up = await hubApi.upload(cid, file, file.name, cat, nm, [], `画布 ↻ 再生成 上传的装备参考${where ? `（${where}）` : ""}`);
  } catch (e) {
    // ASSETUX：查重没拦住、上传报“已经在库里”（409 带 item_id）→ 用库里那件，别让整个再生成卡住
    const id = (e as { detail?: { item_id?: string } })?.detail?.item_id ?? String((e as Error)?.message ?? "").match(/"item_id":\s*"([^"]+)"/)?.[1];
    const hit = id ? (await hubApi.get(cid, true).catch(() => null))?.items.find((x) => x.id === id) : undefined;
    if (hit && pathOf(hit)) return { path: pathOf(hit)!, role: "item", label, item_id: hit.id, reused: true };
    throw e;
  }
  const p = pathOf(up.item);
  if (!p) throw new Error("登记成功但没拿到图片路径");
  return { path: p, role: "item", label, item_id: up.item.id, reused: false, unchecked: !chk };
}
