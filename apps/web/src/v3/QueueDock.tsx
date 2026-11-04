// L-123 延伸：全系统出图队列（项目方 17:0x：“提示整个系统的排队阵列”）。通用组件：出图页、资产页、视频页都放同一个。
// 数据：/api/frame-queue（producer registry 的 ready / running，按 K-OPS-E30 排序：按集、集内插队 / 驳回先、尾帧先、镜号）。
// 收起时一行：“出图队列 12 · 你提交的 3 条：排第 2、5、9”；点开是完整列表（按集顺序），你提交的那几条高亮。
import { useState } from "react";
import { useFrameQueue, type Item } from "./QueueDock.helpers";
import { fmtClock } from "./GenState.helpers";
import { GenLamp } from "./GenState";
import "./genstate.css";

export function QueueDock() {
  const q = useFrameQueue();
  const [open, setOpen] = useState(false);
  if (!q) return null;
  const total = q.running + q.queued;
  const mine = q.mine.filter((m) => m.state !== "needs_look");
  const look = q.mine.filter((m) => m.state === "needs_look");
  if (!total && !q.mine.length) return null;
  const poss = mine.map((m) => (m.pos ? `排第 ${m.pos}` : m.state === "rendering" ? "修改中" : m.word)).join("、");
  const mineShots = new Set(q.mine.map((m) => `${m.stage}:${m.shot}`));
  const byEp = new Map<number, Item[]>();
  for (const i of q.items) byEp.set(i.ep, [...(byEp.get(i.ep) ?? []), i]);
  return (
    <div className="qd" aria-label="出图队列">
      <button type="button" className="qd-bar" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <GenLamp phase={q.running ? "running" : "queued"} />
        <b>出图队列 {total}</b>
        {mine.length > 0 && <span>· 你提交的 {mine.length} 条：{poss}</span>}
        {look.length > 0 && <span className="qd-look">· {look.length} 条需要你看一眼</span>}
        <span className="qd-chev">{open ? "▾" : "▴"}</span>
      </button>
      {open && (
        <div className="qd-list">
          {q.stale && <div className="qd-stale">数据可能过期：服务器那边的排队情况还没同步过来，位置和时间只是估计</div>}
          {look.map((m) => (
            <div key={m.id} className="qd-row look">
              <b>{m.shot} {m.stage === "first" ? "首帧" : "尾帧"}</b> <span>需要你看一眼：{m.msg}</span>
            </div>
          ))}
          {[...byEp.entries()].map(([ep, rows]) => (
            <div key={ep}>
              <div className="qd-ep">第 {ep} 集</div>
              {rows.map((i) => (
                <div key={i.oid} className={`qd-row${mineShots.has(i.oid) ? " mine" : ""}`}>
                  <GenLamp phase={i.state === "running" ? "running" : "queued"} />
                  <b>{i.shot} {i.kind === "first" ? "首帧" : "尾帧"}</b>
                  <span>{i.state === "running" ? "出图中" : `排第 ${i.pos}`}{i.redo ? " · 修改 / 重出" : ""}</span>
                  <span className="qd-eta">{fmtClock(i.eta_at * 1000)} 前后</span>
                  {mineShots.has(i.oid) && <span className="qd-me">你提交的</span>}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
