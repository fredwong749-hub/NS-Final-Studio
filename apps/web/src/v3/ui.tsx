// fredw-92/W4a：v3 外壳自己的界面状态（不进 store）：参考切换浮层、左栏收起、右栏标签
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useStudio } from "../store";
import type { RefTarget } from "./edit/RefSwitchPanel";
import type { RightTab } from "./edit/RightTabs";

interface UiState {
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

const Ctx = createContext<UiState | null>(null);

function pref(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* 隐私模式 */
  }
}

export function UiProvider({ children }: { children: ReactNode }) {
  const [refSwitch, setRefSwitch] = useState<UiState["refSwitch"]>(null);
  // v3.1：新键 ns.v3.railOpen（旧键 ns.v3.rail 默认展开，不再沿用）；默认收起
  const [railCollapsed, setRail] = useState(() => pref("ns.v3.railOpen", "0") !== "1");
  const [rightTab, setTab] = useState<RightTab>(() => {
    const q = new URLSearchParams(location.search).get("rtab");
    const v = q ?? pref("ns.v3.rtab", "prompt");
    return (["prompt", "versions", "rules", "advanced"].includes(v) ? v : "prompt") as RightTab;
  });
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 1440);
  useEffect(() => {
    const on = () => setNarrow(window.innerWidth <= 1440);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  const { canvasMode } = useStudio();
  const railMini = railCollapsed || (narrow && canvasMode === "edit");
  const openRefSwitch = useCallback((shotId: string, target: RefTarget) => setRefSwitch({ shotId, target }), []);
  const closeRefSwitch = useCallback(() => setRefSwitch(null), []);
  const setRailCollapsed = useCallback((v: boolean) => (setRail(v), save("ns.v3.railOpen", v ? "0" : "1")), []);
  const setRightTab = useCallback((t: RightTab) => (setTab(t), save("ns.v3.rtab", t)), []);
  return (
    <Ctx.Provider value={{ refSwitch, openRefSwitch, closeRefSwitch, railCollapsed, railMini, setRailCollapsed, rightTab, setRightTab }}>{children}</Ctx.Provider>
  );
}

export function useUi(): UiState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useUi 必须在 UiProvider 里");
  return v;
}
