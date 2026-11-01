// UIMASTER UM-P0-02（项目方原话：“我没有确认按钮，也没有否定按钮……给我一个按钮来确定是否接受。”）
// 资产中心每个待审对象一对明确按钮：“✓ 用这张”（一键生效，外面给 10 秒撤销）+ “✗ 不要”（小框：常用原因 + 一句话 +
// “不要并重出” / “只标记不要”）。已经是当前的：显示“当前”+“✗ 不要”。
// “不要”：记到 /api/asset-rejects（不删文件、不动当前选择）；原因同时交给编辑逻辑层 /api/edits（只标记 = dry_run 只出计划；重出 = 执行）。
import { useState } from "react";
import { createPortal } from "react-dom";
import { Button, Modal } from "../../ds";
import "./verdict.css";

export type RejectKind = "face" | "sheet" | "scene_plate" | "item_image";
const REASONS: Record<RejectKind, string[]> = {
  face: ["不像本人", "脸型不对", "妆太浓", "表情不对", "太假 / 塑料感", "画质差"],
  sheet: ["衣服不对", "鞋不对", "饰品不对", "身材比例不对", "脸不像", "画质差"],
  scene_plate: ["不像剧本里的地方", "光线不对", "太空 / 太乱", "有人影", "画质差"],
  item_image: ["不是这件", "颜色不对", "角度不好", "背景太乱", "画质差"],
};

export type Rejected = { reasons: string[]; note: string } | null | undefined;

async function postReject(body: Record<string, unknown>) {
  const r = await fetch("/api/asset-rejects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `HTTP ${r.status}`);
}

/** 原因交给编辑逻辑层（失败不挡“不要”本身） */
function toEdits(file: string, feedback: string, redo: boolean) {
  void fetch("/api/edits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "image", id: `file:${file}`, feedback, dry_run: !redo }),
  }).catch(() => undefined);
}

export function Verdict({
  kind,
  file,
  label,
  current,
  rejected,
  cid,
  busy,
  onUse,
  onChanged,
  notify,
}: {
  kind: RejectKind;
  file: string;
  label: string;
  current: boolean;
  rejected?: Rejected;
  cid?: string;
  busy?: boolean;
  /** 不给 = 这类对象没有“用这张”（例如单品附图） */
  onUse?: () => void;
  onChanged?: () => void;
  notify?: (text: string, undo?: () => Promise<unknown>, err?: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="vd">
      {current ? (
        <span className="vd-cur">✓ 当前</span>
      ) : onUse ? (
        <button className="vd-use" disabled={busy} onClick={onUse} title={`用这张作为${label}（10 秒内可撤销）`}>
          ✓ 用这张
        </button>
      ) : null}
      {rejected ? (
        <button
          className="vd-no on"
          title={`已标记不要：${[...rejected.reasons, rejected.note].filter(Boolean).join("、") || "没写原因"}（点一下撤销）`}
          onClick={() =>
            void postReject({ kind, file, cid, undo: true }).then(
              () => (notify?.("已撤销“不要”"), onChanged?.()),
              (e) => notify?.(`没撤销成功：${(e as Error).message}`, undefined, true),
            )
          }
        >
          ✗ 已标不要
        </button>
      ) : (
        <button className="vd-no" disabled={busy} onClick={() => setOpen(true)} title="不要这张：选原因，可以顺便重出">
          ✗ 不要
        </button>
      )}
      {open && <RejectDialog kind={kind} file={file} label={label} cid={cid} onClose={() => setOpen(false)} onDone={(redo) => (setOpen(false), notify?.(redo ? "已标记不要，并按原因重出一版（出好后会出现在候选里）" : "已标记不要", () => postReject({ kind, file, cid, undo: true }).then(() => onChanged?.())), onChanged?.())} notifyErr={(t) => notify?.(t, undefined, true)} />}
    </div>
  );
}

function RejectDialog({ kind, file, label, cid, onClose, onDone, notifyErr }: { kind: RejectKind; file: string; label: string; cid?: string; onClose: () => void; onDone: (redo: boolean) => void; notifyErr: (t: string) => void }) {
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async (redo: boolean) => {
    setBusy(true);
    try {
      const reasons = [...sel];
      await postReject({ kind, file, cid, reasons, note, redo });
      const fb = `不要这张${label}${reasons.length ? `：${reasons.join("、")}` : ""}${note.trim() ? `。${note.trim()}` : ""}${redo ? "。请按这些原因重出一版。" : ""}`;
      toEdits(file, fb, redo);
      onDone(redo);
    } catch (e) {
      notifyErr(`没记上：${(e as Error).message}。数据没改动，可以再试一次`);
    } finally {
      setBusy(false);
    }
  };
  return createPortal(
    <Modal
      title={`不要这张${label}`}
      sub="选一下原因（可多选），也可以补一句话。图不会被删，只标成“不要”；随时能撤销。"
      onClose={onClose}
      foot={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => void go(false)}>
            只标记不要
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => void go(true)}>
            不要并重出
          </Button>
        </>
      }
    >
      <div className="vd-chips" role="group" aria-label="原因">
        {REASONS[kind].map((r) => (
          <button key={r} className={sel.has(r) ? "on" : ""} aria-pressed={sel.has(r)} onClick={() => setSel((s) => (s.has(r) ? new Set([...s].filter((x) => x !== r)) : new Set([...s, r])))}>
            {r}
          </button>
        ))}
      </div>
      <input className="ds-input vd-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="一句话（可不填），例如：头发再长一点" aria-label="补一句话" />
    </Modal>,
    document.body,
  );
}
