import type { ShotSummary } from "../types";
import { seamState } from "./Seam.helpers";

export function SeamMarker({ left, right, onOpen }: { left: ShotSummary; right: ShotSummary; onOpen: () => void }) {
  const { state, title } = seamState(left, right);
  return (
    <button className={`seam v seam-${state}`} title={`${left.id} ⟶ ${right.id}\n${title}\n点击打开接缝对比`} onClick={onOpen}>
      <span className="seam-line" />
    </button>
  );
}
