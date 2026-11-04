import { useSyncExternalStore } from "react";
import type { JobLite } from "./GenState.helpers";

export type GenItem = {
  id: string; // job id
  where: string; // 位置键：sheet:A / face / item:<id> / shot:ep01-S3:first …
  title: string;
  summary?: string; // 它理解的改动（prompt_rewrite 的 zh_summary）
  at: number;
};

let items: GenItem[] = [];
let jobs: JobLite[] = [];
let tick = 0;
const subs = new Set<() => void>();
export const emit = () => {
  tick++;
  subs.forEach((f) => f());
};
const sub = (f: () => void) => (subs.add(f), () => subs.delete(f));
let snap = { items, jobs, tick };
const get = () => {
  if (snap.tick !== tick) snap = { items, jobs, tick };
  return snap;
};

export function trackGen(it: Omit<GenItem, "at">) {
  if (!it.id || items.some((x) => x.id === it.id)) return;
  items = [...items, { ...it, at: Date.now() }];
  emit();
}
export function untrackGen(id: string) {
  items = items.filter((x) => x.id !== id);
  emit();
}
export function useGen() {
  return useSyncExternalStore(sub, get);
}
/** 测试用：清空 */
export function _resetGen() {
  items = [];
  jobs = [];
  emit();
}

export const getItems = () => items;
export const getJobs = () => jobs;
export function setJobs(all: JobLite[]) {
  jobs = all;
  emit();
}

/** 别名：任务轮询状态（和 trackGen 配套） */
export const useJobs = useGen;
