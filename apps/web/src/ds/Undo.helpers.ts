// 从 Undo.tsx 挪出来的撤销提示条状态与 showUndo（PW-019：.tsx 只导出组件，热更新才不会整页重载）。
// 用法：showUndo("已选定 阿岚 造型 A", async () => { …撤销… })；App 里挂一个 <UndoHost />（ds/Undo.tsx）。

export type UndoItem = { id: number; text: string; undo: () => Promise<void>; until: number; state: "live" | "undoing" | "undone" | "failed" };
let items: UndoItem[] = [];
let seq = 0;
const subs = new Set<() => void>();
export const emitUndo = () => subs.forEach((f) => f());
export const undoItems = () => items;
export const subscribeUndo = (f: () => void) => {
  subs.add(f);
  return () => void subs.delete(f);
};
export const removeUndo = (id: number) => {
  items = items.filter((x) => x.id !== id);
  emitUndo();
};

export function showUndo(text: string, undo: () => Promise<void>, ms = 10000) {
  const it: UndoItem = { id: ++seq, text, undo, until: Date.now() + ms, state: "live" };
  items = [...items.slice(-2), it];
  emitUndo();
  window.setTimeout(() => {
    items = items.filter((x) => x.id !== it.id || x.state === "undoing");
    emitUndo();
  }, ms + 300);
}
