// PW-019：从 VideoBase.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import { useEffect, useState } from "react";
import { apiV1, type VideoBaseInfo } from "../api_v1";

export const DEFAULT_VIDEO_BASE = "official_turbo";

export const FALLBACK: VideoBaseInfo[] = [
  { id: "official_turbo", label: "官方 8 步（当前）", short: "官方8步", steps: 8, steps_adjustable: true },
  {
    id: "pika_flex",
    label: "Pika H3 Flex（6 步·试验）",
    short: "Pika Flex",
    steps: 6,
    steps_adjustable: false,
    experimental: true,
    hint: "换成 Pika 的蒸馏 LoRA：6 步、lcm 采样、官方 sigma 表；步数和 LoRA 强度固定，不能改",
  },
];

export let cache: VideoBaseInfo[] | null = null;
/** 配置里的默认基底（GET /api/video-bases 的 default；项目方 2026-11-01 起 = pika_flex） */
export let configDefault: string = "pika_flex";

/** 给人看的说法（PF：项目方“改成容易懂”）——不出现 LoRA / 步数 / sigma 这类内部词 */
export const PLAIN: Record<string, { name: string; what: string }> = {
  pika_flex: { name: "Pika Flex", what: "出得快，首尾两张定稿图都用上" },
  official_turbo: { name: "官方快速版", what: "以前的老方法，首尾两张定稿图都用上" },
  official_base: { name: "官方完整版", what: "只用首帧，动作更完整，但每个镜头要慢 3 倍左右" },
};

export function useVideoBases(): VideoBaseInfo[] {
  const [list, setList] = useState<VideoBaseInfo[]>(cache ?? FALLBACK);
  useEffect(() => {
    if (cache) return;
    let dead = false;
    apiV1
      .videoBases()
      .then((r) => {
        if (dead || !r.bases?.length) return;
        cache = r.bases;
        if (r.default) configDefault = r.default;
        setList(r.bases);
      })
      .catch(() => {});
    return () => {
      dead = true;
    };
  }, []);
  return list;
}

/** 新出一版时默认选哪个：沿用这一版的；还没有视频版本 → 配置默认 */
export function initialBase(p: { base?: string | null } | null | undefined, hasTake: boolean): string {
  return hasTake ? takeBaseId(p) : configDefault;
}

/** 这一版的基底 id（老版本 params 里没有 base = 官方现链） */
export function takeBaseId(p: { base?: string | null } | null | undefined): string {
  return p?.base || DEFAULT_VIDEO_BASE;
}

export function baseFixed(list: VideoBaseInfo[], id: string): boolean {
  const b = list.find((x) => x.id === id);
  return b ? b.steps_adjustable === false : id !== DEFAULT_VIDEO_BASE;
}
