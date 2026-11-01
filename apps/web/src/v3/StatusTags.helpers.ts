// UIRSI r40（项目方 11-02 00:1x：“在 UI 里面做一个错误标志吧.比如哪些是重置的,过期的,就给它用不同的颜色 label 一下”）：
// 镜头状态标签的口径——kind 由后端 ns_api/shot_status.py 给（汇总 producer 登记 / 剧本版本 / 看图判定），前端只负责上色和写图例。
export type TagKind = "vqa_fail" | "old" | "redo" | "stale" | "judge" | "best" | "busy" | "queued" | "ok";
export type ShotTag = { kind: TagKind; label: string; stage: string; text: string };
export type ShotStatusTags = { main: TagKind | null; tags: ShotTag[] };

/** 严重程度从高到低（与后端 KINDS 同序）；图例按这个顺序 */
export const TAG_ORDER: TagKind[] = ["vqa_fail", "old", "redo", "stale", "judge", "best", "busy", "queued", "ok"];
export const TAG_WORD: Record<TagKind, string> = {
  vqa_fail: "看图没过",
  old: "旧剧本版本",
  redo: "待重出",
  stale: "过期",
  judge: "待补判",
  best: "尽力版",
  busy: "出图中",
  queued: "排队中",
  ok: "通过",
};
export const TAG_HELP: Record<TagKind, string> = {
  vqa_fail: "看图检查没过（写了原因：看镜头 / 缺外套 / 发色 / 缺身份脸 / 跨镜不连贯 / 多肢…）",
  old: "只剩剧本更新前出的旧图，没有按现在剧本出的新图",
  redo: "已重置或被驳回（全量重做、总调度或看图检查驳回），等重出",
  stale: "剧本或出图作业变了，当前这一版要重出",
  judge: "看图检查还没出结果，待补判",
  best: "试了几次没全过，先用罚分最小的一版",
  busy: "正在出图 / 出视频",
  queued: "排队等空闲的卡",
  ok: "已通过并设为当前",
};

/** 一格的提示文字：全部状态逐条列出（悬停 / 点开看） */
export const tagsTitle = (st: ShotStatusTags | null | undefined) =>
  st?.tags.length ? st.tags.map((t) => `${TAG_WORD[t.kind]} · ${t.stage}：${t.text}`).join("\n") : "";

/** 一集里每类各有几镜（每镜按它带的全部状态计，一镜同类只算一次） */
export function countKinds(list: (ShotStatusTags | null | undefined)[]): Partial<Record<TagKind, number>> {
  const out: Partial<Record<TagKind, number>> = {};
  for (const st of list) for (const k of new Set((st?.tags ?? []).map((t) => t.kind))) out[k] = (out[k] ?? 0) + 1;
  return out;
}
export const hasKind = (st: ShotStatusTags | null | undefined, k: TagKind) => !!st?.tags.some((t) => t.kind === k);
