// PW-019：从 Drawer.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { STAGE_LABEL } from "../util";
import type { Stage } from "../types";

/** fredw-92/UXF1（审查 #43）：v1 任务的 take 是对象 {n, stage, …}，旧任务是数字 → 统一成 “#n” */
export function takeLabel(t: unknown): string | null {
  if (t == null) return null;
  if (typeof t === "number" || typeof t === "string") return `#${t}`;
  if (typeof t === "object") {
    const o = t as { n?: number | null; stage?: string | null; bad?: string | null };
    if (o.n == null) return null;
    return `${o.stage ? `${STAGE_LABEL[o.stage as Stage] ?? o.stage} ` : ""}#${o.n}${o.bad ? "（坏图）" : ""}`;
  }
  return null;
}

/** 错误先给一句中文摘要（全文在悬停 / 展开里） */
export function errSummary(e: string | null | undefined): string {
  if (!e) return "";
  if (/out of memory|CUDA OOM|OutOfMemory|allocation on device/i.test(e)) return "显存不够（另一个任务占着卡），可稍后重试或换卡";
  if (/timed? ?out|超时/i.test(e)) return "超时：卡太忙或隧道慢，可重试";
  if (/connection|连不上|refused|unreachable/i.test(e)) return "连不上出图卡（隧道断了？），恢复后重试";
  if (/API 重启中断/.test(e)) return "API 重启时中断（不是画面问题），可重试";
  // fredw-92/UXF5（审查 R1）：存版本时的数据校验错（pydantic 原文）不给项目方看英文，原文只在悬停
  if (/validation error for|errors\.pydantic\.dev/i.test(e)) return "存版本失败（系统问题，不是画面问题），已记录";
  if (/坏图/.test(e)) return e.slice(0, 80);
  return e.length > 80 ? `${e.slice(0, 80)}…` : e;
}
