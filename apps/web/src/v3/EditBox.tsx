// L-123（项目方 16:4x：“去掉这个逻辑，我不太喜欢什么要这个，不要那个”）：全站只有正向动作——“用这张”和“修改”。
// 这是“修改”的小框：写一句话（可点建议 chip 追加）→ 生成；“换个种子再来”= 同样的话换个随机种子。
// 以前“不要 + 原因”喂学习环的数据，现在由这一句话（feedback）提供：调用方照旧写 /api/edits，口径不变。
// 编辑器本体（框选 / 版本带 / 对比）是 P1 第 3 项；本框是它出来之前所有“修改”按钮共用的入口，之后同一入口换成抽屉。
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./verdict.css";

export function EditBox({
  title,
  suggestions,
  seedLabel = "换个种子再来",
  onSubmit,
  onClose,
}: {
  title: string;
  suggestions: string[];
  seedLabel?: string;
  /** text 为空 = 只换种子；返回的 Promise 失败会显示在框里 */
  onSubmit: (text: string, chips: string[]) => Promise<void>;
  onClose: () => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<null | "go" | "seed">(null);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("textarea")?.focus();
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !box.current) return;
      const f = [...box.current.querySelectorAll<HTMLElement>("button, textarea")].filter((x) => !(x as HTMLButtonElement).disabled);
      if (!f.length) return;
      const i = f.indexOf(document.activeElement as HTMLElement);
      if (e.shiftKey && i <= 0) (e.preventDefault(), f[f.length - 1].focus());
      else if (!e.shiftKey && i === f.length - 1) (e.preventDefault(), f[0].focus());
    };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, []);
  const sentence = [...picked, text.trim()].filter(Boolean).join("；");
  const go = async (seed: boolean) => {
    setBusy(seed ? "seed" : "go");
    setErr(null);
    try {
      await onSubmit(seed ? "" : sentence, seed ? [] : picked);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return createPortal(
    <div className="vd-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="dialog" aria-modal="true" aria-label={title}>
      <div ref={box} className="vd-box" onClick={(e) => e.stopPropagation()}>
        <b>{title}</b>
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="写一句话：想改成什么样" />
        <div className="vd-chips">
          {suggestions.map((r) => (
            <button key={r} type="button" className={picked.includes(r) ? "on" : ""} onClick={() => setPicked((p) => (p.includes(r) ? p.filter((x) => x !== r) : [...p, r]))}>
              {r}
            </button>
          ))}
        </div>
        {err && <p className="vd-err">{err}</p>}
        <div className="vd-btns">
          <button type="button" className="vd-redo" disabled={!!busy || !sentence} onClick={() => void go(false)}>
            {busy === "go" ? "提交中…" : "生成"}
          </button>
          <button type="button" className="vd-mark" disabled={!!busy} onClick={() => void go(true)}>
            {busy === "seed" ? "…" : seedLabel}
          </button>
          <button type="button" className="vd-cancel" onClick={onClose}>
            算了
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
