// PW-019：从 RightTabs.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会整页重载）。
import type { ShotSummary, SopShot } from "../../types";
import { isSysText } from "../status";

export type RightTab = "prompt" | "advanced" | "versions" | "assets" | "sound" | "rules";
export const RIGHT_TABS: [RightTab, string][] = [
  ["prompt", "提示词"],
  // UIRSI r11（D12）：以前参数分在 3 处（修改诉求面板 / 改参数重渲弹窗 / 右栏高级），现在这一镜的全部参数都在「参数」一处
  ["advanced", "参数"],
  ["versions", "版本"],
  ["assets", "资产"], // UX5：本镜资产 + 出图时用的版本（依赖已更新）
  ["sound", "声音"], // UIRSI B4：这一镜每句台词 ▶ + 整镜连播 + 跳到配乐
  ["rules", "规则"],
];

/** 这条卡点是不是要项目方本人处理 */
// UIMASTER：系统内部检查（G3 采纳、校验器、规则号……）即使挂在项目方名下也不算“需要你处理”，归到灰色“系统提示”（与 status.ts 的“为什么卡住”同口径）
export const isMine = (b: { actor?: string | null; actor_label?: string | null; text?: string | null }) => (b.actor === "owner" || /项目方|你/.test(b.actor_label ?? "")) && !isSysText(b.text ?? "");
/** 去掉内部代号（“S3 ”“G4：”“img：剧本 img”这类）后的说明 */
export const plain = (t: string) =>
  t
    .replace(/\*\*/g, "")
    .replace(/^(等\s*)?G\d+[：:]\s*/, "等：")
    .replace(/\bgpu3\b/gi, "视频端")
    .replace(/accepted/g, "验收")
    .trim();

/** 规则标签上该显示的数字：只数“需要你处理”的（供外壳的标签徽标用） */
export function rulesNeedYou(shot: ShotSummary, sopShot: SopShot | null | undefined): number {
  const mine = (sopShot?.blockers ?? []).filter(isMine).length;
  const stale = Object.values(shot.stale ?? {}).filter((v) => v && v.length).length;
  return mine + stale;
}
