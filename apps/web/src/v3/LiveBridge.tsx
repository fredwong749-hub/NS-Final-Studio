// 实时事件 → 画布数据（全站挂一次）：某一镜的首帧 / 尾帧 / 视频 / 任务变了，只重取这几镜（不整页刷新，滚动和打开的抽屉都不动）；
// 轮询兜底（SSE 断了）时每 10 秒重取集摘要。各页面自己的板块用 useLiveEvent 刷自己的数据。
import { useEffect, useRef } from "react";
import { useStudio } from "../store";
import { onLive, useLiveStatus } from "./live";
import { reloadCandidates } from "./candidates";
import "../ds/live.css";

// 全局重取队列：同一时刻只有一批（≤ 4 镜）在路上
const queue = new Set<string>();
// 别的集变了的镜：先记着（缓存算过期），切到那一集时再取
const staleIds = new Set<string>();
let draining = false;
let refreshFn: ((ids: string[]) => Promise<unknown>) | null = null;
async function drain() {
  if (draining || !refreshFn) return;
  draining = true;
  try {
    while (queue.size) {
      const batch = [...queue].slice(0, 4);
      batch.forEach((id) => queue.delete(id));
      try {
        await refreshFn(batch);
      } catch {
        /* 这一批失败不影响后面 */
      }
    }
  } finally {
    draining = false;
  }
}

export function LiveBridge() {
  const st = useStudio();
  const ref = useRef(st);
  ref.current = st;
  refreshFn = st.refreshShots;
  // 切到别的集：把那一集里先前记下的“过期”镜补取一次
  const epNo = st.episode?.number;
  useEffect(() => {
    const ids = (ref.current.episode?.shots ?? []).map((x) => x.id).filter((id) => staleIds.has(id));
    if (!ids.length) return;
    ids.forEach((id) => (staleIds.delete(id), queue.add(id)));
    void drain();
  }, [epNo]);
  useEffect(() => {
    const ids = new Set<string>();
    const eps = new Set<number>();
    let t: number | null = null;
    let tick = false;
    const flush = () => {
      t = null;
      const s = ref.current;
      const list = [...ids];
      const tickWas = tick;
      ids.clear();
      eps.forEach((e) => reloadCandidates(e));
      eps.clear();
      // PAGEWATCH PW-016（复查后）：只重取当前这一集的镜 + 正在看的那一镜；别的集不管（切过去时 store 会自己取那一集的详情）。
      // 所有 flush 共用一个全局队列，一次只跑一批（最多 4 镜）；一阵变了 20 镜以上就只拉一次集摘要。
      const cur = new Set((s.episode?.shots ?? []).map((x) => x.id));
      const need = list.filter((id) => cur.has(id) || id === s.sel);
      tick = false;
      if (list.length || tickWas) void s.refreshEpisodes();
      if (!need.length || list.length > 20) return;
      list.filter((id) => !need.includes(id)).forEach((id) => staleIds.add(id));
      need.forEach((id) => queue.add(id));
      void drain();
    };
    return onLive((e) => {
      if (e.type === "tick") tick = true;
      else if ((e.type === "frame" || e.type === "lastframe" || e.type === "video" || e.type === "job") && e.shot) {
        ids.add(e.shot);
        if (e.episode) eps.add(e.episode);
      } else if (e.type === "cut" || e.type === "stage") tick = true;
      else return;
      if (t == null) t = window.setTimeout(flush, 500);
    });
  }, []);
  return null;
}

/** 顶栏小标：实时 / 断开改为 10 秒轮询 */
export function LiveIndicator() {
  const s = useLiveStatus();
  if (s === "live") return <span className="live-ind" title="实时连接正常：素材、任务、写作一有变化就自动更新">
      <i aria-hidden />实时
    </span>;
  if (s === "poll") return <span className="live-ind poll" title="实时连接断开了，先每 10 秒自动刷新；连上后自动恢复">
      <i aria-hidden />实时连接已断开·10 秒刷新
    </span>;
  if (s === "reconnecting")
    return (
      <span className="live-ind connecting" title="后台刚重启或连接断了，正在重新连上；连上后自动把这页的数据全部重取一次">
        <i aria-hidden />重连中
      </span>
    );
  return <span className="live-ind connecting"><i aria-hidden />连接中</span>;
}
