import { useMemo, useState } from "react";
import { useStudio } from "../store";
import { epCode, EXPLICIT_LABEL, FILTER_LABEL, matchFilter } from "../util";

export function EpisodeList() {
  const { episodes, epNum, gotoEpisode, latest, filter, select } = useStudio();
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

  // 「仅看红标」：全部集的露骨红标镜头集中列出（只列镜号，不显示镜头文字）
  const held = useMemo(() => (episodes ?? []).flatMap((e) => e.shots.filter((s) => s.explicit_hold).map((s) => ({ ep: e.number, id: s.id }))), [episodes]);

  return (
    <aside className="ep-list">
      <div className="ep-list-head">
        <div className="ep-totals tnum" title={`全剧 ${totals.n} 镜：首帧 ${totals.f} · 视频 ${totals.v} · 审核通过 ${totals.p}`}>
          <span><b>{totals.f}</b>首帧</span>
          <span><b>{totals.v}</b>视频</span>
          <span><b>{totals.p}</b>通过</span>
          <span className="ep-totals-n">/ {totals.n} 镜</span>
        </div>
        <input className="ep-search" placeholder="搜索集数 / 标题" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="ep-filter">
          <input type="checkbox" checked={onlyRed} onChange={(e) => setOnlyRed(e.target.checked)} /> 只看高强度集
          {filter !== "all" && <span className="muted">· 过滤：{FILTER_LABEL[filter]}</span>}
        </label>
      </div>
      {filter === "explicit" && (
        <div className="explicit-list">
          <div className="explicit-list-head">
            <span className="chip chip-explicit">{EXPLICIT_LABEL}</span> 共 {held.length} 镜
          </div>
          <div className="explicit-ids">
            {held.map((h) => (
              <button key={h.id} className="btn-mini" onClick={() => (gotoEpisode(h.ep), select(h.id))}>
                {h.id}
              </button>
            ))}
            {held.length === 0 && <span className="muted small">没有红标镜头</span>}
          </div>
        </div>
      )}
      <ul>
        {rows.map((e) => {
          const passed = e.shots.filter((s) => s.review.state === "passed").length;
          const rejected = e.shots.some((s) => s.review.state === "rejected");
          return (
            <li key={e.number}>
              <button
                className={`ep-row${e.number === epNum ? " active" : ""}`}
                onClick={() => gotoEpisode(e.number)}
                title={`第 ${e.number} 集《${e.title}》\n${e.synopsis ?? ""}`}
              >
                <span className="ep-num tnum">{String(e.number).padStart(2, "0")}</span>
                <span className="ep-main">
                  <span className="ep-title">
                    {e.high_intensity && <i className="ep-hi" title="高强度集" />}
                    {e.title}
                    {!!e.explicit_hold_count && (
                      <span className="chip chip-explicit" title={`${e.explicit_hold_count} 镜露骨红标（项目方自行处理）`}>
                        露骨 {e.explicit_hold_count}
                      </span>
                    )}
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
