// NAVFLOW-F 11-03（项目方 L-146）：各集进度矩阵——每行一集、每列一步（①剧本 ②资产 ③分镜 ④出图 ⑤视频 ⑥成片）。
// W5 UIUX 11-03（L-155）改版：每格 = 状态色 + 一句大白话 + 负责方；点格子在下面展开详情（卡点列表 + “打开这一页”）。
// 状态只从后端 GET /api/sop/stepbar 取（sop_gate 判定 + report_issue 未关卡点），前端不自己猜；读不到就写明读不到。
// 同文件 NowPanel：首页 30 秒回答四句话——现在哪一集在哪一步？系统在做什么？卡在哪、谁负责？需要我做什么？
import { useState } from "react";
import { useStudio } from "../store";
import type { PipeStepId } from "./NavTabs.helpers";
import { useFramesCounts, useVideosSummary } from "./NavTabs.helpers";
import { queueFailText, useOwnerQueue } from "./ownerQueue";
import { FALLBACK_TEXT, STATE_GLYPH, STATE_WORD, STEP_IDS, STEP_NUM, stepHref, useStepbar, type CellState, type Stepbar } from "./stepbar";
import "./pipeline.css";
import "./overview_now.css";

const labelOf = (v: Stepbar, s: PipeStepId) => `${STEP_NUM[STEP_IDS.indexOf(s)]} ${v.steps.find((x) => x.id === s)?.label ?? s}`;

/** A5 P1-1：读不到卡点时（旧接口 / 卡点登记读不到）必须醒目说出来，不许让页面看起来像“没卡住”。
 *  顶栏步骤条、首页“现在”、进度表顶部共用这一条 */
export function StepbarBanner({ v, slim }: { v: Stepbar | null; slim?: boolean }) {
  if (!v || (!v.fallback && !v.issues_error)) return null;
  const msg = v.fallback ? FALLBACK_TEXT : `卡点读不到：${v.issues_error}`;
  return (
    <div className={`sb-banner${slim ? " slim" : ""}`} role="alert" data-fallback={v.fallback ? "1" : "0"}>
      ⚠ {msg}
      {slim ? null : <small>下面只有进度计数，“卡在哪 · 谁负责”现在不可信；后台更新后自动恢复。</small>}
    </div>
  );
}

