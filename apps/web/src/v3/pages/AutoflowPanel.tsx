// UIRSI r43（总调度 02:5x：#/script-create 加“全流程自动”入口；HOLLYWOOD r8 后端 services/api/ns_api/script_autoflow.py，L-104 第二季 series10_s2）
// 整洁规格（K-UI-049）：中性色；每段一行 = 状态点 + 名称 + 谁判定 + 花费 + 分数；失败项点开看；一键返修、一键导入（导入只在 verdict=importable 时可点）。
// 剧目切换：多剧并行（新剧本是新的 run，不替换 series10）——列出有 autoflow.json 的运行目录（/api/story-runs 列表逐个问 /api/script-autoflow/{id}）。
// 接口：GET /api/script-autoflow/{id}（nsfs.autoflow/1）；POST …/repair、…/import，body {episode, budget_usd?, import_mode}。
import { useCallback, useEffect, useState } from "react";
import { useStudio } from "../../store";
import { useLiveEvent } from "../live";

type AStage = { id: string; name: string; status: string; decider?: string; usd?: number | null; detail?: string[] | string; fails?: number; rounds?: number };
type AScore = { at: string; sum: number; judge_sums?: number[]; noise_stop?: { stop?: boolean } };
type AEp = { verdict: string; usd_total: number | null; score: number | null; code_fails: number | null; next_action?: string | null };
type AFlow = {
  run?: string; episode?: number; verdict: string; next_action?: string | null; running?: boolean; stages?: AStage[]; score_trajectory?: AScore[];
  usd_total?: number | null; budget_usd?: number | null; import_mode?: string; episodes?: Record<string, AEp>; season_usd?: number | null; latest_episode?: number;
};

const VERDICT: Record<string, string> = {
  not_started: "还没开始", running: "正在写", stopped_in_chain: "写作链中途停了", not_importable: "还不能导入（有没过的项）",
  blocked_by_gate: "导入闸门没过", importable: "可以导入", imported: "已导入",
};
const DECIDER: Record<string, string> = { code: "代码判定", api_model: "写作模型", owner: "你" };
const SEASON_BUDGET = 8; // HOLLYWOOD：第二季整季预算 $8
const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);
// 三种状态点（同总览）：在跑=蓝点呼吸、需要人看 / 没过=琥珀、通过=绿；其他不画点
function dot(status: string, running: boolean): "run" | "need" | "ok" | null {
  if (status === "running" || (running && status === "pending")) return "run";
  if (["ok", "reused", "pass", "passed", "importable", "imported"].includes(status)) return "ok";
  if (["fails_left", "failed", "fail", "blocked", "needs_writer", "stopped", "error", "not_importable", "blocked_by_gate", "stopped_in_chain"].includes(status)) return "need";
  return null;
}

async function listAutoflowRuns(): Promise<string[]> {
  const r = await fetch("/api/story-runs?limit=60").then((x) => (x.ok ? x.json() : { runs: [] }));
  const ids: string[] = (r.runs ?? []).map((x: { id: string }) => x.id);
  const ok = await Promise.all(
    ids.map((id) =>
      fetch(`/api/script-autoflow/${encodeURIComponent(id)}`)
        .then((x) => (x.ok ? (x.json() as Promise<AFlow>) : null))
        .then((d) => (d && d.verdict !== "not_started" ? id : null))
        .catch(() => null),
    ),
  );
  return ok.filter((x): x is string => !!x);
}

