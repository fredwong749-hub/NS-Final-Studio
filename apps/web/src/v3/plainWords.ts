// W5b UIUX-FIX 11-03（A5 审计 P2-3 / C-20 大白话）：工程词 → 人话 的唯一一份词典。
// 卡点一句话、负责方、待办卡片里项目方看得到的文字都过一遍这里；别处不要另写一套替换。
// 根治仍是登记卡点时多写一个 plain 字段（tools/ 不在前端地盘）——这里是兜底。

/** 顺序有讲究：长的、具体的在前（“producer import 失败”要先于“producer”） */
export const PLAIN_WORDS: [RegExp, string][] = [
  // UI-FIX 11-03（项目方 10:4x 截图：一键出片小窗露“G4 样片”“LoRA”）
  [/\bG4\s*样片/g, "样片"],
  [/身份\s*LoRA/gi, "人物脸模型"],
  [/\bLoRA\s*训练/gi, "模型训练"],
  [/\bLoRA\b/gi, "专属模型"],
  [/渲染道|出图道/g, "显卡"],
  [/派道/g, "分配显卡"],
  [/道表/g, "显卡列表"],
  [/producer\s*(?:整体\s*)?import\s*失败/gi, "出图程序启动失败"],
  [/import\s*失败/gi, "程序启动失败"],
  [/\bproducer\b/gi, "出图程序"],
  [/\bpreflight\b/gi, "出图前检查"],
  [/\blint\b/gi, "规则检查"],
  [/\bP1\s*storyline\b/gi, "故事线"],
  [/\bstoryline\b/gi, "故事线"],
  [/\blogline\b/gi, "一句话梗概"],
  [/\bP4\b#?/gi, "分镜稿"],
  [/\bsha(?:256|1)?\b/gi, "校验码"],
  [/\bseed\b/gi, "种子号"],
  [/\bOCR\b/gi, "文字识别"],
  [/\bVQA\b/gi, "看图检查"],
  [/\bprompt\b/gi, "提示词"],
  [/\bverify\b/gi, "复核"],
  [/\bautoflow(?:\s*(?:run|daemon))?\b/gi, "自动流程"],
  [/\bdaemon\b/gi, "常驻程序"],
  [/\bgit\s*status\b/gi, "代码改动清单"],
  [/\bobserve\b/gi, "只观察"],
  [/\bwhy\b/gi, "原因说明"],
  [/\bSH(\d+)\b/g, "镜$1"],
  [/补丁环/g, "自动返修"],
  [/出图契约/g, "出图规则检查"],
];

/** 一句话过词典（不改长度限制；后端已截好） */
export function plainText(s: string | null | undefined): string {
  let t = String(s ?? "");
  for (const [re, to] of PLAIN_WORDS) t = t.replace(re, to);
  return t.replace(/\s{2,}/g, " ");
}

/** 负责方：“工程师（REVIEW-A / HARNESS-O …）”这类工程 agent 代号 → “系统（工程线）” */
export function plainOwner(s: string | null | undefined): string {
  const t = String(s ?? "");
  if (/^工程师[（(]/.test(t) || /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$/.test(t)) return "系统（工程线）";
  return plainText(t);
}
