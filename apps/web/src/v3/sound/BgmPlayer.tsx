// UIRSI（B4，UI_CONTRACT §1.4「配乐 BGM」）：整集播放 + 波形 + 镜头分段 + 提示点；点任一镜从那一镜开始放。
import { useEffect, useRef, useState } from "react";
import { claim, fmt, loadPeaks } from "../../ds/MediaPlayer.helpers";
import { cueText, cueWord, type Music } from "./sound_api";
import { BgmCandidates } from "./BgmCandidates";
import "./sound.css";

export function BgmPlayer({ m, focusShot }: { m: Music; focusShot?: string | null }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(m.duration_s ?? 0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  // BGM10：换用候选后取新地址（带 ?v=修改时间），波形和播放都跟着换
  const [src, setSrc] = useState(m.url);
  useEffect(() => setSrc(m.url), [m.url]);
  const reload = () => void fetch(`/api/music/${m.episode}`).then((r) => (r.ok ? r.json() : null)).then((x: Music | null) => x?.url && setSrc(x.url));
  useEffect(() => {
    let alive = true;
    setPeaks(null);
    void loadPeaks(src, 360).then((p) => alive && setPeaks(p));
    return () => {
      alive = false;
    };
  }, [src]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const on = () => {
      setT(el.currentTime);
      if (el.duration) setDur(el.duration);
      setPlaying(!el.paused);
    };
    const bad = () => setErr("配乐文件打不开");
    const evs = ["timeupdate", "durationchange", "loadedmetadata", "play", "pause", "ended", "seeked"];
    evs.forEach((e) => el.addEventListener(e, on));
    el.addEventListener("error", bad);
    return () => {
      evs.forEach((e) => el.removeEventListener(e, on));
      el.removeEventListener("error", bad);
    };
  }, []);
  const total = dur || m.duration_s || 1;
  const playAt = (s: number) => {
    const el = ref.current;
    if (!el) return;
    el.currentTime = Math.max(0, Math.min(total - 0.05, s));
    claim(el);
    void el.play().catch(() => undefined);
  };
  const toggle = () => {
    const el = ref.current;
    if (!el) return;
    if (el.paused) (claim(el), void el.play().catch(() => undefined));
    else el.pause();
  };
  // 从画布带过来的镜头：进页就停在那一镜开头（不自动出声）
  useEffect(() => {
    const s = m.shots.find((x) => x.shot === focusShot);
    if (s && ref.current) ref.current.currentTime = s.start_s;
  }, [focusShot, m.shots]);
  const pct = (s: number) => `${(Math.max(0, s) / total) * 100}%`;
  const cur = [...m.shots].reverse().find((s) => t >= s.start_s - 0.01);
  const cues = m.cues.filter((c) => c.start_s != null);
  return (
    <div className={`bgm${err ? " bad" : ""}`}>
      <div className="bgm-top">
        <button type="button" className={`mp-big${playing ? " on" : ""}`} onClick={toggle} aria-label={playing ? "暂停" : "播放"}>
          {playing ? "❚❚" : "▶"}
        </button>
        <div className="bgm-meta">
          <b>第 {m.episode} 集配乐</b>
          <span className="ds-muted ds-small">
            {fmt(t)} / {fmt(total)}
            {cur ? ` · 正在第 ${cur.index} 镜` : ""} · {m.shots.length} 镜 · {cues.length} 个提示点
          </span>
          {err && <span className="mp-err">{err}</span>}
        </div>
      </div>
      <div
        className="bgm-wave"
        role="slider"
        tabIndex={0}
        aria-label="配乐进度（点哪里从哪里放）"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(t)}
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          playAt(((e.clientX - r.left) / r.width) * total);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") playAt(t + 5);
          if (e.key === "ArrowLeft") playAt(t - 5);
          if (e.key === " ") (e.preventDefault(), toggle());
        }}
      >
        <div className="bgm-bars" aria-hidden>
          {peaks ? peaks.map((v, i) => <i key={i} className={(i + 0.5) / peaks.length <= t / total ? "on" : ""} style={{ height: `${Math.max(4, v * 100)}%` }} />) : <span className="bgm-noline" />}
        </div>
        {cues.map((c, i) => (
          <span key={i} className={`bgm-cue a-${c.action ?? "x"}`} style={{ left: pct(c.start_s!) }} title={`第 ${c.shot ?? "?"} 镜 · ${cueWord(c.action)}：${cueText(c.text)}`} />
        ))}
        <span className="bgm-head" style={{ left: pct(t) }} aria-hidden />
      </div>
      <div className="bgm-shots" aria-label="按镜头跳">
        {m.shots.map((s) => (
          <button
            key={s.shot}
            type="button"
            className={`bgm-seg${cur?.shot === s.shot ? " on" : ""}${focusShot === s.shot ? " focus" : ""}`}
            style={{ left: pct(s.start_s), width: pct(s.dur_s ?? 0) }}
            onClick={() => playAt(s.start_s)}
            title={`从第 ${s.index} 镜开始放（${fmt(s.start_s)}）`}
          >
            镜 {s.index}
          </button>
        ))}
      </div>
      {cues.length > 0 && (
        <ol className="bgm-cues">
          {cues.map((c, i) => (
            <li key={i}>
              <button type="button" className="v3p-link" onClick={() => playAt(c.start_s!)} title="从这个提示点开始放">
                ▶ {fmt(c.start_s!)}
              </button>
              <span className={`bgm-cue-tag a-${c.action ?? "x"}`}>{cueWord(c.action)}</span>
              <span className="ds-muted">第 {c.shot ?? "?"} 镜</span>
              <span className="bgm-cue-text">{cueText(c.text)}</span>
            </li>
          ))}
        </ol>
      )}
      {!m.old_script && <BgmCandidates ep={m.episode} onSwitched={reload} />}
      <audio ref={ref} src={src} preload="metadata" />
    </div>
  );
}
