// UIRSI r43（总调度 02:2x 规格 §一“颜色规则”，项目方 02:1x：“颜色太错乱了，能不能再整洁一点？”）
// 全剧总览只用中性色；状态色只有三种，而且只用 8px 小圆点：
//   run  = 渲染中（蓝点 + 呼吸灯，K-UI-048）
//   need = 需要人看 / 失败（琥珀点）
//   ok   = 已确认（绿点）
// 其他状态（排队、待重出、未开始、过期…）一律不画点，只在悬停提示和详情抽屉里用文字写。
// 口径：后端 ns_api/shot_status.main5（need / stale / doing / todo / done + running + why）；
//       main5 还没上线（:8800 未重启）时按旧标签兜底：busy → run；vqa_fail / best → need；ok → ok。
import type { ShotStatusTags } from "../StatusTags.helpers";

export type MainStatus = ShotStatusTags & { main5?: "need" | "stale" | "doing" | "todo" | "done"; why?: string; running?: boolean; step?: string };
export type SeaDot = "run" | "need" | "ok";

export function dotOf(s: MainStatus | null | undefined): SeaDot | null {
  if (!s) return null;
  if (s.main5) return s.main5 === "need" ? "need" : s.main5 === "done" ? "ok" : s.main5 === "doing" && s.running ? "run" : null;
  if (s.main === "busy") return "run";
  if (s.main === "vqa_fail" || s.main === "best") return "need";
  if (s.main === "ok") return "ok";
  return null;
}

const WORD5: Record<string, string> = { need: "需要你看", stale: "过期，要重出", doing: "进行中", todo: "未开始", done: "已确认" };
const WORD_OLD: Record<string, string> = { vqa_fail: "看图没过", old: "旧剧本版本", redo: "待重出", stale: "过期", judge: "待补判", best: "尽力版，等你接受", busy: "正在出", queued: "排队中", ok: "已确认" };

/** 一句状态文字（抽屉 / 悬停用） */
export function statusWord(s: MainStatus | null | undefined): string {
  if (!s) return "未开始";
  if (s.main5) return s.main5 === "doing" ? (s.running ? "正在出" : "排队中") : WORD5[s.main5];
  return s.main ? WORD_OLD[s.main] ?? s.main : "未开始";
}

export const DOT_TITLE: Record<SeaDot, string> = { run: "正在出图 / 出视频", need: "需要你看（没过检查或尽力版待接受）", ok: "已确认" };
