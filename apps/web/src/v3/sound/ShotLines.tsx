// UIRSI（B4，UI_CONTRACT §1.4「对白 / 旁白音频」）：每句一行 ▶；整镜连播。
// 对白、独白用本机音色现合成（不花钱，按内容缓存，和成片同一份）；旁白是远端复刻音色，合成成片后才能听，写明原因。
import { useEffect, useRef, useState } from "react";
import { PlayButton } from "../../ds/MediaPlayer";
import { claim, fmt } from "../../ds/MediaPlayer.helpers";
import { getShotLines, type Line, type ShotLines } from "./sound_api";
import "./sound.css";

export function LineRow({ ln, playing }: { ln: Line; playing?: boolean }) {
  return (
    <li className={`snd-line${playing ? " on" : ""}${ln.play ? "" : " off"}`}>
      <span className={`snd-tag snd-${ln.kind}`}>{ln.label}</span>
      <b className={`snd-who${ln.speaker_name === ln.label ? " same" : ""}`}>{ln.speaker_name}</b>
      <span className="snd-text" title={ln.note ? `剧本标注：${ln.note}` : undefined}>
        {ln.text}
      </span>
      {ln.play ? (
        <PlayButton src={ln.play} label={ln.dur ? fmt(ln.dur) : "听"} size="xs" title={`听这一句：${ln.speaker_name}`} />
      ) : (
        <span className="snd-why" title={ln.reason ?? ""}>
          {ln.reason ?? "暂时不能听"}
        </span>
      )}
    </li>
  );
}

/** 整镜连播：按顺序放这一镜能放的每一句 */
function usePlayAll(lines: Line[] | null) {
  const ref = useRef<HTMLAudioElement | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const queue = (lines ?? []).filter((l) => l.play);
  useEffect(() => () => ref.current?.pause(), []);
  const start = (from = 0) => {
    if (!queue.length) return;
    const el = ref.current ?? (ref.current = new Audio());
    let k = from;
    const next = () => {
      if (k >= queue.length) return setAt(null);
      setAt(queue[k].i);
      el.src = queue[k].play!;
      k += 1;
      claim(el);
      void el.play().catch(() => setAt(null));
    };
    el.onended = next;
    el.onpause = () => (el.ended ? undefined : setAt(null));
    next();
  };
  const stop = () => {
    ref.current?.pause();
    setAt(null);
  };
  return { at, start, stop, n: queue.length };
}

export function ShotLinesList({ shot, data, compact }: { shot: string; data?: ShotLines; compact?: boolean }) {
  const [d, setD] = useState<ShotLines | null>(data ?? null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (data) return setD(data);
    let alive = true;
    setD(null);
    setErr(null);
    getShotLines(shot).then((x) => alive && setD(x), (e: Error) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [shot, data]);
  const all = usePlayAll(d?.lines ?? null);
  if (err) return <p className="snd-empty">台词读不到：{err}</p>;
  if (!d) return <p className="snd-empty">正在读台词…</p>;
  if (!d.lines.length) return <p className="snd-empty">这一镜没有台词</p>;
  return (
    <div className={`snd-shot${compact ? " compact" : ""}`}>
      {all.n > 1 && (
        <button type="button" className={`snd-all${all.at != null ? " on" : ""}`} onClick={() => (all.at != null ? all.stop() : all.start())}>
          {all.at != null ? "❚❚ 停" : `▶ 整镜连播（${all.n} 句）`}
        </button>
      )}
      <ol className="snd-lines">
        {d.lines.map((ln) => (
          <LineRow key={ln.i} ln={ln} playing={all.at === ln.i} />
        ))}
      </ol>
    </div>
  );
}

/** 画布行里用：点了才去读台词（首屏不多发请求），读到后整镜连播 */
export function PlayShotLines({ shot }: { shot: string }) {
  const [lines, setLines] = useState<Line[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [want, setWant] = useState(false);
  const all = usePlayAll(lines);
  useEffect(() => {
    if (want && lines) {
      setWant(false);
      if (all.n) all.start();
      else setMsg(lines.find((l) => l.reason)?.reason ?? "这一镜没有能听的台词");
    }
  }, [want, lines, all]);
  const click = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (all.at != null) return all.stop();
    setMsg(null);
    if (lines) {
      if (all.n) all.start();
      else setMsg(lines.find((l) => l.reason)?.reason ?? "这一镜没有能听的台词");
      return;
    }
    setWant(true);
    getShotLines(shot).then((d) => setLines(d.lines), (er: Error) => (setWant(false), setMsg(er.message)));
  };
  return (
    <button type="button" className={`mp-play mp-xs snd-rowplay${all.at != null ? " on" : ""}`} onClick={click} title={msg ?? "听这一镜的台词（按顺序连播）"} aria-label="听这一镜的台词">
      <span className="mp-ico" aria-hidden>
        {all.at != null ? "❚❚" : want ? "…" : "▶"}
      </span>
      {msg && <span className="mp-lbl snd-why">{msg.length > 14 ? `${msg.slice(0, 14)}…` : msg}</span>}
    </button>
  );
}
