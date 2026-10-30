import { memo, useEffect, useRef, type MouseEvent } from "react";
import { useStudio } from "../store";
import type { Job, ShotSummary } from "../types";
import { epCode, isFailed, JOB_LABEL, matchFilter, REVIEW_LABEL, staleList } from "../util";
import { mediaChain } from "./ShotCard";

const Cell = memo(function Cell({
  s,
  job,
  selected,
  inMulti,
  dim,
  onClick,
  onOpen,
}: {
  s: ShotSummary;
  job?: Job;
  selected: boolean;
  inMulti: boolean;
  dim: boolean;
  onClick: (e: MouseEvent, id: string) => void;
  onOpen: (id: string) => void;
}) {
  const failed = isFailed(s, job);
  const stale = staleList(s).length > 0;
  return (
    <div
      className={`ov-cell${selected ? " selected" : ""}${inMulti ? " multi" : ""}${dim ? " dim" : ""}`}
      onClick={(e) => onClick(e, s.id)}
      onDoubleClick={() => onOpen(s.id)}
      title={`${s.id}\n${s.img_summary}\n审核：${REVIEW_LABEL[s.review.state]}${stale ? "\n已过期：" + staleList(s).join("、") : ""}`}
    >
      <div className="ov-pair">
        {s.first_frame ? <img src={s.first_frame} alt="" loading="lazy" draggable={false} /> : <div className="thumb-empty">首</div>}
        {s.last_frame_target ? <img src={s.last_frame_target} alt="" loading="lazy" draggable={false} /> : <div className="thumb-empty">尾</div>}
      </div>
      <div className="ov-chain">
        {mediaChain(s, undefined, job).map(([k, c, t]) => (
          <i key={k} className={`c-${c}`} title={`${k}：${t}`} />
        ))}
      </div>
      <div className="ov-badges">
        {s.job && <span className={`badge b-${s.job}`}>{JOB_LABEL[s.job]}</span>}
        {failed && <span className="badge b-failed">失败</span>}
        {s.edited && <span className="badge b-edited">改</span>}
        {s.adult && <span className="badge b-adult">本地</span>}
      </div>
    </div>
  );
});

export function OverviewGrid() {
  const { episodes, latest, sel, multi, select, setMulti, setView, filter, epNum } = useStudio();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.querySelector(".ov-row.current")?.scrollIntoView({ block: "center" });
    // 只在打开总览时定位一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!episodes) return null;
  // 每集 6–8 镜：列数按最多的那集，少的补空格
  const maxShots = Math.max(6, ...episodes.map((e) => e.shots.length));
  const cols = Array.from({ length: maxShots }, (_, i) => i + 1);
  const onClick = (e: MouseEvent, id: string) => select(id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey });
  const onOpen = (id: string) => {
    select(id);
    setView("episode");
  };
  return (
    <div className="overview v3" ref={box} style={{ ["--ov-n" as string]: maxShots }}>
      <div className="ov-row ov-header">
        <div className="ov-ep">集</div>
        {cols.map((i) => (
          <div key={i} className="ov-col">S{i}</div>
        ))}
      </div>
      {episodes.map((e) => {
        const passed = e.shots.filter((s) => s.review.state === "passed").length;
        return (
          <div key={e.number} className={`ov-row${e.number === epNum ? " current" : ""}`}>
            <button
              className="ov-ep"
              title={`${e.synopsis}\n点击：选中整集 ${e.shots.length} 镜；双击：打开本集`}
              onClick={() => setMulti(new Set(e.shots.map((s) => s.id)))}
              onDoubleClick={() => e.shots[0] && onOpen(e.shots[0].id)}
            >
              <b>{epCode(e.number)}</b>
              <span className="ov-title">{e.high_intensity && "🔴"}{e.title}</span>
              <span className="ov-looks" title="本集造型">
                {[...new Map(e.shots.flatMap((s) => s.characters).map((c) => [c.character, c])).values()].map((c) => (
                  <span key={c.character}>
                    {c.name.slice(0, 1)}
                    <b>{c.look_label || c.look_name.slice(0, 2)}</b>
                    {c.d_state && <i>{c.d_state}</i>}
                  </span>
                ))}
              </span>
              <span className="tnum muted">审 {passed}/{e.shots.length}</span>
            </button>
            {e.shots.map((s) => (
              <Cell
                key={s.id}
                s={s}
                job={latest.get(s.id)}
                selected={s.id === sel}
                inMulti={multi.has(s.id)}
                dim={!matchFilter(filter, s, latest.get(s.id))}
                onClick={onClick}
                onOpen={onOpen}
              />
            ))}
            {cols.slice(e.shots.length).map((i) => (
              <div key={`pad${i}`} className="ov-cell pad" title="本集没有这一镜" />
            ))}
          </div>
        );
      })}
    </div>
  );
}
