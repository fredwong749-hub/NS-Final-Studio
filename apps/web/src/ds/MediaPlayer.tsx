// UIAUDIT（2026-10-31）：统一媒体播放器——图 / 视频 / 音频同一套预览、对比。
// 项目方原话：“声音模型那边，我需要监听它的播放……我连播放按钮都没有。”
// 契约：docs/uiaudit/UI_CONTRACT.md 列 P（预览 / 播放）、C（对比）、S（一键选定）。
//
// 用法：
//   <PlayButton src="/files/assets/voices/narrator_qag/ref.wav" label="试听" />          // 卡片上的 ▶（全站同一时间只响一个）
//   <AudioPlayer src={url} title="旁白 · QAg" />                                          // 带波形、可点波形跳转、显示时长
//   <AudioAB a={{src, label:"当前"}} b={{src, label:"候选"}} onPick={(k)=>…} />           // A/B 同位置切换（键盘 A / B / 空格）
//   <MediaView kind="image|video|audio" src={url} />                                       // 统一预览：图点开放大、视频可播、音频带波形
//   <MediaCompare kind="image|video|audio" a={{src,label}} b={{src,label}} onPick={…} />   // 并排 / 滑块（图）· 同步播放（视频）· A/B（音频）
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import "./media.css";
import { claim, fmt, loadPeaks } from "./MediaPlayer.helpers";

export type MediaKind = "image" | "video" | "audio";
export interface MediaSrc {
  src: string;
  label?: ReactNode;
  sub?: ReactNode;
}

function useMediaState(ref: React.RefObject<HTMLAudioElement | HTMLVideoElement | null>) {
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const on = () => {
      setT(el.currentTime);
      setDur(el.duration || 0);
      setPlaying(!el.paused);
    };
    const onErr = () => setErr("这段音频打不开（文件不在或格式不支持）");
    const evs = ["timeupdate", "durationchange", "loadedmetadata", "play", "pause", "ended", "seeked"];
    evs.forEach((e) => el.addEventListener(e, on));
    el.addEventListener("error", onErr);
    return () => {
      evs.forEach((e) => el.removeEventListener(e, on));
      el.removeEventListener("error", onErr);
    };
  }, [ref]);
  return { t, dur, playing, err };
}

// ---------------------------------------------------------------- ▶ 小按钮（卡片上用）
export function PlayButton({ src, label = "试听", size = "sm", title }: { src: string; label?: ReactNode; size?: "xs" | "sm" | "md"; title?: string }) {
  const ref = useRef<HTMLAudioElement>(null);
  const { t, dur, playing, err } = useMediaState(ref);
  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    const el = ref.current;
    if (!el) return;
    if (el.paused) {
      claim(el);
      void el.play().catch(() => undefined);
    } else el.pause();
  };
  const pct = dur ? (t / dur) * 100 : 0;
  return (
    <button type="button" className={`mp-play mp-${size}${playing ? " on" : ""}${err ? " bad" : ""}`} onClick={toggle} title={err ?? title ?? (playing ? "暂停" : "播放")} aria-label={playing ? "暂停" : "播放"}>
      <span className="mp-ico" aria-hidden>{playing ? "❚❚" : "▶"}</span>
      {label && <span className="mp-lbl">{label}</span>}
      {(playing || t > 0) && <span className="mp-time">{fmt(playing ? t : dur)}</span>}
      <span className="mp-bar" style={{ width: `${pct}%` }} aria-hidden />
      <audio ref={ref} src={src} preload="none" />
    </button>
  );
}

// ---------------------------------------------------------------- 音频播放器（波形 + 跳转）
export function AudioPlayer({ src, title, sub, wave = true, compact, extra }: { src: string; title?: ReactNode; sub?: ReactNode; wave?: boolean; compact?: boolean; extra?: ReactNode }) {
  const ref = useRef<HTMLAudioElement>(null);
  const { t, dur, playing, err } = useMediaState(ref);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  useEffect(() => {
    let alive = true;
    setPeaks(null);
    if (wave) void loadPeaks(src).then((p) => alive && setPeaks(p));
    return () => {
      alive = false;
    };
  }, [src, wave]);
  const toggle = () => {
    const el = ref.current;
    if (!el) return;
    if (el.paused) {
      claim(el);
      void el.play().catch(() => undefined);
    } else el.pause();
  };
  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el || !dur) return;
    const r = e.currentTarget.getBoundingClientRect();
    el.currentTime = ((e.clientX - r.left) / r.width) * dur;
    if (el.paused) {
      claim(el);
      void el.play().catch(() => undefined);
    }
  };
  const pct = dur ? t / dur : 0;
  return (
    <div className={`mp-audio${compact ? " compact" : ""}${err ? " bad" : ""}`}>
      <button type="button" className={`mp-big${playing ? " on" : ""}`} onClick={toggle} aria-label={playing ? "暂停" : "播放"}>
        {playing ? "❚❚" : "▶"}
      </button>
      <div className="mp-main">
        {(title || sub) && (
          <div className="mp-head">
            {title && <b>{title}</b>}
            {sub && <span className="ds-muted ds-small">{sub}</span>}
          </div>
        )}
        <div className="mp-wave" onClick={seek} role="slider" aria-label="播放进度" aria-valuemin={0} aria-valuemax={Math.round(dur)} aria-valuenow={Math.round(t)} tabIndex={0}
          onKeyDown={(e) => {
            const el = ref.current;
            if (!el) return;
            if (e.key === "ArrowRight") el.currentTime = Math.min(dur, el.currentTime + 2);
            if (e.key === "ArrowLeft") el.currentTime = Math.max(0, el.currentTime - 2);
            if (e.key === " ") (e.preventDefault(), toggle());
          }}>
          {peaks ? (
            peaks.map((v, i) => <i key={i} className={i / peaks.length <= pct ? "on" : ""} style={{ height: `${Math.max(6, v * 100)}%` }} />)
          ) : (
            <span className="mp-line"><span style={{ width: `${pct * 100}%` }} /></span>
          )}
        </div>
        <div className="mp-foot">
          <span className="mp-time">{fmt(t)} / {fmt(dur)}</span>
          {err && <span className="mp-err">{err}</span>}
          {extra}
        </div>
      </div>
      <audio ref={ref} src={src} preload="metadata" />
    </div>
  );
}

