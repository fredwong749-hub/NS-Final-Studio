// fredw-92/UXF5（审查 N8 / 流程 c）：整集出片跑完以后，集头一直有一个“上次整集出片”入口——
// 点开看这次跑的结果：模式、阶段、起止时间、每镜每步的结果（哪张卡、第几版、是不是自动测试定稿）、失败原因、时间线。
// 数据：GET /api/episodes/{n}/produce（后端每集落盘最近一次，API 重启也在）；本机另记以前几次的摘要（localStorage，只是方便回看）。
// 只读：这里不提交、不取消、不定稿。
import { useEffect, useState } from "react";
import { Pop } from "./widgets";
import { type ProduceStage, type ProduceView } from "./EpisodeProduce";
import { useProduceView } from "./EpisodeProduce.helpers";
import { laneName, useLanes } from "./edit/lanes";
import { errSummary } from "../components/Drawer.helpers";
import { AUTO_SHORT, AUTO_TIP } from "./words";

type Stage = "first" | "last" | "video";
type Ev = { t: string; shot: string | null; stage: Stage | null; ev: string; step?: string; gpu?: number | string; take?: number; wall_s?: number; error?: string; reason?: string; shots?: number; mode?: string };
type Run = ProduceView & {
  created_at?: string;
  finished_at?: string | null;
  updated_at?: string;
  by?: string | null;
  events?: Ev[];
};
type Past = { id: string; state: string; mode?: string; stages?: string[]; created_at?: string; finished_at?: string | null; counts?: Record<string, number>; shots: number };

const STAGE_LABEL: Record<Stage, string> = { first: "首帧", last: "尾帧", video: "视频" };
const STATE_LABEL: Record<string, string> = {
  pending: "没轮到",
  ready: "待派卡",
  queued: "排队",
  running: "生成中",
  review: "等你定稿",
  done: "完成",
  skipped: "已是最新，跳过",
  failed: "失败",
  blocked: "卡住",
  waiting: "等待",
  cancelled: "已取消",
};
const RUN_STATE: Record<string, string> = { running: "进行中", waiting: "等你定稿 / 等卡", done: "已完成", cancelled: "已取消" };
/** fredw-92/UXF5（审查 R3 / #5）：被 API 重启打断的不算真失败（可重试） */
const isIntr = (x: { error?: string | null; reason?: string | null }) => /API 重启/.test(`${x.error ?? ""} ${x.reason ?? ""}`);
/** 一次整集出片的结局：有真失败 → 红“结束 · 失败 N”；只有中断 → 橙“结束 · 中断 N”；全成功才绿“已完成” */
function runOutcome(v: Run): { text: string; cls: string } {
  if (v.state !== "done") return { text: RUN_STATE[v.state] ?? v.state, cls: v.state };
  const fails = v.failures ?? [];
  const intr = fails.filter(isIntr).length;
  const failed = Math.max(0, (v.counts?.failed ?? fails.length) - intr);
  if (failed) return { text: `结束 · 失败 ${failed}${intr ? ` · 中断 ${intr}` : ""}`, cls: "failed" };
  if (intr) return { text: `结束 · 中断 ${intr}`, cls: "interrupted" };
  const left = Object.entries(v.counts ?? {}).filter(([k, n]) => n && !["done", "skipped"].includes(k)).reduce((a, [, n]) => a + n, 0);
  return left ? { text: `结束 · 没跑完 ${left}`, cls: "interrupted" } : { text: "已完成", cls: "done" };
}
const EV_LABEL: Record<string, string> = { start: "开始", submit: "提交", done: "完成", fail: "失败", failed: "失败", retry: "重试", finish: "全部跑完", cancel: "取消", review: "等你定稿", lock: "定稿", skip: "跳过", wait: "等待" };

const hm = (t?: string | null) => (t ? t.replace("T", " ").slice(5, 16) : "—");
const dur = (a?: string | null, b?: string | null) => {
  if (!a || !b) return "";
  const s = (Date.parse(b) - Date.parse(a)) / 1000;
  if (!(s > 0)) return "";
  return s >= 3600 ? `${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分` : `${Math.max(1, Math.round(s / 60))} 分钟`;
};
const short = (id?: string | null) => (id ? id.split("-")[1] ?? id : "");
const stepsOf = (v: Run) => v.shots.reduce((n, s) => n + Object.keys(s.stages).length, 0);
const doneOf = (c?: Record<string, number>) => (c?.done ?? 0) + (c?.skipped ?? 0);

