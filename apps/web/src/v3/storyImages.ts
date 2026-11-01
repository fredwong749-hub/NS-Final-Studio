// UIRSI：写作 / 出图线（IMGGEN）产出的新图（data/pipeline/runs/<id>/images/），在登记成 take 之前先显示。
// 后端 GET /api/story-images（services/api/ns_api/story_runs.py）；接口没上线或没有图时返回空，不影响页面。
import { useEffect, useState } from "react";

export type StoryImg = { url: string; path: string; kind: "first" | "last" | "sheet" | "other"; mtime: number; thumb?: string; look?: string; seed?: number };
export type StoryImages = { run: string | null; by_shot: Record<string, StoryImg[]>; chars: Record<string, StoryImg[]>; count: number; picks?: Record<string, Record<string, { path: string; at: string }>> };

const EMPTY: StoryImages = { run: null, by_shot: {}, chars: {}, count: 0 };
// DATAALIGN（K-DATA-001）：缓存按运行分开（以前全站一份：剧本页看 A 剧时显示的是“最近有图的运行”的同号镜头图）。
// run 不传 = 后端默认“当前画布剧本自己的运行”。
const caches = new Map<string, { at: number; p: Promise<StoryImages> }>();
export function loadStoryImages(force = false, delayMs = 0, run?: string | null): Promise<StoryImages> {
  const k = run ?? "";
  const cache = caches.get(k);
  if (force || !cache || Date.now() - cache.at > 60000) {
    const url = run ? `/api/story-images?run=${encodeURIComponent(run)}` : "/api/story-images";
    const c = { at: Date.now(), p: new Promise((r) => setTimeout(r, cache ? 0 : delayMs)).then(() => fetch(url)).then((r) => (r.ok ? r.json() : EMPTY), () => EMPTY) };
    caches.set(k, c);
    return c.p;
  }
  return cache.p;
}
/** delayMs：画布格子里用（首屏之后再取，W-02）；新建剧本 / 资产中心要立刻用，不延迟。run：只看这一次写作运行的图 */
export function useStoryImages(delayMs = 0, run?: string | null): StoryImages {
  const [v, setV] = useState<StoryImages>(EMPTY);
  useEffect(() => {
    let alive = true;
    setV(EMPTY);
    void loadStoryImages(false, delayMs, run).then((x) => alive && setV(x));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);
  return v;
}
/** 某镜某格的新图（首帧 / 尾帧），没有就 null */
export const storyFrame = (im: StoryImages, shot: string, stage: "image" | "last") =>
  im.by_shot[shot]?.find((x) => x.kind === (stage === "image" ? "first" : "last")) ?? (stage === "image" ? im.by_shot[shot]?.find((x) => x.kind === "other") : undefined) ?? null;
