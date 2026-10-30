import { useRef, useState } from "react";
import { useStudio, type DrawerTab } from "../store";
import { fmtTime, JOB_LABEL, segDiff, STAGE_LABEL } from "../util";
import { PersonRow } from "./ShotCard";
import type { Job, Stage } from "../types";
import { seamState } from "./Seam";

const TABS: [DrawerTab, string][] = [
  ["jobs", "任务队列"],
  ["batch", "批量结果"],
  ["compare", "A/B 对比"],
  ["seam", "接缝对比"],
];

function waitText(w: NonNullable<Job["comfy_wait"]>) {
  if (w.who === "offline") return `等待：${w.what ?? "本机 ComfyUI 未启动"}，启动后自动继续`;
  return `等待 ComfyUI：${w.who === "orchestrator" ? "编排器" : w.who} 正在用${w.what ? `（${w.what}）` : ""}`;
}

/** T54-B / 调研 #5：每个 镜头×阶段 只看最新一次任务，最新一次失败的按阶段汇总，一键重试（仍走批量确认框） */
function FailedRetry() {
  const { jobs, requestBatch } = useStudio();
  const newest = new Map<string, Job>();
  for (const j of jobs) {
    if (j.stage === "asset" || j.shot_id.startsWith("asset:")) continue;
    const k = `${j.shot_id}|${j.stage}`;
    const o = newest.get(k);
    if (!o || j.created_at > o.created_at) newest.set(k, j);
  }
  const failed = new Map<Stage, string[]>();
  for (const j of newest.values()) if (j.state === "failed" && j.stage !== "asset") failed.set(j.stage, [...(failed.get(j.stage) ?? []), j.shot_id]);
  if (!failed.size) return null;
  return (
    <div className="batch-retry">
      <span className="bad">最近失败：</span>
      {[...failed].map(([stage, ids]) => (
        <button key={stage} className="btn-mini" onClick={() => requestBatch(ids, stage)} title={ids.join("\n")}>
          重试失败{STAGE_LABEL[stage]} {ids.length} 镜
        </button>
      ))}
    </div>
  );
}

function Jobs() {
  const { jobs, select } = useStudio();
  if (!jobs.length) return <div className="muted pad">本次服务启动后还没有任务（命令行批跑不经过此队列）。</div>;
  return (
    <>
    <FailedRetry />
    <table className="jobs">
      <thead>
        <tr>
          <th>任务</th>
          <th>镜头</th>
          <th>阶段</th>
          <th>种子</th>
          <th>状态</th>
          <th>提交</th>
          <th>错误</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id} className={`job-${j.state}`}>
            <td className="tnum">{j.id}</td>
            <td>
              {j.shot_id.startsWith("asset:") ? j.shot_id : <a onClick={() => select(j.shot_id)}>{j.shot_id}</a>}
            </td>
            <td>{STAGE_LABEL[j.stage]}</td>
            <td className="tnum">{j.seed ?? "—"}</td>
            <td>
              {JOB_LABEL[j.state]}
              {j.take != null && ` → #${j.take}`}
            </td>
            <td className="tnum">{fmtTime(j.created_at)}</td>
            <td className="err-cell" title={j.error ?? j.comfy_wait?.error ?? ""}>
              {j.error ?? (j.comfy_wait ? waitText(j.comfy_wait) : "")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </>
  );
}