// ---------------------------------------------------------------- 本机记的以前几次（只存摘要）
const KEY = (ep: number) => `ns.v3.produceHistory.ep${ep}`;
function readPast(ep: number): Past[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY(ep)) ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}
function remember(ep: number, v: Run) {
  if (!v.id || v.state === "none") return;
  try {
    const p = readPast(ep).filter((x) => x.id !== v.id);
    const me: Past = { id: v.id, state: v.state, mode: v.mode, stages: v.stages, created_at: v.created_at, finished_at: v.finished_at, counts: v.counts, shots: v.shots.length };
    localStorage.setItem(KEY(ep), JSON.stringify([me, ...p].slice(0, 10)));
  } catch {
    /* 隐私模式 */
  }
}

/** 读本集最近一次整集出片（集头先看 EpisodeProduce 的共享轮询，没有再自己读一次） */
function useRun(ep: number): Run | null {
  const shared = useProduceView(ep) as Run | undefined;
  const [own, setOwn] = useState<Run | null>(null);
  const hasShared = !!shared;
  useEffect(() => {
    let alive = true;
    setOwn(null);
    if (hasShared) return; // UIDEBUG #1：共享轮询已有值就不再自己读（ep02 加载时曾并发 4 次）
    fetch(`/api/episodes/${ep}/produce`)
      .then((r) => (r.ok ? r.json() : null))
      .then((v: Run | null) => alive && v && setOwn(v))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [ep, hasShared]);
  const v = shared && (shared.events || !own) ? shared : own ?? shared ?? null;
  useEffect(() => {
    if (v && (v.state === "done" || v.state === "cancelled")) remember(ep, v);
  }, [ep, v?.id, v?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  return v && v.state !== "none" ? v : null;
}

const modeText = (m?: string) => (m === "auto_lock" ? "自动测试定稿" : m === "review" ? "每步等我定稿" : m ?? "");

function StageCell({ st, x }: { st: Stage; x?: ProduceStage }) {
  if (!x) return <td className="ph-na">—</td>;
  const auto = x.locked_by === "auto";
  const where = x.gpu != null ? laneName(x.gpu) : x.lane ?? "";
  return (
    <td className={`ph-st ${x.state}`} title={`${STAGE_LABEL[st]}：${STATE_LABEL[x.state] ?? x.state}${where ? ` · ${where}` : ""}${x.reason ? `\n${x.reason}` : ""}${x.error ? `\n${x.error}` : ""}`}>
      <i className={`ph-dot ${x.state === "failed" && isIntr(x) ? "interrupted" : x.state}`} />
      {x.state === "failed" && isIntr(x) ? "中断" : STATE_LABEL[x.state] ?? x.state}
      {x.take != null && <small> #{x.take}</small>}
      {auto && <em className="ph-auto" title={AUTO_TIP}>{AUTO_SHORT}</em>}
    </td>
  );
}

function Body({ ep, v }: { ep: number; v: Run }) {
  useLanes(); // 卡名与“用卡”下拉同一个来源（laneName）
  const stages = (v.stages ?? ["first", "last", "video"]) as Stage[];
  const total = stepsOf(v);
  const evs = [...(v.events ?? [])].reverse();
  const past = readPast(ep).filter((p) => p.id !== v.id);
  const autoN = v.shots.reduce((n, s) => n + Object.values(s.stages).filter((x) => x?.locked_by === "auto").length, 0);
  return (
    <div className="ph" onClick={(e) => e.stopPropagation()}>
      <header className="ph-head">
        <b>第 {ep} 集 · 最近一次整集出片</b>
        <span className={`ph-badge ${runOutcome(v).cls}`}>{runOutcome(v).text}</span>
      </header>
      <dl className="ph-sum">
        <dt>模式</dt>
        <dd>{modeText(v.mode)}{v.mode === "auto_lock" && <small className="ph-warn">（自动定稿的版本还要你复审）</small>}</dd>
        <dt>出哪几步</dt>
        <dd>{stages.map((s) => STAGE_LABEL[s] ?? s).join(" → ")} · {v.shots.length} 镜 · {total} 步</dd>
        <dt>时间</dt>
        <dd>
          {hm(v.created_at)} 开始 · {v.finished_at ? `${hm(v.finished_at)} 结束（用时 ${dur(v.created_at, v.finished_at)}）` : `还没结束（最后更新 ${hm(v.updated_at)}）`}
        </dd>
        <dt>结果</dt>
        <dd>
          完成 {doneOf(v.counts)}/{total}
          {Object.entries(v.counts ?? {})
            .filter(([k, n]) => n && k !== "done" && k !== "skipped")
            .map(([k, n]) => ` · ${STATE_LABEL[k] ?? k} ${n}`)
            .join("")}
          {v.counts?.skipped ? ` · 其中 ${v.counts.skipped} 步已是最新、跳过` : ""}
          {autoN ? <small className="ph-warn"> · {autoN} 步是自动测试定稿</small> : null}
        </dd>
        {v.by && (
          <>
            <dt>发起</dt>
            <dd>{/^fredw|^gpu|agent/i.test(v.by) ? "系统测试" : v.by}</dd>
          </>
        )}
      </dl>
      {!!v.failures?.length && (
        <div className="ph-fail">
          <b>没出成 / 卡住（{v.failures.length}）</b>
          <ul>
            {v.failures.map((f, i) => (
              <li key={i}>
                <span title={f.error || f.reason || undefined}>
                  {short(f.shot_id)} {STAGE_LABEL[f.stage as Stage] ?? f.stage}：{isIntr(f) ? "API 重启时中断（不是画面问题），可重试" : errSummary(f.reason || f.error) || STATE_LABEL[f.state] || f.state}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="ph-tblwrap">
        <table className="ph-tbl">
          <thead>
            <tr>
              <th>镜头</th>
              {stages.map((s) => (
                <th key={s}>{STAGE_LABEL[s] ?? s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {v.shots.map((s) => (
              <tr key={s.shot_id}>
                <td className="ph-id">
                  <a href={`#${s.shot_id}`} title="回到这一镜">
                    {short(s.shot_id)}
                  </a>
                </td>
                {stages.map((st) => (
                  <StageCell key={st} st={st} x={s.stages[st]} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {evs.length > 0 && (
        <details className="ph-evs">
          <summary>时间线（最近 {evs.length} 条）</summary>
          <ol>
            {evs.map((e, i) => (
              <li key={i}>
                <time>{hm(e.t).slice(6)}</time> {EV_LABEL[e.ev] ?? e.ev}
                {e.shot ? ` ${short(e.shot)}` : ""}
                {e.stage ? ` ${STAGE_LABEL[e.stage] ?? e.stage}` : ""}
                {e.step === "final" ? "（定稿档）" : ""}
                {e.gpu != null ? ` · ${laneName(e.gpu)}` : ""}
                {e.take != null ? ` · #${e.take}` : ""}
                {e.wall_s ? ` · 用时 ${Math.round(e.wall_s / 60)} 分钟` : ""}
                {e.ev === "start" && e.shots ? ` · ${e.shots} 镜` : ""}
                {e.error || e.reason ? ` · ${errSummary(e.error || e.reason)}` : ""}
              </li>
            ))}
          </ol>
        </details>
      )}
      {past.length > 0 && (
        <details className="ph-evs">
          <summary>以前几次（本机记录 {past.length}）</summary>
          <ol>
            {past.map((p) => (
              <li key={p.id}>
                {hm(p.created_at)} · {modeText(p.mode)} · {p.state === "done" ? "结束" : RUN_STATE[p.state] ?? p.state} · 完成 {doneOf(p.counts)} 步{p.counts?.failed ? ` · 失败 ${p.counts.failed}` : ""} · {p.shots} 镜
              </li>
            ))}
          </ol>
        </details>
      )}
      <p className="ph-note">后端每集保存最近一次的完整记录（API 重启后也在）；更早的只在这台电脑上记了摘要。</p>
    </div>
  );
}

/** 集头入口：本集跑过整集出片就一直在（跑完也在） */
let replacedAt: Promise<string | null> | null = null;
/** 最近一次换剧本（整份替换导入）的时间：换剧本之前的整集出片记录属于旧剧本，不再显示 */
function useReplacedAt(): string | null | undefined {
  const [v, setV] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    replacedAt ??= fetch("/api/script/replaced-at").then((r) => (r.ok ? r.json() : { at: null })).then((d: { at: string | null }) => d.at, () => null);
    void replacedAt.then(setV);
  }, []);
  return v;
}

export function ProduceHistoryChip({ ep }: { ep: number }) {
  const v = useRun(ep);
  const since = useReplacedAt();
  if (!v || since === undefined) return null;
  if (since && v.created_at && v.created_at < since) return null; // UIRSI：旧剧本的整集出片，不显示
  const total = stepsOf(v);
  const live = v.state === "running" || v.state === "waiting";
  const out = runOutcome(v);
  const label = live ? `整集出片 ${doneOf(v.counts)}/${total}` : `上次整集出片 · 完成 ${doneOf(v.counts)}/${total}${out.cls === "done" ? "" : ` · ${out.text.replace(/^结束 · /, "")}`}`;
  return (
    <Pop label={label} btnClass={`sb-chip ph-chip ${out.cls}`} title={`第 ${ep} 集最近一次整集出片：${hm(v.created_at)} 开始${v.finished_at ? `，${hm(v.finished_at)} 结束` : ""}\n点开看每镜结果和时间线`}>
      {() => <Body ep={ep} v={v} />}
    </Pop>
  );
}
