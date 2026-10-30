import { useEffect, useState } from "react";
import { api } from "../api";
import type { SopBlocker, SopEpisode, SopOwnerAction, SopShot } from "../types";

/** SOP 阶段 S1→S5（docs/SOP_production.md ★）：上游没过就不进下游。只读：项目方关口只给命令，画布从不代为接受 */

export const SOP_STAGES = ["S1", "S2", "S3", "S4", "S5"] as const;
const ACTOR = { owner: "项目方", gpu3: "gpu3", laptop: "笔记本" } as const;

/** 本集 SOP 状态：换集时取一次，之后每 30 秒刷新（状态表 / gpu3 镜像由别的进程更新） */
export function useSopEpisode(n: number | undefined): { sop: SopEpisode | null; error: string | null } {
  const [sop, setSop] = useState<SopEpisode | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (n == null) return;
    let alive = true;
    setSop(null);
    const load = () =>
      api.sopEpisode(n).then(
        (d) => alive && (setSop(d), setError(null)),
        (e: Error) => alive && setError(e.message),
      );
    void load();
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [n]);
  return { sop, error };
}

function blockerLines(bs: SopBlocker[]): string {
  return bs.map((b) => `· [${ACTOR[b.actor] ?? b.actor}] ${b.text}${b.cli ? `\n    命令：${b.cli}` : ""}`).join("\n");
}

/** 本集阶段条：S1 剧本 → S2 资产 → S3 画面 → S4 视频 → S5 成片，每段写停在这里的镜头数 */
export function SopStageBar({ sop, error, onOwner, ownerOpen }: { sop: SopEpisode | null; error: string | null; onOwner: () => void; ownerOpen: boolean }) {
  if (error) return <div className="sop-bar muted small">SOP 阶段读取失败：{error}（API 需要重启才有 /api/sop）</div>;
  if (!sop) return <div className="sop-bar muted small">SOP 阶段加载中…</div>;
  const cur = sop.stage;
  const curIdx = cur === "done" ? 5 : SOP_STAGES.indexOf(cur);
  const owner = sop.owner_actions.filter((a) => a.actionable).length;
  return (
    <div className="sop-bar">
      <span className="sop-k" title="SOP ★：镜头和集两级判断，上游阶段的出口闸门没过就不进下游">SOP</span>
      <ol className="sop-steps">
        {sop.stages.map((s, i) => {
          const here = sop.blocker_summary.filter((b) => b.stage === s.id);
          const state = i < curIdx ? "past" : i === curIdx ? "cur" : "todo";
          return (
            <li
              key={s.id}
              className={`sop-step sop-${state}`}
              title={`${s.id} ${s.label}：停在这里 ${s.shots_here} 镜${here.length ? `\n${blockerLines(here)}` : ""}`}
            >
              <b>{s.id}</b> {s.label}
              {s.shots_here > 0 && <span className="sop-n">{s.shots_here}</span>}
            </li>
          );
        })}
      </ol>
      {cur === "done" ? (
        <span className="r-ok">本集已完成并验收</span>
      ) : (
        <span className="sop-why muted small" title={blockerLines(sop.blocker_summary)}>
          本集停在 {cur} {sop.stage_label}
          {sop.blocker_summary[0] && <>：{sop.blocker_summary[0].text}</>}
        </span>
      )}
      <span className="grow" />
      <button className={`btn sop-owner-btn${owner ? " has" : ""}${ownerOpen ? " on" : ""}`} onClick={onOwner} title="只列项目方本人要拍板的事，每条附命令；画布不会替你接受">
        待你决定{owner ? ` ${owner}` : ""}
      </button>
    </div>
  );
}

function Cli({ cmd }: { cmd: string }) {
  const [ok, setOk] = useState(false);
  return (
    <div className="sop-cli">
      <code>{cmd}</code>
      <button
        className="btn-mini"
        onClick={() => void navigator.clipboard?.writeText(cmd).then(() => (setOk(true), setTimeout(() => setOk(false), 1200)))}
        title="复制命令：把 <项目方原话> 换成你的原话后在仓库根目录运行"
      >
        {ok ? "已复制" : "复制"}
      </button>
    </div>
  );
}

/** 「待你决定」：G3 采纳、造型确认、底板确认、G4 样片锁定、G5 成片验收——只显示命令，不提供代办按钮 */
export function OwnerPanel({ actions }: { actions: SopOwnerAction[] }) {
  if (!actions.length) return <div className="sop-owner muted small">目前没有需要你拍板的事。</div>;
  const sorted = [...actions].sort((a, b) => Number(b.actionable) - Number(a.actionable));
  return (
    <div className="sop-owner">
      <div className="muted small">以下关口只能由你本人决定：在仓库根目录运行命令（把 &lt;项目方原话&gt; 换成你的原话）。系统从不自动接受。</div>
      {sorted.map((a, i) => (
        <div key={i} className={`sop-act${a.actionable ? "" : " waiting"}`}>
          <div className="sop-act-head">
            <span className="chip">{a.stage}</span>
            <b>{a.title}</b>
            {!a.actionable && <span className="chip chip-warn">先等上游</span>}
          </div>
          {a.why && <div className="muted small">{a.why}</div>}
          {a.waiting_on.length > 0 && <div className="small r-warn">等：{a.waiting_on.join("；")}</div>}
          {a.cli && <Cli cmd={a.cli} />}
          {a.cli_all && a.cli_all !== a.cli && (
            <details className="small">
              <summary>一次确认全部未确认的集</summary>
              <Cli cmd={a.cli_all} />
            </details>
          )}
          {a.cli_rework && (
            <details className="small">
              <summary>退回返工</summary>
              <Cli cmd={a.cli_rework} />
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

/** 镜头行的阶段 / 阻塞小标签：颜色 = 谁来做（项目方 / gpu3 / 笔记本） */
export function SopChip({ s }: { s?: SopShot }) {
  if (!s) return null;
  const done = s.blockers.length === 0;
  const actors = [...new Set(s.blockers.map((b) => b.actor))];
  const lead = actors.includes("owner") ? "owner" : actors[0];
  const title =
    `SOP：本镜停在 ${s.stage} ${s.stage_label}` +
    (done ? "（S1–S4 全过）" : `，${s.blockers.length} 项未过：\n${blockerLines(s.blockers)}`) +
    (s.ahead_of_gate.length ? `\n\n注意：${s.ahead_of_gate.join("；")}` : "");
  return (
    <span className={`chip sop-chip ${done ? "sop-done" : `sop-by-${lead}`}`} title={title} onClick={(e) => e.stopPropagation()}>
      {s.stage} {s.stage_label}
      {!done && (
        <>
          {" · "}
          {s.blockers.length} 项{actors.includes("owner") ? " · 待你" : ` · ${ACTOR[lead as keyof typeof ACTOR] ?? lead}`}
        </>
      )}
      {s.ahead_of_gate.length > 0 && " ⚠"}
    </span>
  );
}
