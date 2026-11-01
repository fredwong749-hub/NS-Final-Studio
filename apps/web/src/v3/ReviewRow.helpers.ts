// 从 ReviewRow.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）

import { type Studio } from "../store";
import type { ShotSummary } from "../types";
import { matchFilter } from "../util";

import { frameState, videoBlock } from "./status";

/** fredw-92/UXF5（审查 N4）：⋯ 菜单里的“通过”什么时候不能点——全部由 status.ts 的 frameState / videoBlock 推出（只读用），
 *  与行状态、精修同一口径：没有视频、链不完整（没有首帧，视频作废）、视频已过期、首尾帧坏图 / 过期（视频不是由当前首尾帧来的） */
export function passBlock(s: ShotSummary, d: Parameters<typeof frameState>[1]): string | null {
  if (!s.video) return "还没有视频";
  const fv = frameState(s, d, "video");
  if (fv === "orphan") return "链不完整：没有首帧，这条视频已作废";
  if (fv === "stale") return "视频已过期，先重出视频";
  const up = videoBlock(s, d);
  if (up && up !== "还没有尾帧") return `${up}，这条视频随之作废`;
  return null;
}

/** 是否被过滤变暗 */
export const rowDim = (st: Studio, s: ShotSummary) => !matchFilter(st.filter, s, st.latest.get(s.id));
