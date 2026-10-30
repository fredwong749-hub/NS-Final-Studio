// 进度看板：每集一行 8 个状态灯（剧本 / 首帧 / 尾帧 / 视频 / QA / 声音 / 4K / 成片）、异常队列、ETA、GPU 占用
import { useCallback, useEffect, useState } from "react";
import { InboxList } from "./InboxView";
import { fmtDur, go, papi, type Board, type GpuInfo, type Light } from "./papi";

const LIGHTS = ["剧本", "首帧", "尾帧", "视频", "QA", "声音", "4K", "成片"];
const STATUS_TEXT: Record<string, string> = {
  done: "完成", running: "进行中", waiting: "等待", pending: "未开始", failed: "失败", blocked: "异常", gate: "待验收",
};

function Lamp({ l }: { l: Light | undefined }) {
  const s = l?.status ?? "pending";
  const prog = l?.total ? `${l.done ?? 0}/${l.total}` : "";
  return (
    <span className={`lamp lamp-${s}`} title={`${STATUS_TEXT[s] ?? s}${prog ? ` ${prog}` : ""}${l?.detail ? `\n${l.detail}` : ""}`}>
      <i />
      {prog && s !== "done" ? <em className="tnum">{prog}</em> : null}
    </span>
  );
}

function GpuPanel({ g }: { g: GpuInfo | null }) {
  if (!g) return <div className="bd-gpu muted small">读取 GPU…</div>;
  const lp = g.laptop;
  return (
    <div className="bd-gpu">
      <div className="bd-gpu-row">
        <b>笔记本</b>
        {lp.reachable ? (
          <>
            <span className="chip">{lp.gpu?.replace(/^cuda:\d+\s*/, "").slice(0, 28) ?? "ComfyUI"}</span>
            <span className="chip">运行 {lp.running} · 排队 {lp.pending}</span>
            {lp.vram_total_mb ? (
              <span className="bd-bar" title={`${lp.vram_used_mb}/${lp.vram_total_mb} MB`}>
                <i style={{ width: `${Math.round(((lp.vram_used_mb ?? 0) / lp.vram_total_mb) * 100)}%` }} />
              </span>
            ) : null}
          </>
        ) : (
          <span className="chip chip-warn">ComfyUI 未开</span>
        )}
        <span className="muted small">只出图片（规则 7）</span>
      </div>
      <div className="bd-gpu-row">
        <b>gpu3</b>
        {!g.gpu3.reachable && <span className="chip chip-warn" title={g.gpu3.error}>桥不可达</span>}
        {g.gpu3.simulated && <span className="chip chip-busy">演练（模拟）</span>}
        {g.gpu3.gpus.map((x) => (
          <span key={x.id} className={`bd-card${x.faulty ? " faulty" : x.busy_by ? " busy" : ""}`}
            title={x.faulty ? "坏卡，永不使用" : `${x.task ?? "空闲"}${x.vram_total_mb ? `\n${x.vram_used_mb}/${x.vram_total_mb} MB` : ""}`}>
            GPU{x.id}
            <small>{x.faulty ? "坏卡" : x.busy_by ? `${x.busy_by}${x.util != null ? ` ${x.util}%` : ""}` : "空闲"}</small>
          </span>
        ))}
      </div>
    </div>
  );
}

