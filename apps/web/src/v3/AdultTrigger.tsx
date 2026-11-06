// L-128 / L-210 成人镜“本人触发”：只有登录的项目方本人看得到按钮；点“出这一集的成人镜 / 出这一镜”→ 一键确认 → 才开始出。
// 只显示文字（镜号、秒数、状态），不显示图、不显示画面描述。系统自己永远不出成人镜。
import { useState } from "react";
import { useMe } from "../projects/AuthGate.helpers";
import { fmtSecs, triggerAdult, useAdult, type AdultEp } from "./AdultTrigger.helpers";
import "./adult.css";

function ConfirmBtn({ label, ask, onGo, small }: { label: string; ask: string; onGo: () => Promise<void>; small?: boolean }) {
  const [step, setStep] = useState<"idle" | "ask" | "busy">("idle");
  const [err, setErr] = useState<string | null>(null);
  if (step === "idle")
    return (
      <span className="adt-act">
        <button type="button" className={small ? "adt-btn adt-sm" : "adt-btn"} onClick={() => (setErr(null), setStep("ask"))}>
          {label}
        </button>
        {err ? <span className="adt-err" role="alert">{err}</span> : null}
      </span>
    );
  return (
    <span className="adt-act adt-ask">
      <span>{ask}</span>
      <button
        type="button"
        className="adt-btn adt-go"
        disabled={step === "busy"}
        onClick={() => {
          setStep("busy");
          onGo().then(
            () => setStep("idle"),
            (e: Error) => (setErr(e.message), setStep("idle")),
          );
        }}
      >
        {step === "busy" ? "正在记下…" : "确认"}
      </button>
      <button type="button" className="adt-link" disabled={step === "busy"} onClick={() => setStep("idle")}>
        取消
      </button>
    </span>
  );
}

function EpBlock({ e, open }: { e: AdultEp; open?: boolean }) {
  const [show, setShow] = useState(!!open);
  const total = e.shots.length;
  return (
    <div className="adt-ep">
      <div className="adt-eph">
        <b>第 {e.ep} 集</b>
        <span className="adt-m">
          成人镜 {total} 镜 · 等你点 {e.counts.waiting} · 已点 {total - e.counts.waiting} · 已出好 {e.counts.done}
        </span>
        {e.waiting > 0 ? (
          <ConfirmBtn label={`出这一集的成人镜（${e.waiting}）`} ask={`出第 ${e.ep} 集还没出的 ${e.waiting} 个成人镜？`} onGo={() => triggerAdult({ episode: e.ep })} />
        ) : null}
        <button type="button" className="adt-link" aria-expanded={show} onClick={() => setShow((v) => !v)}>
          {show ? "收起 ▾" : "逐镜 ▸"}
        </button>
      </div>
      {show ? (
        <ul className="adt-shots">
          {e.shots.map((s) => (
            <li key={s.shot} className={`adt-shot st-${s.state}`}>
              <span className="mono">{s.shot}</span>
              <span className="adt-m">{fmtSecs(s.seconds)}</span>
              <span className="adt-st">{s.state_word}</span>
              {s.state === "waiting" ? <ConfirmBtn small label="出这一镜" ask={`出 ${s.shot}？`} onGo={() => triggerAdult({ objects: [s.shot] })} /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** 全剧总览每集集头：本集有成人镜才出现（只给登录的项目方本人） */
export function AdultEpButton({ ep }: { ep: number }) {
  const { me } = useMe();
  const d = useAdult();
  const [open, setOpen] = useState(false);
  const e = d?.episodes.find((x) => x.ep === ep);
  if (me?.role !== "owner" || !d?.can_trigger || !e) return null;
  return (
    <span className="adt-hdr">
      <button type="button" className="adt-btn adt-sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        title="成人镜只在你点了之后才出（系统不会自己出）">
        {e.waiting ? `出这一集的成人镜（${e.waiting}）` : `成人镜 ${e.shots.length} 镜已点`}
      </button>
      {open ? (
        <div className="adt-pop">
          <EpBlock e={e} open />
        </div>
      ) : null}
    </span>
  );
}

/** 待办页：还有没点的成人镜就列出来（只给登录的项目方本人） */
export function AdultQueuePanel() {
  const { me } = useMe();
  const d = useAdult();
  if (me?.role !== "owner" || !d?.can_trigger || !d.episodes.length) return null;
  const eps = d.episodes.filter((e) => e.shots.some((s) => s.state !== "done"));
  if (!eps.length) return null;
  return (
    <section className="adt-panel" aria-label="成人镜">
      <h2>成人镜 · 只在你点了之后才出{d.waiting ? `（等你点 ${d.waiting}）` : ""}</h2>
      <p className="adt-m">系统不会自己出这些镜头。点“出这一集的成人镜”或逐镜“出这一镜”，确认后才开始；这里只列镜号和状态。</p>
      {eps.map((e) => (
        <EpBlock key={e.ep} e={e} />
      ))}
    </section>
  );
}