export function AutoflowPanel() {
  const st = useStudio();
  const [runs, setRuns] = useState<string[] | null>(null);
  const [run, setRun] = useState<string>("");
  const [d, setD] = useState<AFlow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set(["code"]));
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    listAutoflowRuns()
      .then((ids) => {
        setRuns(ids);
        setRun((r) => r || ids.find((x) => x === "series10_s2") || ids[0] || "");
      })
      .catch(() => setRuns([]));
  }, []);
  const load = useCallback(() => {
    if (!run) return;
    fetch(`/api/script-autoflow/${encodeURIComponent(run)}`)
      .then((r) => (r.ok ? (r.json() as Promise<AFlow>) : Promise.reject(new Error(r.status === 404 ? "接口还没上线（:8800 待重启）" : `HTTP ${r.status}`))))
      .then((x) => (setD(x), setErr(null)), (e: Error) => setErr(e.message));
  }, [run]);
  useEffect(() => {
    load();
    const t = window.setInterval(load, d?.running ? 5000 : 20000);
    return () => window.clearInterval(t);
  }, [load, d?.running]);
  useLiveEvent((e) => e.type === "stage" || e.type === "tick", load, 2000);
  const ep = d?.episode ?? d?.latest_episode ?? 1;
  const isSeason = !!d?.episodes;
  const importBlocked = run === "series10_s2" && d?.import_mode !== "live";
  const post = (what: "repair" | "import") => {
    setBusy(true);
    fetch(`/api/script-autoflow/${encodeURIComponent(run)}/${what}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episode: ep, budget_usd: d?.budget_usd ?? undefined, import_mode: what === "import" ? "live" : d?.import_mode ?? "dry" }) })
      .then(async (r) => {
        const t = await r.text();
        if (!r.ok) throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
        st.notify(what === "repair" ? `已开始返修第 ${ep} 集（通过的段直接复用，从卡住的地方接着写）` : `已开始导入第 ${ep} 集`);
        load();
      })
      .catch((e: Error) => st.notify(`${what === "repair" ? "返修" : "导入"}没开始：${e.message}`, "err"))
      .finally(() => setBusy(false));
  };
  const last = d?.score_trajectory?.[d.score_trajectory.length - 1];
  return (
    <section className="af" aria-label="全流程自动">
      <header className="af-head">
        <b className="af-title">全流程自动</b>
        <span className="af-sub">提纲 → 故事线 → 大纲 → 剧本 → 分镜 → 代码判定与补丁 → 打分 → 导入闸门</span>
        <span className="grow" />
        <label className="af-run">
          剧目
          <select value={run} onChange={(e) => setRun(e.target.value)} disabled={!runs?.length}>
            {(runs ?? []).map((id) => (
              <option key={id} value={id}>
                {id === "series10_s2" ? "第二季 series10_s2" : id}
              </option>
            ))}
          </select>
        </label>
      </header>
      {runs == null ? (
        <p className="af-muted">读取中…</p>
      ) : !runs.length ? (
        <p className="af-muted">{err ?? "还没有全流程自动的运行（接口还没上线时 :8800 需重启）"}</p>
      ) : err ? (
        <p className="af-muted">{err}</p>
      ) : d ? (
        <>
          <p className="af-verdict">
            {(() => { const k = dot(d.verdict, !!d.running); return k ? <i className={`sea-dot d-${k}${k === "run" ? " is-rendering" : ""}`} aria-hidden /> : null; })()}
            <b>{d.running ? "正在写" : VERDICT[d.verdict] ?? d.verdict}</b>
            <span className="af-muted"> · 第 {ep} 集 · 花费 {usd(d.usd_total)}{d.budget_usd != null ? ` / ${usd(d.budget_usd)}` : ""}{last ? ` · 分数 ${last.sum}` : ""}{d.next_action ? ` · 下一步：${d.next_action}` : ""}</span>
          </p>
          {isSeason && (
            <div className="af-block">
              <h5>整季 · 花费 {usd(d.season_usd)} / ${SEASON_BUDGET}</h5>
              <table className="af-table">
                <thead>
                  <tr><th>集</th><th>结论</th><th>分数</th><th>失败项</th><th>花费</th></tr>
                </thead>
                <tbody>
                  {Object.entries(d.episodes!).sort((a, b) => Number(a[0]) - Number(b[0])).map(([n, e]) => (
                    <tr key={n}>
                      <td>第 {n} 集</td>
                      <td>
                        {(() => { const k = dot(e.verdict, false); return k ? <i className={`sea-dot d-${k}${k === "run" ? " is-rendering" : ""}`} aria-hidden /> : null; })()} {VERDICT[e.verdict] ?? e.verdict}
                      </td>
                      <td>{e.score ?? "—"}</td>
                      <td>{e.code_fails ?? "—"}</td>
                      <td>{usd(e.usd_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="af-block">
            <h5>各段{isSeason ? `（第 ${ep} 集）` : ""}</h5>
            <ul className="af-stages">
              {(d.stages ?? []).map((s) => {
                const k = dot(s.status, !!d.running);
                const det = Array.isArray(s.detail) ? s.detail : s.detail ? [s.detail] : [];
                const can = det.length > 0;
                const on = open.has(s.id);
                return (
                  <li key={s.id}>
                    <button type="button" className="af-row" disabled={!can} aria-expanded={can ? on : undefined}
                      onClick={() => setOpen((o) => { const x = new Set(o); if (x.has(s.id)) x.delete(s.id); else x.add(s.id); return x; })}>
                      <span className="af-dot">{k ? <i className={`sea-dot d-${k}${k === "run" ? " is-rendering" : ""}`} aria-hidden /> : null}</span>
                      <span className="af-name">{s.name}</span>
                      <span className="af-who">{DECIDER[s.decider ?? ""] ?? s.decider ?? ""}</span>
                      <span className="af-st">{s.fails ? `${s.fails} 项没过` : s.status === "reused" ? "复用" : s.status === "ok" ? "通过" : VERDICT[s.status] ?? s.status}</span>
                      <span className="af-usd">{s.usd != null ? usd(s.usd) : ""}</span>
                      <span className="af-more">{can ? (on ? "▴" : "▾") : ""}</span>
                    </button>
                    {can && on && (
                      <ol className="af-det">
                        {det.map((x, i) => (
                          <li key={i} title={x}>{x}</li>
                        ))}
                      </ol>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
          {!!d.score_trajectory?.length && (
            <div className="af-block">
              <h5>分数轨迹</h5>
              <table className="af-table">
                <thead>
                  <tr><th>时间</th><th>总分</th><th>各评委</th><th>稳定</th></tr>
                </thead>
                <tbody>
                  {d.score_trajectory.map((t, i) => (
                    <tr key={i}>
                      <td>{t.at.slice(11, 16)}</td>
                      <td>{t.sum}</td>
                      <td className="af-muted">{(t.judge_sums ?? []).join(" · ")}</td>
                      <td className="af-muted">{t.noise_stop?.stop ? "已稳定" : "继续"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <footer className="af-foot">
            <button type="button" className="v3-btn" disabled={busy || !!d.running} onClick={() => post("repair")} title="已通过的段直接复用，从卡住的地方接着写（花费计入预算）">
              一键返修
            </button>
            <button type="button" className="v3-btn primary" disabled={busy || !!d.running || d.verdict !== "importable" || importBlocked} onClick={() => post("import")}
              title={importBlocked ? "第二季导入目标待 WORKFLOW / PRODUCER 接 --run" : d.verdict !== "importable" ? `还不能导入：${VERDICT[d.verdict] ?? d.verdict}` : "导入这一集（你确认的唯一一步，L-098）"}>
              一键导入
            </button>
            {importBlocked && <span className="af-muted">第二季导入目标待 WORKFLOW / PRODUCER 接 --run</span>}
          </footer>
        </>
      ) : (
        <p className="af-muted">读取中…</p>
      )}
    </section>
  );
}
