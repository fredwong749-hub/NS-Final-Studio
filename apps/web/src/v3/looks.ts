// fredw-92/UXF5（审查 #31 / #39）：形象的字母 / 名字 / 图——资产页、本镜参考条、参考切换面板共用这一处，
// 不再各写一套（以前面板写“形象 默认 · 无图”，资产页写“形象 A · 默认”并显示角色主图）。
// 数据：GET /api/assets/characters（资产页同一份）；整页只读一次，资产改过后 bumpLooks() 重读。
import { useEffect, useSyncExternalStore } from "react";
import { api } from "../api";
import type { CharacterAssets, LookView } from "../types";

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

type LookLike = { id: string; label?: string | null; name?: string | null; preview_url?: string | null; reference_urls?: (string | null)[] };
type CharLike = { id?: string; looks: LookLike[]; hero?: { url: string | null } | null; face_url?: string | null };

/** 形象字母：有 label 用 label，否则按顺序 A/B/C（资产页卡片、排期、镜头角标、参考条一律用它） */
export function lookLetter(ch: CharLike, lk: LookLike | undefined | null): string {
  if (!lk) return "?";
  if (lk.label) return lk.label;
  const i = ch.looks.findIndex((x) => x.id === lk.id);
  return LETTERS[i] ?? "?";
}

/** “形象 A · 通勤”；名字和 id 一样（没起名）时只写字母 */
export function lookTitle(ch: CharLike, lk: LookLike): string {
  const nm = (lk.name || "").trim();
  return `形象 ${lookLetter(ch, lk)}${nm && nm !== lk.id ? ` · ${nm}` : ""}`;
}

/** 形象的图：形象自己的预览 / 参考图；都没有时退回角色主图（own=false，界面上标“角色主图”） */
export function lookImage(ch: CharLike, lk: LookLike | undefined | null): { url: string | null; own: boolean } {
  const own = lk ? lk.preview_url ?? lk.reference_urls?.find(Boolean) ?? null : null;
  if (own) return { url: own, own: true };
  return { url: ch.hero?.url ?? ch.face_url ?? null, own: false };
}

/** 一次拿齐：字母 + 标题 + 图 */
export function resolveLook(ch: CharLike, lookId: string | null | undefined) {
  const lk = ch.looks.find((x) => x.id === lookId) ?? null;
  const img = lookImage(ch, lk);
  return { look: lk, letter: lookLetter(ch, lk), title: lk ? lookTitle(ch, lk) : "未指定形象", url: img.url, own: img.own };
}

// ---------------------------------------------------------------- 资产目录缓存（参考条 / 面板用）

let cat: Map<string, CharacterAssets> | null = null;
let loading: Promise<void> | null = null;
let rev = 0;
const subs = new Set<() => void>();
const emit = () => {
  rev++;
  subs.forEach((f) => f());
};
function load() {
  if (loading) return loading;
  loading = api.assets
    .list()
    .then((c) => {
      cat = new Map(c.characters.map((x) => [x.id, x]));
      emit();
    })
    .catch(() => undefined)
    .finally(() => {
      loading = null;
    });
  return loading;
}
/** 资产页改过形象 / 加过图后调用：参考条、面板重读 */
export const bumpLooks = () => void load();

/** 资产目录里的某个角色（没读到时 null，读到后自动刷新） */
export function useCharAssets(id: string | null | undefined): CharacterAssets | null {
  useSyncExternalStore(
    (f) => (subs.add(f), () => void subs.delete(f)),
    () => rev,
  );
  useEffect(() => {
    if (!cat) void load();
  }, []);
  return id && cat ? cat.get(id) ?? null : null;
}

/** 参考条 / 面板：某角色当前形象的显示信息（目录没读到时退回 /refs 给的名字，不显示“无图”） */
export function useLookInfo(charId: string | null | undefined, lookId: string | null | undefined, fallbackName?: string | null) {
  const ch = useCharAssets(charId);
  if (!ch) return { letter: "", title: fallbackName ? `形象 ${fallbackName}` : "集默认", url: null as string | null, own: false, ready: false };
  return { ...resolveLook(ch, lookId), ready: true };
}

export type { LookView };