/** 首页“现在”：四个问题四句话（每句都能点过去） */
export function NowPanel() {
  const { v, err } = useStepbar();
  const { q, err: qerr } = useOwnerQueue();
  const fc = useFramesCounts();
  const vs = useVideosSummary();
  const st = useStudio();
  const qfail = queueFailText(q, qerr);
  const go = (ep: number, s: PipeStepId) => {
    st.gotoEpisode(ep);
    location.hash = stepHref(s, ep, v?.run);
  };
  const running = (fc?.gen.running ?? 0) + (vs?.rendering ?? 0);
  const queued = (fc?.gen.queued ?? 0) + (vs?.queued ?? 0);
  const f = v?.now.focus;
  return (
    <>
    <StepbarBanner v={v} />
    <section className="now" aria-label="现在的情况">
      <div className="now-q">
        <h3>现在在哪</h3>
        {!v ? (
          <p className="now-muted">{err ? `进度暂时读不到（${err}）` : "正在读…"}</p>
        ) : f ? (
          <p>
            《{v.title}》<button type="button" className="now-link" onClick={() => go(f.episode, f.step)}>第 {f.episode} 集 · {labelOf(v, f.step)}</button>：{f.plain}
          </p>
        ) : (
          <p>《{v.title}》{v.steps[v.steps.length - 1].done === v.episodes_total ? "全部集都完成了" : "还没有哪一集开工"}（共 {v.episodes_total} 集）</p>
        )}
      </div>
      <div className="now-q">
        <h3>系统在做什么</h3>
        {v && v.now.doing.length ? (
          <ul>
            {v.now.doing.slice(0, 3).map((d) => (
              <li key={`${d.episode}-${d.step}`}>
                <button type="button" className="now-link" onClick={() => go(d.episode, d.step)}>第 {d.episode} 集 {labelOf(v, d.step)}</button>：{d.plain}
                {d.owner ? <small> · {d.owner}</small> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p>{v ? (v.now.blocked.length ? "没有在往前走的步骤——都在等下面的卡点解决。" : "没有在跑的步骤。") : "…"}</p>
        )}
        {running + queued > 0 ? (
          <p className="now-muted">机器上：正在出 {running} 个（图 / 视频），排队 {queued} 个。</p>
        ) : fc || vs ? (
          <p className="now-muted">机器上现在没有在出图或视频。</p>
        ) : null}
      </div>
      <div className={`now-q${v?.now.blocked.length || v?.fallback || v?.issues_error ? " warn" : ""}`}>
        <h3>卡在哪 · 谁负责</h3>
        {v && (v.fallback || v.issues_error) ? <p className="now-unknown">⚠ {v.fallback ? FALLBACK_TEXT : `卡点读不到：${v.issues_error}`}。</p> : null}
        {v && v.now.blocked.length ? (
          <ul>
            {v.now.blocked.slice(0, 3).map((b) => (
              <li key={`${b.episode}-${b.step}`}>
                <button type="button" className="now-link" onClick={() => go(b.episode, b.step)}>第 {b.episode} 集 {labelOf(v, b.step)}</button>：{b.block || b.plain}
                {b.owner || b.n_issues > 1 ? <small>{b.owner ? ` · 负责：${b.owner}` : ""}{b.n_issues > 1 ? ` · 共 ${b.n_issues} 条` : ""}</small> : null}
              </li>
            ))}
            {v.now.blocked.length > 3 ? <li className="now-muted">还有 {v.now.blocked.length - 3} 处，见下面的进度表</li> : null}
          </ul>
        ) : v && (v.fallback || v.issues_error) ? null : (
          <p>{v ? "登记的卡点里没有挡住正在做的步骤。" : "…"}</p>
        )}
      </div>
      <div className={`now-q${q && q.count ? " ask" : ""}`}>
        <h3>需要你做什么</h3>
        {qfail ? (
          <p className="now-muted">{qfail}</p>
        ) : !q ? (
          <p>…</p>
        ) : q.count ? (
          <>
            <ul>
              {q.items.slice(0, 3).map((it) => (
                <li key={it.id}>{it.title}</li>
              ))}
            </ul>
            <a className="now-cta" href="#/queue">
              去待办处理 {q.count} 件 ›
            </a>
          </>
        ) : (
          <p>现在没有要你做的事，系统自己在跑。有新的会出现在顶部“待办”。</p>
        )}
      </div>
    </section>
    </>
  );
}

export function PipelineMatrix({ compact }: { compact?: boolean }) {
  const { v, err, reload } = useStepbar();
  const st = useStudio();
  const [open, setOpen] = useState<{ ep: number; step: PipeStepId } | null>(null);
  if (!v) {
    return (
      <section className="pm" aria-label="各集进度">
        <p className="pm-note">
          {err ? (
            <>
              各集进度暂时读不到：{err}{" "}
              <button type="button" className="pm-link" onClick={reload}>
                再试
              </button>
            </>
          ) : (
            "正在读各集进度…"
          )}
        </p>
      </section>
    );
  }
  const go = (step: PipeStepId, ep: number) => {
    st.gotoEpisode(ep);
    location.hash = stepHref(step, ep, v.run);
  };
  const oe = open ? v.episodes.find((e) => e.episode === open.ep) : null;
  const oc = oe && open ? oe.cells[open.step] : null;
  return (
    <section className={`pm pm2${compact ? " compact" : ""}`} aria-label="各集进度">
      <StepbarBanner v={v} slim={compact} />
      <table className="pm-table">
        <thead>
          <tr>
            <th className="pm-ep">集</th>
            {v.steps.map((s, i) => (
              <th key={s.id} title={`共 ${v.episodes_total} 集：完成 ${s.done} · 进行中 ${s.doing} · 卡住 ${s.blocked} · 未开始 ${s.todo}`}>
                <span>
                  {STEP_NUM[i]} {s.label}
                </span>
                <small>
                  完成 {s.done}
                  {s.doing ? ` · 进行 ${s.doing}` : ""}
                  {s.blocked ? ` · 卡住 ${s.blocked}` : ""}
                </small>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {v.episodes.map((e) => (
            <tr key={e.episode} className={e.episode === st.epNum ? "cur" : ""}>
              <th className="pm-ep" scope="row" title={`第 ${e.episode} 集：${e.plain || e.stage}`}>
                {e.episode}
              </th>
              {STEP_IDS.map((s) => {
                const c = e.cells[s];
                const state: CellState = c?.state ?? "todo";
                const on = open?.ep === e.episode && open.step === s;
                return (
                  <td key={s}>
                    <button
                      type="button"
                      className={`pm-cell2 s-${state}${c?.ahead ? " ahead" : ""}${on ? " on" : ""}`}
                      onClick={() => {
                        setOpen(on ? null : { ep: e.episode, step: s });
                        if (!on) window.setTimeout(() => document.querySelector(".pm-detail")?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 50);
                      }}
                      title={`第 ${e.episode} 集 · ${labelOf(v, s)}：${STATE_WORD[state]}\n${c?.plain ?? ""}${c?.block ? `\n${c.block}` : ""}${c?.owner ? `\n负责：${c.owner}` : ""}\n点击看详情`}
                      aria-label={`第 ${e.episode} 集 ${labelOf(v, s)} ${STATE_WORD[state]}`}
                      aria-expanded={on}
                    >
                      <span className="pm-st">
                        <i aria-hidden>{STATE_GLYPH[state]}</i> {STATE_WORD[state]}
                      </span>
                      {state !== "todo" ? <span className="pm-txt">{c?.plain}</span> : null}
                      {c?.block ? <span className="pm-blk">⚠ {c.block}</span> : null}
                      {c?.owner ? <small className="pm-own">{c.owner}</small> : null}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {open && oe && oc ? (
        <div className={`pm-detail s-${oc.state}`} role="region" aria-label="格子详情">
          <div className="pm-detail-h">
            <b>
              第 {open.ep} 集 · {labelOf(v, open.step)}：{STATE_WORD[oc.state]}
            </b>
            <button type="button" className="pm-x" onClick={() => setOpen(null)} aria-label="关闭详情">
              ×
            </button>
          </div>
          <p>{oc.plain}</p>
          {oc.owner ? <p className="pm-own">负责：{oc.owner}</p> : null}
          {oc.stale ? <p className="now-muted">这一步已完成；还有 {oc.stale} 条旧卡点单没关（不再挡路，总调度会关掉）。</p> : null}
          {oc.issues.length ? (
            <>
              <h4>登记的卡点（{oc.issues.length + oc.issues_more} 条）</h4>
              <ul>
                {oc.issues.map((x) => (
                  <li key={x.id}>
                    <i className={x.blocking ? "blk" : "info"}>{x.blocking ? "挡路" : "提醒"}</i> {x.text} <small>· {x.owner}{x.at ? ` · ${x.at.slice(5, 16)}` : ""}</small>
                  </li>
                ))}
                {oc.issues_more ? <li className="now-muted">还有 {oc.issues_more} 条，总调度在跟</li> : null}
              </ul>
            </>
          ) : null}
          <div className="pm-detail-a">
            <button type="button" className="v3-btn primary" onClick={() => go(open.step, open.ep)}>
              打开第 {open.ep} 集的{v.steps.find((x) => x.id === open.step)?.label}页
            </button>
          </div>
        </div>
      ) : null}
      <p className="pm-legend" aria-hidden>
        <span>
          <i className="s-done" /> ✓ 完成
        </span>
        <span>
          <i className="s-doing" /> ● 进行中
        </span>
        <span>
          <i className="s-blocked" /> ⚠ 卡住
        </span>
        <span>
          <i className="s-todo" /> · 未开始
        </span>
        <span className="pm-src">{v.fallback ? "状态只来自后台的阶段检查（卡点登记读不到），每 30 秒刷新；点格子看详情" : "状态来自后台的阶段检查和卡点登记（最新的在前），每 30 秒刷新；点格子看详情"}</span>
      </p>
    </section>
  );
}
