// UIPIXEL：图 / 视频格子的统一底栏与顶栏（项目方 11-01 截图：“渲染中 / 过期·需重出 / ✎ 改 / 🗑”四样各自 absolute 叠在格子底边，互相压住）。
// 规则（knowledge/rules/ui.yaml K-UI-P10，docs/uiaudit/UI_CONTRACT.md §格子叠放）：
//   一个角落只放一个定位容器；容器里是 flex 行 + gap，谁也不 absolute；
//   状态牌单行省略号 + title（看得到全文）；格子窄了（< 180px）操作收进 ⋯；按钮和状态一个都不删。
import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

const stop = (e: MouseEvent) => e.stopPropagation();

export function TileBar({ status, job, actions, className = "" }: {
  /** 状态牌（过期·需重出 / 已定稿 / 坏图 / 提示 …），可多个，单行省略 */
  status?: ReactNode;
  /** 进行中的任务条（渲染中 / 排队），单独一行在最上面 */
  job?: ReactNode;
  /** 操作按钮（✎ 改 / 🗑 …）：宽格直接排开，窄格收进 ⋯ */
  actions?: ReactNode;
  className?: string;
}) {
  if (!status && !job && !actions) return null;
  return (
    <div className={`ds-tilebar ${className}`}>
      {job ? <div className="ds-tilebar-job">{job}</div> : null}
      {status || actions ? (
        <div className="ds-tilebar-row">
          <span className="ds-tilebar-st">{status}</span>
          {actions ? (
            <>
              <span className="ds-tilebar-acts" onClick={stop} onMouseDown={stop}>
                {actions}
              </span>
              <MoreMenu>{actions}</MoreMenu>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** 窄格的 ⋯ 菜单：点菜单外面或按 Esc 收起（菜单里的按钮自己打开的弹框不受影响） */
function MoreMenu({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = () => {
      if (ref.current) ref.current.open = false;
    };
    // 菜单里的按钮打开的确认框 / 弹层（在别处渲染）里点、按 Esc，不算“点到菜单外面”：关掉确认框后焦点还能回到菜单里的按钮
    const inDialog = (t: EventTarget | null) => t instanceof Element && !!t.closest("[role=dialog], [role=alertdialog], .ds-modal-wrap, .ds-drawer, .ds-scrim");
    const dialogOpen = () => !!document.querySelector("[role=dialog], [role=alertdialog], .ds-modal-wrap");
    const down = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !inDialog(e.target)) close();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !dialogOpen()) {
        close();
        ref.current?.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("keydown", key, true);
    };
  }, [open]);
  return (
    <details ref={ref} className="ds-tilebar-more" onClick={stop} onMouseDown={stop} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary title="更多操作" aria-label="更多操作" aria-expanded={open}>⋯</summary>
      <span className="ds-tilebar-menu">{children}</span>
    </details>
  );
}

/** 左上角标签组（“首帧 #4”、运动质检 …）：一列排开，换行也不会压到下一个 */
export function TileTop({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`ds-tiletop ${className}`}>{children}</div>;
}
