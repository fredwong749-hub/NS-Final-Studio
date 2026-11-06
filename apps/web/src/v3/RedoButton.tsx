// 每镜一个“重做”（L-215/216）：一次点击直接重出，不弹确认；只有文字，不带图（成人镜也安全）。
import { useState } from "react";
import "./regen.css";
import { useStudio } from "../store";
import { REDO_WORD, redoShot, type RedoKind } from "./redo";

export function RedoButton({ shot, kind, short = false, onDone }: { shot: string; kind: RedoKind; short?: boolean; onDone?: () => void }) {
  const st = useStudio();
  const [busy, setBusy] = useState(false);
  const word = REDO_WORD[kind];
  const click = async (ev: React.MouseEvent) => {
    ev.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      const res = await redoShot(shot, kind);
      st.notify(res.say || `${shot} ${word}已交给系统重做`);
      onDone?.();
    } catch (e) {
      st.notify(`${shot} ${word}重做没交出去：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="v3-btn sm redo-btn" disabled={busy} onClick={click} title={`${shot} 的${word}直接重做一版（不用确认）`}>
      {busy ? "交给系统…" : short ? word : `重做${word}`}
    </button>
  );
}
