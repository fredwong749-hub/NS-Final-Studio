// 从 OwnerDecision.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）

import type { SopOwnerAction } from "../types";

/** 界面里能直接拍板的关口（其余仍只显示说明） */
export const DECIDABLE = new Set(["look", "G3", "G4", "G5", "plate"]);

/** 芯片上的短标题：去掉关口代号，角色用中文名 */
export function actionTitle(a: SopOwnerAction): string {
  if (a.gate === "look" && a.character_name) return `确认造型：${a.character_name}`;
  return a.title.replace(/（G\d）/g, "").replace(/\bG\d\b\s*/g, "").trim();
}
