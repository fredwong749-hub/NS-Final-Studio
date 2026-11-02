import { useEpisodeTags } from "../looks";
import { useStudio } from "../store";
import { REVIEW_LABEL, shotLine, staleList } from "../util";
import { LookStrip } from "./LookStrip";
import { WatchVideo } from "./Player";
import { LooksSection } from "./LooksSection";

function LookDetails({ shotId }: { shotId: string }) {
  return (
    <details className="compiled">
      <summary>造型明细与参考图</summary>
      <LooksSection shotId={shotId} />
    </details>
  );
}

/** 审片模式（规范 C9）：全屏 9:16 播放器；J/K 移动，A 用这版，Esc 退出 */
export function ReviewMode() {
  const { reviewMode, setReviewMode, sel, summaryById, epNum, details, episode } = useStudio();
  const tags = useEpisodeTags(epNum);
  if (!reviewMode) return null;
  const s = sel ? summaryById.get(sel) : undefined;
  const d = sel ? details[sel] : undefined;
  const passed = episode?.shots.filter((x) => x.review.state === "passed").length ?? 0;
  return (
    <div className="review-mode">
      <div className="rm-stage">
        {s?.video ? (
          <WatchVideo id="review-player" src={s.video} poster={s.first_frame} className="rm-video" />
        ) : s?.first_frame ? (
          <img src={s.first_frame} alt="" />
        ) : (
          <div className="thumb-empty">没有首帧 / 视频</div>
        )}
      </div>
      <div className="rm-side">
        <div className="row-actions">
          <b className="insp-id">{s?.id ?? "—"}</b>
          <span className="grow" />
          <button className="btn-mini" onClick={() => setReviewMode(false)}>
            退出 Esc
          </button>
        </div>
        {/* T60：翻到下一集时本集详情可能还在路上（轻量数据没有运镜 / 表情 / 对白），先只显示画面 */}
        {s && episode?.light && <div className="muted">加载第 {episode.number} 集…</div>}
        {s && !episode?.light && (
          <>
            <div>
              <span className={`review-badge r-${s.review.state}`}>{REVIEW_LABEL[s.review.state]}</span>{" "}
              {s.review.reason && <span className="muted">{s.review.reason}</span>}
            </div>
            <div className="muted">本集已通过 {passed}/{episode?.shots.length ?? 0}</div>
            {staleList(s).length > 0 && <div className="warn">已过期：{staleList(s).join("、")}</div>}
            <div className="sub-title">造型</div>
            <LookStrip tags={tags[s.id]} />
            <LookDetails shotId={s.id} />
            <div className="sub-title">运镜 / 表情</div>
            <div>
              {s.camera.text || "—"} · {s.expression.text || "未标注"}
            </div>
            <div className="sub-title">对白 / 旁白</div>
            <div>{shotLine(s).text || "—"}</div>
            {d?.script.voiceover && <div className="muted">🎙 {d.script.voiceover.text}</div>}
            <div className="rm-keys">
              <kbd>J</kbd> 上一镜 <kbd>K</kbd> 下一镜 <kbd>空格</kbd> 播放
              <br />
              <kbd>A</kbd> 用这版 · 标记后自动跳到下一个未审镜头
            </div>
          </>
        )}
      </div>
    </div>
  );
}