export function BoardView({ slug }: { slug: string }) {
  const [b, setB] = useState<Board | null>(null);
  const [gpu, setGpu] = useState<GpuInfo | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    papi.board(slug).then(setB, (e: Error) => setErr(e.message));
    papi.gpus(slug).then(setGpu, () => {});
  }, [slug]);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, [load]);
  const run = (p: Promise<Board>) => {
    setBusy(true);
    setErr("");
    p.then(setB, (e: Error) => setErr(e.message)).finally(() => setBusy(false));
  };
  if (!b) return <div className="empty">{err || "加载中…"}</div>;
  const pj = b.project;
  const totals = LIGHTS.map((k) => b.episodes.filter((r) => r.lights[k]?.status === "done").length);
  return (
    <div className="pj-page bd">
      <div className="pj-head">
        <h2>{pj.name}</h2>
        <span className="chip">{pj.is_default ? "现有项目（只读看板）" : `projects/${pj.slug}/`}</span>
        {pj.running ? (
          <span className="chip chip-busy">{pj.mode === "dry_run" ? "演练中" : "生产中"} · 自 {pj.started_at}</span>
        ) : (
          pj.started_at && <span className="chip chip-warn">已暂停</span>
        )}
        <span className="grow" />
        {pj.can_start && !pj.running && (
          <>
            {pj.mode !== "real" && (
              <button className="btn" disabled={busy} onClick={() => run(papi.start(slug, "dry_run"))} title="不出图、不交 gpu3：用模拟 gpu3 走一遍流程">
                演练
              </button>
            )}
            {pj.mode !== "dry_run" && (
              <button className="btn primary big" disabled={busy} onClick={() => {
                if (window.confirm("开始正式生产？笔记本会按集出非成人首帧/尾帧；成人画面与视频要在「待办」授权后才交 gpu3。")) run(papi.start(slug, "real"));
              }}>
                ▶ 开始生产
              </button>
            )}
          </>
        )}
        {pj.running && (
          <>
            <button className="btn" disabled={busy} onClick={() => run(papi.tick(slug))} title="立即推进一步（后台每 20 秒自动推进）">
              立即推进
            </button>
            <button className="btn" disabled={busy} onClick={() => run(papi.pause(slug))}>
              ⏸ 暂停
            </button>
          </>
        )}
      </div>
      {err && <div className="banner">{err}</div>}
      <div className="bd-top">
        <div className="bd-eta">
          <span className="muted small">预计完成</span>
          <b className="tnum">{fmtDur(b.eta.total_s)}</b>
          <span className="muted small" title={b.eta.note}>
            笔记本 {fmtDur(b.eta.laptop_s)} · gpu3 {fmtDur(b.eta.gpu3_s)}
          </span>
        </div>
        {b.gates.length > 0 ? (
          <div className="bd-gates">
            {b.gates.map((g) => (
              <span key={g.id} className={`bd-gate ${g.status}`} title={g.decided_by ? `${g.decided_by} · ${g.decided_at}` : g.status}>
                {g.id !== "GPU3" && <b>{g.id}</b>} {g.title}
              </span>
            ))}
          </div>
        ) : (
          <div className="bd-gates muted small">{pj.is_default ? "现有项目不走编排关口；灯来自 data/renders 与 gpu3 桥" : "开始生产后显示关口 G2–G5"}</div>
        )}
        <GpuPanel g={gpu} />
      </div>

      {b.cards.length > 0 && (
        <div className="bd-section">
          <div className="bd-section-head">
            <b>待办 {b.cards.length}</b>
            <span className="muted small">关口之后的步骤在点之前不会运行</span>
          </div>
          <InboxList cards={b.cards} reload={load} />
        </div>
      )}

      <div className="bd-main">
        <div className="bd-table-wrap">
          <table className="bd-table">
            <thead>
              <tr>
                <th>集</th>
                <th className="bd-title">标题</th>
                {LIGHTS.map((k, i) => (
                  <th key={k} className="bd-lamp-h">
                    {k}
                    <small className="tnum">{totals[i]}/{b.episodes.length}</small>
                  </th>
                ))}
                <th>当前</th>
                <th>预计</th>
              </tr>
            </thead>
            <tbody>
              {b.episodes.map((r) => (
                <tr key={r.number} className={r.accept === "done" ? "published" : ""}>
                  <td className="tnum">ep{String(r.number).padStart(2, "0")}</td>
                  <td className="bd-title">
                    {r.title} <span className="muted small">{r.shots} 镜{r.adult_shots ? ` · 成人 ${r.adult_shots}` : ""}</span>
                  </td>
                  {LIGHTS.map((k) => (
                    <td key={k} className="bd-lamp-c">
                      <Lamp l={r.lights[k]} />
                    </td>
                  ))}
                  <td className="small">{r.accept === "done" ? "已发布" : r.current ?? "—"}</td>
                  <td className="tnum small">{fmtDur(r.eta_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!b.episodes.length && <div className="empty">还没有导入剧本</div>}
          <div className="bd-legend muted small">
            {["done", "running", "waiting", "gate", "failed", "pending"].map((s) => (
              <span key={s}>
                <Lamp l={{ status: s }} /> {STATUS_TEXT[s]}
              </span>
            ))}
          </div>
        </div>
        <aside className="bd-side">
          <div className="bd-section-head">
            <b>异常队列 {b.exceptions.length}</b>
            <span className="muted small">同一步骤失败 3 次进入；不阻塞其他集</span>
          </div>
          {b.exceptions.length === 0 && <div className="muted small bd-none">无</div>}
          {b.exceptions.slice(0, 40).map((x, i) => (
            <div key={i} className={`bd-exc ${x.status}`}>
              <div>
                <b>{x.episode ? `ep${String(x.episode).padStart(2, "0")}` : "项目"}</b> {x.label}
                <span className={`chip ${x.source === "gpu3" ? "chip-busy" : "chip-accent"}`}>{x.source === "gpu3" ? "gpu3" : "笔记本"}</span>
                {x.attempts ? <span className="muted small"> 第 {x.attempts} 次</span> : null}
                {x.retryable && (
                  <button className="btn-mini" onClick={() => run(papi.retry(slug, x.episode, x.step))}>
                    重试
                  </button>
                )}
              </div>
              <div className="muted small bd-err">{x.error}</div>
            </div>
          ))}
          <div className="bd-section-head">
            <b>日志</b>
          </div>
          {b.log.map((l, i) => (
            <div key={i} className="bd-log">
              <span className="muted tnum">{l.at.slice(11)}</span> {l.msg}
            </div>
          ))}
          {pj.is_default && (
            <button className="btn ghost" onClick={() => go("#/")}>
              打开《为他而骚》画布
            </button>
          )}
        </aside>
      </div>
    </div>
  );
}
