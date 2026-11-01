// fredw-92/U2（v3.1 §2.1 / §2.4）：精修中区的大格——单格放大、视频审片（循环 / 逐帧 / 0.5×）、
// 首尾对照（视频第一帧 | 定稿首帧、视频最后一帧 | 定稿尾帧）、与上一版视频并排同步播放。
import { thumb } from "../../thumb";
import { useEffect, useRef, type CSSProperties, type ReactNode, type SyntheticEvent } from "react";
import { MODE_LABEL, STRENGTH_LABEL, type Slot } from "../api_v1";
import { takeBadge, takeUrl, type TakeX } from "./state";
import { SLOT_NAME } from "./actions";
import { MotionQcBadge } from "../MotionQc";
import { motionOf } from "../MotionQc.helpers";
import { TileActionButtons } from "../../ds/editdel";
import { TileBar, TileTop } from "../../ds/TileBar";
import { RegenButton } from "../RegenButton";
import { useStudio } from "../../store";

/** 精修的格子名 → takes.json 的 stage */
const STAGE_OF: Record<Slot, "image" | "last" | "video"> = { first: "image", last: "last", video: "video" } as Record<Slot, "image" | "last" | "video">;

export type VideoView = "single" | "ends" | "prev";

/** 一格：标签 + 唯一状态角标 + 内容 */
export function Cell({
  label,
  t,
  style,
  children,
  cap,
  className = "",
  onClick,
  title,
  top,
  actions,
}: {
  label: ReactNode;
  t?: TakeX | null;
  style?: CSSProperties;
  children: ReactNode;
  cap?: ReactNode;
  className?: string;
  onClick?: () => void;
  title?: string;
  /** 左上角标签下面再放的东西（运动质检…），和标签一列排开 */
  top?: ReactNode;
  /** 格子操作（✎ 改 / 🗑）：和状态牌、说明一起放进底栏（UIPIXEL：不再各自 absolute 叠放） */
  actions?: ReactNode;
}) {
  const b = takeBadge(t);
  return (
    <div className={`v3e-cell ${className}`} style={style} onClick={onClick} title={title} role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}>
      <TileTop>
        <span className="v3e-lab">{label}</span>
        {top}
      </TileTop>
      {children}
      <TileBar
        status={
          b || cap ? (
            <>
              {b && (
                <b className={`v3e-badge ${b.cls}`} title={b.why ? `${b.text}：${b.why}` : b.text}>
                  {b.text}
                </b>
              )}
              {cap && (
                <span className="v3e-cap" title={typeof cap === "string" ? cap : undefined}>
                  {cap}
                </span>
              )}
            </>
          ) : null
        }
        actions={actions}
      />
    </div>
  );
}

const modeCap = (t: TakeX | null | undefined) =>
  t?.mode && t.mode !== "regen"
    ? `${MODE_LABEL[t.mode] ?? t.mode}${t.strength ? ` · ${STRENGTH_LABEL[t.strength]}` : ""}${t.parent != null ? ` · 来自 #${t.parent}` : ""}`
    : null;

/** 视频第一帧 / 最后一帧：用媒体片段 #t= 让浏览器停在那一帧；最后一帧优先用后端抽好的 last_url */
function VideoFrame({ src, at }: { src: string; at: "first" | "last" }) {
  const ref = useRef<HTMLVideoElement>(null);
  return (
    <video
      ref={ref}
      src={at === "first" ? `${src}#t=0.001` : src}
      muted
      playsInline
      preload="auto"
      onLoadedMetadata={(e) => {
        const v = e.currentTarget;
        if (at === "last" && Number.isFinite(v.duration)) v.currentTime = Math.max(0, v.duration - 0.04);
      }}
    />
  );
}

interface StageProps {
  slot: Slot;
  cur: TakeX | null;
  /** 单格的尺寸（按可用高度算好的） */
  size: { w: number; h: number };
  view: VideoView;
  prev: TakeX | null;
  lockFirst: TakeX | null;
  lockLast: TakeX | null;
  loop: boolean;
  rate: number;
  placeholder: ReactNode;
  overlay?: ReactNode;
  /** UXF2 #7：这一版视频完整看过一遍（播到结尾或拖到最后 0.3 s）——通过前的 B11 规则 */
  onWatched?: () => void;
  /** EDITDEL：本镜 id（给了就在大格右下角显示“修改 / 删除这一版”） */
  shot?: string;
  onChanged?: () => void;
}

/** 播到结尾（或拖到最后 0.3 s）算看完 */
const watchProps = (cb?: () => void) =>
  cb
    ? {
        onEnded: cb,
        onTimeUpdate: (e: SyntheticEvent<HTMLVideoElement>) => {
          const v = e.currentTarget;
          if (v.duration && v.currentTime >= v.duration - 0.3) cb();
        },
      }
    : {};

