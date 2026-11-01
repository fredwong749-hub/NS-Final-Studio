// PW-019：从 RefBar.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { useEffect, useState } from "react";
import { apiV1, isNotReady, opt, type CharRefState, type ShotRefsV1 } from "../api_v1";
import { useLookInfo } from "../looks";
import { sceneLabel } from "../sceneLabel";

export type Load = { data: ShotRefsV1 | null; notReady: boolean; error: string | null; reload: () => void };

// F2：应用参考后通知所有参考条 / 面板重读（原来参考条只在换镜时读一次，应用后仍显示旧形象、没有“本镜改过”角标）
export const refsSubs = new Set<() => void>();

export const bumpShotRefs = () => refsSubs.forEach((f) => f());

export function useShotRefs(shot: string): Load {
  const [st, setSt] = useState<Omit<Load, "reload">>({ data: null, notReady: false, error: null });
  const [k, setK] = useState(0);
  useEffect(() => {
    const f = () => setK((x) => x + 1);
    refsSubs.add(f);
    return () => void refsSubs.delete(f);
  }, []);
  useEffect(() => {
    let dead = false;
    apiV1.shotRefs(shot).then(
      (data) => !dead && setSt({ data, notReady: false, error: null }),
      (e) => !dead && setSt({ data: null, notReady: isNotReady(e), error: isNotReady(e) ? null : (e as Error).message }),
    );
    return () => {
      dead = true;
    };
  }, [shot, k]);
  return { ...st, reload: () => setK((x) => x + 1) };
}

export const SRC_TAG: Record<string, string> = { shot: "本镜改过", scene: "本场改过" };

export const imgOf = (c: CharRefState) => {
  const im = c.effective?.images?.[0];
  return typeof im === "string" ? im : im?.url ?? null;
};

/** fredw-92/UXF5（审查 #31）：参考卡上的形象图 / 名字与资产页同一个解析（v3/looks.ts）：形象自己的图，没有就是角色主图 */
export function useRefLook(c: CharRefState | null | undefined) {
  const fallback = c ? (c.options?.looks ?? []).map(opt).find((o) => o.id === c.effective?.look)?.name ?? c.effective?.look_name ?? null : null;
  const info = useLookInfo(c?.id, c?.effective?.look, fallback);
  return { ...info, url: info.url ?? (c ? imgOf(c) : null) };
}

/** 旧写法（没读到资产目录时的退路） */
export const lookName = (c: CharRefState) => {
  const l = (c.options?.looks ?? []).map(opt).find((o) => o.id === c.effective?.look);
  const nm = c.effective?.look_name ?? l?.name;
  return nm || l?.letter ? `形象 ${l?.letter ?? ""} ${nm ?? ""}`.replace(/\s+/g, " ").trim() : c.effective?.look ?? "集默认";
};

export const sceneEff = (s: ShotRefsV1["scene"]) => {
  const e = s?.effective;
  if (!e) return { name: "无底图", url: null as string | null, id: null as string | null };
  if (typeof e === "string") return { name: e === "none" ? "不用底图" : sceneLabel(e) ?? e, url: null, id: e };
  const id = e.plate_id ?? e.plate ?? e.id ?? null;
  // UIPIXEL：不显示 sk_xxx/plate.png 这种 id / 路径，显示场景名
  return { name: id === "none" ? "不用底图" : sceneLabel(e.name ?? id) ?? "无底图", url: e.url ?? null, id };
};
