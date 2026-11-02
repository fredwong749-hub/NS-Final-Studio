// V2-WALK W-01 / W-07：新建剧本页的“写作流程”面板（唯一的写作入口 = /api/script-autoflow；下方提纲表单只负责写提纲，不再单独起写作）。
// 版式参考小云雀：步骤 tab（故事线 · 造型表 · 各集）、结果卡下固定两个按钮（用这版 / 修改）、提交前显示花费；每集只有三种状态（写作中 / 等你看 / 完成）+ 一键重试。
// 界面只写中文大白话：英文状态词一律翻译；颜色只用灰 / 琥珀 / 绿；规则编号、文件名收进“详情”。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store";
import { useLiveEvent } from "../live";
import { P1Gate, ReviewBlock, canShowP1, p1Round, p1Status } from "./P1Review";

type AStage = { id: string; name: string; status: string; decider?: string; usd?: number | null; detail?: string[] | string; fails?: number };
type AScore = { at: string; sum?: number; sum_code?: number; of?: number; judge_sums?: number[] };
type AEp = { verdict: string; usd_total: number | null; score: number | null; code_fails: number | null; next_action?: string | null };
type Gate = { status?: string; note?: string; at?: string };
export type AFlow = {
  run?: string; episode?: number; verdict: string; next_action?: string | null; running?: boolean; stages?: AStage[]; score_trajectory?: AScore[];
  usd_total?: number | null; budget_usd?: number | null; import_mode?: string; episodes?: Record<string, AEp>; latest_episode?: number; writer_backend?: string;
  owner_gates?: { enabled?: boolean; gates?: Record<string, Gate> };
  p1_review?: { latest?: Review | null; rounds?: Review[]; threshold?: { min_mean?: number; max_rounds?: number; judges?: number }; revise_options?: string[]; owner_direction?: { at?: string; by?: string; why?: string; round?: number; mean?: number; totals?: number[] } };
};
export type Review = { n: number; passed: boolean; why?: string[]; totals?: number[]; mean?: number; item_mean?: Record<string, number>; top_fixes?: string[] };
type Story = {
  title?: string; premise?: string; world?: { setting?: string; era?: string; rules?: string[] };
  characters?: { name: string; role?: string; age?: number; gender?: string; zh_look?: string }[];
  scenes?: { scene_id: string; name: string; space?: string; time_of_day?: string }[];
  episodes?: { episode: number; title?: string; logline?: string }[];
};
type Look = { id: string; use?: string; zh?: string };
export type LookChar = { name: string; marker?: string; looks?: Look[] };
type RunOpt = { id: string; title: string };

// ---------- 中文词表（W-07）：状态词只在这里翻译，页面上不出现英文状态 ----------
const VERDICT: Record<string, string> = {
  not_started: "还没开始", running: "正在写", awaiting_writer: "等写手交稿", awaiting_reviewer: "等核查", awaiting_owner_p1: "等你看故事线",
  held_by_p1_gate: "等你看完故事线再写", needs_patch: "正在返修", reopened: "重新打开了", stopped_in_chain: "写到一半停了", not_importable: "还有没过的项",
  blocked_by_gate: "导入前的检查没过", importable: "可以导入", imported: "已导入", awaiting_owner: "等你看", owner_direction: "等你定方向", reused: "复用", ok: "通过", pending: "等待",
  fails_left: "还有没过的项", failed: "没过", needs_writer: "等写手", dry_run: "试跑", revise_requested: "已收下修改，正在重写", waiting_p1_review: "评审中", awaiting_p1_judges: "故事线在评审", awaiting_judges: "等评委打分", voided: "已作废，重写中", p1_review_failed: "评审三轮没过，已转总调度",
};
export const zhState = (k?: string | null) => (k ? VERDICT[k] ?? "进行中" : "");
const DECIDER: Record<string, string> = { code: "自动检查", api_model: "写手", agent: "写手", owner: "你" };
const STAGE_NAME: Record<string, string> = { P0: "提纲", P1: "故事线", P1L: "造型表", P1G: "你看故事线", P2: "分集大纲", P3: "单集剧本", P4: "分镜", facts: "事实表", code: "自动检查", factcheck: "事实核查", score: "打分", gate: "导入前检查", import: "导入" };
const money = (v: number | null | undefined) => `$${(v ?? 0).toFixed(2)}`;