export function Stage({ slot, cur, size, view, prev, lockFirst, lockLast, loop, rate, placeholder, overlay, onWatched, shot, onChanged }: StageProps) {
  const studio = useStudio();
  const box = useRef<HTMLDivElement>(null);
  const master = useRef<HTMLVideoElement>(null);
  const slave = useRef<HTMLVideoElement>(null);
  const cs: CSSProperties = { width: size.w, height: size.h };

  // 播放速度 / 循环作用到大格里所有视频
  useEffect(() => {
    box.current?.querySelectorAll<HTMLVideoElement>("video[data-play]").forEach((v) => {
      v.playbackRate = rate;
      v.loop = loop;
    });
  });

  // 与上一版并排：右边（这一版）是主控，左边跟着播 / 停 / 跳 / 变速
  useEffect(() => {
    if (view !== "prev") return;
    const m = master.current;
    const s = slave.current;
    if (!m || !s) return;
    const sync = () => {
      if (Math.abs(s.currentTime - m.currentTime) > 0.08) s.currentTime = Math.min(m.currentTime, s.duration || m.currentTime);
    };
    const play = () => {
      sync();
      void s.play().catch(() => undefined);
    };
    const pause = () => {
      s.pause();
      sync();
    };
    const rc = () => (s.playbackRate = m.playbackRate);
    const tu = () => !m.paused && Math.abs(s.currentTime - m.currentTime) > 0.25 && sync();
    m.addEventListener("play", play);
    m.addEventListener("pause", pause);
    m.addEventListener("seeked", sync);
    m.addEventListener("ratechange", rc);
    m.addEventListener("timeupdate", tu);
    return () => {
      m.removeEventListener("play", play);
      m.removeEventListener("pause", pause);
      m.removeEventListener("seeked", sync);
      m.removeEventListener("ratechange", rc);
      m.removeEventListener("timeupdate", tu);
    };
  }, [view, cur?.n, prev?.n]);

  const vidSrc = slot === "video" ? cur?.url ?? null : null;

  if (slot === "video" && vidSrc && view === "ends") {
    const fUsed = cur?.params && (cur.params as { first?: { n?: number } }).first?.n;
    const lUsed = cur?.params && (cur.params as { last?: { n?: number } }).last?.n;
    return (
      <div className="v3e-stage ends" ref={box}>
        <div className="v3e-pair2">
          <Cell label={`视频 #${cur!.n} · 第一帧`} style={cs}>
            <VideoFrame src={vidSrc} at="first" />
          </Cell>
          <Cell label={lockFirst ? `定稿首帧 #${lockFirst.n}` : "首帧未定稿"} t={lockFirst} style={cs} cap={fUsed && lockFirst && fUsed !== lockFirst.n ? `这版视频用的是首帧 #${fUsed}` : null}>
            {takeUrl(lockFirst) ? <img src={thumb(takeUrl(lockFirst)!, 720) ?? takeUrl(lockFirst)!} alt="" /> : <div className="v3e-ph">还没有定稿首帧</div>}
          </Cell>
        </div>
        <div className="v3e-pair2">
          <Cell label={`视频 #${cur!.n} · 最后一帧`} style={cs}>
            {cur?.last_url ? <img src={thumb(cur.last_url, 720) ?? cur.last_url} alt="" /> : <VideoFrame src={vidSrc} at="last" />}
          </Cell>
          <Cell label={lockLast ? `定稿尾帧 #${lockLast.n}` : "尾帧未定稿"} t={lockLast} style={cs} cap={lUsed && lockLast && lUsed !== lockLast.n ? `这版视频用的是尾帧 #${lUsed}` : null}>
            {takeUrl(lockLast) ? <img src={thumb(takeUrl(lockLast)!, 720) ?? takeUrl(lockLast)!} alt="" /> : <div className="v3e-ph">还没有定稿尾帧</div>}
          </Cell>
        </div>
      </div>
    );
  }

  if (slot === "video" && vidSrc && view === "prev" && prev?.url) {
    return (
      <div className="v3e-stage" ref={box}>
        <Cell label={`上一版 视频 #${prev.n}`} t={prev} style={cs} cap={modeCap(prev)}>
          <video ref={slave} data-play src={prev.url} muted playsInline preload="auto" />
        </Cell>
        <Cell label={`这一版 视频 #${cur!.n}`} t={cur} style={cs} className="focus" cap="这一格的进度条 / 播放 = 两边一起">
          <video ref={master} data-play src={vidSrc} controls playsInline preload="auto" {...watchProps(onWatched)} />
        </Cell>
        {overlay}
      </div>
    );
  }

  const url = slot === "video" ? null : takeUrl(cur);
  return (
    <div className="v3e-stage" ref={box}>
      <Cell
        label={`${SLOT_NAME[slot]}${cur ? ` · #${cur.n}` : ""}`}
        t={cur}
        style={cs}
        className={`focus ${slot === "video" ? "vid" : ""}`}
        cap={modeCap(cur)}
        top={vidSrc ? <MotionQcBadge q={motionOf(cur)} className="v3e-mqc" /> : null}
        actions={
          shot && cur && (vidSrc || url) ? (
            <>
              {/* 项目方 11-01：“添加一个生成按钮,基于现在再生成一个新的图”——精修大格也挂 ↻ 再生成（首帧 / 尾帧；新图进版本链，不动当前版） */}
              {slot !== "video" && url && (
                <RegenButton
                  shot={shot}
                  stage={STAGE_OF[slot] as "image" | "last"}
                  n={cur.n}
                  label={SLOT_NAME[slot]}
                  chars={(studio.summaryById.get(shot)?.characters ?? []).map((c) => ({ id: c.character, name: c.name }))}
                  size="sm"
                  onDone={(m, k) => {
                    studio.notify(m, k ?? "ok");
                    onChanged?.();
                  }}
                />
              )}
              <TileActionButtons
                edit={{ type: slot === "video" ? "video" : "image", id: `take:${shot}/${STAGE_OF[slot]}/${cur.n}`, src: vidSrc ?? url, label: `${shot} ${SLOT_NAME[slot]} #${cur.n}` }}
                del={{ type: "take", id: `${shot}/${STAGE_OF[slot]}/${cur.n}` }}
                onChanged={onChanged}
              />
            </>
          ) : null
        }
      >
        {vidSrc ? (
          <video data-play src={vidSrc} poster={cur?.last_url ?? undefined} controls playsInline preload="metadata" {...watchProps(onWatched)} />
        ) : url ? (
          <img src={url} alt="" />
        ) : (
          placeholder
        )}
        {overlay}
      </Cell>
    </div>
  );
}

