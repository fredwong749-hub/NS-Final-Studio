// PW-019：从 ui.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { createContext, useContext } from "react";
import type { RefTarget } from "./edit/RefSwitchPanel";
import type { RightTab } from "./edit/RightTabs";

export interface UiState {
  refSwitch: { shotId: string; target: RefTarget } | null;
  openRefSwitch: (shotId: string, target: RefTarget) => void;
  closeRefSwitch: () => void;
  railCollapsed: boolean;
  /** 实际是否显示 56 px 头像条（v3.1 §1.2：审片、精修默认都收起；用户展开后记住），窄屏（≤1440）精修始终收起 */
  railMini: boolean;
  setRailCollapsed: (v: boolean) => void;
  rightTab: RightTab;
  setRightTab: (t: RightTab) => void;
}

export const Ctx = createContext<UiState | null>(null);

export function useUi(): UiState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useUi 必须在 UiProvider 里");
  return v;
}
