// UIPIXEL：场景显示名（界面不显示 sk_office_night/plate.png 这种 id / 路径）。
// 名字只来自当前剧的场景登记 /api/assets/scenes（整页共用一次请求）；登记里没有的显示“场景未登记：<id>”。
// UIFIX-F 11-03：去掉了按 id 单词拼中文名的 WORD 表（V1 词汇，拼出过“办公室夜”）；纯函数在 sceneLabel.pure.ts，有 node 测试。
import { useEffect, useState } from "react";
import { loadScenes, sceneName } from "./pages/scenes_api";
import { onLive } from "./live";
import { resolveSceneLabel } from "./sceneLabel.pure";

export { sceneIdOf, looksInternal, plateMatchesScene, sopSceneId, unregisteredLabel } from "./sceneLabel.pure";

let names: Map<string, string> | null = null;
let loading: Promise<Map<string, string>> | null = null;
const subs = new Set<() => void>();

let retryT: number | null = null;
let liveHooked = false;
function load(): Promise<Map<string, string>> {
  if (!liveHooked) {
    liveHooked = true;
    // 后台重启时取不到名字：实时通道重连（hello）后再取一次
    onLive((e) => {
      if (e.type === "hello" && !names?.size) { if (retryT != null) { window.clearTimeout(retryT); retryT = null; } void load(); }
    });
  }
  if (retryT != null) return Promise.resolve(names ?? new Map()); // 等重试中：不在每次渲染时都去取（后台断开时不刷请求）
  if (!loading)
    loading = loadScenes()
      .then((ss) => new Map(ss.map((s) => [s.scene_id, sceneName(s)] as [string, string])))
      .catch(() => new Map<string, string>())
      .then((m) => {
        names = m.size ? m : names ?? m;
        if (!m.size) {
          loading = null; // 取失败 / 空表：15 秒后再取
          if (retryT == null) retryT = window.setTimeout(() => ((retryT = null), void load()), 15000);
        }
        subs.forEach((f) => f());
        return names ?? m;
      });
  return loading ?? Promise.resolve(names ?? new Map());
}

/** 同步取名（名字表还没到时显示“场景未登记：id”，到了会重渲染） */
export function sceneLabel(v: string | null | undefined): string | null {
  if (!v) return null;
  if (!names?.size) void load();
  return resolveSceneLabel(v, names);
}

/** 组件里用：名字表到了会重渲染 */
export function useSceneLabel(v: string | null | undefined): string | null {
  const [, tick] = useState(0);
  useEffect(() => {
    if (names?.size) return;
    const f = () => tick((x) => x + 1);
    subs.add(f);
    void load();
    return () => void subs.delete(f);
  }, []);
  return sceneLabel(v);
}
