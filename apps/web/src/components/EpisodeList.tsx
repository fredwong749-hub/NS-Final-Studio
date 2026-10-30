import { useMemo, useState } from "react";
import { useStudio } from "../store";
import { epCode, FILTER_LABEL, matchFilter } from "../util";

export function EpisodeList() {
  const { episodes, epNum, gotoEpisode, latest, filter, epLooks } = useStudio();
  const [q, setQ] = useState("");
  const [onlyRed, setOnlyRed] = useState(false);

  const rows = useMemo(() => {
    const t = q.trim();
    return (episodes ?? []).filter(
      (e) =>
        (!onlyRed || e.high_intensity) &&
        (filter === "all" || e.shots.some((s) => matchFilter(filter, s, latest.get(s.id)))) &&
        (!t || String(e.number) === t.replace(/^ep0?/i, "") || e.title.includes(t) || e.tag.includes(t)),
    );
  }, [episodes, q, onlyRed, filter, latest]);

  const totals = useMemo(() => {
    let f = 0, v = 0, p = 0, n = 0;
    for (const e of episodes ?? [])
      for (const s of e.shots) {
        n++;
        if (s.first_frame) f++;
        if (s.video) v++;
        if (s.review.state === "passed") p++;
      }
    return { f, v, p, n };
  }, [episodes]);

  return (
    <aside className="ep-list">
      <div className="ep-list-head">
        <div className="ep-totals tnum">
          首帧 {totals.f}/{totals.n} · 视频 {totals.v}/{totals.n} · 通过 {totals.p}/{totals.n}
        </div>
        <input className="ep-search" placeholder="搜索集数 / 标题" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="ep-filter">
          <input type="checkbox" checked={onlyRed} onChange={(e) => setOnlyRed(e.target.checked)} /> 只看 🔴
          {filter !== "all" && <span className="muted">· 过滤：{FILTER_LABEL[filter]}</span>}
        </label>
      </div>
      <ul>
        {rows.map((e) => {
          const passed = e.shots.filter((s) => s.review.state === "passed").length;
          const rejected = e.shots.some((s) => s.review.state === "rejected");
          const d = Object.values(epLooks[e.number]?.characters ?? {})[0]?.resolved.d_state.value;
          return (
            <li key={e.number}>
              <button
                className={`ep-row${e.number === epNum ? " active" : ""}`}
                onClick={() => gotoEpisode(e.number)}
                title={e.synopsis}
              >
                <span className="ep-num tnum">{String(e.number).padStart(2, "0")}</span>
                <span className="ep-main">
                  <span className="ep-title">
                    {e.high_intensity && <span title="高强度集">🔴</span>}
                    {e.title}
                  </span>
                  <span className="ep-prog">
                    <span className="dots6">
                      {e.shots.map((s) => {
                        const cls = s.job
                          ? "p-busy"
                          : s.video
                            ? (s.stale.video?.length ? "p-warn" : "p-vid")
                            : s.first_frame
                              ? (s.stale.image?.length ? "p-warn" : "p-img")
                              : "p-none";
                        return <i key={s.id} className={cls} title={`${s.id}：${s.video ? "有视频" : s.first_frame ? "有首帧" : "未出图"}${s.job ? "（任务中）" : ""}`} />;
                      })}
                    </span>
                    {d && <span className="muted">{d}</span>}
                    <span className={`tnum ${rejected ? "bad" : passed === e.shots.length ? "good" : "muted"}`}>
                      审 {passed}/{e.shots.length}
                    </span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && <li className="muted pad">没有匹配的集</li>}
        {episodes && <li className="muted pad small">{epCode(1)}–{epCode(episodes.length)}</li>}
      </ul>
    </aside>
  );
}
