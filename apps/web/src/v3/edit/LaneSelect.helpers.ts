// PW-019：从 LaneSelect.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { autoLane, type LaneInfo, type LanePick } from "./lanes";

/** 选中的道前面还有多少秒的活（自动 = 预计落到的那条） */
export function laneWait(value: LanePick, kind: "image" | "video", lanes: LaneInfo[] | null): number {
  const l = value === "auto" ? autoLane(kind, lanes) : (lanes ?? []).find((x) => String(x.gpu) === String(value));
  return l?.load_s ?? 0;
}
