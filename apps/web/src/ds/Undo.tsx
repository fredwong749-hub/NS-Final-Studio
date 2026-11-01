// 点选即生效 + 10 秒撤销（项目方 2026-10-31：“我选这个图按一下就可以了”）。
// 用法：showUndo（在 ds/Undo.helpers.ts）弹提示条；App 里挂一个 <UndoHost />。本文件只导出组件（PW-019）。
import { useEffect, useState } from "react";
import { emitUndo, removeUndo, subscribeUndo, undoItems } from "./Undo.helpers";

export function UndoHost() {
  const [, setN] = useState(0);
  useEffect(() => {
    const f = () => setN((n) => n + 1);
    const off = subscribeUndo(f);
    const t = window.setInterval(f, 500);
    return () => {
      off();
      window.clearInterval(t);
    };
  }, []);
  const items = undoItems();
  if (!items.length) return null;
  return (
    <div className="ds-undo-host" role="status" aria-live="polite">
      {items.map((it) => {
        const left = Math.max(0, Math.ceil((it.until - Date.now()) / 1000));
        return (
          <div key={it.id} className={`ds-undo ${it.state}`}>
            <span>{it.state === "undone" ? `已撤销：${it.text}` : it.state === "failed" ? `撤销没成功：${it.text}` : it.text}</span>
            {it.state === "live" && left > 0 && (
              <button
                className="ds-btn sm"
                onClick={async () => {
                  it.state = "undoing";
                  emitUndo();
                  try {
                    await it.undo();
                    it.state = "undone";
                  } catch {
                    it.state = "failed";
                  }
                  it.until = Date.now() + 3000;
                  emitUndo();
                  window.setTimeout(() => removeUndo(it.id), 3000);
                }}
              >
                撤销 {left}s
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
