// BGM10（2026-11-01）：声音页「配乐」——本集当前用的配乐 + 其他通过闸门的候选：▶ 试听、「用这一版」一键换用、撤销。
// 只列通过自动闸门（无人声 / 无削波 / 无长静音 / 时长够）的候选；没过的只报个数。后端 /api/music/{ep}/candidates、/choose。
import { useEffect, useRef, useState } from "react";
import { Button, Tag } from "../../ds";
import { claim } from "../../ds/MediaPlayer.helpers";
import { chooseBgm, getBgmCands, plainReason, type BgmCand, type BgmCands } from "./sound_api";

const pct = (v?: number) => (v == null ? "—" : v.toFixed(2));

function CandRow({ c, busy, onUse }: { c: BgmCand; busy: boolean; onUse: () => void }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const on = () => setPlaying(!el.paused);
    ["play", "pause", "ended"].forEach((e) => el.addEventListener(e, on));
    return () => ["play", "pause", "ended"].forEach((e) => el.removeEventListener(e, on));
  }, []);
  const toggle = () => {
    const el = ref.current;
    if (!el) return;
    if (el.paused) (claim(el), void el.play().catch(() => undefined));
    else el.pause();
  };
  const m = c.metrics;
  const tags = Object.keys(m.tags ?? {}).slice(0, 3).join(" · ");
  return (
    <li className={`bgmc-row${c.chosen ? " on" : ""}`} data-cand={c.id}>
      <button type="button" className={`mp-big${playing ? " on" : ""}`} onClick={toggle} aria-label={playing ? `暂停候选 ${c.id}` : `试听候选 ${c.id}`}>
        {playing ? "❚❚" : "▶"}
      </button>
      <div className="bgmc-meta">
        <b>{c.id}</b> {c.chosen && <Tag tone="ok" pill size="xs">现在在用</Tag>}
        <span
          className="ds-muted ds-small"
          title={`听感贴合度 clap ${pct(m.clap)} · 起伏走向贴合度 energy_r ${pct(m.energy_r)} · 人声残留 vocal_rel_db ${m.vocal_rel_db ?? "—"} dB · 速度 ${m.tempo_bpm ?? "—"}`}
        >
          {" "}第 {c.round} 轮 · 约 {m.tempo_bpm != null ? Math.round(m.tempo_bpm) : "—"} 拍/分{tags ? ` · 听出来有 ${tags}` : ""}
        </span>
        {c.flags.length > 0 && (
          <span className="ds-muted ds-small" title={c.flags.join("；")}>
            {" "}· 提示：{c.flags.map((f, i) => c.flags_plain?.[i] || plainReason(f) || "有一项自动提示，原文见悬停").join("；")}
          </span>
        )}
      </div>
      {!c.chosen && (
        <Button size="sm" variant="primary" disabled={busy} why="正在换用" onClick={onUse} title="整集配乐换成这一条（成片下次合成时生效，可撤销）">
          用这一版
        </Button>
      )}
      <audio ref={ref} src={c.url} preload="none" />
    </li>
  );
}

export function BgmCandidates({ ep, onSwitched }: { ep: number; onSwitched?: () => void }) {
  const [d, setD] = useState<BgmCands | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setD(null);
    getBgmCands(ep).then((x) => alive && setD(x), () => alive && setD(null));
    return () => {
      alive = false;
    };
  }, [ep]);
  if (!d || !d.candidates.length) return null;
  const act = (body: { id?: string; undo?: boolean }) => {
    setBusy(true);
    setErr(null);
    chooseBgm(ep, body).then(
      (x) => {
        setD(x);
        setMsg(body.undo ? "已换回上一条" : `已换成 ${body.id}`);
        onSwitched?.();
      },
      (e: Error) => setErr(e.message),
    ).finally(() => setBusy(false));
  };
  const ch = d.chosen;
  return (
    <section className="bgmc" aria-label="配乐候选">
      <header className="bgmc-head">
        <b>配乐候选（{d.candidates.length} 条通过自动检查）</b>
        {d.hidden_failed > 0 && <span className="ds-muted ds-small"> · 另有 {d.hidden_failed} 条没过检查（有人声 / 静音 / 太短），不列出</span>}
        {d.needs_owner_listen && <Tag tone="warn" pill size="xs">🟡 审听模型没选，系统按度量兜底，请听一下</Tag>}
      </header>
      {ch && (
        <p className="ds-muted ds-small bgmc-why" title={[ch.reason, ch.reason_evidence].filter(Boolean).join("\n依据：")}>
          现在用 <b>{ch.id}</b>（{ch.by === "review_llm" ? "审听模型选" : ch.by === "fallback_metrics" ? "系统按度量兜底" : ch.by}）：{ch.reason_plain || plainReason(ch.reason) || "理由见悬停原文"}
          {ch.previous && (
            <button type="button" className="v3p-link" disabled={busy} onClick={() => act({ undo: true })}>
              撤销，换回 {ch.previous}
            </button>
          )}
        </p>
      )}
      <ol className="bgmc-list">
        {d.candidates.map((c) => (
          <CandRow key={c.id} c={c} busy={busy} onUse={() => act({ id: c.id })} />
        ))}
      </ol>
      {msg && <p className="ds-small" role="status">{msg}</p>}
      {err && <p className="mp-err" role="alert">{err}</p>}
    </section>
  );
}
