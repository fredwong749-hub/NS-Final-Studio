import { useEffect, useMemo, useRef, useState } from "react";
import { useStudio } from "../store";
import { epCode, joinReason, REJECT_CODES } from "../util";
import { useEsc, useFocusTrap } from "../ds/helpers";

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  // UIMASTER（批量打回框等）：和 ds 弹框同一套键盘行为——Esc 关、Tab 留在框里、关掉后焦点回到打开它的按钮
  useEsc(onClose);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} tabIndex={-1} className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <b>{title}</b>
          <button className="btn-mini" onClick={onClose}>
            关闭 Esc
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog() {
  const { confirmReq, setConfirmReq } = useStudio();
  const [busy, setBusy] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  // 封板修复（项目方 2026-10-30）：项目方确认勾选框，每个新确认框都从未勾选开始
  const [ownerOk, setOwnerOk] = useState(false);
  useEffect(() => setOwnerOk(false), [confirmReq]);
  useEffect(() => btn.current?.focus(), [confirmReq]);
  if (!confirmReq) return null;
  const req = confirmReq;
  // 只关闭自己：操作里又弹出新的确认框（如“批量重出”→ 批量确认）时不能把新框也关掉
  const close = () => setConfirmReq((cur) => (cur === req ? null : cur));
  const run = async (fn: () => void | Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
      close();
    }
  };
  return (
    <Modal title={confirmReq.title} onClose={close}>
      <div className="modal-body">
        {confirmReq.lines.map((l, i) => (
          <div key={i}>{l}</div>
        ))}
        {confirmReq.ownerCheck && (
          <label className="or-confirm" style={{ display: "inline-flex", gap: 6, alignItems: "center", cursor: "pointer", marginTop: 8 }}>
            <input type="checkbox" checked={ownerOk} onChange={(e) => setOwnerOk(e.target.checked)} /> {confirmReq.ownerCheck}
          </label>
        )}
      </div>
      <div className="modal-foot">
        <button className="btn" onClick={close}>
          {confirmReq.cancelLabel ?? "取消"}
        </button>
        {confirmReq.secondary && (
          <button className="btn" disabled={busy} onClick={() => void run(confirmReq.secondary!.onClick)}>
            {confirmReq.secondary.label}
          </button>
        )}
        <button
          ref={btn}
          className={`btn ${confirmReq.danger ? "bad" : "primary"}`}
          disabled={busy || (!!confirmReq.ownerCheck && !ownerOk)}
          onClick={() => void run(confirmReq.onConfirm)}
        >
          {confirmReq.confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

export function RejectDialog({ onDone }: { onDone?: () => void }) {
  const { rejectFor, setRejectFor, setReview } = useStudio();
  const [code, setCode] = useState<string>("画面");
  const [note, setNote] = useState("");
  useEffect(() => setNote(""), [rejectFor]);
  if (!rejectFor) return null;
  const close = () => setRejectFor(null);
  const submit = async () => {
    const ok = await setReview(rejectFor, "rejected", joinReason(code, note));
    close();
    if (ok) onDone?.();
  };
  return (
    <Modal title={`打回 ${rejectFor.length === 1 ? rejectFor[0] : `${rejectFor.length} 镜`}`} onClose={close}>
      <div className="modal-body">
        <div className="reason-codes">
          {REJECT_CODES.map((c, i) => (
            <button key={c} className={`btn${code === c ? " primary" : ""}`} onClick={() => setCode(c)}>
              {i + 1} {c}
            </button>
          ))}
        </div>
        <input
          autoFocus
          className="grow"
          placeholder="备注（可选），Enter 提交"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
            else if (!note && /^[1-7]$/.test(e.key)) {
              e.preventDefault();
              setCode(REJECT_CODES[Number(e.key) - 1]);
            }
          }}
        />
      </div>
      <div className="modal-foot">
        <button className="btn" onClick={close}>
          取消
        </button>
        <button className="btn bad" onClick={() => void submit()}>
          打回：{code}
        </button>
      </div>
    </Modal>
  );
}

