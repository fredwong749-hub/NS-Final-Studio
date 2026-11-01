// ASSETUX：单品挂到造型时，替换造型里的哪一个部件。
// 11-01 审计日志：项目方在衣橱卡上点“A”，旧逻辑按槽位取“第一个还没有单品图的部件”，于是
// 黑色镜面漆皮超短裙 → 替换了“米白衬衫”、漆皮长风衣 → 替换了“深灰西装裙”，横杆铃铛链环 → 替换了“细银链”。
// 现在：只有名字里的品类词对得上（如“短裙”“高跟”）才自动替换；对不上就不猜，让人选（或作为额外单品，不替换）。
// 纯函数、只用类型导入：node --test 直接跑（apps/web/e2e/assetux/hub_match.test.mjs）。
import type { HubItem, HubLook, Part } from "./hub_api";

/** 部位是否兼容：部件和单品都知道部位时必须一致（上衣 ≠ 下装、颈饰 ≠ 身体穿环）；有一边不知道就不拦 */
export function zoneOk(partZone: string | null | undefined, itemZone: string | null | undefined): boolean {
  return !partZone || !itemZone || partZone === itemZone;
}

/** 部件换单品的候选：同槽位 + 同部位（REFLOCK 11-01：上衣部件只列上衣，裙 / 裤只列下装，项链只列颈饰） */
export function choicesFor(items: HubItem[], p: Part): HubItem[] {
  return items.filter((it) => (it.slot === p.slot && zoneOk(p.zone, it.zone)) || (p.extra && it.id === p.item_id));
}

export type PartPick = {
  /** 写进映射的部件名：替换时 = 造型里的部件；不替换时 = 单品名（额外，出图暂不用） */
  part: string;
  extra: boolean;
  /** true = 可以直接点一下生效；false = 要人选替换哪一项 */
  sure: boolean;
  /** 同类、同部位的部件（可替换的候选；只在人明确选择时才替换） */
  options: string[];
  /** 名字最像的那一项（只作提示，不自动替换） */
  suggest?: string | null;
  /** 不能直接挂的原因：zone = 造型里有同类部件，但部位都对不上（例：下装挂到只有上衣的造型） */
  reason?: "zone";
  /** 同槽位但部位不同的部件（给提示用） */
  others?: string[];
};

/** 品类词：去掉括号说明后的最后两个字（短裙、高跟、衬衫、银链…） */
export function nounOf(label: string): string {
  const t = label.replace(/[（(][^）)]*[）)]/g, "").trim();
  return t.slice(-2);
}

export function partFor(lk: HubLook, slot: string, name: string, zone?: string | null): PartPick {
  // 总调度 11-01：挂造型的默认行为 = 加为本造型的额外单品，不替换任何已登记部件；
  // 只有人在界面上明确选了“替换哪一项”才替换。这里只给出“可替换的候选”和“名字最像的那一项”（suggest，仅作提示）。
  const slotParts = lk.parts.filter((p) => !p.extra && p.slot === slot);
  const same = slotParts.filter((p) => zoneOk(p.zone, zone));
  const options = same.map((p) => p.label);
  const n = nounOf(name);
  const hits = same.filter((p) => {
    const pn = nounOf(p.label);
    return (pn.length === 2 && name.includes(pn)) || (n.length === 2 && p.label.includes(n));
  });
  return {
    part: name,
    extra: true,
    sure: true,
    options,
    suggest: hits.length === 1 ? hits[0].label : null,
    reason: !same.length && slotParts.length ? "zone" : undefined,
    others: slotParts.map((p) => p.label),
  };
}