// 每集三态：写作中（灰）/ 等你看（琥珀）/ 完成（绿）；卡住的集给“重试”
type EpState = "idle" | "writing" | "look" | "done";
function epState(v: string | undefined, p1Open: boolean): { s: EpState; stuck: boolean } {
  if (p1Open) return { s: "idle", stuck: false }; // 故事线没过闸门前，各集都还没开始（W-28）
  if (!v) return { s: "writing", stuck: false };
  if (["importable", "imported"].includes(v)) return { s: "done", stuck: false };
  if (["awaiting_owner_p1", "held_by_p1_gate", "awaiting_owner"].includes(v)) return { s: "look", stuck: false };
  return { s: "writing", stuck: ["stopped_in_chain", "not_importable", "blocked_by_gate", "failed", "fails_left", "needs_writer"].includes(v) };
}
const EP_WORD: Record<EpState, string> = { idle: "未开始（等故事线定稿）", writing: "写作中", look: "等你看", done: "完成" };

async function listRuns(): Promise<RunOpt[]> {
  const r = await fetch("/api/story-runs?limit=60").then((x) => (x.ok ? x.json() : { runs: [] }));
  const items: { id: string; title?: string; registry_status?: string | null }[] = (r.runs ?? []).filter((x: { id: string; registry_status?: string | null }) => x.registry_status !== "archived" && !/^(drill_|zz_)/.test(x.id));
  const ok = await Promise.all(
    items.map((it) =>
      fetch(`/api/script-autoflow/${encodeURIComponent(it.id)}`)
        .then((x) => (x.ok ? (x.json() as Promise<AFlow>) : null))
        .then((d) => (d && d.verdict !== "not_started" ? it : null))
        .catch(() => null),
    ),
  );
  return ok.filter((x): x is NonNullable<typeof x> => !!x).map((it) => ({ id: it.id, title: it.title || "新剧（未定名）" }));
}
const getJson = <T,>(url: string) => fetch(`${url}?t=${Date.now()}`).then((r) => (r.ok ? (r.json() as Promise<T>) : null)).catch(() => null);

/** 提纲表单提交后通知面板切到这部剧 */
export const FLOW_EVENT = "ns:flowrun";

