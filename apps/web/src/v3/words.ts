// fredw-92/UXF5（审查 R4 / N13 / R6）：对项目方的状态词、动作名只在这里定一份，各处都从这里取。
// 短名放角标 / 行格，长名放状态胶囊 / 说明；动作统一叫“重出X”（不再有“重新生成X”“重出X（已过期）”）。
// 这个文件不 import 任何东西（state.ts / status.ts 都要用，避免循环引用）。

/** 自动测试定稿（整集出片替你定的，你还没复审）：短名 */
export const AUTO_SHORT = "自动·待复审";
/** 自动测试定稿：长名 */
export const AUTO_LONG = "自动测试定稿，待你复审";
/** 自动测试定稿：悬停说明 */
export const AUTO_TIP = "整集出片“自动测试定稿”出的，你还没复审：不算已定稿 / 已通过";

/** 过期（上游改过，要重出）：短名 */
export const STALE_SHORT = "过期·需重出";
/** 过期：长名，例“首帧已过期，需重出” */
export const staleLong = (nm: string) => `${nm}已过期，需重出`;

/** UX5-B：所用资产（定妆 / LoRA / 预设 / 视频基底…）出了新版本；只标记，不算过期、不触发整集重出 */
export const DEP_UPDATED = "依赖已更新";

/** 重出某一格的动作名，例“重出首帧” */
export const regenLabel = (nm: string) => `重出${nm}`;

/** 术语表（审查 R6）：顶栏步骤、页面标题、工具菜单统一用这些叫法 */
export const TERM = {
  /** 顶栏第 ② 步、资产页标题 */
  assets: "资产中心",
  /** 顶栏第 ③ 步：首尾帧图片 */
  frames: "出图（首尾帧）",
  /** 剧本里的分镜字段（分镜表 / 分镜详情） */
  storyboard: "剧本分镜",
} as const;

/** SOP 阶段编号 → 人话（审查 R5）：画布里每行都标着 S1、S2、S3（镜头号），“不进 S3”会被读成“第 3 镜”。
 *  对项目方的文字里出现的阶段编号改成“第 N 阶段（名称）”；镜头号（ep02-S3 / 行首 S3）不经过这里。 */
const STAGE_NAME: Record<string, string> = { "1": "剧本", "2": "资产", "3": "出图", "4": "视频", "5": "成片" };
export const stageWords = (t: string) =>
  t
    .replace(/^S\d[：:]\s*/, "")
    .replace(/(进入?|停在|回到|退回)\s*S([1-5])(?![0-9])/g, (_m, v: string, n: string) => `${v}第 ${n} 阶段（${STAGE_NAME[n]}）`)
    .replace(/^S([1-5])(?![0-9])\s*/, (_m, n: string) => `第 ${n} 阶段（${STAGE_NAME[n]}）`);

/** UX5（A4）：衣橱槽位英文键 → 中文，全站只在这里定一份 */
export const SLOT_NAME: Record<string, string> = { outfit: "服装", shoes: "鞋", makeup: "妆容", nails: "美甲", hair: "发型", accessory: "饰品", other: "其他" };
export const slotName = (k: string) => SLOT_NAME[k] ?? k;
