// fredw-92/W4a：v3 小部件——下拉 / 小窗、状态点、“为什么卡住”
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { DOT_LABEL, type Dot, type ShotStatus } from "./status";

/** 点按钮开一个小窗；点外面或 Esc 关闭 */
export function Pop({
  label,
  className = "",
  btnClass = "v3-btn",
  title,
  align = "left",
  children,
}: {
  label: ReactNode;
  className?: string;
  btnClass?: string;
  title?: string;
  align?: "left" | "right" | "up-right";
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), setOpen(false));
    window.addEventListener("mousedown", off);
    window.addEventListener("keydown", esc, true);
    return () => {
      window.removeEventListener("mousedown", off);
      window.removeEventListener("keydown", esc, true);
    };
  }, [open]);
  // UI-FIX 11-03（项目方 10:4x 截图：“一键出片·第 1 集”小窗右侧被截断）：所有小窗打开后按视口收边——
  // 超出右 / 左边就平移回来，超出底部就限高滚动；16px 边距（手机宽同样适用）。不靠每个调用方自己选 align
  const popRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = popRef.current;
    if (!open || !el) return;
    const fit = () => {
      el.style.transform = "";
      el.style.maxHeight = "";
      const r = el.getBoundingClientRect();
      const vw = document.documentElement.clientWidth || window.innerWidth;
      const vh = window.innerHeight;
      const G = 16;
      let dx = 0;
      if (r.right > vw - G) dx = vw - G - r.right;
      if (r.left + dx < G) dx = G - r.left;
      if (dx) el.style.transform = `translateX(${Math.round(dx)}px)`;
      if (r.top >= 0 && r.bottom > vh - G) {
        el.style.maxHeight = `${Math.max(160, Math.floor(vh - G - r.top))}px`;
        el.style.overflowY = "auto";
      }
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [open]);
  return (
    <div className={`v3-popwrap ${className}`} ref={ref} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      <button className={`${btnClass}${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)} title={title}>
        {label}
      </button>
      {open && <div ref={popRef} className={`v3-pop v3-pop-${align}`}>{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function StatusDot({ dot, title }: { dot: Dot; title?: string }) {
  return <i className={`v3-dot d-${dot}`} title={title ?? DOT_LABEL[dot]} />;
}

/** 状态胶囊 = 状态点 + 一句话；有卡点时胶囊本身可点，点开看“为什么卡住”（v3.1 §1.4：不再单独放链接） */
export function StatusLine({ st, why = true, align = "right" }: { st: ShotStatus; why?: boolean; align?: "left" | "right" }) {
  const body = (
    <>
      <StatusDot dot={st.dot} />
      <span className="v3-status-t">{st.text}</span>
    </>
  );
  if (!why || !st.why.length || st.dot === "green") return <span className={`v3-status s-${st.dot}`}>{body}</span>;
  return (
    <Pop label={<>{body}<i className="v3-status-q">?</i></>} btnClass={`v3-status s-${st.dot} click`} align={align} title="点开看为什么卡住（就绪清单、关口、过期原因）">
      {() => <WhyList items={st.why} />}
    </Pop>
  );
}

function WhyList({ items }: { items: ShotStatus["why"] }) {
  // UM-P0-01：只列你能处理的事；系统自己在处理的检查合成一行灰字
  const mine = items.filter((w) => !w.sys);
  const sys = items.length - mine.length;
  return (
    <div className="v3-why-pop">
      <b>{mine.length ? "要你处理" : "不用你处理"}</b>
      {mine.length > 0 && (
        <ul>
          {mine.map((w, i) => (
            <li key={i}>{w.text}</li>
          ))}
        </ul>
      )}
      {sys > 0 && <p className="v3-why-sys">系统检查中（{sys} 项，系统自己处理）</p>}
    </div>
  );
}

/** “为什么卡住”独立链接（兼容旧调用；v3 行内已改为点状态胶囊） */
export function WhyStuck({ items, align = "right" }: { items: ShotStatus["why"]; align?: "left" | "right" }) {
  return (
    <Pop label="为什么卡住？" btnClass="v3-why" align={align} title="就绪清单、关口阻塞、过期原因">
      {() => <WhyList items={items} />}
    </Pop>
  );
}