function Batch() {
  const { batchResults, select } = useStudio();
  if (!batchResults) return <div className="muted pad">还没有批量操作</div>;
  const ok = batchResults.results.filter((r) => r.ok).length;
  return (
    <div className="pad">
      <div>
        {fmtTime(batchResults.at)} 批量{STAGE_LABEL[batchResults.stage]}：成功 {ok} / {batchResults.results.length}
      </div>
      <ul className="plain">
        {batchResults.results.map((r) => (
          <li key={r.shot_id} className={r.ok ? "" : "bad"}>
            <a onClick={() => select(r.shot_id)}>{r.shot_id}</a>：{r.ok ? `已入队 ${r.job?.id ?? ""}` : r.error}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Compare() {
  const { compare, details } = useStudio();
  const ra = useRef<HTMLVideoElement>(null);
  const rb = useRef<HTMLVideoElement>(null);
  if (!compare) return <div className="muted pad">在检查器「版本」里勾选两个版本后点 A/B 对比（或按 C）。</div>;
  const d = details[compare.shotId];
  const ta = d?.takes.takes.find((t) => t.stage === compare.stage && t.n === compare.a);
  const tb = d?.takes.takes.find((t) => t.stage === compare.stage && t.n === compare.b);
  if (!ta || !tb) return <div className="muted pad">版本不存在</div>;
  const both = (fn: (v: HTMLVideoElement) => void) => [ra, rb].forEach((r) => r.current && fn(r.current));
  return (
    <div className="compare">
      <div className="compare-media">
        {[ta, tb].map((t, i) => (
          <figure key={t.n}>
            {compare.stage === "video" ? (
              <video ref={i ? rb : ra} src={t.url ?? undefined} muted playsInline loop />
            ) : (
              <img src={t.url ?? undefined} alt="" />
            )}
            <figcaption>
              {compare.shotId} {i ? "B" : "A"} · #{t.n} · 种 {t.seed}
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="compare-side">
        {compare.stage === "video" && (
          <div className="row-actions">
            <button
              className="btn"
              onClick={() =>
                both((v) => {
                  v.currentTime = 0;
                  void v.play();
                })
              }
            >
              同步播放
            </button>
            <button className="btn" onClick={() => both((v) => v.pause())}>
              暂停
            </button>
          </div>
        )}
        <div className="sub-title">提示词差异（A → B）</div>
        <div className="diff">
          {segDiff(ta.prompt, tb.prompt).map((p, i) => (
            <span key={i} className={`d-${p.op}`}>
              {p.text}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function SeamCompare() {
  const { seam, summaryById, details, openAssets } = useStudio();
  const [mix, setMix] = useState(50);
  const [mode, setMode] = useState<"split" | "fade">("split");
  if (!seam) return <div className="muted pad">点击两张卡片之间的衔接标记打开接缝对比。</div>;
  const a = summaryById.get(seam.from);
  const b = summaryById.get(seam.to);
  if (!a || !b) return null;
  const st = seamState(a, b);
  const target = a.last_frame_target;
  const actual = a.last_frame_actual;
  void details;
  return (
    <div className="seam-compare">
      <div className="row-actions">
        <b>
          {a.id} 尾帧 ⟶ {b.id} 首帧
        </b>
        <span className={`seam-dot seam-${st.state}`} /> {st.title}
        <span className="grow" />
        <button className={`btn-mini${mode === "split" ? " on" : ""}`} onClick={() => setMode("split")}>
          左右
        </button>
        <button className={`btn-mini${mode === "fade" ? " on" : ""}`} onClick={() => setMode("fade")}>
          叠化
        </button>
        {mode === "fade" && <input type="range" min={0} max={100} value={mix} onChange={(e) => setMix(Number(e.target.value))} />}
      </div>
      {mode === "split" ? (
        <div className="compare-media">
          <figure>
            {target ? <img src={target} alt="" /> : <div className="thumb-empty">{a.id} 没有目标尾帧</div>}
            <figcaption>{a.id} 目标尾帧（{a.last_frame_source ?? "未设"}）</figcaption>
          </figure>
          <figure>
            {actual ? <img src={actual} alt="" /> : <div className="thumb-empty">{a.id} 还没有视频</div>}
            <figcaption>{a.id} 实际尾帧（视频抽帧）</figcaption>
          </figure>
          <figure>
            {b.first_frame ? <img src={b.first_frame} alt="" /> : <div className="thumb-empty">{b.id} 还没有首帧</div>}
            <figcaption>{b.id} 首帧</figcaption>
          </figure>
        </div>
      ) : (
        <div className="fade-box">
          {(target ?? actual) && <img src={(target ?? actual)!} alt="" />}
          {b.first_frame && <img src={b.first_frame} alt="" style={{ opacity: mix / 100 }} />}
        </div>
      )}
      <div className="seam-looks">
        <div>
          <b>{a.id}</b>
          {a.characters.map((c) => (
            <PersonRow key={c.character} c={c} hl={false} onFace={() => openAssets({ character: c.character, lookId: c.look_id })} />
          ))}
        </div>
        <div>
          <b>{b.id}</b>
          {b.characters.map((c) => (
            <PersonRow key={c.character} c={c} hl={false} onFace={() => openAssets({ character: c.character, lookId: c.look_id })} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function Drawer() {
  const { drawer, setDrawer } = useStudio();
  if (!drawer.open) return null;
  return (
    <section className="drawer">
      <div className="drawer-tabs">
        {TABS.map(([t, l]) => (
          <button key={t} className={drawer.tab === t ? "on" : ""} onClick={() => setDrawer({ open: true, tab: t })}>
            {l}
          </button>
        ))}
        <span className="grow" />
        <button className="btn-mini" onClick={() => setDrawer({ ...drawer, open: false })}>
          收起
        </button>
      </div>
      <div className="drawer-body">
        {drawer.tab === "jobs" && <Jobs />}
        {drawer.tab === "batch" && <Batch />}
        {drawer.tab === "compare" && <Compare />}
        {drawer.tab === "seam" && <SeamCompare />}
      </div>
    </section>
  );
}
