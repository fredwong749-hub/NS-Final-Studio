// NAVIA：镜头状态的统一词表与圆点（全站唯一来源；总览 / 分镜行 / 出图 / 视频 / 顶栏 tab 都按这张表）。
// 颜色只有三种加一种状态：灰 = 排队或没开始；琥珀呼吸 = 在出；琥珀实心 = 要你看或卡住；绿 = 全部定稿。没有红、蓝。
// L-123：只有“用这张 / 用这版”和“修改”，词表里没有“不要 / 打回”。
export type ShotKind = "todo" | "queued" | "running" | "review" | "stuck" | "final";
export type ShotDot = "gray" | "breathe" | "amber" | "green";

export const SHOT_WORD: Record<ShotKind, { word: string; dot: ShotDot }> = {
  todo: { word: "还没出", dot: "gray" },
  queued: { word: "排队", dot: "gray" },
  running: { word: "正在出", dot: "breathe" },
  review: { word: "待你看", dot: "amber" },
  stuck: { word: "缺首尾帧", dot: "amber" },
  final: { word: "已定稿", dot: "green" },
};

/** 视频页后端状态 → 统一类别 */
export const VIDEO_STATE_KIND: Record<string, ShotKind> = {
  todo: "todo",
  queued: "queued",
  rendering: "running",
  pending_review: "review",
  need_frames: "stuck",
  failed: "stuck",
  final: "final",
};

/** 阶段名放前面（“出视频中 / 出图中”），其余词沿用统一词表 */
export const shotWord = (kind: ShotKind, stage?: "图" | "视频") => (kind === "running" && stage ? `出${stage}中` : SHOT_WORD[kind].word);
