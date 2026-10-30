import { useMemo } from "react";
import { useStudio } from "./store";
import type { EpisodeLooks } from "./types";
import type { LookTag } from "./util";

/** 本集每个镜头的造型标签；继承 / 覆盖 / 换装点 / 冲突都由后端解析好 */
export function episodeTags(ep: EpisodeLooks | undefined): Record<string, LookTag[]> {
  const out: Record<string, LookTag[]> = {};
  if (!ep) return out;
  for (const sh of ep.shots)
    out[sh.shot_id] = Object.entries(sh.characters).map(([ch, v]) => ({
      character: ch,
      label: v.label,
      lookId: v.look_id,
      override: v.has_override,
      changed: v.changed_from_prev,
      changedFields: v.changed_fields,
      conflicts: v.conflicts,
    }));
  return out;
}

export function useEpisodeTags(n: number): Record<string, LookTag[]> {
  const { epLooks } = useStudio();
  const ep = epLooks[n];
  return useMemo(() => episodeTags(ep), [ep]);
}