const KEYS: [string, string][] = [
  // fredw-92/UXF1：与 keymap.ts 同步（审查 #14 / #15）
  ["↑ / ↓ · ← / →", "上一镜 / 下一镜（跨集自动换集）"],
  ["[ / ] · PgUp / PgDn", "上一集 / 下一集"],
  ["G · Ctrl+K", "跳转到集或镜头"],
  ["1 / 2", "总览 / 集视图"],
  ["Enter · 双击行", "进精修"],
  ["L", "审片 / 精修切换"],
  ["Esc", "只关最上面的菜单 / 弹窗；什么都没开时清除多选，再按回审片"],
  ["空格", "播放 / 暂停（松开时触发）"],
  ["I / E / V", "出首帧 / 出尾帧 / 出视频（需确认）"],
  ["F · 点图片", "全屏查看首帧 | 尾帧（←/→ 翻版本，Tab 切首/尾，Enter 设为当前，↑/↓ 换镜）"],
  ["C", "全屏 A/B 对比（当前 vs 候选版本）"],
  ["4 / 5", "资产中心 / 成片"],
  ["1 / G", "换集 / 搜索镜头"],
  ["N", "新建剧本（故事提纲 → 自动写）"],
  ["A / E", "用这张 / 修改（审片行和精修里一样）"],
  ["R", "串播审片（J / K 移动，A 用这版）"],
  ["Ctrl+C / Ctrl+V", "复制 / 粘贴编辑字段（运镜、表情、负面词、种子）"],
  ["Ctrl+Z / Ctrl+Shift+Z", "撤销 / 重做编辑"],
  ["Ctrl/Shift+点击", "多选 / 连续选择"],
  ["?", "本表"],
];

export function HelpDialog() {
  const { helpOpen, setHelpOpen } = useStudio();
  if (!helpOpen) return null;
  return (
    <Modal title="快捷键" onClose={() => setHelpOpen(false)}>
      <table className="keys">
        <tbody>
          {KEYS.map(([k, v]) => (
            <tr key={k}>
              <td>
                <kbd>{k}</kbd>
              </td>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="muted small pad">焦点在输入框里时快捷键不生效（Ctrl+S 除外）；按住不放不会重复触发。</div>
    </Modal>
  );
}

export function Palette() {
  const { paletteOpen, setPaletteOpen, episodes, select, gotoEpisode } = useStudio();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  useEffect(() => {
    setQ("");
    setI(0);
  }, [paletteOpen]);
  const items = useMemo(() => {
    if (!episodes) return [];
    const t = q.trim().toLowerCase();
    const out: { key: string; label: string; go: () => void }[] = [];
    for (const e of episodes) {
      const code = epCode(e.number);
      if (!t || code.includes(t) || String(e.number) === t || e.title.includes(q.trim()))
        out.push({ key: code, label: `${code} · ${e.title}`, go: () => gotoEpisode(e.number) });
      for (const s of e.shots)
        if (t && s.id.toLowerCase().includes(t))
          out.push({ key: s.id, label: `${s.id} · ${s.img_summary}`, go: () => select(s.id) });
    }
    return out.slice(0, 30);
  }, [episodes, q, gotoEpisode, select]);
  if (!paletteOpen) return null;
  const close = () => setPaletteOpen(false);
  const run = (k: number) => {
    items[k]?.go();
    close();
  };
  return (
    <Modal title="跳转" onClose={close}>
      <input
        autoFocus
        className="palette-input"
        placeholder="集号（12 / ep12）、标题或镜头（ep12-S3）"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setI(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") (e.preventDefault(), setI((x) => Math.min(items.length - 1, x + 1)));
          else if (e.key === "ArrowUp") (e.preventDefault(), setI((x) => Math.max(0, x - 1)));
          else if (e.key === "Enter") run(i);
          else if (e.key === "Escape") close();
        }}
      />
      <ul className="palette-list">
        {items.map((it, k) => (
          <li key={it.key} className={k === i ? "on" : ""} onMouseEnter={() => setI(k)} onClick={() => run(k)}>
            {it.label}
          </li>
        ))}
      </ul>
    </Modal>
  );
}

export function Toasts() {
  const { toasts } = useStudio();
  return (
    // 总调度 11-01：提示条只是告诉你一句话、没有可点的东西——整层不接鼠标（pointer-events: none），
    // 盖在按钮上也不挡点击（以前右下角的“通过 / 打回 / ×”被提示条挡住点不到）；读屏照常读（role=status）
    <div className="toasts" style={{ pointerEvents: "none" }} role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} style={{ pointerEvents: "none" }}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
