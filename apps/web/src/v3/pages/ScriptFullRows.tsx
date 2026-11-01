// UIRSI 2026-11-01（项目方：“剧本的页面你改坏了……之前起码有前后帧，还有视频”）：
// 剧本页默认 = 每镜一行的完整视图（和画布审片同一个 ReviewRow：首帧 · 尾帧 · 视频 · 剧本 / 表情 / 对白 ▶ / 声音 · 人物与场景 ·
// 分镜详情 / 首帧提示词 / 视频提示词 · 资料完整度 · 状态 · 一键操作 · 修改 / 删除）。阅读模式（EpisodeReader）是第二视图。
import { useEffect } from "react";
import { useStudio } from "../../store";
import { useSop } from "../sop.helpers";
import { ReviewRow } from "../ReviewRow";
import { rowDim } from "../ReviewRow.helpers";
import { Skel } from "../../ds";

export function ScriptFullRows({ ep }: { ep: number }) {
  const st = useStudio();
  const { sop } = useSop();
  const has = !!st.episodes?.some((e) => e.number === ep);
  useEffect(() => {
    // 剧本页看哪一集，顶栏 / 画布就跟到哪一集（同一份数据，状态与操作全通用）
    if (has && st.episode?.number !== ep) st.gotoEpisode(ep);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ep, has]);
  if (!st.episodes) return <Skel h={360} />;
  if (!has) return <p className="ds-muted">第 {ep} 集还没导入画布：导入后这里显示每镜完整一行（首尾帧、视频、提示词、状态、操作）。</p>;
  const e = st.episode;
  if (!e || e.number !== ep || e.light) {
    // 换集时这一集的镜头还没读到：按这一集的镜数占好同样高度的位置（不让下面的内容先缩再撑，PAGEWATCH PW-007）
    const n = st.episodes.find((x) => x.number === ep)?.shots.length || 3;
    return (
      <div className="v3-rows sf-fullrows" aria-busy="true" aria-label={`第 ${ep} 集 正在读镜头`}>
        {Array.from({ length: n }, (_, i) => (
          <div key={i} className="v3-row sf-row-skel">
            <Skel h="100%" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="v3-rows sf-fullrows" aria-label={`第 ${ep} 集 每镜完整信息`}>
      {e.shots.map((s) => (
        <ReviewRow key={s.id} s={s} sop={sop?.shots.find((x) => x.id === s.id)} selected={s.id === st.sel} inMulti={st.multi.has(s.id)} dim={rowDim(st, s)} />
      ))}
    </div>
  );
}
