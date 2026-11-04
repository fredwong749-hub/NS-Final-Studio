// ASSETUX L-120：全站通用生成状态。任何“再生成 / 编辑 / 重出”按钮提交后，调 trackGen() 登记 job；
// 同一位置放 <GenTiles where=…/>（原位占位卡：琥珀呼吸灯 + 排队第 N / 生成中 + 预计完成钟点），页面放一个 <GenPoller onDone=…/>（轮询 /api/jobs，完成后回调刷新）。
// 页面右下 <GenDock/> 汇总所有在跑的（点一条 = 滚到对应位置）。呼吸灯样式沿用 breathe.css 的 ns-breathe（2.7 s），排队静止灰点。
import { useEffect, useRef } from "react";
import { emit, getItems, getJobs, setJobs, untrackGen, useGen, type GenItem } from "./GenState.store";
import { fmtClock, fmtRemain, genView, jobId, statusText, type GenView, type JobLite } from "./GenState.helpers";
import "./genstate.css";

/** 轮询 /api/jobs：有在跟踪的 job 才轮询（3 s），完成 / 失败时回调一次（完成的自动从跟踪里拿掉，失败的留着给“重试”） */
export function GenPoller({ onDone, onFail }: { onDone?: (it: GenItem, j: JobLite) => void; onFail?: (it: GenItem, j: JobLite) => void }) {
  const { items: its } = useGen();
  const cb = useRef({ onDone, onFail });
  cb.current = { onDone, onFail };
  const seen = useRef(new Set<string>());
  useEffect(() => {
    if (!its.length) return;
    let alive = true;
    const run = async () => {
      try {
        const r = await fetch("/api/jobs");
        if (!r.ok) return;
        const all = (await r.json()) as JobLite[];
        if (!alive) return;
        setJobs(all);
        for (const it of getItems()) {
          const j = all.find((x) => jobId(x) === it.id);
          const v = genView(j, all, Date.now());
          if (!j || !v || seen.current.has(it.id)) continue;
          if (v.phase === "done") {
            seen.current.add(it.id);
            untrackGen(it.id);
            cb.current.onDone?.(it, j);
          } else if (v.phase === "failed") {
            seen.current.add(it.id);
            cb.current.onFail?.(it, j);
          }
        }
      } catch {
        /* 网络抖动：下一轮再试 */
      }
    };
    void run();
    const t = window.setInterval(run, 3000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [its.length]);
  // 每秒刷新倒计时
  useEffect(() => {
    if (!its.length) return;
    const t = window.setInterval(emit, 1000);
    return () => window.clearInterval(t);
  }, [its.length]);
  return null;
}

function view(it: GenItem): GenView | null {
  const jobs = getJobs();
  const j = jobs.find((x) => jobId(x) === it.id);
  // 刚提交、/api/jobs 还没轮到：当作排队第 1，用兜底估时
  return genView(j ?? { id: it.id, state: "queued", created_at: new Date(it.at).toISOString() }, jobs, Date.now());
}

export function GenLamp({ phase }: { phase: GenView["phase"] }) {
  return <i className={`gen-lamp ${phase === "running" ? "is-rendering" : phase === "queued" ? "is-queued" : "bad"}`} aria-hidden />;
}

/** 一行小条：按钮旁 / 顶部任务条用 */
export function GenChip({ it, onClick }: { it: GenItem; onClick?: () => void }) {
  const v = view(it);
  if (!v) return null;
  return (
    <span className={`gen-chip ${v.phase}`} role="status" onClick={onClick} title={it.summary ? `它理解的改动：${it.summary}` : undefined}>
      <GenLamp phase={v.phase} />
      <b>{statusText(v)}</b>
      {v.phase !== "failed" && (
        <span className="gen-eta">
          {fmtRemain(v.remainS, v.estimated)}
          {v.etaAt ? ` · ${fmtClock(v.etaAt)} 前后` : ""}
        </span>
      )}
    </span>
  );
}

/** 原位占位卡：放在候选列表里，出好后由 onDone 刷新成真候选 */
export function GenTiles({ where, onRetry, className = "" }: { where: string; onRetry?: (it: GenItem) => void; className?: string }) {
  const { items: its } = useGen();
  return (
    <>
      {its
        .filter((x) => x.where === where)
        .map((it) => {
          const v = view(it);
          if (!v) return null;
          return (
            <div key={it.id} id={`gen-${it.id}`} className={`gen-tile ${v.phase} ${className}`} role="status" aria-live="polite">
              <span className="gen-ring" aria-hidden />
              <div className="gen-body">
                <div className="gen-st">
                  <GenLamp phase={v.phase} /> <b>{statusText(v)}</b>
                </div>
                {v.phase !== "failed" ? (
                  <>
                    <div className="gen-eta">{fmtRemain(v.remainS, v.estimated)}</div>
                    {v.etaAt && <div className="gen-eta sub">预计 {fmtClock(v.etaAt)} 完成</div>}
                  </>
                ) : (
                  <button className="gen-retry" onClick={() => (untrackGen(it.id), onRetry?.(it))}>
                    重试
                  </button>
                )}
                {it.summary && <div className="gen-sum">它理解的改动：{it.summary}</div>}
              </div>
            </div>
          );
        })}
    </>
  );
}

/** 页面右下角：所有在跑的汇总；点一条滚到占位卡 */
export function GenDock() {
  const { items: its } = useGen();
  if (!its.length) return null;
  return (
    <div className="gen-dock" aria-label="正在生成">
      {its.map((it) => (
        <div key={it.id} className="gen-dock-row" onClick={() => document.getElementById(`gen-${it.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
          <span className="gen-dock-t">{it.title}</span>
          <GenChip it={it} />
        </div>
      ))}
    </div>
  );
}
