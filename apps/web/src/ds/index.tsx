// UX5 设计系统组件（D_workflow_visual §4.5）。样式在 ds.css，只引用 theme.css 的 token。
// 新代码一律用这里的组件；旧 .btn / .v3-btn / .v3e-btn 在 ds.css 里统一了形状和禁用态，逐步替换。
import { useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ASSET_STATUS, useEsc, useFocusTrap, type AssetStatus } from "./helpers";
// PW-019：hook / 常量 / 函数在 ./helpers（组件文件只导出组件）；类型照旧可从这里拿
export type { AssetStatus } from "./helpers";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "ok";
type Size = "xs" | "sm" | "md";

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  wide,
  solid,
  className = "",
  why,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: boolean; wide?: boolean; solid?: boolean; why?: string }) {
  // 禁用时必须写原因（why → title），D10
  const title = rest.disabled && why ? why : rest.title;
  const cls = ["ds-btn", variant !== "secondary" && variant, size !== "md" && size, icon && "icon", wide && "wide", solid && "solid", className].filter(Boolean).join(" ");
  return (
    <button type="button" {...rest} title={title} className={cls}>
      {children}
    </button>
  );
}

export type Tone = "neutral" | "accent" | "ok" | "warn" | "bad" | "busy" | "info" | "stale" | "void" | "on-media";
export function Tag({ tone = "neutral", dot, pill, size, title, children, className = "" }: { tone?: Tone; dot?: boolean; pill?: boolean; size?: "xs" | "s"; title?: string; children: ReactNode; className?: string }) {
  const cls = ["ds-tag", tone !== "neutral" && tone, pill && "pill", size === "s" && "s", className].filter(Boolean).join(" ");
  return (
    <span className={cls} title={title}>
      {dot && <i aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Card({ title, sub, extra, tight, className = "", children }: { title?: ReactNode; sub?: ReactNode; extra?: ReactNode; tight?: boolean; className?: string; children?: ReactNode }) {
  return (
    <section className={`ds-card${tight ? " tight" : ""} ${className}`}>
      {(title || extra) && (
        <header className="ds-card-h">
          {title && <h3>{title}</h3>}
          {sub && <span className="sub">{sub}</span>}
          <span className="grow" />
          {extra}
        </header>
      )}
      {children}
    </section>
  );
}

export function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: [T, ReactNode][]; onChange: (v: T) => void; label?: string }) {
  return (
    <div className="ds-seg" role="tablist" aria-label={label}>
      {options.map(([v, l]) => (
        <button key={v} role="tab" aria-selected={v === value} className={v === value ? "on" : ""} onClick={() => onChange(v)}>
          {l}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: [T, ReactNode, (number | string)?][]; onChange: (v: T) => void }) {
  return (
    <div className="ds-tabs" role="tablist">
      {options.map(([v, l, n]) => (
        <button key={v} role="tab" aria-selected={v === value} className={v === value ? "on" : ""} onClick={() => onChange(v)}>
          {l}
          {n != null && <small>{n}</small>}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon = "○", title, sub, action }: { icon?: ReactNode; title: ReactNode; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="ds-empty">
      <span className="ic" aria-hidden="true">{icon}</span>
      <b>{title}</b>
      {sub && <p>{sub}</p>}
      {action}
    </div>
  );
}

/** 已知形状用骨架；未知形状用转圈 + “正在读…”（全站只有这两种加载文案） */
export function Loading({ text = "正在读…" }: { text?: string }) {
  return <span className="ds-spin" role="status">{text}</span>;
}
export function Skel({ w = "100%", h = 16, r }: { w?: number | string; h?: number | string; r?: string }) {
  return <span className="ds-skel" style={{ display: "block", width: w, height: h, borderRadius: r }} aria-hidden="true" />;
}

/** 读不到：一句人话 + 重试 + 折叠的技术细节（不直接给用户看“502 Bad Gateway”，D4） */
export function LoadError({ what, err, retry, hint }: { what: string; err?: string | null; retry?: () => void; hint?: ReactNode }) {
  const notReady = !!err && /404|没有这个接口|Not Found/i.test(err);
  const down = !!err && /502|503|504|Failed to fetch|NetworkError|ECONNREFUSED|网络不通/i.test(err);
  const human = notReady ? `${what}暂时读不到：后台还没有这项功能（等 API 重启后自动出现）` : down ? `${what}暂时读不到：后台服务没响应` : `${what}没读到`;
  return (
    <div className="ds-loaderr" role="alert">
      <b>{human}</b>
      {hint && <span className="ds-muted">{hint}</span>}
      {retry && (
        <Button size="sm" onClick={retry}>
          重试
        </Button>
      )}
      {err && (
        <details>
          <summary>技术细节</summary>
          <code>{err}</code>
        </details>
      )}
    </div>
  );
}

export function Drawer({ title, onClose, wide, head, foot, children }: { title: ReactNode; onClose: () => void; wide?: boolean; head?: ReactNode; foot?: ReactNode; children: ReactNode }) {
  useEsc(onClose);
  const box = useRef<HTMLElement>(null);
  useFocusTrap(box);
  // UIPIXEL：同 Modal，挂到 body 上，不受所在容器的 overflow / transform / container 影响
  return createPortal(
    <>
      <div className="ds-scrim" onClick={onClose} />
      <aside ref={box} tabIndex={-1} className={`ds-drawer${wide ? " w-l" : ""}`} role="dialog" aria-modal="true">
        <header className="ds-drawer-h">
          <h2>{title}</h2>
          {head}
          <Button variant="ghost" size="sm" icon onClick={onClose} aria-label="关闭" title="关闭（Esc）">
            ✕
          </Button>
        </header>
        <div className="ds-drawer-b">{children}</div>
        {foot && <footer className="ds-drawer-f">{foot}</footer>}
      </aside>
    </>,
    document.body,
  );
}

export function Modal({ title, sub, onClose, wide, foot, children }: { title: ReactNode; sub?: ReactNode; onClose: () => void; wide?: boolean; foot?: ReactNode; children?: ReactNode }) {
  useEsc(onClose);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  // UIPIXEL：挂到 body 上（以前就地渲染：放在格子底栏 / 带 overflow:hidden、transform、container、backdrop-filter 的容器里时，
  // fixed 定位以那个容器为准，确认框被缩在 70px 的格子里、还被裁掉）。React 事件照常沿组件树冒泡。
  return createPortal(
    <div className="ds-modal-wrap" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} tabIndex={-1} className={`ds-modal${wide ? " w-l" : ""}`} role="dialog" aria-modal="true">
        <header className="ds-modal-h">
          <h2>{title}</h2>
          {sub && <p>{sub}</p>}
        </header>
        {children && <div className="ds-modal-b">{children}</div>}
        {foot && <footer className="ds-modal-f">{foot}</footer>}
      </div>
    </div>,
    document.body,
  );
}

/* ---------------------------------------------------------------- 资产统一状态（A §3.3） */

export function StatusTag({ s, extra, onMedia }: { s: AssetStatus; extra?: string; onMedia?: boolean }) {
  const d = ASSET_STATUS[s];
  return (
    <Tag tone={onMedia && s === "draft" ? "on-media" : d.tone} dot pill title={d.tip + (extra ? `\n${extra}` : "")}>
      {d.label}
      {extra && s === "final" ? ` · ${extra}` : ""}
    </Tag>
  );
}

