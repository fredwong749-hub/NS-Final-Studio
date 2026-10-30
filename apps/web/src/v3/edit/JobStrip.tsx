// fredw-92/W4b：本镜任务进度（/api/jobs/{id} 轮询）+ 取消
import { useEffect, useState } from "react";
import { useStudio } from "../../store";
import { cancelJob, dismissJob, fmtSec, gpuLabel, useEdit } from "./state";

const ST: Record<string, string> = { queued: "排队中", running: "生成中", done: "完成", failed: "失败", cancelled: "已取消" };

export function JobStrip({ shot }: { shot: string }) {
  const es = useEdit();
  const { notify } = useStudio();
  const [, tick] = useState(0);
  const jobs = es.jobs.filter((j) => j.shot === shot);
  const anyLive = jobs.some((j) => j.state === "queued" || j.state === "running");
  useEffect(() => {
    if (!anyLive) return;
    const t = window.setInterval(() => tick((x) => x + 1), 1000);
    return () => window.clearInterval(t);
  }, [anyLive]);
  if (!jobs.length) return null;
  return (
    <div className="v3e-jobs">
      {jobs.map((j) => {
        const live = (j.state === "queued" || j.state === "running") && !j.notReady;
        const startMs = j.started_at ? Date.parse(j.started_at) : j.submitted;
        const el = (Date.now() - startMs) / 1000;
        const pct = j.state === "done" ? 100 : j.eta_s ? Math.min(95, (el / j.eta_s) * 100) : 0;
        return (
          <div key={j.id} className={`v3e-job ${j.state} ${j.notReady ? "nr" : ""}`}>
            <span className="lb">{j.label}</span>
            <span className="st">{j.notReady ? "后端未就绪" : ST[j.state] ?? j.state}</span>
            <span className="gp">{gpuLabel(j.gpu)}</span>
            {live && (
              <span className="tm">
                已 {fmtSec(el)} / 预计约 {fmtSec(j.eta_s)}
              </span>
            )}
            <span className="bar">
              <i style={{ width: `${pct}%` }} />
            </span>
            {j.error && <span className="er" title={j.error}>{j.error}</span>}
            {live ? (
              <button
                className="v3e-btn sm"
                onClick={async () => {
                  const err = await cancelJob(j.id);
                  notify(err ? `取消失败：${err}` : "已取消", err ? "err" : "ok");
                }}
              >
                取消
              </button>
            ) : (
              <button className="v3e-x sm" onClick={() => dismissJob(j.id)} aria-label="移除">
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