export function AutoflowPanel() {
  const st = useStudio();
  const [runs, setRuns] = useState<RunOpt[] | null>(null);
  const [run, setRun] = useState<string>("");
  const [d, setD] = useState<AFlow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"story" | "looks" | "review" | "eps">("eps");
  const [story, setStory] = useState<Story | null>(null);
  const [looks, setLooks] = useState<LookChar[] | null>(null);
  const [epTotal, setEpTotal] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);

  const loadRuns = useCallback(
    (pick?: string) =>
      Promise.all([listRuns(), fetch("/api/script-library").then((x) => (x.ok ? x.json() : null)).catch(() => null)])
        .then(([opts, lib]) => {
          const all = pick && !opts.some((o) => o.id === pick) ? [...opts, { id: pick, title: "新剧（未定名）" }] : opts;
          setRuns(all);
          const prim: string | undefined = (lib?.current ?? []).concat(lib?.history ?? []).find((c: { primary?: boolean }) => c.primary)?.run;
          setRun((r) => pick || r || (prim && all.some((o) => o.id === prim) ? prim : "") || all[0]?.id || "");
        })
        .catch(() => setRuns([])),
    [],
  );
  useEffect(() => {
    void loadRuns();
    const on = (e: Event) => void loadRuns((e as CustomEvent<string>).detail);
    window.addEventListener(FLOW_EVENT, on);
    return () => window.removeEventListener(FLOW_EVENT, on);
  }, [loadRuns]);

  const load = useCallback(() => {
    if (!run) return;
    fetch(`/api/script-autoflow/${encodeURIComponent(run)}`)
      .then((r) => (r.ok ? (r.json() as Promise<AFlow>) : Promise.reject(new Error(r.status === 404 ? "这部剧还没有提纲" : "暂时读不到"))))
      .then((x) => (setD(x), setErr(null)), (e: Error) => setErr(e.message));
    const base = `/files/pipeline/runs/${encodeURIComponent(run)}`;
    void getJson<Story>(`${base}/P1_storyline.json`).then(setStory);
    void getJson<LookChar[]>(`${base}/P1_looks.json`).then((x) => setLooks(Array.isArray(x) ? x : null));
    void getJson<{ episodes?: { to?: number } }>(`${base}/P0_brief.json`).then((b) => setEpTotal(b?.episodes?.to ?? 0));
  }, [run]);
  useEffect(() => {
    setD(null);
    setStory(null);
    setLooks(null);
    load();
    const t = window.setInterval(load, 8000);
    return () => window.clearInterval(t);
  }, [load]);
  useLiveEvent((e) => e.type === "stage" || e.type === "tick", load, 2000);

  const canLook = canShowP1(d);
  // 评审没过 / 还在评审的稿不给项目方看：只有“等你看”或已经用了这版，才展示故事线和造型表
  const viewable = canLook || d?.owner_gates?.gates?.P1?.status === "approved";
  const p1Open = d?.owner_gates?.gates?.P1?.status !== "approved" && !!d?.owner_gates?.enabled; // 故事线还没定稿
  useEffect(() => {
    if (canLook) setTab("story");
  }, [canLook, run]);

  const total = Math.max(epTotal, Object.keys(d?.episodes ?? {}).length);
  const eps = useMemo(
    () => Array.from({ length: total }, (_, i) => ({ n: i + 1, ...epState(d?.episodes?.[String(i + 1)]?.verdict, p1Open) })),
    [d, total, p1Open],
  );
  const cur = d?.episode ?? d?.latest_episode ?? 1;

  const post = (path: string, body: unknown, ok: string, key: string) => {
    setBusy(key);
    fetch(`/api/script-autoflow/${encodeURIComponent(run)}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(async (r) => {
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `没成功（${r.status}）`);
        st.notify(ok);
        load();
      })
      .catch((e: Error) => st.notify(e.message, "err"))
      .finally(() => setBusy(null));
  };
  const retry = (n: number) => post("repair", { episode: n, import_mode: d?.import_mode ?? "dry" }, `第 ${n} 集重新开始写`, `ep${n}`);
  const doImport = () => post("import", { episode: cur, import_mode: "live" }, `开始导入第 ${cur} 集`, "import");

  const last = d?.score_trajectory?.[d.score_trajectory.length - 1];
  const score = last && typeof last.sum === "number" ? last.sum : null;

  return (
    <section className="af" aria-label="写作流程">
      <header className="af-head">
        <b className="af-title">写作流程</b>
        <span className="af-sub">提纲 → 故事线 → 造型表 → 各集大纲 · 剧本 · 分镜 → 你确认导入</span>
        <span className="grow" />
        <label className="af-run">
          剧目
          <select value={run} onChange={(e) => setRun(e.target.value)} disabled={!runs?.length}>
            {(runs ?? []).map((o) => (
              <option key={o.id} value={o.id}>
                {o.title}
              </option>
            ))}
          </select>
        </label>
      </header>
      {runs == null ? (
        <p className="af-muted">读取中…</p>
      ) : !runs.length ? (
        <p className="af-muted">还没有在写的剧。在下面填好提纲，点“开始写作”。</p>
      ) : err ? (
        <p className="af-muted">{err}</p>
      ) : !d ? (
        <p className="af-muted">读取中…</p>
      ) : (
        <>
          <p className="af-verdict">
            <i className={`af-dot ${canLook ? "amber" : d.verdict === "imported" || d.verdict === "importable" ? "green" : ""}`} aria-hidden />
            <b>{d.running && !p1Status(d) ? "正在写" : p1Status(d)?.text ?? zhState(d.verdict)}</b>
            <span className="af-muted">
              {" "}
              · 已花 {money(d.usd_total)}
              {score != null ? ` · 分数 ${score}` : ""}
            </span>
          </p>
          <div className="af-tabs" role="tablist">
            {([["story", "① 故事线"], ["looks", "② 造型表"], ["review", "③ 评审分"], ["eps", "④ 各集进度"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
                {l}
                {(k === "story" || k === "looks") && canLook && <i className="af-dot amber" aria-hidden />}
              </button>
            ))}
          </div>

          {tab === "story" &&
            (story && viewable ? (
              <article className="af-read">
                <h3>{story.title || "（未定名）"}</h3>
                {story.premise && <p className="af-prem">{story.premise}</p>}
                {story.world?.setting && (
                  <>
                    <h5>世界</h5>
                    <p>{story.world.setting}</p>
                  </>
                )}
                {!!story.characters?.length && (
                  <>
                    <h5>人物</h5>
                    <ul>
                      {story.characters.map((c) => (
                        <li key={c.name}>
                          <b>{c.name}</b>
                          <span className="af-muted"> {[c.role, c.age ? `${c.age} 岁` : "", c.gender].filter(Boolean).join(" · ")}</span>
                          {c.zh_look && <div className="af-sm">{c.zh_look}</div>}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {!!story.scenes?.length && (
                  <>
                    <h5>场景</h5>
                    <ul>
                      {story.scenes.map((s) => (
                        <li key={s.scene_id}>
                          <b>{s.name}</b>
                          <span className="af-muted"> {s.time_of_day ?? ""}</span>
                          {s.space && <div className="af-sm">{s.space}</div>}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {!!story.episodes?.length && (
                  <>
                    <h5>逐集</h5>
                    <ol>
                      {story.episodes.map((e) => (
                        <li key={e.episode}>
                          <b>第 {e.episode} 集 · {e.title}</b>
                          <div className="af-sm">{e.logline}</div>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </article>
            ) : (
              <p className="af-muted">{`故事线在评审 / 返修中（第 ${p1Round(d)} 轮），过了门槛就在这里给你看`}</p>
            ))}

          {tab === "looks" &&
            (looks && viewable ? (
              <article className="af-read">
                {looks.map((c) => (
                  <div key={c.name}>
                    <h3>{c.name}</h3>
                    {c.marker && <p className="af-muted">{c.marker}</p>}
                    <ul>
                      {(c.looks ?? []).map((l) => (
                        <li key={l.id}>
                          <b>造型 {l.id}</b>
                          <div className="af-sm">{l.zh}</div>
                          {l.use && <div className="af-sm af-muted">{l.use}</div>}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </article>
            ) : (
              <p className="af-muted">造型表在评审，过了门槛后给你看。</p>
            ))}

          {(tab === "story" || tab === "looks") && <P1Gate run={run} d={d} hasStory={!!story && viewable} onChanged={load} />}
          {tab === "review" && <ReviewBlock d={d} />}

          {tab === "eps" && (
            <div className="af-block">
              {eps.length > 1 && eps.every((e) => e.s === eps[0].s && !e.stuck) ? (
                // 全部集状态相同：合成一行，不重复 10 遍
                <p className="af-same">
                  <i className={`af-dot ${eps[0].s === "look" ? "amber" : eps[0].s === "done" ? "green" : ""}`} aria-hidden />{" "}
                  {eps.length} 集{{ idle: "都还没开始（等故事线定稿）", writing: "都在写作中", look: "都等你看", done: "都完成了" }[eps[0].s]}
                </p>
              ) : (
              <ul className="af-eps">
                {eps.map((e) => (
                  <li key={e.n} className={`s-${e.s}`}>
                    <b>第 {e.n} 集</b>
                    <span className="af-es">
                      <i className={`af-dot ${e.s === "look" ? "amber" : e.s === "done" ? "green" : ""}`} aria-hidden /> {EP_WORD[e.s]}
                    </span>
                    {e.stuck ? (
                      <button type="button" className="v3-btn sm" disabled={!!busy || !!d.running} onClick={() => retry(e.n)}>
                        重试
                      </button>
                    ) : e.s === "look" && canLook ? (
                      <button type="button" className="v3-btn sm" onClick={() => setTab("story")}>
                        去看
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
              )}
              {d.verdict === "importable" && (
                <div className="af-foot">
                  <button type="button" className="v3-btn primary" disabled={!!busy || !!d.running} onClick={doImport} title="导入这一集（你确认的唯一一步）">
                    导入第 {cur} 集
                  </button>
                </div>
              )}
            </div>
          )}

          <button type="button" className="af-dtoggle" onClick={() => setShowDetail((x) => !x)}>
            {showDetail ? "收起详情 ▴" : "详情 ▾"}
          </button>
          {showDetail && (
            <div className="af-block">
              <ul className="af-stages">
                {(d.stages ?? []).map((s) => {
                  const det = Array.isArray(s.detail) ? s.detail : s.detail ? [s.detail] : [];
                  return (
                    <li key={s.id}>
                      <div className="af-row2">
                        <span className="af-name">{STAGE_NAME[s.id] ?? s.name}</span>
                        <span className="af-who">{DECIDER[s.decider ?? ""] ?? ""}</span>
                        <span className="af-st">{s.fails ? `${s.fails} 项没过` : zhState(s.status)}</span>
                        <span className="af-usd">{s.usd != null ? money(s.usd) : ""}</span>
                      </div>
                      {det.length > 0 && (
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
          )}
        </>
      )}
    </section>
  );
}
