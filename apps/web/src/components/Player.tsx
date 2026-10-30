import { useStudio } from "../store";
import type { ShotDetail } from "../types";
import { STAGE_LABEL } from "../util";

/** 视频播放到结尾（或最后 0.3 s）记为“完整看过” */
export function WatchVideo({ src, poster, className, id }: { src: string; poster?: string | null; className?: string; id?: string }) {
  const { markWatched, watched } = useStudio();
  return (
    <div className={`watch-wrap ${className ?? ""}`}>
      <video
        id={id}
        key={src}
        src={src}
        poster={poster ?? undefined}
        controls
        playsInline
        onTimeUpdate={(e) => {
          const v = e.currentTarget;
          if (v.duration && v.currentTime >= v.duration - 0.3) markWatched(src);
        }}
        onEnded={() => markWatched(src)}
      />
      <span className={`watched-tag${watched.has(src) ? " yes" : ""}`}>{watched.has(src) ? "已完整看过" : "未看完"}</span>
    </div>
  );
}

export function Player({ d }: { d: ShotDetail }) {
  const { preview, setPreview } = useStudio();
  const s = d.summary;
  const p = preview && preview.shotId === s.id ? d.takes.takes.find((t) => t.stage === preview.stage && t.n === preview.n) : undefined;
  return (
    <div className="player">
      {p ? (
        <>
          <div className="preview-banner">
            预览 {STAGE_LABEL[p.stage]} #{p.n}（非当前）
            <button className="btn-mini" onClick={() => setPreview(null)}>
              回到当前
            </button>
          </div>
          {p.stage === "video" && p.url ? (
            <video id="main-player" key={p.url} src={p.url} controls playsInline poster={p.last_url ?? undefined} />
          ) : p.url ? (
            <img src={p.url} alt="" />
          ) : (
            <div className="thumb-empty">文件缺失</div>
          )}
        </>
      ) : s.video ? (
        <WatchVideo id="main-player" src={s.video} poster={s.first_frame} />
      ) : s.first_frame ? (
        <img src={s.first_frame} alt="首帧" />
      ) : (
        <div className="thumb-empty">还没有首帧 / 视频</div>
      )}
    </div>
  );
}