// ---------------------------------------------------------------- A/B 试听（同一位置切换）
export function AudioAB({ a, b, onPick, picked }: { a: MediaSrc; b: MediaSrc; onPick?: (k: "a" | "b") => void; picked?: "a" | "b" | null }) {
  const ra = useRef<HTMLAudioElement>(null);
  const rb = useRef<HTMLAudioElement>(null);
  const [side, setSide] = useState<"a" | "b">("a");
  const sa = useMediaState(ra);
  const sb = useMediaState(rb);
  const cur = side === "a" ? sa : sb;
  const el = () => (side === "a" ? ra.current : rb.current);
  const toggle = useCallback(() => {
    const e = side === "a" ? ra.current : rb.current;
    if (!e) return;
    if (e.paused) {
      claim(e);
      void e.play().catch(() => undefined);
    } else e.pause();
  }, [side]);
  const switchTo = useCallback(
    (k: "a" | "b") => {
      if (k === side) return;
      const from = side === "a" ? ra.current : rb.current;
      const to = k === "a" ? ra.current : rb.current;
      if (!from || !to) return;
      const was = !from.paused;
      to.currentTime = Math.min(from.currentTime, to.duration || from.currentTime);
      from.pause();
      setSide(k);
      if (was) {
        claim(to);
        void to.play().catch(() => undefined);
      }
    },
    [side],
  );
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "a" || e.key === "A") switchTo("a");
      if (e.key === "b" || e.key === "B") switchTo("b");
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [switchTo]);
  const seek = (ev: React.MouseEvent<HTMLDivElement>) => {
    const e = el();
    if (!e || !cur.dur) return;
    const r = ev.currentTarget.getBoundingClientRect();
    e.currentTime = ((ev.clientX - r.left) / r.width) * cur.dur;
  };
  return (
    <div className="mp-ab">
      <div className="mp-ab-row">
        <button type="button" className={`mp-big${cur.playing ? " on" : ""}`} onClick={toggle} aria-label={cur.playing ? "暂停" : "播放"}>
          {cur.playing ? "❚❚" : "▶"}
        </button>
        {(["a", "b"] as const).map((k) => {
          const m = k === "a" ? a : b;
          return (
            <button key={k} type="button" className={`mp-ab-side${side === k ? " on" : ""}${picked === k ? " picked" : ""}`} onClick={() => switchTo(k)} title={`切到 ${k.toUpperCase()}（键盘 ${k.toUpperCase()}），从同一位置接着播`}>
              <span className="mp-ab-k">{k.toUpperCase()}</span>
              <span className="mp-ab-l">{m.label ?? (k === "a" ? "当前" : "候选")}</span>
              {m.sub && <span className="ds-muted ds-small">{m.sub}</span>}
            </button>
          );
        })}
      </div>
      <div className="mp-wave mp-line-only" onClick={seek}>
        <span className="mp-line"><span style={{ width: `${cur.dur ? (cur.t / cur.dur) * 100 : 0}%` }} /></span>
      </div>
      <div className="mp-foot">
        <span className="mp-time">{side.toUpperCase()} · {fmt(cur.t)} / {fmt(cur.dur)}</span>
        {onPick && (
          <span className="mp-ab-pick">
            <button type="button" className={`ds-btn sm${picked === "a" ? " primary" : ""}`} onClick={() => onPick("a")}>用 A</button>
            <button type="button" className={`ds-btn sm${picked === "b" ? " primary" : ""}`} onClick={() => onPick("b")}>用 B</button>
          </span>
        )}
      </div>
      <audio ref={ra} src={a.src} preload="metadata" />
      <audio ref={rb} src={b.src} preload="metadata" />
    </div>
  );
}

