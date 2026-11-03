// UIFIX-F 11-03：场景显示名的纯函数部分（不依赖 React / 接口），sceneLabel.ts 和 node --test 共用。
// 规则（L-126 完全切割）：名字只来自当前剧的场景登记（/api/assets/scenes）；登记里没有的，显示“场景未登记：<id>”，
// 绝不按 id 里的英文单词拼中文名——以前的 WORD 表（office→办公室、night→夜、gu→顾沉…）是 V1 词汇，
// V2 第 1 集分镜页上的“办公室夜”就是它把 V1 状态表漏进来的 sk_office_night 拼出来的。

/** id / 路径 → 场景 id（"sk_office_night/plate.png" → "sk_office_night"） */
export const sceneIdOf = (v: string) => v.replace(/\\/g, "/").split("/").find((p) => /^sk_/.test(p)) ?? v.replace(/\.(png|jpe?g|webp)$/i, "").split("/")[0];

/** 看起来像内部 id / 路径（不是给人看的名字） */
export const looksInternal = (v: string | null | undefined) => !!v && (/[/\\]|\.(png|jpe?g|webp|json)$/i.test(v) || /^[a-z0-9]+(_[a-z0-9]+)+$/i.test(v));

/** 登记里没有这个场景时的显示（带 id，项目方能对上资产清单；不拼中文、不回退 V1） */
export const unregisteredLabel = (id: string) => `场景未登记：${id}`;

/** 纯查表：names = 当前剧场景登记（scene_id → 名字）。v 已是人话 → 原样；登记有名字 → 名字；否则“场景未登记：id” */
export function resolveSceneLabel(v: string | null | undefined, names: ReadonlyMap<string, string> | null | undefined): string | null {
  if (!v) return null;
  if (!looksInternal(v)) return v;
  const id = sceneIdOf(v);
  const hit = names?.get(id);
  if (hit && !looksInternal(hit)) return hit;
  return unregisteredLabel(id);
}

type SopShotLike = {
  scene_id?: string | null;
  scene_id_source?: string | null;
  blockers?: { code: string }[];
  stages?: Record<string, { blockers?: { code: string }[] }>;
};

/** SOP 接口带出的本镜场景 id 能不能信：新后端自带 scene_id_source（后端已按“剧本 > 属于当前剧本的状态表”判过）→ 直接用；
 *  旧后端只有状态表的 scene_id → 状态表过期（timeline_stale：按别的剧本生成）时不用，否则 V1 的 sk_office_night 会挂到 V2 镜头上 */
export function sopSceneId(sop: SopShotLike | null | undefined): string | null {
  if (!sop?.scene_id) return null;
  if ("scene_id_source" in sop) return sop.scene_id_source ? sop.scene_id : null;
  const codes = [...(sop.blockers ?? []), ...Object.values(sop.stages ?? {}).flatMap((s) => s.blockers ?? [])].map((b) => b.code);
  return codes.includes("timeline_stale") ? null : sop.scene_id;
}

/** 底图 / 参考路径属于哪个场景；与本镜场景 id 不一致（例如 V1 状态表残留的 sk_office_night 底图挂到了 V2 的 sk_white_cyc 镜上）→ false */
export function plateMatchesScene(plateIdOrPath: string | null | undefined, sceneId: string | null | undefined): boolean {
  if (!plateIdOrPath) return false;
  if (!sceneId) return true; // 本镜没写场景：无从比对，照旧显示
  return sceneIdOf(plateIdOrPath) === sceneId;
}
