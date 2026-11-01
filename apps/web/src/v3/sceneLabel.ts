// UIPIXEL：场景显示名（界面不显示 sk_office_night/plate.png 这种 id / 路径）。
// 名字来自资产库 /api/assets/scenes（整页共用一次请求）；资产库还没起名的，按 id 里的词拼一个中文名兜底。
import { useEffect, useState } from "react";
import { loadScenes, sceneName } from "./pages/scenes_api";
import { onLive } from "./live";

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

const WORD: Record<string, string> = {
  office: "办公室", night: "夜", day: "日", elevator: "电梯", closet: "衣帽间", dining: "餐厅", rental: "出租屋", entry: "玄关",
  taxi: "出租车", home: "家", kitchen: "厨房", studio: "工作室", alley: "街巷", ballroom: "酒会厅", apartment: "公寓", bedroom: "卧室",
  bathroom: "浴室", car: "车内", street: "街道", bar: "酒吧", hotel: "酒店", room: "房间", corridor: "走廊", lobby: "大堂", gu: "顾沉", chen: "", guchen: "顾沉",
};

/** id / 路径 → 场景 id（"sk_office_night/plate.png" → "sk_office_night"） */
export const sceneIdOf = (v: string) => v.replace(/\\/g, "/").split("/").find((p) => /^sk_/.test(p)) ?? v.replace(/\.(png|jpe?g|webp)$/i, "").split("/")[0];

/** 看起来像内部 id / 路径（不是给人看的名字） */
export const looksInternal = (v: string | null | undefined) => !!v && (/[/\\]|\.(png|jpe?g|webp|json)$/i.test(v) || /^[a-z0-9]+(_[a-z0-9]+)+$/i.test(v));

/** 同步取名（名字表还没到时先用兜底名） */
export function sceneLabel(v: string | null | undefined): string | null {
  if (!v) return null;
  if (!looksInternal(v)) return v;
  const id = sceneIdOf(v);
  if (!names?.size) void load();
  const hit = names?.get(id);
  if (hit && !looksInternal(hit)) return hit;
  const parts = id.replace(/^sk_/, "").split("_").map((w) => WORD[w.toLowerCase()] ?? null);
  const zh = parts.filter((x) => x !== null).join("");
  return zh && parts.every((x) => x !== null) ? zh : "未命名场景";
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