// ---------------------------------------------------------------- 统一预览
export function MediaView({ kind, src, alt, title, sub, fit = "contain" }: { kind: MediaKind; src: string; alt?: string; title?: ReactNode; sub?: ReactNode; fit?: "contain" | "cover" }) {
  const [zoom, setZoom] = useState(false);
  if (kind === "audio") return <AudioPlayer src={src} title={title} sub={sub} />;
  if (kind === "video")
    return (
      <figure className="mp-fig">
        <video className="mp-video" src={src} controls preload="metadata" onPlay={(e) => claim(e.currentTarget)} />
        {title && <figcaption>{title}{sub && <span className="ds-muted ds-small"> · {sub}</span>}</figcaption>}
      </figure>
    );
  return (
    <figure className="mp-fig">
      <img className={`mp-img ${fit}`} src={src} alt={alt ?? ""} onClick={() => setZoom(true)} title="点开看大图" />
      {title && <figcaption>{title}{sub && <span className="ds-muted ds-small"> · {sub}</span>}</figcaption>}
      {zoom && <Lightbox src={src} onClose={() => setZoom(false)} />}
    </figure>
  );
}

export function Lightbox({ src, onClose }: { src: string; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="mp-lightbox" onClick={onClose} role="dialog" aria-label="大图">
      <img src={src} alt="" onClick={(e) => e.stopPropagation()} />
      <button type="button" className="ds-btn sm mp-close" onClick={onClose}>关闭 Esc</button>
    </div>
  );
}

// ---------------------------------------------------------------- 对比
export function MediaCompare({ kind, a, b, onPick, picked }: { kind: MediaKind; a: MediaSrc; b: MediaSrc; onPick?: (k: "a" | "b") => void; picked?: "a" | "b" | null }) {
  const [mode, setMode] = useState<"side" | "slide">("side");
  const [x, setX] = useState(50);
  const va = useRef<HTMLVideoElement>(null);
  const vb = useRef<HTMLVideoElement>(null);
  if (kind === "audio") return <AudioAB a={a} b={b} onPick={onPick} picked={picked} />;
  const sync = (ev: "play" | "pause" | "seeked") => {
    const A = va.current;
    const B = vb.current;
    if (!A || !B) return;
    if (ev === "play") void B.play().catch(() => undefined);
    if (ev === "pause") B.pause();
    if (ev === "seeked") B.currentTime = A.currentTime;
  };
  const pick = onPick && (
    <div className="mp-cmp-pick">
      <button type="button" className={`ds-btn sm${picked === "a" ? " primary" : ""}`} onClick={() => onPick("a")}>用左边</button>
      <button type="button" className={`ds-btn sm${picked === "b" ? " primary" : ""}`} onClick={() => onPick("b")}>用右边</button>
    </div>
  );
  if (kind === "image" && mode === "slide")
    return (
      <div className="mp-cmp">
        <CmpModes mode={mode} setMode={setMode} />
        <div className="mp-slide" onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setX(((e.clientX - r.left) / r.width) * 100); }}>
          <img src={b.src} alt="" />
          <img src={a.src} alt="" style={{ clipPath: `inset(0 ${100 - x}% 0 0)` }} />
          <span className="mp-slide-bar" style={{ left: `${x}%` }} />
          <span className="mp-tag l">{a.label ?? "A"}</span>
          <span className="mp-tag r">{b.label ?? "B"}</span>
        </div>
        {pick}
      </div>
    );
  return (
    <div className="mp-cmp">
      {kind === "image" && <CmpModes mode={mode} setMode={setMode} />}
      <div className="mp-cmp-grid">
        {[a, b].map((m, i) => (
          <figure key={i} className={`mp-fig${picked === (i ? "b" : "a") ? " picked" : ""}`}>
            {kind === "video" ? (
              <video ref={i ? vb : va} className="mp-video" src={m.src} controls={!i} muted={!!i} preload="metadata"
                onPlay={() => !i && sync("play")} onPause={() => !i && sync("pause")} onSeeked={() => !i && sync("seeked")} />
            ) : (
              <img className="mp-img contain" src={m.src} alt="" />
            )}
            <figcaption>{m.label ?? (i ? "B" : "A")}{m.sub && <span className="ds-muted ds-small"> · {m.sub}</span>}</figcaption>
          </figure>
        ))}
      </div>
      {pick}
    </div>
  );
}

function CmpModes({ mode, setMode }: { mode: "side" | "slide"; setMode: (m: "side" | "slide") => void }) {
  return (
    <div className="mp-modes" role="tablist">
      <button type="button" role="tab" aria-selected={mode === "side"} className={mode === "side" ? "on" : ""} onClick={() => setMode("side")}>并排</button>
      <button type="button" role="tab" aria-selected={mode === "slide"} className={mode === "slide" ? "on" : ""} onClick={() => setMode("slide")}>滑块</button>
    </div>
  );
}
