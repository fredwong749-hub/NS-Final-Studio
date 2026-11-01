// UM-P0-01（项目方原话：“我没有确认按钮，也没有否定按钮……给我一个按钮来确定是否接受。”）
// 每个待审对象（首帧 / 尾帧 / 视频）一对明确按钮：
//   ✓ 用这张（视频：✓ 用这版）—— 一键生效，提示条 10 秒内撤销；
//   ✗ 不要 —— 小框：常用原因 chip + 可选一句话 + “不要并重出”（原因交给编辑逻辑层 /api/edits，系统按原因改出新的一版）/“只标记不要”。
// 首帧 / 尾帧“✓ 用这张”= 定稿这一版（撤销 = 取消定稿）；视频“✓ 用这版”= 通过（撤销 = 回到未审）。
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { editApi } from "../ds/editdel.api";
import { showUndo } from "../ds/Undo.helpers";
import { useStudio } from "../store";
import { setLock } from "./edit/actions";
import { reloadCandidates, epOf } from "./candidates";
import "./verdict.css";

export type VStage = "first" | "last" | "video";
const STAGE_KEY = { first: "image", last: "last", video: "video" } as const;
const NAME = { first: "首帧", last: "尾帧", video: "视频" } as const;
const REASONS: Record<VStage, string[]> = {
  first: ["脸不像", "手 / 手指不对", "衣服鞋子不对", "构图 / 景别不对", "表情不对", "太假 / 塑料感", "场景不对"],
  last: ["和首帧接不上", "脸不像", "手 / 手指不对", "动作结束状态不对", "太假 / 塑料感"],
  video: ["动作不自然", "脸变了", "手 / 手指崩", "镜头运动不对", "节奏太慢 / 太快", "声音不对"],
};

async function post(url: string, body?: unknown) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!r.ok) {
    let m = `HTTP ${r.status}`;
    try {
      const d = await r.json();
      if (d?.detail) m = String(d.detail);
    } catch {
      /* 非 JSON */
    }
    throw new Error(m);
  }
  return r.json();
}

export function Verdict({ shot, stage, n, size = "sm", auto, onAccept }: { shot: string; stage: VStage; n: number | null; size?: "sm" | "md"; auto?: boolean; onAccept?: () => Promise<unknown> }) {
  const st = useStudio();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const noRef = useRef<HTMLButtonElement>(null);
  // 关掉小框后焦点回到“✗ 不要”（和其它弹框一致）
  const closeBox = () => {
    setOpen(false);
    window.setTimeout(() => noRef.current?.focus(), 0);
  };
  if (n == null) return null;
  const nm = NAME[stage];
  const refresh = async (ids: string[]) => {
    reloadCandidates(epOf(shot));
    await st.refreshAfter(ids);
  };
  const accept = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    try {
      if (onAccept) await onAccept();
      else if (stage === "video") {
        await st.setReview([shot], "passed");
        showUndo(`已用 ${shot.split("-")[1]} 视频 #${n}`, async () => void (await st.setReview([shot], "unreviewed")));
      } else if (await setLock(shot, stage, n, true, () => undefined, refresh)) {
        showUndo(`已用 ${shot.split("-")[1]} ${nm} #${n}`, async () => void (await setLock(shot, stage, n, false, () => undefined, refresh)));
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className={`vd vd-${size}`} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      {auto ? (
        <span className="vd-auto" title="这一版通过了出图契约检查，按你的授权已自动采用；不满意点“✗ 不要”">
          已自动采用（可改）
        </span>
      ) : (
        <button type="button" className="vd-yes" disabled={busy} onClick={(e) => void accept(e)} title={`${stage === "video" ? "通过这版视频" : `定稿这张${nm}`}（10 秒内可撤销）`}>
          ✓ {stage === "video" ? "用这版" : "用这张"}
        </button>
      )}
      <button ref={noRef} type="button" className="vd-no" disabled={busy} onClick={() => setOpen(true)} title={`不要这${stage === "video" ? "版" : "张"}${nm}：选原因，可以直接按原因重出`}>
        ✗ 不要
      </button>
      {open && <RejectBox shot={shot} stage={stage} n={n} onClose={closeBox} onDone={refresh} />}
    </span>
  );
}

function RejectBox({ shot, stage, n, onClose, onDone }: { shot: string; stage: VStage; n: number; onClose: () => void; onDone: (ids: string[]) => Promise<void> }) {
  const st = useStudio();
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<null | "redo" | "mark">(null);
  const [err, setErr] = useState<string | null>(null);
  const nm = NAME[stage];
  const reason = [...picked, text.trim()].filter(Boolean).join("；");
  const box = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // Esc 关闭（捕获阶段先拦下，不连带退出精修）；Tab 只在小框里转（焦点陷阱）；打开时焦点进小框
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("button")?.focus();
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
  const mark = async () => {
    if (stage === "video") {
      await st.setReview([shot], "rejected", reason || "不要这版");
      return async () => void (await st.setReview([shot], "unreviewed"));
    }
    const r = (await post(`/api/shots/${shot}/takes/${STAGE_KEY[stage]}/${n}/reject`, { reason, by: "owner" })) as { was_active: boolean };
    return async () => {
      await post(`/api/shots/${shot}/takes/${STAGE_KEY[stage]}/${n}/unreject`, { restore_active: r.was_active });
      await onDone([shot]);
    };
  };
  const go = async (redo: boolean) => {
    setBusy(redo ? "redo" : "mark");
    setErr(null);
    try {
      const undo = await mark();
      if (redo)
        await editApi.create({ type: stage === "video" ? "video" : "image", id: `take:${shot}/${STAGE_KEY[stage]}/${n}`, feedback: reason || `不要这${stage === "video" ? "版" : "张"}${nm}，重出`, by: "owner" });
      await onDone([shot]);
      showUndo(redo ? `已标不要并按原因重出 ${shot.split("-")[1]} ${nm}` : `已标不要 ${shot.split("-")[1]} ${nm} #${n}`, undo);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return createPortal(
    <div className="vd-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="dialog" aria-modal="true" aria-label={`不要这${nm}`}>
      <div ref={box} className="vd-box" onClick={(e) => e.stopPropagation()}>
        <b>
          不要 {shot.split("-")[1]} {nm} #{n}：哪里不对？
        </b>
        <div className="vd-chips">
          {REASONS[stage].map((r) => (
            <button key={r} type="button" className={picked.includes(r) ? "on" : ""} onClick={() => setPicked((p) => (p.includes(r) ? p.filter((x) => x !== r) : [...p, r]))}>
              {r}
            </button>
          ))}
        </div>
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="可以再说一句（选填）" />
        {err && <p className="vd-err">{err}</p>}
        <div className="vd-btns">
          <button type="button" className="vd-redo" disabled={!!busy} onClick={() => void go(true)} title="标记不要，并把原因交给系统按原因改出新的一版">
            {busy === "redo" ? "提交中…" : "不要并重出"}
          </button>
          <button type="button" className="vd-mark" disabled={!!busy} onClick={() => void go(false)} title="只标记不要，先不重出">
            {busy === "mark" ? "…" : "只标记不要"}
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
